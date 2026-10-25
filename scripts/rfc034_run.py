"""RFC-034 orchestrator — profitability-research closure & re-entry governance.

Deterministic and documentation-only: it adds **no** alpha, indicator, agent,
market, execution optimisation, strategy family or dataset (§0).  It freezes the
project's economic truth, consolidates the RFC-010B → RFC-033 evidence into a
canonical ledger + candidate registry, separates verification from economic
result, and writes a strict re-entry policy.

Outputs the required artifacts under ``reports/strategy-closure/`` (§71), the
final report ``reports/RFC034_FINAL_REPORT.{md,json}`` (§72) and the tracked
canonical documents under ``docs/research/`` (§49/§50).
"""

from __future__ import annotations

import json
import subprocess
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from trading_bot.research import economic_closure as EC

REPO = Path(__file__).resolve().parents[1]
OUT = REPO / "reports" / "strategy-closure"
DOCS = REPO / "docs" / "research"

RFC_COMMITS: dict[str, str] = {
    "RFC-010B": "2d64536",
    "RFC-020": "49c2cdb",
    "RFC-021": "0289bcb",
    "RFC-022": "59f77cd",
    "RFC-023": "7c64714",
    "RFC-024": "7f80b66",
    "RFC-025": "c17c1ce",
    "RFC-026": "f35f6f0",
    "RFC-027": "2cf195c",
    "RFC-028": "b3a048b",
    "RFC-029": "1a9d5d0",
    "RFC-030": "3a32f9f",
    "RFC-031": "8cd10cc",
    "RFC-032": "45ac4db",
    "RFC-033": "38b9700",
}

REGEN_COMMANDS: dict[str, str] = {
    "RFC-021": "python scripts/sprint002_verify.py  # sprint-002 evidence",
    "RFC-022/023": "python scripts/sprint023_verify.py",
    "RFC-024": "python scripts/sprint024_verify.py",
    "RFC-025": "python scripts/sprint025_verify.py",
    "RFC-026": "python scripts/sprint026_verify.py",
    "RFC-027": "python scripts/sprint027_verify.py",
    "RFC-028": "python scripts/sprint028_verify.py",
    "RFC-029": "python scripts/sprint029_verify.py",
    "RFC-030": "python scripts/sprint030_run.py && python scripts/sprint030_verify.py",
    "RFC-031": "python scripts/sprint031_run.py && python scripts/sprint031_verify.py",
    "RFC-032": "python scripts/sprint032_run.py && python scripts/sprint032_verify.py",
    "RFC-033": "python scripts/sprint033_fetch.py && python scripts/sprint033_run.py"
    " && python scripts/sprint033_verify.py",
}


def git(rev: str = "HEAD") -> str:
    try:
        return subprocess.check_output(["git", "rev-parse", rev], text=True).strip()
    except Exception:
        return "UNKNOWN"


def now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n",
        encoding="utf-8",
    )


