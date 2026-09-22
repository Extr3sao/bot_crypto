"""Full OI metrics archive ingestion (OI-FULL-HISTORY-FREEZE-01 Track A).

Downloads the official Binance USD-M daily metrics archives (zip + .CHECKSUM
sha256 sidecar) for BTCUSDT/ETHUSDT/SOLUSDT over their authoritative ranges,
verifies EVERY file against its sidecar, retries failures, and skips files
already verified on disk. Provider-original files are never modified.

Usage:
    python scripts/download_oi_full_history.py --symbol BTCUSDT
    python scripts/download_oi_full_history.py --symbol all
"""

from __future__ import annotations

import argparse
import concurrent.futures as cf
import hashlib
import json
import subprocess
import sys
import time
from datetime import date, timedelta
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
RAW = REPO / "data" / "raw" / "binance_um" / "metrics"
OUT_DIR = REPO / "docs" / "external-audit-01" / "oi-full-history-01"
BASE = "https://s3-ap-northeast-1.amazonaws.com/data.binance.vision"
NS_PREFIX = "data/futures/um/daily/metrics"

# Authoritative per-asset ranges from DATA_ARCHIVE_COVERAGE_MATRIX.json (2026-09-11 probe)
RANGES: dict[str, tuple[str, str]] = {
    "BTCUSDT": ("2020-09-01", "2026-09-10"),
    "ETHUSDT": ("2021-12-01", "2026-09-10"),
    "SOLUSDT": ("2021-12-01", "2026-09-10"),
}
WORKERS = 8
RETRIES = 3


def daterange(d0: str, d1: str) -> list[str]:
    a = date.fromisoformat(d0)
    b = date.fromisoformat(d1)
    return [(a + timedelta(days=i)).isoformat() for i in range((b - a).days + 1)]


def _curl(url: str, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".part")
    cmd = [
        "curl",
        "-sS",
        "--fail",
        "--max-time",
        "60",
        "--retry",
        str(RETRIES),
        "--retry-delay",
        "2",
        "-o",
        str(tmp),
        url,
    ]
    for attempt in range(1, RETRIES + 1):
        r = subprocess.run(cmd, capture_output=True, text=True)
        if r.returncode == 0 and tmp.exists() and tmp.stat().st_size > 0:
            tmp.replace(dest)
            return
        time.sleep(1.5 * attempt)
    tmp.unlink(missing_ok=True)
    raise RuntimeError(f"download failed after {RETRIES} attempts: {url}: {r.stderr.strip()[:200]}")


def verify_one(zip_path: Path) -> tuple[Path, bool, str]:
    sidecar = zip_path.with_name(zip_path.name + ".CHECKSUM")
    if not sidecar.exists():
        return zip_path, False, "MISSING_CHECKSUM"
    expected = sidecar.read_text(encoding="utf-8", errors="replace").strip().split()[0]
    actual = hashlib.sha256(zip_path.read_bytes()).hexdigest()
    return zip_path, actual == expected, actual


def process_day(symbol: str, day: str) -> dict[str, object]:
    name = f"{symbol}-metrics-{day}.zip"
    zip_path = RAW / symbol / name
    url = f"{BASE}/{NS_PREFIX}/{symbol}/{name}"
    outcome: dict[str, object] = {"symbol": symbol, "day": day, "file": name}
    # skip if already present and verifies
    if zip_path.exists():
        _, ok, _ = verify_one(zip_path)
        if ok:
            outcome.update(status="ALREADY_VERIFIED", downloaded=False, checksum="PASS")
            return outcome
    try:
        _curl(url, zip_path)
        _curl(url + ".CHECKSUM", zip_path.with_name(name + ".CHECKSUM"))
    except RuntimeError as e:
        outcome.update(status="DOWNLOAD_FAILED", error=str(e), checksum="UNKNOWN")
        return outcome
    _, ok, _ = verify_one(zip_path)
    if not ok:
        # one full re-download cycle before declaring failure (incomplete-download case)
        try:
            _curl(url, zip_path)
            _curl(url + ".CHECKSUM", zip_path.with_name(name + ".CHECKSUM"))
            _, ok, _ = verify_one(zip_path)
        except RuntimeError:
            ok = False
    outcome.update(
        status="OK" if ok else "CHECKSUM_FAIL", downloaded=True, checksum="PASS" if ok else "FAIL"
    )
    return outcome


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--symbol", choices=(*RANGES, "all"), required=True)
    args = ap.parse_args(argv)
    symbols = list(RANGES) if args.symbol == "all" else [args.symbol]

    results: list[dict[str, object]] = []
    for sym in symbols:
        d0, d1 = RANGES[sym]
        days = daterange(d0, d1)
        print(f"[{sym}] {len(days)} days {d0}..{d1}", flush=True)
        t0 = time.time()
        with cf.ThreadPoolExecutor(max_workers=WORKERS) as ex:
            futs = [ex.submit(process_day, sym, d) for d in days]
            for i, fut in enumerate(cf.as_completed(futs), 1):
                res = fut.result()
                results.append(res)
                if res["status"] not in ("OK", "ALREADY_VERIFIED"):
                    print(f"  !! {res['file']}: {res['status']}", flush=True)
                if i % 250 == 0:
                    print(f"  {i}/{len(days)} ({time.time() - t0:.0f}s)", flush=True)
        dt = time.time() - t0
        ok = sum(
            1 for r in results if r["symbol"] == sym and r["status"] in ("OK", "ALREADY_VERIFIED")
        )
        print(f"[{sym}] done: {ok}/{len(days)} verified in {dt:.0f}s", flush=True)

    summary = {
        "checkpoint": "OI-FULL-HISTORY-FREEZE-01",
        "track": "A",
        "retrieval_date_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "source": "data.binance.vision official archive (USD-M daily metrics)",
        "files_expected": sum(len(daterange(*RANGES[s])) for s in symbols),
        "files_downloaded": sum(1 for r in results if r.get("downloaded")),
        "files_already_verified": sum(1 for r in results if r["status"] == "ALREADY_VERIFIED"),
        "files_checksum_pass": sum(1 for r in results if r.get("checksum") == "PASS"),
        "files_checksum_fail": sum(1 for r in results if r.get("checksum") == "FAIL"),
        "files_download_failed": sum(1 for r in results if r["status"] == "DOWNLOAD_FAILED"),
        "missing_dates": [r["day"] for r in results if r["status"] == "DOWNLOAD_FAILED"],
        "checksum_fail_dates": [r["day"] for r in results if r.get("checksum") == "FAIL"],
        "per_symbol": {
            s: {
                "expected": len(daterange(*RANGES[s])),
                "pass": sum(1 for r in results if r["symbol"] == s and r.get("checksum") == "PASS"),
            }
            for s in symbols
        },
        "results": sorted(results, key=lambda r: (str(r["symbol"]), str(r["day"]))),
    }
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out = OUT_DIR / "DOWNLOAD_SUMMARY.json"
    out.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"summary -> {out}")
    return (
        0 if (summary["files_checksum_fail"] == 0 and summary["files_download_failed"] == 0) else 1
    )


if __name__ == "__main__":
    sys.exit(main())
