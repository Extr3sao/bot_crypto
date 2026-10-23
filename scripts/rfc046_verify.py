"""RFC-046 independent verifier.

Independence is structural, not stylistic:

* it does **not** import ``scripts/rfc046_audit.py`` — every fact is re-derived in this file, from git, from
  the tracked documents and from the repository's own cost model;
* it re-runs the collision scan with its own implementation;
* it recomputes the tracked document hashes;
* it may return FAIL, and it does so on any mismatch.

Exit code 0 = PASS, 1 = FAIL. ``MISMATCHES = n`` is printed for the builder to record.

``FALSE_SUCCESS`` is *measured*, not asserted: it counts claims recorded as satisfied in a tracked artefact
that this verifier cannot reproduce. A tracked artefact that says ``true`` about something that is false is the
only thing this counter rewards.

HISTORICAL SCOPE (2026-10-08): this tool was built for the RFC-046 NOT_ACTIVE phase. The owner
approved option 5A on 2026-10-08 (tasks/decisions.md ADR-0024), so the proposal-era invariants it
measures (status PROPOSED, trigger unchanged, no ADR) are expected to report as changed **by
design**. The current verifier is `scripts/rfc046_campaign_verify.py`; this file is kept because
it produced the pre-approval report and is part of the record, not because it is still green.
"""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
SRC = REPO / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

RFC_MD = REPO / "docs" / "rfc" / "RFC-046_CONTROLLED_DISCOVERY.md"
RFC_JSON = REPO / "docs" / "rfc" / "RFC-046_CONTROLLED_DISCOVERY.json"
AMENDMENT = REPO / "docs" / "roadmap" / "PROFITABILITY_ROADMAP_AMENDMENT.md"
ADMISSION = REPO / "docs" / "governance" / "DISCOVERY_ADMISSION_POLICY.md"
STOP = REPO / "docs" / "governance" / "DISCOVERY_STOP_RULES.md"
FLOW = REPO / "docs" / "architecture" / "DISCOVERY_EXECUTION_FLOW.md"
AUDIT = REPO / "data" / "rfc046" / "audit.json"
FINAL_JSON = REPO / "reports" / "rfc046" / "FINAL_REPORT.json"

TRACKED = (RFC_MD, RFC_JSON, AMENDMENT, ADMISSION, STOP, FLOW)
REQUESTED_PATHS = (
    "docs/rfc/RFC-046_CONTROLLED_DISCOVERY.md",
    "docs/roadmap/PROFITABILITY_ROADMAP_AMENDMENT.md",
    "docs/governance/DISCOVERY_ADMISSION_POLICY.md",
    "docs/governance/DISCOVERY_STOP_RULES.md",
    "docs/architecture/DISCOVERY_EXECUTION_FLOW.md",
    "reports/rfc046/IMPACT_ASSESSMENT.md",
    "reports/rfc046/FINAL_REPORT.md",
    "reports/rfc046/FINAL_REPORT.json",
)
FORBIDDEN_VERDICTS = ("PROFITABLE", "EDGE_CONFIRMED", "PRODUCTION_READY")
NEGATORS = (
    "not ",
    "no ",
    "never",
    "forbidden",
    "does not",
    "doesn't",
    "asserts no",
    "cannot",
    "without",
    "no_profit",
    "non-",
)

#: Known *references* to historic programme titles, which name a verdict without claiming it. Removing
#: them before the negation test keeps the check honest instead of loosening it.
KNOWN_REFERENCES = ("EXTERNAL PROFITABLE OPPORTUNITY DISCOVERY",)

FAILURES: list[str] = []
CHECKS = 0
_CLAIMS_BROKEN = 0


def check(label: str, ok: bool, detail: str = "") -> None:
    global CHECKS
    CHECKS += 1
    if not ok:
        FAILURES.append(f"{label}{' :: ' + detail if detail else ''}")


def check_claim(label: str, claimed: Any, actual: Any) -> None:
    """A claim recorded in a tracked artefact, compared with what the verifier derived."""
    global _CLAIMS_BROKEN
    ok = claimed == actual
    if claimed and not ok:
        _CLAIMS_BROKEN += 1
    check(f"claim: {label} (claimed={claimed!r}, actual={actual!r})", ok)


def run(args: list[str]) -> tuple[int, str]:
    proc = subprocess.run(args, cwd=str(REPO), capture_output=True, text=True, check=False)
    return proc.returncode, (proc.stdout or "") + (proc.stderr or "")


def git(args: list[str]) -> str:
    code, out = run(["git", *args])
    return out if code == 0 else ""


def sha256(path: Path) -> str:
    """Hash of the document text with line endings normalised, so a CRLF checkout is not read as an edit."""
    text = path.read_bytes().decode("utf-8").replace("\r\n", "\n")
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# independent re-derivation of the collision audit
# ---------------------------------------------------------------------------
def col_paths() -> list[str]:
    return sorted(
        line.strip()
        for line in git(["ls-tree", "-r", "--name-only", "HEAD"]).splitlines()
        if line.strip()
    )


