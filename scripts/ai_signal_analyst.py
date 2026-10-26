"""Read-only AI commentary on the signal stream (WP-SIGNAL-002 sidecar).

    uv run python scripts/ai_signal_analyst.py --once
    uv run python scripts/ai_signal_analyst.py --loop --interval 60

Reads `signals.jsonl` for one PAPER run and appends one analysis row per signal to
`analysis.jsonl`. It is a *sidecar*: a separate process with a separate failure
domain, no broker, no risk engine and no order path. If it stops, PAPER and SHADOW
keep deciding and the dashboard keeps showing the stream; if the model is slow or
wrong, the row says `FAILED` and the page shows the failure instead of a synthesis.

With no provider configured this script still runs and records `NOT_CONFIGURED` —
once per signal, idempotent on the analysis id — and exits 0, because a missing key
is a state to display, not a reason to stop the lab. It never prints, stores or
reports the key.

The budget is read from the analysis ledger (calls in the last hour), so restarting
this process cannot reset the spend.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from trading_bot.autonomous.analysis import (  # noqa: E402
    PROMPT_VERSION,
    AnalysisStore,
    SignalAnalyst,
    pending_signals,
    provider_from_env,
)
from trading_bot.autonomous.observability import allow_tolerant_console_output  # noqa: E402
from trading_bot.autonomous.signals import SignalEvent, SignalLedger  # noqa: E402

DEFAULT_RUN_ROOT = Path("reports/autonomous-paper")
HEARTBEAT_NAME = "AI_ANALYST_HEARTBEAT.json"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-root", default=str(DEFAULT_RUN_ROOT))
    parser.add_argument("--run-id", default=None, help="default: the newest run with signals")
    parser.add_argument(
        "--limit-per-pass",
        type=int,
        default=5,
        help="how many unanalysed signals one pass may examine (bounds latency per pass)",
    )
    parser.add_argument("--once", action="store_true", help="one pass and exit")
    parser.add_argument("--loop", action="store_true", help="keep passing until stopped")
    parser.add_argument("--interval", type=float, default=60.0)
    parser.add_argument("--stop-file", default=None)
    parser.add_argument("--budget-per-hour", type=int, default=60)
    parser.add_argument("--max-per-run", type=int, default=500)
    parser.add_argument("--timeout", type=float, default=45.0)
    parser.add_argument("--json", action="store_true", help="print the pass payload")
    return parser.parse_args(argv)


def resolve_run_dir(root: Path, run_id: str | None) -> Path | None:
    """The run to read: named, or the newest one that actually has a stream."""
    if run_id:
        candidate = root / run_id
        return candidate if (candidate / "signals.jsonl").exists() else None
    if not root.exists():
        return None
    runs = [
        path
        for path in root.iterdir()
        if path.is_dir() and (path / "signals.jsonl").exists()
    ]
    if not runs:
        return None
    return max(runs, key=lambda path: (path / "signals.jsonl").stat().st_mtime)


def trace_evidence(run_dir: Path, decision_ids: set[str]) -> dict[str, list[str]]:
    """Evidence strings the engine itself recorded, per decision.

    Read from the trace file rather than re-deriving anything: the model is shown
    what the decision was justified with, not a fresh interpretation of the market.
    """
    path = run_dir / "traces.jsonl"
    if not decision_ids or not path.exists():
        return {}
    out: dict[str, list[str]] = {}
    with open(path, encoding="utf-8", errors="replace") as handle:
        for line in handle:
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except ValueError:
                continue
            decision_id = str(row.get("decision_id") or "")
            if decision_id not in decision_ids:
                continue
            evidence = [str(item) for item in (row.get("evidence") or [])]
            counter = [str(item) for item in (row.get("counter_evidence") or [])]
            out[decision_id] = evidence + counter
    return out


def run_pass(args: argparse.Namespace, run_dir: Path, provider: Any) -> dict[str, Any]:
    """One bounded pass: at most `--limit-per-pass` model calls."""
    ledger = SignalLedger(run_dir)
    store = AnalysisStore(run_dir)
    events: list[SignalEvent] = []
    for row in ledger.iter_rows():
        try:
            events.append(SignalEvent.from_dict(row))
        except (ValueError, TypeError, KeyError):
            continue
    waiting = pending_signals(events, store)
    pending = waiting[: max(0, args.limit_per_pass)]
    analyst = SignalAnalyst(
        store=store,
        provider=provider,
        prompt_version=PROMPT_VERSION,
        budget_per_hour=args.budget_per_hour,
        max_per_run=args.max_per_run,
        timeout_seconds=args.timeout,
    )
    evidence = trace_evidence(run_dir, {event.decision_id for event in pending})
    counts: dict[str, int] = {}
    last_error: str | None = None
    for event in pending:
        record = analyst.analyze(event, trace_evidence=evidence.get(event.decision_id, ()))
        counts[record.status] = counts.get(record.status, 0) + 1
        if record.error_message:
            last_error = f"{record.error_code}: {record.error_message}"[:300]
        print(
            f"[analyst] {record.status:<15} {record.signal_id} "
            f"{event.symbol} {event.stage} {event.strategy_id or '-'} :: "
            f"{(record.claim or record.error_message or '')[:120]}"
        )
    summary = {
        "schema_version": "ai-analyst-pass-v1",
        "run_id": run_dir.name,
        "run_dir": str(run_dir),
        "passed_at_ms": int(time.time() * 1000),
        "passed_at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "provider_configured": provider is not None and provider.configured(),
        "provider": None if provider is None else provider.name,
        "model": None if provider is None else provider.model,
        "prompt_version": PROMPT_VERSION,
        "signals_seen": len(events),
        # Captured before this pass spent anything, so the number is measured
        # rather than reconstructed after the fact.
        "pending_before": len(waiting),
        "examined": len(pending),
        "statuses": counts,
        "last_error": last_error,
        "budget": {"per_hour": args.budget_per_hour, "max_per_run": args.max_per_run},
        "read_only": True,
        "authority_over_orders": False,
        "store": store.summary(),
    }
    write_heartbeat(run_dir, summary)
    if args.json:
        print(json.dumps(summary, indent=2, ensure_ascii=False))
    elif not pending:
        print("[analyst] nothing pending: every signal already has an analysis")
    if not summary["provider_configured"]:
        print(
            "[analyst] NOT_CONFIGURED: no provider key is present, so each pending signal "
            "is recorded as NOT_CONFIGURED (never as an analysed one). Set "
            "SIGNAL_ANALYST_API_KEY to enable live analysis.",
            file=sys.stderr,
        )
    return summary


def write_heartbeat(run_dir: Path, payload: dict[str, Any]) -> Path:
    """The sidecar's own liveness, written atomically next to its ledger."""
    target = run_dir / HEARTBEAT_NAME
    tmp = target.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    os.replace(tmp, target)
    return target


