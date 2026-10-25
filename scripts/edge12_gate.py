"""WP-EDGE-12A — run the dependency and runtime gate, and render its deliverables.

    python scripts/edge12_gate.py                 collect from the host and render
    python scripts/edge12_gate.py --offline       re-derive from the stored evidence
    python scripts/edge12_gate.py --json          print the gate itself

Read-only with respect to the host, the lane and the scheduler: the gate runs ``--help``
on entry points and imports modules in a separate interpreter, and it reads the
scheduler through the same evidence collector WP-EDGE-04R uses.

Research only: public market data, no credentials, no orders, no capital.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from trading_bot.research.edge12 import evidence as ev  # noqa: E402
from trading_bot.research.edge12 import gate as G  # noqa: E402
from trading_bot.research.edge12 import render  # noqa: E402

EVIDENCE_FILENAME = "OS_EVIDENCE.json"
TASK_NAME = "TradingAgentic-EDGE04-Forward"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--reports", default=str(ev.DEFAULT_REPORTS))
    parser.add_argument("--state-root", default=str(ev.DEFAULT_STATE_ROOT))
    parser.add_argument("--store-root", default=str(ev.DEFAULT_STORE_ROOT))
    parser.add_argument("--task-name", default=TASK_NAME)
    parser.add_argument("--offline", action="store_true", help="read the stored host evidence")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    reports = ev.repo_path(args.reports)
    state_root = ev.repo_path(args.state_root)
    store_root = ev.repo_path(args.store_root)
    evidence_dir = reports / "evidence"
    evidence_path = evidence_dir / EVIDENCE_FILENAME

    if args.offline:
        stored = ev.load_json(evidence_path)
        if not stored:
            print(f"no stored host evidence at {evidence_path}", file=sys.stderr)
            return 3
        host_evidence = stored
    else:
        from trading_bot.research.edge04r import os_evidence

        host_evidence = os_evidence.collect(task_name=args.task_name)
        # The lane tree's own size is pinned here, at the instant it was read: it is the one
        # figure a later re-derivation would otherwise move, because the lane keeps writing.
        host_evidence["lane"] = {
            "state_root": str(state_root),
            "store_root": str(store_root),
            "bytes": _tree_bytes(state_root) + _tree_bytes(store_root),
            "measured_at_utc": ev.now_utc(),
        }
        ev.write_json(evidence_path, host_evidence)

    gate = G.dependency_gate(
        repo_root=REPO_ROOT,
        task_name=args.task_name,
        state_root=state_root,
        store_root=store_root,
        evidence=host_evidence,
    )
    baseline = G.baseline(gate)
    ev.write_json(reports / "DEPENDENCY_GATE.json", gate)
    ev.write_json(reports / "BASELINE.json", baseline)
    (reports / "DEPENDENCY_GATE.md").write_text(render.dependency_gate_md(gate), encoding="utf-8")
    (reports / "RUNTIME_AUTHORITY_MAP.md").write_text(
        render.runtime_authority_map_md(gate), encoding="utf-8"
    )
    if args.json:
        print(json.dumps(gate, indent=2, sort_keys=True, default=str))
        return 0
    print(f"verdict           {gate['verdict']}")
    print(
        f"entry points      {gate['entry_points']['reachable']}/{gate['entry_points']['total']}"
        f" answered --help with status 0"
    )
    print(
        f"modules           {gate['modules']['importable']}/{gate['modules']['total']} importable"
    )
    print(
        f"dependency        {gate['dependency_named_by_the_request']['identifier']}:"
        f" {gate['dependency_named_by_the_request']['audit']['verdict']}"
    )
    print(
        f"observer          {gate['observer_runtime']['runs']} tick(s), last"
        f" {gate['observer_runtime']['last_tick_utc']}"
    )
    print(
        f"scheduler         {gate['scheduler']['state']} /"
        f" {gate['scheduler']['logon_type']} / missed={gate['scheduler']['missed_runs']}"
    )
    print(f"storage           {gate['storage']['relocation_verdict']}")
    print(f"failing checks    {gate['failing_checks'] or 'none'}")
    print(f"deliverables      {reports}")
    return 0 if gate["verdict"] == "DEPENDENCY_GATE_PASS" else 5


def _tree_bytes(root: Path) -> int:
    if not root.is_dir():
        return 0
    return sum(path.stat().st_size for path in root.rglob("*") if path.is_file())


if __name__ == "__main__":
    raise SystemExit(main())
