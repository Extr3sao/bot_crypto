"""CODEX / FASE C — the controls that must fail, run against the real runtime.

A paper session that only ever runs on a good day proves nothing about the days that
matter. This driver exercises three conditions the runtime claims to handle, each with the
outcome declared *before* the run so the artifact cannot be read as agreement after the
fact:

``stale``
    the feed has stopped delivering minutes. Expected: ``BLOCKED`` rows with
    ``DATA_NOT_TRADEABLE``, zero executed cycles, exit 2.
``feed-down``
    the venue is unreachable. Expected: ``BLOCKED`` with ``FEED_DOWN``, zero cycles,
    exit 2.
``identity``
    a resume whose declaration no longer matches the pinned one. Expected: refusal,
    exit 4, and no new cycle.

The session is the production class; only the declared configuration or the data source
changes. Nothing here writes an order, and every run is ``PAPER`` by construction.

Usage::

    python scripts/tap_unblock_paper.py --control stale --out reports/.../control/stale \
        --root <checkout> --symbols BTCUSDT ETHUSDT SOLUSDT
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import traceback
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
if str(REPO / "src") not in sys.path:
    sys.path.insert(0, str(REPO / "src"))

from trading_bot.config.settings import load_settings  # noqa: E402
from trading_bot.market_data.minute_collector import (  # noqa: E402
    BinanceRestSource,
    MinuteCollector,
)
from trading_bot.vision.prospective import (  # noqa: E402
    PAPER,
    ProspectiveConfig,
    ProspectiveSession,
    RuntimeNotProvable,
    SessionAborted,
    SessionIdentityMismatch,
)
from trading_bot.vision.settings import load_vision_config  # noqa: E402

#: Declared before the run, never after. The verifier reads this file and checks the
#: stream against it, so a driver that softened its expectation would be visible.
EXPECTATIONS: dict[str, dict[str, Any]] = {
    "stale": {
        "exit_code": 2,
        "executed_cycles": 0,
        "blocked_reason": "DATA_NOT_TRADEABLE",
        "why": "a feed that stopped delivering must stop the session, not freeze its clock",
    },
    "feed-down": {
        "exit_code": 2,
        "executed_cycles": 0,
        "blocked_reason": "FEED_DOWN",
        "why": "an unreachable venue cannot produce a decision; inventing one is the defect",
    },
    "identity": {
        "exit_code": 4,
        "executed_cycles": 0,
        "blocked_reason": "RESUME_IDENTITY_MISMATCH",
        "why": "a resume under a changed declaration is a different run wearing the name",
    },
}


def utc_now() -> str:
    return datetime.now(tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def write(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def build_config(args: argparse.Namespace, *, window_bars: int | None = None) -> ProspectiveConfig:
    return ProspectiveConfig(
        symbols=tuple(args.symbols),
        timeframe=args.timeframe,
        window_bars=window_bars or args.window_bars,
        decision_every_bars=1,
        duration_s=args.duration_s,
        poll_interval_s=args.poll_s,
        settle_ms=args.settle_ms,
        latency_ms=args.latency_ms,
        warmup_minutes=args.warmup_minutes,
        mode=PAPER,
        max_cycles=args.max_cycles,
        #: the only knob this control touches: how old a minute may be before it is
        #: declared unusable. One millisecond is not a simulation of a stale feed; it is
        #: the real freshness gate answering a feed that is always too old.
        stale_after_ms=1 if args.control == "stale" else 150_000,
    )


def collector_for(args: argparse.Namespace, out: Path) -> MinuteCollector | None:
    if args.control != "feed-down":
        return None
    return MinuteCollector(
        source=BinanceRestSource(base_url="http://127.0.0.1:9", timeout_s=2.0),
        root=out / "market-1m",
        symbols=tuple(args.symbols),
        local_clock=lambda: int(time.time() * 1000),
        settle_ms=0,
    ).open()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run a declared negative control")
    parser.add_argument("--control", required=True, choices=sorted(EXPECTATIONS))
    parser.add_argument("--out", required=True)
    parser.add_argument("--root", default=str(REPO))
    parser.add_argument("--symbols", nargs="*", default=["BTCUSDT"])
    parser.add_argument("--timeframe", default="1m")
    parser.add_argument("--window-bars", type=int, default=20)
    parser.add_argument("--warmup-minutes", type=int, default=120)
    parser.add_argument("--duration-s", type=int, default=120)
    parser.add_argument("--poll-s", type=float, default=5.0)
    parser.add_argument("--settle-ms", type=int, default=2_500)
    parser.add_argument("--latency-ms", type=int, default=30_000)
    parser.add_argument("--max-cycles", type=int, default=2)
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args(argv)

    root = Path(args.root).resolve()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    expectation = EXPECTATIONS[args.control]

    vision = load_vision_config(env={})
    vision = replace(vision, lane=replace(vision.lane, timeframe=args.timeframe))
    settings = load_settings(config_dir=REPO / "config", env_file=None)

    #: ``identity`` deliberately resumes a declaration that differs from the pinned one.
    window = args.window_bars + (2 if args.control == "identity" else 0)
    config = build_config(args, window_bars=window)
    session = ProspectiveSession(
        config=config,
        out_dir=out,
        vision_config=vision,
        risk_policy=settings.risk,
        root=root,
        collector=collector_for(args, out),
        resume=args.resume or args.control == "identity",
        progress=lambda message: print(f"[{args.control}] {message}", flush=True),
    )

    record: dict[str, Any] = {
        "schema_version": "TAP_OPERATIONAL_CONTROL_V1",
        "generated_at_utc": utc_now(),
        "control": args.control,
        "root": str(root),
        "out": str(out),
        "mode": PAPER,
        "live_enabled": False,
        "live_orders": 0,
        "declared_expectation": expectation,
        "config": config.identity_payload(),
    }

    exit_code = 0
    try:
        summary = session.run()
        record["summary"] = summary
        record["executed_cycles"] = int(summary.get("cycles_executed", 0))
        record["blocked_reasons"] = sorted(summary.get("blocked_reasons") or [])
    except RuntimeNotProvable as exc:
        exit_code = 3
        record["refusal"] = {"kind": "RUNTIME_NOT_PROVABLE", "reasons": exc.reasons}
    except SessionIdentityMismatch as exc:
        exit_code = 4
        record["refusal"] = {
            "kind": "RESUME_IDENTITY_MISMATCH",
            "reasons": exc.reasons,
            "detail": exc.detail,
        }
        record["executed_cycles"] = 0
        record["blocked_reasons"] = ["RESUME_IDENTITY_MISMATCH"]
    except SessionAborted as exc:
        exit_code = 5
        record["aborted"] = str(exc)
    except Exception as exc:
        exit_code = 1
        record["crash"] = {
            "type": type(exc).__name__,
            "message": str(exc),
            "traceback": traceback.format_exc()[-4000:],
        }
    else:
        if int(summary.get("cycles_executed", 0)) == 0:
            exit_code = 2
    record["exit_code"] = exit_code

    #: The verdict is the comparison the file itself declares, computed here so a reader
    #: does not have to reconstruct it — and so a control that did not fail is visible.
    observed = {
        "exit_code": exit_code,
        "executed_cycles": record.get("executed_cycles"),
        "blocked_reason": next(
            (
                reason
                for reason in [
                    *(record.get("blocked_reasons") or []),
                    *(record.get("refusal", {}).get("reasons") or []),
                ]
                if expectation["blocked_reason"] in str(reason)
            ),
            None,
        ),
    }
    record["observed"] = observed
    record["matched"] = (
        observed["exit_code"] == expectation["exit_code"]
        and observed["executed_cycles"] == expectation["executed_cycles"]
        and observed["blocked_reason"] == expectation["blocked_reason"]
    )
    write(out / "CONTROL.json", record)
    print(
        json.dumps(
            {
                "control": args.control,
                "exit_code": exit_code,
                "matched": record["matched"],
                "observed": observed,
            },
            indent=2,
        )
    )
    return 0 if record["matched"] else 6


if __name__ == "__main__":
    raise SystemExit(main())
