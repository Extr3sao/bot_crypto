#!/usr/bin/env python
"""WP-EDGE-06 — who else lives on the volume, measured again, and what moved.

WP-EDGE-05R named the volume's other tenants once, by hand, between `05:46Z` and
`05:49Z` on 2026-10-14, and stopped there because the mission authorises cache
cleanup *inside* the repository and nothing else. That walk could not be repeated:
the numbers lived in prose, so "did the volume's neighbours change?" had no answer
that did not involve believing a document written once.

This tool is that walk, made repeatable and left **read-only**:

1. It sizes every declared tenant outside the repository, with a per-tenant time
   budget. A tenant the budget cut short is reported as `measured: false` with the
   bytes it did walk — a partial sum is never printed as if it were a total;
2. it breaks the home user's `AppData/Local` down one level, because that is where
   the volume's growth lives, and ages the temporary directory's contents;
3. it compares every tenant with the previous reading of the same tenant, when one
   exists, so the question the operator actually has — *which consumer took the GiB*
   — is answered with two instants rather than one;
4. it deletes nothing, and says so in the artefact.

The comparison basis is stated for every row. When no previous reading of a tenant
exists, the row says so instead of comparing against a number from a different
method: the 05R walk is carried as a labelled baseline, not as a measurement of this
tool's.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]

SCHEMA_VERSION = "EDGE06_VOLUME_TENANTS_V1"
GIB = 1024**3
MIB = 1024**2

#: Seconds a single tenant may spend being walked. The two big trees (a user
#: profile and the operating system) hold hundreds of thousands of files on this
#: host; a walk without a budget is a walk that can run until the disk fills.
DEFAULT_BUDGET_SECONDS = 90.0

#: The age buckets the temporary directory is read by. A temporary file is by
#: definition regenerable; its *age* is what says whether anything still wants it.
AGE_BUCKETS: tuple[tuple[str, float, float], ...] = (
    ("under_6h", 0.0, 6.0),
    ("6h_to_24h", 6.0, 24.0),
    ("1d_to_7d", 24.0, 24.0 * 7),
    ("over_7d", 24.0 * 7, float("inf")),
)

#: The 05R manual walk, transcribed so the volume's evolution has a first instant
#: even on the very first run of this tool. Marked as transcribed inside the
#: payload: these bytes were counted by another method and must not be read as
#: this tool's own measurement.
BASELINE_05R: dict[str, Any] = {
    "as_of_utc": "2026-10-14T05:49:00Z",
    "method": "manual read-only walk recorded in WP-EDGE-05R/VOLUME_NEIGHBOURS.md",
    "tenants": {
        "AppData/Local": 85_457.7 * MIB,
        "Windows": 33_775.4 * MIB,
        "Program Files": 20_050.6 * MIB,
        "AppData/Roaming": 11_738.3 * MIB,
        "Program Files (x86)": 9_978.4 * MIB,
        "Downloads": 7_906.7 * MIB,
        "ProgramData": 1_976.0 * MIB,
        ".cache": 1_486.5 * MIB,
        "Documents": 1_302.1 * MIB,
        ".docker": 75.3 * MIB,
        ".npm": 52.3 * MIB,
        "AppData/Local/Temp": 29_747.9 * MIB,
        "AppData/Local/Microsoft": 14_714.8 * MIB,
        "AppData/Local/Programs": 7_193.1 * MIB,
        "AppData/Local/wsl": 6_310.0 * MIB,
        "AppData/Roaming/Msty": 6_503.1 * MIB,
        "AppData/Local/ms-playwright": 3_353.6 * MIB,
        "AppData/Local/hermes": 2_832.5 * MIB,
        "AppData/Local/npm-cache": 1_185.9 * MIB,
        "AppData/Roaming/Code": 1_693.3 * MIB,
        "AppData/Roaming/npm": 1_069.5 * MIB,
    },
}


def now_ms() -> int:
    return int(datetime.now(tz=UTC).timestamp() * 1000)


def stamp(instant_ms: int) -> str:
    return datetime.fromtimestamp(instant_ms / 1000, tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def disk_free(path: Path) -> int:
    import shutil

    return int(shutil.disk_usage(path).free)


def tenant_roots() -> list[tuple[str, Path, str]]:
    """The tenants to size, named relative to this host rather than hardcoded.

    A hardcoded `C:\\Users\\<name>\\...` would make this tool a record of one
    machine's spelling. The names stay stable across hosts because they are the
    paths *below* the volume root and the user profile, which is what a comparison
    between two readings needs.
    """
    home = Path.home()
    local = home / "AppData" / "Local"
    roaming = home / "AppData" / "Roaming"
    volume = Path(REPO_ROOT.drive + os.sep) if REPO_ROOT.drive else Path("/")

    declared: list[tuple[str, Path, str]] = [
        ("AppData/Local", local, "host user data"),
        ("AppData/Roaming", roaming, "host user data"),
        ("Downloads", home / "Downloads", "user data"),
        ("Documents", home / "Documents", "user data"),
        (".cache", home / ".cache", "tool cache (outside the repository)"),
        (".docker", home / ".docker", "tool cache (outside the repository)"),
        (".npm", home / ".npm", "tool cache (outside the repository)"),
        ("Windows", volume / "Windows", "operating system"),
        ("Program Files", volume / "Program Files", "installed software"),
        ("Program Files (x86)", volume / "Program Files (x86)", "installed software"),
        ("ProgramData", volume / "ProgramData", "installed software"),
    ]
    return [(name, path, kind) for name, path, kind in declared if path.exists()]


def breakdown_roots() -> list[tuple[str, Path, str]]:
    home = Path.home()
    local = home / "AppData" / "Local"
    roaming = home / "AppData" / "Roaming"
    declared: list[tuple[str, Path, str]] = [
        ("AppData/Local/Temp", local / "Temp", "temporary files"),
        ("AppData/Local/Microsoft", local / "Microsoft", "browser and profile caches"),
        ("AppData/Local/Programs", local / "Programs", "per-user installed software"),
        ("AppData/Local/wsl", local / "wsl", "WSL distributions (data, not cache)"),
        ("AppData/Local/ms-playwright", local / "ms-playwright", "browser builds"),
        ("AppData/Local/npm-cache", local / "npm-cache", "package cache"),
        ("AppData/Local/hermes", local / "hermes", "user data"),
        ("AppData/Roaming/Msty", roaming / "Msty", "local model files"),
        ("AppData/Roaming/Code", roaming / "Code", "editor state and extensions"),
        ("AppData/Roaming/npm", roaming / "npm", "global packages"),
    ]
    return [(name, path, kind) for name, path, kind in declared if path.exists()]


def walk_size(root: Path, *, budget_seconds: float) -> dict[str, Any]:
    """One bounded walk: bytes, files, and whether the budget cut it short.

    ``measured`` is the field that matters. A tenant whose walk hit the budget is
    reported with the bytes it *did* visit and `measured: false`; the caller prints
    those bytes as a floor, never as a size. Silently returning the partial sum as
    a total is how a budget becomes a lie.
    """
    started = time.monotonic()
    total = 0
    files = 0
    truncated = False
    unsized = 0
    for dirpath, dirnames, filenames in os.walk(root, onerror=lambda _e: None):
        dirnames.sort()
        if time.monotonic() - started > budget_seconds:
            truncated = True
            break
        for name in filenames:
            try:
                total += os.stat(os.path.join(dirpath, name)).st_size
                files += 1
            except OSError:
                unsized += 1
    return {
        "bytes": total,
        "files": files,
        "measured": not truncated,
        "unsized_entries": unsized,
        "walk_seconds": round(time.monotonic() - started, 2),
    }


def age_profile(root: Path, *, budget_seconds: float) -> dict[str, Any]:
    """The temporary directory by the age of each file's newest write."""
    now = time.time()
    buckets: dict[str, dict[str, Any]] = {
        label: {"bytes": 0, "files": 0} for label, _lo, _hi in AGE_BUCKETS
    }
    started = time.monotonic()
    truncated = False
    for dirpath, dirnames, filenames in os.walk(root, onerror=lambda _e: None):
        dirnames.sort()
        if time.monotonic() - started > budget_seconds:
            truncated = True
            break
        for name in filenames:
            try:
                stat = os.stat(os.path.join(dirpath, name))
            except OSError:
                continue
            age_hours = (now - stat.st_mtime) / 3600.0
            for label, low, high in AGE_BUCKETS:
                if low <= age_hours < high:
                    buckets[label]["bytes"] += stat.st_size
                    buckets[label]["files"] += 1
                    break
    return {
        "buckets": buckets,
        "measured": not truncated,
        "walk_seconds": round(time.monotonic() - started, 2),
    }


