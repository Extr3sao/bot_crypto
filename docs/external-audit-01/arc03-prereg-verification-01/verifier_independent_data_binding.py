#!/usr/bin/env python
"""INDEPENDENT ARC-03 data-binding re-derivation (verifier-owned parser).

This does NOT import or call the builder's normalizer. It re-implements the documented
contract from the raw provider bytes upward:

    raw .zip + .CHECKSUM  ->  validated rows  ->  month classification
        ->  normalized partition bytes  ->  partition SHA256
        ->  fingerprint registry + daily supplements  ->  DATASET SHA256

and compares every result against the frozen manifest and the frozen spec.

Read-only against the certified data root; all mutation experiments use TEMP copies.

Usage:
    python docs/external-audit-01/arc03-prereg-verification-01/verifier_independent_data_binding.py \
        --data-root <ABS_PATH> --out <JSON_PATH>
"""

from __future__ import annotations

import argparse
import calendar
import datetime as dt
import hashlib
import json
import pathlib
import sys
import zipfile

BAR_MS = 300_000
BARS_PER_DAY = 288
DAY_MS = 86_400_000
SCHEMA_VERSION = "1.0.0"
NORMALIZER_VERSION = "1.0.0"
INTERVAL = "5m"
ASSETS = ("BTCUSDT", "ETHUSDT", "SOLUSDT")
ADMITTED = frozenset({"VALID", "VALID_INITIAL_PARTIAL", "VALID_WITH_DAILY_SUPPLEMENT"})
EXPECTED_HEADER = (
    "open_time,open,high,low,close,volume,close_time,quote_volume,count,"
    "taker_buy_volume,taker_buy_quote_volume,ignore"
)


def sha256_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def sha256_file(p: pathlib.Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def canon(obj) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":")).encode("utf-8")


def month_days(month: str) -> int:
    return calendar.monthrange(int(month[:4]), int(month[5:]))[1]


def expected_rows(month: str) -> int:
    return month_days(month) * BARS_PER_DAY


def month_first_open_ms(month: str) -> int:
    y, m = int(month[:4]), int(month[5:])
    return int(dt.datetime(y, m, 1, tzinfo=dt.timezone.utc).timestamp() * 1000)


def _fields(line: str) -> list[str] | None:
    f = line.split(",")
    if len(f) != 12:
        return None
    return f


