"""V2 normalizer: OI-FULL-HISTORY-FREEZE-02 / OI-DATASET-REFREEZE-02

Writes to data/processed/oi_full_history_v2/ (NEVER to the V1 directory).
All semantics identical to V1 normalizer (schema 2.0.1, normalizer 2.1.0)
except output_root is parametrizable and tests are forbidden from writing
to the canonical V2 root.

This script is the authoritative V2 builder. It also powers determinism
checks (A/B into separate dirs) and forensic gap analysis.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import math
import subprocess
import sys
import zipfile
from datetime import UTC, datetime, timedelta
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
RAW = REPO / "data" / "raw" / "binance_um" / "metrics"
OUT_V2_DEFAULT = REPO / "data" / "processed" / "oi_full_history_v2"
EVID_V2 = REPO / "docs" / "external-audit-01" / "oi-full-history-02"

SYMBOLS = ("BTCUSDT", "ETHUSDT", "SOLUSDT")
RANGES: dict[str, tuple[str, str]] = {
    "BTCUSDT": ("2020-09-01", "2026-09-10"),
    "ETHUSDT": ("2021-12-01", "2026-09-10"),
    "SOLUSDT": ("2021-12-01", "2026-09-10"),
}
EXPECTED_INTERVAL_SECONDS = 300
EXPECTED_ROWS_PER_DAY = 288
SCHEMA_VERSION = "2.0.1"
NORMALIZER_VERSION = "2.1.0"
NORMALIZER_VERSION_V2 = "2.1.0"  # unchanged semantics, version stays same
COMMON_WINDOW = ("2021-12-01T00:00:00Z", "2026-09-10T23:55:00Z")
ALLOWED_PROVIDER_FIELDS = {"create_time", "symbol", "sum_open_interest", "sum_open_interest_value"}
# Guard: canonical V2 roots (both on-disk and versioned docs) must never be written by tests
CANONICAL_V2_DATA_ROOTS = [
    OUT_V2_DEFAULT.resolve(),
    (REPO / "data" / "processed" / "oi_full_history").resolve(),
]


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _normalizer_commit() -> str:
    try:
        return subprocess.run(
            ["git", "rev-parse", "HEAD"], capture_output=True, text=True, check=True, cwd=REPO
        ).stdout.strip()
    except Exception:
        return "-"


def _grid_for_day(day: str) -> list[int]:
    base = int(datetime.strptime(day, "%Y-%m-%d").replace(tzinfo=UTC).timestamp() * 1000)
    return [base + i * EXPECTED_INTERVAL_SECONDS * 1000 for i in range(EXPECTED_ROWS_PER_DAY)]


def _guard_not_canonical_under_pytest(out_dir: Path) -> None:
    """Fail-closed: if running under pytest, forbid writes to canonical V2/V1 data roots."""
    import os

    if "PYTEST_CURRENT_TEST" not in os.environ:
        return
    try:
        resolved = out_dir.resolve()
    except Exception:
        return
    for root in CANONICAL_V2_DATA_ROOTS:
        try:
            # If out_dir is inside or equal to a canonical root, block it.
            if resolved == root or root in resolved.parents:
                raise RuntimeError(
                    f"TEST_DATASET_WRITE_FORBIDDEN: test attempted to write to canonical dataset root {root} "
                    f"(requested out_dir={out_dir}). Use tmp_path / isolated sandbox instead."
                )
        except RuntimeError:
            raise
        except Exception:
            continue
    # Also check docs evidence root
    evid = EVID_V2.resolve()
    try:
        if resolved == evid or evid in resolved.parents:
            raise RuntimeError(
                f"TEST_DATASET_WRITE_FORBIDDEN: test attempted to write to V2 evidence dir {evid}"
            )
    except RuntimeError:
        raise
    except Exception:
        pass


def process_file_v2(
    symbol: str, day: str, raw_dir: Path = RAW, out_dir: Path = OUT_V2_DEFAULT
) -> dict[str, object]:
    """Normalize one symbol/day for V2 (deterministic, PIT-valid).

    Rules:
    - provider timestamp: YYYY-MM-DD HH:MM:SS interpreted UTC
    - exact duplicate (same ts, identical OI payload) -> collapsed deterministically, counted
    - conflicting duplicate (same ts, different payload) -> INVALID_CONFLICTING_DUPLICATE effort; day INVALID_DUPLICATE
    - native cadence 5m, complete grid 288 timestamps, no synthetic gaps
    - out_dir is parametrizable; tests must NOT pass the canonical V2 root
    """
    _guard_not_canonical_under_pytest(out_dir)
    zip_path = raw_dir / symbol / f"{symbol}-metrics-{day}.zip"
    try:
        raw_rel = str(zip_path.relative_to(REPO)).replace("\\", "/")
    except ValueError:
        raw_rel = str(zip_path).replace("\\", "/")
    entry: dict[str, object] = {"symbol": symbol, "day": day, "raw_source": raw_rel}
    if not zip_path.exists():
        entry.update(classification="SOURCE_MISSING", rows=0)
        return entry
    sidecar = zip_path.with_name(zip_path.name + ".CHECKSUM")
    if not sidecar.exists():
        entry.update(classification="INVALID_CHECKSUM", checksum="MISSING_SIDECAR", rows=0)
        return entry
    expected = sidecar.read_text(encoding="utf-8", errors="replace").strip().split()[0]
    raw_sha = _sha256_file(zip_path)
    if raw_sha != expected:
        entry.update(
            classification="INVALID_CHECKSUM", checksum="FAIL", raw_source_sha256=raw_sha, rows=0
        )
        return entry
    entry["checksum"] = "PASS"
    entry["raw_source_sha256"] = raw_sha

    rows: list[dict[str, object]] = []
    order_inversions = 0
    invalid_values = 0
    conflicting_duplicates = 0
    exact_duplicate_rows = 0
    schema_drift = False
    try:
        with zipfile.ZipFile(zip_path) as zf:
            name = zf.namelist()[0]
            with zf.open(name) as fh:
                text = io.TextIOWrapper(fh, encoding="utf-8")
                reader = csv.DictReader(text)
                header = list(reader.fieldnames or [])
                if header and not set(ALLOWED_PROVIDER_FIELDS) <= set(header):
                    schema_drift = True
                prev_ts: int | None = None
                seen_payloads: dict[int, tuple[float, float]] = {}
                for row in reader:
                    try:
                        ts_str = str(row["create_time"]).strip()
                        ts = int(
                            datetime.strptime(ts_str, "%Y-%m-%d %H:%M:%S")
                            .replace(tzinfo=UTC)
                            .timestamp()
                            * 1000
                        )
                        oi = float(row["sum_open_interest"])
                        oiv = float(row["sum_open_interest_value"])
                    except (KeyError, TypeError, ValueError):
                        invalid_values += 1
                        continue
                    if not (math.isfinite(oi) and math.isfinite(oiv)) or oi < 0 or oiv < 0:
                        invalid_values += 1
                        continue
                    if prev_ts is not None and ts < prev_ts:
                        order_inversions += 1
                    prev_ts = ts
                    payload = (oi, oiv)
                    if ts in seen_payloads:
                        if seen_payloads[ts] == payload:
                            exact_duplicate_rows += 1
                            continue
                        conflicting_duplicates += 1
                        continue
                    seen_payloads[ts] = payload
                    rows.append(
                        {
                            "timestamp_ms": ts,
                            "sum_open_interest": oi,
                            "sum_open_interest_value": oiv,
                        }
                    )
    except (zipfile.BadZipFile, UnicodeDecodeError, KeyError) as e:
        entry.update(classification="INVALID_SCHEMA", error=str(e)[:120], rows=0)
        return entry

    if schema_drift:
        entry.update(classification="INVALID_SCHEMA", rows=len(rows))
        return entry
    if invalid_values:
        entry.update(classification="INVALID_VALUE", rows=len(rows), invalid_values=invalid_values)
        return entry

    rows.sort(key=lambda r: r["timestamp_ms"])  # type: ignore[arg-type]
    seen_set: set[int] = set()
    deduped: list[dict[str, object]] = []
    for r in rows:
        ts = int(r["timestamp_ms"])
        if ts in seen_set:
            continue
        seen_set.add(ts)
        deduped.append(r)

    grid = set(_grid_for_day(day))
    ts_set = seen_set
    missing_intervals = sorted(grid - ts_set)
    off_grid = sorted(ts_set - grid)
    day_end_ms = max(grid) + EXPECTED_INTERVAL_SECONDS * 1000
    future_rows = sum(1 for r in deduped if int(r["timestamp_ms"]) >= day_end_ms)

    if future_rows:
        cls = "INVALID_VALUE"
    elif conflicting_duplicates:
        cls = "INVALID_CONFLICTING_DUPLICATE"
    elif missing_intervals:
        cls = "INVALID_GAP"
    elif len(deduped) != EXPECTED_ROWS_PER_DAY:
        cls = "INVALID_ROW_COUNT"
    else:
        cls = "VALID"

    # Normalize classification naming for ledger (keep historic names for compatibility, but record new)
    # External verifier expects INVALID_GAP / INVALID_VALUE etc; we keep those, plus new CONFLICTING name as INVALID_CONFLICTING_DUPLICATE
    entry.update(
        classification=cls,
        rows=len(deduped),
        raw_order_inversions=order_inversions,
        duplicates=conflicting_duplicates,
        exact_duplicate_rows_collapsed=exact_duplicate_rows,
        missing_intervals=len(missing_intervals),
        missing_first=missing_intervals[:5],
        off_grid=len(off_grid),
        invalid_values=invalid_values,
        rows_within_pit=len(deduped) - future_rows,
        first_timestamp_ms=int(deduped[0]["timestamp_ms"]) if deduped else None,
        last_timestamp_ms=int(deduped[-1]["timestamp_ms"]) if deduped else None,
        schema_version=SCHEMA_VERSION,
        normalizer_version=NORMALIZER_VERSION_V2,
    )

    if cls == "VALID":
        out_path = out_dir / symbol / f"{symbol}-oi-5m-{day}.jsonl"
        buf = bytearray()
        for r in deduped:
            rec = {
                "timestamp_ms": r["timestamp_ms"],
                "sum_open_interest": r["sum_open_interest"],
                "sum_open_interest_value": r["sum_open_interest_value"],
                "unit_semantics": "BASE_ASSET_UNITS",
                "source_file": entry["raw_source"],
                "source_sha256": raw_sha,
            }
            buf += (json.dumps(rec, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_bytes(bytes(buf))
        try:
            norm_rel = str(out_path.relative_to(REPO)).replace("\\", "/")
        except ValueError:
            norm_rel = str(out_path).replace("\\", "/")
        entry["normalized_path"] = norm_rel
        entry["normalized_sha256"] = hashlib.sha256(bytes(buf)).hexdigest()
        fp_payload = json.dumps(
            {
                "symbol": symbol,
                "day": day,
                "raw_source_sha256": raw_sha,
                "normalized_sha256": entry["normalized_sha256"],
                "rows": entry["rows"],
                "schema_version": SCHEMA_VERSION,
                "normalizer_version": NORMALIZER_VERSION_V2,
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        entry["dataset_fingerprint"] = hashlib.sha256(fp_payload.encode("utf-8")).hexdigest()
    return entry


def build_v2_dataset(
    out_dir: Path = OUT_V2_DEFAULT, raw_dir: Path = RAW
) -> tuple[list[dict[str, object]], dict[str, object]]:
    """Build full V2 dataset into out_dir and return (ledger, manifest)."""
    _guard_not_canonical_under_pytest(out_dir) if "PYTEST_CURRENT_TEST" in __import__(
        "os"
    ).environ else None
    commit = _normalizer_commit()
    ledger: list[dict[str, object]] = []
    for sym in SYMBOLS:
        d0, d1 = RANGES[sym]
        from datetime import date as _date

        a, b = _date.fromisoformat(d0), _date.fromisoformat(d1)
        days = [(a + timedelta(days=i)).isoformat() for i in range((b - a).days + 1)]
        print(f"[{sym}] normalizing {len(days)} days -> {out_dir}...", flush=True)
        for k, day in enumerate(days, 1):
            ledger.append(process_file_v2(sym, day, raw_dir=raw_dir, out_dir=out_dir))
            if k % 500 == 0:
                print(f"  {k}/{len(days)}", flush=True)

    out_dir.mkdir(parents=True, exist_ok=True)
    ledger_path = out_dir / "OI_ARCHIVE_DAY_VALIDITY_LEDGER_V2.jsonl"
    with ledger_path.open("w", encoding="utf-8", newline="\n") as fh:
        for e in ledger:
            fh.write(json.dumps(e, sort_keys=True, separators=(",", ":")) + "\n")

    per_symbol: dict[str, dict[str, object]] = {}
    for sym in SYMBOLS:
        entries = [e for e in ledger if e["symbol"] == sym]
        valid = [e for e in entries if e["classification"] == "VALID"]
        invalid = [e for e in entries if e["classification"] != "VALID"]
        per_symbol[sym] = {
            "files": len(entries),
            "valid_days": len(valid),
            "invalid_days": len(invalid),
            "invalid_breakdown": {
                cls: sum(1 for e in invalid if e["classification"] == cls)
                for cls in sorted({str(e["classification"]) for e in invalid})
            },
            "rows": sum(int(e.get("rows", 0)) for e in valid),
            "first_timestamp_ms": min(
                (int(e["first_timestamp_ms"]) for e in valid if e.get("first_timestamp_ms")),
                default=None,
            ),
            "last_timestamp_ms": max(
                (int(e["last_timestamp_ms"]) for e in valid if e.get("last_timestamp_ms")),
                default=None,
            ),
            "gaps": sum(int(e.get("missing_intervals", 0)) for e in entries),
            "duplicates": sum(int(e.get("duplicates", 0)) for e in entries),
            "checksum_failures": sum(
                1 for e in entries if e["classification"] == "INVALID_CHECKSUM"
            ),
            "schema_drift": sum(1 for e in entries if e["classification"] == "INVALID_SCHEMA"),
            "invalid_values": sum(int(e.get("invalid_values", 0)) for e in entries),
            "raw_order_inversions": sum(int(e.get("raw_order_inversions", 0)) for e in entries),
        }

    total_valid = sum(int(v["valid_days"]) for v in per_symbol.values())
    total_invalid = sum(int(v["invalid_days"]) for v in per_symbol.values())
    hard_fail = any(
        per_symbol[s]["checksum_failures"] or per_symbol[s]["schema_drift"] for s in SYMBOLS
    )
    quality = "FAIL" if hard_fail else ("PASS_WITH_EXPLICIT_GAPS" if total_invalid else "PASS")

    manifest = {
        "checkpoint": "OI-DATASET-REFREEZE-02 + OI-FULL-HISTORY-FREEZE-02",
        "family": "open_interest_full_history",
        "source": "SOURCE_BINANCE_VISION_USDM_METRICS_DAILY (official data.binance.vision archive)",
        "schema_version": SCHEMA_VERSION,
        "normalizer_version": NORMALIZER_VERSION_V2,
        "normalizer_commit": commit,
        "native_cadence": "5m",
        "expected_interval_seconds": EXPECTED_INTERVAL_SECONDS,
        "expected_rows_complete_utc_day": EXPECTED_ROWS_PER_DAY,
        "field_whitelist": sorted(ALLOWED_PROVIDER_FIELDS),
        "excluded_provider_fields": [
            "count_toptrader_long_short_ratio",
            "sum_toptrader_long_short_ratio",
            "count_long_short_ratio",
            "sum_taker_long_short_vol_ratio",
        ],
        "unit_semantics": {
            "sum_open_interest": "BASE_ASSET_UNITS",
            "sum_open_interest_value": "USDT_NOTIONAL",
        },
        "common_research_window_utc": list(COMMON_WINDOW),
        "USE_COMMON_WINDOW": True,
        "pre_common_auxiliary_data": "BTCUSDT 2020-09-01..2021-11-30 preserved, excluded from H6 by default",
        "quality_status": quality,
        "totals": {
            "files": len(ledger),
            "valid_days": total_valid,
            "invalid_days": total_invalid,
            "rows_valid": sum(int(v["rows"]) for v in per_symbol.values()),
            "valid_days_in_common_window": sum(
                1
                for e in ledger
                if e["classification"] == "VALID" and str(e["day"]) >= "2021-12-01"
            ),
            "valid_days_in_common_window_all_symbols": None,
        },
        "per_symbol": per_symbol,
        "ledger": str(
            (out_dir / "OI_ARCHIVE_DAY_VALIDITY_LEDGER_V2.jsonl").relative_to(REPO)
        ).replace("\\", "/")
        if out_dir.is_relative_to(REPO)
        else str(out_dir / "OI_ARCHIVE_DAY_VALIDITY_LEDGER_V2.jsonl"),
        "output_root": str(out_dir.relative_to(REPO)).replace("\\", "/")
        if out_dir.is_relative_to(REPO)
        else str(out_dir),
    }
    # compute intersection of valid days across all three symbols in common window
    valid_sets = []
    for sym in SYMBOLS:
        valid_sets.append(
            {
                str(e["day"])
                for e in ledger
                if e["symbol"] == sym
                and e["classification"] == "VALID"
                and str(e["day"]) >= "2021-12-01"
            }
        )
    if valid_sets:
        manifest["totals"]["valid_days_in_common_window_all_symbols"] = len(
            set.intersection(*valid_sets)
        )

    fp_src = json.dumps(
        {
            "schema_version": SCHEMA_VERSION,
            "normalizer_version": NORMALIZER_VERSION_V2,
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
    manifest["OI_FULL_HISTORY_DATASET_SHA256_V2"] = hashlib.sha256(
        fp_src.encode("utf-8")
    ).hexdigest()
    # also keep legacy key for compatibility
    manifest["OI_FULL_HISTORY_DATASET_SHA256"] = manifest["OI_FULL_HISTORY_DATASET_SHA256_V2"]
    manifest["ledger_sha256"] = hashlib.sha256(
        (out_dir / "OI_ARCHIVE_DAY_VALIDITY_LEDGER_V2.jsonl").read_bytes()
    ).hexdigest()
    manifest["manifest_sha256"] = hashlib.sha256(
        json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()

    out_manifest = out_dir / "OI_FULL_HISTORY_DATASET_MANIFEST_V2.json"
    out_manifest.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    # committed evidence copy (data/processed is gitignored)
    EVID_V2.mkdir(parents=True, exist_ok=True)
    (EVID_V2 / "OI_FULL_HISTORY_DATASET_MANIFEST_V2.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    (EVID_V2 / "OI_ARCHIVE_DAY_VALIDITY_LEDGER_V2.jsonl").write_bytes(
        (out_dir / "OI_ARCHIVE_DAY_VALIDITY_LEDGER_V2.jsonl").read_bytes()
    )
    print(
        json.dumps(
            {
                k: manifest[k]
                for k in ("quality_status", "totals", "OI_FULL_HISTORY_DATASET_SHA256_V2")
            },
            indent=2,
        )
    )
    return ledger, manifest


def main(argv: list[str] | None = None) -> int:
    out = OUT_V2_DEFAULT
    if argv and len(argv) >= 1:
        out = Path(argv[0])
    _ledger, _manifest = build_v2_dataset(out_dir=out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
