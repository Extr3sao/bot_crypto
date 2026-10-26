"""WP-EDGE-05 — reconcile the forward store against the ticks that claim it, and their decisions.

    python scripts/edge05_reconcile.py              reconcile, write the artefacts, report the status
    python scripts/edge05_reconcile.py --json       the whole report on stdout
    python scripts/edge05_reconcile.py --at INSTANT reconcile as if the clock read INSTANT

Exit codes:

    0  CLEAN or HISTORICAL_ONLY   every stored bar is attributed, and every unattributed attempt is
                                  a closed episode: its bars are all present and the interval it
                                  covered was never written again
    1  OPEN_DEFECTS               something is attributed to nobody, claimed and absent, claimed
                                  twice, or evaluated twice with different decisions

The reconciliation is a *reading*: it never rewrites the lane's run log, its slot ledger, its daily
evidence files or the store. What it cannot attribute, it names — an attempt that died before it
recorded itself is marked as such, with the bars it stored and the tick that found them already
there, rather than being invented into the run log.

Research only: no orders, no credentials, no capital, no promotion.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from trading_bot.research.edge05.reconcile import Reconciler  # noqa: E402

EXIT_STATUS = {"CLEAN": 0, "HISTORICAL_ONLY": 0, "OPEN_DEFECTS": 1}


def _instant(text: str | None) -> int | None:
    if not text:
        return None
    parsed = datetime.fromisoformat(text.strip().replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return int(parsed.timestamp() * 1000)


def _summary(report: dict) -> str:
    counts = report["inputs"]["counts"]
    chains = report["chains"]
    lines = [
        f"status    {report['status']} · verdict {report['verdict']} · {report['generated_at_utc']}",
        f"inputs    runs {counts['runs']} · consuming {counts['consuming_runs']} · seals "
        f"{counts['seals']} · ledger rows {counts['ledger_rows']} · attempts {counts['ingest_attempts']}",
        f"attempts  with a run row {report['attempts']['with_a_run']} · without "
        f"{report['attempts']['without_a_run']}",
        f"defects   {json.dumps(report['defect_counts'], sort_keys=True)}",
        f"open      {json.dumps(report['open_defect_counts'], sort_keys=True)}",
    ]
    for name, body in sorted(chains.items()):
        lines.append(
            f"  {name:<9} epoch {body['epoch_utc']} · rows {body['ledger_rows']} · claimed "
            f"{body['claimed_bars']} · stored {body['stored_bars']} · unattributed "
            f"{body['unattributed_bars']} · chain {'holds' if body['chain_holds'] else 'BROKEN'}"
        )
    for item in report["attempts"]["without_a_run_detail"]:
        lines.append(
            f"  attempt {item['attempt_at_utc']}: {item['bars_appended']} bar(s), no run row, "
            f"recovered by {item.get('next_run_id')} at {item.get('next_attempt_with_a_run')}"
        )
    for item in report["open_defects"]:
        lines.append(f"  OPEN {item['state']}: {json.dumps(item, sort_keys=True, default=str)[:240]}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--lane-state-root", default=None)
    parser.add_argument("--store-root", default=None)
    parser.add_argument("--state-root", default=None)
    parser.add_argument("--at", default=None, help="the instant to reconcile as of (ISO-8601 UTC)")
    parser.add_argument("--json", action="store_true", help="the whole report on stdout")
    parser.add_argument("--no-write", action="store_true", help="do not write the artefacts")
    options = parser.parse_args(argv)

    reconciler = Reconciler(
        repo_root=REPO_ROOT,
        lane_state_root=Path(options.lane_state_root) if options.lane_state_root else None,
        store_root=Path(options.store_root) if options.store_root else None,
        state_root=Path(options.state_root) if options.state_root else None,
    )
    report = reconciler.reconcile(now_ms=_instant(options.at))
    if not options.no_write:
        written = reconciler.write(report)
        report = {**report, "artifacts": {name: str(path) for name, path in sorted(written.items())}}
    if options.json:
        print(json.dumps(report, indent=2, sort_keys=True, default=str))
    else:
        print(_summary(report))
    return EXIT_STATUS.get(str(report["status"]), 1)


if __name__ == "__main__":  # pragma: no cover - entry point
    raise SystemExit(main())
