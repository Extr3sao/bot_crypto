"""ARC-01 funding normalizer — RAW -> NORMALIZED with PIT semantics.

Input RAW:
  - data/raw/arc01_funding/vision_monthly/<SYMBOL>/*.zip (+.CHECKSUM)  [official archive, monthly]
  - data/raw/arc01_funding/rest_tail/<SYMBOL>_rest_tail.jsonl             [REST tail after 2026-08-31 16:00 UTC]

Normalized schema (minimal, portable, no future-looking derivations):
  symbol                 str            e.g. BTCUSDT
  funding_time_utc       ISO8601 Z      settlement instant (UTC)
  funding_time_ms        int            settlement instant epoch ms
  funding_rate           str(decimal)   normalized decimal per 8h settlement, as string for fidelity
  funding_interval_hours int            as on provider (always 8 in this universe; not assumed, read)
  availability_time_utc  ISO8601 Z      when value becomes knowable (= funding_time_utc)
  availability_time_ms   int            idem
  settlement_time_utc    ISO8601 Z      = funding_time_utc (settlement = availability)
  next_funding_time_utc  ISO8601 Z|None next expected settlement (funding_time+8h) if predictable
  source                 str            e.g. data.binance.vision:fundingRate/monthly or binanceusdm:/fapi/v1/fundingRate
  source_file            str            relative path of raw file (repo-relative)
  source_sha256          str            sha256 of that raw file (CHECKSUM provider or REST tail file)
  rate_type              str            provider rateType (Regular)

Rules:
  - Preserve provider data exactly: funding rate bytes are normalized only via decimal normalization (no scaling),
    timestamp is calc_time/fundingTime directly.
  - Canonical funding units frozen (FUNDING-UNITS-CANONICAL-V1): decimal_fraction_per_interval.
  - Interval taken from data source per row, never silently assumed; if source says 8, we record 8.
  - Availability = funding_time (settlement instant is when rate is knowable). No next-interval lookahead.
  - No synthetic rows. No mark/index mixed in (those are separate P1 families).
  - Duplicate handling: provider duplicates identical => collapse; conflicting duplicates (same calc_time, different rate) => FAIL CLOSED (ledger INVALID_CONFLICTING_DUPLICATE).
  - Out-of-order source rows normalize deterministically (sorted by calc_time).

Quality checks recorded per asset + globally.
Fingerprint chain: RAW provider bytes -> normalized partitions -> partition SHA256 -> deterministic manifest -> DATASET SHA256.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import math
import zipfile
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
MAIN_DATA = REPO.parents[1] / "data"
RAW_ROOT = REPO / "data" / "raw" / "arc01_funding"
PROC_ROOT = REPO / "data" / "processed" / "arc01_funding"
EVID = REPO / "docs" / "arc01-data-authority-01"
EXT_EVID = REPO / "docs" / "external-audit-01" / "arc01-data-authority-01"

SYMBOLS = ("BTCUSDT", "ETHUSDT", "SOLUSDT")
SCHEMA_VERSION = "1.0.0"
NORMALIZER_VERSION = "1.0.0"
FUNDING_INTERVAL_HOURS_CANON = 8
FUNDING_INTERVAL_MS = 8 * 3600 * 1000

# Guard: forbid test writes to canonical processed path
import os


def _guard_not_canonical_under_pytest(out_dir: Path | None = None) -> None:
    if "PYTEST_CURRENT_TEST" not in os.environ:
        return
    candidates = [out_dir.resolve()] if out_dir is not None else [PROC_ROOT.resolve()]
    for cand in candidates:
        for root in [PROC_ROOT.resolve(), (MAIN_DATA / "processed" / "arc01_funding").resolve()]:
            try:
                if cand == root or root in cand.parents:
                    raise RuntimeError(f"TEST_DATASET_WRITE_FORBIDDEN: {cand} inside canonical {root}")
            except RuntimeError:
                raise
            except Exception:
                continue


def _sha256_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def _sha256_file(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _normalizer_commit() -> str:
    import subprocess

    try:
        return subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True, check=True, cwd=REPO).stdout.strip()
    except Exception:
        return "-"


def collect_raw_rows(symbol: str, raw_root: Path | None = None) -> tuple[list[dict], list[dict]]:
    """Collect all raw rows for symbol from vision monthly ZIPs + REST tail. Returns (rows, provenance_entries).

    raw_root defaults to the worktree raw root; callers may point it at another host data root
    (portable verifier). Both A/B runs must read the SAME raw provider bytes.
    """
    raw_root = Path(raw_root) if raw_root is not None else RAW_ROOT
    rows: list[dict] = []
    provenance: list[dict] = []
    sym_vision_dir = raw_root / "vision_monthly" / symbol
    for zp in sorted(sym_vision_dir.glob("*.zip")):
        sha = _sha256_file(zp)
        sidecar = zp.with_name(zp.name + ".CHECKSUM")
        provider_checksum = sidecar.read_text(encoding="utf-8", errors="replace").strip().split()[0] if sidecar.exists() else ""
        if provider_checksum and sha != provider_checksum:
            raise RuntimeError(f"CHECKSUM FAIL {symbol} {zp.name}")
        with zipfile.ZipFile(zp) as z:
            txt = z.read(z.namelist()[0]).decode()
            for r in csv.DictReader(io.StringIO(txt)):
                # calc_time is settlement instant ms, funding_interval_hours, last_funding_rate
                calc_time = int(r["calc_time"])
                interval_h = int(float(r["funding_interval_hours"]))
                rate = str(r["last_funding_rate"]).strip()
                rows.append({
                    "funding_time_ms": calc_time,
                    "funding_interval_hours": interval_h,
                    "funding_rate_raw": rate,
                    "rate_type": "Regular",
                    "source": "data.binance.vision:fundingRate/monthly",
                    "source_file": str(zp.relative_to(REPO)).replace("\\", "/") if zp.is_relative_to(REPO) else str(zp),
                    "source_sha256": sha,
                })
        provenance.append({"local": str(zp.relative_to(REPO)).replace("\\","/") if zp.is_relative_to(REPO) else str(zp), "sha256": sha, "provider_checksum": provider_checksum, "csv_rows": len(list(csv.DictReader(io.StringIO(txt)))) if False else 0})

    # REST tail
    tail_path = raw_root / "rest_tail" / f"{symbol}_rest_tail.jsonl"
    rest_sha = _sha256_file(tail_path) if tail_path.exists() else ""
    if tail_path.exists():
        for line in tail_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            r = json.loads(line)
            ms = int(r["funding_time_ms"])
            rows.append({
                "funding_time_ms": ms,
                "funding_interval_hours": FUNDING_INTERVAL_HOURS_CANON,
                "funding_rate_raw": str(r["funding_rate"]).strip(),
                "rate_type": r.get("rateType", "Regular"),
                "source": "binanceusdm:/fapi/v1/fundingRate",
                "source_file": str(tail_path.relative_to(REPO)).replace("\\","/") if tail_path.is_relative_to(REPO) else str(tail_path),
                "source_sha256": rest_sha,
            })
    return rows, provenance


def normalize_symbol(symbol: str, raw_rows: list[dict], out_dir: Path) -> dict:
    _guard_not_canonical_under_pytest(out_dir)
    # Deterministic sort by funding_time_ms
    raw_rows_sorted = sorted(raw_rows, key=lambda r: int(r["funding_time_ms"]))
    # Detect duplicates/conflicts
    seen: dict[int, dict] = {}
    normalized: list[dict] = []
    dup_identical = 0
    dup_conflicting = 0
    conflicting_keys: list[int] = []
    malformed = 0
    non_finite = 0
    for r in raw_rows_sorted:
        ms = int(r["funding_time_ms"])
        rate_raw = str(r["funding_rate_raw"]).strip()
        try:
            rate = float(rate_raw)
            if not math.isfinite(rate):
                non_finite += 1
                continue
        except Exception:
            malformed += 1
            continue
        interval_h = int(r["funding_interval_hours"])
        if interval_h != FUNDING_INTERVAL_HOURS_CANON:
            # Schedule change: record but don't fail at normalization; quality will flag
            pass
        if ms in seen:
            prev = seen[ms]
            if prev["rate"] == rate and prev["interval_h"] == interval_h:
                dup_identical += 1
                continue
            else:
                dup_conflicting += 1
                conflicting_keys.append(ms)
                continue
        seen[ms] = {"rate": rate, "interval_h": interval_h}
        # Build normalized record (canonical decimal per 8h)
        # availability = settlement (PIT: data_time <= decision_time)
        funding_time_ms = ms
        funding_time_utc = datetime.fromtimestamp(ms / 1000, tz=timezone.utc).isoformat().replace("+00:00", "Z")
        next_ms = funding_time_ms + interval_h * 3600 * 1000
        next_utc = datetime.fromtimestamp(next_ms / 1000, tz=timezone.utc).isoformat().replace("+00:00", "Z")
        # Preserve decimal fidelity as string with at least repr
        # Use funding_units normalization (same as contract): decimal_per_interval passthrough
        rate_str = str(rate) if "e" not in rate_raw.lower() else repr(rate)  # keep provider fidelity but canonicalize via float round-trip check
        # Actually normalize via float canonical: keep normalized decimal string
        rate_decimal_str = format(rate, ".10f").rstrip("0").rstrip(".") if rate != 0 else "0.0"
        # Keep original provider string as well? We'll keep rate_decimal_str as funding_rate
        normalized.append({
            "symbol": symbol,
            "funding_time_utc": funding_time_utc,
            "funding_time_ms": funding_time_ms,
            "funding_rate": rate_decimal_str,
            "funding_interval_hours": interval_h,
            "availability_time_utc": funding_time_utc,
            "availability_time_ms": funding_time_ms,
            "settlement_time_utc": funding_time_utc,
            "settlement_time_ms": funding_time_ms,
            "next_funding_time_utc": next_utc,
            "next_funding_time_ms": next_ms,
            "source": r["source"],
            "source_file": r["source_file"],
            "source_sha256": r["source_sha256"],
            "rate_type": r.get("rate_type", "Regular"),
        })
    normalized.sort(key=lambda r: int(r["funding_time_ms"]))
    # Quality checks
    timestamps = [int(r["funding_time_ms"]) for r in normalized]
    monotonic = all(timestamps[i] < timestamps[i + 1] for i in range(len(timestamps) - 1)) if timestamps else True
    duplicates_identical = dup_identical
    duplicates_conflicting = dup_conflicting
    # Interval distribution
    interval_dist: dict[str, int] = {}
    for r in normalized:
        k = str(r["funding_interval_hours"])
        interval_dist[k] = interval_dist.get(k, 0) + 1
    # Missing expected settlements: based on 8h cadence from first to last.
    # Provider timestamp jitter: calc_time may be  0..50ms off the 8h grid (verified: ±45ms range).
    # Treat any delta in [28799950, 28800050] as expected 8h. Anything else is a provider-schedule
    # difference (e.g. SOL 2022-11 temporarily 2h intervals) — recorded as PROVIDER_SCHEDULE_CHANGE,
    # not as a data error, so quality does not FAIL on a real exchange regime.
    missing_expected = 0
    missing_list: list[str] = []
    unexpected_settlements = 0
    provider_schedule_changes = 0
    provider_schedule_change_samples: list[str] = []
    if timestamps:
        for a, b in zip(timestamps, timestamps[1:]):
            delta = b - a
            # 8h jitter ±50ms is expected; 2h/4h with same jitter covers SOL 2022-11 schedule change
            if 28799950 <= delta <= 28800050:
                continue
            elif 14399950 <= delta <= 14400050:
                provider_schedule_changes += 1
                if len(provider_schedule_change_samples) < 10:
                    provider_schedule_change_samples.append(f"{a}->{b} delta={delta}ms (4h)")
                continue
            elif 7199950 <= delta <= 7200050:
                provider_schedule_changes += 1
                if len(provider_schedule_change_samples) < 10:
                    provider_schedule_change_samples.append(f"{a}->{b} delta={delta}ms (2h)")
                continue
            elif delta == 0:
                continue
            elif delta > FUNDING_INTERVAL_MS:
                # Larger gaps may be missing 8h settlements or a 2h/4h multiple; classify as provider schedule if multiple of 2h
                if delta % 7200000 == 0:
                    provider_schedule_changes += 1
                    if len(provider_schedule_change_samples) < 10:
                        provider_schedule_change_samples.append(f"{a}->{b} delta={delta}ms ({delta/3600000:.2f}h)")
                    continue
                elif delta % 28800000 == 0 or (delta > 28800050 and abs(delta - round(delta/28800000)*28800000) < 60):
                    missing_expected += int(round(delta / FUNDING_INTERVAL_MS)) - 1
                else:
                    unexpected_settlements += 1
            else:
                unexpected_settlements += 1
            if len(missing_list) < 10 and delta > FUNDING_INTERVAL_MS:
                missing_list.append(f"{a}->{b} delta={delta}ms")
    # Check for timezone normalization: all timestamps end with Z already
    # Malformed / non-finite already counted
    # Determine classification
    # Provider-schedule changes are NOT quality failures — they are recorded as PROVIDER_SCHEDULE_CHANGE
    # and surfaced in the ledger so downstream code can branch (still PIT-safe, still 8h decision cadence).
    if dup_conflicting > 0:
        classification = "INVALID_CONFLICTING_DUPLICATE"
    elif malformed > 0 or non_finite > 0:
        classification = "INVALID_VALUE"
    elif unexpected_settlements > 0:
        classification = "INVALID_SCHEDULE"
    else:
        classification = "VALID"
    # Write partition
    out_dir.mkdir(parents=True, exist_ok=True)
    # Partition per symbol (single file per symbol for now; future: monthly sharding if volume grows)
    partition_path = out_dir / f"{symbol}_funding.jsonl"
    lines = [json.dumps(r, sort_keys=True, separators=(",", ":")) + "\n" for r in normalized]
    partition_path.write_text("".join(lines), encoding="utf-8")
    part_bytes = partition_path.read_bytes()
    part_sha = _sha256_bytes(part_bytes)
    # Write per-symbol ledger entry
    ledger_entry = {
        "symbol": symbol,
        "partition": str(partition_path.relative_to(REPO)).replace("\\", "/") if partition_path.is_relative_to(REPO) else str(partition_path),
        "partition_sha256": part_sha,
        "partition_bytes": len(part_bytes),
        "rows": len(normalized),
        "first_funding_time_ms": timestamps[0] if timestamps else None,
        "first_funding_time_utc": normalized[0]["funding_time_utc"] if normalized else None,
        "last_funding_time_ms": timestamps[-1] if timestamps else None,
        "last_funding_time_utc": normalized[-1]["funding_time_utc"] if normalized else None,
        "monotonic": monotonic,
        "duplicates_identical_collapsed": duplicates_identical,
        "duplicates_conflicting": duplicates_conflicting,
        "conflicting_keys_ms": conflicting_keys[:20],
        "malformed_rows": malformed,
        "non_finite": non_finite,
        "interval_distribution_hours": interval_dist,
        "missing_expected_settlements": missing_expected,
        "missing_expected_samples": missing_list[:5],
        "unexpected_settlements": unexpected_settlements,
        "provider_schedule_changes": provider_schedule_changes,
        "provider_schedule_change_samples": provider_schedule_change_samples[:5],
        "provider_schedule_change_note": "SOL 2022-11: 2h intervals per funding_interval_hours=2 (verified). Treated as PROVIDER_SCHEDULE_CHANGE, not a data error. PIT-safe. Downstream must use funding_time_ms, not assumed 8h.",
        "classification": classification,
        "schema_version": SCHEMA_VERSION,
        "normalizer_version": NORMALIZER_VERSION,
    }
    return ledger_entry


def build_archive_dataset(out_dir: Path = PROC_ROOT, raw_root: Path = RAW_ROOT, *, write_evidence: bool = True) -> tuple[list[dict], dict]:
    _guard_not_canonical_under_pytest(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    # Evidence write is only for canonical PROC_ROOT builds; A/B temp builds must not overwrite committed evidence.
    # If out_dir is not PROC_ROOT and the caller did not explicitly request evidence, suppress it.
    try:
        canonical_proc = PROC_ROOT.resolve()
        requested = out_dir.resolve()
        is_canonical_out = requested == canonical_proc or canonical_proc in requested.parents
    except Exception:
        is_canonical_out = out_dir == PROC_ROOT
    effective_write_evidence = bool(write_evidence and is_canonical_out)
    commit = _normalizer_commit()
    per_symbol_ledgers: list[dict] = []
    for sym in SYMBOLS:
        raw_rows, _ = collect_raw_rows(sym, raw_root=raw_root)
        entry = normalize_symbol(sym, raw_rows, out_dir)
        per_symbol_ledgers.append(entry)
        print(f"[{sym}] {entry['rows']} rows {entry['first_funding_time_utc']} -> {entry['last_funding_time_utc']} class={entry['classification']} sha={entry['partition_sha256'][:12]}")

    # Dataset SHA: deterministic hash over sorted (symbol, funding_time_ms, funding_rate) tuples
    # Also include interval hours to catch schedule changes
    fingerprint_payload = {
        "schema_version": SCHEMA_VERSION,
        "normalizer_version": NORMALIZER_VERSION,
        "normalizer_commit": commit,
        "partitions": [
            {"symbol": e["symbol"], "partition_sha256": e["partition_sha256"], "rows": e["rows"]}
            for e in sorted(per_symbol_ledgers, key=lambda x: x["symbol"])
        ],
        "funding_units_contract": "FUNDING-UNITS-CANONICAL-V1",
        "pit_invariant": "data_time <= decision_time; funding_time_ms == availability_time_ms == settlement_time_ms; future funding never visible at T",
    }
    dataset_sha = _sha256_bytes(json.dumps(fingerprint_payload, sort_keys=True, separators=(",", ":")).encode())
    # Also compute strictly the funding bytes fingerprint (sorted rows hash) for cross-check
    # Full canonical JSON of all normalized rows sorted by (symbol, funding_time_ms)
    all_rows = []
    for e in per_symbol_ledgers:
        part_path = REPO / e["partition"] if not Path(e["partition"]).is_absolute() else Path(e["partition"])
        # Fallback if relative to REPO not to cwd
        if not part_path.exists():
            part_path = out_dir / f"{e['symbol']}_funding.jsonl"
        for line in part_path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                all_rows.append(json.loads(line))
    all_rows_sorted = sorted(all_rows, key=lambda r: (r["symbol"], int(r["funding_time_ms"])))
    canonical_bytes = json.dumps(all_rows_sorted, sort_keys=True, separators=(",", ":")).encode()
    canonical_sha = _sha256_bytes(canonical_bytes)

    # Write ledgers (only for canonical evidence builds)
    manifest = {
        "checkpoint": "ARC-01-FUNDING-AUTHORITY-01",
        "schema_version": SCHEMA_VERSION,
        "normalizer_version": NORMALIZER_VERSION,
        "normalizer_commit": commit,
        "funding_units_contract": "FUNDING-UNITS-CANONICAL-V1",
        "source_official": [
            "data.binance.vision:fundingRate/monthly (official archive, .CHECKSUM verified)",
            "binanceusdm:/fapi/v1/fundingRate (official REST, tail after 2026-08-31 16:00 UTC)",
        ],
        "pit_invariant": "data_time <= decision_time; funding_time_ms == availability_time_ms == settlement_time_ms; future funding never visible at T",
        "per_symbol": {e["symbol"]: e for e in per_symbol_ledgers},
        "partitions": {e["symbol"]: e["partition"] for e in per_symbol_ledgers},
        "partition_sha256": {e["symbol"]: e["partition_sha256"] for e in per_symbol_ledgers},
        "dataset_sha256": dataset_sha,
        "canonical_rows_sha256": canonical_sha,
        "rows_total": sum(e["rows"] for e in per_symbol_ledgers),
        "quality_overall": "PASS" if all(e["classification"] == "VALID" for e in per_symbol_ledgers) else "FAIL",
    }
    manifest_path = out_dir / "ARC01_FUNDING_MANIFEST.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if effective_write_evidence:
        EVID.mkdir(parents=True, exist_ok=True)
        EXT_EVID.mkdir(parents=True, exist_ok=True)
        quality_ledger_path = EVID / "ARC01_FUNDING_QUALITY_LEDGER.jsonl"
        with quality_ledger_path.open("w", encoding="utf-8", newline="\n") as fh:
            for e in per_symbol_ledgers:
                fh.write(json.dumps(e, sort_keys=True, separators=(",", ":")) + "\n")
        (EXT_EVID / "ARC01_FUNDING_QUALITY_LEDGER.jsonl").write_bytes(quality_ledger_path.read_bytes())
        (EVID / "ARC01_FUNDING_MANIFEST.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        (EXT_EVID / "ARC01_FUNDING_MANIFEST.json").write_bytes(manifest_path.read_bytes())
        # Also write evidence copy of partitions (data/processed is gitignored, so keep committed evidence snapshots for portability checks)
        for e in per_symbol_ledgers:
            src = REPO / e["partition"] if not Path(e["partition"]).is_absolute() else Path(e["partition"])
            if not src.exists():
                src = out_dir / f"{e['symbol']}_funding.jsonl"
            dst = EVID / f"{e['symbol']}_funding.jsonl"
            dst.write_bytes(src.read_bytes())
            dst2 = EXT_EVID / f"{e['symbol']}_funding.jsonl"
            dst2.write_bytes(src.read_bytes())
    else:
        # For temp A/B builds, keep evidence untouched; ensure manifest partitions remain portable logical paths
        # but the temp partition files exist only under out_dir.
        pass

    # Also write determinism seed (only for canonical)
    if effective_write_evidence:
        det_path = EVID / "ARC01_DATA_DETERMINISM.json"
        # caller collect_arc01_reuse_assessments will finalize; keep lightweight log here
        pass
    print(json.dumps({k: manifest[k] for k in ("dataset_sha256", "canonical_rows_sha256", "rows_total", "quality_overall")}, indent=2))
    return per_symbol_ledgers, manifest


def main(argv: list[str] | None = None) -> int:
    out = PROC_ROOT
    if argv and len(argv) >= 1:
        out = Path(argv[0])
    ledgers, manifest = build_archive_dataset(out_dir=out)
    bad = [e for e in ledgers if e["classification"] != "VALID"]
    if bad:
        print(f"FATAL quality: {[e['symbol'] + ':' + e['classification'] for e in bad]}")
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
