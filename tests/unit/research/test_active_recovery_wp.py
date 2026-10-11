"""Contract tests for POST RFC-049 / ACTIVE RECOVERY (WP-2 and WP-3).

These tests hold the two derived artefacts to what they claim:

* the campaign state view resolves a superseded frozen declaration by precedence
  and keeps the supersession trail (§WP-2);
* it fails visibly on an unresolved contradiction instead of picking a side;
* it cannot modify the sources it reads (immutability) and reproduces bit-for-bit
  (determinism);
* the ACTIVE economic audit reconstructs all 24 registered strategies, invents no
  metric, keeps its own mismatches declared and bounded, and reaches no positive
  net edge anywhere.

The scripts are imported as modules, so the tests exercise the same functions the
artefacts were produced by.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
RECOVERY = ROOT / "data" / "recovery"


def load_script(name: str):
    path = ROOT / "scripts" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def state_view():
    return load_script("campaign_state_view")


@pytest.fixture(scope="module")
def audit():
    return load_script("active_economic_audit")


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


# --------------------------------------------------------------------------- #
# WP-2 — campaign state view
# --------------------------------------------------------------------------- #


def test_state_view_is_deterministic(state_view):
    first = state_view.payload_hash(state_view.build())
    second = state_view.payload_hash(state_view.build())
    assert first == second

    stored = json.loads((RECOVERY / "CAMPAIGN_STATE_VIEW.json").read_text(encoding="utf-8"))
    assert stored["payload_sha256"] == first, "the committed view is stale: re-run scripts/campaign_state_view.py"


def test_state_view_does_not_modify_its_sources(state_view):
    paths = sorted({fact["path"] for spec in state_view.CAMPAIGNS for fact in spec["facts"]} | {state_view.DECISIONS})
    before = {rel: sha256(ROOT / rel) for rel in paths if (ROOT / rel).exists()}

    state_view.build()

    after = {rel: sha256(ROOT / rel) for rel in paths if (ROOT / rel).exists()}
    assert before == after, "the state view must be read-only"


def test_state_view_reports_sources_unchanged(state_view):
    payload = state_view.build()
    assert payload["sources_unchanged"] is True
    assert all(
        entry["sha256_before"] is None or entry["sha256_before"] == entry["sha256_after"]
        for entry in payload["sources"]
    )


@pytest.mark.parametrize("script", ["campaign_state_view", "active_economic_audit"])
def test_identity_hash_ignores_the_moment_but_not_the_findings(script):
    """The identity hash must be stable across commits and volatile inputs.

    ``head``/``branch``/``generated_at_utc`` and the per-file ``sources`` block describe the
    moment; a finding describes the state. Committing the artefact (which moves HEAD) or an
    unrelated lane writing its own file must not change the identity, and a real change to a
    finding must.
    """
    module = load_script(script)
    payload = module.build()
    baseline = module.payload_hash(payload)

    moment = {**payload, "head": "0" * 40, "branch": "other-branch",
              "generated_at_utc": "1999-01-01T00:00:00Z", "sources": []}
    assert module.payload_hash(moment) == baseline, "volatile fields leaked into the identity hash"

    changed = json.loads(json.dumps(payload))
    if "strategies" in changed:
        first = sorted(changed["strategies"])[0]
        changed["strategies"][first]["ledger_status"] = "PAPER_CANDIDATE"
    else:
        changed["campaigns"][0]["effective_state"]["NEXT_CAMPAIGN"] = "AUTHORIZED"
    assert module.payload_hash(changed) != baseline, "a changed finding must change the identity"


def test_frozen_declaration_is_superseded_not_current(state_view):
    payload = state_view.build()
    campaign = next(c for c in payload["campaigns"] if c["id"] == "RFC-049-DISCOVERY-2")

    # the current state comes from the latest ADR, not from the frozen manifest
    assert campaign["effective_state"]["NEXT_CAMPAIGN"] == "NOT_AUTHORIZED"
    assert campaign["effective_state"]["SEALED_OOS"] == "CANCELLED_NOT_OPENED"
    assert campaign["effective_state"]["TERMINAL_STATE"] == "DISCOVERY_CAMPAIGN_FAILED"
    assert campaign["governing_adr"]["adr"] == "ADR-0026"

    # the frozen gate says the opposite and is kept as a historical fact, never current
    frozen = next(f for f in campaign["facts"] if f["field"] == "AUTHORIZED")
    assert frozen["value"] is False
    assert frozen["priority"] == 4

    # ADR-0025 authorized the campaign and is recorded as superseded, not erased
    superseded = {(s["field"], s["value"]) for s in campaign["superseded_values"]}
    assert ("NEXT_CAMPAIGN", "AUTHORIZED") in superseded
    assert ("SEALED_OOS", "CLOSED") in superseded
    assert [entry["adr"] for entry in campaign["adr_history"]] == ["ADR-0025", "ADR-0026"]


def test_frozen_manifest_is_byte_identical(state_view):
    manifest = ROOT / "data" / "rfc049" / "PREREGISTRATION_MANIFEST.json"
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    # the closure promised the frozen declaration is not edited; the gate text is still there
    assert payload["gate"]["authorized"] is False
    assert "NOT_AUTHORIZED" in payload["gate"]["reason"]


def test_resolution_prefers_the_latest_adr(state_view):
    facts = [{"field": "X", "role": "P4_frozen_declaration", "value": "FROZEN", "present": True,
              "source": "f.json", "pointer": "a", "priority": 4}]
    history = [
        {"adr": "ADR-0010", "number": 10, "facts": {"X": "FIRST"}, "terminal_state_tokens": []},
        {"adr": "ADR-0011", "number": 11, "facts": {"X": "SECOND"}, "terminal_state_tokens": []},
    ]
    resolution = state_view.resolve_field("C", "X", facts, history)
    assert resolution["effective"] == "SECOND"
    assert resolution["contradiction"] is None
    assert {s["value"] for s in resolution["superseded"]} == {"FIRST", "FROZEN"}


def test_same_level_disagreement_is_an_unresolved_contradiction(state_view):
    facts = [
        {"field": "X", "role": "P2_campaign_record", "value": "A", "present": True,
         "source": "a.json", "pointer": "x", "priority": 2},
        {"field": "X", "role": "P2_campaign_record", "value": "B", "present": True,
         "source": "b.json", "pointer": "y", "priority": 2},
    ]
    resolution = state_view.resolve_field("C", "X", facts, [])
    assert resolution["effective"] is None
    assert resolution["contradiction"]["field"] == "X"
    assert {v["value"] for v in resolution["contradiction"]["values"]} == {"A", "B"}

    # the same values at the same level are agreement, not a contradiction
    agreeing = [dict(facts[0]), {**facts[1], "value": "A"}]
    assert state_view.resolve_field("C", "X", agreeing, [])["contradiction"] is None


def test_same_level_agreement_resolves(state_view):
    facts = [
        {"field": "STATE", "role": "P2_campaign_record", "value": "CLOSED", "present": True,
         "source": "a.json", "pointer": "x", "priority": 2},
        {"field": "STATE", "role": "P2_campaign_record", "value": "CLOSED", "present": True,
         "source": "b.json", "pointer": "y", "priority": 2},
    ]
    resolution = state_view.resolve_field("C", "STATE", facts, [])
    assert resolution["effective"] == "CLOSED"
    assert resolution["superseded"] == []


@pytest.mark.parametrize(
    ("recorded", "actual", "kind", "expected"),
    [
        ("abc", "abc", "STRICT", "VERIFIED"),
        ("abc", "def", "STRICT", "FAILED"),
        ("abc", "def", "APPEND_ONLY", "DRIFTED"),
        ("abc", None, "STRICT", "MISSING"),
        ("abc", None, "UNRESOLVED", "UNRESOLVED"),
    ],
)
def test_pin_grading(state_view, recorded, actual, kind, expected):
    assert state_view.judge_pin(recorded, actual, kind) == expected


def test_committed_view_is_consistent_and_makes_no_claim(state_view):
    payload = json.loads((RECOVERY / "CAMPAIGN_STATE_VIEW.json").read_text(encoding="utf-8"))
    assert payload["status"] in {"CONSISTENT", "CONSISTENT_WITH_ADVISORIES"}
    assert payload["contradictions"] == []
    assert payload["failed_invariants"] == []
    by_id = {item["id"]: item for item in payload["invariants"]}
    for required in ("I1_frozen_pins_verify", "I2_builder_is_not_verifier", "I3_no_profitability_claim",
                     "I4_sealed_window_never_read", "I5_governance_mirrors_agree"):
        assert by_id[required]["result"] == "PASS", by_id[required]
    # a strict pin that fails would make the view contradictory; only append-only drift is tolerated
    assert not [p for p in payload["integrity"]["pins"] if p["result"] in {"FAILED", "MISSING"}]
    # a pin that could not be checked says so and names nothing: it is never dressed as verified
    for pin in payload["integrity"]["pins"]:
        if pin["result"] == "UNRESOLVED":
            assert pin["path"] is None and pin["actual_sha256_lf"] is None, pin
        else:
            assert pin["actual_sha256_lf"], pin


def test_the_view_declares_where_every_input_comes_from():
    """WP-8C: the certified state names every input's class, authority and evidence copy."""
    payload = json.loads((RECOVERY / "CAMPAIGN_STATE_VIEW.json").read_text(encoding="utf-8"))
    declared = payload["input_authority"]["declared_inputs"]
    assert {record["class"] for record in declared.values()} == {
        "COMMITTED", "EXTERNAL_GENERATED", "EXTERNAL_LIVE", "EXTERNAL_DATASET"}

    # the forward lane's governance mirror is read from a dated snapshot the repository carries:
    # another lane rewrites the live file on its own schedule, and a moving file cannot be
    # certified, so the view certifies the snapshot and observes the rest
    st6 = declared["data/st6/ST6_HEALTH_STATUS.json"]
    assert st6["class"] == "EXTERNAL_LIVE"
    assert st6["evidence_copy"]["in_head"] is True
    assert st6["evidence_copy"]["sha256_lf"]
    assert payload["local_observations"]

    by_id = {item["id"]: item for item in payload["invariants"]}
    assert by_id["I7_inputs_are_reproducible"]["result"] == "PASS"
    assert by_id["I7_inputs_are_reproducible"]["coverage"]["declared_inputs"] == len(declared)
    assert by_id["I5_governance_mirrors_agree"]["coverage"]["coverage"] == "FULL"