def previous_reading(out: Path) -> dict[str, Any] | None:
    path = out / "VOLUME_TENANTS.json"
    if not path.exists():
        return None
    try:
        payload: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if payload.get("schema_version") != SCHEMA_VERSION:
        return None
    return payload


def compare(
    current: dict[str, Any], previous: dict[str, Any] | None
) -> tuple[dict[str, Any], str]:
    """``(basis, sentence)`` for the evolution section, or a stated absence.

    The baseline is the previous run of THIS tool when one exists. Otherwise it is
    the 05R transcription, labelled as such: comparing against another method's
    numbers is a weaker claim than comparing against one's own, and the difference
    is printed rather than smoothed over.
    """
    if previous is not None:
        rows = {row["name"]: row["bytes"] for row in previous.get("tenants", [])}
        return (
            {
                "kind": "previous_run_of_this_tool",
                "as_of_utc": previous.get("as_of_utc"),
                "run_id": previous.get("run_id"),
                "tenants": rows,
            },
            f"compared with the previous run of this tool at {previous.get('as_of_utc')}",
        )
    rows = dict(BASELINE_05R["tenants"])
    return (
        {
            "kind": "transcribed_from_wp_edge_05r_report",
            "as_of_utc": BASELINE_05R["as_of_utc"],
            "method": BASELINE_05R["method"],
            "tenants": rows,
        },
        f"no previous run of this tool exists; every delta is against the 05R manual walk "
        f"({BASELINE_05R['as_of_utc']}), which is another method and is named as such",
    )


