"""H6 V3 — DATASET DETERMINISM + BTC 2024-06-05 FORENSIC (EXT-DATA-001 companion).

Proves, from the portable shared data root (no repo-local data/ dependency):

1. DATASET_DETERMINISM_A_B : independent full re-normalization A and B into two
   separate TEMP roots -> ledger bytes and recomputed dataset fingerprint
   identical (A == B), and equal to the committed V2 authority fingerprint.
2. DATASET_MUTATION_SENSITIVITY : recomputed fingerprint over a verifier copy
   with ONE normalized file mutated -> differs from A (C != A).
3. BTC_2024_06_05_FORENSIC : raw zip checksum (official sidecar) + byte-identity
   of re-normalization vs canonical V2 normalized file.

Writes durable evidence:
  docs/external-audit-01/oi-full-history-03/DATASET_DETERMINISM_V3_RESULT.json

DATA-ONLY: no signals, no performance, no economics.
Exit 0 iff all three proofs PASS.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
import tempfile
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))

from normalize_oi_full_history_v2 import (  # noqa: E402
    NORMALIZER_VERSION,
    SCHEMA_VERSION,
    SYMBOLS,
    build_v2_dataset,
    process_file_v2,
)

EVID = REPO / "docs" / "external-audit-01" / "oi-full-history-03"
LEDGER_COPY = REPO / "docs/external-audit-01/oi-full-history-02/OI_ARCHIVE_DAY_VALIDITY_LEDGER_V2.jsonl"
MANIFEST_COPY = REPO / "docs/external-audit-01/oi-full-history-02/OI_FULL_HISTORY_DATASET_MANIFEST_V2.json"


def resolve_data_root(cli_root: str | None) -> Path:
    if cli_root:
        return Path(cli_root)
    env = os.environ.get("TRADING_AGENTIC_DATA_ROOT")
    if env:
        return Path(env)
    # shared main-repo data root (never a builder-worktree-only path)
    # REPO is <main>/.worktrees/h6-v3-repair -> main repo is REPO.parents[1]
    main_repo_data = REPO.parents[1] / "data"
    if (main_repo_data / "raw" / "binance_um" / "metrics").is_dir():
        return main_repo_data
    worktree_data = REPO / "data"
    if (worktree_data / "raw" / "binance_um" / "metrics").is_dir():
        return worktree_data
    raise SystemExit(
        "DATA_ROOT_UNRESOLVED: pass --data-root <path> or set TRADING_AGENTIC_DATA_ROOT"
    )


def sha256_file(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def recompute_dataset_fingerprint(
    ledger_path: Path, files_root: Path | None = None
) -> str:
    """Recompute dataset fingerprint committing to ACTUAL canonical file bytes.

    V3 repair of EXT-MANIFEST-HASH-001 companion defect: the V2 dataset
    fingerprint was derived from ledger CLAIMS (normalized_sha256 recorded at
    build time), so mutating a normalized file was undetectable. Here, when
    files_root is given, each VALID entry's normalized_sha256 is recomputed
    from the actual file bytes under files_root/<symbol>/<file>, and the
    per-day fingerprint is re-derived from those actual hashes.
    """
    ledger = [
        json.loads(line)
        for line in ledger_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    for e in ledger:
        if files_root is not None and e.get("classification") == "VALID" and e.get("normalized_path"):
            # normalized_path is a canonical locator:
            # data/processed/oi_full_history_v2/<SYM>/<file>.jsonl
            rel = str(e["normalized_path"]).replace("\\", "/")
            parts = rel.split("/")
            fname = "/".join(parts[-2:])  # <SYM>/<file>
            actual = sha256_file(files_root / fname)
            e["normalized_sha256"] = actual
            payload = json.dumps(
                {
                    "symbol": e["symbol"],
                    "day": e["day"],
                    "raw_source_sha256": e["raw_source_sha256"],
                    "normalized_sha256": actual,
                    "rows": e["rows"],
                    "schema_version": SCHEMA_VERSION,
                    "normalizer_version": NORMALIZER_VERSION,
                },
                sort_keys=True,
                separators=(",", ":"),
            )
            e["dataset_fingerprint"] = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    fp_src = json.dumps(
        {
            "schema_version": SCHEMA_VERSION,
            "normalizer_version": NORMALIZER_VERSION,
            "files": [
                {
                    k: e.get(k)
                    for k in (
                        "symbol",
                        "day",
                        "raw_source_sha256",
                        "normalized_sha256",
                        "rows",
                        "dataset_fingerprint",
                        "classification",
                    )
                }
                for e in sorted(ledger, key=lambda e: (str(e["symbol"]), str(e["day"])))
            ],
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(fp_src.encode("utf-8")).hexdigest()


def main() -> int:
    t0 = time.time()
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--data-root", default=None, help="root containing raw/binance_um/metrics and processed/oi_full_history_v2")
    ap.add_argument(
        "--evidence-dir",
        default=os.environ.get("H6_EVIDENCE_DIR"),
        help="directory for the machine-readable result (default: the historical V3 evidence dir)",
    )
    args = ap.parse_args()
    data_root = resolve_data_root(args.data_root)
    raw = data_root / "raw" / "binance_um" / "metrics"

    out: dict[str, object] = {
        "checkpoint": "H6-V3-REPAIR",
        "proof": "DATASET_DETERMINISM_V3",
        "command": "python scripts/prove_h6_v3_dataset_determinism.py --data-root <path>",
        "commit": os.popen("git rev-parse HEAD").read().strip(),
        "data_root": str(data_root),
        "data_root_source": (
            "TRADING_AGENTIC_DATA_ROOT"
            if os.environ.get("TRADING_AGENTIC_DATA_ROOT")
            else ("--data-root" if args.data_root else "shared_main_repo_data")
        ),
        "environment": {"python": sys.version.split()[0], "platform": sys.platform},
        "started_utc": datetime.now(timezone.utc).isoformat(),
    }
    print(f"[1/3] Independent A/B re-normalization from {data_root} ...", flush=True)

    tmp = Path(tempfile.mkdtemp(prefix="h6v3_det_"))
    out["temp_root"] = str(tmp)
    norm_a = tmp / "A"
    norm_b = tmp / "B"

    ledger_a, _manifest_a = build_v2_dataset(out_dir=norm_a, raw_dir=raw)
    ledger_b, _manifest_b = build_v2_dataset(out_dir=norm_b, raw_dir=raw)

    ledger_a_bytes = (norm_a / "OI_ARCHIVE_DAY_VALIDITY_LEDGER_V2.jsonl").read_bytes()
    ledger_b_bytes = (norm_b / "OI_ARCHIVE_DAY_VALIDITY_LEDGER_V2.jsonl").read_bytes()
    # Fingerprint recomputed from ACTUAL normalized bytes in each run root
    fp_a = recompute_dataset_fingerprint(
        norm_a / "OI_ARCHIVE_DAY_VALIDITY_LEDGER_V2.jsonl", files_root=norm_a
    )
    fp_b = recompute_dataset_fingerprint(
        norm_b / "OI_ARCHIVE_DAY_VALIDITY_LEDGER_V2.jsonl", files_root=norm_b
    )
    committed_fp = json.loads(MANIFEST_COPY.read_text(encoding="utf-8"))[
        "OI_FULL_HISTORY_DATASET_SHA256_V2"
    ]
    # Canonical authority fingerprint recomputed from actual canonical bytes
    fp_canonical = recompute_dataset_fingerprint(
        LEDGER_COPY, files_root=data_root / "processed" / "oi_full_history_v2"
    )

    out["determinism"] = {
        "method": "independent full re-normalization A and B from shared raw authority into separate TEMP roots",
        "files_normalized_per_run": len(ledger_a),
        "raw_counts": {s: len(list((raw / s).glob("*.zip"))) for s in SYMBOLS},
        "ledger_bytes_A_equals_B": ledger_a_bytes == ledger_b_bytes,
        "fingerprint_A": fp_a,
        "fingerprint_B": fp_b,
        "committed_authority_fingerprint": committed_fp,
        "canonical_bytes_fingerprint": fp_canonical,
        "fingerprint_A_equals_B": fp_a == fp_b,
        "fingerprint_A_equals_committed": fp_a == committed_fp,
        "fingerprint_commits_to_actual_bytes": fp_canonical == committed_fp,
        "determinism_status": "PASS" if (fp_a == fp_b == committed_fp and ledger_a_bytes == ledger_b_bytes) else "FAIL",
    }

    print("[2/3] Mutation sensitivity (verifier TEMP copy, one normalized file mutated)...", flush=True)
    mut_root = tmp / "C"
    shutil.copytree(norm_a, mut_root)
    target = mut_root / "BTCUSDT" / "BTCUSDT-oi-5m-2024-06-05.jsonl"
    orig_len = target.stat().st_size
    mutated = bytearray(orig_len)
    mutated[:16] = b"XX_MUTATED_XX__"  # 16 bytes, same total length
    target.write_bytes(bytes(mutated))
    fp_c = recompute_dataset_fingerprint(
        mut_root / "OI_ARCHIVE_DAY_VALIDITY_LEDGER_V2.jsonl", files_root=mut_root
    )
    out["mutation_sensitivity"] = {
        "mutated_file": "BTCUSDT/BTCUSDT-oi-5m-2024-06-05.jsonl (first 16 bytes overwritten, same length)",
        "fingerprint_C": fp_c,
        "fingerprint_C_differs_from_A": fp_c != fp_a,
        "mutation_status": "PASS" if fp_c != fp_a else "FAIL",
        "real_raw_files_modified": False,
        "canonical_authority_modified": False,
        "note": "mutation applied to verifier TEMP copy only",
    }

    print("[3/3] BTC 2024-06-05 forensic (official raw -> normalize -> compare canonical)...", flush=True)
    day = "2024-06-05"
    zip_path = raw / "BTCUSDT" / f"BTCUSDT-metrics-{day}.zip"
    sidecar = Path(str(zip_path) + ".CHECKSUM")
    expected_checksum = sidecar.read_text(encoding="utf-8", errors="replace").strip().split()[0]
    actual_sha = sha256_file(zip_path)
    forensic_root = tmp / "forensic"
    entry = process_file_v2("BTCUSDT", day, raw_dir=raw, out_dir=forensic_root)
    canonical_norm = data_root / "processed" / "oi_full_history_v2" / "BTCUSDT" / f"BTCUSDT-oi-5m-{day}.jsonl"
    canonical_sha = sha256_file(canonical_norm)
    out["btc_2024_06_05_forensic"] = {
        "raw_zip": str(zip_path),
        "official_checksum_expected": expected_checksum,
        "raw_sha256_actual": actual_sha,
        "official_checksum_match": actual_sha == expected_checksum,
        "renormalized_entry_classification": entry.get("classification"),
        "renormalized_normalized_sha256": entry.get("normalized_sha256"),
        "canonical_normalized_sha256": canonical_sha,
        "byte_identical": entry.get("normalized_sha256") == canonical_sha,
        "forensic_status": "PASS" if (actual_sha == expected_checksum and entry.get("normalized_sha256") == canonical_sha) else "FAIL",
        "v1_contamination_mechanism": "V1 dataset wrote into the shared canonical root without per-file provenance; BTC 2024-06-05 normalized content diverged from official raw",
        "v2_clean_authority": "V2 refreeze wrote to dedicated oi_full_history_v2 root with per-file raw/normalized sha256 provenance",
        "v3_portable_verification_path": "any verifier resolves --data-root, re-normalizes the day from the official sidecar-checked zip, compares byte-identity vs committed canonical",
    }

    det_ok = out["determinism"]["determinism_status"] == "PASS"  # type: ignore[index]
    mut_ok = out["mutation_sensitivity"]["mutation_status"] == "PASS"  # type: ignore[index]
    fore_ok = out["btc_2024_06_05_forensic"]["forensic_status"] == "PASS"  # type: ignore[index]
    out["status"] = "PASS" if (det_ok and mut_ok and fore_ok) else "FAIL"
    out["duration_seconds"] = round(time.time() - t0, 1)
    out["ended_utc"] = datetime.now(timezone.utc).isoformat()
    out["exit_code"] = 0 if out["status"] == "PASS" else 1

    evidence_dir = Path(args.evidence_dir) if args.evidence_dir else EVID
    if not evidence_dir.is_absolute():
        evidence_dir = REPO / evidence_dir
    evidence_dir.mkdir(parents=True, exist_ok=True)
    (evidence_dir / "DATASET_DETERMINISM_V3_RESULT.json").write_text(
        json.dumps(out, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps({"status": out["status"], "duration_seconds": out["duration_seconds"]}, indent=2))
    return 0 if out["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
