"""paper_supervisor — recover a crashed PAPER session without an operator.

Thin CLI over ``trading_bot.ops.paper_supervisor``: the policy and the evidence checks
live in one place and are unit-tested there, so the command an operator runs cannot drift
into a second opinion about what counts as a recovery.

Two invocations matter:

* ``--start`` launches the session and keeps it alive across crashes;
* without it the supervisor only attaches to an existing directory and resumes what is
  already in ``RECOVERING``.

Its journal and result live in ``<session>.supervisor`` by default. That directory is a
*sibling* on purpose: ``session_status`` reads every ``*.lock`` under the session tree, and
a supervisor lock inside it would be reported as a live writer.

Exit codes::

``0``  the session completed, or the operator asked to stop
``2``  there was nothing to supervise
``3``  the supervisor refused to continue (failed, ambiguous, blocked or out of budget)
``4``  another supervisor already owns this session

Usage::

    python scripts/paper_supervisor.py --session reports/.../session --start \
        --symbols BTCUSDT ETHUSDT SOLUSDT --timeframe 1m --duration-s 180 \
        --max-restarts 8
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import replace
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
if str(REPO / "src") not in sys.path:
    sys.path.insert(0, str(REPO / "src"))

from trading_bot.ops.paper_supervisor import (  # noqa: E402
    Policy,
    Supervisor,
    describe,
)


def _config_from_args(args: argparse.Namespace) -> dict:
    if args.config:
        raw = Path(args.config).read_text(encoding="utf-8")
        payload = json.loads(raw)
        if not isinstance(payload, dict):
            raise SystemExit(f"--config must be a JSON object, got {type(payload).__name__}")
        return payload
    return {
        "symbols": list(args.symbols),
        "timeframe": args.timeframe,
        "window_bars": args.window_bars,
        "decision_every_bars": args.decision_every_bars,
        "duration_s": args.duration_s,
        "poll_interval_s": args.session_poll_s,
        "settle_ms": args.settle_ms,
        "latency_ms": args.latency_ms,
        "warmup_minutes": args.warmup_minutes,
        "equity": args.equity,
        "mode": "PAPER",
        "max_cycles": args.max_cycles,
        "stale_after_ms": args.stale_after_ms,
        "max_skew_ms": args.max_skew_ms,
        "signal_source": args.signal_source,
        "strategy_id": args.strategy_id,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Supervise and recover a PAPER session")
    parser.add_argument("--session", required=True, help="session output directory")
    parser.add_argument(
        "--state-dir",
        default=None,
        help="where the journal lives (default: <session>.supervisor)",
    )
    parser.add_argument("--root", default=str(REPO), help="checkout the entrypoint runs from")
    parser.add_argument("--entrypoint", default=None)
    parser.add_argument("--start", action="store_true", help="create the session when absent")
    parser.add_argument("--once", action="store_true", help="act at most once, then stop")
    parser.add_argument("--max-restarts", type=int, default=3)
    parser.add_argument("--backoff-base-s", type=float, default=2.0)
    parser.add_argument("--backoff-cap-s", type=float, default=30.0)
    parser.add_argument("--poll-s", type=float, default=1.0, help="supervisor poll interval")
    parser.add_argument("--observe-timeout-s", type=float, default=None)
    parser.add_argument("--child-timeout-s", type=float, default=3_600.0)
    parser.add_argument("--config", default=None, help="JSON object/file for the first start")
    parser.add_argument("--symbols", nargs="*", default=["BTCUSDT"])
    parser.add_argument("--timeframe", default="1m")
    parser.add_argument("--window-bars", type=int, default=20)
    parser.add_argument("--decision-every-bars", type=int, default=1)
    parser.add_argument("--warmup-minutes", type=int, default=120)
    parser.add_argument("--duration-s", type=int, default=300)
    parser.add_argument("--session-poll-s", type=float, default=5.0)
    parser.add_argument("--settle-ms", type=int, default=2_500)
    parser.add_argument("--latency-ms", type=int, default=30_000)
    parser.add_argument("--equity", type=float, default=10_000.0)
    parser.add_argument("--max-cycles", type=int, default=None)
    parser.add_argument("--stale-after-ms", type=int, default=150_000)
    parser.add_argument("--max-skew-ms", type=int, default=5_000)
    parser.add_argument("--signal-source", default="legacy_parity")
    parser.add_argument("--strategy-id", default="ema_crossover")
    args = parser.parse_args(argv)

    session = Path(args.session)
    state_dir = (
        Path(args.state_dir) if args.state_dir else session.with_name(session.name + ".supervisor")
    )
    policy = Policy(
        max_restarts=args.max_restarts,
        backoff_base_s=args.backoff_base_s,
        backoff_cap_s=args.backoff_cap_s,
        poll_s=args.poll_s,
        child_timeout_s=args.child_timeout_s,
        observe_timeout_s=args.observe_timeout_s,
    )
    supervisor = Supervisor(
        session=session,
        state_dir=state_dir,
        entrypoint=args.entrypoint,
        policy=policy,
        config=_config_from_args(args),
        allow_start=args.start,
        root=args.root,
    )
    if args.once:
        #: ``--once`` is not a dry run: it still performs the one action the policy chose.
        #: It exists so a caller can ask "would you touch this?" and stop there.
        supervisor.policy = replace(policy, max_restarts=min(policy.max_restarts, 1))
    result = supervisor.run()
    print(json.dumps(result, indent=2, sort_keys=True))
    print(f"[supervisor] {describe(result)}", file=sys.stderr)
    return int(result.get("exit_code") or 0)


if __name__ == "__main__":
    raise SystemExit(main())