def test_registry_staleness_is_an_advisory_not_a_contradiction(state_view):
    payload = json.loads((RECOVERY / "CAMPAIGN_STATE_VIEW.json").read_text(encoding="utf-8"))
    advisory_ids = {a["id"] for a in payload["advisories"]}
    # the registry does not list numbers the tree already occupies: reported, not fatal
    assert "A1_registry_is_stale" in advisory_ids
    assert payload["rfc_numbering"]["next_free_derived"] == 50
    assert str(payload["rfc_numbering"]["registry_next_free_declared"]) not in {"050", "50"}
    assert payload["status"] == "CONSISTENT_WITH_ADVISORIES"
    # nothing was rewritten to make the view agree with itself
    assert payload["sources_unchanged"] is True


# --------------------------------------------------------------------------- #
# WP-3 — ACTIVE economic audit
# --------------------------------------------------------------------------- #


def test_audit_reconstructs_all_registered_strategies(audit):
    payload = audit.build()
    assert payload["strategy_count"] == 24
    assert len(payload["strategies"]) == 24
    assert set(payload["aggregates"]["ledger_status_counts"]) == {"NO_GROSS_EDGE", "COST_KILLED"}
    assert payload["aggregates"]["admitted_for_paper"] == 0
    for sid, record in payload["strategies"].items():
        assert record["strategy_id"] == sid
        assert record["failure_taxonomy"]["primary"] in audit.FAILURE_CATEGORIES