def build(*, budget_seconds: float) -> dict[str, Any]:
    instant = now_ms()
    as_of = stamp(instant)
    out_root = REPO_ROOT

    tenants: list[dict[str, Any]] = []
    for name, path, kind in tenant_roots():
        size = walk_size(path, budget_seconds=budget_seconds)
        tenants.append(
            {
                "name": name,
                "path": str(path),
                "kind": kind,
                "mib": round(size["bytes"] / MIB, 1),
                **size,
            }
        )

    breakdown: list[dict[str, Any]] = []
    temp_age: dict[str, Any] | None = None
    for name, path, kind in breakdown_roots():
        size = walk_size(path, budget_seconds=budget_seconds)
        breakdown.append({"name": name, "path": str(path), "kind": kind, **size})
        if name.endswith("/Temp"):
            temp_age = {"name": name, **age_profile(path, budget_seconds=budget_seconds)}

    payload: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "label": "WP-EDGE-06",
        "run_id": f"EDGE06-TENANTS-{as_of.replace('-', '').replace(':', '')}",
        "as_of_utc": as_of,
        "host": os.environ.get("COMPUTERNAME", "unknown"),
        "volume": {
            "drive": f"{REPO_ROOT.drive}/" if REPO_ROOT.drive else "/",
            "free_bytes": disk_free(out_root),
            "free_gib": round(disk_free(out_root) / GIB, 3),
        },
        "repository_root": str(REPO_ROOT),
        "method": (
            "read-only bounded directory walks; a tenant whose walk hit the "
            f"{budget_seconds:.0f}s budget carries measured: false and its bytes are a floor, "
            "not a size"
        ),
        "deleted_anything": False,
        "tenants": tenants,
        "tenants_total_bytes": sum(row["bytes"] for row in tenants),
        "tenants_all_measured": all(row["measured"] for row in tenants),
        "breakdown": breakdown,
        "temp_age": temp_age,
    }
    return payload


