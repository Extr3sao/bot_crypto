#!/usr/bin/env python
"""ARC-03 official Binance USD-M 5m kline acquisition (official bytes only).

Source: https://data.binance.vision  (official Binance public market-data archive)
Path:   /data/futures/um/monthly/klines/{SYMBOL}/5m/{SYMBOL}-5m-{YYYY-MM}.zip
        + the provider's own .CHECKSUM sidecar (SHA256) for every archive.

Modes:
    --probe     HEAD-probe monthly archive availability per symbol/month, write
                ARC03_PROVIDER_COVERAGE.json (provider availability only).
    --download  download every available archive, verify the provider CHECKSUM,
                and append to the append-only raw ledger (resumable, idempotent).

No credentials, no third-party reconstruction, no normalized data written here.
Window selection depends only on provider availability / common coverage.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import datetime as dt
import hashlib
import json
import pathlib
import sys
import urllib.error
import urllib.request
from typing import Any

REPO = pathlib.Path(__file__).resolve().parents[1]
BASE = "https://data.binance.vision/data/futures/um"
INTERVAL = "5m"
SYMBOLS = ("BTCUSDT", "ETHUSDT", "SOLUSDT")
PROBE_START = (2019, 1)
PROBE_END = (2026, 9)

RAW_ROOT = REPO / "data" / "raw" / "binance_um" / "arc03"
DAILY_RAW_ROOT = REPO / "data" / "raw" / "binance_um" / "arc03_daily"
EVID = REPO / "docs" / "arc03-data-authority-01"
RAW_LEDGER = EVID / "ARC03_RAW_LEDGER.jsonl"
COVERAGE = EVID / "ARC03_PROVIDER_COVERAGE.json"
SUPPLEMENT = EVID / "ARC03_PROVIDER_COVERAGE_SUPPLEMENT.json"

sys.path.insert(0, str(REPO / "src"))
from trading_bot.research.arc03.arc03_normalize import (  # noqa: E402
    classify_month,
    day_shortfalls,
    parse_month,
)

USER_AGENT = "arc03-research/1.0 (official archive acquisition)"


def months(start: tuple[int, int], end: tuple[int, int]) -> list[str]:
    y, m = start
    out: list[str] = []
    while (y, m) <= end:
        out.append(f"{y:04d}-{m:02d}")
        m += 1
        if m == 13:
            y, m = y + 1, 1
    return out


def url_for(symbol: str, month: str, *, monthly: bool = True) -> str:
    if monthly:
        return f"{BASE}/monthly/klines/{symbol}/{INTERVAL}/{symbol}-{INTERVAL}-{month}.zip"
    return f"{BASE}/daily/klines/{symbol}/{INTERVAL}/{symbol}-{INTERVAL}-{month}.zip"


def fetch(url: str, *, timeout: int = 60) -> tuple[int, bytes]:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, resp.read()
    except urllib.error.HTTPError as exc:
        return exc.code, b""
    except Exception as exc:  # network/timeout
        return -1, str(exc).encode()


def probe_one(symbol: str, month: str) -> dict:
    url = url_for(symbol, month)
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT}, method="HEAD")
    try:
        with urllib.request.urlopen(req, timeout=45) as resp:
            return {
                "symbol": symbol,
                "month": month,
                "available": resp.status == 200,
                "content_length": int(resp.headers.get("Content-Length") or 0),
                "last_modified": resp.headers.get("Last-Modified"),
                "http_status": resp.status,
            }
    except urllib.error.HTTPError as exc:
        return {"symbol": symbol, "month": month, "available": False, "http_status": exc.code, "content_length": 0}
    except Exception as exc:
        return {"symbol": symbol, "month": month, "available": False, "http_status": -1, "error": str(exc)[:200]}


def cmd_probe() -> int:
    ms = months(PROBE_START, PROBE_END)
    tasks = [(s, m) for s in SYMBOLS for m in ms]
    results: list[dict] = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        for r in pool.map(lambda t: probe_one(*t), tasks):
            results.append(r)
    by_symbol: dict[str, list[dict]] = {s: [] for s in SYMBOLS}
    for r in results:
        by_symbol[r["symbol"]].append(r)
    summary: dict[str, dict] = {}
    for s in SYMBOLS:
        avail = sorted(r["month"] for r in by_symbol[s] if r["available"])
        missing = sorted(r["month"] for r in by_symbol[s] if not r["available"])
        summary[s] = {
            "available_months": len(avail),
            "first_available_month": avail[0] if avail else None,
            "last_available_month": avail[-1] if avail else None,
            "internally_missing_months": [
                m for m in missing if avail and avail[0] < m < avail[-1]
            ],
            "content_length_bytes_total": sum(r["content_length"] for r in by_symbol[s] if r["available"]),
        }
    COVERAGE.parent.mkdir(parents=True, exist_ok=True)
    COVERAGE.write_text(
        json.dumps(
            {
                "source": "https://data.binance.vision (official Binance public archive)",
                "family": "futures/um/monthly/klines",
                "interval": INTERVAL,
                "symbols": list(SYMBOLS),
                "probe_start_month": f"{PROBE_START[0]:04d}-{PROBE_START[1]:02d}",
                "probe_end_month": f"{PROBE_END[0]:04d}-{PROBE_END[1]:02d}",
                "probe_method": "HTTP HEAD per symbol/month; availability only (no data content inspected)",
                "per_symbol": summary,
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


def _download_one(symbol: str, month: str, retrieved_utc: str) -> dict:
    url = url_for(symbol, month)
    status, payload = fetch(url)
    if status != 200 or not payload:
        return {"symbol": symbol, "month": month, "url": url, "status": f"HTTP_{status}", "verified": False, "retrieved_utc": retrieved_utc}
    cs_status, cs_payload = fetch(url + ".CHECKSUM")
    expected = None
    if cs_status == 200 and cs_payload:
        expected = cs_payload.decode("utf-8", "replace").strip().split()[0]
    actual = hashlib.sha256(payload).hexdigest()
    out_dir = RAW_ROOT / symbol / month
    out_dir.mkdir(parents=True, exist_ok=True)
    zip_path = out_dir / f"{symbol}-{INTERVAL}-{month}.zip"
    if not (zip_path.exists() and hashlib.sha256(zip_path.read_bytes()).hexdigest() == actual):
        zip_path.write_bytes(payload)
    if expected:
        (out_dir / (zip_path.name + ".CHECKSUM")).write_text(f"{expected}  {zip_path.name}\n", encoding="utf-8")
    return {
        "symbol": symbol,
        "month": month,
        "url": url,
        "source": "data.binance.vision:futures/um/monthly/klines",
        "raw_path": str(zip_path.relative_to(REPO)).replace("\\", "/"),
        "size_bytes": len(payload),
        "provider_checksum_sidecar": bool(expected),
        "provider_checksum_sha256": expected,
        "sha256": actual,
        "checksum_match": (expected == actual) if expected else None,
        "status": "VERIFIED" if (expected == actual) else ("UNVERIFIED_NO_SIDECAR" if not expected else "CHECKSUM_MISMATCH"),
        "verified": bool(expected == actual),
        "retrieved_utc": retrieved_utc,
    }


def cmd_download() -> int:
    coverage = json.loads(COVERAGE.read_text(encoding="utf-8"))
    EVID.mkdir(parents=True, exist_ok=True)
    ledger_path = RAW_LEDGER
    done: set[tuple[str, str]] = set()
    if ledger_path.exists():
        for line in ledger_path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                e = json.loads(line)
                if e.get("status") == "VERIFIED":
                    done.add((e["symbol"], e["month"]))
    tasks: list[tuple[str, str]] = []
    for symbol in SYMBOLS:
        info = coverage["per_symbol"][symbol]
        if not info["available_months"]:
            continue
        first = info["first_available_month"]
        last = info["last_available_month"]
        for month in months(tuple(int(x) for x in first.split("-")), tuple(int(x) for x in last.split("-"))):
            if (symbol, month) not in done:
                tasks.append((symbol, month))
    retrieved = dt.datetime.now(tz=dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    entries: list[dict] = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        for e in pool.map(lambda t: _download_one(t[0], t[1], retrieved), tasks):
            entries.append(e)
            print(f"{e['symbol']} {e['month']} {e.get('size_bytes', 0)} bytes status={e['status']}", flush=True)
    entries.sort(key=lambda e: (e["symbol"], e["month"]))
    with ledger_path.open("a", encoding="utf-8", newline="\n") as fh:
        for e in entries:
            fh.write(json.dumps(e, sort_keys=True, separators=(",", ":")) + "\n")
    bad = [e for e in entries if not e.get("verified")]
    total = sum(e.get("size_bytes", 0) for e in entries)
    print(json.dumps({"new_entries": len(entries), "unverified": len(bad), "bytes_downloaded": total}, indent=2))
    return 0 if not bad else 1


def _download_one_day(symbol: str, date: str, retrieved_utc: str, *, for_month: str) -> dict:
    url = url_for(symbol, date, monthly=False)
    status, payload = fetch(url)
    if status != 200 or not payload:
        return {
            "symbol": symbol,
            "granularity": "daily",
            "date": date,
            "supplement_for_month": for_month,
            "url": url,
            "status": f"HTTP_{status}",
            "verified": False,
            "retrieved_utc": retrieved_utc,
        }
    cs_status, cs_payload = fetch(url + ".CHECKSUM")
    expected = cs_payload.decode("utf-8", "replace").strip().split()[0] if (cs_status == 200 and cs_payload) else None
    actual = hashlib.sha256(payload).hexdigest()
    out_dir = DAILY_RAW_ROOT / symbol / date
    out_dir.mkdir(parents=True, exist_ok=True)
    zip_path = out_dir / f"{symbol}-{INTERVAL}-{date}.zip"
    if not (zip_path.exists() and hashlib.sha256(zip_path.read_bytes()).hexdigest() == actual):
        zip_path.write_bytes(payload)
    if expected:
        (out_dir / (zip_path.name + ".CHECKSUM")).write_text(f"{expected}  {zip_path.name}\n", encoding="utf-8")
    return {
        "symbol": symbol,
        "granularity": "daily",
        "date": date,
        "supplement_for_month": for_month,
        "purpose": "coverage_gap_supplement",
        "url": url,
        "source": "data.binance.vision:futures/um/daily/klines",
        "raw_path": str(zip_path.relative_to(REPO)).replace("\\", "/"),
        "size_bytes": len(payload),
        "provider_checksum_sidecar": bool(expected),
        "provider_checksum_sha256": expected,
        "sha256": actual,
        "checksum_match": (expected == actual) if expected else None,
        "status": "VERIFIED" if (expected == actual) else ("UNVERIFIED_NO_SIDECAR" if not expected else "CHECKSUM_MISMATCH"),
        "verified": bool(expected == actual),
        "retrieved_utc": retrieved_utc,
    }


def cmd_supplement() -> int:
    """Close monthly coverage shortfalls with the same provider's DAILY archives.

    Only months that fail the authority contract as ``INVALID_GAP`` are considered; a
    month that already validates is never supplemented (no duplicate dataset).
    """
    retrieved = dt.datetime.now(tz=dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    analysis: dict[str, Any] = {
        "source": "https://data.binance.vision (official Binance public archive)",
        "method": (
            "parse each monthly archive; for months classified INVALID_GAP, compute the per-day "
            "5m slot shortfall and retrieve exactly those daily archives (CHECKSUM-verified)"
        ),
        "per_symbol": {},
    }
    new_entries: list[dict[str, Any]] = []
    for symbol in SYMBOLS:
        sym_dir = RAW_ROOT / symbol
        if not sym_dir.exists():
            continue
        months_found: list[dict[str, Any]] = []
        first_seen: int | None = None
        tasks: list[tuple[str, str]] = []
        for md in sorted(p for p in sym_dir.iterdir() if p.is_dir()):
            month = md.name
            zp = md / f"{symbol}-{INTERVAL}-{month}.zip"
            parsed = parse_month(zp)
            entry = parsed["entry"]
            is_first = first_seen is None
            cls = classify_month(entry, month, is_first_month=is_first)
            rows = parsed["rows_list"]
            if cls in {"VALID", "VALID_INITIAL_PARTIAL"} and rows:
                first_seen = rows[0]["t"]
            if cls != "INVALID_GAP":
                continue
            shortfalls = day_shortfalls(rows, month, is_first_month=is_first)
            months_found.append({"month": month, "missing_days": sorted(shortfalls), "missing_slots": shortfalls})
            tasks.extend((symbol, date) for date in sorted(shortfalls))
        entries = [_download_one_day(s, d, retrieved, for_month=next(m["month"] for m in months_found if m["month"] == d[:7])) for s, d in tasks]
        for e in entries:
            print(f"{e['symbol']} {e.get('date')} {e.get('size_bytes', 0)} bytes status={e['status']}", flush=True)
        new_entries.extend(entries)
        analysis["per_symbol"][symbol] = {
            "gap_months": months_found,
            "daily_archives_retrieved": len(entries),
            "daily_archives_verified": sum(1 for e in entries if e.get("verified")),
            "retrieval": entries,
        }

    new_entries.sort(key=lambda e: (e["symbol"], e.get("date") or ""))
    EVID.mkdir(parents=True, exist_ok=True)
    existing = set()
    if RAW_LEDGER.exists():
        for line in RAW_LEDGER.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            e = json.loads(line)
            if e.get("granularity") == "daily" and e.get("status") == "VERIFIED":
                existing.add((e["symbol"], e["date"]))
    appended = [e for e in new_entries if (e["symbol"], e.get("date")) not in existing]
    if appended:
        with RAW_LEDGER.open("a", encoding="utf-8", newline="\n") as fh:
            for e in appended:
                fh.write(json.dumps(e, sort_keys=True, separators=(",", ":")) + "\n")
    analysis["raw_ledger_appended"] = len(appended)
    bad = [e for e in new_entries if not e.get("verified")]
    analysis["unverified"] = len(bad)
    SUPPLEMENT.write_text(json.dumps(analysis, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"gap_months": {s: v["gap_months"] for s, v in analysis["per_symbol"].items()}}, indent=2))
    print(json.dumps({"retrieved": len(new_entries), "appended": len(appended), "unverified": len(bad)}, indent=2))
    analysis["unverified"] = len(bad)
    return 0 if not bad else 1


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--probe", action="store_true")
    ap.add_argument("--download", action="store_true")
    ap.add_argument("--supplement", action="store_true")
    args = ap.parse_args(argv)
    if args.probe:
        return cmd_probe()
    if args.download:
        return cmd_download()
    if args.supplement:
        return cmd_supplement()
    ap.print_help()
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
