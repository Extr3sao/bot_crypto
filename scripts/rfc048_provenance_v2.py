"""Generate RFC-048 provenance **version 2** without touching version 1.

Why this exists
---------------
``data/rfc048/PROVENANCE.json`` records digests that do not match the bytes the
repository stores: the payload was hashed on a Windows working tree with CRLF and
then committed with LF, so ``sha256(file_as_delivered) != recorded`` for every JSON
source. ``INSTRUMENTS.json`` inherited the same digests in ``source_hash`` and
``source_hash_brackets``.

What this script does
---------------------
1. proves the diagnosis: for every source it recomputes the digest over the bytes
   on disk and over the CRLF-transformed bytes, and records which one v1 used;
2. writes a **new, versioned** provenance that pins the bytes as delivered
   (``data/rfc048/provenance/PROVENANCE@v2.json``);
3. writes ``INSTRUMENTS@v2.json`` — a copy of v1 whose two digest fields carry the
   values for the bytes in the repository;
4. leaves ``PROVENANCE.json``, ``INSTRUMENTS.json`` and every raw payload
   untouched, and pins their hashes so the originals stay auditable.

Run from the repository root:

    PYTHONPATH=src python scripts/rfc048_provenance_v2.py --check   # diagnosis only
    PYTHONPATH=src python scripts/rfc048_provenance_v2.py --write   # emit v2
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
DATA = REPO_ROOT / "data" / "rfc048"
OUT = DATA / "provenance"
HERE = Path(__file__).resolve()
SCHEMA = "rfc048-provenance-v2"

#: ``INSTRUMENTS.json`` field -> PROVENANCE source key it must equal.
INSTRUMENT_HASH_FIELDS = {
    "source_hash": "exchange_info",
    "source_hash_brackets": "leverage_brackets",
}


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def crlf(payload: bytes) -> bytes:
    return payload.replace(b"\r\n", b"\n").replace(b"\n", b"\r\n")


def git_blob(path: Path) -> bytes | None:
    rel = path.relative_to(REPO_ROOT).as_posix()
    proc = subprocess.run(
        ["git", "cat-file", "blob", f"HEAD:{rel}"],
        cwd=REPO_ROOT,
        capture_output=True,
        check=False,
    )
    return proc.stdout if proc.returncode == 0 else None


def diagnose() -> dict[str, Any]:
    provenance = json.loads((DATA / "PROVENANCE.json").read_text(encoding="utf-8"))
    sources: dict[str, Any] = {}
    unexplained: list[str] = []
    for key, entry in provenance["sources"].items():
        path = REPO_ROOT / entry["file"]
        payload = path.read_bytes()
        as_stored = sha256_bytes(payload)
        as_crlf = sha256_bytes(crlf(payload))
        blob = git_blob(path)
        recorded = entry["sha256"]
        if recorded == as_crlf and as_crlf != as_stored:
            relation = "crlf_normalized"
        elif recorded == as_stored:
            relation = "as_stored"
        else:
            relation = "UNEXPLAINED"
            unexplained.append(key)
        sources[key] = {
            "url": entry.get("url"),
            "file": entry["file"],
            "v1_sha256": recorded,
            "v1_bytes": entry.get("bytes"),
            "as_stored_sha256": as_stored,
            "as_stored_bytes": len(payload),
            "as_crlf_sha256": as_crlf,
            "git_blob_sha256": sha256_bytes(blob) if blob is not None else None,
            "git_blob_matches_worktree": blob == payload if blob is not None else None,
            "relation": relation,
        }
    return {
        "provenance_v1_sha256": sha256_file(DATA / "PROVENANCE.json"),
        "instruments_v1_sha256": sha256_file(DATA / "INSTRUMENTS.json"),
        "sources": sources,
        "unexplained": unexplained,
        "relation_counts": {
            relation: sum(1 for s in sources.values() if s["relation"] == relation)
            for relation in ("as_stored", "crlf_normalized", "UNEXPLAINED")
        },
    }


def build_provenance_v2(diagnosis: dict[str, Any]) -> dict[str, Any]:
    provenance_v1 = json.loads((DATA / "PROVENANCE.json").read_text(encoding="utf-8"))
    sources = {}
    for key, row in diagnosis["sources"].items():
        sources[key] = {
            "url": row["url"],
            "file": row["file"],
            "sha256": row["as_stored_sha256"],
            "bytes": row["as_stored_bytes"],
            "v1_sha256": row["v1_sha256"],
            "v1_bytes": row["v1_bytes"],
            "v1_relation": row["relation"],
        }
    return {
        "schema_version": SCHEMA,
        "generated_at_utc": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "generated_by": "scripts/rfc048_provenance_v2.py",
        "representation": (
            "sha256 over the bytes the repository stores and delivers (LF, no "
            "end-of-line normalisation). data/rfc048/** is marked -text in "
            ".gitattributes so a checkout cannot rewrite them."
        ),
        "defect_in_v1": {
            "summary": (
                "v1 digests were computed on a Windows working tree before the "
                "commit normalised the payload to LF, so they describe a byte "
                "sequence the repository never stores."
            ),
            "evidence": (
                "For every JSON source, v1_sha256 == sha256(LF bytes with \\n -> \\r\\n) "
                "and as_stored != v1; the byte delta equals the number of lines. "
                "esma_statement.html is unaffected because it was stored verbatim."
            ),
            "relation_counts": diagnosis["relation_counts"],
            "unexplained": diagnosis["unexplained"],
        },
        "supersedes": {
            "file": "data/rfc048/PROVENANCE.json",
            "sha256": diagnosis["provenance_v1_sha256"],
            "preserved": True,
            "note": "v1 is kept byte-identical for historical audit; it is not authoritative.",
        },
        "sources": sources,
        "derived": provenance_v1.get("derived", {}),
    }


def build_instruments_v2(diagnosis: dict[str, Any]) -> dict[str, Any]:
    instruments_v1 = json.loads((DATA / "INSTRUMENTS.json").read_text(encoding="utf-8"))
    payload = json.loads(json.dumps(instruments_v1))  # deep copy, v1 stays on disk
    for row in payload["instruments"]:
        for field, source_key in INSTRUMENT_HASH_FIELDS.items():
            if field in row:
                row[field] = diagnosis["sources"][source_key]["as_stored_sha256"]
    payload["provenance"] = {
        "schema_version": SCHEMA,
        "supersedes": {
            "file": "data/rfc048/INSTRUMENTS.json",
            "sha256": diagnosis["instruments_v1_sha256"],
            "preserved": True,
        },
        "digest_representation": "bytes as stored by the repository (LF)",
        "source_digests": {
            field: diagnosis["sources"][source_key]["as_stored_sha256"]
            for field, source_key in INSTRUMENT_HASH_FIELDS.items()
        },
        "note": (
            "Only source_hash and source_hash_brackets differ from v1; every other "
            "field is byte-identical JSON."
        ),
    }
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true", help="diagnose only, write nothing")
    mode.add_argument("--write", action="store_true", help="emit the v2 artifacts")
    args = parser.parse_args()

    diagnosis = diagnose()
    counts = diagnosis["relation_counts"]
    print(json.dumps({"relation_counts": counts, "unexplained": diagnosis["unexplained"]}, indent=2))
    if diagnosis["unexplained"]:
        print("[rfc048] refusing to version a provenance whose drift is unexplained")
        return 2
    if args.check:
        (REPO_ROOT / ".tmp").mkdir(exist_ok=True)
        (REPO_ROOT / ".tmp" / "rfc048-provenance-diagnosis.json").write_text(
            json.dumps(diagnosis, indent=2) + "\n", encoding="utf-8"
        )
        return 0

    OUT.mkdir(parents=True, exist_ok=True)
    provenance_v2 = build_provenance_v2(diagnosis)
    instruments_v2 = build_instruments_v2(diagnosis)
    (OUT / "PROVENANCE@v2.json").write_text(
        json.dumps(provenance_v2, indent=2) + "\n", encoding="utf-8"
    )
    (OUT / "INSTRUMENTS@v2.json").write_text(
        json.dumps(instruments_v2, indent=2) + "\n", encoding="utf-8"
    )
    manifest = {
        "schema_version": SCHEMA,
        "generator": {
            "path": HERE.relative_to(REPO_ROOT).as_posix(),
            "sha256": sha256_file(HERE),
        },
        "inputs": {
            "PROVENANCE.json": diagnosis["provenance_v1_sha256"],
            "INSTRUMENTS.json": diagnosis["instruments_v1_sha256"],
        },
        "outputs": {
            "provenance/PROVENANCE@v2.json": sha256_file(OUT / "PROVENANCE@v2.json"),
            "provenance/INSTRUMENTS@v2.json": sha256_file(OUT / "INSTRUMENTS@v2.json"),
        },
        "v1_untouched": True,
        "regenerate_with": "PYTHONPATH=src python scripts/rfc048_provenance_v2.py --write",
    }
    (OUT / "GENERATION.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(manifest, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
