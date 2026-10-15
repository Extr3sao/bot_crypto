#!/usr/bin/env python
"""Build the EDGE-09 decision panel from the forward microstructure capture.

    python scripts/edge09_panel.py --runs paper-lab-continuous-02 ...

Every second of the panel carries the instant it became knowable, so a feature
built from it cannot see the future. The panel is the input of WP-EDGE-09D and
WP-EDGE-09E, and the independent verifier re-derives samples of it from the raw
segments rather than trusting the file.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from trading_bot.research.edge09 import panel  # noqa: E402
from trading_bot.research.edge09.registration import SCHEMA_VERSION, WP  # noqa: E402

OUTDIR = WP / "panel"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--runs",
        nargs="*",
        default=["paper-lab-continuous-02", "paper-strategy-lifecycle-shadow-02"],
        help="capture run ids to fold into the panel",
    )
    options = parser.parse_args(argv)

    started = time.time()
    payload: dict[str, Any] = panel.build(OUTDIR, runs=tuple(options.runs))
    payload["schema_version"] = SCHEMA_VERSION
    payload["work_package"] = "WP-EDGE-09B"
    payload["declared_run_selection"] = list(options.runs)
    payload["selection_rule"] = (
        "the longest single continuous captures this repository holds; every other "
        "capture stays available and is enumerated in the estate audit"
    )
    payload["build_seconds"] = round(time.time() - started, 2)
    payload["stats"] = {key: value.as_dict() for key, value in payload["stats"].items()}
    payload["digests"] = {
        name: {
            "path": str(path.relative_to(REPO_ROOT)).replace("\\", "/"),
            "sha256": sha256_file(path),
            "bytes": path.stat().st_size,
        }
        for name, path in (
            ("panel_seconds", Path(payload["paths"]["panel_seconds"])),
            ("oi_samples", Path(payload["paths"]["oi_samples"])),
            ("depth_snapshots", Path(payload["paths"]["depth_snapshots"])),
        )
        if path.is_file()
    }
    payload["paths"] = {
        name: str(Path(value).relative_to(REPO_ROOT)).replace("\\", "/")
        for name, value in payload["paths"].items()
    }
    (OUTDIR / "PANEL.json").write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

    print(f"runs folded: {', '.join(payload['runs'])}")
    print(f"build seconds: {payload['build_seconds']}", flush=True)
    streams = 0
    for key, stat in payload["stats"].items():
        streams += 1
        print(
            f"  {key:<42} seconds={stat['seconds']:<7} quotes={stat['quotes']:<9} "
            f"trades={stat['trades']:<8} missing={stat['missing_seconds']:<6} "
            f"oi={stat['oi_samples']:<5} depth={stat['depth_snapshots']}"
        )
    print(f"streams: {streams}")
    for name, digest in payload["digests"].items():
        print(f"  {name}: {digest['bytes']} bytes sha256 {digest['sha256'][:16]}")
    print(f"wrote {OUTDIR.relative_to(REPO_ROOT)}/PANEL.{{json,csv}}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
