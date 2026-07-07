from __future__ import annotations

import datetime
from pathlib import Path

from trading_bot.paper.reporting import (
    build_session_alerts,
    build_session_metrics,
    build_session_report_payload,
    render_session_markdown,
    write_session_report,
)
from trading_bot.paper.types import (
    PaperBacktestExpectation,
    PaperClosedTrade,
    PaperExecutionSummary,
    PaperSessionResult,
)
from trading_bot.scanner import CounterSnapshot
from trading_bot.scanner.types import MarketSnapshot


def _snapshot(symbol: str, *, active: bool, spread_bps: float, rank_score: float) -> MarketSnapshot:
    return MarketSnapshot(
        symbol=symbol,
        last_price=100.0,
        volume_24h_usdt=10_000_000.0,
        spread_bps=spread_bps,
        atr_pct=1.0,
        volatility_pct=1.0,
        active=active,
        rejection_reason=None if active else "spread_above_threshold",
        timestamp=1_700_000_000_000,
        rank_score=rank_score,
    )


def test_build_session_metrics_computes_ratios_and_active_stats() -> None:
    metrics = build_session_metrics(
        [
            _snapshot("BTC/USDT", active=True, spread_bps=4.0, rank_score=0.9),
            _snapshot("ETH/USDT", active=True, spread_bps=6.0, rank_score=0.7),
            _snapshot("SOL/USDT", active=False, spread_bps=40.0, rank_score=0.0),
        ],
        CounterSnapshot(
            pairs_processed=3,
            pairs_active=2,
            pairs_inactive=1,
            scanner_errors=0,
        ),
    )
    assert metrics.total_snapshots == 3
    assert metrics.active_snapshots == 2
    assert metrics.inactive_snapshots == 1
    assert metrics.active_ratio == 2 / 3
    assert metrics.inactive_ratio == 1 / 3
    assert metrics.avg_active_rank_score == 0.8
    assert metrics.median_spread_bps_active == 5.0


def test_build_session_metrics_handles_empty_snapshot_list() -> None:
    metrics = build_session_metrics(
        [],
        CounterSnapshot(
            pairs_processed=0,
            pairs_active=0,
            pairs_inactive=0,
            scanner_errors=2,
        ),
    )
    assert metrics.total_snapshots == 0
    assert metrics.active_ratio == 0.0
    assert metrics.avg_active_rank_score == 0.0
    assert metrics.median_spread_bps_active == 0.0
    assert metrics.scanner_errors == 2


def _session_result() -> PaperSessionResult:
    snapshots = [
        _snapshot("BTC/USDT", active=True, spread_bps=4.0, rank_score=0.9),
        _snapshot("ETH/USDT", active=True, spread_bps=8.0, rank_score=0.6),
        _snapshot("SOL/USDT", active=False, spread_bps=40.0, rank_score=0.0),
    ]
    counters = CounterSnapshot(
        pairs_processed=3,
        pairs_active=2,
        pairs_inactive=1,
        scanner_errors=4,
    )
    return PaperSessionResult(
        session_id="session-1",
        started_at=datetime.datetime(2026, 1, 1, 12, 0, tzinfo=datetime.UTC),
        ended_at=datetime.datetime(2026, 1, 1, 12, 5, tzinfo=datetime.UTC),
        duration_ms=300_000,
        snapshots=snapshots,
        counters=counters,
        metrics=build_session_metrics(
            snapshots,
            counters,
            PaperExecutionSummary(
                fills_opened=2,
                fills_closed=2,
                closed_trades=[
                    PaperClosedTrade(
                        trade_id="trade-1",
                        symbol="BTC/USDT",
                        qty=1.0,
                        entry_price=100.0,
                        exit_price=98.0,
                        opened_at_ms=1_700_000_000_000,
                        closed_at_ms=1_700_000_300_000,
                        realized_pnl=-80.0,
                        realized_pnl_pct=-0.08,
                        total_commission=2.0,
                        sessions_held=1,
                        entry_fill_id="fill-1",
                        exit_fill_id="fill-2",
                    )
                ],
                realized_pnl=-80.0,
                unrealized_pnl=0.0,
                ending_cash=9_920.0,
                ending_equity=9_920.0,
                win_rate_closed=0.25,
            ),
        ),
    )


def test_build_session_alerts_flags_threshold_breaches() -> None:
    alerts = build_session_alerts(
        _session_result(),
        PaperBacktestExpectation(
            expected_active_snapshots=10,
            expected_median_spread_bps=2.0,
            expected_realized_pnl=100.0,
            min_active_ratio=0.80,
            min_win_rate_closed=0.30,
            max_scanner_errors=3,
        ),
    )
    codes = {alert.code for alert in alerts}
    assert "realized_pnl_diverged" in codes
    assert "signal_frequency_diverged" in codes
    assert "spread_above_expected" in codes
    assert "active_ratio_below_threshold" in codes
    assert "win_rate_below_threshold" in codes
    assert "scanner_errors_above_threshold" in codes


def test_render_session_markdown_includes_metrics_and_alerts() -> None:
    markdown = render_session_markdown(
        _session_result(),
        PaperBacktestExpectation(
            expected_active_snapshots=2,
            expected_median_spread_bps=5.0,
            expected_realized_pnl=100.0,
        ),
    )
    assert "# Paper Session session-1" in markdown
    assert "## Metrics" in markdown
    assert "## Backtest Comparison" in markdown
    assert "## Alerts" in markdown


def test_build_session_report_payload_contains_alerts_and_expectation() -> None:
    payload = build_session_report_payload(
        _session_result(),
        PaperBacktestExpectation(
            expected_active_snapshots=2,
            expected_median_spread_bps=5.0,
            expected_realized_pnl=100.0,
        ),
    )
    assert payload["session_id"] == "session-1"
    assert payload["metrics"]["active_snapshots"] == 2
    assert payload["expectation"]["expected_active_snapshots"] == 2
    assert payload["expectation"]["expected_realized_pnl"] == 100.0
    assert isinstance(payload["alerts"], list)


def test_write_session_report_writes_markdown_and_json(tmp_path: Path) -> None:
    markdown_path, json_path = write_session_report(
        _session_result(),
        tmp_path,
        PaperBacktestExpectation(
            expected_active_snapshots=2,
            expected_median_spread_bps=5.0,
            expected_realized_pnl=100.0,
        ),
    )
    assert markdown_path.exists()
    assert json_path.exists()
    assert "Paper Session session-1" in markdown_path.read_text(encoding="utf-8")
    assert '"session_id": "session-1"' in json_path.read_text(encoding="utf-8")
