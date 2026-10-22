"""DEF-RUN-019 / WP-04E — does pinning the runtime change a single decision?

The cheapest way to make this check meaningless would be to compare a run against itself.
So the baseline is a *different tree*: the commit before this work package, checked out in
its own worktree, executing the same recorded minutes with the same configuration and the
same simulated clock. The only thing that differs is that the current tree writes the
provenance block and the baseline does not.

Because two ``trading_bot`` packages cannot live in one process, the parent spawns a child
per tree with ``PYTHONPATH`` pointed at that tree's ``src``. The child never invents data:
it replays a minute store captured from a real Binance feed, and the clock is simulated so
the comparison is reproducible.

Usage::

    python scripts/def_run_019_integrity.py --minutes LIVE/market-1m/BTCUSDT.jsonl \
        --baseline-src ../baseline/src --current-src src --out AB.json
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

MINUTE_MS = 60_000
SYMBOLS = ("BTCUSDT",)


def utc_now() -> str:
    return datetime.now(tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def canonical(payload: Any) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def load_minutes(path: Path) -> list[dict[str, Any]]:
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    rows.sort(key=lambda row: int(row["open_ms"]))
    return rows


# --------------------------------------------------------------------------- child


class FakeClock:
    def __init__(self, now_ms: int) -> None:
        self.now = int(now_ms)

    def __call__(self) -> int:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.now += int(float(seconds) * 1000)


class RecordedVenue:
    """A venue that only ever serves minutes that were really recorded."""

    name = "recorded_minutes"

    def __init__(self, rows: list[dict[str, Any]], clock: FakeClock, symbol: str) -> None:
        self.rows = rows
        self.clock = clock
        self.symbol = symbol
        self.first_open_ms = int(rows[0]["open_ms"])
        self.last_open_ms = int(rows[-1]["open_ms"])

    def last_closed_open(self, now_ms: int | None = None) -> int:
        now = int(self.clock() if now_ms is None else now_ms)
        return min((now // MINUTE_MS) * MINUTE_MS - MINUTE_MS, self.last_open_ms)

    def server_time(self) -> int:
        return int(self.clock())

    def fetch(
        self,
        symbol: str,
        *,
        start_ms: int | None = None,
        end_ms: int | None = None,
        limit: int = 500,
    ):
        from trading_bot.market_data.minute_collector import KlinePage

        last = self.last_closed_open()
        stamps = [
            int(row["open_ms"])
            for row in self.rows
            if int(row["open_ms"]) <= last
            and (start_ms is None or int(row["open_ms"]) >= int(start_ms))
            and (end_ms is None or int(row["open_ms"]) <= int(end_ms))
        ]
        stamps = stamps[: max(1, limit)] if start_ms is not None else stamps[-max(1, limit) :]
        index = {int(row["open_ms"]): row for row in self.rows}
        rows = tuple(
            (
                stamp,
                float(index[stamp]["open"]),
                float(index[stamp]["high"]),
                float(index[stamp]["low"]),
                float(index[stamp]["close"]),
                float(index[stamp]["volume"]),
            )
            for stamp in stamps
        )
        return KlinePage(
            symbol=symbol,
            rows=rows,
            server_time_ms=int(self.clock()),
            received_at_ms=int(self.clock()),
        )


def run_child(args: argparse.Namespace) -> int:
    src = Path(args.src).resolve()
    sys.path.insert(0, str(src))
    from trading_bot.config.settings import load_settings
    from trading_bot.market_data.minute_collector import MinuteCollector
    from trading_bot.vision.prospective import PAPER, ProspectiveConfig, ProspectiveSession
    from trading_bot.vision.settings import load_vision_config

    rows = load_minutes(Path(args.minutes))
    start = int(rows[0]["open_ms"]) + int(
        args.warmup_minutes + args.start_offset_minutes
    ) * MINUTE_MS
    clock = FakeClock(start)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    venue = RecordedVenue(rows, clock, SYMBOLS[0])
    collector = MinuteCollector(
        source=venue,
        root=out / "market-1m",
        symbols=SYMBOLS,
        local_clock=clock,
        settle_ms=0,
    ).open()
    vision = load_vision_config(env={})
    vision = replace(
        vision,
        lane=replace(
            vision.lane,
            timeframe=args.timeframe,
            window_bars=args.window_bars,
            decision_every_bars=args.decision_every_bars,
        ),
    )
    settings = load_settings(config_dir=Path(args.config_dir), env_file=None)
    session = ProspectiveSession(
        config=ProspectiveConfig(
            symbols=SYMBOLS,
            timeframe=args.timeframe,
            window_bars=args.window_bars,
            decision_every_bars=args.decision_every_bars,
            duration_s=args.duration_s,
            #: One simulated second per poll: the clock only moves when the session sleeps,
            #: so a zero interval would spin forever instead of reaching the next bar.
            poll_interval_s=1.0,
            settle_ms=0,
            latency_ms=args.latency_ms,
            warmup_minutes=args.warmup_minutes,
            mode=PAPER,
            max_cycles=args.max_cycles,
        ),
        out_dir=out / "session",
        vision_config=vision,
        risk_policy=settings.risk,
        root=Path(args.root_for_provenance).resolve() if args.root_for_provenance else src.parent,
        collector=collector,
        clock=clock,
        sleeper=clock.sleep,
        progress=lambda message: print(f"[child] {message}", flush=True),
    )
    summary = session.run()

    from trading_bot.vision.ledger import read_entries

    cycles: list[dict[str, Any]] = []
    for path in sorted((out / "session" / "cycles").glob("*/ledger.jsonl")):
        entries = [canonical(row["entry"]) for row in read_entries(path)]
        cycles.append(
            {
                "cycle": int(path.parent.name.split("-")[-1]),
                "rows_sha256": sha256_text("\n".join(entries)),
                "rows": entries,
            }
        )
    payload = {
        "src": str(src),
        "commit": subprocess.run(
            ["git", "-C", str(src.parent), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            check=False,
        ).stdout.strip(),
        "session_dir": str(out / "session"),
        "cycles": cycles,
        "summary": {
            "cycles_executed": summary["cycles_executed"],
            "cycles_blocked": summary["cycles_blocked"],
            "fills": summary["fills"],
            "closed_trades": summary["closed_trades"],
            "net_realised_usdt": summary["net_realised_usdt"],
            "accounting": summary["accounting"],
            "execution": summary["execution"],
            "reconciliation": summary["reconciliation"],
            "open_positions_at_end": summary["open_positions_at_end"],
            "data_delay_ms": summary["data_delay_ms"],
            "provenance_present": "provenance" in summary,
        },
    }
    (out / "CYCLE_LEDGERS.json").write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n"
    )
    print(json.dumps({"cycles": len(cycles), "fills": summary["fills"]}, indent=2))
    return 0


# --------------------------------------------------------------------------- parent


def spawn(src: Path, args: argparse.Namespace, out: Path) -> dict[str, Any]:
    env = dict(os.environ)
    env["PYTHONPATH"] = str(src.resolve())
    command = [
        sys.executable,
        str(Path(__file__).resolve()),
        "--child",
        "--src",
        str(src.resolve()),
        "--minutes",
        str(Path(args.minutes).resolve()),
        "--out",
        str(out.resolve()),
        "--config-dir",
        str(Path(args.config_dir).resolve()),
        "--timeframe",
        args.timeframe,
        "--window-bars",
        str(args.window_bars),
        "--decision-every-bars",
        str(args.decision_every_bars),
        "--warmup-minutes",
        str(args.warmup_minutes),
        "--start-offset-minutes",
        str(args.start_offset_minutes),
        "--duration-s",
        str(args.duration_s),
        "--latency-ms",
        str(args.latency_ms),
        "--max-cycles",
        str(args.max_cycles),
    ]
    if args.root_for_provenance:
        command += ["--root-for-provenance", str(Path(args.root_for_provenance).resolve())]
    completed = subprocess.run(command, capture_output=True, text=True, env=env, check=False)
    payload_path = out.resolve() / "CYCLE_LEDGERS.json"
    payload: dict[str, Any] = {}
    if payload_path.is_file():
        payload = json.loads(payload_path.read_text(encoding="utf-8"))
    return {
        "exit_code": completed.returncode,
        "stdout_tail": completed.stdout.strip().splitlines()[-6:],
        "stderr_tail": completed.stderr.strip().splitlines()[-6:],
        "payload": payload,
    }


def compare(baseline: dict[str, Any], current: dict[str, Any]) -> dict[str, Any]:
    differences: list[str] = []
    left = baseline.get("cycles") or []
    right = current.get("cycles") or []
    if len(left) != len(right):
        differences.append(f"CYCLE_COUNT {len(left)} != {len(right)}")
    for a, b in zip(left, right, strict=False):
        if a["cycle"] != b["cycle"]:
            differences.append(f"CYCLE_INDEX {a['cycle']} != {b['cycle']}")
        if a["rows_sha256"] != b["rows_sha256"]:
            first = next(
                (
                    index
                    for index, (row_a, row_b) in enumerate(
                        zip(a["rows"], b["rows"], strict=False)
                    )
                    if row_a != row_b
                ),
                None,
            )
            differences.append(
                f"CYCLE_{a['cycle']}_LEDGER_DIFFERS rows={len(a['rows'])}/{len(b['rows'])} "
                f"first={first}"
            )
    keys = (
        "fills",
        "closed_trades",
        "net_realised_usdt",
        "data_delay_ms",
        "accounting",
        "execution",
        "reconciliation",
        "open_positions_at_end",
        "cycles_executed",
    )
    left_summary = baseline.get("summary") or {}
    right_summary = current.get("summary") or {}
    for key in keys:
        if left_summary.get(key) != right_summary.get(key):
            differences.append(
                f"SUMMARY_{key} {left_summary.get(key)!r} != {right_summary.get(key)!r}"
            )
    return {"differences": differences, "cycles": len(right)}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="A/B economic integrity across two code roots")
    parser.add_argument("--child", action="store_true")
    parser.add_argument("--src", default=None, help="child: code root to execute")
    parser.add_argument("--minutes", required=True, help="recorded minute store JSONL")
    parser.add_argument("--out", required=True)
    parser.add_argument("--baseline-src", default=None, help="parent: pre-WP src")
    parser.add_argument("--current-src", default=None, help="parent: current src")
    parser.add_argument("--config-dir", default=str(Path(__file__).resolve().parents[1] / "config"))
    parser.add_argument("--root-for-provenance", default=None)
    parser.add_argument("--timeframe", default="5m")
    parser.add_argument("--window-bars", type=int, default=20)
    parser.add_argument("--decision-every-bars", type=int, default=1)
    parser.add_argument("--warmup-minutes", type=int, default=90)
    parser.add_argument("--start-offset-minutes", type=int, default=5)
    parser.add_argument("--duration-s", type=int, default=3_600)
    parser.add_argument("--latency-ms", type=int, default=30_000)
    parser.add_argument("--max-cycles", type=int, default=3)
    args = parser.parse_args(argv)

    if args.child:
        if not args.src:
            parser.error("--child needs --src")
        return run_child(args)

    if not args.baseline_src or not args.current_src:
        parser.error("--baseline-src and --current-src are required")
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    baseline = spawn(Path(args.baseline_src), args, out.parent / "baseline")
    current = spawn(Path(args.current_src), args, out.parent / "current")
    verdict = compare(baseline.get("payload") or {}, current.get("payload") or {})
    payload = {
        "schema_version": "DEF_RUN_019_INTEGRITY_AB_V1",
        "generated_at_utc": utc_now(),
        "builder": "scripts/def_run_019_integrity.py",
        "minutes": str(Path(args.minutes).resolve()),
        "minutes_sha256": hashlib.sha256(Path(args.minutes).read_bytes()).hexdigest(),
        "parameters": {
            "timeframe": args.timeframe,
            "window_bars": args.window_bars,
            "decision_every_bars": args.decision_every_bars,
            "warmup_minutes": args.warmup_minutes,
            "latency_ms": args.latency_ms,
            "max_cycles": args.max_cycles,
            "symbols": list(SYMBOLS),
        },
        "baseline": {
            "src": baseline["payload"].get("src"),
            "commit": baseline["payload"].get("commit"),
            "exit_code": baseline["exit_code"],
            "cycles": len(baseline["payload"].get("cycles") or []),
            "provenance_present": (baseline["payload"].get("summary") or {}).get(
                "provenance_present"
            ),
            "stderr_tail": baseline["stderr_tail"],
        },
        "current": {
            "src": current["payload"].get("src"),
            "commit": current["payload"].get("commit"),
            "exit_code": current["exit_code"],
            "cycles": len(current["payload"].get("cycles") or []),
            "provenance_present": (current["payload"].get("summary") or {}).get(
                "provenance_present"
            ),
            "stderr_tail": current["stderr_tail"],
        },
        **verdict,
        "all_match": bool(current["payload"].get("cycles"))
        and not verdict["differences"]
        and baseline["exit_code"] == 0
        and current["exit_code"] == 0,
    }
    out.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n"
    )
    print(
        json.dumps(
            {
                "all_match": payload["all_match"],
                "cycles": payload["cycles"],
                "differences": payload["differences"],
                "baseline_exit": baseline["exit_code"],
                "current_exit": current["exit_code"],
            },
            indent=2,
        )
    )
    return 0 if payload["all_match"] else 1


if __name__ == "__main__":
    sys.exit(main())
