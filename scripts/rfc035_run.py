"""RFC-035 builder - Strategic Profitability Plan V2 & Multi-Asset Opportunity Admission.

Emits every §79/§80 artifact from the deterministic rules in
``trading_bot.research.strategic_profitability_v2``:

    reports/profitability-v2/*.md|json   (10 artifact pairs)
    reports/RFC035_FINAL_REPORT.md|json
    docs/research/STRATEGIC_PROFITABILITY_PLAN_V2.md|json   (tracked)

No strategy is implemented, backtested or promoted.  The economic marker stays at
all-execution-zeros; only the *plan* and its admission decision change.
"""

from __future__ import annotations

import dataclasses
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from trading_bot.research import strategic_profitability_v2 as SP

REPO = Path(__file__).resolve().parents[1]
OUT = REPO / "reports" / "profitability-v2"
REPORTS = REPO / "reports"
DOCS = REPO / "docs" / "research"


def _git_head() -> str:
    import subprocess

    try:
        return subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
    except Exception:  # pragma: no cover - git always present here
        return "UNKNOWN"


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _jsonable(obj: Any) -> Any:
    if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
        return {f.name: _jsonable(getattr(obj, f.name)) for f in dataclasses.fields(obj)}
    if isinstance(obj, dict):
        return {k: _jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_jsonable(v) for v in obj]
    return obj


def _md_table(headers: list[str], rows: list[list[str]]) -> str:
    out = ["| " + " | ".join(headers) + " |", "| " + " | ".join(["---"] * len(headers)) + " |"]
    for r in rows:
        out.append("| " + " | ".join(str(c) for c in r) + " |")
    return "\n".join(out)


def _artifact_pair(name: str, json_payload: Any, md_body: str) -> None:
    _write_json(OUT / f"{name}.json", json_payload)
    (OUT / f"{name}.md").write_text(md_body.rstrip() + "\n", encoding="utf-8")


def _family_row(f: SP.StrategyFamily) -> list[str]:
    return [
        f.family_id,
        f.required_group,
        f.asset_class,
        f.horizon,
        f.post_publication,
        str(f.headroom_ratio) if f.headroom_ratio is not None else "N/A",
        f.headroom_class,
        f.data_cost_class,
        f.research_cost,
        f.time_to_validation,
    ]


