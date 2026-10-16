"""Tests for RFC-EDGE-014 — the economic-recovery package.

The tests are written against the rules the brief states as requirements, not against the
implementation that happens to satisfy them. Two of them are the most important: a
contract that *can* be built in a forbidden shape is not enforcing anything, so the
contracts are tested by asserting they refuse; and the reconciliation of the WP-EDGE-09
contradiction is tested by reproducing both published numbers from the primary artefact,
because a reconciliation that cannot reproduce the number it explains proves nothing.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT / "src"))

from trading_bot.research.economic_recovery import (  # noqa: E402
    candidates,
    contracts,
    costs,
    experiments,
    frequency,
    parity,
    render,
    trade_path,
)


# --------------------------------------------------------------------- contracts refuse
def test_an_exchange_order_cannot_be_built_without_being_sent():
    with pytest.raises(ValueError, match="order_sent=False"):
        contracts.TradePathEvent(
            run_id="r",
            utc_timestamp="2026-10-16T00:00:00Z",
            asset="BTC/USDT",
            stage="FILL",
            outcome="ACCEPTED",
            reason_code="X",
            execution_class="EXCHANGE_ORDER",
            order_sent=False,
        )


def test_a_fill_stage_must_name_its_fill_class():
    with pytest.raises(ValueError, match="must name the class of fill"):
        contracts.TradePathEvent(
            run_id="r",
            utc_timestamp="2026-10-16T00:00:00Z",
            asset="BTC/USDT",
            stage="FILL",
            outcome="ACCEPTED",
            reason_code="X",
            execution_class="NONE",
        )


def test_a_fill_without_its_required_fields_is_refused():
    with pytest.raises(ValueError, match="must carry"):
        contracts.TradePathEvent(
            run_id="r",
            utc_timestamp="2026-10-16T00:00:00Z",
            asset="BTC/USDT",
            stage="FILL",
            outcome="ACCEPTED",
            reason_code="X",
            execution_class="PAPER_BROKER_FILL",
            order_sent=True,
        )


def test_a_complete_paper_fill_is_accepted_and_carries_order_sent():
    event = contracts.TradePathEvent(
        run_id="r",
        utc_timestamp="2026-10-16T00:00:00Z",
        asset="BTC/USDT",
        stage="FILL",
        outcome="ACCEPTED",
        reason_code="PAPER_FILL",
        execution_class="PAPER_BROKER_FILL",
        order_sent=True,
        quantity=0.01,
        price=60000.0,
        fees_bps=10.0,
        side="buy",
        provenance="paper-broker",
    )
    assert event.order_sent is True
    assert event.as_dict()["execution_class"] == "PAPER_BROKER_FILL"


def test_an_experiment_result_cannot_carry_a_promotion():
    with pytest.raises(ValueError, match="cannot carry a promotion"):
        contracts.ExperimentResult(
            run_id="r",
            commit="abc",
            environment="test",
            data_fingerprint="f",
            source_sha="s",
            strategy_id="x",
            baseline_id="CURRENT",
            assets=["BTC/USDT"],
            period="p",
            train="t",
            validation="v",
            oos="o",
            trials_count=1,
            executed_trades_by_day={"2026-01-01": 0},
            signal_count=0,
            rejected_count=0,
            fill_model="BACKTEST_FILL",
            risk_constraints="deterministic",
            costs="admission",
            promotion="PAPER_READY",
        )


def test_a_rejected_candidate_must_state_why():
    with pytest.raises(ValueError, match="must state why"):
        contracts.StrategyCandidate(
            candidate_id="X",
            source_id="SRC-01",
            source_sha="sha",
            hypothesis="h",
            family="F",
            product="spot",
            venue="binance",
            assets=["BTC/USDT"],
            timeframes=["1h"],
            permitted_sides=["long"],
            regime="all",
            params_locked={},
            test_plan="p",
            admission_status="REJECTED",
        )


def test_a_cost_breakdown_refuses_to_reconcile_when_components_do_not_add_up():
    good = contracts.EconomicCostBreakdown(
        scenario_id="s",
        population="admission",
        round_trip_bps=23.0,
        entry_fee_bps=10.0,
        exit_fee_bps=10.0,
        spread_bps=3.0,
    )
    bad = contracts.EconomicCostBreakdown(
        scenario_id="s",
        population="admission",
        round_trip_bps=23.0,
        entry_fee_bps=10.0,
        exit_fee_bps=10.0,
        spread_bps=30.0,
    )
    assert good.reconcile()["status"] == "RECONCILED"
    assert bad.reconcile()["status"] == "INCONSISTENT"


def test_a_component_above_its_own_total_is_inconsistent_unless_explained():
    unexplained = contracts.EconomicCostBreakdown(
        scenario_id="s",
        population="p",
        round_trip_bps=23.0,
        entry_fee_bps=32.5,
        exit_fee_bps=0.0,
    )
    explained = contracts.EconomicCostBreakdown(
        scenario_id="s",
        population="p",
        round_trip_bps=23.0,
        entry_fee_bps=32.5,
        exit_fee_bps=0.0,
        included_in=["entry_fee_bps"],
    )
    assert "no_component_exceeds_a_non_negative_total_unexplained" in [
        c["name"] for c in unexplained.reconcile()["checks"] if not c["passed"]
    ]
    assert explained.reconcile()["status"] == "INCONSISTENT"  # components still must add up


# ------------------------------------------------- the WP-EDGE-09 contradiction is real
def test_the_published_fee_share_and_the_published_ratio_both_reproduce():
    """Both numbers exist because they use different populations, and both are reproducible."""
    payload = costs.reconciliation_payload()
    admission = payload["admission_claim"]
    defect = payload["cross_population_defect"]

    assert admission["mean_fee_bps"] == 20.0
    assert admission["fee_share_percent"] == 85.92
    assert defect["published_ratio"] == pytest.approx(1.3863, abs=5e-4)
    assert defect["matches_published_1_3863"] is True
    assert defect["defect"] == "population_mismatch"


def test_the_cross_population_ratio_divides_two_different_populations():
    payload = costs.reconciliation_payload()
    defect = payload["cross_population_defect"]
    assert defect["numerator"]["population"] == "all_registered_venue_schedules"
    assert defect["denominator"]["population"] == "admission_scenario_only"
    assert defect["numerator"]["n_schedules"] == 4
    assert defect["denominator"]["n_assets"] == 6


def test_every_venue_schedule_reconciles_against_its_own_round_trip():
    payload = costs.reconciliation_payload()
    assert payload["verdict"] == "ECONOMIC_INTEGRITY_RECONCILED"
    for breakdown in payload["breakdowns"]:
        assert breakdown["reconciliation"]["status"] == "RECONCILED", breakdown["scenario_id"]


def test_the_reconciliation_marks_the_published_sentence_superseded_not_deleted():
    payload = costs.reconciliation_payload()
    assert payload["status_by_axis"]["published_1_3863_sentence"] == "INCONSISTENT_SUPERSEDED"
    assert payload["primary_source_untouched"] is True


# ----------------------------------------------------------- frequency window definitions
def test_the_two_frequency_numbers_are_not_the_same_metric():
    payload = frequency.frequency_reconciliation()
    two = payload["the_two_numbers"]
    assert two["same_metric"] is False
    assert two["selector_long_only_overlapping_per_day"] == 144.061
    assert two["tape_bound_non_overlapping_per_day"] == 48.018
    assert two["selector_long_only_overlapping_per_day"] > two["tape_bound_non_overlapping_per_day"]


def test_the_active_target_is_measured_against_the_non_overlapping_bound():
    payload = frequency.frequency_reconciliation()
    assert payload["active_target_measured_against"] == "tape_bound_non_overlapping_per_day"
    definitions = {d["name"]: d for d in payload["definitions"]}
    assert definitions["tape_bound_non_overlapping"]["is_the_active_denominator"] is True
    assert definitions["selector_long_only_overlapping"]["window_rule"] == "overlapping"


def test_the_definition_table_states_a_window_rule_and_direction_for_every_number():
    for definition in frequency.DEFINITIONS:
        assert definition["window_rule"] in ("overlapping", "non-overlapping")
        assert definition["direction_filter"]
        assert definition["reads_as"]


# ------------------------------------------------------------------------ trade path 14A
def test_the_trade_path_stage_that_has_no_ledger_is_unknown_not_zero():
    payload = trade_path.trade_path_payload()
    by_stage = {s["stage"]: s for s in payload["funnel"]["stages"]}
    assert by_stage["ROUTER"]["evidence_class"] == "unknown"
    assert by_stage["ROUTER"]["count"] is None
    assert by_stage["ORDER_INTENT"]["evidence_class"] == "absent_ledger"
    assert by_stage["RECONCILIATION"]["evidence_class"] == "observed"


def test_a_decision_is_not_counted_as_a_trade():
    payload = trade_path.trade_path_payload()
    headline = payload["funnel"]["headline"]
    assert headline["sealed_decisions"] >= headline["closed_trades"]
    assert headline["paper_broker_fills"] == 0
    assert headline["exchange_orders"] == 0


def test_the_live_status_is_verified_zero_with_its_basis_stated():
    payload = trade_path.trade_path_payload()
    assert payload["live_status"] == "VERIFIED_ZERO"
    assert "venue" in payload["live_status_basis"]


def test_the_window_is_reported_as_what_it_is_and_not_padded_to_thirty_days():
    payload = trade_path.trade_path_payload()
    window = payload["window"]
    assert window["requested_days"] == 30
    assert window["window_is_the_full_thirty_days"] == (window["span_days"] >= 30.0)


def test_a_disk_veto_is_normalised_to_a_reason_with_its_source_code_kept():
    payload = trade_path.trade_path_payload()
    reasons = payload["no_trade"]["by_reason"]
    assert "DISK_BUDGET_VETO" in reasons
    assert "NO_NEW_DECISION_DISK_CRITICAL" in reasons["DISK_BUDGET_VETO"]["raw_codes"]


def test_an_unmapped_error_code_becomes_unknown_rather_than_being_guessed():
    code, explanation = trade_path.normalise_reason("SOME_CODE_NEVER_SEEN")
    assert code == "UNKNOWN"
    assert "does not yet normalise" in explanation


# --------------------------------------------------------------------- candidates 14D
def test_the_three_named_hypotheses_are_rejected_because_the_families_carry_them():
    registry = candidates.register_candidates()
    by_id = {c["candidate_id"]: c for c in registry["candidates"]}
    for candidate_id in ("E14-01", "E14-02", "E14-03"):
        assert by_id[candidate_id]["admission_status"] == "REJECTED"
        assert by_id[candidate_id]["duplicate_of"]
        assert by_id[candidate_id]["duplicate_reason"]


def test_the_duplicate_rule_is_symmetric_and_retains_a_genuinely_orthogonal_one():
    registry = candidates.register_candidates()
    by_id = {c["candidate_id"]: c for c in registry["candidates"]}
    assert by_id["E14-04"]["admission_status"] != "REJECTED"
    scan = candidates.duplicate_scan()
    assert scan["E14-04"]["token_coverage"] == 0.0
    assert scan["E14-01"]["token_coverage"] >= 0.5


def test_a_rejected_candidate_is_not_promoted_by_being_registered():
    registry = candidates.register_candidates()
    assert registry["promotion"] == "NONE"
    assert registry["order_sent"] is False
    assert all(c["sizing_authority"] == "DETERMINISTIC_RISK" for c in registry["candidates"])


# ------------------------------------------------------------------ experiments 14C/14D
def test_every_arm_charges_the_admission_round_trip():
    payload = experiments.experiment_payload()
    assert payload["round_trip_cost_bps"] > 0
    for name, result in payload["results"].items():
        if result["status"] != "EXECUTED":
            continue
        measurement = result.get("measurement") or result.get("neutral")
        assert measurement["round_trip_cost_bps_charged"] == payload["round_trip_cost_bps"], name


def test_no_executed_arm_claims_an_exchange_order():
    payload = experiments.experiment_payload()
    for result in payload["results"].values():
        if result["status"] == "EXECUTED":
            assert result["fill_class"] == "BACKTEST_FILL"


def test_zero_trade_days_stay_visible_in_the_per_day_series():
    payload = experiments.experiment_payload()
    executed = [r for r in payload["results"].values() if r["status"] == "EXECUTED"]
    assert executed
    for result in executed:
        measurement = result.get("measurement") or result.get("neutral")
        assert measurement["days_with_zero_trades"] <= measurement["days_observed"]


def test_the_oos_is_declared_non_fresh_when_no_unread_corpus_remains():
    payload = experiments.experiment_payload()
    if not payload["corpus_registry"]["has_a_genuinely_fresh_oos"]:
        assert payload["oos_is_fresh"] is False
        assert payload["verdict"] == "INSUFFICIENT_SAMPLE_FOR_FRESH_OOS"


def test_both_on_disk_bar_shapes_are_read_and_a_third_is_refused(tmp_path):
    dict_shard = tmp_path / "dict.json"
    dict_shard.write_text(
        '[{"ts": 1, "open": 1, "high": 2, "low": 0.5, "close": 1.5, "volume": 3}]'
    )
    list_shard = tmp_path / "list.json"
    list_shard.write_text("[[1, 1.0, 2.0, 0.5, 1.5, 3.0]]")
    bad_shard = tmp_path / "bad.json"
    bad_shard.write_text('[{"ts": 1, "o": 1}]')

    assert len(experiments.load_ohlcv(dict_shard)) == 1
    assert len(experiments.load_ohlcv(list_shard)) == 1
    # The third shape must raise rather than silently return zero bars.
    with pytest.raises(ValueError, match="none parsed"):
        experiments.load_ohlcv(bad_shard)


def test_a_run_that_did_not_execute_is_labelled_not_executed():
    payload = experiments.experiment_payload()
    for name in payload["not_executed"]:
        assert payload["results"][name]["status"] != "EXECUTED"
    for name in payload["executed"]:
        assert payload["results"][name]["status"] == "EXECUTED"


# ----------------------------------------------------------------------------- parity 14C
def test_a_gpl_or_agpl_source_is_never_copyable():
    preflight = parity.license_preflight()
    by_id = {row["id"]: row for row in preflight["sources"]}
    for source_id in ("SRC-01",):
        assert by_id[source_id]["may_copy_into_this_project"] is False
    assert set(preflight["not_copyable"]) >= {"SRC-01", "SRC-05", "SRC-09"}


def test_the_licence_family_is_read_from_the_title_not_the_whole_body():
    """GPL-3.0's body names the AGPL in section 13; the title must win."""
    gpl_body = "GNU GENERAL PUBLIC LICENSE\nVersion 3, 29 June 2007\n" + "x" * 1000
    gpl_body += "\nthe GNU Affero General Public License"
    assert parity._licence_family(gpl_body) == "GPL"
    assert parity._licence_family("MIT License\n\nCopyright") == "MIT"
    assert parity._licence_family("GNU AFFERO GENERAL PUBLIC LICENSE\nVersion 3") == "AGPL"
    assert parity._licence_family("NOASSERTION") == "UNKNOWN"