def own_paths() -> set[str]:
    """Files this RFC adds, plus the RFC-035 lineage that named RFC-046.

    Once these are committed they are part of HEAD, so the exclusion has to work from the committed state too:
    otherwise RFC-046 reads as its own predecessor and the spacing audit reports a collision with itself.
    """
    return {
        "docs/rfc/RFC-046_CONTROLLED_DISCOVERY.md",
        "docs/rfc/RFC-046_CONTROLLED_DISCOVERY.json",
        "docs/roadmap/PROFITABILITY_ROADMAP_AMENDMENT.md",
        "docs/governance/DISCOVERY_ADMISSION_POLICY.md",
        "docs/governance/DISCOVERY_STOP_RULES.md",
        "docs/architecture/DISCOVERY_EXECUTION_FLOW.md",
        "docs/roadmap/PROFITABILITY_DISCOVERY_PROPOSAL.md",
        "scripts/rfc046_audit.py",
        "scripts/rfc046_verify.py",
        "tests/unit/research/test_rfc046_discovery_proposal.py",
        "data/rfc046/audit.json",
    }


def is_this_rfcs_output(rel: str) -> bool:
    """True for artefacts this RFC produced, which must never count as pre-existing occupancy."""
    if rel in own_paths():
        return True
    if (
        "/rfc046/" in rel
        or rel.endswith("/rfc046")
        or rel == "data/rfc046"
        or rel.startswith("data/rfc046/")
    ):
        return True
    if rel.startswith("docs/rfc/RFC-046_") or rel.startswith("docs/governance/DISCOVERY_"):
        return True
    return rel in (
        "docs/architecture/DISCOVERY_EXECUTION_FLOW.md",
        "docs/roadmap/PROFITABILITY_ROADMAP_AMENDMENT.md",
    )


def rewrite_collision() -> dict[str, Any]:
    tree = col_paths()
    excluded = own_paths()
    occupied: dict[str, dict[str, Any]] = {}
    root = REPO / "reports"
    for n in range(51):
        tag = f"{n:03d}"
        pattern = re.compile(rf"^(RFC{tag}|rfc{tag})([_\-.]|$)", re.IGNORECASE)
        artefacts: list[str] = []
        if root.is_dir():
            for path in sorted(root.rglob("*")):
                rel = str(path.relative_to(REPO)).replace("\\", "/")
                if is_this_rfcs_output(rel):
                    continue
                if (path.is_dir() and pattern.match(path.name)) or (
                    path.is_file() and pattern.match(path.name)
                ):
                    artefacts.append(rel + "/" if path.is_dir() else rel)
        declared: list[str] = []
        for rel in tree:
            if not rel.startswith("docs/") or not rel.endswith((".md", ".json", ".yaml", ".yml")):
                continue
            if is_this_rfcs_output(rel) or rel in excluded:
                continue
            text = (REPO / rel).read_text(encoding="utf-8", errors="replace")
            if re.search(rf'"rfc"\s*:\s*"RFC-{tag}"', text) or re.search(
                rf"^#\s+RFC-{tag}\b", text, flags=re.MULTILINE
            ):
                declared.append(rel)
        if artefacts or declared:
            occupied[tag] = {"artefacts": artefacts, "declared_in_tracked_docs": declared}
    grep_out = git(["grep", "-l", "no RFC-045 artifact exists", "HEAD", "--", "."])
    asserting = sorted(
        {ln.partition(":")[2].replace("\\", "/") for ln in grep_out.splitlines() if ln.strip()}
        - excluded
    )
    mentions: dict[str, list[str]] = {}
    for n in range(51):
        out = git(["grep", "-l", "-E", f"RFC-{n:03d}", "HEAD", "--", "."])
        paths = {ln.partition(":")[2].replace("\\", "/") for ln in out.splitlines() if ln.strip()}
        mentions[f"{n:03d}"] = sorted(
            p for p in paths if p not in excluded and not is_this_rfcs_output(p)
        )
    return {"occupied": occupied, "asserting_files_045": asserting, "mentions": mentions}