def build() -> dict[str, Any]:
    OUT.mkdir(parents=True, exist_ok=True)
    now = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    head = _git_head()
    gate = SP.evaluate_reentry_gate()
    top5 = SP.select_top5()
    finalists = SP.select_finalists()
    authorized = SP.authorize_reproductions()
    summary = SP.plan_summary()

    header = (
        "# RFC-035 STRATEGIC PROFITABILITY PLAN V2\n\n"
        f"as_of_commit = {head}\ngenerated_at = {now}\n"
        f"branch = main\nphase_1_status = CLOSED\n"
        f"phase_2_status = {SP.profitability_research_status(gate)}\n"
        f"g_reentry = {gate.status_value}\n"
    )

    # ---- RFC035_PLAN ---------------------------------------------------- #
    plan_rows = [
        [
            f.family_id,
            f.name,
            str(f.scores["evidence_strength"]),
            str(f.scores["economic_headroom"]),
            str(f.scores["tradability"]),
            str(f.scores["data_feasibility"]),
            SP.decision_for(f, gate),
        ]
        for f in SP.STRATEGY_FAMILIES
    ]
    plan_md = (
        header + "\n## Objective\n"
        "Find the most promising path to the first EXECUTABLE, VALIDATED, NET POSITIVE\n"
        "EDGE before writing any strategy code (EDGE FIRST, FREQUENCY SECOND).\n\n"
        "## Scope\n"
        "ADMISSION_REVIEW, not ALPHA_IMPLEMENTATION. RFC-035 does not break\n"
        "NEXT_ALPHA_RFC_ALLOWED=NO unless G_REENTRY passes.\n\n"
        "## Families reviewed\n"
        + _md_table(
            ["family", "name", "evidence", "economics", "tradability", "data", "decision"],
            plan_rows,
        )
        + "\n\n## Hard caps\n"
        f"- MAX_TOP5 = {SP.MAX_TOP5} -> {[f.family_id for f in top5]}\n"
        f"- MAX_FINALISTS = {SP.MAX_FINALISTS} -> {[f.family_id for f in finalists]}\n"
        f"- MAX_AUTHORIZED = {SP.MAX_AUTHORIZED} -> {[f.family_id for f in authorized]}\n"
        f"- MAX_IMPLEMENTED_STRATEGIES = {SP.MAX_IMPLEMENTED_STRATEGIES}, "
        f"MAX_PARAMETER_VARIANTS = {SP.MAX_PARAMETER_VARIANTS}\n"
    )
    _artifact_pair("RFC035_PLAN", {**summary, "families": _jsonable(SP.STRATEGY_FAMILIES)}, plan_md)

    # ---- SOURCE_REGISTRY ------------------------------------------------ #
    src_rows = [
        [
            s.source_id,
            s.source_type,
            str(s.year),
            s.strategy_family,
            s.evidence_role,
            s.reliability,
            "yes" if s.is_strong else "no",
        ]
        for s in SP.SOURCES
    ]
    src_md = (
        header
        + "\n## Source authority ladder (§16)\n"
        + "\n".join(f"{i + 1}. {t}" for i, t in enumerate(SP.SOURCE_AUTHORITY_LADDER))
        + "\n\nLevels 6-8 clarify implementation but are not economic evidence alone.\n\n"
        "## Registry (§17)\n"
        + _md_table(["id", "type", "year", "family", "role", "reliability", "strong?"], src_rows)
        + "\n\n"
        + "\n".join(
            f"- **{s.source_id}** ({s.authors}, {s.year}) {s.title}. {s.url} "
            f"retrieved {s.retrieval_date}. Role={s.evidence_role}."
            for s in SP.SOURCES
        )
    )
    _artifact_pair(
        "SOURCE_REGISTRY",
        {
            "authority_ladder": list(SP.SOURCE_AUTHORITY_LADDER),
            "strong_types": list(SP.STRONG_SOURCE_TYPES),
            "sources": _jsonable(SP.SOURCES),
        },
        src_md,
    )

    # ---- STRATEGY_UNIVERSE --------------------------------------------- #
    uni_rows = [_family_row(f) for f in SP.STRATEGY_FAMILIES]
    uni_md = (
        header
        + "\n## Reviewed universe (§6-§9, 10-15 families, no variants)\n"
        + _md_table(
            [
                "family",
                "§9",
                "asset class",
                "horizon",
                "post-pub",
                "headroom",
                "band",
                "data cost",
                "research",
                "ttv",
            ],
            uni_rows,
        )
        + "\n\n"
        + "\n".join(
            f"- **{f.family_id}**: {f.name}. Mechanism: {f.mechanism}. "
            f"Early kill: {f.early_kill_condition}"
            for f in SP.STRATEGY_FAMILIES
        )
    )
    _artifact_pair("STRATEGY_UNIVERSE", {"families": _jsonable(SP.STRATEGY_FAMILIES)}, uni_md)

    # ---- STRATEGY_SCORECARD -------------------------------------------- #
    sc_rows = [
        [
            f.family_id,
            *[str(f.scores[d]) for d in SP.SCORECARD_DIMENSIONS],
            ",".join(f.weak_critical_dimensions) or "-",
        ]
        for f in SP.STRATEGY_FAMILIES
    ]
    sc_md = (
        header + "\n## Scorecard (§38-§41)\n"
        "Priority: evidence > economics > tradability > data. Critical dims "
        "(evidence, data, tradability) <= 1 block finalist status (§39).\n\n"
        + _md_table(["family", *SP.SCORECARD_DIMENSIONS, "weak critical"], sc_rows)
    )
    _artifact_pair(
        "STRATEGY_SCORECARD",
        {
            "dimensions": list(SP.SCORECARD_DIMENSIONS),
            "critical_dimensions": list(SP.CRITICAL_DIMENSIONS),
            "priority_order": list(SP.PRIORITY_ORDER),
            "families": [
                {"family_id": f.family_id, "scores": f.scores} for f in SP.STRATEGY_FAMILIES
            ],
        },
        sc_md,
    )

    # ---- TOP5_REVIEW ---------------------------------------------------- #
    top5_md = (
        header
        + f"\n## Top-5 shortlist (§42-§46): {[f.family_id for f in top5]}\n\n"
        + "\n\n".join(
            f"### {i + 1}. {f.family_id} - {f.name}\n"
            f"- Evidence sources: {', '.join(f.source_ids)}\n"
            f"- Supporting: {f.mechanism}\n"
            f"- Counter-evidence: {f.counter_evidence}\n"
            f"- Uncertainties: {f.uncertainties}\n"
            f"- Mechanism: {f.mechanism}\n"
            f"- Fidelity potential: {f.fidelity}; proxy: {f.proxy}\n"
            f"- Implementation concept (not coded): {f.implementation_concept}\n"
            f"- Early kill condition: {f.early_kill_condition}"
            for i, f in enumerate(top5)
        )
    )
    _artifact_pair("TOP5_REVIEW", {"top5": [f.family_id for f in top5]}, top5_md)

    # ---- DATA_FEASIBILITY_MATRIX --------------------------------------- #
    data_rows = [
        [
            f.family_id,
            str(f.scores["data_feasibility"]),
            f.data_cost_class,
            f.data_notes,
        ]
        for f in SP.STRATEGY_FAMILIES
    ]
    data_md = (
        header
        + "\n## Data feasibility (§27-§29, §56-§59)\n"
        + _md_table(["family", "score", "cost class", "notes"], data_rows)
        + "\n\nPaid/expensive data is recorded, never purchased (§29)."
    )
    _artifact_pair(
        "DATA_FEASIBILITY_MATRIX",
        {
            "families": [
                {
                    "family_id": f.family_id,
                    "data_feasibility": f.scores["data_feasibility"],
                    "data_cost_class": f.data_cost_class,
                    "notes": f.data_notes,
                }
                for f in SP.STRATEGY_FAMILIES
            ]
        },
        data_md,
    )

    # ---- ECONOMIC_HEADROOM_MATRIX -------------------------------------- #
    hr_rows = [
        [
            f.family_id,
            f.headroom_class,
            str(f.headroom_ratio) if f.headroom_ratio is not None else "N/A",
            "yes" if f.net_evidence_exception else "no",
            f.turnover,
        ]
        for f in SP.STRATEGY_FAMILIES
    ]
    hr_md = (
        header + "\n## Economic headroom (§22-§26)\n"
        "HEADROOM_RATIO = expected gross edge / realistic cost. Bands: "
        + ", ".join(f"{b} {n}" for b, n in SP.HEADROOM_BANDS)
        + "\n\n"
        + _md_table(["family", "band", "ratio", "net exception", "turnover"], hr_rows)
    )
    _artifact_pair(
        "ECONOMIC_HEADROOM_MATRIX",
        {
            "bands": [[b if b != float("inf") else "inf", n] for b, n in SP.HEADROOM_BANDS],
            "families": [
                {
                    "family_id": f.family_id,
                    "headroom_ratio": f.headroom_ratio,
                    "headroom_class": f.headroom_class,
                    "net_evidence_exception": f.net_evidence_exception,
                    "turnover": f.turnover,
                }
                for f in SP.STRATEGY_FAMILIES
            ],
        },
        hr_md,
    )

    # ---- TRADABILITY_MATRIX -------------------------------------------- #
    tr_rows = [
        [f.family_id, str(f.scores["tradability"]), f.tradability_notes, f.capacity]
        for f in SP.STRATEGY_FAMILIES
    ]
    tr_md = (
        header
        + "\n## Tradability & product match (§30-§37)\n"
        + _md_table(["family", "score", "notes", "capacity"], tr_rows)
    )
    _artifact_pair(
        "TRADABILITY_MATRIX",
        {
            "families": [
                {
                    "family_id": f.family_id,
                    "tradability": f.scores["tradability"],
                    "notes": f.tradability_notes,
                    "capacity": f.capacity,
                }
                for f in SP.STRATEGY_FAMILIES
            ]
        },
        tr_md,
    )

    # ---- POST_PUBLICATION_REVIEW --------------------------------------- #
    pp_rows = [
        [f.family_id, f.post_publication, str(f.scores["post_publication_survival"])]
        for f in SP.STRATEGY_FAMILIES
    ]
    pp_md = (
        header + "\n## Post-publication survival (§19, §72-§73)\n"
        "Classes: "
        + ", ".join(SP.POST_PUBLICATION_CLASSES)
        + "\n\n"
        + _md_table(["family", "survival", "score"], pp_rows)
        + "\n\n"
        + "\n".join(f"- **{f.family_id}**: {f.counter_evidence}" for f in SP.STRATEGY_FAMILIES)
    )
    _artifact_pair(
        "POST_PUBLICATION_REVIEW",
        {
            "classes": list(SP.POST_PUBLICATION_CLASSES),
            "families": [
                {
                    "family_id": f.family_id,
                    "post_publication": f.post_publication,
                    "counter_evidence": f.counter_evidence,
                }
                for f in SP.STRATEGY_FAMILIES
            ],
        },
        pp_md,
    )

    # ---- FINAL_DECISION_MATRIX ----------------------------------------- #
    dec_rows = [
        [
            str(i + 1),
            f.family_id,
            str(f.scores["evidence_strength"]),
            "yes",
            f.headroom_class,
            f.turnover.split(";")[0],
            f.data_cost_class,
            str(f.scores["tradability"]),
            f.post_publication,
            str(f.scores["orthogonality"]),
            str(f.scores["implementation_simplicity"]),
            f.research_cost,
            f.time_to_validation,
            SP.decision_for(f, gate),
        ]
        for i, f in enumerate(SP.STRATEGY_FAMILIES)
    ]
    dec_md = (
        header
        + "\n## Final decision matrix (§74-§75)\n"
        + _md_table(
            [
                "rank",
                "strategy",
                "evidence",
                "mechanism",
                "headroom",
                "turnover",
                "data",
                "tradability",
                "post-pub",
                "orthogonality",
                "complexity",
                "research cost",
                "time-to-validation",
                "decision",
            ],
            dec_rows,
        )
        + "\n\nDecision values are exactly: "
        + ", ".join(SP.DECISIONS)
    )
    _artifact_pair(
        "FINAL_DECISION_MATRIX",
        {
            "decision_values": list(SP.DECISIONS),
            "rows": [
                {
                    "family_id": f.family_id,
                    "decision": SP.decision_for(f, gate),
                    "headroom_class": f.headroom_class,
                    "post_publication": f.post_publication,
                    "research_cost": f.research_cost,
                    "time_to_validation": f.time_to_validation,
                }
                for f in SP.STRATEGY_FAMILIES
            ],
        },
        dec_md,
    )

    # ---- final report --------------------------------------------------- #
    fs = SP.audit_false_success(gate)
    final_json = {
        "title": "RFC-035 STRATEGIC PROFITABILITY PLAN V2",
        "source_commit": head,
        "final_commit": "RFC-035 build commit (the commit containing this artifact)",
        "as_of_commit": head,
        "generated_at": now,
        "current_status": SP.profitability_research_status(gate),
        "strategy_families_reviewed": len(SP.STRATEGY_FAMILIES),
        "top5": [f.family_id for f in top5],
        "finalists": [f.family_id for f in finalists],
        "g_reentry": gate.status_value,
        "authorized_reproductions": [f.family_id for f in authorized],
        "p1": gate.authorized_p1,
        "p2": gate.authorized_p2,
        "primary_markets": "diversified futures (indices, bonds, rates, FX, commodities)",
        "primary_horizon": "WEEKLY/MONTHLY",
        "expected_turnover": "LOW-MONTHLY",
        "economic_headroom": "STRONG_HEADROOM",
        "data_feasibility": "free/PIT-constructible futures data",
        "tradability": "liquid futures, long/short, no borrow",
        "next_alpha_rfc_allowed": SP.next_alpha_rfc_allowed(gate),
        "next_rfc_type": SP.NEXT_RFC_TYPE if gate.status is SP.ReentryStatus.PASS else None,
        "false_success": fs["false_success"],
        "independent_verification": "reports/profitability-v2/RFC035_VERIFICATION.json",
        "economic_marker": {
            "statistical_historical_effect": SP.STATISTICAL_HISTORICAL_EFFECT,
            "executable_validated_edge_count": SP.EXECUTABLE_VALIDATED_EDGE_COUNT,
            "robust_edge_count": SP.ROBUST_EDGE_COUNT,
            "paper_candidate_count": SP.PAPER_CANDIDATE_COUNT,
            "forward_profitable_count": SP.FORWARD_PROFITABLE_COUNT,
            "live_profitable_count": SP.LIVE_PROFITABLE_COUNT,
        },
    }
    p1 = gate.authorized_p1 or "NONE"
    p2 = gate.authorized_p2 or "NONE"
    final_md = (
        header
        + f"\nsource_commit = {head} (RFC-034 entry)\n"
        + f"\nCurrent status = {SP.profitability_research_status(gate)}\n"
        f"Strategy families reviewed = {len(SP.STRATEGY_FAMILIES)}\n"
        f"Top-5 = {[f.family_id for f in top5]}\n"
        f"Finalists = {[f.family_id for f in finalists]}\n"
        f"G_REENTRY = {gate.status_value}\n"
        f"AUTHORIZED_REPRODUCTIONS = {[f.family_id for f in authorized]}\n"
        f"P1 = {p1}\nP2 = {p2}\n"
        "Primary markets = diversified futures (indices, bonds, rates, FX, commodities)\n"
        "Primary horizon = WEEKLY/MONTHLY\n"
        "Expected turnover = LOW-MONTHLY\n"
        "Economic headroom = STRONG_HEADROOM\n"
        "Data feasibility = free/PIT-constructible futures data\n"
        "Tradability = liquid futures, long/short, no borrow\n"
        f"Next alpha RFC allowed = {'YES' if SP.next_alpha_rfc_allowed(gate) else 'NO'}\n"
        f"FALSE_SUCCESS = {fs['false_success']}\n"
        "Independent verification = reports/profitability-v2/RFC035_VERIFICATION.json\n\n"
        "## Economic marker\n"
        f"- Executable validated edges = {SP.EXECUTABLE_VALIDATED_EDGE_COUNT}\n"
        f"- Robust edges = {SP.ROBUST_EDGE_COUNT}\n"
        f"- Paper candidates = {SP.PAPER_CANDIDATE_COUNT}\n"
        f"- Forward profitable = {SP.FORWARD_PROFITABLE_COUNT}\n"
        f"- Live profitable = {SP.LIVE_PROFITABLE_COUNT}\n\n"
        "## Next\n"
        + (
            f"Phase 2 = REENTRY_APPROVED. NEXT_RFC_TYPE = {SP.NEXT_RFC_TYPE}, candidate = {p1}."
            if gate.status is SP.ReentryStatus.PASS
            else "NO STRATEGY CURRENTLY JUSTIFIES IMPLEMENTATION. Remain PAUSED."
        )
    )
    _write_json(REPORTS / "RFC035_FINAL_REPORT.json", final_json)
    (REPORTS / "RFC035_FINAL_REPORT.md").write_text(final_md.rstrip() + "\n", encoding="utf-8")

    # ---- tracked plan --------------------------------------------------- #
    tracked_md = (
        header + "\n## Current state\n"
        f"- platform_status = {SP.PLATFORM_STATUS}\n"
        f"- economic_status = {SP.ECONOMIC_STATUS}\n"
        f"- profitability_research_status = {SP.profitability_research_status(gate)}\n"
        f"- entry_next_alpha_rfc_allowed = {SP.ENTRY_NEXT_ALPHA_RFC_ALLOWED}\n"
        f"- next_alpha_rfc_allowed = {SP.next_alpha_rfc_allowed(gate)}\n\n"
        "## Why Phase 1 closed\n"
        "Crypto-centric, intraday, indicator/price-driven lines were all rejected at a gate "
        "under realistic costs (RFC-010B..RFC-033).  See PROJECT_ECONOMIC_STATUS.md.\n\n"
        "## What changes in Phase 2\n"
        "External, multi-asset, lower-turnover, evidence-first.  EDGE FIRST, FREQUENCY "
        "SECOND.  Crypto is one possible sleeve, not the whole business.\n\n"
        "## Markets considered\n"
        "futures, equities, ETFs, FX, commodities, rates/bonds, indices, crypto.\n\n"
        f"## Strategies considered ({len(SP.STRATEGY_FAMILIES)})\n"
        + "\n".join(f"- {f.family_id}: {f.name}" for f in SP.STRATEGY_FAMILIES)
        + "\n\n## Evidence standards\n"
        ">= 2 independent sources per finalist where they exist; source authority ladder; "
        "post-publication survival; contradictory evidence mandatory.\n\n"
        "## Economic standards\n"
        "mechanism required; realistic cost floor; HEADROOM_RATIO bands; net-evidence "
        "exception allowed only with net-of-cost external evidence.\n\n"
        "## Shortlist (top-5)\n"
        + "\n".join(f"{i + 1}. {f.family_id}" for i, f in enumerate(top5))
        + "\n\n## Finalists (max 3)\n"
        + "\n".join(f"{i + 1}. {f.family_id}" for i, f in enumerate(finalists))
        + "\n\n## Authorized reproductions (max 2)\n"
        + ("\n".join(f"{i + 1}. {f.family_id}" for i, f in enumerate(authorized)) or "- none")
        + f"\n\n## G_REENTRY = {gate.status_value}\n"
        f"## Stop conditions\n"
        "VALIDATION FAIL -> stop, no retuning; a finalist may remain RESEARCHABLE but NOT "
        "AUTHORIZED.\n\n"
        "## Path to Validation\n"
        "REPRODUCTION -> DISCOVERY -> VALIDATION (pre-registered spec, unseen data).\n"
        "## Path to Paper\n"
        "VALIDATION -> ROBUSTNESS -> HOLDOUT -> CERTIFICATION -> FORWARD PAPER.\n"
        "## Path to Live\n"
        "forward success -> CANARY -> explicit human approval -> LIVE.\n\n"
        "## Economic marker\n"
        f"executable_validated_edge_count = {SP.EXECUTABLE_VALIDATED_EDGE_COUNT}; "
        "all execution counters remain 0.\n\n"
        f"## Provenance\nSOURCE_COMMIT = {head}\n"
        "FINAL_COMMIT = the RFC-035 build commit (this commit).\n"
    )
    _write_json(
        DOCS / "STRATEGIC_PROFITABILITY_PLAN_V2.json",
        {**summary, "source_commit": head, "generated_at": now},
    )
    (DOCS / "STRATEGIC_PROFITABILITY_PLAN_V2.md").write_text(
        tracked_md.rstrip() + "\n", encoding="utf-8"
    )

    return {
        "summary": summary,
        "false_success": fs["false_success"],
        "artifacts_dir": str(OUT),
        "tracked_plan": str(DOCS / "STRATEGIC_PROFITABILITY_PLAN_V2.md"),
    }


def main() -> int:
    result = build()
    print(json.dumps(result["summary"], indent=2, ensure_ascii=False))
    print(f"FALSE_SUCCESS = {result['false_success']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