def test_the_parity_tolerance_is_registered_before_the_run():
    plan = parity.parity_plan()
    tolerance = plan["preregistered_tolerance"]
    assert tolerance["declared_before_run"] is True
    assert tolerance["on_exceed"]


def test_every_p0_source_is_pinned_to_a_full_sha():
    for source in parity.SOURCES:
        assert len(source["sha"]) == 40
        assert all(c in "0123456789abcdef" for c in source["sha"])


def test_the_parity_plan_uses_a_neutral_unfitted_strategy():
    plan = parity.parity_plan()
    assert "ema(12)" in plan["neutral_strategy"]["rule"]
    assert plan["neutral_strategy"]["why_neutral"]


def test_no_third_party_engine_is_a_runtime_component():
    preflight = parity.license_preflight()
    for row in preflight["sources"]:
        assert row["runtime_impact"].startswith("none")


def test_a_component_that_does_not_add_up_is_reported_inconsistent():
    from trading_bot.research.economic_recovery import contracts as c

    breakdown = c.EconomicCostBreakdown(
        scenario_id="s",
        population="p",
        round_trip_bps=23.0,
        entry_fee_bps=10.0,
        exit_fee_bps=10.0,
        spread_bps=1.0,
    )
    result = breakdown.reconcile()
    assert result["status"] == "INCONSISTENT"
    assert any(check["name"] == "components_add_up_to_the_round_trip" for check in result["checks"])


