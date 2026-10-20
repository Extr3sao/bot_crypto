"""exp_003j_replay — run one arm of RFC-TA-EXP-003J-001 over the frozen dataset.

    ./.venv/Scripts/python.exe scripts/exp_003j_replay.py --arm real --partition research
    ./.venv/Scripts/python.exe scripts/exp_003j_replay.py --arm control --partition oos --repeat 2

Both arms go through the **production** ``VisionLane``: the same ``RiskManager``, the same
``PaperBroker``, the same cost schedule, the same exit policy, the same ledger. The only
difference between them is the provider line — ``legacy_parity`` (the script) or
``strategy_experimental`` (the runtime family). Nothing in the risk policy, the sizing,
the broker slots, the fees, the stops or the accounting is touched, and the run record
proves that by carrying the exact bytes of both configurations.

The bars are 1-minute klines aggregated into 5-minute bars by **complete groups only**; an
incomplete group is dropped and counted, never filled. Fills happen at the next observable
bar open (``subbar_entries=False``), which is the lane's published default: no intrabar
price is invented, and a stop is resolved on the bar range with the ``BAR_WINDOW``
resolution the ledger already records.

What this script does not do: contact an exchange, read a credential, decide anything about
profitability, or write into another experiment's directory.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
if str(REPO / "src") not in sys.path:
    sys.path.insert(0, str(REPO / "src"))

from trading_bot.config.settings import load_settings  # noqa: E402
from trading_bot.research.economic_recovery.experiments import Bar  # noqa: E402
from trading_bot.vision.clock import timeframe_ms  # noqa: E402
from trading_bot.vision.lane import VisionLane  # noqa: E402
from trading_bot.vision.ledger import read_entries  # noqa: E402
from trading_bot.vision.prospective import display_symbol  # noqa: E402
from trading_bot.vision.settings import load_vision_config  # noqa: E402
from trading_bot.vision.signal_sources import (  # noqa: E402
    SIGNAL_SOURCE_LEGACY,
    SIGNAL_SOURCE_STRATEGY,
    STRATEGY_EMA_CROSSOVER,
    build_signal_provider,
)

EXPERIMENT_OUT = REPO / "reports" / "ai-bots" / "EXP-003J-REAL-SIGNAL-PAPER-001"
DATASET_DIR = EXPERIMENT_OUT / "dataset"
ARMS = {"control": SIGNAL_SOURCE_LEGACY, "real": SIGNAL_SOURCE_STRATEGY}


def _utc(ms: int) -> str:
    return datetime.fromtimestamp(int(ms) / 1000.0, tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse_utc(text: str) -> int:
    return int(
        datetime.strptime(text, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC).timestamp() * 1000
    )


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_minutes(path: Path) -> list[list[Any]]:
    import gzip

    with gzip.open(path, "rt", encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def aggregate(minutes: list[list[Any]], *, interval_ms: int) -> tuple[list[Bar], dict[str, Any]]:
    """1-minute rows → decision bars, complete groups only.

    A group is complete when it holds exactly ``interval_ms / 60_000`` distinct, aligned
    minutes. Anything else is counted and dropped: a partly observed bar would give the
    strategy a close nobody could have seen.
    """

    per_bar = int(interval_ms // 60_000)
    if per_bar < 1 or interval_ms % 60_000:
        raise ValueError(f"interval {interval_ms} is not a whole number of minutes")
    buckets: dict[int, list[list[Any]]] = {}
    for row in minutes:
        open_ms = int(row[0])
        buckets.setdefault(open_ms - (open_ms % interval_ms), []).append(row)
    bars: list[Bar] = []
    incomplete: list[dict[str, Any]] = []
    for open_ms in sorted(buckets):
        group = sorted(buckets[open_ms], key=lambda item: int(item[0]))
        stamps = [int(item[0]) for item in group]
        complete = (
            len(group) == per_bar
            and len(set(stamps)) == per_bar
            and stamps == [open_ms + index * 60_000 for index in range(per_bar)]
        )
        if not complete:
            incomplete.append(
                {
                    "bar_open_ms": int(open_ms),
                    "bar_open_utc": _utc(open_ms),
                    "minutes": len(group),
                    "expected": per_bar,
                }
            )
            continue
        bars.append(
            Bar(
                ts_ms=int(open_ms),
                open=float(group[0][1]),
                high=max(float(item[2]) for item in group),
                low=min(float(item[3]) for item in group),
                close=float(group[-1][4]),
                volume=sum(float(item[5]) for item in group),
            )
        )
    meta = {
        "minutes": len(minutes),
        "bars": len(bars),
        "interval_ms": int(interval_ms),
        "per_bar_minutes": per_bar,
        "incomplete_groups": len(incomplete),
        "incomplete_examples": incomplete[:10],
        "first_bar_utc": _utc(bars[0].ts_ms) if bars else None,
        "last_bar_utc": _utc(bars[-1].ts_ms) if bars else None,
    }
    return bars, meta


def load_series(
    *,
    symbols: list[str],
    start_ms: int,
    end_ms: int,
    interval_ms: int,
    dataset_dir: Path = DATASET_DIR,
) -> tuple[dict[str, list[Bar]], dict[str, Any]]:
    series: dict[str, list[Bar]] = {}
    report: dict[str, Any] = {}
    for symbol in symbols:
        path = dataset_dir / f"{symbol}.1m.jsonl.gz"
        if not path.exists():
            raise FileNotFoundError(
                f"frozen dataset missing {path.name}; run scripts/exp_003j_dataset.py --fetch"
            )
        rows = [row for row in read_minutes(path) if start_ms <= int(row[0]) < end_ms]
        bars, meta = aggregate(rows, interval_ms=interval_ms)
        if not bars:
            raise RuntimeError(f"{symbol}: no complete {interval_ms} bar in the requested window")
        series[display_symbol(symbol)] = bars
        report[symbol] = {
            **meta,
            "file": path.name,
            "file_sha256": _sha256_file(path),
            "window_start_utc": _utc(start_ms),
            "window_end_utc": _utc(end_ms),
        }
    return series, report


def _normalized(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Ledger rows without the wall-clock stamp, for byte-stable comparison."""

    out = []
    for row in entries:
        entry = dict(row.get("entry", {}))
        entry.pop("recorded_at_utc", None)
        out.append(entry)
    return out