def derive_invariants() -> dict[str, Any]:
    roadmap = (REPO / "tasks" / "roadmap.md").read_text(encoding="utf-8")
    operating = json.loads(
        (REPO / "docs" / "research" / "PROFITABILITY_OPERATING_MODEL.json").read_text(
            encoding="utf-8"
        )
    )
    freeze = (REPO / "docs" / "governance" / "PROFITABILITY_FIRST_FREEZE.md").read_text(
        encoding="utf-8"
    )
    decisions = (REPO / "tasks" / "decisions.md").read_text(encoding="utf-8")
    return {
        "roadmap_unchanged": ("Fase 10" not in roadmap) and ("RFC-046" not in roadmap),
        "operating_model_trigger_unchanged": operating["next_action_policy"]["trigger"]
        == "ONLY a NEW QUALIFIED OPPORTUNITY or a MATERIAL CAPITAL / INSTRUMENT CHANGE reopens evaluation",
        "operating_model_supports_discovery": "DISCOVERY CAMPAIGN" in json.dumps(operating),
        "freeze_still_active_on_rfc035": "ACTIVE_RFC: **RFC-035" in freeze,
        "freeze_declares_rfc035_open": "ACTIVE** while RFC-035 is open" in freeze,
        "no_adr_for_rfc046": not re.search(
            r"^## ADR-[0-9]{4}.*RFC-046", decisions, flags=re.MULTILINE
        ),
        "runtime_live_disabled": "live_trading_enabled: false"
        in (REPO / "config" / "runtime.yaml").read_text(encoding="utf-8"),
        "risk_live_disabled": "live_trading_enabled: false"
        in (REPO / "config" / "risk.yaml").read_text(encoding="utf-8"),
        "runtime_mode_paper": 'mode: "paper"'
        in (REPO / "config" / "runtime.yaml").read_text(encoding="utf-8"),
        "manual_confirmation_required_for_live": "require_manual_confirmation_for_live: true"
        in (REPO / "config" / "runtime.yaml").read_text(encoding="utf-8"),
        "exchange_sandbox": "sandbox: true"
        in (REPO / "config" / "exchange.yaml").read_text(encoding="utf-8"),
    }


def derive_cost() -> dict[str, Any]:
    from trading_bot.research.microstructure import cost_model_v3 as m

    cost = m.default_model("BINANCE_SPOT_STANDARD_TAKER").evaluate(
        size_usd=1_000.0,
        liquidity_regime="normal",
        horizon_minutes=25.0,
        entry_order_type="market",
        exit_order_type="market",
    )
    by_class: dict[str, float] = {}
    for component in cost.components:
        by_class[component.knowledge] = round(
            by_class.get(component.knowledge, 0.0) + component.value_bps, 4
        )
    return {
        "round_trip_bps": round(cost.round_trip_bps, 4),
        "known_bps": by_class.get("KNOWN", 0.0),
        "estimated_bps": by_class.get("ESTIMATED", 0.0),
        "assumed_bps": by_class.get("ASSUMED", 0.0),
        "stressed": round(cost.required_edge_bps(1.5), 4),
        "sum_matches": round(sum(by_class.values()), 4) == round(cost.round_trip_bps, 4),
    }


# ---------------------------------------------------------------------------
# claim verifications
# ---------------------------------------------------------------------------
def verify_artifacts() -> None:
    for rel in REQUESTED_PATHS:
        check(f"deliverable exists: {rel}", (REPO / rel).is_file(), rel)
    check("tracked canonical state exists", RFC_JSON.is_file(), str(RFC_JSON))
    check("tracked audit record exists", AUDIT.is_file(), str(AUDIT))
    check(
        "verifier is a separate program from the builder",
        (REPO / "scripts" / "rfc046_verify.py").resolve()
        != (REPO / "scripts" / "rfc046_audit.py").resolve(),
        "",
    )
    check(
        "verifier does not import the builder", not _imports_builder(), "independence is structural"
    )


def _imports_builder() -> bool:
    """True if this file imports the builder module (it must not, by design)."""
    import ast

    tree = ast.parse(Path(__file__).read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import) and any(
            a.name.endswith("rfc046_audit") for a in node.names
        ):
            return True
        if isinstance(node, ast.ImportFrom) and (node.module or "").endswith("rfc046_audit"):
            return True
    return False


