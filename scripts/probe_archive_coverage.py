"""Metadata-only archive coverage probe for ALPHA-DATA-ADMISSION-01 (Track D/E).

Lists the official Binance Vision S3 bucket (data.binance.vision) for
aggTrades (daily+monthly) and metrics (daily) across the three target symbols
and derives FIRST/LAST availability, file counts, missing dates, CHECKSUM
availability and exact compressed-size sums for full-history cost estimates.

LISTINGS ONLY: no archive files are downloaded. Emits
docs/external-audit-01/data-admission-01/DATA_ARCHIVE_COVERAGE_MATRIX.json.
"""

from __future__ import annotations

import json
import re
import urllib.request
import xml.etree.ElementTree as ET
from datetime import date, timedelta
from pathlib import Path

BASE = "https://s3-ap-northeast-1.amazonaws.com/data.binance.vision"
NS = {"s3": "http://s3.amazonaws.com/doc/2006-03-01/"}
REPO = Path(__file__).resolve().parents[1]
OUT = REPO / "docs" / "external-audit-01" / "data-admission-01" / "DATA_ARCHIVE_COVERAGE_MATRIX.json"
SYMBOLS = ("BTCUSDT", "ETHUSDT", "SOLUSDT")
RETRIEVAL_UTC = "2026-09-11"


def list_keys(prefix: str, timeout: int = 30) -> list[dict[str, object]]:
    """Paginate the S3 XML listing for a prefix; return {key, size} for files."""
    out: list[dict[str, object]] = []
    marker = ""
    while True:
        url = (
            f"{BASE}?delimiter=/&max-keys=1000&prefix={prefix}"
            + (f"&marker={marker}" if marker else "")
        )
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            root = ET.fromstring(resp.read())
        contents = root.findall("s3:Contents", NS)
        for c in contents:
            key = c.findtext("s3:Key", default="", namespaces=NS)
            size = int(c.findtext("s3:Size", default="0", namespaces=NS))
            out.append({"key": key, "size": size})
        truncated = root.findtext("s3:IsTruncated", default="false", namespaces=NS) == "true"
        if not truncated:
            break
        next_marker = root.findtext("s3:NextMarker", default="", namespaces=NS)
        if not next_marker:
            next_marker = out[-1]["key"] if out else ""
        marker = str(next_marker)
    return out


def date_from_key(key: str, kind: str) -> str:
    """Extract YYYY-MM-DD (daily) or YYYY-MM (monthly) from a listing key."""
    name = key.rsplit("/", 1)[-1]
    if kind == "daily":
        m = re.search(r"(\d{4}-\d{2}-\d{2})\.zip$", name)
    else:
        m = re.search(r"(\d{4}-\d{2})\.zip$", name)
    return m.group(1) if m else ""


def coverage(kind: str, cadence: str, symbol: str, family_prefix: str) -> dict[str, object]:
    prefix = f"data/futures/um/{cadence}/{family_prefix}/{symbol}/"
    entries = list_keys(prefix)
    all_zips = [e for e in entries if str(e["key"]).endswith(".zip")]
    # dated archives only; bucket also hosts non-dated spark part-*.zip chunks
    zips = [e for e in all_zips if re.search(r"\d{4}-\d{2}(-\d{2})?\.zip$", str(e["key"]).rsplit("/", 1)[-1])]
    non_dated_part_files = len(all_zips) - len(zips)
    checksums = {str(e["key"]) for e in entries if str(e["key"]).endswith(".zip.CHECKSUM")}
    dates = sorted({date_from_key(str(e["key"]), cadence) for e in zips})
    size_sum = sum(int(e["size"]) for e in zips)
    # expected-file continuity between first and last available date
    missing: list[str] = []
    if dates:
        if cadence == "daily":
            d0 = date.fromisoformat(dates[0])
            d1 = date.fromisoformat(dates[-1])
            expected = {
                (d0 + timedelta(days=i)).isoformat()
                for i in range((d1 - d0).days + 1)
            }
        else:
            y0, m0 = int(dates[0][:4]), int(dates[0][5:7])
            y1, m1 = int(dates[-1][:4]), int(dates[-1][5:7])
            expected = set()
            y, m = y0, m0
            while (y, m) <= (y1, m1):
                expected.add(f"{y:04d}-{m:02d}")
                m += 1
                if m == 13:
                    y, m = y + 1, 1
        missing = sorted(expected - set(dates))
    return {
        "listing_prefix": prefix,
        "first_available": dates[0] if dates else None,
        "last_available": dates[-1] if dates else None,
        "zip_files": len(zips),
        "non_dated_part_files": non_dated_part_files,
        "checksum_files": sum(1 for k in checksums if k[:-len(".CHECKSUM")] + ".zip" in {str(e["key"]) for e in zips}),
        "checksum_coverage": "FULL" if zips and len(checksums) >= len(zips) else ("PARTIAL" if checksums else "NONE"),
        "missing_dates_or_months": missing[:50],
        "missing_count": len(missing),
        "compressed_bytes_total": size_sum,
        "retrieval_date_utc": RETRIEVAL_UTC,
    }


def main() -> None:
    matrix: dict[str, object] = {
        "checkpoint": "ALPHA-DATA-ADMISSION-01",
        "probe_type": "METADATA_LISTING_ONLY (no archive download)",
        "bucket": "data.binance.vision (official Binance public data)",
        "retrieval_date_utc": RETRIEVAL_UTC,
        "aggTrades": {},
        "open_interest_metrics": {},
    }
    for sym in SYMBOLS:
        for cadence in ("daily", "monthly"):
            matrix["aggTrades"][f"{sym}_{cadence}"] = coverage(cadence, cadence, sym, "aggTrades")
        matrix["open_interest_metrics"][f"{sym}_daily"] = coverage("daily", "daily", sym, "metrics")
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(matrix, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"written: {OUT}")
    for fam in ("aggTrades", "open_interest_metrics"):
        for k, v in matrix[fam].items():
            assert isinstance(v, dict)
            print(
                f"{fam:24s} {k:18s} first={v['first_available']} last={v['last_available']} "
                f"zips={v['zip_files']} checksum={v['checksum_coverage']} "
                f"missing={v['missing_count']} bytes={v['compressed_bytes_total']:,}"
            )


if __name__ == "__main__":
    main()
