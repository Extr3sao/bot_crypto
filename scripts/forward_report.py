"""FORWARD READ-SIDE CLI — replay, report and daily views of a capture.

``scripts/forward_collector.py`` is the capture entry point and is one of the five
paths this phase proves byte-identical to the commit that produced the certified
hour. Reporting therefore lives here instead of being bolted onto it: adding a
flag there would have made the certified capture's own entry point differ from the
tree being certified, and no re-run of a finished hour can restore that equality.

Modes
-----
``report``  aggregate the capture, then write the contract / quality / evidence /
            resource / daily / replay artifacts the later phases cite.
``replay``  reconstruct the capture from disk and print the verification payload.
``daily``   print the compact FORWARD_DATA_DAILY_REPORT.

``--offline`` replaces the socket entry points with raisers for the duration of
the run, so a network-free replay is a property of the process rather than a claim
in the output. Every mode is read-only with respect to the capture: it never
writes under the segment, state or manifest directories — only the report
artifacts it is asked for.

Examples
--------
    uv run python scripts/forward_report.py --mode report --offline
    uv run python scripts/forward_report.py --mode replay --offline --write-docs
    uv run python scripts/forward_report.py --mode daily
"""

from __future__ import annotations

import argparse
import json
import socket
import sys
from pathlib import Path

from trading_bot.research.forward.replay import replay_microstructure_dataset
from trading_bot.research.forward.reporting import (
    REPORT_VERSION,
    build_aggregation,
    build_daily_report,
    build_quality_report,
    build_resource_report,
    load_run,
    save_aggregation,
    write_machine_readable_reports,
)
from trading_bot.research.forward.storage import DEFAULT_ROOT, save_json

OFFLINE_GUARD_NOTE = (
    "socket.socket / socket.create_connection / socket.getaddrinfo were replaced "
    "with raisers for the duration of this run"
)


def _json(payload: object) -> str:
    return json.dumps(payload, indent=2, ensure_ascii=False, default=str)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--mode", choices=("report", "replay", "daily"), default="report")
    parser.add_argument("--out", default=DEFAULT_ROOT)
    parser.add_argument("--docs-dir", default="docs")
    parser.add_argument("--run-id", default=None)
    parser.add_argument(
        "--offline",
        action="store_true",
        help="replace the socket entry points with raisers before any work starts",
    )
    parser.add_argument(
        "--write-docs",
        action="store_true",
        help="persist the JSON artifact for this mode (replay writes its own)",
    )
    return parser


def forbid_network() -> None:
    """Make a network-free run a fact about the process, not a promise."""

    def _forbidden(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("offline run attempted network access")

    socket.socket = _forbidden  # type: ignore[misc, assignment]
    socket.create_connection = _forbidden  # type: ignore[assignment]
    socket.getaddrinfo = _forbidden  # type: ignore[assignment]


def mode_replay(args: argparse.Namespace) -> int:
    verification = replay_microstructure_dataset(Path(args.out), args.run_id)
    payload = verification.as_dict()
    if args.offline:
        payload["offline_guard"] = OFFLINE_GUARD_NOTE
    print(_json(payload))
    if args.write_docs:
        target = Path(args.docs_dir) / "FORWARD_DATA_REPLAY_VALIDATION.json"
        target.parent.mkdir(parents=True, exist_ok=True)
        save_json(target, payload)
        print(f"replay validation -> {target}", file=sys.stderr)
    return 0 if verification.ok else 1


def mode_report(args: argparse.Namespace) -> int:
    root = Path(args.out)
    run_id, manifest = load_run(root, args.run_id)
    _resolved, aggregation = build_aggregation(root, run_id)
    aggregation_path = save_aggregation(root, run_id, aggregation)
    # Each section is a full streaming pass over the capture, so build every one
    # once and hand it to the writer instead of letting the writer rebuild them.
    quality = build_quality_report(root, run_id)
    resource = build_resource_report(root, run_id)
    daily = build_daily_report(root, run_id, quality=quality, resource=resource)
    replay = replay_microstructure_dataset(root, run_id)
    files = write_machine_readable_reports(
        root, args.docs_dir, run_id, quality=quality, resource=resource, daily=daily, replay=replay
    )
    if args.offline:
        guarded = replay.as_dict()
        guarded["offline_guard"] = OFFLINE_GUARD_NOTE
        save_json(files["replay"], guarded)
    print(
        _json(
            {
                "report_version": REPORT_VERSION,
                "run_id": run_id,
                "continuity": manifest.get("continuity"),
                "readiness": quality["readiness"],
                "resource_health": resource["resources"],
                "storage_verdict": resource.get("storage_capacity", {}).get("verdict"),
                "aggregation": str(aggregation_path),
                "replay_ok": replay.ok,
                "feature_match": replay.feature_match,
                "written": {name: str(path) for name, path in files.items()},
            }
        )
    )
    return 0 if replay.ok else 1


def mode_daily(args: argparse.Namespace) -> int:
    print(_json(build_daily_report(Path(args.out), args.run_id)))
    return 0


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.offline:
        forbid_network()
    if args.mode == "replay":
        return mode_replay(args)
    if args.mode == "daily":
        return mode_daily(args)
    return mode_report(args)


if __name__ == "__main__":
    raise SystemExit(main())