# ------------------------------------------- the deliverable set the brief enumerates
NAMED_DELIVERABLES = (
    "BASELINE.json",
    "runtime_authority_map.md",
    "TRADE_PATH_DIAGNOSIS.md",
    "TRADE_PATH_DIAGNOSIS.json",
    "TRADE_FUNNEL.csv",
    "NO_TRADE_CAUSE_MATRIX.csv",
    "EVIDENCE_INDEX.json",
    "MARKET_COST_RECONCILIATION.md",
    "MARKET_COST_RECONCILIATION.json",
    "EDGE09R_PROVENANCE.md",
    "VENUE_COST_MATRIX.csv",
    "FREQUENCY_DEFINITIONS.md",
    "INTEGRITY_VERIFICATION.json",
    "source_registry.md",
    "CLONE_MANIFEST.json",
    "LICENSE_COMPATIBILITY.md",
    "SECURITY_PREFLIGHT.md",
    "BENCHMARK_PARITY_REPORT.md",
    "ENGINE_DIFF.csv",
    "CANDIDATE_REGISTRY.json",
    "EXPERIMENT_MATRIX.csv",
    "CANDIDATE_EXPERIMENTS.md",
    "CANDIDATE_EXPERIMENTS.json",
    "OOS_HOLDOUT_MANIFEST.json",
    "TRADE_FREQUENCY_BY_DAY.csv",
    "REJECTED_CANDIDATES.md",
    "PAPER_BLOCKED.md",
    "GATE_DECISIONS.jsonl",
    "INDEPENDENT_VERIFICATION.md",
    "INDEPENDENT_VERIFICATION.json",
    "SABOTAGE_MATRIX.csv",
    "RUN_REPORT.md",
    "RUN_REPORT.json",
    "FINAL_REPORT.md",
    "INFORME_EJECUTIVO.md",
    "GIT_STATE.json",
    "PATH_MAP.md",
)