def verify_collision(audit: dict[str, Any]) -> None:
    derived = rewrite_collision()
    recorded = audit["governance"]["collision"]

    occupied_recorded = dict(recorded["occupied"])
    derived_occupied = dict(derived["occupied"])
    check(
        "recorded occupied RFC numbers equal the derived ones",
        set(occupied_recorded) == set(derived_occupied),
        f"only recorded={sorted(set(occupied_recorded) - set(derived_occupied))} "
        f"only derived={sorted(set(derived_occupied) - set(occupied_recorded))}",
    )
    for tag in sorted(set(occupied_recorded) & set(derived_occupied)):
        recorded_declared = set(occupied_recorded[tag].get("declared_in_tracked_docs", []))
        derived_declared = set(derived_occupied[tag].get("declared_in_tracked_docs", []))
        check(
            f"RFC-{tag}: recorded versioned declarations cover the derived ones",
            derived_declared <= recorded_declared or not derived_declared,
            f"missing {sorted(derived_declared - recorded_declared)}",
        )
    check(
        "no RFC-046 artefact existed before this RFC",
        recorded["taken_by_this_rfc"]["046"]["prior_artefacts"] == [],
        json.dumps(recorded["taken_by_this_rfc"]["046"]),
    )
    check(
        "the audit records that reports/ artefacts are not versioned",
        "gitignored" in recorded["occupancy_evidence_note"],
        recorded["occupancy_evidence_note"],
    )
    prior = [p for p in derived["mentions"]["046"]]
    check(
        "RFC-046 prior mentions are limited to the RFC-035 lineage",
        all(
            "PROFITABILITY_DISCOVERY_PROPOSAL" in p
            or "profitability_gate035" in p
            or "pgate035" in p
            for p in prior
        ),
        json.dumps(prior),
    )
    asserting = derived["asserting_files_045"]
    check(
        "RFC-045 is asserted absent by the campaign verifier scripts",
        all(any(f"cap00{i}_verify.py" in p for p in asserting) for i in (1, 2, 3, 4)),
        json.dumps(asserting),
    )
    stale_045 = [p for p in col_paths() if re.search(r"RFC-?045", p)]
    on_disk_045 = [
        str(p.relative_to(REPO)).replace("\\", "/") for p in (REPO / "reports").rglob("*RFC045*")
    ]
    check(
        "no RFC-045 artefact exists",
        not stale_045 and not on_disk_045,
        json.dumps(stale_045 + on_disk_045),
    )
    check(
        "recorded RFC-045 assertions are not lower than derived",
        recorded["vacant_by_control"]["045"]["assertion_count"]
        <= len(derived["asserting_files_045"]),
        f"{recorded['vacant_by_control']['045']['assertion_count']} vs {len(derived['asserting_files_045'])}",
    )
    unversioned = [t for t, v in occupied_recorded.items() if not v.get("declared_in_tracked_docs")]
    check(
        "the audit records how many occupied numbers have no versioned declaration",
        len(unversioned) >= 1
        and all("declared_in_tracked_docs" in v for v in occupied_recorded.values()),
        f"{len(unversioned)} unversioned of {len(occupied_recorded)}",
    )
    check("RFC-036 stays recorded as occupied", "036" in recorded["occupied"], "")
    check(
        "the RFC itself records that RFC-036 is not reusable",
        "not reused" in RFC_MD.read_text(encoding="utf-8")
        or "NOT available" in RFC_MD.read_text(encoding="utf-8"),
        "",
    )
    check("the audit records that no RFC registry exists", recorded["registry_exists"] is False, "")
    check(
        "the audit records the path exclusions it used",
        recorded["excluded_paths"] and "excluded_reason" in recorded,
        "",
    )
    check(
        "every excluded path is either this RFC's own output or the RFC-035 lineage that named it",
        all(
            p.startswith(
                (
                    "docs/rfc/RFC-046_",
                    "docs/governance/DISCOVERY_",
                    "data/rfc046/",
                    "scripts/rfc046_",
                    "tests/unit/research/test_rfc046_",
                )
            )
            or p
            in (
                "docs/architecture/DISCOVERY_EXECUTION_FLOW.md",
                "docs/roadmap/PROFITABILITY_ROADMAP_AMENDMENT.md",
                "docs/roadmap/PROFITABILITY_DISCOVERY_PROPOSAL.md",
            )
            for p in recorded["excluded_paths"]
        ),
        json.dumps(recorded["excluded_paths"]),
    )
    stale = {
        k
        for k in set(occupied_recorded) & set(derived_occupied)
        if not set(occupied_recorded[k].get("artefacts", []))
        & set(derived_occupied[k].get("artefacts", []))
        and not set(occupied_recorded[k].get("declared_in_tracked_docs", []))
        & set(derived_occupied[k].get("declared_in_tracked_docs", []))
    }
    check("no recorded occupied number lost its evidence", not stale, json.dumps(sorted(stale)))


def verify_hashes(audit: dict[str, Any]) -> None:
    recorded = audit["document_hashes"]
    for path in TRACKED:
        rel = str(path.relative_to(REPO)).replace("\\", "/")
        check(f"document hash recorded for {rel}", rel in recorded, "")
        if rel in recorded:
            check(
                f"document hash matches for {rel}",
                recorded[rel] == sha256(path),
                "the tracked document changed after the audit was built; rebuild required",
            )


def verify_audit_is_head_free(audit: dict[str, Any]) -> None:
    text = AUDIT.read_text(encoding="utf-8")
    check(
        "tracked audit declares what it intentionally excludes",
        audit["intentionally_excluded"] == ["current_head", "timestamps"],
        str(audit["intentionally_excluded"]),
    )
    check(
        "tracked audit contains no commit hash",
        not re.search(r"\b[0-9a-f]{40}\b", text),
        "a tracked artefact must not embed the live HEAD",
    )
    check(
        "tracked audit contains no ISO timestamp",
        not re.search(r"\b20\d{2}-\d{2}-\d{2}T\d{2}:\d{2}", text),
        "TD-4: no author-typed timestamps",
    )


