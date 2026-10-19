"""ai_bots_003g_paper — prospective PAPER over a real 1-minute feed.

    ./.venv/Scripts/python.exe scripts/ai_bots_003g_paper.py --duration-s 1800
    ./.venv/Scripts/python.exe scripts/ai_bots_003g_paper.py --max-cycles 3 --timeframe 5m

What it does, in order: bootstraps real 1-minute klines from the public Binance REST
endpoint, measures the delivery delay on minutes that close *after* the session starts,
then, at each closed decision bar, runs the production ``VisionLane`` over the closed
prefix with ``subbar_entries=True`` and writes a chained stream row plus a per-cycle
ledger.

What it refuses to do: run outside PAPER, read a credential, submit an order, or invent a
decision when the feed is stale, gapped or short of a full window. In those cases the
stream records ``BLOCKED`` and the exit code is 2.
"""

from __future__ import annotations

import argparse
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
from trading_bot.vision.prospective import (  # noqa: E402
    PAPER,
    LiveModeRefused,
    ProspectiveConfig,
    ProspectiveSession,
    SessionAborted,
)
from trading_bot.vision.settings import load_vision_config  # noqa: E402

DEFAULT_OUT = REPO / "reports" / "ai-bots" / "RFC-AI-BOTS-003G" / "session"


def git_commit() -> str:
    try:
        return subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=REPO,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):  # pragma: no cover - no git
        return "UNKNOWN"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Prospective PAPER session (1m live feed)")
    parser.add_argument("--mode", default=PAPER, choices=(PAPER, "LIVE"))
    parser.add_argument("--symbols", nargs="*", default=["BTCUSDT", "ETHUSDT"])
    parser.add_argument("--timeframe", default="5m")
    parser.add_argument("--window-bars", type=int, default=20)
    parser.add_argument("--decision-every-bars", type=int, default=1)
    parser.add_argument("--duration-s", type=int, default=2_700)
    parser.add_argument("--max-cycles", type=int, default=None)
    parser.add_argument("--poll-s", type=float, default=15.0)
    parser.add_argument("--settle-ms", type=int, default=2_500)
    parser.add_argument("--latency-ms", type=int, default=30_000)
    parser.add_argument("--warmup-minutes", type=int, default=240)
    parser.add_argument("--out", default=str(DEFAULT_OUT))
    args = parser.parse_args(argv)

    if args.mode != PAPER:
        print("[003g] REFUSED — this path is PAPER only; no LIVE order code exists here")
        return 2

    settings = load_settings(config_dir=REPO / "config", env_file=None)
    vision = load_vision_config(env={})
    # The lane's own timeframe is replaced by the session's; nothing else in the vision
    # configuration changes, and config/risk.yaml is read, never written.
    vision = replace(vision, lane=replace(vision.lane, timeframe=args.timeframe))

    stamp = datetime.now(tz=UTC).strftime("%Y%m%dT%H%M%SZ")
    out = Path(args.out)
    if out == DEFAULT_OUT:
        out = out / stamp
    out.mkdir(parents=True, exist_ok=True)

    config = ProspectiveConfig(
        symbols=tuple(args.symbols),
        timeframe=args.timeframe,
        window_bars=args.window_bars,
        decision_every_bars=args.decision_every_bars,
        duration_s=args.duration_s,
        poll_interval_s=args.poll_s,
        settle_ms=args.settle_ms,
        latency_ms=args.latency_ms,
        warmup_minutes=args.warmup_minutes,
        mode=PAPER,
        max_cycles=args.max_cycles,
    )
    session = ProspectiveSession(
        config=config,
        out_dir=out,
        vision_config=vision,
        risk_policy=settings.risk,
        root=REPO,
        progress=lambda message: print(f"[003g] {message}", flush=True),
    )
    meta: dict[str, Any] = {
        "commit": git_commit(),
        "started_at_utc": datetime.now(tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "mode": PAPER,
        "live_enabled": False,
        "risk_yaml_sha256": _sha256(REPO / "config" / "risk.yaml"),
        "vision_yaml_sha256": _sha256(REPO / "config" / "vision.yaml"),
        "out_dir": str(out),
    }
    (out / "RUN_META.json").write_text(
        json.dumps(meta, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n"
    )
    print(f"[003g] session dir {out}", flush=True)
    try:
        summary = session.run()
    except LiveModeRefused as exc:
        print(f"[003g] REFUSED — {exc}")
        return 2
    except SessionAborted as exc:
        print(f"[003g] ABORTED — {exc}")
        return 2
    print(json.dumps({k: summary[k] for k in (
        "cycles_executed", "cycles_blocked", "fills", "closed_trades",
        "net_realised_usdt", "data_delay_ms",
    )}, indent=2))
    if summary["cycles_executed"] == 0:
        print("[003g] BLOCKED — no cycle could be executed on real data")
        return 2
    return 0


def _sha256(path: Path) -> str:
    import hashlib

    if not path.exists():
        return "MISSING"
    return hashlib.sha256(path.read_bytes()).hexdigest()


if __name__ == "__main__":
    raise SystemExit(main())
