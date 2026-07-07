from __future__ import annotations

import asyncio
import datetime
from pathlib import Path

import pytest
import structlog

from trading_bot.backtesting import BacktestResult, EquityPoint, Fill, Trade
from trading_bot.config.runtime import TradingMode
from trading_bot.config.settings import Settings
from trading_bot.market_data.fake import build_demo_fetcher, build_demo_settings
from trading_bot.paper import PaperBroker, PaperSessionRunner, PaperSnapshotArchive
from trading_bot.paper.types import PaperBacktestExpectation
from trading_bot.scanner import UniverseScanner, build_filter_set_per_mode


def _build_paper_scanner() -> tuple[UniverseScanner, Settings]:
    settings = build_demo_settings(
        mode="paper",
        kill_switch_enabled=False,
    )
    source = build_demo_fetcher(settings)
    scanner = UniverseScanner(
        source=source,
        registry_per_mode=build_filter_set_per_mode(settings),
        settings=settings,
    )
    return scanner, settings


def _backtest_result(total_trades: int = 2) -> BacktestResult:
    def _fill(*, order_id: str, side: str, timestamp: int) -> Fill:
        return Fill(
            order_id=order_id,
            symbol="BTC/USDT",
            side=side,  # type: ignore[arg-type]
            qty_filled=1.0,
            fill_price=100.0,
            commission=1.0,
            slippage=0.2,
            timestamp=timestamp,
        )

    trades = [
        Trade(
            entry_fill=_fill(order_id=f"t{i}-buy", side="buy", timestamp=1_700_000_000_000),
            exit_fill=_fill(order_id=f"t{i}-sell", side="sell", timestamp=1_700_000_300_000),
            pnl=10.0,
            pnl_pct=0.1,
            bars_held=2,
        )
        for i in range(total_trades)
    ]
    return BacktestResult(
        strategy_name="demo-strategy",
        symbol="BTC/USDT",
        timeframe="1h",
        start=datetime.datetime(2026, 1, 1, tzinfo=datetime.UTC),
        end=datetime.datetime(2026, 1, 31, tzinfo=datetime.UTC),
        initial_capital=10_000.0,
        final_equity=10_100.0,
        trades=trades,
        equity_curve=[
            EquityPoint(timestamp=1_700_000_000_000, equity=10_000.0, drawdown_pct=0.0),
        ],
        metrics={
            "total_trades": float(total_trades),
            "win_rate": 1.0,
            "profit_factor": float("inf"),
            "final_equity": 10_100.0,
            "max_drawdown": 0.0,
            "cagr": 0.1,
            "calmar_ratio": 1.0,
            "sharpe_ratio": 1.0,
            "sortino_ratio": 1.0,
            "avg_trade_pnl": 10.0,
            "expectancy": 10.0,
        },
    )


def test_runner_rejects_non_paper_mode() -> None:
    scanner, settings = _build_paper_scanner()
    bad_settings = settings.model_copy(
        update={"runtime": settings.runtime.model_copy(update={"mode": TradingMode.RESEARCH})}
    )
    runner = PaperSessionRunner(scanner=scanner, settings=bad_settings)
    with pytest.raises(ValueError, match=r"runtime\.mode='paper'"):
        asyncio.run(runner.run_session())


def test_runner_executes_session_and_archives_snapshots(tmp_path: Path) -> None:
    scanner, settings = _build_paper_scanner()
    now_points = iter(
        [
            datetime.datetime(2026, 1, 1, 12, 0, tzinfo=datetime.UTC),
            datetime.datetime(2026, 1, 1, 12, 0, 1, tzinfo=datetime.UTC),
        ]
    )
    with PaperSnapshotArchive(f"sqlite:///{tmp_path}/paper.db") as archive:
        runner = PaperSessionRunner(
            scanner=scanner,
            settings=settings,
            archive=archive,
            now_fn=lambda: next(now_points),
        )
        result = asyncio.run(runner.run_session())
        archived = archive.list_session(result.session_id)
        assert len(result.snapshots) == len(archived)
        assert result.metrics.total_snapshots == len(result.snapshots)
        assert result.duration_ms == 1000


def test_runner_logs_completed_event(tmp_path: Path) -> None:
    scanner, settings = _build_paper_scanner()
    now_points = iter(
        [
            datetime.datetime(2026, 1, 1, 12, 0, tzinfo=datetime.UTC),
            datetime.datetime(2026, 1, 1, 12, 0, 1, tzinfo=datetime.UTC),
        ]
    )
    with PaperSnapshotArchive(f"sqlite:///{tmp_path}/paper.db") as archive:
        runner = PaperSessionRunner(
            scanner=scanner,
            settings=settings,
            archive=archive,
            now_fn=lambda: next(now_points),
        )
        with structlog.testing.capture_logs() as cap:
            result = asyncio.run(runner.run_session())
        assert result.metrics.total_snapshots > 0
        events = [entry["event"] for entry in cap]
        assert "paper.session.completed" in events