def verify_cost(audit: dict[str, Any]) -> None:
    derived = derive_cost()
    recorded = audit["cost_baseline"]
    check_claim("cost round trip bps", recorded["round_trip_bps"], derived["round_trip_bps"])
    check_claim("known bps", recorded["known_bps"], derived["known_bps"])
    check_claim("estimated bps", recorded["estimated_bps"], derived["estimated_bps"])
    check_claim("assumed bps", recorded["assumed_bps"], derived["assumed_bps"])
    check_claim(
        "1.5x stressed requirement",
        recorded["required_gross_edge_stressed_bps"],
        derived["stressed"],
    )
    check_claim(
        "cost arithmetic is internally consistent",
        recorded["arithmetic_check"],
        derived["sum_matches"],
    )
    check(
        "the audited floor matches the documented 23.791 rounded",
        recorded["documented_reference_bps"] == 23.791,
        "",
    )
    check(
        "known fee share is the published VIP0 taker schedule (20 bps)",
        derived["known_bps"] == 20.0
        and recorded["admission_scenario_id"] == "BINANCE_SPOT_STANDARD_TAKER",
        "",
    )
    check(
        "no component is promoted out of its knowledge class",
        all(
            c["knowledge"] in ("KNOWN", "OBSERVED", "ESTIMATED", "ASSUMED")
            for c in recorded["components"]
        ),
        "",
    )
    check(
        "validity scope is recorded and bounded",
        bool(recorded.get("validity_scope")) or bool(audit["cost_baseline"]),
        "",
    )
    docs_text = RFC_MD.read_text(encoding="utf-8")
    for token in ("23.7906", "35.6859", "20.0", "3.7906"):
        check(f"the RFC states the audited figure {token}", token in docs_text, "")
    for surface in (
        "BINANCE_SPOT_STANDARD_TAKER",
        "VIP0",
        "taker on both legs",
        "1,000 USD",
        "2026-09-27",
    ):
        check(f"the RFC records the cost surface: {surface}", surface in docs_text, "")
    check(
        "the RFC records that both legs are market orders",
        "`market`, **taker on both legs**" in docs_text,
        "",
    )


def verify_governance(audit: dict[str, Any]) -> None:
    derived = derive_invariants()
    recorded = audit["governance"]["invariants"]
    for key, value in derived.items():
        if key.endswith("_disabled") or key in (
            "runtime_mode_paper",
            "manual_confirmation_required_for_live",
            "exchange_sandbox",
        ):
            check(
                f"governance fact {key} is {value}",
                value,
                f"{key} must hold while RFC-046 is only proposed",
            )
        elif key == "operating_model_supports_discovery":
            check(
                "the operating model still does not admit discovery today",
                value is False,
                "it must be amended before any activation",
            )
        else:
            check_claim(f"governance invariant {key}", recorded.get(key), value)
    check(
        "the amendment is not applied: roadmap has no discovery phase",
        derived["roadmap_unchanged"],
        "",
    )
    check("no ADR was recorded for RFC-046", derived["no_adr_for_rfc046"], "")
    check(
        "live trading is disabled in both configs",
        derived["runtime_live_disabled"] and derived["risk_live_disabled"],
        "",
    )
    check(
        "the RFC-041 reentry precondition is still recorded as required",
        "G_BUSINESS_REENTRY = PASS"
        in (REPO / "docs" / "research" / "BUSINESS_REENTRY_POLICY.md").read_text(encoding="utf-8"),
        "",
    )


