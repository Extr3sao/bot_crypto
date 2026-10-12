"""WP-EDGE-03 runner — forward observation, shadow reading and risk parity.

    python scripts/edge03_run.py [--outdir reports/edge-recovery/WP-EDGE-03]
                                 [--observed-at 2026-10-13T00:00:00Z]
                                 [--scenarios BASE,2X_FEES,ADVERSE]
                                 [--sweep-cases 384] [--quick]
                                 [--reports-only PATH]

``--reports-only`` re-renders the daily and cumulative reports from an
``OBSERVATION.json`` a previous run preserved, without touching the network or the
store: the reporting layer reads the stored observation, not the venue.

What it does, in order, and nothing else:

1. re-reads the frozen corpora and refuses to run if their bytes moved;
2. grows the local forward store with the closed bars the venue published after
   the frozen end, per series, recording ``no_new_data`` where there were none;
3. proves restart safety by ingesting a second time at the SAME market instant
   (it must append nothing and leave every digest identical);
4. walks the frozen rulesets over the forward window and books hypothetical fills
   only — this process has no exchange client and sends no order;
5. feeds the research budget and the runtime Risk Engine the same state and the
   same intent, and classifies every agreement and divergence;
6. writes the daily report, the cumulative report and the parity findings.

Exit status is 0 whenever the run completed, including a run that found no new
data: "nothing happened" is a recorded result here, not a failure. It is non-zero
only when the lane could not do the work.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from trading_bot.research.edge03.parity import write_parity_artifacts  # noqa: E402
from trading_bot.research.edge03.reporting import write_observability  # noqa: E402
from trading_bot.research.edge03.run import (  # noqa: E402
    write_forward_artifacts,
    run_forward_observation,
)

#: The callable both the runner and the tests drive. Named here so the verifier can insist
#: that the two targets are the same one (WP-EDGE-03 §E).
TARGET = "run_forward_observation"


def _parse_instant(value: str | None) -> int | None:
    if not value:
        return None
    text = value.strip().replace("Z", "+00:00")
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return int(parsed.timestamp() * 1000)


def _reports_only(observation: Path, outdir: Path) -> int:
    """Re-render the daily and cumulative reports from a preserved observation.

    A report is a reading of a stored observation, so it must be reproducible without the
    venue: this path proves a reader can regenerate every human-facing artefact offline.
    """
    if not observation.is_file():
        print(f"no observation at {observation}", file=sys.stderr)
        return 2
    payload = json.loads(observation.read_text(encoding="utf-8"))
    if not payload.get("health") or "ingest" not in payload:
        print(f"{observation} is not an EDGE-03 observation", file=sys.stderr)
        return 2
    written = write_observability(payload, outdir)
    print(f"re-rendered from {observation} (no fetch):")
    for name, path in sorted(written.items()):
        print(f"  {name}: {path}")
    print(json.dumps({"reports_only": True, "dates": sorted(payload.get("daily", {}))}))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--outdir",
        default="reports/edge-recovery/WP-EDGE-03",
        help="where the artefacts go",
    )
    parser.add_argument(
        "--observed-at",
        default=None,
        help="market instant of the run (ISO-8601 UTC); default: the venue's server time",
    )
    parser.add_argument(
        "--scenarios", default="BASE,2X_FEES,ADVERSE", help="cost scenarios to shadow"
    )
    parser.add_argument("--sweep-cases", type=int, default=384, help="declared parity sweep size")
    parser.add_argument("--shadow-case-limit", type=int, default=600)
    parser.add_argument("--quick", action="store_true", help="a smaller parity sweep")
    parser.add_argument(
        "--reports-only",
        default=None,
        help="re-render the reports from a preserved OBSERVATION.json (no fetch, no ingest)",
    )
    args = parser.parse_args(argv)

    outdir = Path(args.outdir)
    if args.reports_only:
        return _reports_only(Path(args.reports_only), outdir / "forward-observation")
    scenarios = tuple(s.strip() for s in args.scenarios.split(",") if s.strip())
    sweep = 64 if args.quick else args.sweep_cases

    payload = run_forward_observation(
        repo_root=REPO_ROOT,
        observed_at_ms=_parse_instant(args.observed_at),
        scenarios=scenarios,
        sweep_cases=sweep,
        shadow_case_limit=args.shadow_case_limit,
    )
    payload["entrypoint"] = f"scripts/edge03_run.py:{TARGET}"
    payload["test_target"] = TARGET

    written = write_forward_artifacts(payload, outdir / "forward-observation")
    written.update(write_parity_artifacts(payload["parity"], outdir / "risk-parity"))

    print(f"run            {payload['run_id']}")
    print(f"market instant {payload['observed_at_utc']}")
    print(f"new bars       {payload['health']['new_bars']}")
    print(f"observation    {payload['health']['observation_days']} independent day(s)")
    print(f"verdict        {payload['verdict']['state']} — {payload['verdict']['reason']}")
    print(f"risk parity    {payload['parity']['verdict']}")
    for klass, count in sorted(payload["parity"]["counts"].items()):
        print(f"  {klass:<32} {count}")
    primary_key = str(payload["shadow"]["primary_arm"])
    primary = payload["shadow"]["arm_summaries"].get(primary_key, {})
    if primary.get("status") == "observed":
        metrics = primary["metrics"]
        print(
            f"primary arm    {primary['arm']} signals={primary['signal_count']} "
            f"fills={metrics['trades']} net={metrics['net_usdt']:.2f} USDT "
            f"(hypothetical, no order sent)"
        )
    else:
        print(f"primary arm    {primary.get('status')}: {primary.get('reason')}")
    print("artefacts:")
    for name, path in sorted(written.items()):
        print(f"  {name}: {path}")
    print(json.dumps({"verdict": payload["verdict"]["state"], "new_bars": payload["health"]["new_bars"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
