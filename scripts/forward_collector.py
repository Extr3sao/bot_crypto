"""FORWARD COLLECTOR CLI — capture, replay, report.

DISCOVERY PLANE ONLY (§3, §4, §39). Read-only public market data; no keys, no
orders, no account endpoints, no capital, and no interaction with the trading
decision path.

Modes
-----
``run``     start (or resume) a WebSocket-first forward capture.
``replay``  reconstruct a capture from disk with no network and verify it.
``report``  aggregate the capture, then write the machine-readable quality /
            resource / daily / replay artifacts.
``daily``   print the compact FORWARD_DATA_DAILY_REPORT.

Examples
--------
    uv run python scripts/forward_collector.py --smoke
    uv run python scripts/forward_collector.py --duration 3600
    uv run python scripts/forward_collector.py --resume --run-id forward-...
    uv run python scripts/forward_collector.py --mode replay
    uv run python scripts/forward_collector.py --mode report
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

from trading_bot.research.forward.collector import (
    PERP_REST,
    SPOT_REST,
    CollectorConfig,
    ForwardCollector,
)
from trading_bot.research.forward.contract import Market
from trading_bot.research.forward.outcome import (
    EXIT_FAILED,
    FAILURE_MANIFEST,
    CaptureStatus,
)
from trading_bot.research.forward.replay import replay_microstructure_dataset
from trading_bot.research.forward.reporting import (
    REPORT_VERSION,
    build_aggregation,
    build_daily_report,
    build_quality_report,
    build_resource_report,
    load_run,
    save_aggregation,
    write_machine_readable_reports,
)
from trading_bot.research.forward.storage import DEFAULT_ROOT

SMOKE_DURATION_SECONDS = 20.0


def _parse_symbols(raw: str) -> tuple[str, ...]:
    symbols = tuple(part.strip().upper() for part in raw.split(",") if part.strip())
    if not symbols:
        raise SystemExit("--symbols must list at least one symbol")
    return symbols


def _parse_markets(raw: str) -> tuple[Market, ...]:
    markets: list[Market] = []
    for part in raw.split(","):
        token = part.strip().lower()
        if not token:
            continue
        try:
            markets.append(Market(token))
        except ValueError as exc:
            raise SystemExit(f"unknown market {token!r}; expected 'spot' or 'perp'") from exc
    if not markets:
        raise SystemExit("--markets must list at least one market")
    return tuple(markets)


def _parse_streams(raw: str) -> tuple[str, ...]:
    streams = tuple(part.strip().lower() for part in raw.split(",") if part.strip())
    if not streams:
        raise SystemExit("--streams must list at least one stream")
    return streams


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Forward microstructure collector (DISCOVERY PLANE, read-only).",
    )
    parser.add_argument("--mode", choices=("run", "replay", "report", "daily"), default="run")
    parser.add_argument("--symbols", default="BTCUSDT,ETHUSDT,SOLUSDT")
    parser.add_argument("--markets", default="spot,perp")
    parser.add_argument("--out", default=DEFAULT_ROOT)
    parser.add_argument(
        "--data-root",
        default=None,
        help=(
            "§16 — where segments, manifests, lineage and reports live. Overrides "
            "--out so a capture can be pointed at another volume without moving "
            "the code; the resume state and stop file follow the same root"
        ),
    )
    parser.add_argument("--docs-dir", default="docs")
    parser.add_argument("--run-id", default=None)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--duration", type=float, default=None)
    parser.add_argument("--rotation-seconds", type=int, default=3600)
    parser.add_argument("--heartbeat-seconds", type=float, default=60.0)
    parser.add_argument("--checkpoint-seconds", type=float, default=30.0)
    parser.add_argument("--oi-interval-seconds", type=float, default=60.0)
    parser.add_argument("--premium-interval-seconds", type=float, default=60.0)
    parser.add_argument("--depth-limit", type=int, default=1000)
    parser.add_argument("--depth-n", type=int, default=10)
    parser.add_argument("--max-event-skew-ms", type=int, default=500)
    parser.add_argument("--read-timeout-seconds", type=float, default=30.0)
    parser.add_argument("--stale-after-ms", type=int, default=5_000)
    parser.add_argument(
        "--streams",
        default="agg_trade,depth,book_ticker",
        help="WebSocket streams to persist (default: all three)",
    )
    parser.add_argument(
        "--max-total-bytes",
        type=int,
        default=None,
        help="stop gracefully once the dataset reaches this size (disk safety valve)",
    )
    parser.add_argument(
        "--min-free-bytes",
        type=int,
        default=None,
        help=(
            "stop gracefully once the *filesystem* has less than this much free "
            "space; the last barrier on a host that is shared with everything else"
        ),
    )
    parser.add_argument(
        "--stop-file",
        default=None,
        help=(
            "path whose appearance stops the capture gracefully (seal + manifest); "
            "the portable stop a supervisor can ask for"
        ),
    )
    parser.add_argument(
        "--drop-raw",
        action="store_true",
        help="omit the verbatim exchange payload (RAW FIRST is on by default)",
    )
    parser.add_argument(
        "--smoke",
        action="store_true",
        help="short pipeline exercise: 20s capture, fast rotation",
    )
    return parser


def _config_from_args(args: argparse.Namespace) -> CollectorConfig:
    duration = args.duration
    rotation = args.rotation_seconds
    heartbeat = args.heartbeat_seconds
    checkpoint = args.checkpoint_seconds
    read_timeout = args.read_timeout_seconds
    if args.smoke:
        duration = SMOKE_DURATION_SECONDS if duration is None else duration
        rotation = 60
        heartbeat = 10.0
        checkpoint = 5.0
        read_timeout = 10.0
    return CollectorConfig(
        symbols=_parse_symbols(args.symbols),
        markets=_parse_markets(args.markets),
        root=Path(args.data_root or args.out),
        rotation_seconds=rotation,
        duration_seconds=duration,
        heartbeat_seconds=heartbeat,
        checkpoint_seconds=checkpoint,
        oi_interval_seconds=args.oi_interval_seconds,
        premium_interval_seconds=args.premium_interval_seconds,
        depth_limit=args.depth_limit,
        depth_n=args.depth_n,
        keep_raw=not args.drop_raw,
        max_event_skew_ms=args.max_event_skew_ms,
        read_timeout_seconds=read_timeout,
        stale_after_ms=args.stale_after_ms,
        streams=_parse_streams(args.streams),
        max_total_bytes=args.max_total_bytes,
        min_free_bytes=args.min_free_bytes,
        stop_file=Path(args.stop_file) if args.stop_file else None,
        run_id=args.run_id,
        resume=args.resume,
    )


def _json(payload: object) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=2, default=str)


def mode_run(args: argparse.Namespace) -> int:
    """Run a capture and exit with the verdict the manifest carries (§2).

    ``0`` means the capture ended cleanly (its duration, an operator's stop, or
    a disk guard) with every segment sealed and accounted for. ``2`` means it
    FAILED. The distinction exists because exit codes are what a supervisor and
    a wrapper script read; a capture whose writer died must never look like a
    capture that finished.
    """
    config = _config_from_args(args)
    collector = ForwardCollector(config)
    print(
        f"forward collector: run_id={collector.run_id} root={collector.root} "
        f"symbols={list(config.symbols)} markets={[m.value for m in config.markets]}",
        file=sys.stderr,
    )
    print(f"  endpoints: spot={SPOT_REST} perp={PERP_REST}", file=sys.stderr)
    print(
        f"  capture: duration={config.duration_seconds}s rotation={config.rotation_seconds}s "
        f"heartbeat={config.heartbeat_seconds}s checkpoint={config.checkpoint_seconds}s",
        file=sys.stderr,
    )
    print(
        f"  graceful stop: {config.stop_file if config.stop_file else 'signal only'}",
        file=sys.stderr,
    )
    try:
        manifest = asyncio.run(collector.run())
    except Exception as exc:
        # The manifest could not be written at all, so the only honest channel
        # left is this line and the exit code. Both say FAILED.
        failure = {
            "run_id": collector.run_id,
            "root": str(collector.root),
            "status": CaptureStatus.FAILED.value,
            "failure_kind": FAILURE_MANIFEST,
            "failure_reason": f"{type(exc).__name__}: {exc}",
            "stop_reason": collector.stop_reason,
            "exit_code": EXIT_FAILED,
        }
        print(_json(failure))
        print(
            f"forward collector: FAILED — the run could not finalise "
            f"({type(exc).__name__}: {exc}); no manifest was written",
            file=sys.stderr,
        )
        return EXIT_FAILED
    print(_json(manifest.as_dict()))
    outcome = manifest.outcome()
    print(
        f"manifest -> {collector.root / 'manifest' / (collector.run_id + '.json')}",
        file=sys.stderr,
    )
    print(f"forward collector: {outcome.describe()}", file=sys.stderr)
    if outcome.failed:
        print(
            "forward collector: FAILED — refusing to exit 0; the supervisor must "
            "see this as a crash, not a completed capture",
            file=sys.stderr,
        )
    return outcome.exit_code


def mode_replay(args: argparse.Namespace) -> int:
    verification = replay_microstructure_dataset(Path(args.out), args.run_id)
    print(_json(verification.as_dict()))
    return 0 if verification.ok else 1


def mode_report(args: argparse.Namespace) -> int:
    root = Path(args.out)
    run_id, manifest = load_run(root, args.run_id)
    _, aggregation = build_aggregation(root, run_id)
    aggregation_path = save_aggregation(root, run_id, aggregation)
    quality = build_quality_report(root, run_id)
    resource = build_resource_report(root, run_id)
    files = write_machine_readable_reports(root, args.docs_dir, run_id)
    print(
        _json(
            {
                "report_version": REPORT_VERSION,
                "run_id": run_id,
                "continuity": manifest.get("continuity"),
                "readiness": quality["readiness"],
                "resource_health": resource["resources"],
                "aggregation": str(aggregation_path),
                "written": {name: str(path) for name, path in files.items()},
            }
        )
    )
    return 0


def mode_daily(args: argparse.Namespace) -> int:
    print(_json(build_daily_report(Path(args.out), args.run_id)))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.mode == "run":
        return mode_run(args)
    if args.mode == "replay":
        return mode_replay(args)
    if args.mode == "report":
        return mode_report(args)
    return mode_daily(args)


if __name__ == "__main__":
    raise SystemExit(main())
