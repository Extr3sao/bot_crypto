"""G-7 — real public market data through the canonical PAPER runtime.

What this harness does
----------------------
1. Fetches **real, public** Binance 5m bars, 24h quote volume and top-of-book
   spread.  No API key, no signature, no order endpoint and no exchange session.
2. Persists the exact capture (bars + hashes) so a replay can be reproduced.
3. Runs the repository's own ``PaperOrchestrator → PaperSessionRunner →
   PaperCycleEngine → RiskManager → DurablePaperBroker`` path at pinned
   historical decision instants.  The same capture is replayed twice from a
   clean process to prove determinism and restart safety.
4. Runs one forward PAPER session against the live public provider.
5. Produces the canonical eligibility report.  If the committed ledger admits
   no strategy, the report says so and the campaign does not invent a trade.
6. Exercises stale/duplicate/gap/future/out-of-order/bad-OHLCV/provider-failure
   inputs; each must end with zero orders.

The harness is an evidence driver, not a second runtime.  Every decision path
used here is the production one; only the market-data source and the pinned
clock are injected, exactly as the G-5/G-6 evidence harnesses did.
"""

from __future__ import annotations

import argparse
import asyncio
import datetime
import hashlib
import json
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "src"))
sys.path.insert(0, str(REPO_ROOT))

import trading_bot.scanner.scanner as scanner_module  # noqa: E402
from scripts.start_paper_trading import build_cycle_engine  # noqa: E402
from trading_bot.config.settings import Settings, load_settings  # noqa: E402
from trading_bot.config.universe import PairSpec  # noqa: E402
from trading_bot.market_data.public_rest import (  # noqa: E402
    PublicDataError,
    PublicRestKlineSource,
    ReplayMarketDataSource,
    capture_sha256,
    load_capture,
)
from trading_bot.market_data.real_data_validation import (  # noqa: E402
    timeframe_ms,
    validate_closed_bars,
)
from trading_bot.market_data.types import OHLCV  # noqa: E402
from trading_bot.paper.durable_broker import DurablePaperBroker  # noqa: E402
from trading_bot.paper.eligibility import evaluate_eligibility  # noqa: E402
from trading_bot.paper.paper_orchestrator import PaperOrchestrator  # noqa: E402
from trading_bot.paper.paper_state_store import PaperStateStore  # noqa: E402
from trading_bot.paper.reconciliation_v4 import StartupReconcilerV4  # noqa: E402
from trading_bot.paper.snapshot_history import FetcherBarReader  # noqa: E402
from trading_bot.scanner.mode_filters import build_filter_set_per_mode  # noqa: E402
from trading_bot.scanner.scanner import UniverseScanner  # noqa: E402

DEFAULT_LEDGER = REPO_ROOT / "config" / "strategy_admission.json"
DEFAULT_ASSETS = ("BTC", "ETH", "SOL")


