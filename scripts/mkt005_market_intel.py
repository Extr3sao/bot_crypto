"""RFC-TAP-MARKET-005 — continuous market intelligence, offline by default.

Subcommands, in the order the work package runs them:

``capture``   one real, public, read-only read of the exact universe/limits the
              research runtime uses (``real_market_context.FETCH_LIMITS``), saved
              as a replayable fixture with per-series hashes and timings.
``ingest``    the incremental plane: bootstrap once, then one bounded delta per
              cycle.  Reuses ``CCXTExchangeConnector`` + ``OHLCVStore``.
``baseline``  CURRENT vs PROPOSED on the same bars and the same scheduler
              cadence (15 minutes, like ``TradingAgentic-CAP004-Campaign``).
``snapshot``  the PIT snapshot gate + event-driven AI decision.  It never calls a
              model: with no authorized credential the answer is
              ``MISSING_CREDENTIAL`` and zero requests.

Nothing here writes to an exchange, an account, ``config/risk.yaml``, the
strategy admission file, the broker or the risk manager.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import tempfile
import time
from collections.abc import Sequence
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from trading_bot.market_data.candle_filter import timeframe_seconds_or_raise  # noqa: E402
from trading_bot.market_data.incremental import (  # noqa: E402
    IncrementalOHLCVIngestor,
    WatermarkStore,
    bar_sha256,
    closed_boundary_ms,
)
from trading_bot.market_data.market_events import (  # noqa: E402
    EventGate,
    EventTriggerConfig,
    ResponseCache,
)
from trading_bot.market_data.replay import ReplayConnector, load_fixture, save_fixture  # noqa: E402
from trading_bot.market_data.snapshot import (  # noqa: E402
    SnapshotUnavailable,
    build_market_snapshot,
    gate_snapshot,
)
from trading_bot.market_data.timeframe_store import OHLCVTimeframeStore  # noqa: E402
from trading_bot.research import real_market_context as rmc  # noqa: E402
from trading_bot.storage.ohlcv_store import OHLCVStore  # noqa: E402

DEFAULT_OUT = REPO / "reports" / "market-data" / "RFC-TAP-MARKET-005"
DEFAULT_STORE = REPO / "data" / "market" / "mkt005_ohlcv.sqlite"
DEFAULT_WATERMARKS = REPO / "data" / "market" / "watermarks"
SOURCE_ID = "binance_public_ccxt"
#: The installed scheduler runs every 15 minutes (CAP004 DEFAULT_INTERVAL_SECONDS).
SCHEDULER_STEP_MS = 900_000


def _series_specs() -> list[tuple[str, str, int]]:
    """``(provider_symbol, ccxt_timeframe, warmup_limit)`` — the runtime workload."""
    specs: list[tuple[str, str, int]] = []
    for asset in rmc.CAMPAIGN_ASSETS:
        for interval_key, (ccxt_interval, _seconds) in rmc.CONTRACT_INTERVALS.items():
            specs.append(
                (rmc.PROVIDER_SYMBOLS[asset], ccxt_interval, rmc.FETCH_LIMITS[interval_key])
            )
    return specs


def _live_connector() -> Any:
    return rmc.make_connector()


def _read_rows_raw(
    connector: Any, symbol: str, timeframe: str, limit: int
) -> tuple[list[Any], float, dict[str, Any]]:
    started = time.perf_counter()
    rows = connector.fetch_ohlcv(symbol, timeframe, limit=limit)
    elapsed = (time.perf_counter() - started) * 1_000.0
    return (
        rows,
        elapsed,
        {"symbol": symbol, "timeframe": timeframe, "limit": limit, "rows": len(rows)},
    )


def cmd_capture(args: argparse.Namespace) -> int:
    connector = _live_connector()
    now_ms = int(time.time() * 1_000)
    series: dict[str, dict[str, list[list[float]]]] = {}
    requests: list[dict[str, Any]] = []
    for symbol, timeframe, limit in _series_specs():
        rows, elapsed, meta = _read_rows_raw(connector, symbol, timeframe, limit)
        meta["elapsed_ms"] = round(elapsed, 3)
        meta["sha256"] = bar_sha256(rows)
        meta["first_open_ms"] = int(rows[0].timestamp) if rows else None
        meta["last_open_ms"] = int(rows[-1].timestamp) if rows else None
        requests.append(meta)
        series.setdefault(symbol, {})[timeframe] = [
            [int(r.timestamp), r.open, r.high, r.low, r.close, r.volume] for r in rows
        ]
    payload = {
        "source": SOURCE_ID,
        "kind": "CAPTURED_PUBLIC_MARKET_DATA",
        "captured_at_ms": now_ms,
        "captured_at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now_ms / 1_000)),
        "provider": rmc.PROVIDER,
        "limits_source": "trading_bot.research.real_market_context.FETCH_LIMITS",
        "requests": requests,
        "series": series,
    }
    target = save_fixture(args.fixture, payload)
    print(
        json.dumps(
            {"fixture": str(target), "series": len(requests), "requests": requests}, indent=2
        )
    )
    return 0


def _load_series(args: argparse.Namespace) -> tuple[dict[str, dict[str, list[list[float]]]], int]:
    fixture = load_fixture(args.fixture)
    captured = int(fixture["captured_at_ms"])
    now = int(args.now_ms) if args.now_ms is not None else captured
    return fixture["series"], now


def _replay(
    series: dict[str, dict[str, list[list[float]]]], now_ms: int, **kwargs: Any
) -> ReplayConnector:
    return ReplayConnector(series, now_ms=lambda: now_ms, **kwargs)


def cmd_ingest(args: argparse.Namespace) -> int:
    store_path = Path(args.store)
    store = OHLCVTimeframeStore(OHLCVStore(f"sqlite:///{store_path.as_posix()}"))
    watermarks = WatermarkStore(args.watermarks)
    ledger_path = Path(args.ledger)
    ledger_path.parent.mkdir(parents=True, exist_ok=True)
    results: list[dict[str, Any]] = []
    clock_ms: int
    if args.fixture:
        series, captured_now = _load_series(args)
        clock_box = {"now": int(args.now_ms) if args.now_ms is not None else captured_now}
        connector: Any = ReplayConnector(series, now_ms=lambda: clock_box["now"])
        clock_ms = clock_box["now"]
    else:
        if args.cycles != 1:
            raise SystemExit("live mode runs one cycle per process; schedule it instead of looping")
        connector = _live_connector()
        clock_ms = int(args.now_ms) if args.now_ms is not None else int(time.time() * 1_000)
        clock_box = {"now": clock_ms}
    try:
        for cycle in range(args.cycles):
            clock_box["now"] = clock_ms + cycle * args.step_ms
            for symbol, timeframe, limit in _series_specs():
                ingestor = IncrementalOHLCVIngestor(
                    connector=connector,
                    store=store,
                    watermarks=watermarks,
                    source_id=SOURCE_ID,
                    warmup_bars=limit,
                )
                result = ingestor.ingest(
                    symbol,
                    timeframe,
                    now_ms=clock_box["now"],
                    reconcile=args.reconcile and cycle == 0,
                )
                row = result.to_json()
                row["run_id_cli"] = args.run_id
                row["cycle"] = cycle
                results.append(row)
                with ledger_path.open("a", encoding="utf-8") as handle:
                    handle.write(json.dumps(row, separators=(",", ":"), sort_keys=True) + "\n")
    finally:
        store.close()
    clock_ms = clock_box["now"]
    summary = {
        "run_id": args.run_id,
        "mode": "REPLAY" if args.fixture else "LIVE",
        "now_ms": clock_ms,
        "results": results,
        "requests_made": sum(int(r["requests_made"]) for r in results),
        "rows_returned": sum(int(r["rows_returned"]) for r in results),
        "rows_new": sum(int(r["rows_new"]) for r in results),
        "statuses": {
            r["status"]: sum(1 for x in results if x["status"] == r["status"]) for r in results
        },
    }
    if args.out:
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(
            json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
    print(
        json.dumps(
            {
                k: summary[k]
                for k in (
                    "mode",
                    "now_ms",
                    "requests_made",
                    "rows_returned",
                    "rows_new",
                    "statuses",
                )
            },
            indent=2,
        )
    )
    return 0


def _closed_tail(rows: Sequence[Any], timeframe: str, at_ms: int, take: int) -> list[Any]:
    bar_ms = timeframe_seconds_or_raise(timeframe) * 1_000
    closed = [r for r in rows if int(r.timestamp) + bar_ms <= at_ms]
    return closed[-take:]


def cmd_baseline(args: argparse.Namespace) -> int:
    series, captured_now = _load_series(args)
    start = captured_now - args.cycles * SCHEDULER_STEP_MS
    store_dir = Path(tempfile.mkdtemp(prefix="mkt005-baseline-"))
    report: dict[str, Any] = {
        "run_id": args.run_id,
        "kind": "CURRENT_VS_PROPOSED",
        "fixture": str(Path(args.fixture).resolve()),
        "fixture_sha256": _file_sha256(Path(args.fixture)),
        "cycles": args.cycles,
        "step_ms": SCHEDULER_STEP_MS,
        "decision_bars": args.decision_bars,
        "start_ms": start,
        "end_ms": captured_now,
        "series": [],
        "totals": {},
    }
    try:
        for symbol, timeframe, limit in _series_specs():
            clock_box = {"now": start}
            connector = ReplayConnector(series, now_ms=lambda box=clock_box: box["now"])
            store = OHLCVTimeframeStore(
                OHLCVStore(f"sqlite:///{(store_dir / 'ohlcv.sqlite').as_posix()}")
            )
            watermarks = WatermarkStore(store_dir / "watermarks")
            ingestor = IncrementalOHLCVIngestor(
                connector=connector,
                store=store,
                watermarks=watermarks,
                source_id=SOURCE_ID,
                warmup_bars=limit,
            )
            current_rows: list[Any] = []
            proposed_rows: list[Any] = []
            current_requests = 0
            current_transferred = 0
            proposal_requests = 0
            proposal_transferred = 0
            statuses: dict[str, int] = {}
            for cycle in range(args.cycles + 1):
                clock_box["now"] = start + cycle * SCHEDULER_STEP_MS
                at = clock_box["now"]
                # CURRENT: the shape the research runtime issues today.
                current = connector.fetch_ohlcv(symbol, timeframe, limit=limit)
                current_requests += 1
                current_transferred += len(current)
                current_rows = current
                # PROPOSED: bootstrap once, then bounded delta.
                before_calls = len(connector.calls)
                result = ingestor.ingest(symbol, timeframe, now_ms=at)
                proposal_requests += int(result.requests_made)
                proposal_transferred += int(result.rows_returned)
                assert len(connector.calls) - before_calls == int(result.requests_made)
                statuses[result.status] = statuses.get(result.status, 0) + 1
                proposed_rows = store.tail(symbol, timeframe, limit)
            at = clock_box["now"]
            current_tail = _closed_tail(current_rows, timeframe, at, args.decision_bars)
            proposed_tail = _closed_tail(proposed_rows, timeframe, at, args.decision_bars)
            equivalent = bar_sha256(current_tail) == bar_sha256(proposed_tail)
            report["series"].append(
                {
                    "symbol": symbol,
                    "timeframe": timeframe,
                    "warmup_limit": limit,
                    "current": {
                        "requests": current_requests,
                        "rows_transferred": current_transferred,
                    },
                    "proposed": {
                        "requests": proposal_requests,
                        "rows_transferred": proposal_transferred,
                        "statuses": statuses,
                    },
                    "reduction": {
                        "requests": current_requests - proposal_requests,
                        "requests_pct": round(
                            100.0 * (current_requests - proposal_requests) / current_requests, 2
                        ),
                        "rows": current_transferred - proposal_transferred,
                        "rows_pct": round(
                            100.0
                            * (current_transferred - proposal_transferred)
                            / current_transferred,
                            2,
                        ),
                    },
                    "data_equivalent": equivalent,
                    "current_tail_sha256": bar_sha256(current_tail),
                    "proposed_tail_sha256": bar_sha256(proposed_tail),
                    "current_tail_bars": len(current_tail),
                    "proposed_tail_bars": len(proposed_tail),
                }
            )
            store.close()
    finally:
        shutil.rmtree(store_dir, ignore_errors=True)

    rows = report["series"]
    report["totals"] = {
        "current_requests": sum(r["current"]["requests"] for r in rows),
        "proposed_requests": sum(r["proposed"]["requests"] for r in rows),
        "current_rows": sum(r["current"]["rows_transferred"] for r in rows),
        "proposed_rows": sum(r["proposed"]["rows_transferred"] for r in rows),
        "all_data_equivalent": all(r["data_equivalent"] for r in rows),
    }
    report["totals"]["requests_pct"] = round(
        100.0
        * (report["totals"]["current_requests"] - report["totals"]["proposed_requests"])
        / report["totals"]["current_requests"],
        2,
    )
    report["totals"]["rows_pct"] = round(
        100.0
        * (report["totals"]["current_rows"] - report["totals"]["proposed_rows"])
        / report["totals"]["current_rows"],
        2,
    )
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report["totals"], indent=2))
    return 0 if report["totals"]["all_data_equivalent"] else 1


def cmd_snapshot(args: argparse.Namespace) -> int:
    store = OHLCVTimeframeStore(OHLCVStore(f"sqlite:///{Path(args.store).as_posix()}"))
    at = int(args.at_ms)
    timeframes = ["1h", "4h", "1d"]
    outputs: list[dict[str, Any]] = []
    gate = EventGate(
        EventTriggerConfig(
            base_timeframe=args.base_timeframe,
            budget_usd=args.budget_usd,
            cost_per_attempt_usd=args.cost_per_attempt_usd,
            min_change_bps=args.min_change_bps,
        ),
        ledger_path=args.trigger_ledger,
    )
    cache = ResponseCache(args.cache_dir)
    try:
        for symbol in args.symbols:
            try:
                snapshot = build_market_snapshot(
                    store,
                    symbol=symbol,
                    timeframes=timeframes,
                    decision_ms=at,
                    source_id=SOURCE_ID,
                    bars_per_timeframe=args.bars,
                    now_ms=at,
                    quote=None,
                )
            except SnapshotUnavailable as exc:
                outputs.append({"symbol": symbol, "snapshot": None, "error": str(exc)})
                continue
            gate_result = gate_snapshot(snapshot, at_ms=at, require_quote=False)
            decision = gate.evaluate(
                snapshot,
                at_ms=at,
                credentials_present=args.credentials_present,
                allow_new_candle=True,
            )
            cached = cache.get(
                snapshot_hash=snapshot.content_hash,
                prompt_version=args.prompt_version,
                model_version=args.model_version,
                at_ms=at,
            )
            outputs.append(
                {
                    "symbol": symbol,
                    "snapshot": snapshot.to_json(),
                    "gate": gate_result.to_json(),
                    "trigger": decision.to_json(),
                    "cache": "HIT_FRESH" if cached else "MISS",
                }
            )
    finally:
        store.close()
    payload = {
        "run_id": args.run_id,
        "mode": "PIT_SNAPSHOT_OFFLINE",
        "at_ms": at,
        "credentials_present": bool(args.credentials_present),
        "model_calls": 0,
        "results": outputs,
    }
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(
        json.dumps(
            {
                "snapshots": sum(1 for o in outputs if o.get("snapshot")),
                "triggers": sum(1 for o in outputs if o.get("trigger", {}).get("should_analyze")),
                "model_calls": 0,
            },
            indent=2,
        )
    )
    return 0


def _file_sha256(path: Path) -> str:
    import hashlib

    return hashlib.sha256(path.read_bytes()).hexdigest()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="RFC-TAP-MARKET-005 market intelligence CLI")
    sub = parser.add_subparsers(dest="command", required=True)

    capture = sub.add_parser("capture", help="capture the runtime window once (public read-only)")
    capture.add_argument("--fixture", required=True)
    capture.set_defaults(func=cmd_capture)

    ingest = sub.add_parser("ingest", help="run one incremental cycle")
    ingest.add_argument("--fixture")
    ingest.add_argument("--now-ms", type=int)
    ingest.add_argument("--store", default=str(DEFAULT_STORE))
    ingest.add_argument("--watermarks", default=str(DEFAULT_WATERMARKS))
    ingest.add_argument("--ledger", default=str(DEFAULT_OUT / "COVERAGE_LEDGER.jsonl"))
    ingest.add_argument("--out")
    ingest.add_argument("--run-id", default="mkt005-ingest")
    ingest.add_argument("--cycles", type=int, default=1)
    ingest.add_argument("--step-ms", type=int, default=SCHEDULER_STEP_MS)
    ingest.add_argument("--reconcile", action="store_true")
    ingest.set_defaults(func=cmd_ingest)

    baseline = sub.add_parser("baseline", help="CURRENT vs PROPOSED on the same bars")
    baseline.add_argument("--fixture", required=True)
    baseline.add_argument("--now-ms", type=int)
    baseline.add_argument("--cycles", type=int, default=96)
    baseline.add_argument("--decision-bars", type=int, default=200)
    baseline.add_argument("--out", default=str(DEFAULT_OUT / "CURRENT_VS_PROPOSED.json"))
    baseline.add_argument("--run-id", default="mkt005-baseline")
    baseline.set_defaults(func=cmd_baseline)

    snapshot = sub.add_parser("snapshot", help="PIT snapshot + event trigger (no model call)")
    snapshot.add_argument("--store", default=str(DEFAULT_STORE))
    snapshot.add_argument("--at-ms", type=int, required=True)
    snapshot.add_argument("--symbols", nargs="+", default=["BTC/USDT"])
    snapshot.add_argument("--bars", type=int, default=300)
    snapshot.add_argument("--base-timeframe", default="1h")
    snapshot.add_argument("--budget-usd", type=float, default=0.0)
    snapshot.add_argument("--cost-per-attempt-usd", type=float, default=0.02)
    snapshot.add_argument("--min-change-bps", type=float, default=25.0)
    snapshot.add_argument("--credentials-present", action="store_true")
    snapshot.add_argument("--prompt-version", default="mkt005-v1")
    snapshot.add_argument("--model-version", default="none")
    snapshot.add_argument("--trigger-ledger", default=str(DEFAULT_OUT / "AI_TRIGGER_LEDGER.jsonl"))
    snapshot.add_argument("--cache-dir", default=str(REPO / "data" / "market" / "response_cache"))
    snapshot.add_argument("--out", default=str(DEFAULT_OUT / "SNAPSHOT_GATE_REPORT.json"))
    snapshot.add_argument("--run-id", default="mkt005-snapshot")
    snapshot.set_defaults(func=cmd_snapshot)

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if getattr(args, "command", None) == "baseline" and closed_boundary_ms(0, "1h") != 0:
        parser.error("bar clock invariant violated")  # pragma: no cover - structural guard
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