def test_runner_writes_daily_report_when_enabled(tmp_path: Path) -> None:
    scanner, settings = _build_paper_scanner()
    now_points = iter(
        [
            datetime.datetime(2026, 1, 1, 12, 0, tzinfo=datetime.UTC),
            datetime.datetime(2026, 1, 1, 12, 0, 1, tzinfo=datetime.UTC),
        ]
    )
    with PaperSnapshotArchive(f"sqlite:///{tmp_path}/paper.db") as archive:
        runner = PaperSessionRunner(
            scanner=scanner,
            settings=settings,
            archive=archive,
            expectation=PaperBacktestExpectation(
                expected_active_snapshots=2,
                expected_median_spread_bps=5.0,
            ),
            report_output_dir=tmp_path / "reports" / "paper",
            now_fn=lambda: next(now_points),
        )
        result = asyncio.run(runner.run_session())
    assert result.report_markdown_path is not None
    assert result.report_json_path is not None
    assert result.report_markdown_path.exists()
    assert result.report_json_path.exists()
    assert "Paper Session" in result.report_markdown_path.read_text(encoding="utf-8")
    assert '"session_id"' in result.report_json_path.read_text(encoding="utf-8")


def test_runner_skips_daily_report_when_disabled(tmp_path: Path) -> None:
    scanner, settings = _build_paper_scanner()
    settings_without_reports = settings.model_copy(
        update={
            "runtime": settings.runtime.model_copy(
                update={
                    "reports": settings.runtime.reports.model_copy(update={"paper_report": False})
                }
            )
        }
    )
    now_points = iter(
        [
            datetime.datetime(2026, 1, 1, 12, 0, tzinfo=datetime.UTC),
            datetime.datetime(2026, 1, 1, 12, 0, 1, tzinfo=datetime.UTC),
        ]
    )
    with PaperSnapshotArchive(f"sqlite:///{tmp_path}/paper.db") as archive:
        runner = PaperSessionRunner(
            scanner=scanner,
            settings=settings_without_reports,
            archive=archive,
            report_output_dir=tmp_path / "reports" / "paper",
            now_fn=lambda: next(now_points),
        )
        result = asyncio.run(runner.run_session())
    assert result.report_markdown_path is None
    assert result.report_json_path is None
    assert not (tmp_path / "reports" / "paper").exists()


def test_runner_can_be_built_from_backtest_result(tmp_path: Path) -> None:
    scanner, settings = _build_paper_scanner()
    now_points = iter(
        [
            datetime.datetime(2026, 1, 1, 12, 0, tzinfo=datetime.UTC),
            datetime.datetime(2026, 1, 1, 12, 0, 1, tzinfo=datetime.UTC),
        ]
    )
    with PaperSnapshotArchive(f"sqlite:///{tmp_path}/paper.db") as archive:
        runner = PaperSessionRunner.from_backtest_result(
            scanner=scanner,
            settings=settings,
            backtest_result=_backtest_result(3),
            expected_median_spread_bps=5.0,
            archive=archive,
            report_output_dir=tmp_path / "reports" / "paper",
            now_fn=lambda: next(now_points),
        )
        result = asyncio.run(runner.run_session())
    assert result.report_json_path is not None
    report_json = result.report_json_path.read_text(encoding="utf-8")
    assert '"expected_active_snapshots": 3' in report_json


def test_runner_includes_execution_summary_when_broker_is_enabled(tmp_path: Path) -> None:
    scanner, settings = _build_paper_scanner()
    now_points = iter(
        [
            datetime.datetime(2026, 1, 1, 12, 0, tzinfo=datetime.UTC),
            datetime.datetime(2026, 1, 1, 12, 0, 1, tzinfo=datetime.UTC),
        ]
    )
    with (
        PaperSnapshotArchive(f"sqlite:///{tmp_path}/paper.db") as archive,
        PaperBroker(f"sqlite:///{tmp_path}/paper.db") as broker,
    ):
        runner = PaperSessionRunner(
            scanner=scanner,
            settings=settings,
            archive=archive,
            broker=broker,
            report_output_dir=tmp_path / "reports" / "paper",
            now_fn=lambda: next(now_points),
        )
        result = asyncio.run(runner.run_session())
    assert result.execution_summary is not None
    assert result.metrics.fills_opened >= 1
    assert result.metrics.ending_equity > 0.0
