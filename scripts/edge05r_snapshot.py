#!/usr/bin/env python
"""WP-EDGE-05R — take one reading of the live state, and freeze it.

Every number the reports quote comes from the file this writes, with the instant it was read at,
the artefact it came from and that artefact's digest. Take a snapshot, then render the reports from
it: `scripts/edge05r_report.py`. Two renders of one snapshot are the same numbers by construction,
which is the whole point — a hand-written figure goes stale the moment the lane ticks again.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from trading_bot.research.edge05 import reading  # noqa: E402


def default_paths(repo_root: Path, out: Path) -> dict[str, Path]:
    return {
        "lane_state_root": repo_root / "data" / "forward" / "edge04",
        "watch_state_root": repo_root / "data" / "forward" / "edge05",
        "store_root": repo_root / "data" / "forward" / "edge03",
        "inventory": out / "STORAGE_INVENTORY.json",
        "reclaim": out / "STORAGE_RECLAIM.json",
        "verification": out / "VERIFICATION.json",
        "evidence_dir": repo_root / "reports" / "edge-recovery" / "WP-EDGE-05" / "evidence",
        "authority_map": out / "runtime_authority_map.md",
        "github": out / "GITHUB_STATE.json",
        "tests": out / "REGRESSION.json",
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--repo-root", default=None)
    parser.add_argument("--out", default=None, help="the work package's report directory")
    parser.add_argument("--lane-state-root", default=None)
    parser.add_argument("--watch-state-root", default=None)
    parser.add_argument("--store-root", default=None)
    parser.add_argument("--json", action="store_true", help="print the snapshot instead of writing it")
    options = parser.parse_args(argv)

    repo_root = Path(options.repo_root).resolve() if options.repo_root else REPO_ROOT
    out = (
        Path(options.out)
        if options.out
        else repo_root / "reports" / "edge-recovery" / "WP-EDGE-05R"
    )
    paths = default_paths(repo_root, out)
    for key in ("lane_state_root", "watch_state_root", "store_root"):
        override = getattr(options, key)
        if override:
            paths[key] = Path(override)

    for optional in (
        "inventory",
        "reclaim",
        "verification",
        "evidence_dir",
        "authority_map",
        "github",
        "tests",
    ):
        if not paths[optional].exists():
            paths[optional] = None

    snapshot = reading.collect(repo_root=repo_root, **paths)
    if options.json:
        print(json.dumps(snapshot.as_dict(), indent=2, sort_keys=True, default=str))
        return 0

    out.mkdir(parents=True, exist_ok=True)
    target = out / "READING_SNAPSHOT.json"
    target.write_text(
        json.dumps(snapshot.as_dict(), indent=2, sort_keys=True, default=str) + "\n",
        encoding="utf-8",
    )
    ok, why = snapshot.verified()
    print(f"snapshot {snapshot.run_id} taken at {snapshot.as_of_utc}")
    print(f"{len(snapshot.figures)} figure(s) from {len(snapshot.sources)} source artefact(s)")
    print(f"digest {snapshot.digest[:16]}…  ({'self-check ok' if ok else why})")
    print(f"wrote {target}")
    return 0 if ok else 1


if __name__ == "__main__":  # pragma: no cover - entry point
    raise SystemExit(main())