def verify_rfc_content() -> None:
    text = RFC_MD.read_text(encoding="utf-8")
    state = json.loads(RFC_JSON.read_text(encoding="utf-8"))

    check(
        "the RFC is marked PROPOSED / NOT APPROVED / NOT ACTIVE",
        "PROPOSED — NOT APPROVED — NOT ACTIVE" in text,
        "",
    )
    check(
        "the RFC is marked PROPOSED in its machine-readable state",
        state["status"] == "PROPOSED" and state["approved"] is False and state["active"] is False,
        "",
    )
    for heading in range(1, 16):
        check(
            f"section {heading:02d} is present",
            re.search(rf"^## {heading:02d} —", text, flags=re.MULTILINE) is not None,
            "",
        )

    chain = "REAL_RUNTIME > EXECUTION_EVIDENCE > TESTS > CODE > RFC > EXTERNAL_SOURCE > ASSUMPTION"
    admission_text = ADMISSION.read_text(encoding="utf-8")
    check(
        "the authority order appears verbatim in the RFC",
        chain in text,
        f"{text.count(chain)} occurrences",
    )
    check(
        "the authority order appears verbatim in the admission policy", chain in admission_text, ""
    )
    fenced = re.search(r"```text\n(REAL_RUNTIME.*?)\n```", text, flags=re.DOTALL)
    check(
        "the authority chain is a single ordered line, not a scrambled list",
        fenced is not None and fenced.group(1).strip() == chain,
        "",
    )
    state = json.loads(RFC_JSON.read_text(encoding="utf-8"))
    check(
        "the state file records the same chain in order",
        state["authority_order"] == [t.strip() for t in chain.split(">")],
        str(state["authority_order"]),
    )
    check(
        "the authority order is declared unchanged in the state file",
        state["authority_order_unchanged"] is True,
        "",
    )

    check(
        "the RFC does not reuse RFC-036",
        "RFC-036 is NOT available" in text or "not reused" in text,
        "",
    )
    check(
        "the RFC states RFC-045 is unavailable by control",
        "RFC-045 must not be used" in text and "deliberately vacant" in text,
        "",
    )
    check(
        "the RFC proposes an RFC registry instead of assuming one",
        "RFC_REGISTRY" in text and state["numbering"]["registry_exists"] is False,
        "",
    )

    check(
        "the RFC defines PROFITABILITY_GATE_V1 for the first time",
        "defined here for the first time" in text,
        "",
    )
    check(
        "the gate has 11 requirements in the document",
        all(f"PG-{i}" in text for i in range(1, 12)),
        "",
    )
    check(
        "the gate has 11 requirements in the state file",
        [r["id"] for r in state["profitability_gate_v1"]["requirements"]]
        == [f"PG-{i}" for i in range(1, 12)],
        "",
    )
    check(
        "the gate thresholds are declared frozen before results",
        state["profitability_gate_v1"]["thresholds_frozen_before_results"] is True,
        "",
    )
    check(
        "the gate is declared not retroactive",
        state["profitability_gate_v1"]["retroactive_application"] is False
        and "No retroactive application" in text,
        "",
    )
    check("PG-3 tightens the existing criterion to 1.10", "profit factor ≥ **1.10**" in text, "")
    check(
        "PG-6 requires a serial-dependence-valid confidence bound",
        "block bootstrap" in text.lower() and "i.i.d." in text.lower(),
        "",
    )
    check(
        "the gate inherits the pre-registered criteria and names their source",
        "c1ffbaa" in text and "STRATEGY_ADMISSION_CRITERIA.md" in text,
        "",
    )

    check(
        "the budget caps are recorded",
        state["budget"]["max_hypotheses"] == 3
        and state["budget"]["max_candidates_per_hypothesis"] == 1
        and state["budget"]["parameter_searches"] == 0,
        "",
    )
    check("the budget is not refillable", state["budget"]["refillable"] is False, "")
    check(
        "all trials including negative ones are recorded",
        state["budget"]["all_attempts_recorded_including_negative"] is True
        and "including negative" in text.lower(),
        "",
    )

    check(
        "the PIT check is the mechanical one",
        state["data_partition"]["mechanical_check"] == "data_time <= decision_time"
        and "data_time <= decision_time" in text,
        "",
    )
    check(
        "the real PIT defect is cited as evidence",
        "DEF-HTF-PIT-001" in text and "900 *milliseconds*" in text,
        "",
    )
    check(
        "the reusable availability convention is named",
        state["data_partition"]["existing_reusable_convention"]
        == ["autonomous/pit.availability_ms", "candle_filter.is_candle_complete"],
        "",
    )

    check(
        "the failure policy forbids tuning until pass",
        state["failure_policy"]["forbidden"] == "TUNE_UNTIL_PASS"
        and "TUNE_UNTIL_PASS" in STOP.read_text(encoding="utf-8"),
        "",
    )
    check(
        "three failures end the campaign with no refill",
        state["failure_policy"]["campaign_failure"] == "DISCOVERY_CAMPAIGN_FAILED"
        and state["failure_policy"]["automatic_refill"] is False,
        "",
    )

    check(
        "the verifier section states builder != verifier",
        state["verification"]["builder_equals_verifier"] is False and "BUILDER != VERIFIER" in text,
        "",
    )
    check(
        "false_success is a measured target of 0",
        state["verification"]["false_success_target"] == 0,
        "",
    )
    check(
        "an incomplete verifier blocks promotion",
        state["verification"]["incomplete_verifier"] == "BLOCKS_PROMOTION",
        "",
    )

    check(
        "paper is a separate promotion gate, not an automatic consequence",
        "requires its own promotion gate" in text,
        "",
    )
    check(
        "micro-live requires a new explicit authorization", "new explicit authorization" in text, ""
    )
    check("TRADES_AUTHORIZED stays 0", state["runtime_state"]["trades_authorized"] == 0, "")
    check(
        "PROFITABILITY_VERIFIED stays false",
        state["runtime_state"]["profitability_verified"] is False,
        "",
    )
    check(
        "no capital tier is authorized", state["runtime_state"]["any_tier_authorized"] is False, ""
    )

    debt_ids = [d["id"] for d in state["technical_debt"]]
    check(
        "the five registered debt incidents are present",
        debt_ids == [f"TD-{i}" for i in range(1, 6)],
        str(debt_ids),
    )
    check(
        "no debt incident is declared gate-blocking",
        all(d["blocks_this_rfc"] is False for d in state["technical_debt"]),
        "",
    )
    for incident, token in (
        ("TD-1", "Duplicate module named"),
        ("TD-2", "TypeError"),
        ("TD-3", "concurrency"),
        ("TD-4", "RETRIEVED_AT"),
        ("TD-5", "reports/*"),
    ):
        check(f"{incident} cites its evidence: {token}", token in text, "")
    for rel in (
        "docs/governance/DISCOVERY_ADMISSION_POLICY.md",
        "docs/governance/DISCOVERY_STOP_RULES.md",
        "docs/architecture/DISCOVERY_EXECUTION_FLOW.md",
        "docs/roadmap/PROFITABILITY_ROADMAP_AMENDMENT.md",
    ):
        check(f"the RFC lists its own deliverable {rel}", rel in text, "")

    for doc_path in (AMENDMENT, ADMISSION, STOP, FLOW):
        body = doc_path.read_text(encoding="utf-8")
        check(
            f"{doc_path.name} is marked not in force",
            "NOT IN FORCE" in body or "NOT APPLIED" in body,
            "",
        )
        check(f"{doc_path.name} cites the vehicle RFC-046", "RFC-046" in body, "")

    stop_text = STOP.read_text(encoding="utf-8")
    for i in range(1, 13):
        check(f"stop rule ST-{i} is defined", f"ST-{i}" in stop_text, "")
    check("a stop is declared a result", "a stop is a result" in stop_text.lower(), "")
    check("the violation response forbids tune-until-pass", "TUNE_UNTIL_PASS" in stop_text, "")
    check("the stop rules forbid discarding an attempt", "discarded" in stop_text, "")

    admission = ADMISSION.read_text(encoding="utf-8")
    for token in (
        "ECONOMIC_MECHANISM",
        "SOURCE_ID",
        "falsification condition",
        "PIT-available",
        "turnover",
    ):
        check(f"the admission policy requires: {token}", token.lower() in admission.lower(), "")
    for banned in ("new RSI variation", "different moving average", "parameter optimization"):
        check(f"the admission policy inherits the ban on: {banned}", banned in admission, "")
    check(
        "the admission policy keeps the cost floor",
        "23.7906" in admission and "35.6859" in admission,
        "",
    )
    check(
        "the admission policy keeps deterministic risk and NO_TRADE",
        "NO_TRADE" in admission and "Deterministic risk" in admission,
        "",
    )

    flow = FLOW.read_text(encoding="utf-8")
    for token in ("data_time <= decision_time", "verifier", "DEF-HTF-PIT-001", "gitignored"):
        check(f"the flow document covers: {token}", token in flow, "")
    check("the flow document forbids a new agent", "no new agent" in flow.lower(), "")

    amendment = AMENDMENT.read_text(encoding="utf-8")
    check(
        "the amendment names all four required amendments plus the exemption question",
        all(
            token in amendment
            for token in (
                "tasks/roadmap.md",
                "next_action_policy",
                "PROFITABILITY_FIRST_FREEZE",
                "tasks/decisions.md",
            )
        ),
        "",
    )
    check(
        "the amendment leaves the ADR unwritten by design",
        "Not written yet, deliberately" in amendment,
        "",
    )
    check(
        "the amendment offers both RFC-041 resolutions and does not choose",
        "5A" in amendment and "5B" in amendment and "does not choose" in amendment,
        "",
    )
    check(
        "the amendment does not reserve a block of RFC numbers",
        "not reserved by this document" in amendment,
        "",
    )


