"""WP-EDGE-12D — exercise the continuity properties on the real observer, then render them.

    python scripts/edge12_continuity.py --rehearse   drive the real observer over a copy
    python scripts/edge12_continuity.py --render     render from the stored receipts
    python scripts/edge12_continuity.py              read the live lane and render
    python scripts/edge12_continuity.py --json       print the matrix

The rehearsal copies the live store into an isolated root under ``data/forward/edge12``
and drives the real ``ForwardObserver`` over it, with the real ingest and the real
network. It takes minutes because it is real: six ticks, each one the whole frozen
pipeline. What it must never do is write into the live lane, and the isolation is what
makes that a property of the layout rather than a promise.

Research only: public market data, no credentials, no orders, no capital.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from trading_bot.research.edge12 import continuity, render  # noqa: E402
from trading_bot.research.edge12 import evidence as ev  # noqa: E402

REHEARSAL_FILENAME = "CONTINUITY_REHEARSAL.json"
LIVE_FILENAME = "LIVE_CONTINUITY.json"
SESSION_FILENAME = "SESSION_INDEPENDENCE.json"


def _live_rows(path: Path) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    if not path.is_file():
        return rows
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            loaded = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(loaded, dict):
            rows.append(loaded)
    return rows


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--reports", default=str(ev.DEFAULT_REPORTS))
    parser.add_argument("--state-root", default=str(ev.DEFAULT_STATE_ROOT))
    parser.add_argument("--store-root", default=str(ev.DEFAULT_STORE_ROOT))
    parser.add_argument("--work-root", default=None, help="where the rehearsal writes")
    parser.add_argument("--rehearse", action="store_true", help="drive the real observer now")
    parser.add_argument("--render", action="store_true", help="render without rehearsing")
    parser.add_argument("--drop-last", type=int, default=2, help="bars to remove per series")
    parser.add_argument("--no-network", action="store_true", help="declare the network unavailable")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    reports = ev.repo_path(args.reports)
    state_root = ev.repo_path(args.state_root)
    store_root = ev.repo_path(args.store_root)
    evidence_dir = reports / "evidence"
    evidence_dir.mkdir(parents=True, exist_ok=True)
    work_root = (
        ev.repo_path(args.work_root)
        if args.work_root
        else REPO_ROOT / "data" / "forward" / "edge12" / "rehearsal"
    )
    rehearsal_path = evidence_dir / REHEARSAL_FILENAME

    if args.rehearse:
        rehearsal = continuity.rehearsal(
            repo_root=REPO_ROOT,
            work_root=work_root,
            store_source=store_root,
            drop_last=args.drop_last,
            network=not args.no_network,
        )
        ev.write_json(rehearsal_path, rehearsal)
    else:
        rehearsal = ev.load_json(rehearsal_path)
        if not rehearsal:
            print(
                f"no stored rehearsal at {rehearsal_path}: run --rehearse first",
                file=sys.stderr,
            )
            return 3

    # The live reading is taken over a private copy of the two logs, so the numbers in the
    # report do not drift with a lane that keeps ticking while the file is written.
    snapshot_dir = evidence_dir
    for live_name, stored_name in (
        ("runs.jsonl", "RUN_LOG_SNAPSHOT.jsonl"),
        ("slots.jsonl", "SLOT_LEDGER_SNAPSHOT.jsonl"),
    ):
        source = state_root / live_name
        if source.is_file():
            shutil.copyfile(source, snapshot_dir / stored_name)
    live = continuity.live_continuity(
        runs_path=snapshot_dir / "RUN_LOG_SNAPSHOT.jsonl",
        alerts_path=state_root / "alerts.jsonl",
        slots_path=snapshot_dir / "SLOT_LEDGER_SNAPSHOT.jsonl",
        state_root=state_root,
    )
    ev.write_json(evidence_dir / LIVE_FILENAME, live)

    session_evidence = ev.load_json(evidence_dir / SESSION_FILENAME)
    if not session_evidence:
        runner_evidence = ev.load_json(evidence_dir / "RUNNER_PROBES.json")
        session_evidence = runner_evidence

    matrix = continuity.matrix(
        rehearsal_row=rehearsal, live=live, session_evidence=session_evidence
    )
    summary = continuity.rehearsal_summary(rehearsal)
    ev.write_json(reports / "CONTINUITY_MATRIX.json", matrix)
    (reports / "CONTINUITY_MATRIX.md").write_text(
        render.continuity_matrix_md(matrix, summary), encoding="utf-8"
    )
    (reports / "RECOVERY_REPORT.md").write_text(
        render.recovery_report_md(matrix=matrix, live=live, rehearsal=rehearsal), encoding="utf-8"
    )

    if args.json:
        print(
            json.dumps(
                {"matrix": matrix, "live": live, "summary": summary},
                indent=2,
                sort_keys=True,
                default=str,
            )
        )
        return 0
    print(
        f"rehearsal         {rehearsal.get('verdict')} ({len(rehearsal.get('steps') or [])} step(s))"
    )
    print(f"live ticks        {live['runs']} ({live['first_tick_utc']} -> {live['last_tick_utc']})")
    print(
        f"live silences     {len(live['gaps_over_the_declared_bound'])} (worst {live['worst_gap_seconds']} s)"
    )
    print(f"matrix            {matrix['verdict']}")
    for row in matrix["rows"]:
        print(f"  {row['property']:32s} {row['verdict']}")
    return 0 if rehearsal.get("verdict") == "REHEARSAL_PASS" else 5


if __name__ == "__main__":
    raise SystemExit(main())
