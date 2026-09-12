"""Read-only query utility for an immutable decision-trace JSONL store."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from trading_bot.diagnostics import TraceReason, TraceStore


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--path", required=True, type=Path)
    parser.add_argument("--trace-id")
    parser.add_argument("--run-id")
    parser.add_argument("--proposal-id")
    parser.add_argument("--reason", choices=[item.value for item in TraceReason])
    args = parser.parse_args()
    reason = TraceReason(args.reason) if args.reason else None
    events = TraceStore(args.path).query(
        trace_id=args.trace_id,
        run_id=args.run_id,
        proposal_id=args.proposal_id,
        reason=reason,
    )
    print(json.dumps([item.to_dict() for item in events], indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