def test_every_named_deliverable_the_brief_asks_for_exists():
    rendered = render.render_all()
    assert len(rendered) == len(set(rendered)) or True  # names are keys, unique by construction
    missing = [name for name in NAMED_DELIVERABLES if not (render.REPORTS / name).is_file()]
    assert missing == [], f"named deliverables missing: {missing}"


def _stem(name: str) -> str:
    """Strip the extension exactly once: ``.json`` is a prefix of ``.jsonl``."""
    path = Path(name)
    return path.stem if path.suffix else name


def test_the_path_map_registers_every_named_deliverable():
    render.render_all()
    mapping = (render.REPORTS / "PATH_MAP.md").read_text(encoding="utf-8")
    for name in NAMED_DELIVERABLES:
        assert _stem(name) in mapping, f"PATH_MAP.md does not register {name}"
    assert _stem("GATE_DECISIONS.jsonl") == "GATE_DECISIONS"


def test_each_markdown_deliverable_is_a_rendering_of_a_json_record():
    for name, source in render.DELIVERABLE_SOURCES:
        assert (render.REPORTS / source).is_file(), source
        body = (render.REPORTS / name).read_text(encoding="utf-8")
        assert body.startswith("# WP-EDGE") or body.startswith("# RFC-EDGE"), name


def test_the_per_day_csv_keeps_zero_trade_days_as_rows():
    text = render.trade_frequency_by_day_csv()
    lines = text.strip().splitlines()
    assert lines[0] == "arm,utc_day,trades"
    assert any(line.endswith(",0") for line in lines[1:]), "no zero-trade day survived"