def write_md(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


# --------------------------------------------------------------------------- #
# §0 — entry gate
# --------------------------------------------------------------------------- #


def entry_gate() -> dict[str, Any]:
    status = subprocess.check_output(["git", "status", "--short"], text=True)
    log = subprocess.check_output(["git", "log", "-10", "--oneline"], text=True)
    return {
        "repository": str(REPO),
        "branch": subprocess.check_output(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"], text=True
        ).strip(),
        "head": git("HEAD"),
        "expected_rfc033_head_prefix": "38b9700",
        "head_matches_rfc033": git("HEAD").startswith("38b9700"),
        "git_log_10": log.strip().splitlines(),
        "git_status_short": [line for line in status.splitlines() if line.strip()],
        "dirt_policy": "pre-existing unrelated dirt left untouched; no reset/cleanup",
    }


# --------------------------------------------------------------------------- #
# markdown renderers
# --------------------------------------------------------------------------- #


def md_marker(marker: EC.EconomicMarker) -> str:
    d = asdict(marker)
    lines = ["| field | value |", "| --- | --- |"]
    for key, value in d.items():
        lines.append(f"| {key.upper()} | {value} |")
    return "\n".join(lines)


def render_plan(gate: dict[str, Any], generated: str) -> str:
    return f"""# RFC-034 — PROFITABILITY RESEARCH CLOSURE & RE-ENTRY GOVERNANCE — PLAN

generated_at = {generated}
source_commit = {gate["head"]}
branch = {gate["branch"]}

## Mission
Close the current profitability research *program* WITHOUT discarding the
platform; consolidate economic evidence; freeze the current project truth; and
create a strict re-entry policy for future externally-evidenced edges.

## Prohibited (§0)
new alpha · new indicator · new agent · new market · new execution optimisation ·
new strategy family · new dataset for alpha search.

## Pipeline (§81)
VERIFY REPOSITORY → AUDIT ALL ECONOMIC RFCs → BUILD CANONICAL CANDIDATE
REGISTRY → REMOVE STALE PROMOTION STATES → FREEZE PROJECT ECONOMIC STATUS →
SEPARATE VERIFICATION FROM ECONOMIC RESULT → BUILD REENTRY POLICY → BUILD ALPHA
RESEARCH PLAYBOOK → VERIFY CLOSURE → PAUSE PROFITABILITY RESEARCH.

## Entry gate (§0)
```json
{json.dumps(gate, indent=2)}
```

## Artifacts (§71)
- reports/strategy-closure/{{RFC034_PLAN, ECONOMIC_RESEARCH_LEDGER,
  CANDIDATE_REGISTRY, PROJECT_ECONOMIC_STATUS, ALPHA_REENTRY_POLICY,
  ALPHA_ADMISSION_SCORECARD, EVIDENCE_ARCHIVE_INDEX, PROJECT_SCORECARD,
  RFC034_VERIFICATION}}.{{md,json}}
- reports/RFC034_FINAL_REPORT.{{md,json}}
- docs/research/{{PROJECT_ECONOMIC_STATUS.md, PROJECT_ECONOMIC_STATUS.json,
  ALPHA_RESEARCH_PLAYBOOK.md, WHERE_WE_ARE.md}}
"""


def render_ledger(generated: str, source: str) -> str:
    rows = [asdict(r) for r in EC.LEDGER]
    lines = [
        "# RFC-034 — ECONOMIC RESEARCH LEDGER",
        "",
        f"generated_at = {generated}",
        f"source_commit = {source}",
        f"rows = {len(rows)}",
        "",
        "Negative results are retained as assets (§5, §47).",
        "",
    ]
    for r in rows:
        lines.append(f"## {r['rfc']} — {r['family']}")
        for key in (
            "hypothesis", "data", "assets", "timeframe", "gross_edge", "cost",
            "net_edge", "sample_size", "discovery", "validation", "walk_forward",
            "robustness", "holdout", "tradability", "pit", "classification",
            "rejection_reason", "economic_lesson",
        ):
            lines.append(f"- {key}: {r[key]}")
        lines.append("")
    return "\n".join(lines)


def render_registry(generated: str, source: str) -> str:
    lines = [
        "# RFC-034 — CANONICAL CANDIDATE REGISTRY",
        "",
        f"generated_at = {generated}",
        f"source_commit = {source}",
        "",
        "PROMOTABLE = AND(mandatory gates) via the RFC-032 CandidateCertificationGate.",
        "No candidate with a failed mandatory gate may be promotable (§7, §35).",
        "",
        "| candidate_id | family | status | promotable | validation | robustness |"
        " holdout | tradability | evidence |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for c in EC.CANDIDATES:
        lines.append(
            f"| {c.candidate_id} | {c.family} | {c.status} | {c.promotable} |"
            f" {c.validation_status} | {c.robustness_status} | {c.holdout_status} |"
            f" {c.tradability_status} | {c.evidence_status} |"
        )
    lines += ["", "## Invalidation reasons", ""]
    for c in EC.CANDIDATES:
        lines.append(f"- {c.candidate_id}: {c.invalidation_reason}")
    lines += ["", "## Superseded promotion claims (§8)", ""]
    for s in EC.SUPERSEDED_CLAIMS:
        lines.append(f"- source: {s['source']}")
        lines.append(f"  - superseded_by: {s['superseded_by']}")
        lines.append(f"  - reason: {s['reason']}")
    lines += ["", f"active/promotable candidates = {EC.active_candidate_count()}"]
    return "\n".join(lines)


def status_payload(source: str, generated: str) -> dict[str, Any]:
    return {
        "as_of_commit": source,
        "status_date": generated,
        "platform_status": EC.PLATFORM_STATUS,
        "economic_status": EC.ECONOMIC_STATUS,
        "profitability_research_status": EC.PROFITABILITY_RESEARCH_STATUS,
        "current_decision": EC.CURRENT_DECISION,
        "validated_edges": EC.ECONOMIC_MARKER.executable_validated_net_edge,
        "robust_edges": EC.ECONOMIC_MARKER.robust_executable_net_edge,
        "paper_candidates": EC.ECONOMIC_MARKER.certified_paper_candidate,
        "forward_profitable": EC.ECONOMIC_MARKER.forward_paper_profitable,
        "live_profitable": EC.ECONOMIC_MARKER.live_profitable,
        "active_candidates": EC.active_candidate_count(),
        "next_alpha_rfc_allowed": EC.NEXT_ALPHA_RFC_ALLOWED,
        "economic_marker": asdict(EC.ECONOMIC_MARKER),
        "paused_reason": EC.PAUSE_REASON,
        "closed_candidate_statuses": EC.canonical_candidates(),
    }


def render_status_md(payload: dict[str, Any]) -> str:
    m = payload["economic_marker"]
    lines = [
        "# PROJECT ECONOMIC STATUS (canonical)",
        "",
        f"as_of_commit = {payload['as_of_commit']}",
        f"status_date = {payload['status_date']}",
        "",
        "## Status split",
        f"- platform_status = {payload['platform_status']}",
        f"- economic_status = {payload['economic_status']}",
        f"- profitability_research_status = {payload['profitability_research_status']}",
        f"- current_decision = {payload['current_decision']}",
        "",
        "## Frozen economic marker",
        "| field | value |",
        "| --- | --- |",
    ]
    for key, value in m.items():
        lines.append(f"| {key.upper()} | {value} |")
    lines += [
        "",
        f"active_candidates = {payload['active_candidates']}",
        f"next_alpha_rfc_allowed = {payload['next_alpha_rfc_allowed']}",
        "",
        "## Paused reason",
        payload["paused_reason"],
        "",
        "## Closed candidate statuses",
    ]
    for cid, status in payload["closed_candidate_statuses"].items():
        lines.append(f"- {cid} = {status}")
    lines += [
        "",
        "> This is the canonical, tracked source of truth. Reports under",
        "> `reports/` are local and gitignored; this document supersedes any stale",
        "> promotion claim (PAPER_CANDIDATE / CERTIFIED / READY / PROFITABLE).",
    ]
    return "\n".join(lines)


def render_reentry_policy(generated: str) -> str:
    lines = [
        "# RFC-034 — ALPHA RE-ENTRY POLICY",
        "",
        f"generated_at = {generated}",
        "",
        "Objective: prevent random new-strategy loops (§18).",
        "",
        "## State machine (§41)",
        " → ".join(EC.REENTRY_STATES),
        "",
        "## Re-entry must start outside (§19)",
    ]
    for s in EC.REENTRY_START_SOURCES:
        lines.append(f"- {s}")
    lines += [
        "",
        "## Required external evidence (§20)",
        f"- >= {EC.REENTRY_MIN_EVIDENCE_SOURCES} independent sources when they exist",
        "- at least one credible source type:",
    ]
    for s in EC.REENTRY_CREDIBLE_SOURCE_TYPES:
        lines.append(f"  - {s}")
    lines += [
        "- social media is not sufficient",
        "",
        "## Economic headroom (§21/§22)",
        "HEADROOM_RATIO = expected gross edge / realistic estimated cost",
        "",
        "| ratio | class |",
        "| --- | --- |",
        "< 1.0 | REJECT",
        "1.0-1.25 | TOO_THIN",
        "1.25-1.5 | WEAK",
        "1.5-2.0 | POTENTIALLY_RESEARCHABLE",
        ">= 2.0 | STRONG_HEADROOM",
        "",
        "Not proof of alpha — a filter to decide whether to spend resources.",
        "",
        "## Exception (§23)",
        "A candidate may pass without the ratio if an external source already",
        "demonstrates NET OF REALISTIC COST convincingly. Document the exception.",
        "",
        "## Data/product/execution/cost gates (§24-§27)",
        "- DATA FEASIBILITY: depth, PIT, tradability, cost evidence, universe,",
        "  survivorship; else DO_NOT_IMPLEMENT.",
        "- PRODUCT FEASIBILITY: long/short/borrow/funding/margin/options/rolls.",
        "- EXECUTION SEMANTICS FIRST: signal/available/order/fill times; no",
        "  same-close ambiguity.",
        "- COST MODEL FIRST, never after seeing PnL.",
        "",
        "## Budget (§30)",
        f"- MAX_STRATEGIES = {EC.MAX_STRATEGIES}",
        f"- MAX_CORE_VARIANTS_PER_STRATEGY = {EC.MAX_CORE_VARIANTS_PER_STRATEGY}",
        "",
        "## Reproduction before adaptation (§31/§32)",
        "EXTERNAL CLAIM → FAITHFUL REPRODUCTION → VERIFY EFFECT → REALISTIC COST",
        "→ ONLY THEN ADAPT. No tuning before reproduction.",
        "",
        "## Mandatory early kill (§33)",
        "Stop if: no information · gross << cost · tradability invalid · PIT unsafe",
        "· Validation fail.",
        "",
        "## Gate order (§34)",
        " → ".join(EC.GATE_ORDER),
        "",
        "No later gate compensates an earlier one.",
        "",
        "## Valid reopen triggers (§42)",
    ]
    for t in EC.VALID_REOPEN_TRIGGERS:
        lines.append(f"- {t}")
    lines += ["", "## Invalid reopen triggers (§43)"]
    for t in EC.INVALID_REOPEN_TRIGGERS:
        lines.append(f"- {t}")
    lines += [
        "",
        "## Periodic scan (§44)",
        "Documented process only (manual/external literature & market-structure",
        "review). No recurring automation inside the trading runtime; runtime stays",
        "quiet while paused.",
        "",
        "## Runtime posture (§45/§46)",
        "live trading disabled · paper campaigns disabled unless explicitly active ·",
        "automatic strategy promotion disabled. Research mode (data validation,",
        "replay, backtests, source audit, external reproduction) remains available",
        "when intentionally invoked.",
        "",
        "## Platform preserved (§47)",
        "Engines, datasets, certification gate, reports, tests, PIT tooling and",
        "cost models are retained. Negative evidence is an asset.",
    ]
    return "\n".join(lines)


def render_scorecard_template(generated: str) -> str:
    lines = [
        "# RFC-034 — ALPHA ADMISSION SCORECARD",
        "",
        f"generated_at = {generated}",
        "",
        "Score each dimension 0-5. A candidate is admitted only if NO CRITICAL",
        "dimension <= 1 and the critical dimensions are strong (§29).",
        "",
        "| dimension | score (0-5) | critical |",
        "| --- | --- | --- |",
    ]
    for dim in EC.SCORECARD_DIMENSIONS:
        critical = "yes" if dim in EC.CRITICAL_DIMENSIONS else ""
        lines.append(f"| {dim} | | {critical} |")
    lines += [
        "",
        "## Decision rule",
        "- any critical dimension <= 1 → REJECT",
        "- any other dimension <= 1 → REJECT",
        "- all critical dimensions >= 3 → APPROVED_FOR_RESEARCH",
        "- otherwise → ADMISSION_REVIEW",
        "",
        "## Worked examples (illustrative, not real candidates)",
        "| candidate | decision |",
        "| --- | --- |",
    ]
    examples: dict[str, dict[str, int]] = {
        "reject_weak_evidence": {
            "evidence_strength": 1, "economic_headroom": 3, "data_feasibility": 4,
            "tradability": 4, "orthogonality": 4, "implementation_cost": 4,
            "independent_replication": 2,
        },
        "approve_strong": {
            "evidence_strength": 4, "economic_headroom": 4, "data_feasibility": 5,
            "tradability": 4, "orthogonality": 4, "implementation_cost": 5,
            "independent_replication": 4,
        },
    }
    for name, scores in examples.items():
        decision = EC.admission_decision(scores).decision
        lines.append(f"| {name} | {decision} |")
    return "\n".join(lines)


def evidence_index(generated: str, source: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    report_for = {
        "RFC-010B": "reports/RFC010B_FINAL_REPORT.md",
        "RFC-020": "reports/RFC020_FINAL_REPORT.md",
        "RFC-021": "reports/RFC021_EDGE001_FINAL_REPORT.md",
        "RFC-022": "reports/EDGE_DISCOVERY_SPRINT002_FINAL_REPORT.md",
        "RFC-023": "reports/RFC023_GENERALIZATION_FINAL_REPORT.md",
        "RFC-024": "reports/directional/RFC024_HYPOTHESIS_REGISTRY.md",
        "RFC-025": "reports/RFC025_FINAL_REPORT.md",
        "RFC-026": "reports/RFC026_FINAL_REPORT.md",
        "RFC-027": "reports/RFC027_FINAL_REPORT.md",
        "RFC-028": "reports/RFC028_FINAL_REPORT.md",
        "RFC-029": "reports/RFC029_FINAL_REPORT.md",
        "RFC-030": "reports/RFC030_FINAL_REPORT.md",
        "RFC-031": "reports/RFC031_FINAL_REPORT.md",
        "RFC-032": "reports/RFC032_FINAL_REPORT.md",
        "RFC-033": "reports/RFC033_FINAL_REPORT.md",
    }
    evidence_for = {
        "RFC-030": "reports/external-alpha/",
        "RFC-031": "reports/paper-certification/",
        "RFC-032": "reports/tsmom-remediation/",
        "RFC-033": "reports/perp-tsmom/",
    }
    candidate_for = {
        "RFC-030": "EXT-TSMOM-001, EXT-XMOM-001",
        "RFC-031": "EXT-TSMOM-001",
        "RFC-032": "EXT-TSMOM-002",
        "RFC-033": "EXT-TSMOM-003",
    }
    status_for = {
        "RFC-030": "REPRODUCED (labels later invalidated)",
        "RFC-031": "REJECTED / INVALIDATED_TRADABILITY",
        "RFC-032": "REJECTED_HISTORICAL_PLAUSIBILITY",
        "RFC-033": "REJECTED_VALIDATION",
    }
    for row in EC.LEDGER:
        rfc = row.rfc
        rows.append(
            {
                "rfc": rfc,
                "candidate": candidate_for.get(rfc, ""),
                "report_path": report_for.get(rfc, ""),
                "evidence_path": evidence_for.get(rfc, "reports/"),
                "commit": RFC_COMMITS.get(rfc, "UNKNOWN"),
                "final_status": status_for.get(rfc, row.classification),
            }
        )
    return rows


def render_evidence_index(rows: list[dict[str, Any]], generated: str) -> str:
    lines = [
        "# RFC-034 — EVIDENCE ARCHIVE INDEX",
        "",
        f"generated_at = {generated}",
        "",
        "| RFC | candidate | report path | evidence path | commit | final status |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for r in rows:
        lines.append(
            f"| {r['rfc']} | {r['candidate']} | {r['report_path']} |"
            f" {r['evidence_path']} | {r['commit']} | {r['final_status']} |"
        )
    lines += ["", "## Regeneration commands (§51)", "", "```"]
    for rfc, cmd in REGEN_COMMANDS.items():
        lines.append(f"{rfc}: {cmd}")
    lines += ["```"]
    return "\n".join(lines)


def render_project_scorecard(generated: str, source: str) -> str:
    return f"""# RFC-034 — FINAL PROJECT SCORECARD

generated_at = {generated}
source_commit = {source}

No single fake readiness percentage is used (§69); each axis is reported on its
own.

| axis | status | note |
| --- | --- | --- |
| runtime / data integrity | PASS | certified runtime, reproducible dataset hashes |
| research integrity | PASS | PIT-safe, independent reproduction, false-alpha rejection |
| cost modeling | PASS | cost model declared before results, reconciled |
| independent verification | PASS | builder != verifier on every RFC |
| governance | PASS | gate order + no later-gate compensation enforced |
| alpha discovery | INCONCLUSIVE_UNTIL_NEW_EVIDENCE | no reproducible directional edge |
| validated executable edge | NONE | executable_validated_net_edge = 0 |
| paper readiness | NONE | certified_paper_candidate = 0 |
| live readiness | NONE | live_profitable = 0 |

## Interpretation

The platform executes and verifies research correctly; what is missing is an
executable, validated, robust, net-positive edge. Absence of edge is not an
architecture failure (§10).
"""


def render_playbook(source: str, generated: str) -> str:
    return f"""# ALPHA RESEARCH PLAYBOOK

canonical tracked document (RFC-034 §52)
as_of_commit = {source}
generated_at = {generated}

This is the default workflow for any future candidate. A future research RFC may
only be created after an external opportunity passes the ALPHA ADMISSION
SCORECARD (see `reports/strategy-closure/ALPHA_ADMISSION_SCORECARD.md` and
`ALPHA_REENTRY_POLICY.md`).

## Stage 0 — SOURCE / CLAIM / MECHANISM (§53)
No code yet. Identify the external evidence (>= 2 independent sources when they
exist, at least one peer-reviewed / credible working paper / exchange research /
independent replication / audited experiment). Social media is not sufficient.

## Stage 1 — DATA FEASIBILITY / TRADABILITY / COST FLOOR (§54)
Check historical depth, PIT availability, instrument tradability, transaction-cost
evidence, universe feasibility and survivorship. Compute HEADROOM_RATIO =
expected gross edge / realistic estimated cost. Kill early.

## Stage 2 — FAITHFUL REPRODUCTION (§55)
Reproduce the original effect exactly. No adaptation, no tuning.

## Stage 3 — DISCOVERY (§56)
Only after faithful reproduction.

## Stage 4 — VALIDATION (§57)
On unseen data with a pre-registered spec. Fail → STOP.

## Stage 5 — ROBUSTNESS (§58)
Walk-forward, temporal stability, cost stress, parameter stability, asset/regime
robustness as relevant.

## Stage 6 — HOLDOUT (§59)
Untouched holdout.

## Stage 7 — CERTIFICATION (§60)
Tradability, universe, cost, PIT and independent reproduction via the RFC-032
`CandidateCertificationGate`. Verifier checks (reproduction/hash/PIT/accounting/
contract) are separate from the economic gates (see verification semantics).

## Stage 8 — FORWARD PAPER (§61)
Fresh evidence only.

## Stage 9 — CANARY / LIVE READINESS (§62)
Only after forward success. Requires explicit human approval.

## Definitions

- VALIDATED NET EDGE (§63): net > 0 after realistic costs on unseen Validation
  with executable instruments.
- ROBUST EDGE (§64): Validation PASS + walk-forward + temporal stability + cost
  stress + parameter stability + asset/regime robustness.
- PAPER CANDIDATE (§65): robust edge + untouched holdout PASS + tradability PASS
  + independent verification PASS.
- PROFITABLE (§66): NEVER used for a Discovery winner, a historical backtest, a
  Validation-only result or a paper candidate.
- FORWARD_PAPER_PROFITABLE (§67): only after sufficient fresh paper evidence.
- LIVE_PROFITABLE (§68): only after real executed trades, real costs,
  reconciliation and a sufficient live sample. No current strategy qualifies.

## Gate order (§34)
{" → ".join(EC.GATE_ORDER)}

No later gate compensates an earlier one.
"""


def render_where_we_are(source: str, generated: str) -> str:
    return f"""# WHERE WE ARE

canonical tracked document (RFC-034 §70)
as_of_commit = {source}
generated_at = {generated}

## What works?
A PIT-safe data pipeline, cost-aware research, independent reproduction, false-alpha
rejection and candidate certification with gate governance. The codebase remains a
capable QUANT RESEARCH PLATFORM.

## What did not work?
Every economic line tested to a gate: price/directional (weak, cost-sensitive),
volatility (magnitude without direction), orthogonal basis/positioning (information
without net edge), execution optimisation (cannot rescue a weak alpha), carry
(predictable but below cost), and the external TSMOM line (statistical effect real,
executable form fails validation).

## Why are we paused?
NOT for lack of tests, runtime stability, PIT, cost models, strategies or agents.
The reason is that NO STRATEGY HAS DEMONSTRATED EXECUTABLE, VALIDATED, ROBUST, NET
POSITIVE EDGE.

## What would justify restarting?
A re-entry-qualified external opportunity: external evidence (>= 2 independent
sources) OR new structural data / market mechanism, with sufficient economic
headroom, passing the ALPHA ADMISSION SCORECARD.

## What should not be done next?
No RFC-035 alpha search; no more indicators/agents/thresholds; no leverage; no
reduced fees; no holdout changes; no seed changes.
"""


def render_final_report(source: str, generated: str) -> str:
    statuses = EC.canonical_candidates()
    closed = ", ".join(f"{k}={v}" for k, v in statuses.items())
    return f"""# RFC-034 PROFITABILITY RESEARCH CLOSURE

PROFITABILITY_RESEARCH_STATUS = {EC.PROFITABILITY_RESEARCH_STATUS}

PLATFORM_STATUS = {EC.PLATFORM_STATUS}

EXECUTABLE VALIDATED NET EDGE = {EC.ECONOMIC_MARKER.executable_validated_net_edge}

ROBUST EXECUTABLE NET EDGE = {EC.ECONOMIC_MARKER.robust_executable_net_edge}

PAPER CANDIDATE = {EC.ECONOMIC_MARKER.certified_paper_candidate}

FORWARD PAPER PROFITABLE = {EC.ECONOMIC_MARKER.forward_paper_profitable}

LIVE PROFITABLE = {EC.ECONOMIC_MARKER.live_profitable}

Candidate lines closed = {closed}

Active alpha candidates = {EC.active_candidate_count()}

NEXT ALPHA SEARCH ALLOWED = NO

REENTRY POLICY = ACTIVE

FALSE_SUCCESS = 0

INDEPENDENT VERIFICATION = (see RFC034_VERIFICATION)

## Final strategic decision

CURRENT DECISION = {EC.CURRENT_DECISION}

Meaning: PAUSE PROFITABILITY SEARCH — not DELETE PROJECT. The codebase remains a
QUANT RESEARCH PLATFORM.

## Future next step

The next action is NOT an RFC number. It is: WAIT FOR / IDENTIFY a reentry-qualified
external opportunity. Only after an opportunity passes the ALPHA ADMISSION SCORECARD
may a new research RFC be created.

## Identity

SOURCE_COMMIT = {source}
status_date = {generated}
economic_marker = {json.dumps(asdict(EC.ECONOMIC_MARKER))}
closed_statuses = {json.dumps(statuses)}
"""


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    DOCS.mkdir(parents=True, exist_ok=True)
    gate = entry_gate()
    source = gate["head"]
    generated = now()

    # RFC034_PLAN
    write_md(OUT / "RFC034_PLAN.md", render_plan(gate, generated))
    write_json(OUT / "RFC034_PLAN.json", {
        "generated_at": generated, "source_commit": source, "entry_gate": gate,
        "prohibited": [
            "new alpha", "new indicator", "new agent", "new market",
            "new execution optimisation", "new strategy family",
            "new dataset for alpha search",
        ],
        "pipeline": [
            "VERIFY_REPOSITORY", "AUDIT_ALL_ECONOMIC_RFCS",
            "BUILD_CANONICAL_CANDIDATE_REGISTRY", "REMOVE_STALE_PROMOTION_STATES",
            "FREEZE_PROJECT_ECONOMIC_STATUS",
            "SEPARATE_VERIFICATION_FROM_ECONOMIC_RESULT", "BUILD_REENTRY_POLICY",
            "BUILD_ALPHA_RESEARCH_PLAYBOOK", "VERIFY_CLOSURE",
            "PAUSE_PROFITABILITY_RESEARCH",
        ],
    })

    # ECONOMIC_RESEARCH_LEDGER
    ledger_rows = [asdict(r) for r in EC.LEDGER]
    write_md(OUT / "ECONOMIC_RESEARCH_LEDGER.md", render_ledger(generated, source))
    write_json(OUT / "ECONOMIC_RESEARCH_LEDGER.json", {
        "generated_at": generated, "source_commit": source,
        "rows": ledger_rows,
    })

    # CANDIDATE_REGISTRY
    registry = [{
        **asdict(c),
        "promotable": c.promotable,
        "blocking_gates": list(c.blocking_gates),
    } for c in EC.CANDIDATES]
    write_md(OUT / "CANDIDATE_REGISTRY.md", render_registry(generated, source))
    write_json(OUT / "CANDIDATE_REGISTRY.json", {
        "generated_at": generated, "source_commit": source,
        "candidates": registry,
        "superseded_claims": list(EC.SUPERSEDED_CLAIMS),
        "active_candidates": EC.active_candidate_count(),
        "mandatory_gates": list(EC.mandatory_gate_names()),
    })

    # PROJECT_ECONOMIC_STATUS (report + tracked)
    payload = status_payload(source, generated)
    status_md = render_status_md(payload)
    write_md(OUT / "PROJECT_ECONOMIC_STATUS.md", status_md)
    write_json(OUT / "PROJECT_ECONOMIC_STATUS.json", payload)
    write_md(DOCS / "PROJECT_ECONOMIC_STATUS.md", status_md)
    write_json(DOCS / "PROJECT_ECONOMIC_STATUS.json", payload)

    # ALPHA_REENTRY_POLICY
    write_md(OUT / "ALPHA_REENTRY_POLICY.md", render_reentry_policy(generated))
    write_json(OUT / "ALPHA_REENTRY_POLICY.json", {
        "generated_at": generated,
        "states": list(EC.REENTRY_STATES),
        "start_sources": list(EC.REENTRY_START_SOURCES),
        "min_evidence_sources": EC.REENTRY_MIN_EVIDENCE_SOURCES,
        "credible_source_types": list(EC.REENTRY_CREDIBLE_SOURCE_TYPES),
        "headroom_classes": [
            {"upper_bound": b, "class": n} for b, n in EC.HEADROOM_CLASSES
        ],
        "valid_reopen_triggers": list(EC.VALID_REOPEN_TRIGGERS),
        "invalid_reopen_triggers": list(EC.INVALID_REOPEN_TRIGGERS),
        "budget": {
            "max_strategies": EC.MAX_STRATEGIES,
            "max_core_variants_per_strategy": EC.MAX_CORE_VARIANTS_PER_STRATEGY,
        },
        "gate_order": list(EC.GATE_ORDER),
    })

    # ALPHA_ADMISSION_SCORECARD
    write_md(OUT / "ALPHA_ADMISSION_SCORECARD.md", render_scorecard_template(generated))
    write_json(OUT / "ALPHA_ADMISSION_SCORECARD.json", {
        "generated_at": generated,
        "dimensions": list(EC.SCORECARD_DIMENSIONS),
        "critical_dimensions": list(EC.CRITICAL_DIMENSIONS),
        "rule": "no critical dimension <= 1; all critical >= 3 to approve",
    })

    # EVIDENCE_ARCHIVE_INDEX
    ev_rows = evidence_index(generated, source)
    write_md(OUT / "EVIDENCE_ARCHIVE_INDEX.md", render_evidence_index(ev_rows, generated))
    write_json(OUT / "EVIDENCE_ARCHIVE_INDEX.json", {
        "generated_at": generated, "entries": ev_rows,
        "regeneration_commands": REGEN_COMMANDS,
    })

    # PROJECT_SCORECARD
    write_md(OUT / "PROJECT_SCORECARD.md", render_project_scorecard(generated, source))
    write_json(OUT / "PROJECT_SCORECARD.json", {
        "generated_at": generated, "source_commit": source,
        "axes": {
            "runtime_data_integrity": "PASS",
            "research_integrity": "PASS",
            "cost_modeling": "PASS",
            "independent_verification": "PASS",
            "governance": "PASS",
            "alpha_discovery": "INCONCLUSIVE_UNTIL_NEW_EVIDENCE",
            "validated_executable_edge": "NONE",
            "paper_readiness": "NONE",
            "live_readiness": "NONE",
        },
        "single_readiness_percentage": None,
    })

    # tracked playbook + where-we-are
    write_md(DOCS / "ALPHA_RESEARCH_PLAYBOOK.md", render_playbook(source, generated))
    write_md(DOCS / "WHERE_WE_ARE.md", render_where_we_are(source, generated))

    # final report
    final_md = render_final_report(source, generated)
    write_md(REPO / "reports" / "RFC034_FINAL_REPORT.md", final_md)
    write_json(REPO / "reports" / "RFC034_FINAL_REPORT.json", {
        "rfc": "RFC-034",
        "title": "PROFITABILITY RESEARCH CLOSURE",
        "source_commit": source,
        "status_date": generated,
        "profitability_research_status": EC.PROFITABILITY_RESEARCH_STATUS,
        "platform_status": EC.PLATFORM_STATUS,
        "economic_status": EC.ECONOMIC_STATUS,
        "current_decision": EC.CURRENT_DECISION,
        "economic_marker": asdict(EC.ECONOMIC_MARKER),
        "closed_candidate_statuses": EC.canonical_candidates(),
        "active_candidates": EC.active_candidate_count(),
        "next_alpha_rfc_allowed": EC.NEXT_ALPHA_RFC_ALLOWED,
        "reentry_policy": "ACTIVE",
        "false_success": 0,
        "head": gate["head"],
    })

    print(f"RFC-034 artifacts written. source_commit={source} generated_at={generated}")
    print(f"active_candidates={EC.active_candidate_count()} marker_zeros="
          f"{EC.ECONOMIC_MARKER.all_execution_zeros}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