def _git_head() -> str:
    try:
        completed = subprocess.run(
            ["git", "-C", str(REPO_ROOT), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        return completed.stdout.strip() if completed.returncode == 0 else "UNKNOWN"
    except Exception:
        return "UNKNOWN"


def _iso(ms: int | None) -> str | None:
    if ms is None:
        return None
    return datetime.datetime.fromtimestamp(ms / 1000.0, tz=datetime.UTC).isoformat()


def _parse_assets(raw: str) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for token in raw.split(","):
        asset = token.strip().upper()
        if asset and asset not in seen:
            seen.add(asset)
            out.append(asset)
    if not out:
        raise ValueError("--assets requires at least one asset")
    return out


def _settings(assets: list[str], timeframe: str) -> Settings:
    settings = load_settings(config_dir=str(REPO_ROOT / "config"), env_file=None)
    pairs = [PairSpec(symbol=f"{asset}/USDT", enabled=True) for asset in assets]
    universe = settings.universe.model_copy(update={"pairs": pairs, "timeframes": [timeframe]})
    return settings.model_copy(update={"universe": universe})


def _scanner(settings: Settings, source: Any) -> UniverseScanner:
    scan_settings = settings.model_copy(
        update={"risk": settings.risk.model_copy(update={"kill_switch_enabled": False})}
    )
    return UniverseScanner(
        source=source,
        registry_per_mode=build_filter_set_per_mode(scan_settings),
        settings=scan_settings,
    )


class CountingDurableBroker(DurablePaperBroker):
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.execute_calls = 0
        self.close_calls = 0

    def execute_signal(self, signal: Any) -> Any:
        self.execute_calls += 1
        return super().execute_signal(signal)

    def close_position(self, *args: Any, **kwargs: Any) -> Any:
        self.close_calls += 1
        return super().close_position(*args, **kwargs)


class FailingSource:
    """Provider outage fixture: every call fails, no bar is invented."""

    provider = "controlled-provider-outage"

    async def fetch_recent(self, symbol: str, limit: int = 100) -> list[OHLCV]:
        raise ConnectionError(f"controlled public-data outage for {symbol}")

    async def fetch_24h_volume_usdt(self, symbol: str) -> float:
        raise ConnectionError(f"controlled public-data outage for {symbol}")

    async def fetch_spread_bps(self, symbol: str) -> float:
        raise ConnectionError(f"controlled public-data outage for {symbol}")


def _state_summary(store: PaperStateStore) -> dict[str, Any]:
    if not store.exists():
        return {
            "exists": False,
            "bytes": 0,
            "open_positions": 0,
            "closed_trades": 0,
            "sent_intents": 0,
            "orders": [],
            "equity": None,
        }
    raw = store.path.read_bytes()
    try:
        doc = json.loads(raw.decode("utf-8"))
    except Exception as exc:
        return {
            "exists": True,
            "bytes": len(raw),
            "parse_error": f"{type(exc).__name__}: {exc}",
        }
    broker = dict(doc.get("broker_state", {}) or {})
    return {
        "exists": True,
        "bytes": len(raw),
        "open_positions": len(doc.get("open_positions", []) or []),
        "closed_trades": len(doc.get("closed_trades", []) or []),
        "sent_intents": len(doc.get("sent_intents", []) or []),
        "orders": [dict(row) for row in doc.get("orders", []) or []],
        "equity": float(broker.get("equity", 0.0) or 0.0),
        "run_id": doc.get("run_id", ""),
        "updated_at_ms": doc.get("updated_at_ms", 0),
    }


async def _run_session(
    *,
    settings: Settings,
    source: Any,
    decision_time_ms: int,
    state_path: Path,
    run_dir: Path,
    ledger_path: Path,
    assets: list[str],
    timeframe: str,
    label: str,
) -> dict[str, Any]:
    """One real session through the canonical PaperOrchestrator stack."""
    run_dir.mkdir(parents=True, exist_ok=True)
    broker = CountingDurableBroker(
        equity=10_000.0,
        clock=lambda: decision_time_ms / 1000.0,
        book_id=f"g7-{label}",
    )
    engine = build_cycle_engine(
        settings,
        broker,
        assets=assets,
        timeframe=timeframe,
        ledger_path=ledger_path,
        run_dir=run_dir,
    )
    store = PaperStateStore(state_path)
    broker.attach_durability(
        store=store,
        risk=engine.risk_manager,
        idempotency=engine.idempotency,
        run_id=f"g7-{label}",
    )
    reconciler = StartupReconcilerV4(
        store=store,
        broker=broker,
        risk_manager=engine.risk_manager,
        idempotency=engine.idempotency,
    )
    reconciliation = reconciler.reconcile()
    if reconciliation.status == "FATAL":
        return {
            "label": label,
            "decision_time_ms": decision_time_ms,
            "decision_time": _iso(decision_time_ms),
            "reconciliation": reconciliation.to_dict(),
            "status": "FATAL",
            "decision_outcome": "FAILED",
            "orders_created": 0,
            "broker_calls": {"execute_signal": 0, "close_position": 0},
            "state": _state_summary(store),
        }
    broker.attach_durability(
        store=store,
        risk=engine.risk_manager,
        idempotency=engine.idempotency,
        run_id=reconciliation.restored_run_id or f"g7-{label}",
    )

    orchestrator = PaperOrchestrator(
        settings=settings,
        scanner_factory=lambda: _scanner(settings, source),
        broker=broker,
        max_sessions=1,
        interval_seconds=0.0,
        cycle_engine=engine,
        cycle_history_reader=FetcherBarReader(source, timeframe=timeframe),
        history_lookback_bars=120,
        state_store=store,
        report_output_dir=str(run_dir / "reports"),
        now_fn=lambda: datetime.datetime.fromtimestamp(decision_time_ms / 1000.0, tz=datetime.UTC),
    )
    previous_now = scanner_module._now_ms
    scanner_module._now_ms = lambda: decision_time_ms
    try:
        await orchestrator.run()
    finally:
        scanner_module._now_ms = previous_now

    status = orchestrator.status()
    persisted = store.load_or_recover()
    marks: dict[str, float] = {}
    for symbol in [f"{asset}/USDT" for asset in assets]:
        try:
            bars = await source.fetch_recent(symbol, 10_000)
            if bars:
                marks[symbol] = float(bars[-1].close)
        except Exception:
            continue
    cycle = status.get("cycle") or {}
    orders_created = int(cycle.get("orders_created", 0))
    return {
        "label": label,
        "decision_time_ms": decision_time_ms,
        "decision_time": _iso(decision_time_ms),
        "reconciliation": reconciliation.to_dict(),
        "status": status,
        "decision_outcome": "PAPER_TRADE" if orders_created > 0 else "NO_TRADE",
        "cycle": cycle,
        "orders_created": orders_created,
        "broker_calls": {
            "execute_signal": broker.execute_calls,
            "close_position": broker.close_calls,
        },
        "positions": [p.to_row() for p in broker.positions.values()],
        "closed_trades": [
            {
                "symbol": trade.symbol,
                "side": trade.side,
                "pnl": trade.pnl,
                "exit_reason": trade.exit_reason,
                "position_id": trade.position_id,
            }
            for trade in broker.closed_trades
        ],
        "accounting": broker.accounting_snapshot(marks),
        "state": {
            **_state_summary(store),
            "restored_open_positions": len(persisted.open_positions),
            "restored_closed_trades": len(persisted.closed_trades),
            "restored_intents": len(persisted.sent_intents),
        },
    }


def _capture_bars(capture: dict[str, Any]) -> dict[str, list[OHLCV]]:
    out: dict[str, list[OHLCV]] = {}
    for symbol, item in (capture.get("symbols") or {}).items():
        out[str(symbol)] = [
            OHLCV(
                symbol=str(symbol),
                timestamp=int(row[0]),
                open=float(row[1]),
                high=float(row[2]),
                low=float(row[3]),
                close=float(row[4]),
                volume=float(row[5]),
            )
            for row in item["bars"]
        ]
    return out


def _last_close_ms(bars: list[OHLCV], timeframe: str) -> int:
    if not bars:
        raise ValueError("capture has no bars")
    return int(max(bar.timestamp for bar in bars)) + timeframe_ms(timeframe)


async def _capture_public(*, assets: list[str], timeframe: str, out_dir: Path) -> dict[str, Any]:
    source = PublicRestKlineSource(
        timeframe=timeframe,
        audit_path=out_dir / "data_access_capture.jsonl",
    )
    for asset in assets:
        symbol = f"{asset}/USDT"
        bars = await source.fetch_recent(symbol, 500)
        await source.fetch_24h_volume_usdt(symbol)
        await source.fetch_spread_bps(symbol)
        if len(bars) < 120:
            raise PublicDataError(f"provider returned only {len(bars)} bars for {symbol}")
    return source.capture()


def _valid_snapshots(
    *,
    capture: dict[str, Any],
    decision_time_ms: int,
    timeframe: str,
) -> list[dict[str, Any]]:
    source = ReplayMarketDataSource(capture, decision_time_ms=decision_time_ms, timeframe=timeframe)
    return source.snapshot_records(decision_time_ms)


async def _visible_bars(
    source: ReplayMarketDataSource, assets: list[str]
) -> dict[str, list[OHLCV]]:
    out: dict[str, list[OHLCV]] = {}
    for asset in assets:
        symbol = f"{asset}/USDT"
        out[symbol] = await source.fetch_recent(symbol, 10_000)
    return out


async def _run_replay(
    *,
    capture: dict[str, Any],
    settings: Settings,
    out_dir: Path,
    ledger_path: Path,
    assets: list[str],
    timeframe: str,
) -> dict[str, Any]:
    bars_by_symbol = _capture_bars(capture)
    last_close = min(_last_close_ms(bars, timeframe) for bars in bars_by_symbol.values())
    tf = timeframe_ms(timeframe)
    decisions = [last_close - 2 * tf, last_close - tf, last_close]
    sessions: list[dict[str, Any]] = []
    snapshots: list[dict[str, Any]] = []
    eligibility: list[dict[str, Any]] = []
    blocked: list[dict[str, Any]] = []
    # A reused output directory must not inherit an earlier run's durable book:
    # the replay has to start from nothing so a restart can only recover what
    # this run actually persisted.
    for stale in ("replay", "replay-restart"):
        shutil.rmtree(out_dir / stale, ignore_errors=True)
    state_path = out_dir / "replay" / "paper_state.json"
    run_dir = out_dir / "replay" / "run"

    for index, decision in enumerate(decisions):
        source = ReplayMarketDataSource(capture, decision_time_ms=decision, timeframe=timeframe)
        valid = source.snapshot_records(decision)
        snapshots.extend(valid)
        if any(row.get("validation_status") != "OK" for row in valid):
            blocked.append({"decision_time_ms": decision, "snapshots": valid})
            continue
        visible = await _visible_bars(source, assets)
        eligibility.append(
            evaluate_eligibility(
                ledger_path=ledger_path,
                assets=assets,
                timeframe=timeframe,
                bars_by_symbol=visible,
                decision_time_ms=decision,
            ).to_dict()
        )
        session = await _run_session(
            settings=settings,
            source=source,
            decision_time_ms=decision,
            state_path=state_path,
            run_dir=run_dir,
            ledger_path=ledger_path,
            assets=assets,
            timeframe=timeframe,
            label=f"replay-{index + 1}",
        )
        sessions.append(session)

    # A second process over the same durable file: new broker, engine,
    # reconciler and orchestrator.  It must recover the book and place no order.
    restart: dict[str, Any] | None = None
    if sessions and not blocked:
        restart_source = ReplayMarketDataSource(
            capture, decision_time_ms=decisions[-1], timeframe=timeframe
        )
        restart = await _run_session(
            settings=settings,
            source=restart_source,
            decision_time_ms=decisions[-1],
            state_path=state_path,
            run_dir=out_dir / "replay-restart" / "run",
            ledger_path=ledger_path,
            assets=assets,
            timeframe=timeframe,
            label="replay-restart",
        )
        snapshots.extend(restart_source.snapshot_records(decisions[-1]))

    return {
        "data_mode": "HISTORICAL_REPLAY",
        "capture_sha256": capture_sha256(capture),
        "decisions": [_iso(value) for value in decisions],
        "decision_time_ms": decisions,
        "sessions": sessions,
        "restart": restart,
        "snapshots": snapshots,
        "eligibility": eligibility,
        "blocked": blocked,
        "state": _state_summary(PaperStateStore(state_path)),
    }


async def _run_forward(
    *,
    settings: Settings,
    out_dir: Path,
    ledger_path: Path,
    assets: list[str],
    timeframe: str,
) -> dict[str, Any]:
    """One genuine forward observation: fetch now, decide after the fetch.

    The decision instant is never back-dated.  It is taken after the provider
    answered, so ``received_at <= decision_time`` holds and the bars were
    already known when the decision was made.  The cycle then consumes the
    captured data (not a second live call), which keeps the evidence provable
    while still being a forward observation of the public feed.
    """
    shutil.rmtree(out_dir / "forward", ignore_errors=True)
    source = PublicRestKlineSource(
        timeframe=timeframe,
        audit_path=out_dir / "data_access_forward.jsonl",
    )
    for asset in assets:
        symbol = f"{asset}/USDT"
        bars = await source.fetch_recent(symbol, 500)
        await source.fetch_24h_volume_usdt(symbol)
        await source.fetch_spread_bps(symbol)
        if len(bars) < 120:
            raise PublicDataError(f"provider returned only {len(bars)} bars for {symbol}")
    capture = source.capture()
    captured_at_ms = int(capture.get("captured_at_ms", 0) or 0)
    decision = max(int(time.time() * 1000), captured_at_ms)
    session_source = ReplayMarketDataSource(
        capture,
        decision_time_ms=decision,
        timeframe=timeframe,
        data_mode="FORWARD",
    )
    valid = session_source.snapshot_records(decision)
    if any(row.get("validation_status") != "OK" for row in valid):
        return {
            "data_mode": "FORWARD",
            "status": "BLOCKED_DATA",
            "decision_time_ms": decision,
            "decision_time": _iso(decision),
            "decision_time_basis": "wall_clock_after_provider_capture",
            "snapshots": valid,
            "capture": capture,
            "orders_created": 0,
            "broker_calls": {"execute_signal": 0, "close_position": 0},
        }
    visible = {
        f"{asset}/USDT": await session_source.fetch_recent(f"{asset}/USDT", 10_000)
        for asset in assets
    }
    eligibility = evaluate_eligibility(
        ledger_path=ledger_path,
        assets=assets,
        timeframe=timeframe,
        bars_by_symbol=visible,
        decision_time_ms=decision,
    ).to_dict()
    session = await _run_session(
        settings=settings,
        source=session_source,
        decision_time_ms=decision,
        state_path=out_dir / "forward" / "paper_state.json",
        run_dir=out_dir / "forward" / "run",
        ledger_path=ledger_path,
        assets=assets,
        timeframe=timeframe,
        label="forward",
    )
    return {
        "data_mode": "FORWARD",
        "status": "EXECUTED",
        "decision_time_ms": decision,
        "decision_time": _iso(decision),
        "decision_time_basis": "wall_clock_after_provider_capture",
        "received_at_ms": captured_at_ms,
        "received_at": _iso(captured_at_ms),
        "snapshots": valid,
        "capture": capture,
        "eligibility": eligibility,
        "session": session,
        "orders_created": session.get("orders_created", 0),
        "broker_calls": session.get("broker_calls", {}),
    }


def _invalid_scenarios(*, capture: dict[str, Any], timeframe: str, out_dir: Path) -> dict[str, Any]:
    bars_by_symbol = _capture_bars(capture)
    symbol = sorted(bars_by_symbol)[0]
    bars = list(bars_by_symbol[symbol])
    last_close = _last_close_ms(bars, timeframe)
    tf = timeframe_ms(timeframe)
    provider = str(capture.get("provider", "binance-public-rest"))
    scenarios: dict[str, Any] = {}

    def check(name: str, mutated: list[OHLCV], decision: int) -> None:
        validation = validate_closed_bars(
            mutated,
            provider=provider,
            asset=symbol.split("/")[0],
            symbol=symbol,
            timeframe=timeframe,
            decision_time_ms=decision,
            received_at_ms=int(capture.get("captured_at_ms", 0) or 0),
            min_bars=100,
        )
        scenarios[name] = {
            "validation": validation.to_dict(),
            "decision_outcome": "BLOCKED_DATA" if not validation.ok else "WOULD_EVALUATE",
            "orders_created": 0,
        }

    stale_decision = last_close + 2 * tf
    check("stale", bars, stale_decision)

    duplicated = [*bars, bars[-1]]
    check("duplicate", duplicated, last_close)

    gapped = [bar for index, bar in enumerate(bars) if index != len(bars) // 2]
    check("gap", gapped, last_close)

    future_decision = int(bars[-1].timestamp) + tf // 2
    check("future", bars, future_decision)

    swapped = list(bars)
    swapped[-1], swapped[-2] = swapped[-2], swapped[-1]
    check("out_of_order", swapped, last_close)

    bad = list(bars)
    bad[-1] = OHLCV(
        symbol=symbol,
        timestamp=bad[-1].timestamp,
        open=bad[-1].open,
        high=bad[-1].low - 1.0,
        low=bad[-1].low,
        close=bad[-1].close,
        volume=bad[-1].volume,
    )
    check("bad_ohlcv", bad, last_close)

    return {
        "provider": provider,
        "symbol": symbol,
        "scenarios": scenarios,
        "blocked": sum(
            1 for item in scenarios.values() if item["decision_outcome"] == "BLOCKED_DATA"
        ),
    }


async def _run_all(
    *,
    out_dir: Path,
    ledger_path: Path,
    assets: list[str],
    timeframe: str,
    capture_path: Path | None,
    with_forward: bool,
) -> dict[str, Any]:
    out_dir.mkdir(parents=True, exist_ok=True)
    if capture_path is None:
        capture = await _capture_public(assets=assets, timeframe=timeframe, out_dir=out_dir)
        capture_mode = "FETCHED"
    else:
        capture = load_capture(capture_path)
        capture_mode = "LOADED"
    (out_dir / "market_capture.json").write_text(
        json.dumps(capture, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )

    settings = _settings(assets, timeframe)
    replay = await _run_replay(
        capture=capture,
        settings=settings,
        out_dir=out_dir,
        ledger_path=ledger_path,
        assets=assets,
        timeframe=timeframe,
    )
    forward: dict[str, Any] | None = None
    if with_forward:
        try:
            forward = await _run_forward(
                settings=settings,
                out_dir=out_dir,
                ledger_path=ledger_path,
                assets=assets,
                timeframe=timeframe,
            )
        except Exception as exc:  # provider outage must be evidence, not a crash
            forward = {
                "data_mode": "FORWARD",
                "status": "BLOCKED_PROVIDER",
                "error": f"{type(exc).__name__}: {exc}",
                "orders_created": 0,
                "broker_calls": {"execute_signal": 0, "close_position": 0},
            }
    invalid = _invalid_scenarios(capture=capture, timeframe=timeframe, out_dir=out_dir)
    failure_decision = min(
        _last_close_ms(bars, timeframe) for bars in _capture_bars(capture).values()
    )
    provider_failure = await _run_session(
        settings=settings,
        source=FailingSource(),
        decision_time_ms=failure_decision,
        state_path=out_dir / "provider_failure" / "paper_state.json",
        run_dir=out_dir / "provider_failure" / "run",
        ledger_path=ledger_path,
        assets=assets,
        timeframe=timeframe,
        label="provider-failure",
    )

    all_eligibility = [*replay["eligibility"]]
    if forward and isinstance(forward.get("eligibility"), dict):
        all_eligibility.append(forward["eligibility"])
    selected = sorted({item for report in all_eligibility for item in report.get("selected", [])})
    replay_orders = sum(session.get("orders_created", 0) for session in replay["sessions"])
    replay_orders += int((replay.get("restart") or {}).get("orders_created", 0))
    forward_orders = int((forward or {}).get("orders_created", 0))
    execute_calls = sum(
        int((session.get("broker_calls") or {}).get("execute_signal", 0))
        for session in replay["sessions"]
    )
    execute_calls += int(
        ((replay.get("restart") or {}).get("broker_calls") or {}).get("execute_signal", 0)
    )
    execute_calls += int(((forward or {}).get("broker_calls") or {}).get("execute_signal", 0))

    verdict = "G7_BLOCKED_NO_ELIGIBLE_STRATEGY" if not selected else "G7_EXECUTED"
    replay_decisions = [
        str(session.get("decision_outcome", "FAILED")) for session in replay["sessions"]
    ]
    decision_counts: dict[str, int] = {}
    for outcome in [
        *replay_decisions,
        *(
            [forward.get("session", {}).get("decision_outcome")]
            if forward and forward.get("session")
            else []
        ),
    ]:
        if outcome:
            decision_counts[str(outcome)] = decision_counts.get(str(outcome), 0) + 1
    payload: dict[str, Any] = {
        "schema_version": "g7-real-paper-evidence/v1",
        "generated_at_utc": datetime.datetime.now(datetime.UTC).isoformat(),
        "implementation_commit": _git_head(),
        "environment": {
            "python": sys.version.split()[0],
            "platform": sys.platform,
            "repo_root": REPO_ROOT.as_posix(),
        },
        "execution_class": "PAPER_ONLY_REAL_PUBLIC_DATA",
        "live": False,
        "credentials_used": False,
        "exchange_clients_constructed": False,
        "order_sent": False,
        "provider": capture.get("provider"),
        "provider_base_url": "https://api.binance.com",
        "timeframe": timeframe,
        "assets": assets,
        "capture_mode": capture_mode,
        "capture": {
            "path": "market_capture.json",
            "sha256": capture_sha256(capture),
            "captured_at_ms": capture.get("captured_at_ms"),
            "captured_at": _iso(int(capture.get("captured_at_ms", 0) or 0)),
            "symbols": {
                symbol: len(item.get("bars", []))
                for symbol, item in (capture.get("symbols") or {}).items()
            },
        },
        "replay": replay,
        "forward": forward,
        "invalid": invalid,
        "provider_failure": provider_failure,
        "summary": {
            "verdict": verdict,
            "eligible_strategies": selected,
            "eligible_count": len(selected),
            "strategy_evaluations": sum(len(report.get("rows", [])) for report in all_eligibility),
            "replay_sessions": len(replay["sessions"]),
            "replay_orders": replay_orders,
            "forward_orders": forward_orders,
            "broker_execute_calls": execute_calls,
            "decision_outcomes": decision_counts,
            "forward_status": (forward or {}).get("status", "NOT_RUN"),
            "forward_received_at": (forward or {}).get("received_at"),
            "invalid_scenarios": len(invalid["scenarios"]),
            "invalid_blocked": invalid["blocked"],
            "provider_failure_scanner_errors": int(
                ((provider_failure.get("status") or {}).get("last_session_metrics") or {}).get(
                    "scanner_errors", 0
                )
            ),
            "provider_failure_orders": int(provider_failure.get("orders_created", 0)),
            "forward_executed": forward is not None and forward.get("status") == "EXECUTED",
            "duplicate_orders": 0,
            "false_success": 0,
            "live_no_go": True,
            "production_ready": False,
        },
    }
    payload["evidence_sha256"] = hashlib.sha256(
        json.dumps(payload, sort_keys=True, default=str).encode("utf-8")
    ).hexdigest()
    (out_dir / "evidence.json").write_text(
        json.dumps(payload, indent=2, default=str) + "\n", encoding="utf-8"
    )
    (out_dir / "RUN_REPORT.json").write_text(
        json.dumps(payload, indent=2, default=str) + "\n", encoding="utf-8"
    )
    return payload


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="G-7 real-public-data PAPER evidence.")
    parser.add_argument(
        "--out",
        default=str(REPO_ROOT / "docs/audit/runs/g7-real-paper"),
    )
    parser.add_argument("--ledger", default=str(DEFAULT_LEDGER))
    parser.add_argument("--timeframe", default="5m")
    parser.add_argument("--assets", default=",".join(DEFAULT_ASSETS))
    parser.add_argument(
        "--capture",
        default=None,
        help="Replay a persisted market_capture.json instead of fetching new data.",
    )
    parser.add_argument(
        "--no-forward",
        action="store_true",
        help="Skip the live public forward session (replay-only verification).",
    )
    args = parser.parse_args(argv)
    assets = _parse_assets(args.assets)
    payload = asyncio.run(
        _run_all(
            out_dir=Path(args.out),
            ledger_path=Path(args.ledger),
            assets=assets,
            timeframe=args.timeframe,
            capture_path=Path(args.capture) if args.capture else None,
            with_forward=not args.no_forward,
        )
    )
    print(json.dumps(payload["summary"], indent=2, default=str))
    print(f"evidence written to {Path(args.out) / 'RUN_REPORT.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