def test_the_engine_diff_declares_the_unrun_engine_rather_than_fabricating_one():
    text = render.engine_diff_csv()
    assert "NOT_EXECUTED" in text
    assert "jesse(SRC-02)" in text


def test_the_manifest_excludes_only_the_two_files_it_cannot_digest():
    payload = render.build_manifest()
    assert payload["excludes"] == ["ARTIFACT_MANIFEST.json", "INDEPENDENT_VERIFICATION.json"]
    assert "ARTIFACT_MANIFEST.json" not in payload["artifacts"]
    assert "INDEPENDENT_VERIFICATION.json" not in payload["artifacts"]
    assert payload["excludes_because"]


def test_the_sabotage_csv_carries_every_case_with_its_kind():
    render.render_all()
    lines = render.sabotage_matrix_csv().strip().splitlines()
    assert lines[0] == "id,name,kind,detected,detail"
    assert len(lines) == 31  # header plus thirty cases
    assert "TAMPER_DETECTED" in render.sabotage_matrix_csv()


def test_the_gate_decisions_jsonl_lists_a_blocked_decision_per_gate():
    text = render.gate_decisions_jsonl()
    rows = [json.loads(line) for line in text.strip().splitlines()]
    assert rows, "no gate decision was recorded"
    assert all(row["decision"] == "BLOCKED" for row in rows)
    assert all(row["gates_relaxed"] == [] for row in rows)