def test_audit_is_deterministic_and_committed(audit):
    first = audit.payload_hash(audit.build())
    second = audit.payload_hash(audit.build())
    assert first == second
    stored = json.loads((RECOVERY / "ACTIVE_ECONOMIC_AUDIT.json").read_text(encoding="utf-8"))
    assert stored["payload_sha256"] == first, "the committed audit is stale: re-run scripts/active_economic_audit.py"


def test_audit_inputs_resolve_from_the_commit(audit):
    """WP-8D: the audit's numbers come from inputs a clean checkout also has."""
    payload = json.loads((RECOVERY / "ACTIVE_ECONOMIC_AUDIT.json").read_text(encoding="utf-8"))
    rows = {row["path"]: row for row in payload["sources"]}
    # these four are gitignored by design, so the audit can only have read the committed
    # evidence copy; reading the local file is what made its findings unreproducible
    for rel in ("reports/strategy-baseline/TIMEFRAME_AUDIT.json",
                "reports/strategy-baseline/COST_BARRIER.json",
                "reports/strategy-baseline/REGIME_ANALYSIS.json",
                "reports/alpha-recovery-v1/STRATEGY_FAILURE_MATRIX.md"):
        assert rows[rel]["resolved_from"] == "EVIDENCE_COPY", rows[rel]
        assert rows[rel]["sha256_lf"], rows[rel]
    assert all(row["resolved_from"] in {"HEAD", "EVIDENCE_COPY", "LOCAL_MATERIALIZATION"}
               for row in payload["sources"])
    checks = {item["check"]: item for item in payload["checks"]}
    assert checks["inputs:every_external_input_resolves_from_the_commit"]["result"] == "PASS"