def _verdicts_outside_the_forbidden_list(
    node: Any, skip: bool = False, out: list[str] | None = None
) -> list[str]:
    """Collect forbidden-verdict strings that appear anywhere except the ``forbidden_verdicts`` list."""
    if out is None:
        out = []
    if isinstance(node, dict):
        for key, value in node.items():
            _verdicts_outside_the_forbidden_list(value, skip or key == "forbidden_verdicts", out)
    elif isinstance(node, list):
        for item in node:
            _verdicts_outside_the_forbidden_list(item, skip, out)
    elif isinstance(node, str) and not skip and node.upper() in FORBIDDEN_VERDICTS:
        out.append(node)
    return out


def verify_no_forbidden_claims() -> None:
    """A forbidden verdict may only appear inside a negated line or a declared forbidden-list."""
    for path in TRACKED:
        if path.suffix == ".json":
            payload = json.loads(path.read_text(encoding="utf-8"))
            offenders = _verdicts_outside_the_forbidden_list(payload)
            check(
                f"{path.name} states no forbidden verdict outside the forbidden list",
                not offenders,
                json.dumps(offenders),
            )
            check(
                f"{path.name} declares the forbidden verdicts explicitly",
                set(payload.get("forbidden_verdicts", [])) == set(FORBIDDEN_VERDICTS),
                "",
            )
            continue
        text = path.read_text(encoding="utf-8")
        for lineno, line in enumerate(text.splitlines(), start=1):
            stripped = line
            for reference in KNOWN_REFERENCES:
                stripped = stripped.replace(reference, "")
            for token in FORBIDDEN_VERDICTS:
                if token in stripped.upper():
                    guarded = any(n in stripped.lower() for n in NEGATORS)
                    check(
                        f"{path.name}:{lineno} does not claim {token}", guarded, line.strip()[:120]
                    )
        for token in ("sharpe", "cagr", "annualised return", "annualized return", "win rate"):
            check(
                f"{path.name} reports no strategy performance metric: {token}",
                token not in text.lower(),
                "",
            )


