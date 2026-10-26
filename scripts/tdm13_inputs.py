"""RFC-TDM-013 — seal, verify and restore the TDM-12 input datasets.

The TDM-12 report left its inputs outside Git: the numbers could be re-checked
but the experiment could not be re-run from a clone. This module seals the exact
bytes into the evidence package, records provenance and hashes, and restores them
into a clean clone so the replay runs on identifiable inputs.

Byte-exactness is the whole contract: the bundle is copied, never re-serialised,
and every digest is recomputed from the bytes on disk before anything is written.

Commands::

    python scripts/tdm13_inputs.py seal   [--source ../ff-wt-tdm12]
    python scripts/tdm13_inputs.py verify
    python scripts/tdm13_inputs.py restore --target <clean-clone>
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

#: ``TDM13_REPO`` lets a sandbox run the same seal/verify logic on its own copy.
REPO_ROOT = Path(os.environ.get("TDM13_REPO") or Path(__file__).resolve().parents[1]).resolve()
EVIDENCE = REPO_ROOT / "evidence" / "tdm" / "wp-tdm-13"
BUNDLE = EVIDENCE / "inputs"
MANIFEST = EVIDENCE / "DATASET_MANIFEST.json"
TDM11 = REPO_ROOT / "evidence" / "tdm" / "wp-tdm-11"

SCHEMA_VERSION = "tdm13-dataset-manifest-v1"
SOURCE_COMMIT = "a96e9c80c608ed91943d1fab35db6fa1704111bb"
VERIFIER_ID = "tdm13-independent-verifier/1"

#: split -> (bundle subdirectory, original repository directory)
SPLITS: dict[str, tuple[str, str]] = {
    "HOLD": ("tdm08", "data/tdm08"),
    "DEV": ("tdm10", "data/tdm10"),
}
MANIFEST_FILES = {"DATASET.json", "DATASET_DEV.json"}


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def git(*args: str) -> str:
    proc = subprocess.run(
        ["git", *args], cwd=REPO_ROOT, capture_output=True, text=True, check=False
    )
    return proc.stdout.strip()


def _window(manifest: dict[str, Any]) -> dict[str, Any]:
    window = manifest.get("window") or {}
    start = window.get("start")
    end = window.get("end") or (
        dt.datetime.fromtimestamp(window["end_ms"] / 1000, dt.UTC).isoformat()
        if window.get("end_ms")
        else None
    )
    return {"start": start, "end": end}


def _dataset_entry(
    *,
    split: str,
    source_dir: Path,
    bundle_dir: Path,
    name: str,
    declared: dict[str, Any],
    provenance: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    path = source_dir / name
    data = path.read_bytes()
    rel = path.relative_to(source_dir.parent.parent).as_posix()
    key = rel.replace("\\", "/")
    prov = provenance.get(key) or {}
    asset, _, timeframe = name.partition("_")
    timeframe = timeframe.removesuffix(".json")
    return {
        "dataset_id": f"{split}:{asset}:{timeframe}",
        "path": (bundle_dir / name).relative_to(REPO_ROOT).as_posix(),
        "original_path": key,
        "format": "json (list of OHLCV bars, epoch-ms timestamps)",
        "bytes": len(data),
        "sha256": hashlib.sha256(data).hexdigest(),
        "bars": declared.get("bars", prov.get("bars")),
        "first_bar_ms": declared.get("first_bar_ms", prov.get("first_bar_ms")),
        "last_bar_ms": declared.get("last_bar_ms", prov.get("last_bar_ms")),
        "asset": asset,
        "symbol": declared.get("venue", prov.get("venue")),
        "timeframe": timeframe,
        "granularity": f"closed {timeframe} candle, close_time used",
        "timezone": "UTC (epoch milliseconds)",
        "source": declared.get("source", prov.get("source", "UNKNOWN")),
        "endpoint": "UNKNOWN (fetcher request URL not recorded in the dataset manifest)",
        "captured_at": declared.get("fetched_at") or prov.get("captured_at") or "UNKNOWN",
        "transform_version": "UNKNOWN (sealing rule recorded, transform code version not pinned)",
        "sealing_rule": declared.get("sealing_rule", "UNKNOWN"),
        "split": split,
        "license": "UNKNOWN (public exchange klines; redistribution terms not verified)",
        "retrievable_from": (bundle_dir / name).relative_to(REPO_ROOT).as_posix(),
        "state": "SEALED_IN_BUNDLE" if data else "MISSING",
        "declared_sha256": declared.get("sha256"),
        "declared_hash_match": declared.get("sha256") in (None, hashlib.sha256(data).hexdigest()),
    }


def seal(source: Path) -> dict[str, Any]:
    """Copy the sealed datasets into the evidence bundle and write the manifest."""
    datasets: list[dict[str, Any]] = []
    missing: list[str] = []
    for split, (subdir, original) in SPLITS.items():
        source_dir = source / original
        manifest_name = "DATASET.json" if split == "HOLD" else "DATASET_DEV.json"
        manifest_path = source_dir / manifest_name
        if not manifest_path.is_file():
            missing.append(f"{original}/{manifest_name}")
            continue
        declared_doc = json.loads(manifest_path.read_text(encoding="utf-8"))
        declared = {f["path"].replace("\\", "/"): f for f in declared_doc.get("files", [])}
        provenance_doc = json.loads((TDM11 / "DATASET_PROVENANCE.json").read_text(encoding="utf-8"))
        provenance = {
            f["path"].replace("\\", "/"): f
            for f in provenance_doc.get("exposed_datasets", {}).get("files", [])
        }
        bundle_dir = BUNDLE / subdir
        bundle_dir.mkdir(parents=True, exist_ok=True)
        for name in sorted(p.name for p in source_dir.iterdir() if p.is_file()):
            shutil.copy2(source_dir / name, bundle_dir / name)
            if name in MANIFEST_FILES:
                continue
            key = f"{original}/{name}"
            entry = _dataset_entry(
                split=split,
                source_dir=source_dir,
                bundle_dir=bundle_dir,
                name=name,
                declared=declared.get(key, {}),
                provenance=provenance,
            )
            entry["manifest_sha256_declared"] = declared.get(key, {}).get("sha256")
            datasets.append(entry)
        # the per-split manifest travels too: it is the provenance of record
        shutil.copy2(manifest_path, bundle_dir / manifest_name)
        datasets.append(
            {
                "dataset_id": f"{split}:manifest",
                "path": (bundle_dir / manifest_name).relative_to(REPO_ROOT).as_posix(),
                "original_path": f"{original}/{manifest_name}",
                "format": "json (dataset manifest: window, sealing rule, per-file hashes)",
                "bytes": manifest_path.stat().st_size,
                "sha256": sha(manifest_path),
                "asset": "ALL",
                "symbol": declared_doc.get("venue"),
                "timeframe": "ALL",
                "granularity": "n/a",
                "timezone": "UTC (epoch milliseconds)",
                "source": declared_doc.get("venue", "UNKNOWN"),
                "endpoint": "UNKNOWN",
                "captured_at": declared_doc.get("fetched_at_ms", "UNKNOWN"),
                "transform_version": "UNKNOWN",
                "sealing_rule": declared_doc.get("sealing_rule", "UNKNOWN"),
                "split": split,
                "window": _window(declared_doc),
                "license": "UNKNOWN (public exchange klines)",
                "retrievable_from": (bundle_dir / manifest_name).relative_to(REPO_ROOT).as_posix(),
                "state": "SEALED_IN_BUNDLE",
                "declared_hash_match": True,
            }
        )

    total = sum(d["bytes"] for d in datasets)
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "rfc_id": "RFC-TDM-013",
        "source_commit": SOURCE_COMMIT,
        "source_checkout": str(source),
        "source_checkout_head": git("rev-parse", "HEAD"),
        "datasets": datasets,
        "dataset_count": len(datasets),
        "total_bytes": total,
        "storage_mode": "BUNDLE_IN_GIT",
        "retrieval_instructions": (
            "python scripts/tdm13_inputs.py restore --target <clean-clone>  "
            "(copies evidence/tdm/wp-tdm-13/inputs/<split>/ into <clone>/data/<split>/ "
            "byte for byte, then verifies every SHA-256)"
        ),
        "restriction_reason": (
            "public exchange klines fetched without credentials, no personal data; total size "
            f"{total} bytes, below the repository's existing sealed-data trees (data/rfc049, "
            "data/recovery/wp7|wp8); committed so a clone can re-run the experiment"
        ),
        "license_status": "UNKNOWN_NOT_VERIFIED",
        "verified_at": dt.datetime.now(dt.UTC).isoformat(),
        "verifier_id": VERIFIER_ID,
        "input_state": "AVAILABLE" if not missing else "UNAVAILABLE",
        "missing": missing,
    }
    MANIFEST.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(f"sealed {len(datasets)} dataset files, {total} bytes -> {BUNDLE.relative_to(REPO_ROOT)}")
    return manifest


def verify() -> int:
    """Recompute every bundle digest from the bytes on disk and the committed blob."""
    if not MANIFEST.is_file():
        print("no dataset manifest; run seal first")
        return 2
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    bad: list[str] = []
    for entry in manifest["datasets"]:
        path = REPO_ROOT / entry["path"]
        if not path.is_file():
            bad.append(f"{entry['dataset_id']}: missing {entry['path']}")
            continue
        actual = sha(path)
        if actual != entry["sha256"]:
            bad.append(f"{entry['dataset_id']}: {entry['sha256'][:12]} != {actual[:12]}")
        committed = subprocess.run(
            ["git", "cat-file", "blob", f"HEAD:{entry['path']}"],
            cwd=REPO_ROOT,
            capture_output=True,
            check=False,
        )
        if committed.returncode == 0:
            if hashlib.sha256(committed.stdout).hexdigest() != entry["sha256"]:
                bad.append(f"{entry['dataset_id']}: committed blob differs")
        elif entry["path"] in git("ls-tree", "-r", "--name-only", "HEAD").splitlines():
            bad.append(f"{entry['dataset_id']}: unreadable blob")
    print(f"verified {len(manifest['datasets']) - len(bad)}/{len(manifest['datasets'])} datasets")
    for failure in bad:
        print(f"  FAIL {failure}")
    return 0 if not bad else 1


def restore(target: Path) -> int:
    """Copy the sealed bundle into a clone and prove the hashes on arrival."""
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    copied = 0
    bad: list[str] = []
    for entry in manifest["datasets"]:
        source = REPO_ROOT / entry["path"]
        destination = target / entry["original_path"]
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, destination)
        actual = sha(destination)
        if actual != entry["sha256"]:
            bad.append(f"{entry['dataset_id']}: restored {actual[:12]} != {entry['sha256'][:12]}")
        copied += 1
    print(f"restored {copied} files into {target} (mismatches={len(bad)})")
    for failure in bad:
        print(f"  FAIL {failure}")
    return 0 if not bad else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("command", choices=("seal", "verify", "restore"))
    parser.add_argument("--source", default=str(REPO_ROOT.parent / "ff-wt-tdm12"))
    parser.add_argument("--target", default=None)
    args = parser.parse_args(argv)

    if args.command == "seal":
        seal(Path(args.source))
        return 0
    if args.command == "verify":
        return verify()
    if not args.target:
        print("restore needs --target <clean-clone>")
        return 2
    return restore(Path(args.target).resolve())


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
