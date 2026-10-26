"""DEF-RUN-019 / WP-04B-C — a real prospective PAPER session that pins its runtime first.

The session itself enforces the policy; this script only drives it and reports the exit
status honestly. There is no order path, no credential and no live mode here: the mode is
``PAPER`` and the session refuses anything else before it builds a single object.

Exit codes:

``0``  at least one cycle executed and the session ended normally
``2``  the session ran but executed no cycle (feed blocked, stale, or short of a window)
``3``  refused: the runtime could not be identified (dirty, missing, or no Git)
``4``  refused: a resume whose pinned identity no longer matches
``5``  aborted: the feed could not support an honest decision

Usage::

    python scripts/def_run_019_prospective_run.py --out reports/.../live \
        --symbols BTCUSDT --timeframe 1m --window-bars 20 --warmup-minutes 120 \
        --duration-s 300 --max-cycles 2
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
    ProspectiveConfig,
    ProspectiveSession,
    RuntimeNotProvable,
    SessionAborted,
    SessionIdentityMismatch,
)
from trading_bot.vision.settings import load_vision_config  # noqa: E402


def utc_now() -> str:
    return datetime.now(tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def git(root: Path, *args: str) -> str:
    try:
        completed = subprocess.run(
            ["git", "-C", str(root), *args], capture_output=True, text=True, check=True
        )
    except (OSError, subprocess.CalledProcessError):
        return ""
    return completed.stdout.strip()


def write(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Prospective PAPER session with a pinned runtime")
    parser.add_argument("--out", required=True)
    parser.add_argument("--root", default=str(REPO))
    parser.add_argument("--symbols", nargs="*", default=["BTCUSDT"])
    parser.add_argument("--timeframe", default="1m")
    parser.add_argument("--window-bars", type=int, default=20)
    parser.add_argument("--decision-every-bars", type=int, default=1)
    parser.add_argument("--warmup-minutes", type=int, default=120)
    parser.add_argument("--duration-s", type=int, default=300)
    parser.add_argument("--poll-s", type=float, default=10.0)
    parser.add_argument("--settle-ms", type=int, default=2_500)
    parser.add_argument("--latency-ms", type=int, default=30_000)
    parser.add_argument("--max-cycles", type=int, default=2)
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args(argv)

    root = Path(args.root).resolve()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    vision = load_vision_config(env={})
    vision = replace(vision, lane=replace(vision.lane, timeframe=args.timeframe))
    settings = load_settings(config_dir=REPO / "config", env_file=None)

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
        root=root,
        resume=args.resume,
        progress=lambda message: print(f"[wp04] {message}", flush=True),
    )

    meta: dict[str, Any] = {
        "schema_version": "DEF_RUN_019_LIVE_META_V1",
        "started_at_utc": utc_now(),
        "root": str(root),
        "commit": git(root, "rev-parse", "HEAD"),
        "branch": git(root, "rev-parse", "--abbrev-ref", "HEAD"),
        "dirty_paths": [line for line in git(root, "status", "--porcelain").splitlines() if line],
        "mode": PAPER,
        "live_enabled": False,
        "live_orders": 0,
        "resume": bool(args.resume),
        "config": config.identity_payload(),
        "out_dir": str(out),
    }
    write(out / "RUN_META.json", meta)
    print(f"[wp04] root={root} commit={meta['commit'][:12]} out={out}", flush=True)

    status = 0
    try:
        summary = session.run()
    except RuntimeNotProvable as exc:
        write(
            out / "REFUSED.json",
            {"reason": "RUNTIME_NOT_PROVABLE", "code": 3, "reasons": exc.reasons},
        )
        write(out / "REFUSED_PROVENANCE.json", exc.block)
        print(f"[wp04] REFUSED — {exc}", flush=True)
        return 3
    except SessionIdentityMismatch as exc:
        write(
            out / "REFUSED.json",
            {"reason": "RESUME_IDENTITY_MISMATCH", "code": 4, "reasons": exc.reasons, "detail": exc.detail},
        )
        print(f"[wp04] REFUSED — {exc}", flush=True)
        return 4
    except SessionAborted as exc:
        write(out / "ABORTED.json", {"reason": "SESSION_ABORTED", "code": 5, "detail": str(exc)})
        print(f"[wp04] ABORTED — {exc}", flush=True)
        return 5

    print(
        json.dumps(
            {
                "cycles_executed": summary["cycles_executed"],
                "cycles_blocked": summary["cycles_blocked"],
                "fills": summary["fills"],
                "closed_trades": summary["closed_trades"],
                "net_realised_usdt": summary["net_realised_usdt"],
                "data_delay_ms": summary["data_delay_ms"],
                "runtime_stable": summary["runtime_stable"],
                "run_id": summary["provenance"]["run_id"],
                "session_id": summary["provenance"]["session_id"],
            },
            indent=2,
        )
    )
    if summary["cycles_executed"] == 0:
        status = 2
        print("[wp04] BLOCKED — no cycle could be executed on the live feed")
    write(out / "RUN_RESULT.json", {"exit_code": status, "summary": summary})
    return status


if __name__ == "__main__":
    raise SystemExit(main())