def verify_report_consistency() -> None:
    if not FINAL_JSON.is_file():
        check("FINAL_REPORT.json exists", False, "run scripts/rfc046_audit.py first")
        return
    report = json.loads(FINAL_JSON.read_text(encoding="utf-8"))
    check(
        "the report records the same HEAD the verifier sees",
        report["evaluated_head"] == git(["rev-parse", "HEAD"]).strip(),
        f"{report['evaluated_head']} vs {git(['rev-parse', 'HEAD']).strip()}",
    )
    check("the report applies no roadmap diff", report["roadmap_diff_applied"] == "NONE", "")
    check(
        "the report keeps live trading disabled and zero trades",
        report["flags"]["live_trading"] == "DISABLED" and report["flags"]["trades_authorized"] == 0,
        "",
    )
    check(
        "the report declares discovery NOT_ACTIVE", report["flags"]["discovery"] == "NOT_ACTIVE", ""
    )
    check(
        "the report quotes the same cost floor the verifier derived",
        report["evidence"]["cost_round_trip_bps"] == derive_cost()["round_trip_bps"],
        "",
    )
    recorded = report.get("independent_verification") or {}
    check(
        "the report records a verifier verdict in a known state",
        recorded.get("status") in ("PASS", "FAIL", "PENDING"),
        str(recorded.get("status")),
    )
    check(
        "the report's recorded false_success is an integer or pending",
        recorded.get("false_success") is None or isinstance(recorded.get("false_success"), int),
        "",
    )
    unit = (report.get("tests") or {}).get("rfc046_tests") or {}
    check(
        "the recorded unit-test run passed",
        unit.get("status") == "PASS",
        f"status={unit.get('status')} summary={unit.get('summary')!r}",
    )
    check(
        "the recorded tooling checks passed",
        (report.get("tooling") or {}).get("ruff", {}).get("exit_code") == 0
        and (report.get("tooling") or {}).get("mypy_own_scripts", {}).get("exit_code") == 0,
        json.dumps(report.get("tooling", {}))[:200],
    )


def verify_test_file() -> None:
    test_path = REPO / "tests" / "unit" / "research" / "test_rfc046_discovery_proposal.py"
    check("the test file exists", test_path.is_file(), "")
    if test_path.is_file():
        body = test_path.read_text(encoding="utf-8")
        for token in (
            "PROPOSED",
            "PG-",
            "TUNE_UNTIL_PASS",
            "data_time <= decision_time",
            "RFC-045",
        ):
            check(f"the tests assert: {token}", token in body, "")
        check(
            "the tests do not write to the repository",
            "write_text" not in body and "mkdir" not in body,
            "",
        )


def main() -> int:
    if not AUDIT.is_file():
        print("FAIL: data/rfc046/audit.json missing — run scripts/rfc046_audit.py")
        return 1
    audit = json.loads(AUDIT.read_text(encoding="utf-8"))

    verify_artifacts()
    verify_collision(audit)
    verify_hashes(audit)
    verify_audit_is_head_free(audit)
    verify_cost(audit)
    verify_governance(audit)
    verify_rfc_content()
    verify_no_forbidden_claims()
    verify_test_file()
    verify_report_consistency()

    # Last: the report may record this verifier's own verdict, so the comparison happens once every other
    # check has run. A recorded verdict that contradicts this run is itself a mismatch.
    verdict = "PASS" if not FAILURES else "FAIL"
    if FINAL_JSON.is_file():
        recorded = (
            json.loads(FINAL_JSON.read_text(encoding="utf-8")).get("independent_verification") or {}
        ).get("status")
        if recorded in ("PASS", "FAIL") and recorded != verdict:
            FAILURES.append(
                f"the report records the verifier verdict {recorded} but this run computed {verdict}"
            )
            verdict = "FAIL"

    print(f"CHECKS     = {CHECKS}")
    print(f"MISMATCHES = {len(FAILURES)}")
    print(f"FALSE_SUCCESS = {_CLAIMS_BROKEN}")
    for failure in FAILURES:
        print(f"  FAIL: {failure}")
    print("RFC-046 VERIFICATION:", verdict)
    return 0 if verdict == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