def render(payload: dict[str, Any], *, comparison: dict[str, Any], sentence: str) -> str:
    baseline = comparison.get("tenants") or {}
    lines = [
        f"# {payload['label']} — the volume's other tenants, measured again",
        "",
        f"*Read at `{payload['as_of_utc']}` on `{payload['host']}` by "
        f"`scripts/edge06_volume_tenants.py`. **This tool deletes nothing**: it sizes what "
        f"lives outside the repository and stops there.*",
        "",
        "## 1. The volume, and the part of it this work package may touch",
        "",
        "| | |",
        "| --- | --- |",
        f"| Volume | `{payload['volume']['drive']}` |",
        f"| Free | **{payload['volume']['free_gib']} GiB** ({payload['volume']['free_bytes']} bytes) |",
        f"| Repository | `{payload['repository_root']}` |",
        f"| Deleted anything | {payload['deleted_anything']} |",
        f"| Every tenant fully walked | {payload['tenants_all_measured']} |",
        "",
        payload["method"] + ".",
        "",
        "## 2. Who else is on the volume, and what they did since the last reading",
        "",
        sentence + ".",
        "",
        "| Tenant | Size | Files | Kind | Previous | Delta | Measured |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for row in sorted(payload["tenants"], key=lambda r: -r["bytes"]):
        previous = baseline.get(row["name"])
        delta = (
            f"{(row['bytes'] - previous) / MIB:+,.1f} MiB"
            if isinstance(previous, (int, float))
            else "no previous reading"
        )
        previous_cell = (
            f"{previous / MIB:,.1f} MiB" if isinstance(previous, (int, float)) else "—"
        )
        lines.append(
            f"| `{row['name']}` | {row['mib']:,.1f} MiB ({row['bytes']:,} B) | {row['files']:,} | "
            f"{row['kind']} | {previous_cell} | {delta} | "
            f"{'yes' if row['measured'] else '**no — a floor**'} |"
        )

    lines += [
        "",
        f"Those tenants hold **{payload['tenants_total_bytes'] / GIB:,.1f} GiB**"
        + ("" if payload["tenants_all_measured"] else " (a floor: at least one walk was cut short)")
        + ". The repository is not one of them.",
        "",
        "### The home user's `AppData` one level down",
        "",
        "| Tenant | Size | Files | Kind | Previous | Delta | Measured |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for row in sorted(payload["breakdown"], key=lambda r: -r["bytes"]):
        previous = baseline.get(row["name"])
        delta = (
            f"{(row['bytes'] - previous) / MIB:+,.1f} MiB"
            if isinstance(previous, (int, float))
            else "no previous reading"
        )
        lines.append(
            f"| `{row['name']}` | {row['bytes'] / MIB:,.1f} MiB | {row['files']:,} | {row['kind']} | "
            f"{f'{previous / MIB:,.1f} MiB' if isinstance(previous, (int, float)) else '—'} | "
            f"{delta} | {'yes' if row['measured'] else '**no — a floor**'} |"
        )

    if payload.get("temp_age"):
        age = payload["temp_age"]
        lines += [
            "",
            "### The temporary directory, by the age of its newest write",
            "",
            "| Newest write | Size | Files |",
            "| --- | --- | --- |",
        ]
        for label, _low, _high in AGE_BUCKETS:
            bucket = age["buckets"][label]
            lines.append(
                f"| {label.replace('_', ' ')} | {bucket['bytes'] / GIB:.2f} GiB | "
                f"{bucket['files']:,} |"
            )
        total = sum(b["bytes"] for b in age["buckets"].values())
        files = sum(b["files"] for b in age["buckets"].values())
        lines += [
            f"| **total** | **{total / GIB:.2f} GiB** | **{files:,}** |",
            "",
            (
                "The walk covered every file."
                if age["measured"]
                else "**The walk was cut short by its budget, so these are floors.**"
            ),
        ]

    lines += [
        "",
        "## 3. What this reading authorises, and what it does not",
        "",
        "- It sizes the volume's other occupants so that the repository's floor can be read "
        "against them. Every byte in this file belongs to somebody else.",
        "- It deletes nothing, and the plan for what could be deleted stays where WP-EDGE-05R "
        "put it: with the volume's owner, who is the only actor whose scope covers these paths.",
        "- It cannot be read as a cleanup: `deleted_anything` is `false` in the JSON as well as "
        "in this sentence.",
        "",
        "## 4. Provenance",
        "",
        "| Figure | Value | as_of_utc | Source |",
        "| --- | --- | --- | --- |",
        f"| `volume_free_bytes` | {payload['volume']['free_bytes']} | {payload['as_of_utc']} | "
        "operating system, `disk_usage` of the repository volume |",
        f"| `tenants_total_bytes` | {payload['tenants_total_bytes']} | {payload['as_of_utc']} | "
        "this tool's own bounded walks |",
        f"| `comparison_basis` | {comparison['kind']} | {comparison.get('as_of_utc')} | "
        f"{comparison.get('method') or comparison.get('run_id')} |",
        "",
        f"*`run_id`: `{payload['run_id']}`. Payload digest of the tenants section: "
        f"`{sha256_text(json.dumps(payload['tenants'], sort_keys=True))[:16]}…`.*",
        "",
    ]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--out", default=None)
    parser.add_argument("--budget-seconds", type=float, default=DEFAULT_BUDGET_SECONDS)
    parser.add_argument("--label", default="WP-EDGE-06")
    parser.add_argument("--json", action="store_true")
    options = parser.parse_args(argv)

    out = (
        Path(options.out)
        if options.out
        else REPO_ROOT / "reports" / "edge-recovery" / "WP-EDGE-06"
    )
    previous = previous_reading(out)
    payload = build(budget_seconds=options.budget_seconds)
    payload["label"] = options.label
    comparison, sentence = compare(payload, previous)

    if options.json:
        print(json.dumps({**payload, "comparison": comparison}, indent=2, sort_keys=True))
        return 0

    out.mkdir(parents=True, exist_ok=True)
    (out / "VOLUME_TENANTS.json").write_text(
        json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8"
    )
    (out / "VOLUME_TENANTS.md").write_text(
        render(payload, comparison=comparison, sentence=sentence), encoding="utf-8"
    )
    print(f"free {payload['volume']['free_gib']} GiB")
    print(
        f"{len(payload['tenants'])} tenant(s), "
        f"{payload['tenants_total_bytes'] / GIB:,.1f} GiB, "
        f"all measured: {payload['tenants_all_measured']}"
    )
    print(sentence)
    print(f"wrote VOLUME_TENANTS.json and VOLUME_TENANTS.md into {out}")
    return 0


if __name__ == "__main__":  # pragma: no cover - entry point
    raise SystemExit(main(sys.argv[1:]))
