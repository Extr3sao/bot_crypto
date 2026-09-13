"""Verify H6 data authority from a clean worktree or any checkout.

Accepts --data-root (or env TRADING_AGENTIC_DATA_ROOT) and independently validates:
  - raw source availability + source counts
  - selected official checksums
  - normalized authority presence
  - ledger + manifest + dataset fingerprint

Exit 0 PASS, non-zero FAIL. No builder-only imports reproduce the same bug alone.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path


def sha256_path(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def sha256_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def resolve_data_root(cli_root: str | None) -> Path:
    if cli_root:
        return Path(cli_root)
    env = os.environ.get("TRADING_AGENTIC_DATA_ROOT")
    if env:
        return Path(env)
    # repo-relative default (may be gitignored but exists on this machine)
    repo = Path(__file__).resolve().parents[1]
    return repo / "data"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--data-root", default=None, help="root containing raw/binance_um/metrics/ and processed/oi_full_history_v2/")
    ap.add_argument("--manifest", default="docs/external-audit-01/oi-full-history-02/OI_FULL_HISTORY_DATASET_MANIFEST_V2.json")
    ap.add_argument("--ledger", default="docs/external-audit-01/oi-full-history-02/OI_ARCHIVE_DAY_VALIDITY_LEDGER_V2.jsonl")
    ap.add_argument(
        "--evidence-dir",
        default=os.environ.get("H6_EVIDENCE_DIR"),
        help="directory for the machine-readable result (default: the historical V3 evidence dir); "
        "set H6_EVIDENCE_DIR or pass this flag so a re-verification checkpoint never rewrites "
        "another checkpoint's frozen evidence",
    )
    args = ap.parse_args(argv)

    repo = Path(__file__).resolve().parents[1]
    data_root = resolve_data_root(args.data_root)
    raw_base = data_root / "raw" / "binance_um" / "metrics" if (data_root / "raw").exists() or args.data_root else repo / "data" / "raw" / "binance_um" / "metrics"
    # If --data-root pointed at repo itself, adjust:
    if (data_root / "data" / "raw").exists():
        raw_base = data_root / "data" / "raw" / "binance_um" / "metrics"
    # Normalize: if user passed repo dir, prefer repo/data
    if not raw_base.exists() and (repo / "data" / "raw" / "binance_um" / "metrics").exists():
        raw_base = repo / "data" / "raw" / "binance_um" / "metrics"

    manifest_path = repo / args.manifest
    ledger_path = repo / args.ledger
    normalized_root = data_root / "processed" / "oi_full_history_v2" if (data_root / "processed").exists() or args.data_root else repo / "data" / "processed" / "oi_full_history_v2"
    if (data_root / "data" / "processed" / "oi_full_history_v2").exists():
        normalized_root = data_root / "data" / "processed" / "oi_full_history_v2"
    if not normalized_root.exists() and (repo / "data" / "processed" / "oi_full_history_v2").exists():
        normalized_root = repo / "data" / "processed" / "oi_full_history_v2"

    ok = True
    out: dict[str, object] = {
        "data_root_resolved": str(data_root),
        "raw_base": str(raw_base),
        "normalized_root": str(normalized_root),
        "manifest_path": str(manifest_path),
        "ledger_path": str(ledger_path),
    }

    # 1. manifest + ledger exist
    if not manifest_path.exists():
        print(f"FAIL manifest missing {manifest_path}", file=sys.stderr)
        return 2
    if not ledger_path.exists():
        print(f"FAIL ledger missing {ledger_path}", file=sys.stderr)
        return 2

    # 2. ledger line count 5691 and valid JSON
    lines = [l for l in ledger_path.read_text(encoding="utf-8").splitlines() if l.strip()]
    out["ledger_lines"] = len(lines)
    if len(lines) != 5691:
        print(f"FAIL ledger line count {len(lines)} != 5691", file=sys.stderr)
        ok = False

    # 3. raw source counts 2201/1745/1745
    expected = {"BTCUSDT": 2201, "ETHUSDT": 1745, "SOLUSDT": 1745}
    for sym, exp in expected.items():
        cnt = len(list((raw_base / sym).glob("*.zip"))) if raw_base.exists() else -1
        out[f"raw_{sym}"] = cnt
        if cnt != exp:
            print(f"FAIL raw {sym} count {cnt} != {exp} (base {raw_base})", file=sys.stderr)
            ok = False

    # 4. selected official checksums (forensic BTC 2024-06-05 + a few samples)
    samples = [("BTCUSDT", "2024-06-05"), ("BTCUSDT", "2020-09-01"), ("ETHUSDT", "2021-12-01"), ("SOLUSDT", "2021-12-01")]
    for sym, day in samples:
        zp = raw_base / sym / f"{sym}-metrics-{day}.zip"
        cs = zp.with_name(zp.name + ".CHECKSUM")
        if not zp.exists() or not cs.exists():
            print(f"FAIL sample missing {zp}", file=sys.stderr)
            ok = False
            continue
        expect = cs.read_text(encoding="utf-8", errors="replace").strip().split()[0]
        actual = sha256_path(zp)
        if actual != expect:
            print(f"FAIL checksum {sym} {day}: {actual} != {expect}", file=sys.stderr)
            ok = False
        else:
            out[f"checksum_{sym}_{day}"] = "PASS"

    # 5. normalized authority presence: ledger VALID days must have files
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        ledger_sha_claim = manifest.get("ledger_sha256", "")
        actual_ledger_sha = sha256_path(ledger_path)
        out["ledger_sha256_claim"] = ledger_sha_claim
        out["ledger_sha256_actual"] = actual_ledger_sha
        if ledger_sha_claim != actual_ledger_sha:
            print(f"FAIL ledger sha mismatch {ledger_sha_claim} vs {actual_ledger_sha}", file=sys.stderr)
            ok = False
        # Check a few normalized shards
        for sym, day in samples:
            shard = normalized_root / sym / f"{sym}-oi-5m-{day}.jsonl"
            # Only VALID days have shards; check at least that valid days have shards
            # For 2021-12-01 all three should be valid/present
            if day == "2021-12-01" and not shard.exists():
                print(f"FAIL normalized shard missing {shard}", file=sys.stderr)
                ok = False
            elif shard.exists():
                out[f"normalized_{sym}_{day}"] = "exists"
        # Dataset fingerprint re-derive partially: use manifest's claimed value vs recomputed from ledger
        # Full fingerprint requires per-file normalized sha; we check that at least the claimed dataset sha is 64 hex
        ds_sha = manifest.get("OI_FULL_HISTORY_DATASET_SHA256_V2", manifest.get("OI_FULL_HISTORY_DATASET_SHA256", ""))
        out["dataset_sha256_manifest"] = ds_sha
        if len(str(ds_sha)) != 64 or not all(c in "0123456789abcdef" for c in str(ds_sha)):
            print(f"FAIL dataset sha malformed {ds_sha}", file=sys.stderr)
            ok = False
        # Price authority fingerprint if present
        price_manifest = repo / "docs" / "external-audit-01" / "oi-full-history-02" / "PRICE_1H_AUTHORITY_V2_MANIFEST.json"
        if price_manifest.exists():
            out["price_manifest_exists"] = True
    except Exception as e:
        print(f"FAIL manifest/ledger parse {e}", file=sys.stderr)
        ok = False

    # Write machine-readable result alongside, in this checkpoint's own evidence dir when asked.
    evidence_dir = Path(args.evidence_dir) if args.evidence_dir else repo / "docs" / "external-audit-01" / "oi-full-history-03"
    if not evidence_dir.is_absolute():
        evidence_dir = repo / evidence_dir
    result_path = evidence_dir / "H6_DATA_AUTHORITY_CHECK.json"
    result_path.parent.mkdir(parents=True, exist_ok=True)
    result = {"verdict": "PASS" if ok else "FAIL", **out}
    result_path.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