def stop_requested(path: Path | None) -> bool:
    return bool(path) and path.exists()


def main(argv: list[str] | None = None) -> int:
    allow_tolerant_console_output()
    args = parse_args(argv)
    root = REPO_ROOT / args.run_root
    run_dir = resolve_run_dir(root, args.run_id)
    if run_dir is None:
        print(
            f"[analyst] no run with a signal stream under {root}"
            + (f" (run id {args.run_id!r})" if args.run_id else ""),
            file=sys.stderr,
        )
        return 2
    provider = provider_from_env()
    print(
        f"[analyst] run={run_dir.name} provider="
        f"{'-' if provider is None else provider.name + ':' + provider.model} "
        f"configured={provider is not None and provider.configured()} mode="
        f"{'loop' if args.loop else 'once'}"
    )
    stop_file = None if args.stop_file is None else Path(args.stop_file)
    if not args.loop:
        run_pass(args, run_dir, provider)
        return 0
    try:
        while not stop_requested(stop_file):
            run_pass(args, run_dir, provider)
            deadline = time.monotonic() + max(1.0, args.interval)
            while time.monotonic() < deadline:
                if stop_requested(stop_file):
                    break
                time.sleep(min(1.0, deadline - time.monotonic()))
    except KeyboardInterrupt:
        print("[analyst] interrupted")
    print("[analyst] stopped")
    return 0


if __name__ == "__main__":
    with contextlib.suppress(BrokenPipeError):
        raise SystemExit(main())
