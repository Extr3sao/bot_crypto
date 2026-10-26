"""RFC-048 — tests for the independent verifier (BUILDER != VERIFIER).

The verifier is only worth anything if (a) it really is independent of the builder
and (b) its negative controls have teeth. Both are asserted here, on decisions the
engine produces in this very test, plus a pass over the artefacts of the real
offline execution when they are present.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from trading_bot.risk.futures import (
    Direction,
    InstrumentSpec,
    MarginLedger,
    PortfolioSnapshot,
    RiskProposal,
    ScenarioRequest,
    load_instrument_registry,
)
from trading_bot.risk.futures.engine import FuturesRiskEngine, FuturesRiskPolicy
from trading_bot.risk.futures_verification import (
    authoritative_evidence_dir,
    load_fixtures,
    run_verification,
    verify_decision,
)

DATA = Path(__file__).resolve().parents[3] / "data" / "rfc048"
#: WP-TDM-07: the authoritative bundle is the v2 generation (digests over the
#: bytes the repository stores). ``DATA`` keeps pointing at the historical v1
#: artifacts so they remain inspectable; verification reads v2.
EVIDENCE = authoritative_evidence_dir(DATA)
REPO = Path(__file__).resolve().parents[3]

pytestmark = pytest.mark.unit


@pytest.fixture(scope="module")
def fixtures():
    return load_fixtures(EVIDENCE)


@pytest.fixture(scope="module")
def instrument() -> InstrumentSpec:
    return load_instrument_registry(EVIDENCE / "INSTRUMENTS.json").get(
        "BINANCE_USDM_BTCUSDT_PERP"
    )


@pytest.fixture(scope="module")
def snapshot_payload() -> dict:
    return json.loads((EVIDENCE / "MARKET_SNAPSHOT.json").read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def funding_history() -> dict:
    return json.loads((EVIDENCE / "FUNDING_HISTORY.json").read_text(encoding="utf-8"))


def build_case(
    instrument: InstrumentSpec,
    snapshot: dict,
    funding: dict,
) -> dict:
    """Run one approving decision and shape it like the executed artefact."""
    mark = float(snapshot["mark_price"])
    proposal = RiskProposal(
        run_id="VERIFY-RUN",
        decision_id="VERIFY-DEC-001",
        instrument_id=instrument.instrument_id,
        direction=Direction.LONG,
        entry_price=mark,
        stop_price=mark * 0.995,
        requested_notional=400.0,
        requested_leverage=5.0,
        horizon_minutes=60.0,
        data_timestamp_ms=int(snapshot["data_timestamp_ms"]),
        decision_timestamp_ms=int(snapshot["data_timestamp_ms"]) + 1_000,
        mark_price=mark,
        strategy_id="verifier_probe",
    )
    portfolio = PortfolioSnapshot(
        snapshot_id="VERIFY-SNAP",
        timestamp_ms=int(snapshot["data_timestamp_ms"]),
        equity=200.0,
        free_margin=200.0,
        reserved_margin=0.0,
    )
    engine = FuturesRiskEngine(
        spec=instrument,
        policy=FuturesRiskPolicy(max_gross_exposure_pct=5.0),
        ledger=MarginLedger(equity=200.0),
    )
    outcome = engine.decide(
        ScenarioRequest(
            proposal=proposal,
            snapshot=portfolio,
            market={
                "mark_price": mark,
                "spread_bps": snapshot["spread_bps"],
                "depth": {"bids": snapshot["depth_bids"], "asks": snapshot["depth_asks"]},
            },
            funding_observations=funding["observations"],
            funding_source_hash=funding["source_hash"],
        )
    )
    detail = dict(outcome.detail)
    detail["ledger"] = {"reserved": outcome.decision.required_margin, "free": 0.0}
    return {
        "scenario": "verify_probe",
        "decision": outcome.decision.to_dict(),
        "inputs": {"funding_observations_provided": len(funding["observations"])},
        "detail": detail,
    }


def test_verifier_does_not_import_the_builder() -> None:
    """Source-level and process-level proof of independence."""
    source = (REPO / "src" / "trading_bot" / "risk" / "futures_verification.py").read_text(
        encoding="utf-8"
    )
    assert "from trading_bot.risk.futures" not in source.replace(
        "from trading_bot.risk.futures_verification", ""
    )
    assert "import trading_bot.risk.futures\n" not in source

    code = (
        "import sys; sys.path.insert(0, 'src');"
        "import trading_bot.risk.futures_verification;"
        "prefix='trading_bot.risk.futures';"
        "loaded=[n for n in sys.modules if (n==prefix or n.startswith(prefix + '.')) "
        "and n!='trading_bot.risk.futures_verification'];"
        "print(loaded)"
    )
    proc = subprocess.run(
        [sys.executable, "-c", code], cwd=REPO, capture_output=True, text=True, check=False
    )
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.strip() == "[]"


def test_verifier_reproduces_a_real_approval(
    instrument, snapshot_payload, funding_history, fixtures
):
    """A decision produced here survives an independent recomputation."""
    case = build_case(instrument, snapshot_payload, funding_history)
    assert case["decision"]["decision"] in {"APPROVE_SIMULATION", "REDUCE_SIMULATED_SIZE"}
    checks, _ = verify_decision(case, fixtures)
    failed = [c.name for c in checks if not c.passed]
    assert failed == []


def test_negative_controls_are_all_detected(
    instrument, snapshot_payload, funding_history, fixtures
):
    """§13 — the seven required controls plus the order-authorisation control."""
    case = build_case(instrument, snapshot_payload, funding_history)
    report = run_verification({"decisions": [case]}, fixtures)
    controls = {row["control"]: row for row in report["negative_controls"]}
    assert controls, "the negative controls must run against a real approval"
    assert report["false_success"] == 0
    for name in (
        "false_margin",
        "omitted_cost",
        "wrong_liquidation",
        "wrong_notional",
        "excess_leverage",
        "aggregate_risk_omitted",
        "temporally_invalid",
        "order_authorisation",
    ):
        assert controls[name]["detected"] is True, f"{name} was not detected"
    assert "margin_and_leverage" in controls["false_margin"]["detected_by"]
    assert "cost_completeness" in controls["omitted_cost"]["detected_by"]
    assert "liquidation_consistency" in controls["wrong_liquidation"]["detected_by"]
    assert "notional_consistency" in controls["wrong_notional"]["detected_by"]
    assert "aggregate_margin_pool" in controls["aggregate_risk_omitted"]["detected_by"]
    assert "temporal_validity" in controls["temporally_invalid"]["detected_by"]
    assert "no_order_authorisation" in controls["order_authorisation"]["detected_by"]


def test_negative_control_requires_an_approval_to_tamper_with(
    instrument, snapshot_payload, funding_history, fixtures
):
    """A refusal-only artefact cannot claim the controls passed."""
    case = build_case(instrument, snapshot_payload, funding_history)
    refused = json.loads(json.dumps(case))
    refused["decision"]["decision"] = "NO_TRADE"
    refused["decision"]["approved_notional"] = 0.0
    refused["decision"]["rejection_reasons"] = ["EXPOSURE_LIMIT"]
    report = run_verification({"decisions": [refused]}, fixtures)
    assert report["negative_controls"][0]["control"] == "none_available"
    assert report["negative_controls"][0]["detected"] is False
    assert report["false_success"] == 1
    assert report["verdict"] == "FAIL"


def test_executed_artifacts_verify_when_present(fixtures) -> None:
    """The artefacts of the real offline run must survive verification."""
    scenarios_path = EVIDENCE / "RISK_SCENARIOS.json"
    if not scenarios_path.exists():  # pragma: no cover - run script not executed yet
        pytest.skip("data/rfc048/RISK_SCENARIOS.json not generated")
    scenarios = json.loads(scenarios_path.read_text(encoding="utf-8"))
    report = run_verification({"decisions": scenarios["cases"]}, fixtures)
    assert report["decisions_verified"] == len(scenarios["cases"])
    assert report["checks_failed"] == []
    assert report["false_success"] == 0
    assert report["verdict"] == "VERIFIED"


def test_execution_report_claims_match_the_artifacts() -> None:
    """The report may not claim more than the artefacts show."""
    scenarios_path = EVIDENCE / "RISK_SCENARIOS.json"
    report_path = EVIDENCE / "RUNTIME_EXECUTION_REPORT.json"
    if not (scenarios_path.exists() and report_path.exists()):  # pragma: no cover
        pytest.skip("RFC-048 artefacts not generated")
    cases = json.loads(scenarios_path.read_text(encoding="utf-8"))["cases"]
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["execution"]["scenarios_run"] == len(cases)
    assert report["execution"]["order_authorised_anywhere"] is False
    assert all(row["decision"]["order_authorised"] is False for row in cases)
    assert report["governance"]["live_orders_sent"] == 0
    assert report["governance"]["new_strategies_created"] == 0
    assert report["governance"]["oos_results_reused"] == 0
    assert report["governance"]["cost_model_v3_modified"] is False
    # every executed decision carries a verdict from the closed vocabulary
    allowed = {
        "APPROVE_SIMULATION",
        "REDUCE_SIMULATED_SIZE",
        "NO_TRADE",
        "RISK_VETO",
        "DATA_INVALID",
        "UNSUPPORTED_INSTRUMENT",
    }
    assert {row["decision"]["decision"] for row in cases} <= allowed


def test_reduced_request_never_widens_risk_in_artifacts() -> None:
    """§12 property, checked on the executed catalogue rather than a unit case."""
    scenarios_path = EVIDENCE / "RISK_SCENARIOS.json"
    if not scenarios_path.exists():  # pragma: no cover
        pytest.skip("RFC-048 artefacts not generated")
    cases = json.loads(scenarios_path.read_text(encoding="utf-8"))["cases"]
    for row in cases:
        decision = row["decision"]
        assert decision["approved_notional"] <= decision["requested_notional"] + 1e-9
        if decision["decision"] in {"APPROVE_SIMULATION", "REDUCE_SIMULATED_SIZE"}:
            assert decision["modeled_worst_loss"] <= decision["risk_budget"] + 1e-9
            assert decision["effective_leverage"] <= decision["requested_leverage"] + 1e-9


def test_fixture_ladder_hash_matches_the_raw_payload(fixtures) -> None:
    """The verifier's own provenance check must be able to fail."""
    import hashlib

    raw = (EVIDENCE / "raw" / "binance_usdm_leverage_brackets_btcusdt.json").read_bytes()
    assert hashlib.sha256(raw).hexdigest() == fixtures.bracket_source_hash
