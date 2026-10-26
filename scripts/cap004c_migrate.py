#!/usr/bin/env python
"""CAP-004C — the storage migration driver (derived artifacts only).

What this script may touch, and why it is allowed to touch it:

* ``reports/cap004/archive/<legacy>/`` — the byte-for-byte copies of the report
  files that grew out of control.  They are **derived** (reports/ is regenerable
  and gitignored, and the authoritative record of every cycle lives in
  ``evidence/real_decisions/operations.jsonl``).  Compression is *lossless*: a
  per-file SHA-256 of the source is compared with a SHA-256 re-derived by
  decompressing the archive, so the archive is provably the same bytes before the
  source is ever removed.  Nothing is deleted until that comparison passes inside
  the same run, and only with ``--commit``.

* ``reports/ALPHA_SCORECARD.json`` / ``.md`` — the CAP-003 scorecard artifact.  It
  is a projection of the shared ledger, and the CAP-003 verifier asserts that it
  recomputes from that ledger.  The writer is the frozen CAP-003 scoring function
  itself; this script only re-runs it (no scoring logic is duplicated here).

What this script never touches: decisions, outcomes, evaluations, operations, raw
evidence, checkpoints, the manifest, or anything under ``evidence/``.

Usage::

    python scripts/cap004c_migrate.py --archive-dir reports/cap004/archive/legacy-... [--commit]
    python scripts/cap004c_migrate.py --refresh-scorecard [--commit]
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import importlib.util
import json
import os
import shutil
import sys
import time
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

MIGRATION_VERSION = "CAP004C_STORAGE_MIGRATION_V1"
MANIFEST_FILENAME = "STORAGE_MIGRATION_MANIFEST.json"
CHUNK = 8 << 20


def git_commit() -> str:
    import subprocess

    try:
        return subprocess.run(
            ["git", "rev-parse", "HEAD"], capture_output=True, text=True, check=True, cwd=REPO
        ).stdout.strip()
    except Exception:  # pragma: no cover - a checkout without git is still auditable
        return "UNKNOWN"


def now_iso() -> str:
    import datetime as dt

    return dt.datetime.fromtimestamp(int(time.time()), dt.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def sha256_file(path: Path) -> tuple[str, int]:
    """(sha256, bytes) computed by streaming; bounded memory, any file size."""
    digest = hashlib.sha256()
    size = 0
    with Path(path).open("rb") as handle:
        while True:
            chunk = handle.read(CHUNK)
            if not chunk:
                break
            digest.update(chunk)
            size += len(chunk)
    return digest.hexdigest(), size


def count_records(path: Path) -> int:
    """Lines for a ``.jsonl`` record stream; one document for a ``.json``."""
    if Path(path).suffix != ".jsonl":
        return 1
    lines = 0
    with Path(path).open("rb") as handle:
        while True:
            chunk = handle.read(CHUNK)
            if not chunk:
                break
            lines += chunk.count(b"\n")
    return lines


def gzip_file(source: Path, target: Path, *, level: int = 6) -> dict[str, Any]:
    """Stream ``source`` into ``target`` (``.gz``) with fsync + atomic rename."""
    temp = target.with_name(target.name + ".tmp")
    digest = hashlib.sha256()
    read = 0
    with Path(source).open("rb") as src, temp.open("wb") as raw:
        with gzip.GzipFile(fileobj=raw, mode="wb", compresslevel=level, mtime=0) as gz:
            while True:
                chunk = src.read(CHUNK)
                if not chunk:
                    break
                digest.update(chunk)
                read += len(chunk)
                gz.write(chunk)
        raw.flush()
        os.fsync(raw.fileno())
    os.replace(temp, target)
    return {"source_sha256": digest.hexdigest(), "source_bytes": read}


def verify_archive(target: Path, *, expected_sha256: str, expected_bytes: int) -> dict[str, Any]:
    """Decompress the archive and re-derive its digest.

    ``gzip`` validates the trailer's CRC-32 and ISIZE while streaming, so a
    truncated or corrupted archive cannot pass this.  Nothing is removed until
    this reports ``PASS``.
    """
    digest = hashlib.sha256()
    size = 0
    lines = 0
    with gzip.open(target, "rb") as handle:
        while True:
            chunk = handle.read(CHUNK)
            if not chunk:
                break
            digest.update(chunk)
            size += len(chunk)
            lines += chunk.count(b"\n")
    ok = digest.hexdigest() == expected_sha256 and size == expected_bytes
    return {
        "status": "PASS" if ok else "MISMATCH",
        "decompressed_sha256": digest.hexdigest(),
        "decompressed_bytes": size,
        "sha256_matches": digest.hexdigest() == expected_sha256,
        "bytes_match": size == expected_bytes,
        "gzip_crc_and_length_validated": True,
        "decompressed_lines": lines,
    }


def migrate_archive(
    *, archive_dir: Path, commit: bool, level: int = 6, manifest_path: Path | None = None
) -> dict[str, Any]:
    archive_dir = Path(archive_dir)
    sources = sorted(
        (
            path
            for path in archive_dir.rglob("*")
            if path.is_file() and not path.name.endswith(".gz") and path.name != MANIFEST_FILENAME
        ),
        key=lambda item: item.stat().st_size,
        reverse=True,
    )
    manifest_path = manifest_path or (archive_dir / MANIFEST_FILENAME)
    entries: list[dict[str, Any]] = []
    blocked: list[str] = []
    reclaimed = 0
    for source in sources:
        target = source.with_name(source.name + ".gz")
        entry: dict[str, Any] = {
            "source": str(source),
            "source_bytes": source.stat().st_size,
            "records": count_records(source),
            "destination": str(target),
            "classification": "DERIVED",
        }
        source_sha, source_bytes = sha256_file(source)
        entry["source_sha256"] = source_sha
        entry["source_bytes"] = source_bytes
        if target.is_file() and target.stat().st_mtime >= source.stat().st_mtime:
            verification = verify_archive(
                target, expected_sha256=source_sha, expected_bytes=source_bytes
            )
            entry["compression"] = {"status": "ALREADY_ARCHIVED", "bytes": target.stat().st_size}
        else:
            compression = gzip_file(source, target, level=level)
            if compression["source_sha256"] != source_sha or compression["source_bytes"] != source_bytes:
                blocked.append(str(source))
                entry["compression"] = {"status": "SOURCE_CHANGED_DURING_COMPRESSION"}
                entries.append(entry)
                continue
            verification = verify_archive(
                target, expected_sha256=source_sha, expected_bytes=source_bytes
            )
            entry["compression"] = {
                "status": "COMPRESSED",
                "bytes": target.stat().st_size,
                **compression,
            }
        entry["archive_bytes"] = target.stat().st_size
        entry["ratio"] = round(source_bytes / max(target.stat().st_size, 1), 2)
        entry["verification"] = verification
        if verification["status"] != "PASS":
            blocked.append(str(source))
        elif commit:
            # Only now, and only after the re-derived digest matched.
            os.remove(source)
            entry["source_removed"] = True
            entry["reclaimed_bytes"] = source_bytes - entry["archive_bytes"]
            reclaimed += entry["reclaimed_bytes"]
        else:
            entry["source_removed"] = False
            entry["reclaimed_bytes"] = 0
        entries.append(entry)
        print(
            f"{'COMMITTED' if entry.get('source_removed') else 'DRY-RUN'} "
            f"{source.name}: {source_bytes / 2**30:.4f} GiB -> "
            f"{entry['archive_bytes'] / 2**20:.2f} MiB (x{entry['ratio']}) "
            f"{verification['status']}",
            flush=True,
        )

    manifest = {
        "migration_version": MIGRATION_VERSION,
        "timestamp": int(time.time()),
        "timestamp_utc": now_iso(),
        "code_commit": git_commit(),
        "mode": "COMMIT" if commit else "DRY_RUN",
        "source_files": [entry["source"] for entry in entries],
        "source_sizes": {entry["source"]: entry["source_bytes"] for entry in entries},
        "source_hashes": {entry["source"]: entry["source_sha256"] for entry in entries},
        "source_records": {entry["source"]: entry["records"] for entry in entries},
        "destination_files": [entry["destination"] for entry in entries],
        "destination_hashes": {
            entry["destination"]: entry["verification"]["decompressed_sha256"] for entry in entries
        },
        "destination_records": {
            entry["destination"]: entry["verification"]["decompressed_lines"] for entry in entries
        },
        "entries": entries,
        "reconciliation": {
            "sources": len(entries),
            "verified": sum(1 for e in entries if e["verification"]["status"] == "PASS"),
            "failed": len(blocked),
            "records_preserved": all(
                e["verification"]["decompressed_lines"] == e["records"]
                or Path(e["source"]).suffix != ".jsonl"
                for e in entries
            ),
            "reclaimed_bytes": reclaimed,
            "reclaimed_gib": round(reclaimed / 2**30, 4),
            "result": "PASS" if not blocked else "BLOCKED",
        },
        "blocked": blocked,
        "note": (
            "Lossless archival of DERIVED report artifacts.  The archive is the "
            "preserved copy; a source file is removed only after its SHA-256 was "
            "re-derived by decompressing the archive in the same run.  Authoritative "
            "ledgers under evidence/ are not part of this migration."
        ),
    }
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    return manifest


def _load_script(name: str) -> Any:
    spec = importlib.util.spec_from_file_location(f"{name}_probe", REPO / "scripts" / f"{name}.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def refresh_scorecard(*, commit: bool) -> dict[str, Any]:
    """Re-run the FROZEN CAP-003 scoring function over the settled ledger.

    The artifact is a projection; CAP-003's own verifier asserts it recomputes
    from the ledger, and it was last written before any of the pilot's decisions
    had matured.  The scoring code is imported, never reimplemented.
    """
    from trading_bot.research import alpha_scorecard as asc
    from trading_bot.research import decision_ledger as dl

    c1 = _load_script("cap001_run")
    campaign = _load_script("cap003_campaign")
    reports = REPO / "reports"
    ledger = dl.DecisionLedger(REPO / "evidence" / "real_decisions")
    scorecard = asc.alpha_scorecard(ledger.rebuilt_evaluations())
    result: dict[str, Any] = {
        "artifact": str(reports / "ALPHA_SCORECARD.json"),
        "n_decisions_evaluated": scorecard["n_decisions_evaluated"],
        "gate": scorecard.get("gate"),
        "before": {},
        "after": {},
        "mode": "COMMIT" if commit else "DRY_RUN",
        "code_commit": git_commit(),
    }
    json_path = reports / "ALPHA_SCORECARD.json"
    md_path = reports / "ALPHA_SCORECARD.md"
    for path in (json_path, md_path):
        result["before"][path.name] = sha256_file(path)[0] if path.is_file() else None
    if commit:
        c1.write_json(json_path, scorecard)
        c1.write_md(md_path, campaign.scorecard_md(scorecard))
    result["after"] = {
        "ALPHA_SCORECARD.json": hashlib.sha256(
            json.dumps(scorecard, indent=2, ensure_ascii=False).encode("utf-8") + b"\n"
        ).hexdigest(),
        "ALPHA_SCORECARD.md": hashlib.sha256(
            campaign.scorecard_md(scorecard).encode("utf-8")
        ).hexdigest(),
    }
    if commit:
        for path in (json_path, md_path):
            result["after"][path.name] = sha256_file(path)[0]
    return result


def disk_free(path: Path) -> dict[str, Any]:
    usage = shutil.disk_usage(Path(path))
    return {
        "free_bytes": int(usage.free),
        "free_gib": round(usage.free / 2**30, 4),
        "total_gib": round(usage.total / 2**30, 4),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="CAP-004C storage migration driver")
    parser.add_argument("--archive-dir", type=Path, default=None)
    parser.add_argument("--manifest", type=Path, default=None)
    parser.add_argument("--refresh-scorecard", action="store_true")
    parser.add_argument("--commit", action="store_true", help="apply; without it, dry run")
    parser.add_argument("--level", type=int, default=6)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    payload: dict[str, Any] = {"before": disk_free(REPO), "started_utc": now_iso()}
    if args.archive_dir is not None:
        payload["archive"] = migrate_archive(
            archive_dir=args.archive_dir,
            commit=args.commit,
            level=args.level,
            manifest_path=args.manifest,
        )
    if args.refresh_scorecard:
        payload["scorecard"] = refresh_scorecard(commit=args.commit)
    payload["after"] = disk_free(REPO)
    payload["freed_gib"] = round(
        (payload["after"]["free_bytes"] - payload["before"]["free_bytes"]) / 2**30, 4
    )
    payload["finished_utc"] = now_iso()
    print(json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) if args.json else "")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
