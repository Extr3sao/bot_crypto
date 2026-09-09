"""POC02 observation module tests (POC02-OBSERVATION-AND-ALPHA-DIAGNOSIS-01).

Pure analytics over synthetic persisted evidence — no network, no runtime.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from trading_bot.paper.poc02_observation import (
    agent_filter_analysis,
    analyze_campaign,
    bottleneck_distribution,
    daily_performance_rows,
    frequency_kpis,
    regime_bottleneck_matrix,
    regime_coverage_map,
    risk_value_test,
    runtime_staleness,
    strategy_contribution,
)

# --------------------------------------------------------------------------
# fixtures: synthetic ledgers
# --------------------------------------------------------------------------


def _cycle_row(
    utc_date: str,
    run_id: str,
    bottleneck: str,
    regime: str,
    *,
    proposals: int = 2,
    selected: int = 0,
    risk_rejects: int = 0,
    risk_accepts: int = 0,
    paper: int = 0,
    decisions: list[dict] | None = None,
) -> dict:
    return {
        "utc_date": utc_date,
        "run_id": run_id,
        "bottlenecks": [
            {
                "window_id": f"{run_id}:X",
                "regime": regime,
                "bottleneck": bottleneck,
                "counts": {},
                "reason": "test",
            }
        ],
        "state": {
            "trade_proposals": proposals,
            "debates": 1,
            "decisions_selected": selected,
            "risk_accepts": risk_accepts,
            "risk_rejects": risk_rejects,
            "paper_trades": paper,
            "decisions": decisions or [],
        },
    }


def _write_campaign(
    tmp_path: Path,
    cycle_rows: list[dict],
    attribution: list[dict] | None = None,
    *,
    coverage: dict[str, dict] | None = None,
    finalizations: dict[str, dict] | None = None,
    state: dict | None = None,
) -> Path:
    (tmp_path / "POC02_CYCLE_LEDGER.jsonl").write_text(
        "".join(json.dumps(r, default=str) + "\n" for r in cycle_rows),
        encoding="utf-8",
    )
    if attribution is not None:
        cdir = tmp_path / "cycles"
        cdir.mkdir(exist_ok=True)
        (cdir / "POC02_ATTRIBUTION.jsonl").write_text(
            "".join(json.dumps(r, default=str) + "\n" for r in attribution),
            encoding="utf-8",
        )
    if coverage:
        (tmp_path / "POC02_COVERAGE_DAILY.jsonl").write_text(
            "".join(json.dumps(r, sort_keys=True) + "\n" for r in coverage.values()),
            encoding="utf-8",
        )
    if finalizations:
        (tmp_path / "POC02_DAY_FINALIZATIONS.json").write_text(
            json.dumps(finalizations), encoding="utf-8"
        )
    if state:
        (tmp_path / "POC02_CAMPAIGN_STATE.json").write_text(
            json.dumps(state), encoding="utf-8"
        )
    return tmp_path


# --------------------------------------------------------------------------
# §5 bottleneck distribution
# --------------------------------------------------------------------------


def test_bottleneck_distribution_proportions() -> None:
    rows = [
        _cycle_row("2026-09-09", "r1", "AGENT_FILTER", "NEUTRAL|WEAK|NORMAL|RANGE|NORMAL|NORMAL"),
        _cycle_row("2026-09-09", "r2", "AGENT_FILTER", "NEUTRAL|WEAK|NORMAL|RANGE|NORMAL|NORMAL"),
        _cycle_row("2026-09-09", "r3", "NO_SIGNAL", "NEUTRAL|WEAK|NORMAL|RANGE|NORMAL|NORMAL"),
    ]
    dist = bottleneck_distribution(rows)
    assert dist["windows_observed"] == 3
    assert dist["counts"]["AGENT_FILTER"] == 2
    assert dist["proportions"]["AGENT_FILTER"] == 0.6667
    assert dist["dominant"] == "AGENT_FILTER"


def test_regime_matrix_flags_single_observation() -> None:
    rows = [
        _cycle_row("2026-09-09", "r1", "AGENT_FILTER", "REGIME_A"),
        _cycle_row("2026-09-09", "r2", "NO_SIGNAL", "REGIME_B"),
        _cycle_row("2026-09-09", "r3", "NO_SIGNAL", "REGIME_B"),
    ]
    matrix = regime_bottleneck_matrix(rows)
    assert matrix["matrix"]["REGIME_A"]["single_observation"] is True
    assert matrix["matrix"]["REGIME_B"]["single_observation"] is False
    assert matrix["matrix"]["REGIME_B"]["proportions"]["NO_SIGNAL"] == 1.0


# --------------------------------------------------------------------------
# §4 frequency KPIs — valid-day denominator discipline
# --------------------------------------------------------------------------


def test_frequency_kpis_exclude_partial_and_invalid_days() -> None:
    perf = [
        {"FINALIZED": True, "DAY_COUNTS_FOR_COVERAGE": True, "trades": 4, "trades_ge_3": True},
        {"FINALIZED": True, "DAY_COUNTS_FOR_COVERAGE": True, "trades": 0, "trades_ge_3": False},
        {"FINALIZED": True, "DAY_COUNTS_FOR_COVERAGE": False, "trades": 99, "trades_ge_3": True},  # invalid
        {"FINALIZED": False, "DAY_COUNTS_FOR_COVERAGE": False, "trades": 50, "trades_ge_3": True},  # open day
    ]
    kpis = frequency_kpis(perf)
    assert kpis["COMPLETED_VALID_DAYS"] == 2
    assert kpis["DAYS_GE_3"] == 1
    assert kpis["PERCENT_DAYS_GE_3"] == 50.0
    assert kpis["TOTAL_TRADES"] == 4  # invalid/open days excluded
    assert kpis["TRADES_PER_VALID_DAY"] == 2.0
    assert kpis["MEDIAN_TRADES_PER_VALID_DAY"] == 2
    assert kpis["TARGET_TRADES_PER_VALID_DAY"] == 3
    assert kpis["target_lowered"] is False


def test_frequency_kpis_zero_valid_days() -> None:
    kpis = frequency_kpis([{"FINALIZED": False, "DAY_COUNTS_FOR_COVERAGE": False, "trades": 1, "trades_ge_3": False}])
    assert kpis["COMPLETED_VALID_DAYS"] == 0
    assert kpis["TRADES_PER_VALID_DAY"] is None
    assert kpis["PERCENT_DAYS_GE_3"] is None


# --------------------------------------------------------------------------
# §7 strategy contribution
# --------------------------------------------------------------------------


def test_strategy_contribution_counts_and_pnl_mapping() -> None:
    attribution = [
        {"written_at": "2026-09-09T10:00:00+00:00", "stage": "AGENT_REJECT", "strategy_id": "Momentum", "regime": "R1", "asset": "BTC"},
        {"written_at": "2026-09-09T10:00:01+00:00", "stage": "AGENT_REJECT", "strategy_id": "Trend", "regime": "R1", "asset": "BTC"},
        {"written_at": "2026-09-09T10:00:02+00:00", "stage": "SELECTED", "strategy_id": "Momentum", "regime": "R1", "asset": "BTC"},
        {"written_at": "2026-09-09T10:00:03+00:00", "stage": "RISK_REJECT", "strategy_id": "Momentum", "regime": "R1", "asset": "BTC", "risk_reason": "x"},
        {"written_at": "2026-09-09T10:00:04+00:00", "stage": "PAPER_OPEN", "strategy_id": "Trend", "regime": "R1", "asset": "BTC", "symbol": "BTC/USDT"},
        {"written_at": "2026-09-09T10:05:00+00:00", "stage": "PAPER_CLOSE", "symbol": "BTC/USDT", "net_pnl": 12.5, "gross_pnl": 15.0},
    ]
    result = strategy_contribution([], attribution)
    momentum = result["strategies"]["Momentum"]
    trend = result["strategies"]["Trend"]
    assert momentum["agent_rejects"] == 1
    assert momentum["selected"] == 1
    assert momentum["risk_rejects"] == 1
    assert trend["paper_trades"] == 1
    assert trend["risk_accepts"] == 1
    assert trend["net_pnl"] == 12.5  # PAPER_CLOSE mapped via symbol
    assert "NONE" in result["profitability_claim"]


# --------------------------------------------------------------------------
# §8 agent filter analysis
# --------------------------------------------------------------------------


def test_agent_filter_rates_conditioned() -> None:
    attribution = [
        {"written_at": "2026-09-09T10:00:00+00:00", "stage": "AGENT_REJECT", "strategy_id": "Momentum", "regime": "R1", "asset": "BTC", "decision_reasons": ["UNRESOLVED_CONFLICT"]},
        {"written_at": "2026-09-09T10:00:01+00:00", "stage": "SELECTED", "strategy_id": "Trend", "regime": "R1", "asset": "BTC"},
        {"written_at": "2026-09-09T10:00:02+00:00", "stage": "AGENT_REJECT", "strategy_id": "Momentum", "regime": "R2", "asset": "ETH", "decision_reasons": ["INSUFFICIENT_EVIDENCE"]},
    ]
    result = agent_filter_analysis([], attribution)
    assert result["AGENT_FILTER_RATE"] == 0.6667
    assert result["AGENT_FILTER_RATE_BY_REGIME"]["R1"]["AGENT_FILTER_RATE"] == 0.5
    assert result["AGENT_FILTER_RATE_BY_STRATEGY"]["Momentum"]["AGENT_FILTER_RATE"] == 1.0
    assert result["AGENT_FILTER_RATE_BY_ASSET"]["ETH"]["AGENT_FILTER_RATE"] == 1.0
    assert result["rejection_reason_distribution"]["UNRESOLVED_CONFLICT"] == 1
    assert result["agents_loosened"] is False


def test_agent_filter_zero_denominator() -> None:
    result = agent_filter_analysis([], [])
    assert result["AGENT_FILTER_RATE"] is None


# --------------------------------------------------------------------------
# §12 regime coverage map
# --------------------------------------------------------------------------


def test_regime_coverage_map_classifications() -> None:
    cycle_rows = [
        _cycle_row("2026-09-09", f"r{i}", "NO_SIGNAL", "NO_SIGNAL_REGIME_X")
        for i in range(6)
    ] + [
        # 20 observed windows for the well-covered regime
        _cycle_row("2026-09-09", "g", "NONE", "GOOD") for _i in range(20)
    ] + [
        # 6 observed windows for the no-edge regime
        _cycle_row("2026-09-09", "s", "AGENT_FILTER", "STUCK") for _i in range(6)
    ]
    attribution = []
    # a well-covered regime: many windows + 2 strategies with progress
    for _i in range(20):
        attribution.append({"written_at": "2026-09-09T10:00:00+00:00", "stage": "SELECTED", "strategy_id": "Momentum", "regime": "GOOD", "asset": "BTC"})
        attribution.append({"written_at": "2026-09-09T10:00:00+00:00", "stage": "SELECTED", "strategy_id": "Trend", "regime": "GOOD", "asset": "BTC"})
    # a no-edge regime: proposals but zero progress
    for _i in range(6):
        attribution.append({"written_at": "2026-09-09T10:00:00+00:00", "stage": "AGENT_REJECT", "strategy_id": "Momentum", "regime": "STUCK", "asset": "BTC"})
    attribution.append({"written_at": "2026-09-09T10:00:00+00:00", "stage": "SELECTED", "strategy_id": "Solo", "regime": "SOLO", "asset": "BTC"})
    result = regime_coverage_map(cycle_rows, attribution)
    assert result["regimes"]["NO_SIGNAL_REGIME_X"]["classification"] == "NO_SIGNAL_REGIME"
    assert result["regimes"]["GOOD"]["classification"] == "WELL_COVERED"
    assert result["regimes"]["STUCK"]["classification"] == "NO_EDGE"
    assert result["regimes"]["SOLO"]["classification"] in ("UNDER_COVERED", "INSUFFICIENT_EVIDENCE")
    assert result["discovery_batch_03"] == "NOT_STARTED"


# --------------------------------------------------------------------------
# §18 staleness
# --------------------------------------------------------------------------


def test_runtime_staleness_flags_old_heartbeat() -> None:
    state = {"heartbeat_utc": "2026-09-09T13:00:00+00:00", "status": "ACTIVE"}
    now = datetime(2026, 9, 9, 14, 0, tzinfo=UTC)
    result = runtime_staleness(state, now=now)
    assert result["RUNTIME_STALE"] is True
    assert result["age_minutes"] == 60.0


def test_runtime_staleness_fresh_and_missing() -> None:
    now = datetime(2026, 9, 9, 14, 0, tzinfo=UTC)
    fresh = runtime_staleness({"heartbeat_utc": "2026-09-09T13:45:00+00:00"}, now=now)
    assert fresh["RUNTIME_STALE"] is False
    assert runtime_staleness({}, now=now)["RUNTIME_STALE"] is True


# --------------------------------------------------------------------------
# daily performance rows
# --------------------------------------------------------------------------


def test_daily_performance_keeps_zero_trade_days(tmp_path: Path) -> None:
    cycle_rows = [
        _cycle_row("2026-09-09", "r1", "AGENT_FILTER", "R1", decisions=[{"verifier": "VERIFIED"}]),
    ]
    coverage = {
        "2026-09-09": {"utc_day": "2026-09-09", "observed_cycles": 1, "observed_minutes": 60, "expected_minutes": 1440, "coverage_ratio": 0.0417, "day_validity": "PENDING", "runtime_downtime_minutes": 1380, "provider_downtime_minutes": 0},
    }
    finalizations = {"2026-09-09": {"validity": "VALID", "finalized_at_utc": "2026-09-10T00:00:01+00:00", "finalization_count": 1, "reason_codes": ["CONTRACT_SATISFIED"]}}
    _write_campaign(tmp_path, cycle_rows, [], coverage=coverage, finalizations=finalizations)
    rows = daily_performance_rows(tmp_path)
    assert len(rows) == 1
    row = rows[0]
    assert row["trades"] == 0
    assert row["trades_ge_3"] is False
    assert row["FINALIZED"] is True
    assert row["DAY_COUNTS_FOR_COVERAGE"] is True
    assert row["day_validity"] == "VALID"
    # zero-trade valid days stay in the denominator


def test_daily_performance_pnl_attribution(tmp_path: Path) -> None:
    attribution = [
        {"written_at": "2026-09-09T10:00:00+00:00", "stage": "PAPER_OPEN", "symbol": "BTC/USDT", "strategy_id": "Trend"},
        {"written_at": "2026-09-09T10:10:00+00:00", "stage": "PAPER_CLOSE", "symbol": "BTC/USDT", "net_pnl": -3.0, "gross_pnl": -2.0},
        {"written_at": "2026-09-09T11:00:00+00:00", "stage": "PAPER_OPEN", "symbol": "ETH/USDT", "strategy_id": "Trend"},
        {"written_at": "2026-09-09T11:10:00+00:00", "stage": "PAPER_CLOSE", "symbol": "ETH/USDT", "net_pnl": 5.0, "gross_pnl": 6.0},
    ]
    _write_campaign(
        tmp_path,
        [_cycle_row("2026-09-09", "r1", "NONE", "R1", paper=2)],
        attribution,
        finalizations={"2026-09-09": {"validity": "VALID", "finalization_count": 1}},
    )
    rows = daily_performance_rows(tmp_path)
    row = rows[0]
    assert row["paper_opens"] == 2
    assert row["paper_closes"] == 2
    assert row["wins"] == 1 and row["losses"] == 1
    assert row["gross_pnl"] == 4.0
    assert row["net_pnl"] == 2.0
    assert row["trades_ge_3"] is False


# --------------------------------------------------------------------------
# shadow analysis (no captures → honest zeros, no inference)
# --------------------------------------------------------------------------


def test_analyze_campaign_with_empty_shadow(tmp_path: Path) -> None:
    _write_campaign(
        tmp_path,
        [_cycle_row("2026-09-09", "r1", "AGENT_FILTER", "R1")],
        [],
        state={"heartbeat_utc": datetime.now(UTC).isoformat(), "status": "ACTIVE"},
    )
    result = analyze_campaign(tmp_path)
    shadow = result["shadow_risk_analysis"]
    assert shadow["captures_total"] == 0
    assert shadow["resolved_total"] == 0
    assert shadow["isolation"]["SHADOW_PAPERBROKER_CALLS"] == 0
    assert "NO Risk change" in shadow["recommendation"]
    rvt = result["risk_value_test"]
    assert rvt["sufficient_sample"] is False
    assert rvt["automatic_risk_change"] is False
    assert result["runtime_staleness"]["RUNTIME_STALE"] is False


def test_risk_value_test_insufficient_sample_honest(tmp_path: Path) -> None:
    # no ledgers at all: no comparison, no interpretation
    result = risk_value_test(tmp_path)
    assert result["sufficient_sample"] is False
    assert result["comparison"] is None
    assert "INSUFFICIENT" in result["status"]
