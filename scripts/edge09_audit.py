#!/usr/bin/env python
"""WP-EDGE-09A — write the estate audit.

    python scripts/edge09_audit.py

Reads the repository, the authoritative configs and the forward captures, and
publishes ``audit/ESTATE.{json,md}``. Nothing is written outside the work
package directory, and no authoritative file is opened for writing.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from trading_bot.research.edge09 import estate  # noqa: E402
from trading_bot.research.edge09.registration import WP  # noqa: E402

OUTDIR = WP / "audit"


def render(payload: dict[str, Any]) -> str:
    auth = payload["authoritative"]
    lines = [
        "# WP-EDGE-09A — estate audit",
        "",
        f"*Read at the tree of `{payload['head'][:12]}` on branch "
        f"`{payload['branch']}`. RFC present: `{payload['rfc_present']}`.*",
        "",
        "## 1. Authoritative inputs (read, never written)",
        "",
        "| File | Bytes | SHA-256 | Last commit | Dirty |",
        "| --- | ---: | --- | --- | :-: |",
    ]
    for row in auth["files"]:
        lines.append(
            f"| `{row['path']}` | {row['bytes']} | `{row['sha256'][:16]}…` | "
            f"{row['last_commit']} | {row['worktree_modified']} |"
        )
    lines += [
        "",
        f"Runtime mode `{auth['runtime_mode']}`, `live_trading_enabled` in "
        f"`config/runtime.yaml` = `{auth['runtime_live_trading_enabled']}` and in "
        f"`config/risk.yaml` = `{auth['risk_live_trading_enabled']}`. This package "
        "reads both and writes neither.",
        "",
        "## 2. Data estate",
        "",
        "| Path | Kind | Files | MiB |",
        "| --- | --- | ---: | ---: |",
    ]
    for row in payload["estate"]["directories"]:
        if not row["present"]:
            lines.append(f"| `{row['path']}` | {row['kind']} | — | absent |")
            continue
        lines.append(f"| `{row['path']}` | {row['kind']} | {row['files']} | {row['mib']} |")
    lines += [
        "",
        "## 3. Forward microstructure captures actually on disk",
        "",
        "| Root | Run | Started | Duration (s) | Markets | Segments | Continuity | Status |",
        "| --- | --- | --- | ---: | --- | ---: | --- | --- |",
    ]
    for run in payload["captures"]:
        duration = run["duration_seconds"]
        lines.append(
            f"| `{run['root']}` | `{run['run_id']}` | {run['started_at']} | "
            f"{round(duration, 1) if isinstance(duration, (int, float)) else '—'} | "
            f"{run['markets']} | {run['segments_on_disk']} | {run['continuity']} | "
            f"{run['status']} |"
        )
    lines += [
        "",
        "## 4. Closed work, read from the artifact that closed it",
        "",
        "| Phase | Artifact | Status line | Digest |",
        "| --- | --- | --- | --- |",
    ]
    for row in payload["closed_phases"]:
        lines.append(
            f"| {row['phase']} | `{row['artifact']}` | "
            f"{(row['status_line'] or '—')[:180]} | `{row['sha256'] or '—'}` |"
        )
    lines += [
        "",
        "## 5. What this package reuses, and what it must not repeat",
        "",
    ]
    for asset in payload["reusable_assets"]:
        lines.append(f"- `{asset['asset']}` — {asset['why']}")
    lines += [
        "",
        "## 6. Work packages of RFC-EDGE-009",
        "",
    ]
    for wp in payload["work_packages"]:
        lines.append(f"- **{wp['id']}** — {wp['scope']}")
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    payload = estate.build()
    OUTDIR.mkdir(parents=True, exist_ok=True)
    (OUTDIR / "ESTATE.json").write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    (OUTDIR / "ESTATE.md").write_text(render(payload), encoding="utf-8")
    print(f"head {payload['head'][:12]}  captures {len(payload['captures'])}")
    print(
        "authoritative files: "
        + ", ".join(
            f"{row['path'].split('/')[-1]}={row['sha256'][:8]}"
            for row in payload["authoritative"]["files"]
        )
    )
    for run in payload["captures"]:
        markets = run["markets"]
        if isinstance(markets, list):
            markets = ",".join(str(item) for item in markets)
        duration = run["duration_seconds"]
        print(
            f"  {run['run_id']:<28} {markets!s:<10} "
            f"{round(duration, 1) if isinstance(duration, (int, float)) else '—'}s  "
            f"segments={run['segments_on_disk']}  {run['continuity']}"
        )
    print(f"wrote {OUTDIR.relative_to(REPO_ROOT)}/ESTATE.{{json,md}}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
