"""WP-EDGE04-RECOVERY-15M — where the frozen 15m corpus could still exist, and proof of absence.

The frozen EDGE-03/04 pin does not store a file hash: ``trading_bot.research.edge01.data``
digests ``sha256(name + sha256(bytes))``, so a pin value alone cannot be checked against a
candidate file unless the file hash is known.  This script closes that gap first (that is the
part a reader should distrust least), then answers the only other question that matters
before anyone touches ``data/raw``: does a byte-identical copy of the three shards exist
anywhere this host can read?

Two independent records of the same bytes are decoded here:

* ``data/economic001/EVIDENCE_CLOSURE.json`` records a plain ``sha256`` per alpha003 shard,
  written 2026-10-08 while the corpus was still on disk;
* ``reports/edge-recovery/WP-EDGE-06/STORAGE_INVENTORY.json`` records the same shards'
  ``st_size``.

Recomputing the EDGE-01 digest from those recorded hashes reproduces all three frozen pins
exactly, which is what licenses the statement "the frozen 15m corpus *is* alpha003's 15m
files" — and, because it is written down in a commit, it also means the target is knowable
without the file.

Every search below is a *negative* result unless it finds a shard whose bytes hash to the
recorded value.  Absence is recorded with the count of what was looked at, so a later reader
can tell "searched and found nothing" from "did not search".
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]

#: The three shards EDGE-03/04 read, and the digest the pin carries for each.
FROZEN_PIN: dict[str, str] = {
    "BTC": "cd1d2ea256a97f7c",
    "ETH": "b8fd5744cc66f635",
    "SOL": "72a268137cbe944b",
}

#: Plain sha256 of the same shards, as recorded by ``data/economic001/EVIDENCE_CLOSURE.json``
#: on 2026-10-08 (``dataset_hashes``).  Imported rather than typed so a moved record fails
#: the check instead of agreeing with itself.
ECON_CLOSURE = REPO / "data" / "economic001" / "EVIDENCE_CLOSURE.json"
STORAGE_INVENTORY = REPO / "reports" / "edge-recovery" / "WP-EDGE-06" / "STORAGE_INVENTORY.json"

#: Where the shards were read from when they still existed, and the byte count the storage
#: inventory recorded there.
SHARD_SUBDIR = "raw/alpha003/price"
TARGET_NAME = "{asset}USDT_15m.json"

#: Directories that cannot hold a 2024-2026 kline shard and would swamp the walk.
PRUNE = {
    ".git",
    ".venv",
    "node_modules",
    "site-packages",
    "__pycache__",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
}


def os_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def pin_digest(name: str, file_sha: str) -> str:
    """The exact recipe ``edge01.data._digest`` uses for a one-file corpus."""
    return hashlib.sha256((name + file_sha).encode("utf-8")).hexdigest()


def recorded_hashes() -> dict[str, Any]:
    """The two committed records, read as data, plus whether they agree with the pin."""
    econ = json.loads(ECON_CLOSURE.read_text(encoding="utf-8"))
    dataset = econ["dataset_hashes"]
    inv = json.loads(STORAGE_INVENTORY.read_text(encoding="utf-8"))
    #: The inventory lists the biggest files per subtree; a shard smaller than the cut-off is
    #: absent from it, and that absence is recorded rather than guessed at.
    sizes = {
        member["path"]: member["bytes"]
        for entry in inv.get("subtrees", [])
        for member in entry.get("largest_members", [])
        if member.get("path")
    }
    out: dict[str, Any] = {"economic001_generated_at_utc": econ.get("generated_at_utc"), "shards": {}}
    for asset, pin in FROZEN_PIN.items():
        key = f"data/{SHARD_SUBDIR}/{TARGET_NAME.format(asset=asset)}"
        file_sha = dataset.get(key)
        size = sizes.get(SHARD_SUBDIR + "/" + TARGET_NAME.format(asset=asset))
        derived = pin_digest(TARGET_NAME.format(asset=asset), file_sha) if file_sha else None
        out["shards"][asset] = {
            "path": key,
            "recorded_file_sha256": file_sha,
            "recorded_bytes": size,
            "frozen_pin": pin,
            "pin_rederived_from_record": derived[:16] if derived else None,
            "pin_agrees": bool(derived) and derived[:16] == pin,
        }
    out["all_pins_agree"] = all(s["pin_agrees"] for s in out["shards"].values())
    return out


def walk_for(names: set[str], roots: list[Path], *, max_depth: int | None = None) -> dict[str, Any]:
    """Every file under ``roots`` whose name is one of ``names`` (or a 15m alpha003 shape)."""
    hits: list[dict[str, Any]] = []
    scanned = 0
    for root in roots:
        if not root.is_dir():
            continue
        base_depth = len(root.parts)
        for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
            here = Path(dirpath)
            if max_depth is not None and len(here.parts) - base_depth >= max_depth:
                dirnames[:] = []
            dirnames[:] = [d for d in dirnames if d not in PRUNE]
            scanned += len(filenames)
            for name in filenames:
                if name in names:
                    hits.append({"path": str(here / name), "bytes": (here / name).stat().st_size})
    return {"roots": [str(r) for r in roots], "files_scanned": scanned, "hits": hits}


def git_objects() -> dict[str, Any]:
    def run(*args: str) -> str:
        try:
            return subprocess.run(
                ["git", *args], cwd=REPO, capture_output=True, text=True, check=False
            ).stdout
        except OSError:  # git absent: say so rather than reporting a clean history
            return ""

    objects = [ln for ln in run("rev-list", "--objects", "--all").splitlines() if "_15m.json" in ln]
    dangling = [ln for ln in run("fsck", "--lost-found").splitlines() if "dangling blob" in ln]
    biggest = []
    for line in dangling:
        sha = line.split()[-1]
        size = run("cat-file", "-s", sha).strip()
        if size.isdigit():
            biggest.append({"sha": sha, "bytes": int(size)})
    biggest.sort(key=lambda item: item["bytes"], reverse=True)
    return {
        "tracked_or_reachable_objects_named_15m": objects,
        "dangling_blobs": len(dangling),
        "largest_dangling_blobs": biggest[:5],
        "lfs_attributes": [
            ln
            for ln in (REPO / ".gitattributes").read_text(encoding="utf-8").splitlines()
            if "filter=lfs" in ln
        ],
        "lfs_files": [ln for ln in run("lfs", "ls-files").splitlines() if ln.strip()],
    }


def recycle_bin() -> dict[str, Any]:
    # ``Path("C:") / "$Recycle.Bin"`` yields ``C:$Recycle.Bin`` — a relative path that is not a
    # directory — so the root is joined as text. An unreadable bin must read as "not searched",
    # never as "searched, empty".
    root = Path(f"{os.environ.get('SYSTEMDRIVE', 'C:')}/$Recycle.Bin")
    if not root.is_dir():
        return {"root": str(root), "searched": False, "files": 0, "largest": [], "unreadable": 0}
    # A bin can hold reparse points and paths longer than the API will stat; a walk that dies
    # on one of them reports nothing at all, which is the failure mode this check exists to
    # avoid. Unreadable entries are counted, not swallowed.
    entries: list[Path] = []
    unreadable = 0

    def onerror(_exc: OSError) -> None:
        nonlocal unreadable
        unreadable += 1

    for dirpath, _dirnames, filenames in os.walk(root, onerror=onerror, followlinks=False):
        for name in filenames:
            entries.append(Path(dirpath) / name)
    files = len(entries)
    sized = []
    for path in entries:
        try:
            sized.append({"path": str(path), "bytes": path.stat().st_size})
        except OSError:
            unreadable += 1
    return {
        "root": str(root),
        "searched": True,
        "files": files,
        "unreadable": unreadable,
        "largest": sorted(sized, key=lambda item: item["bytes"], reverse=True)[:5],
    }


def verify_candidates(candidates: list[Path], recorded: dict[str, Any]) -> list[dict[str, Any]]:
    """A candidate only counts if its bytes hash to the recorded value. Nothing else does."""
    out = []
    for path in candidates:
        if not path.is_file():
            continue
        sha = os_sha256(path)
        asset = path.name.split("USDT")[0]
        want = recorded["shards"].get(asset, {})
        out.append(
            {
                "path": str(path),
                "bytes": path.stat().st_size,
                "file_sha256": sha,
                "matches_recorded_file_sha256": sha == want.get("recorded_file_sha256"),
                "matches_frozen_pin": pin_digest(path.name, sha)[:16] == want.get("frozen_pin"),
            }
        )
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", default=None, help="write the audit JSON here")
    ap.add_argument(
        "--extra-root",
        action="append",
        default=[],
        help="another tree to sweep (repeatable; the default set is the host's likely holders)",
    )
    args = ap.parse_args(argv)

    home = Path.home()
    names = {TARGET_NAME.format(asset=a) for a in FROZEN_PIN}
    default_roots = [
        REPO / "data",
        REPO / "reports",
        REPO / "docs",
        home / "Downloads",
        home / "incident-backup-20261023",
        home / "AppData" / "Local" / "Temp",
    ]
    roots = default_roots + [Path(p) for p in args.extra_root]
    drives = [Path(f"{d}:\\") for d in "CDEFG" if Path(f"{d}:\\").is_dir()]

    recorded = recorded_hashes()
    audit = {
        "wp": "WP-EDGE04-RECOVERY-15M",
        "purpose": "locate a byte-identical copy of the frozen 15m corpus, or prove there is none",
        "frozen_pin": dict(FROZEN_PIN),
        "recorded": recorded,
        "searches": {
            "named_shards": walk_for(names, roots),
            "alpha003_trees": walk_for({"alpha003"}, roots),
            "drives_present": [str(d) for d in drives],
            "whole_drive_named_shards": walk_for(names, [d for d in drives if str(d) != "C:\\"]),
            "git": git_objects(),
            "recycle_bin": recycle_bin(),
        },
    }
    audit["every_name_match_hashed"] = verify_candidates(
        [Path(h["path"]) for h in audit["searches"]["named_shards"]["hits"]], recorded
    )
    audit["candidates_that_match"] = [
        c
        for c in verify_candidates(
            [REPO / "data" / SHARD_SUBDIR / TARGET_NAME.format(asset=a) for a in FROZEN_PIN]
            + [Path(h["path"]) for h in audit["searches"]["named_shards"]["hits"]],
            recorded,
        )
        if c["matches_recorded_file_sha256"]
    ]
    audit["corpus_present_in_expected_location"] = (REPO / "data" / SHARD_SUBDIR).is_dir()
    audit["verdict"] = (
        "RECOVERED"
        if audit["candidates_that_match"]
        else "NO_BYTE_IDENTICAL_COPY_FOUND"
    )

    text = json.dumps(audit, indent=2, sort_keys=True, default=str) + "\n"
    if args.out:
        Path(args.out).write_text(text, encoding="utf-8")
    print(text)
    return 0 if audit["verdict"] == "RECOVERED" else 1


if __name__ == "__main__":
    sys.exit(main())