def run_arm(
    *,
    arm: str,
    partition: str,
    symbols: list[str],
    start_ms: int,
    end_ms: int,
    timeframe: str,
    window_bars: int,
    decision_every: int,
    equity: float,
    out_dir: Path,
    max_bars: int | None = None,
) -> dict[str, Any]:
    source = ARMS[arm]
    interval_ms = timeframe_ms(timeframe)
    series, dataset_report = load_series(
        symbols=symbols, start_ms=start_ms, end_ms=end_ms, interval_ms=interval_ms
    )
    if max_bars is not None:
        series = {symbol: bars[:max_bars] for symbol, bars in series.items()}
        dataset_report = {**dataset_report, "truncated_to_bars": max_bars}
    settings = load_settings(config_dir=REPO / "config", env_file=None)
    vision = load_vision_config(env={})
    vision = replace(
        vision,
        lane=replace(
            vision.lane,
            timeframe=timeframe,
            window_bars=window_bars,
            decision_every_bars=decision_every,
            # A frozen bar's close is the instant its data was public; the delivery delay of
            # a live session has no counterpart here and is declared as zero rather than
            # borrowed from another run.
            data_delay_ms=0,
        ),
    )
    run_dir = out_dir / arm / partition
    run_dir.mkdir(parents=True, exist_ok=True)
    ledger_path = run_dir / "ledger.jsonl"
    if ledger_path.exists():
        ledger_path.unlink()
    trace_path = run_dir / "SIGNAL_TRACE.jsonl"
    if trace_path.exists():
        trace_path.unlink()
    provider = build_signal_provider(
        source,
        series=series,
        timeframe=timeframe,
        interval_ms=interval_ms,
        window_bars=window_bars,
        latency_ms=0,
        trace_path=trace_path,
        mode="PAPER",
        strategy_id=STRATEGY_EMA_CROSSOVER,
    )
    lane = VisionLane(
        series={symbol: list(bars) for symbol, bars in series.items()},
        provider=provider,
        config=vision,
        risk_policy=settings.risk,
        ledger_path=ledger_path,
        equity=equity,
        book_id=f"paper-003j-{arm}",
        decision_every_bars=decision_every,
        # A run-scoped ceiling, not a policy: the provider is local and costs nothing, and
        # the default (300) would stop a 60-day replay well before its end.
        max_calls=max(1_000, sum(len(bars) for bars in series.values())),
        quote_feed=None,
        subbar_entries=False,
        decision_from_ms=None,
    )
    summary = lane.run()
    entries = read_entries(ledger_path)
    meta = {
        "schema_version": "AI_BOTS_003J_REPLAY_RUN_V1",
        "experiment": "EXP-003J-REAL-SIGNAL-PAPER-001",
        "arm": arm,
        "signal_source": source,
        "strategy_id": STRATEGY_EMA_CROSSOVER if arm == "real" else None,
        "partition": partition,
        "window_start_utc": _utc(start_ms),
        "window_end_utc": _utc(end_ms),
        "timeframe": timeframe,
        "interval_ms": interval_ms,
        "window_bars": window_bars,
        "decision_every_bars": decision_every,
        "decision_cadence_hours": round(interval_ms * decision_every / 3_600_000.0, 4),
        "equity_usdt": equity,
        "data_delay_ms": 0,
        "subbar_entries": False,
        "fill_policy": "next_observable_bar_open",
        "live_orders": 0,
        "live_enabled": False,
        "commit": _git("rev-parse", "HEAD"),
        "branch": _git("rev-parse", "--abbrev-ref", "HEAD"),
        "generated_at_utc": _utc(int(datetime.now(tz=UTC).timestamp() * 1000)),
        "dataset": dataset_report,
        "risk_policy_sha256": _sha256_file(REPO / "config" / "risk.yaml"),
        "vision_config_sha256": _sha256_file(REPO / "config" / "vision.yaml"),
        "summary": summary,
        "ledger": {
            "path": _display_path(ledger_path),
            "sha256": _sha256_file(ledger_path),
            "rows": len(entries),
        },
        "signal_trace": {
            "path": _display_path(trace_path) if trace_path.exists() else None,
            "sha256": _sha256_file(trace_path) if trace_path.exists() else None,
            "rows": _count_lines(trace_path),
        },
        "provider_counters": {
            key: value
            for key, value in {
                "calls": getattr(provider, "calls", None),
                "no_trade": getattr(provider, "no_trade", None),
                "blocked": getattr(provider, "blocked", None),
                "rotation_seen": getattr(provider, "seen", None),
            }.items()
            if value is not None
        },
    }
    (run_dir / "SUMMARY.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n"
    )
    (run_dir / "RUN_META.json").write_text(
        json.dumps(meta, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n"
    )
    return {"meta": meta, "dir": run_dir, "ledger_sha256": meta["ledger"]["sha256"]}


def _display_path(path: Path) -> str:
    """Repo-relative when it lives here, absolute otherwise (a scratch run still reads)."""

    try:
        return path.resolve().relative_to(REPO).as_posix()
    except ValueError:
        return path.resolve().as_posix()


def _count_lines(path: Path) -> int:
    if not path.exists():
        return 0
    return sum(1 for line in path.read_text(encoding="utf-8").splitlines() if line.strip())


def _git(*args: str) -> str:
    try:
        return subprocess.run(
            ["git", *args], cwd=REPO, capture_output=True, text=True, check=True
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):  # pragma: no cover - no git
        return "UNKNOWN"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--arm", required=True, choices=("control", "real", "both"))
    parser.add_argument("--partition", default="research", choices=("research", "oos"))
    parser.add_argument("--symbols", nargs="*", default=["BTCUSDT", "ETHUSDT", "SOLUSDT"])
    parser.add_argument("--start", default=None)
    parser.add_argument("--end", default=None)
    parser.add_argument("--timeframe", default="5m")
    parser.add_argument("--window-bars", type=int, default=60)
    parser.add_argument("--decision-every", type=int, default=24)
    parser.add_argument("--equity", type=float, default=10_000.0)
    parser.add_argument("--max-bars", type=int, default=None)
    parser.add_argument("--repeat", type=int, default=1, help="run twice and compare ledgers")
    parser.add_argument("--out", default=str(EXPERIMENT_OUT / "runs"))
    args = parser.parse_args(argv)

    boundaries = json.loads((EXPERIMENT_OUT / "PARTITIONS.json").read_text(encoding="utf-8"))
    window = boundaries[args.partition]
    start = _parse_utc(args.start or window["start_utc"])
    end = _parse_utc(args.end or window["end_utc"])
    arms = ("control", "real") if args.arm == "both" else (args.arm,)
    out = Path(args.out)

    results: list[dict[str, Any]] = []
    for arm in arms:
        first = run_arm(
            arm=arm,
            partition=args.partition,
            symbols=list(args.symbols),
            start_ms=start,
            end_ms=end,
            timeframe=args.timeframe,
            window_bars=args.window_bars,
            decision_every=args.decision_every,
            equity=args.equity,
            out_dir=out,
            max_bars=args.max_bars,
        )
        results.append(first)
        if args.repeat > 1:
            second = run_arm(
                arm=arm,
                partition=args.partition,
                symbols=list(args.symbols),
                start_ms=start,
                end_ms=end,
                timeframe=args.timeframe,
                window_bars=args.window_bars,
                decision_every=args.decision_every,
                equity=args.equity,
                out_dir=out / "repeat",
                max_bars=args.max_bars,
            )
            left = _normalized(read_entries(first["dir"] / "ledger.jsonl"))
            right = _normalized(read_entries(second["dir"] / "ledger.jsonl"))
            verdict = {
                "arm": arm,
                "partition": args.partition,
                "rows": len(left),
                "identical": left == right,
                "first_sha256": first["ledger_sha256"],
                "second_sha256": second["ledger_sha256"],
            }
            (out / arm / args.partition / "DETERMINISM.json").write_text(
                json.dumps(verdict, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
                newline="\n",
            )
            if not verdict["identical"]:
                print(f"[003j-replay] FAIL — {arm} is not reproducible", file=sys.stderr)
                return 1
        summary = first["meta"]["summary"]
        print(
            "[003j-replay] {arm}/{partition}: decisions={calls} fills={fills} "
            "closes={closes} net={net} dd={dd} rows={rows}".format(
                arm=arm,
                partition=args.partition,
                calls=summary.get("calls"),
                fills=summary.get("fills"),
                closes=summary.get("closed_trades"),
                net=summary.get("net_realised_usdt"),
                dd=summary.get("drawdown_pct"),
                rows=first["meta"]["ledger"]["rows"],
            ),
            flush=True,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