def test_audit_checks_all_pass(audit):
    payload = json.loads((RECOVERY / "ACTIVE_ECONOMIC_AUDIT.json").read_text(encoding="utf-8"))
    failures = [c for c in payload["checks"] if c["result"] != "PASS"]
    assert failures == []
    assert payload["checks_failed"] == 0


def test_audit_finds_no_positive_net_edge_anywhere(audit):
    payload = audit.build()
    assert payload["aggregates"]["net_positive_count"] == 0
    for sid, record in payload["strategies"].items():
        expectancy = record["economics"]["base_expectancy_bps"]
        assert expectancy is None or expectancy <= 0, sid
        gross = record["economics"]["zero_cost_gross_bps"]
        assert gross is None or gross <= payload["cost_plane"]["research_contract"]["base_rt_bps"], sid
    assert payload["objective_3_ops_per_day"]["assessment"] == "NOT_ACHIEVABLE_FROM_CURRENT_REGISTERED_FAMILIES"


def test_audit_invents_no_metric(audit):
    payload = audit.build()
    for sid, record in payload["strategies"].items():
        assert record["economics"]["max_drawdown"] is None, sid
        assert "max_drawdown" in record["missing_metrics"], sid
        # every published number is either a real value or explicitly absent
        for field, value in record["economics"].items():
            if value is not None and field.endswith("_bps"):
                assert isinstance(value, (int, float)), f"{sid}:{field}"


def test_declared_source_discrepancies_are_exactly_the_observed_ones(audit):
    payload = audit.build()
    observed = {
        sid for sid, record in payload["strategies"].items()
        if record["economics"]["zero_cost_gross_bps_matches_ledger"] is False
    }
    declared = set(audit.DECLARED_SOURCE_DISCREPANCIES)
    assert observed == declared, f"observed {observed} declared {declared}"
    for entry in audit.DECLARED_SOURCE_DISCREPANCIES.values():
        assert abs(entry["delta_bps"]) <= entry["materiality_bound_bps"]
        assert entry["defect"], "a declared discrepancy must name the defect it is registered under"


def test_cost_plane_reproduces_the_frozen_value(audit):
    plane = audit.derived_cost_plane()
    assert plane["reproduces_frozen_value"] is True
    assert plane["round_trip_bps_200_usdt"] == pytest.approx(audit.FROZEN_ADMISSION_RT_BPS, abs=1e-9)
    assert plane["stress_1_5x_bps"] == pytest.approx(audit.FROZEN_STRESS_1_5X_BPS, abs=1e-6)


def test_audit_records_the_paper_lane_failure_honestly(audit):
    payload = audit.build()
    lane = payload["paper_lane"]
    assert lane["present"] is True
    assert lane["final_status"] == "PAPER_24H_DATA_FAILED"
    assert lane["false_success"] == 0
    assert lane["paper_trades"] == 0 and lane["shadow_trades"] == 0
    assert lane["no_trade_kind"] == "NO_TRADE_STRATEGIC"
    # the payload carries no authorization of its own
    flags = json.loads((RECOVERY / "ACTIVE_ECONOMIC_AUDIT.json").read_text(encoding="utf-8"))
    assert flags["answers"]["Q6_next_rfc"]["authorization_state"] == "NOT_AUTHORIZED"


def test_recovery_reports_make_no_promotion_claim():
    """The prose reports must state the negative and must not assert the positive.

    Transcribing a governance value out of another campaign's artefact (the state
    view reports RFC-048V's own ``RFC048_OFFLINE_CERTIFIED`` status) is not a claim;
    what is forbidden is this work asserting profitability, certification or
    production readiness of the ACTIVE pipeline.
    """
    import re

    prose = ["FINAL_REPORT.md", "ACTIVE_RECOVERY_ROADMAP.md", "RFC049_POST_CLOSURE_REPORT.md"]
    for name in prose:
        path = RECOVERY / name
        assert path.exists(), f"required report {name} is missing"
        text = path.read_text(encoding="utf-8")
        assert "PROFITABILITY_VERIFIED = FALSE" in text, f"{name} must state the negative explicitly"
        assert not re.search(r"PROFITABILITY_VERIFIED\s*[:=]\s*(true|TRUE)", text), name

    for path in sorted(RECOVERY.glob("*.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        assert not any_hit(payload, ("profitability_verified", "rentable", "production_ready")), path.name


def any_hit(obj, keys: tuple[str, ...]) -> bool:
    """True when any of ``keys`` is present with a truthy value anywhere in ``obj``."""
    if isinstance(obj, dict):
        for key, value in obj.items():
            if key.lower() in keys and value is True:
                return True
            if any_hit(value, keys):
                return True
    elif isinstance(obj, list):
        return any(any_hit(item, keys) for item in obj)
    return False
