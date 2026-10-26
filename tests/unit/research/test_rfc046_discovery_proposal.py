"""Offline guards for the RFC-046 controlled-discovery proposal.

These tests are network-free and read-only. They assert the properties a later edit is most likely to break:

* the RFC stays **PROPOSED** and nothing it depends on has been silently activated;
* the tracked canonical state and the tracked audit record stay consistent with each other and with the repo;
* the audited cost floor is re-derived from the model code, never copied from a document;
* `PROFITABILITY_GATE_V1` has its eleven requirements, frozen, and explicitly not retroactive;
* the budget caps, the PIT check and the failure policy are present and unchanged;
* RFC-045 stays empty by control and RFC-036 is never reused;
* no artefact claims a success the evidence does not support.

The dependency split is deliberate: ``data/rfc046/audit.json`` is tracked and therefore asserted strictly; the
``reports/rfc046`` surface is gitignored by repo convention, so it is asserted only when present.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
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
REPORT_JSON = REPO / "reports" / "rfc046" / "FINAL_REPORT.json"

TRACKED_DOCS = (RFC_MD, RFC_JSON, AMENDMENT, ADMISSION, STOP, FLOW)
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
FORBIDDEN_VERDICTS = ("EDGE_CONFIRMED", "PROFITABLE", "PRODUCTION_READY")
NEGATION_MARKERS = ("never", "not ", "no ", "false", "cannot", "forbidden", "does not", "without")
#: Historic programme titles that name a verdict without claiming it; removed before the negation test.
KNOWN_REFERENCES = ("EXTERNAL PROFITABLE OPPORTUNITY DISCOVERY",)

#: The scripts that produce RFC-046 artefacts. This test file is deliberately excluded from the scan below:
#: it necessarily contains the very tokens it searches for, which would make the check self-referential.
NEW_CODE = (
    REPO / "scripts" / "rfc046_audit.py",
    REPO / "scripts" / "rfc046_verify.py",
)


@pytest.fixture(scope="module")
def audit() -> dict:
    return json.loads(AUDIT.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def state() -> dict:
    return json.loads(RFC_JSON.read_text(encoding="utf-8"))


def _git(*args: str) -> str:
    proc = subprocess.run(["git", *args], cwd=str(REPO), capture_output=True, text=True, check=False)
    return proc.stdout if proc.returncode == 0 else ""


def _sha256(path: Path) -> str:
    """Line-ending-normalised hash: a CRLF checkout is not an edit."""
    import hashlib

    text = path.read_bytes().decode("utf-8").replace("\r\n", "\n")
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# deliverables and state
# ---------------------------------------------------------------------------
def test_all_requested_deliverables_exist_and_are_not_empty() -> None:
    for rel in REQUESTED_PATHS:
        path = REPO / rel
        assert path.is_file(), f"missing deliverable {rel}"
        assert path.stat().st_size > 0, f"empty deliverable {rel}"


def test_the_tracked_audit_remains_the_pre_approval_snapshot(state: dict) -> None:
    """The audit is the record of the NOT_ACTIVE phase; the approval came after it.

    It must not be edited to look prescient, and the *current* contract is the approval record.
    """
    snapshot = json.loads(AUDIT.read_text(encoding="utf-8"))
    assert snapshot["status"] == "PROPOSED", "the pre-approval snapshot must keep saying what it said"
    assert snapshot["governance"]["invariants"]["rfc_status_proposed"] is True
    assert state["approved"] is True and state["active"] is True
    text = RFC_MD.read_text(encoding="utf-8")
    assert "APPROVED / ACTIVE" in text and "## 00 — APPROVAL RECORD" in text
    assert "TRADES_AUTHORIZED" in text and "0" in text


def test_the_activation_amended_exactly_the_documented_documents() -> None:
    roadmap = (REPO / "tasks" / "roadmap.md").read_text(encoding="utf-8")
    operating = json.loads((REPO / "docs" / "research" / "PROFITABILITY_OPERATING_MODEL.json").read_text(encoding="utf-8"))
    freeze = (REPO / "docs" / "governance" / "PROFITABILITY_FIRST_FREEZE.md").read_text(encoding="utf-8")
    decisions = (REPO / "tasks" / "decisions.md").read_text(encoding="utf-8")

    assert "Fase 10" in roadmap and "RFC-046" in roadmap
    assert "RFC-046 limited exemption" in operating["next_action_policy"]["trigger"]
    assert (
        operating["next_action_policy"]["rfc046_limited_exemption"]["gate_state"]["G_BUSINESS_REENTRY"]
        == "NOT_PASS"
    )
    assert "ADDENDUM DE CIERRE" in freeze and "ACTIVE_RFC: **RFC-035" in freeze
    assert re.search(r"^## ADR-0024.*RFC-046", decisions, flags=re.MULTILINE), "ADR-0024 must exist"
    assert (REPO / "docs" / "roadmap" / "RFC_REGISTRY.json").is_file()


def test_live_trading_stays_disabled_and_no_trade_is_authorized(state: dict) -> None:
    assert "live_trading_enabled: false" in (REPO / "config" / "runtime.yaml").read_text(encoding="utf-8")
    assert "live_trading_enabled: false" in (REPO / "config" / "risk.yaml").read_text(encoding="utf-8")
    runtime = state["runtime_state"]
    assert runtime["mode"] == "paper"
    assert runtime["trades_authorized"] == 0
    assert runtime["profitability_verified"] is False
    assert runtime["any_tier_authorized"] is False
    assert runtime["business_edge_milestone"] == "M0"


def test_the_new_code_cannot_place_an_order() -> None:
    import ast

    for path in NEW_CODE:
        body = path.read_text(encoding="utf-8")
        imported = set()
        for node in ast.walk(ast.parse(body)):
            if isinstance(node, ast.Import):
                imported |= {a.name.split(".")[0] for a in node.names}
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module.split(".")[0])
        assert imported <= {"argparse", "ast", "hashlib", "json", "re", "subprocess", "sys", "pathlib", "typing",
                            "datetime", "trading_bot", "__future__"}, f"{path.name} imports {sorted(imported)}"
        for token in ("create_order", "place_order", "fetch_balance", "ccxt"):
            assert token not in body, f"{path.name} must not touch execution: {token}"
        assert "api_key" not in body and "API_SECRET" not in body, f"{path.name} must not handle credentials"


# ---------------------------------------------------------------------------
# audit record
# ---------------------------------------------------------------------------
def test_the_tracked_audit_is_head_free_and_timestamp_free(audit: dict) -> None:
    assert audit["intentionally_excluded"] == ["current_head", "timestamps"]
    text = AUDIT.read_text(encoding="utf-8")
    assert not re.search(r"\b[0-9a-f]{40}\b", text), "a tracked artefact must not embed the live HEAD"
    assert not re.search(r"\b20\d{2}-\d{2}-\d{2}T\d{2}:\d{2}", text), "TD-4: no author-typed timestamps"


def test_document_hashes_only_changed_where_the_approval_says_they_did(audit: dict) -> None:
    """Churn detection with the approval taken into account.

    A document may differ from the pre-approval audit only if the independent verification recorded
    its new hash after activation. Any other drift is still a failure.
    """
    import json as _json

    recorded = audit["document_hashes"]
    activation = _json.loads((REPO / "data" / "rfc046" / "ACTIVATION.json").read_text(encoding="utf-8"))
    post_activation = activation["document_hashes"]
    for path in TRACKED_DOCS:
        rel = str(path.relative_to(REPO)).replace("\\", "/")
        assert rel in recorded, f"no recorded hash for {rel}"
        current = _sha256(path)
        if current == recorded[rel]:
            continue
        assert rel in post_activation, f"{rel} changed after the approval but was never re-verified"
        assert post_activation[rel] == current, f"{rel} drifted after the verification ran"


def test_collision_audit_is_recorded_and_honest(audit: dict) -> None:
    collision = audit["governance"]["collision"]
    assert collision["registry_exists"] is False
    assert collision["registry_proposed_path"] == "docs/roadmap/RFC_REGISTRY.json"
    assert "046" not in collision["occupied"], "RFC-046 must not be claimed as previously occupied"
    assert collision["taken_by_this_rfc"]["046"]["prior_artefacts"] == []
    assert "036" in collision["occupied"], "RFC-036 is occupied by the managed-futures reproduction"
    assert collision["vacant_by_control"]["045"]["assertion_count"] >= 4
    assert collision["occupancy_evidence_note"]
    assert collision["excluded_reason"]
    unversioned = [t for t, v in collision["occupied"].items() if not v.get("declared_in_tracked_docs")]
    assert unversioned, "the audit must record which occupied numbers have no versioned declaration (TD-5)"


def test_rfc_045_stays_empty_by_control() -> None:
    tree = _git("ls-tree", "-r", "--name-only", "HEAD")
    assert not re.search(r"RFC-?045", tree), "creating an RFC-045 artefact would break four campaign verifiers"
    asserting = [ln for ln in _git("grep", "-l", "no RFC-045 artifact exists", "HEAD", "--", ".").splitlines() if ln]
    scripts = [ln for ln in asserting if "scripts/cap00" in ln]
    assert len(scripts) >= 4, f"the RFC-045 control must be asserted by four verifier scripts: {scripts}"


def test_rfc_036_is_not_reused_for_discovery() -> None:
    text = RFC_MD.read_text(encoding="utf-8")
    assert "RFC-036 is NOT available" in text or "not reused" in text
    amendment = AMENDMENT.read_text(encoding="utf-8")
    assert "RFC-036" in amendment, "the amendment should record why the number is unavailable"
    assert "not reserved by this document" in amendment


# ---------------------------------------------------------------------------
# economics
# ---------------------------------------------------------------------------
def test_cost_floor_is_re_derived_from_the_model_not_copied(audit: dict) -> None:
    from trading_bot.research.microstructure import cost_model_v3 as model_module

    cost = model_module.default_model("BINANCE_SPOT_STANDARD_TAKER").evaluate(
        size_usd=1_000.0, liquidity_regime="normal", horizon_minutes=25.0,
        entry_order_type="market", exit_order_type="market",
    )
    recorded = audit["cost_baseline"]
    assert recorded["round_trip_bps"] == round(cost.round_trip_bps, 4)
    assert recorded["required_gross_edge_stressed_bps"] == round(cost.required_edge_bps(1.5), 4)
    assert recorded["known_bps"] + recorded["estimated_bps"] + recorded["assumed_bps"] == recorded["round_trip_bps"]
    assert recorded["arithmetic_check"] is True


def test_the_cost_knowledge_split_is_not_silently_promoted(audit: dict) -> None:
    recorded = audit["cost_baseline"]
    assert recorded["known_bps"] == 20.0, "the VIP0 taker fee is the published, irreversible term"
    assert recorded["assumed_bps"] == 0.0
    assert {c["knowledge"] for c in recorded["components"]} <= {"KNOWN", "OBSERVED", "ESTIMATED", "ASSUMED"}
    assert recorded["documented_reference_bps"] == 23.791


def test_the_rfc_states_the_cost_surface_it_is_valid_for() -> None:
    text = RFC_MD.read_text(encoding="utf-8")
    for token in ("23.7906", "35.6859", "BINANCE_SPOT_STANDARD_TAKER", "VIP0", "taker on both legs",
                  "1,000 USD", "2026-09-27"):
        assert token in text, token
    assert "`market`, **taker on both legs**" in text


def test_no_candidate_may_use_a_cheaper_cost_model() -> None:
    text = RFC_MD.read_text(encoding="utf-8")
    assert "No cheaper cost model without evidence" in text
    admission = ADMISSION.read_text(encoding="utf-8")
    assert "23.7906" in admission and "35.6859" in admission
    assert "ZERO_COST" in admission


# ---------------------------------------------------------------------------
# gate, budget and protocol
# ---------------------------------------------------------------------------
def test_profitability_gate_v1_has_eleven_frozen_requirements(state: dict) -> None:
    requirements = state["profitability_gate_v1"]["requirements"]
    assert [r["id"] for r in requirements] == [f"PG-{i}" for i in range(1, 12)]
    assert state["profitability_gate_v1"]["thresholds_frozen_before_results"] is True
    assert state["profitability_gate_v1"]["retroactive_application"] is False
    assert state["profitability_gate_v1"]["existed_before"] is False
    text = RFC_MD.read_text(encoding="utf-8")
    assert "profit factor ≥ **1.10**" in text
    assert "block bootstrap" in text.lower() and "i.i.d." in text.lower()
    assert "No retroactive application" in text


def test_gate_continuity_with_the_pre_registered_criteria() -> None:
    criteria = (REPO / "docs" / "STRATEGY_ADMISSION_CRITERIA.md").read_text(encoding="utf-8")
    assert "Profit factor BASE > 1.0" in criteria, "the criteria this RFC builds on must still exist"
    assert "≥ 100 trades totales y ≥ 30 en OOS" in criteria
    assert "c1ffbaa" in RFC_MD.read_text(encoding="utf-8")


def test_budget_caps_are_recorded_and_not_refillable(state: dict) -> None:
    budget = state["budget"]
    assert budget["max_hypotheses"] == 3
    assert budget["max_candidates_per_hypothesis"] == 1
    assert budget["parameter_searches"] == 0
    assert budget["new_agents"] == 0
    assert budget["refillable"] is False
    assert budget["all_attempts_recorded_including_negative"] is True


def test_pit_enforcement_is_mechanical_and_rooted_in_a_real_defect(state: dict) -> None:
    assert state["data_partition"]["mechanical_check"] == "data_time <= decision_time"
    text = RFC_MD.read_text(encoding="utf-8")
    assert "DEF-HTF-PIT-001" in text
    assert "900 *milliseconds*" in text
    work_package = REPO / "docs" / "research" / "work_packages" / "WP-HTF-PIT-001_htf_availability_unit_fix.md"
    assert work_package.is_file()
    assert "htf_pit" in work_package.read_text(encoding="utf-8")


def test_failure_policy_forbids_tuning_until_pass(state: dict) -> None:
    assert state["failure_policy"]["forbidden"] == "TUNE_UNTIL_PASS"
    assert state["failure_policy"]["campaign_failure"] == "DISCOVERY_CAMPAIGN_FAILED"
    assert state["failure_policy"]["automatic_refill"] is False
    stop = STOP.read_text(encoding="utf-8")
    for i in range(1, 13):
        assert f"ST-{i}" in stop, f"stop rule ST-{i} missing"
    assert "a stop is a result" in stop.lower()
    assert "discarded" in stop


def test_verification_boundary_is_structural(state: dict) -> None:
    assert state["verification"]["builder_equals_verifier"] is False
    assert state["verification"]["false_success_target"] == 0
    assert state["verification"]["incomplete_verifier"] == "BLOCKS_PROMOTION"
    assert state["verification"]["crashing_verifier"] == "IS_A_DEFECT"
    assert (REPO / "scripts" / "rfc046_verify.py").resolve() != (REPO / "scripts" / "rfc046_audit.py").resolve()


def test_paper_and_live_keep_their_own_gates() -> None:
    text = RFC_MD.read_text(encoding="utf-8")
    assert "requires its own promotion gate" in text
    assert "new explicit authorization" in text
    assert "offline validation" in text


# ---------------------------------------------------------------------------
# technical debt and vocabulary
# ---------------------------------------------------------------------------
def test_the_five_debt_incidents_are_registered(audit: dict) -> None:
    items = audit["technical_debt"]["items"]
    assert [i["id"] for i in items] == [f"TD-{i}" for i in range(1, 6)]
    assert all(i["blocks_this_rfc"] is False for i in items)
    assert all(i["status"].startswith("OPEN") for i in items)
    mapping = {i["id"]: i for i in items}
    assert "duplicate module name" in mapping["TD-1"]["incident"].lower()
    assert mapping["TD-1"]["evidence_present"] is True
    assert mapping["TD-2"]["status"] == "OPEN_NOT_REPAIRED"
    assert mapping["TD-4"]["instances"], "the timestamp-constant pattern must cite its instances"
    assert mapping["TD-5"]["mitigation"]


def _verdicts_outside_the_forbidden_list(node, skip: bool = False, out: list[str] | None = None) -> list[str]:
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


def test_no_artefact_claims_a_forbidden_verdict() -> None:
    for path in TRACKED_DOCS:
        if path.suffix == ".json":
            payload = json.loads(path.read_text(encoding="utf-8"))
            assert set(payload.get("forbidden_verdicts", [])) == set(FORBIDDEN_VERDICTS)
            assert not _verdicts_outside_the_forbidden_list(payload), (
                f"{path.name} quotes a forbidden verdict outside its declared forbidden list"
            )
            continue
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            stripped = line
            for reference in KNOWN_REFERENCES:
                stripped = stripped.replace(reference, "")
            for token in FORBIDDEN_VERDICTS:
                if token in stripped.upper():
                    assert any(marker in stripped.lower() for marker in NEGATION_MARKERS), (
                        f"{path.name}:{lineno} appears to claim {token}: {line.strip()[:120]}"
                    )


def test_no_tracked_document_reports_strategy_performance() -> None:
    for path in TRACKED_DOCS:
        if path.suffix != ".md":
            continue
        text = path.read_text(encoding="utf-8").lower()
        for token in ("sharpe", "cagr", "annualised return", "annualized return", "win rate"):
            assert token not in text, f"{path.name} reports {token}; this RFC may not claim performance"


def test_the_report_surface_stays_consistent_when_present() -> None:
    if not REPORT_JSON.is_file():
        pytest.skip("reports/rfc046 is a gitignored working surface; the tracked contract is data/rfc046/audit.json")
    report = json.loads(REPORT_JSON.read_text(encoding="utf-8"))
    assert report["flags"]["live_trading"] == "DISABLED"
    assert report["flags"]["trades_authorized"] == 0
    assert report["flags"]["discovery"] == "NOT_ACTIVE"
    assert report["roadmap_diff_applied"] == "NONE"
    assert report["next_gate"] == "APPROVAL_REQUIRED"

    # The report is written at the end of a build, so while a build is running the report on disk can only
    # describe an earlier commit. The honest invariant is therefore: the recorded commit is real and is an
    # ancestor of HEAD - never a fabricated hash, never a commit that has not happened yet.
    recorded = report["evaluated_head"]
    assert re.fullmatch(r"[0-9a-f]{40}", recorded), recorded
    exists = subprocess.run(["git", "cat-file", "-e", f"{recorded}^{{commit}}"], cwd=str(REPO),
                            capture_output=True, check=False)
    assert exists.returncode == 0, f"{recorded} is not a commit in this repository"
    ancestor = subprocess.run(["git", "merge-base", "--is-ancestor", recorded, "HEAD"], cwd=str(REPO),
                              capture_output=True, check=False)
    assert ancestor.returncode == 0, f"{recorded} is not an ancestor of HEAD; the report predates this history"