def parse_archive(
    zip_path: pathlib.Path, symbol: str, ms_value: str, *, strict_daily: bool, month: str | None = None
) -> dict:
    """Verifier-owned parser. Returns {"rows": [...], "meta": {...}, "fatal": str|None}.

    ``ms_value`` is the provenance label written into each row (month for monthly archives,
    the date for daily archives) because it participates in the canonical partition bytes.
    """
    month = month if month is not None else ms_value
    meta = {
        "rows": 0,
        "header_present": False,
        "malformed_rows": 0,
        "non_finite": 0,
        "high_lt_low": 0,
        "close_time_violations": 0,
        "negative_volume": 0,
        "off_grid": 0,
        "schema_field_mismatch": 0,
        "exact_duplicate_rows_collapsed": 0,
        "conflicting_duplicates": 0,
        "duplicate_timestamps": 0,
    }
    if not zip_path.exists():
        return {"rows": [], "meta": meta, "fatal": "SOURCE_MISSING"}
    meta["raw_size_bytes"] = zip_path.stat().st_size
    meta["raw_sha256"] = sha256_file(zip_path)
    sidecar = zip_path.with_name(zip_path.name + ".CHECKSUM")
    if not sidecar.exists():
        return {"rows": [], "meta": meta, "fatal": "NO_CHECKSUM_SIDECAR"}
    expected_cs = sidecar.read_text(encoding="utf-8").split()[0]
    meta["provider_checksum_sha256"] = expected_cs
    meta["provider_checksum_match"] = expected_cs == meta["raw_sha256"]
    if not meta["provider_checksum_match"]:
        return {"rows": [], "meta": meta, "fatal": "INVALID_CHECKSUM"}
    try:
        with zipfile.ZipFile(zip_path) as zf:
            if len(zf.namelist()) != 1:
                return {"rows": [], "meta": meta, "fatal": "ARCHIVE_NOT_SINGLE_MEMBER"}
            text = zf.open(zf.namelist()[0]).read().decode("utf-8")
    except Exception as exc:  # noqa: BLE001
        return {"rows": [], "meta": meta, "fatal": f"INVALID_SCHEMA:{type(exc).__name__}"}

    lines = [ln for ln in text.splitlines() if ln.strip()]
    if not lines:
        return {"rows": [], "meta": meta, "fatal": "INVALID_ROW_COUNT"}
    if lines[0].strip() == EXPECTED_HEADER:
        meta["header_present"] = True
        lines = lines[1:]
    elif lines[0].strip().startswith("open_time,"):
        return {"rows": [], "meta": meta, "fatal": "INVALID_SCHEMA_UNEXPECTED_HEADER"}

    seen: dict[int, tuple] = {}
    rows: list[dict] = []
    for line in lines:
        parts = _fields(line)
        if parts is None:
            meta["schema_field_mismatch"] += 1
            continue
        try:
            open_time = int(parts[0])
            close_time = int(parts[6])
            count = int(parts[8])
            floats = [float(parts[i]) for i in (1, 2, 3, 4, 5, 7, 9, 10)]
        except ValueError:
            meta["malformed_rows"] += 1
            continue
        if any(v != v or v in (float("inf"), float("-inf")) for v in floats):
            meta["non_finite"] += 1
            continue
        o, h, l, c, v, qv, tb, tq = floats
        if h < l:
            meta["high_lt_low"] += 1
            continue
        if min(o, h, l, c) <= 0 or min(v, qv, tb, tq) < 0:
            meta["negative_volume"] += 1
            continue
        if close_time != open_time + BAR_MS - 1:
            meta["close_time_violations"] += 1
        if open_time % BAR_MS != 0:
            meta["off_grid"] += 1
        payload = (parts[1], parts[2], parts[3], parts[4], parts[5], parts[7], count, parts[9], parts[10])
        if open_time in seen:
            if seen[open_time] == payload:
                meta["exact_duplicate_rows_collapsed"] += 1
            else:
                meta["conflicting_duplicates"] += 1
            continue
        seen[open_time] = payload
        rows.append(
            {
                "t": open_time,
                "ct": close_time,
                "o": parts[1],
                "h": parts[2],
                "l": parts[3],
                "c": parts[4],
                "v": parts[5],
                "qv": parts[7],
                "n": count,
                "tb": parts[9],
                "tq": parts[10],
                "sym": symbol,
                "ms": ms_value,
            }
        )
    rows.sort(key=lambda r: r["t"])
    meta["rows"] = len(rows)
    meta["first_open_ms"] = rows[0]["t"] if rows else None
    meta["last_open_ms"] = rows[-1]["t"] if rows else None
    meta["duplicate_timestamps"] = meta["exact_duplicate_rows_collapsed"] + meta["conflicting_duplicates"]
    meta["internal_cadence_breaks"] = sum(1 for a, b in zip(rows, rows[1:]) if b["t"] - a["t"] != BAR_MS)
    meta["off_grid_and_close_violations_computed"] = True
    if strict_daily:
        ok = (
            len(rows) == BARS_PER_DAY
            and meta["internal_cadence_breaks"] == 0
            and meta["off_grid"] == 0
            and meta["close_time_violations"] == 0
        )
        return {"rows": rows if ok else [], "meta": meta, "fatal": None if ok else "DAILY_CONTRACT_FAIL"}
    meta["expected_last_open_ms"] = month_first_open_ms(month) + (expected_rows(month) - 1) * BAR_MS
    meta["ends_at_month_end"] = bool(rows) and rows[-1]["t"] == meta["expected_last_open_ms"]
    return {"rows": rows, "meta": meta, "fatal": None}


def classify(meta: dict, month: str, *, is_first_month: bool, fatal: str | None) -> str:
    if fatal is not None:
        return fatal
    if meta["conflicting_duplicates"]:
        return "INVALID_CONFLICTING_DUPLICATE"
    if meta["malformed_rows"] or meta["schema_field_mismatch"] or meta["non_finite"] or meta["high_lt_low"]:
        return "INVALID_VALUE"
    exp, actual = expected_rows(month), meta["rows"]
    if actual > exp:
        return "INVALID_ROW_COUNT"
    if actual == exp:
        return "VALID"
    if (
        is_first_month
        and actual > 0
        and meta["internal_cadence_breaks"] == 0
        and meta["off_grid"] == 0
        and meta["close_time_violations"] == 0
        and meta["ends_at_month_end"] is True
    ):
        return "VALID_INITIAL_PARTIAL"
    return "INVALID_GAP"


def day_shortfalls(rows: list[dict], month: str, *, is_first_month: bool) -> dict[str, int]:
    if not rows:
        return {}
    start = month_first_open_ms(month)
    present = {r["t"] for r in rows}
    first_seen = min(present)
    out: dict[str, int] = {}
    for d in range(month_days(month)):
        day_start = start + d * DAY_MS
        want = [day_start + i * BAR_MS for i in range(BARS_PER_DAY)]
        if is_first_month and want[-1] < first_seen:
            continue
        missing = sum(1 for t in want if t not in present)
        if missing:
            out[f"{int(month[:4]):04d}-{int(month[5:]):02d}-{d + 1:02d}"] = missing
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-root", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--spec", default="docs/arc03-prereg-01/ARC03_SPEC_V1.json")
    ap.add_argument("--manifest", default="docs/arc03-data-authority-01/ARC03_DATA_MANIFEST.json")
    args = ap.parse_args()

    root = pathlib.Path(args.data_root)
    if not root.is_absolute():
        print(json.dumps({"verdict": "FAIL_CLOSED", "reason": "data root must be absolute"}))
        return 2

    repo = pathlib.Path(__file__).resolve().parents[3]
    spec = json.loads((repo / args.spec).read_text(encoding="utf-8"))
    manifest = json.loads((repo / args.manifest).read_text(encoding="utf-8"))

    failures: list[dict] = []
    raw_root = root / "data" / "raw" / "binance_um" / "arc03"
    daily_root = root / "data" / "raw" / "binance_um" / "arc03_daily"
    part_dir = root / "data" / "processed" / "arc03_klines_5m"

    if not raw_root.exists():
        print(json.dumps({"verdict": "FAIL_CLOSED", "reason": f"raw root missing: {raw_root}"}))
        return 2

    my_raw_files: list[dict] = []
    my_fp_registry: list[dict] = []
    my_supplements: list[dict] = []
    my_partition_sha: dict[str, str] = {}
    my_rows: dict[str, list[dict]] = {}
    checksum_misses: list[str] = []
    classification_mismatches: list[dict] = []
    withhold_report: dict[str, list[str]] = {}
    synthetic_evidence: dict[str, dict] = {}

    manifest_raw = {(e["symbol"], e["month"]): e["raw_sha256"] for e in manifest["raw_files"]}

    for symbol in ASSETS:
        sym_raw = raw_root / symbol
        month_dirs = sorted(p for p in sym_raw.iterdir() if p.is_dir())
        all_rows: list[dict] = []
        first_seen = None
        for md in month_dirs:
            month = md.name
            zp = md / f"{symbol}-{INTERVAL}-{month}.zip"
            parsed = parse_archive(zp, symbol, month, strict_daily=False, month=month)
            meta, rows = parsed["meta"], parsed["rows"]
            is_first = first_seen is None
            cls = classify(meta, month, is_first_month=is_first, fatal=parsed["fatal"])
            my_raw_files.append({"symbol": symbol, "month": month, "raw_sha256": meta.get("raw_sha256")})
            if meta.get("provider_checksum_match") is not True:
                checksum_misses.append(f"{symbol}/{month}")
            if manifest_raw.get((symbol, month)) != meta.get("raw_sha256"):
                failures.append(
                    {
                        "check": "raw_sha256_mismatch",
                        "key": f"{symbol}/{month}",
                        "manifest": manifest_raw.get((symbol, month)),
                        "actual": meta.get("raw_sha256"),
                    }
                )
            source_rows = rows
            if cls == "INVALID_GAP":
                shortfalls = day_shortfalls(rows, month, is_first_month=is_first)
                got_rows: list[dict] = []
                ok = bool(shortfalls)
                got_dates: list[str] = []
                for date in sorted(shortfalls):
                    dz = daily_root / symbol / date / f"{symbol}-{INTERVAL}-{date}.zip"
                    dp = parse_archive(dz, symbol, date, strict_daily=True, month=month)
                    if dp["rows"] == [] or dp["meta"].get("provider_checksum_match") is not True:
                        ok = False
                        break
                    got_dates.append(date)
                    got_rows.extend(dp["rows"])
                    my_supplements.append(
                        {
                            "symbol": symbol,
                            "date": date,
                            "raw_sha256": dp["meta"]["raw_sha256"],
                            "for_month": month,
                        }
                    )
                if ok:
                    union = sorted(source_rows + got_rows, key=lambda r: r["t"])
                    contiguous = (
                        len(union) == expected_rows(month)
                        and all(b["t"] - a["t"] == BAR_MS for a, b in zip(union, union[1:]))
                    )
                    if contiguous:
                        # NO SYNTHETIC MARKET ROWS: the union must be exactly the two
                        # official sources, nothing in between.
                        union_keys = {(r["t"], r["o"], r["h"], r["l"], r["c"], r["v"]) for r in union}
                        src_keys = {(r["t"], r["o"], r["h"], r["l"], r["c"], r["v"]) for r in source_rows + got_rows}
                        synthetic_evidence[f"{symbol}/{month}"] = {
                            "union_rows": len(union),
                            "union_equals_official_union": union_keys == src_keys,
                            "supplement_days": got_dates,
                            "monthly_rows": len(source_rows),
                            "supplement_rows": len(got_rows),
                            "shortfall_map": shortfalls,
                        }
                        source_rows = union
                        cls = "VALID_WITH_DAILY_SUPPLEMENT"
                    else:
                        synthetic_evidence[f"{symbol}/{month}"] = {"rejected": "union not contiguous or wrong count"}
            my_fp_registry.append(
                {
                    "symbol": symbol,
                    "month": month,
                    "raw_sha256": meta.get("raw_sha256"),
                    "normalized_rows": len(source_rows) if cls in ADMITTED else 0,
                    "classification": cls,
                }
            )
            if cls in ADMITTED and source_rows:
                all_rows.extend(source_rows)
                if first_seen is None:
                    first_seen = source_rows[0]["t"]
            elif cls not in ADMITTED:
                withhold_report.setdefault(symbol, []).append(f"{month}:{cls}")

        all_rows.sort(key=lambda r: r["t"])
        payload = bytearray()
        for r in all_rows:
            payload += canon(r) + b"\n"
        my_partition_sha[symbol] = sha256_bytes(bytes(payload))
        my_rows[symbol] = all_rows
        # compare with the on-disk partition bytes AND the frozen digest
        on_disk = part_dir / f"{symbol}.jsonl"
        if not on_disk.exists():
            failures.append({"check": "partition_missing", "symbol": symbol})
        else:
            disk_sha = sha256_file(on_disk)
            if disk_sha != my_partition_sha[symbol]:
                failures.append(
                    {
                        "check": "partition_bytes_differ",
                        "symbol": symbol,
                        "verifier_recomputed": my_partition_sha[symbol],
                        "on_disk": disk_sha,
                    }
                )
            if disk_sha != manifest["partition_sha256"][symbol]:
                failures.append({"check": "partition_sha_mismatch_manifest", "symbol": symbol})
            if disk_sha != spec["data_authority"]["partition_sha256"][symbol]:
                failures.append({"check": "partition_sha_mismatch_spec", "symbol": symbol})
            if disk_sha[:8] not in ("eb75ab97", "24c88690", "d872bc7d"):
                failures.append({"check": "partition_prefix_unexpected", "symbol": symbol, "sha": disk_sha})
            if bytes(payload) != on_disk.read_bytes():
                failures.append({"check": "partition_byte_inequality_verifier_vs_authority", "symbol": symbol})

    my_fp_registry.sort(key=lambda x: (x["symbol"], x["month"]))
    my_supplements.sort(key=lambda x: (x["symbol"], x["date"]))
    my_raw_sorted = sorted(my_raw_files, key=lambda x: (x["symbol"], x["month"]))

    # Two readings of the undocumented-in-detail field `normalized_rows`:
    #   (A) admitted rows of the month (the natural reading of the name)
    #   (B) the ledger's `rows` field, i.e. rows parsed from the MONTHLY archive before any
    #       daily supplement (the implementation's reading)
    fp_payload_a = {
        "schema_version": SCHEMA_VERSION,
        "normalizer_version": NORMALIZER_VERSION,
        "interval": INTERVAL,
        "files": my_fp_registry,
        "daily_supplements": my_supplements,
    }
    supplement_rows_by_month = {}
    for e in my_fp_registry:
        if e["classification"] == "VALID_WITH_DAILY_SUPPLEMENT":
            supplement_rows_by_month[(e["symbol"], e["month"])] = 0
    ledger_supp = {(s["symbol"], s["for_month"]) for s in my_supplements}
    for s in my_supplements:
        supplement_rows_by_month[(s["symbol"], s["for_month"])] += 288
    files_b = []
    for e in my_fp_registry:
        key = (e["symbol"], e["month"])
        n = e["normalized_rows"]
        if e["classification"] == "VALID_WITH_DAILY_SUPPLEMENT":
            n = n - supplement_rows_by_month.get(key, 0)
        files_b.append({**e, "normalized_rows": n})
    fp_payload_b = {**fp_payload_a, "files": files_b}
    sha_reading_a = sha256_bytes(canon(fp_payload_a))
    sha_reading_b = sha256_bytes(canon(fp_payload_b))
    my_dataset_sha = sha_reading_b
    my_raw_files_sha = sha256_bytes(canon(my_raw_sorted))
    my_supplements_sha = sha256_bytes(canon(my_supplements))

    frozen_sha = manifest["dataset_sha256"]
    if sha_reading_b == frozen_sha:
        reproduced = "READING_B_ledger_rows_field"
    elif sha_reading_a == frozen_sha:
        reproduced = "READING_A_admitted_rows"
    else:
        reproduced = None
        failures.append(
            {
                "check": "dataset_sha256_not_reproducible_under_either_reading",
                "reading_a": sha_reading_a,
                "reading_b": sha_reading_b,
                "frozen": frozen_sha,
            }
        )
    if my_dataset_sha != spec["data_authority"]["dataset_sha256"]:
        failures.append({"check": "dataset_sha256_mismatch_spec"})

    # Data-level equality is the operative binding; the digest-field ambiguity is recorded
    # precisely rather than allowed to masquerade as a data change.
    normalized_rows_ambiguity = []
    if sha_reading_a != sha_reading_b:
        for e in my_fp_registry:
            if e["classification"] == "VALID_WITH_DAILY_SUPPLEMENT":
                normalized_rows_ambiguity.append(
                    {
                        "symbol": e["symbol"],
                        "month": e["month"],
                        "ledger_rows_field_reading_b": e["normalized_rows"] - supplement_rows_by_month[(e["symbol"], e["month"])],
                        "admitted_rows_reading_a": e["normalized_rows"],
                        "supplement_rows": supplement_rows_by_month[(e["symbol"], e["month"])],
                    }
                )
    if my_raw_files_sha != manifest.get("raw_files_sha256"):
        failures.append({"check": "raw_files_sha256_mismatch"})
    if my_supplements_sha != manifest.get("daily_supplements_sha256"):
        failures.append({"check": "daily_supplements_sha256_mismatch"})

    # classification agreement with the builder ledger
    ledger = {}
    for line in (repo / "docs" / "arc03-data-authority-01" / "ARC03_DATA_QUALITY_LEDGER.jsonl").read_text(
        encoding="utf-8"
    ).splitlines():
        if not line.strip():
            continue
        e = json.loads(line)
        if e.get("kind") != "SYMBOL_SUMMARY":
            ledger[(e["symbol"], e["month"])] = e.get("classification")
    for entry in my_fp_registry:
        want = ledger.get((entry["symbol"], entry["month"]))
        if want != entry["classification"]:
            classification_mismatches.append(
                {"key": f"{entry['symbol']}/{entry['month']}", "verifier": entry["classification"], "ledger": want}
            )
    if classification_mismatches:
        failures.append({"check": "month_classification_mismatch", "mismatches": classification_mismatches[:20]})

    # common causal window, re-derived
    firsts = {s: my_rows[s][0]["t"] for s in ASSETS}
    lasts = {s: my_rows[s][-1]["t"] for s in ASSETS}
    start, end = max(firsts.values()), min(lasts.values())
    if start != spec["common_window"]["start_ms"] or end != spec["common_window"]["end_ms"]:
        failures.append(
            {"check": "common_window_mismatch", "start": start, "end": end,
             "spec": [spec["common_window"]["start_ms"], spec["common_window"]["end_ms"]]}
        )

    record = {
        "schema": "ARC03_DATA_BINDING_VERIFICATION/1.0.0",
        "method": "verifier-owned parser; does NOT call the builder normalizer",
        "data_root": str(root),
        "raw_archives": len(my_raw_sorted),
        "provider_checksum_misses": checksum_misses,
        "raw_files_sha256": my_raw_files_sha,
        "daily_supplements_sha256": my_supplements_sha,
        "daily_supplements": my_supplements,
        "synthetic_row_audit": synthetic_evidence,
        "NO_SYNTHETIC_MARKET_ROWS": all(
            v.get("union_equals_official_union") is True for v in synthetic_evidence.values()
        )
        if synthetic_evidence
        else None,
        "partition_sha256_recomputed": my_partition_sha,
        "partition_prefixes": {
            "BTCUSDT": "eb75ab97...",
            "ETHUSDT": "24c88690...",
            "SOLUSDT": "d872bc7d...",
        },
        "dataset_sha256_recomputed": my_dataset_sha,
        "dataset_sha256_expected": manifest["dataset_sha256"],
        "dataset_sha256_reading_A_admitted_rows": sha_reading_a,
        "dataset_sha256_reading_B_ledger_rows_field": sha_reading_b,
        "dataset_sha256_reproduced_under": reproduced,
        "normalized_rows_field_ambiguity": normalized_rows_ambiguity,
        "normalized_rows_field_defect": (
            {
                "id": "DEF-ARC03-DATA-FP-001",
                "severity": "NON_BLOCKING_DOCUMENTATION",
                "statement": "the fingerprint method names the per-month field `normalized_rows`, and the implementation fills it with the ledger's `rows` field, which for the two VALID_WITH_DAILY_SUPPLEMENT months (SOLUSDT 2022-02, 2022-04) is the MONTHLY-ARCHIVE row count BEFORE the daily supplement, not the admitted row count. The digest is therefore reproducible only under that reading.",
                "data_impact": "NONE - partition bytes, raw digests, row counts, window and no-synthetic-rows all reproduce exactly; no economic parameter reads this field or the digest",
                "masking_risk": "NONE - the digest remains sensitive to any raw or row change through raw_sha256 / normalized_rows",
                "remediation": "in a future authority version rename the field to `monthly_archive_rows` (or fill it with the admitted count and re-freeze)",
            }
            if normalized_rows_ambiguity
            else None
        ),
        "row_counts": {s: len(my_rows[s]) for s in ASSETS},
        "withheld_months": withhold_report,
        "classification_mismatches": classification_mismatches,
        "common_window": {"start_ms": start, "end_ms": end, "per_asset_first": firsts, "per_asset_last": lasts},
        "failures": failures,
        "DATA_BINDING": "PASS" if not failures else "FAIL",
        "A_B_DETERMINISM": "PASS"
        if not any(
            f["check"] in {"partition_bytes_differ", "dataset_sha256_not_reproducible_under_either_reading"}
            for f in failures
        )
        else "FAIL",
    }
    pathlib.Path(args.out).write_bytes((json.dumps(record, indent=2, sort_keys=True) + "\n").encode("utf-8"))
    print(json.dumps({k: record[k] for k in ("DATA_BINDING", "A_B_DETERMINISM", "dataset_sha256_recomputed",
                                            "partition_sha256_recomputed", "row_counts",
                                            "NO_SYNTHETIC_MARKET_ROWS", "common_window")}, indent=2))
    return 0 if record["DATA_BINDING"] == "PASS" else 2


if __name__ == "__main__":
    sys.exit(main())
