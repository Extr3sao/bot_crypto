"""RFC-033 -- UM-perpetual data acquisition (READ-ONLY research acquisition).

Materialises, from the *already-supported* Binance venue (``data.binance.vision``,
the same source RFC-028 used for funding), the two series EXT-TSMOM-003 needs:

  * USD-M perpetual **1d klines**  (``futures/um/monthly/klines``)  -- the
    execution/signal instrument itself (signal instrument == execution
    instrument; no spot/perp porting).
  * USD-M perpetual **funding-rate history** (``futures/um/monthly/fundingRate``)
    -- the carry cashflow that must be accounted separately from price PnL.

The universe is *probed*, not assumed: the S3 bucket listing enumerates every
USDT-margined perpetual symbol ever published, and a symbol is futures-eligible
for this study iff a monthly kline archive exists for ``ELIGIBILITY_PROBE``.
That is a point-in-time rule (the archive emits a row only once the contract
existed); symbols that later delisted keep their files and are therefore
retained, which limits survivorship bias.

Output (gitignored cache, reproducible):
    reports/perp-tsmom/cache/perp_daily_<SYM>.npz   (open_time_ms, o,h,l,c,volume,quote_volume)
    reports/perp-tsmom/cache/funding_<SYM>.npz      (funding_time_ms, funding_rate, funding_interval_hours)
    reports/perp-tsmom/cache/_manifest.json
"""

from __future__ import annotations

import concurrent.futures as cf
import csv
import io
import json
import re
import threading
import time
import urllib.error
import urllib.request
import zipfile
from pathlib import Path
from typing import Any

import numpy as np

REPO = Path(__file__).resolve().parents[1]
OUT_DIR = REPO / "reports" / "perp-tsmom"
CACHE_DIR = OUT_DIR / "cache"

S3_BASE = ("https://s3-ap-northeast-1.amazonaws.com/data.binance.vision"
           "?delimiter=/&prefix=data/futures/um/monthly/klines/")
KLINES_URL = "https://data.binance.vision/data/futures/um/monthly/klines"
FUNDING_URL = "https://data.binance.vision/data/futures/um/monthly/fundingRate"

ELIGIBILITY_PROBE = "2021-06"
MONTH_START = (2019, 9)
MONTH_END = (2026, 9)

# Index / basket / non-single-asset products are excluded (not a spot-like asset;
# they are themselves portfolios, which would double-count exposure).
EXCLUDE_SUFFIXES = ("USDT",)
EXCLUDE = {"BTCDOMUSDT", "DEFIUSDT"}

KLINES_COLUMNS = ("open_time", "open", "high", "low", "close", "volume",
                  "close_time", "quote_volume", "count", "taker_buy_volume",
                  "taker_buy_quote_volume", "ignore")
FUNDING_COLUMNS = ("calc_time", "funding_interval_hours", "last_funding_rate")

_thread_local = threading.local()


def _http(url: str, timeout: float = 60.0, retries: int = 4) -> bytes | None:
    last: Exception | None = None
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(url, timeout=timeout) as resp:
                return bytes(resp.read())
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                return None
            last = exc
        except Exception as exc:
            last = exc
        time.sleep(0.4 * (attempt + 1))
    if last is not None:
        raise last
    return None


def list_symbols() -> list[str]:
    marker = ""
    out: list[str] = []
    while True:
        url = S3_BASE + (f"&marker={marker}" if marker else "")
        body = _http(url)
        if body is None:
            break
        text = body.decode("utf-8", "replace")
        out += re.findall(
            r"<Prefix>data/futures/um/monthly/klines/([^/]+)/</Prefix>", text)
        if "<IsTruncated>false</IsTruncated>" in text:
            break
        m = re.search(r"<NextMarker>([^<]+)</NextMarker>", text)
        if not m:
            break
        marker = m.group(1)
    return [s for s in out if any(s.endswith(sfx) for sfx in EXCLUDE_SUFFIXES)]


def _has_archive(sym: str, ym: str) -> bool:
    url = f"{KLINES_URL}/{sym}/1d/{sym}-1d-{ym}.zip"
    try:
        req = urllib.request.Request(url, method="HEAD")
        with urllib.request.urlopen(req, timeout=30) as resp:
            return bool(resp.status == 200)
    except Exception:
        return False


def eligible_universe() -> list[str]:
    syms = list_symbols()
    present: list[str] = []
    with cf.ThreadPoolExecutor(max_workers=24) as ex:
        for s, ok in zip(syms, ex.map(lambda s: _has_archive(s, ELIGIBILITY_PROBE), syms),
                         strict=True):
            if ok:
                present.append(s)
    return sorted(s for s in present if s not in EXCLUDE)


def _months() -> list[str]:
    out = []
    y, m = MONTH_START
    while (y, m) <= MONTH_END:
        out.append(f"{y:04d}-{m:02d}")
        m += 1
        if m == 13:
            y, m = y + 1, 1
    return out


def _read_zip_csv(blob: bytes) -> list[list[str]]:
    with zipfile.ZipFile(io.BytesIO(blob)) as zf:
        name = zf.namelist()[0]
        raw = zf.read(name).decode("utf-8", "replace")
    return [row for row in csv.reader(io.StringIO(raw)) if row]


def _fetch_klines(sym: str, ym: str) -> list[tuple[int, float, float, float, float, float, float]]:
    blob = _http(f"{KLINES_URL}/{sym}/1d/{sym}-1d-{ym}.zip")
    if blob is None:
        return []
    rows = _read_zip_csv(blob)
    out = []
    for r in rows:
        if r and r[0].lower().startswith("open_time"):
            continue
        try:
            ot = int(r[0])
        except ValueError:
            continue
        out.append((ot, float(r[1]), float(r[2]), float(r[3]), float(r[4]),
                    float(r[5]), float(r[7])))
    return out


def _fetch_funding(sym: str, ym: str) -> list[tuple[int, float, float]]:
    blob = _http(f"{FUNDING_URL}/{sym}/{sym}-fundingRate-{ym}.zip")
    if blob is None:
        return []
    rows = _read_zip_csv(blob)
    out = []
    for r in rows:
        if r and r[0].lower().startswith("calc_time"):
            continue
        try:
            ct = int(r[0])
        except ValueError:
            continue
        out.append((ct, float(r[1]), float(r[2])))
    return out


def fetch_symbol(sym: str) -> dict[str, Any]:
    klines: list[tuple[int, float, float, float, float, float, float]] = []
    funding: list[tuple[int, float, float]] = []
    for ym in _months():
        klines += _fetch_klines(sym, ym)
        funding += _fetch_funding(sym, ym)
    if klines:
        arr = np.asarray(sorted(set(klines)), dtype=np.float64)
        np.savez_compressed(
            CACHE_DIR / f"perp_daily_{sym}.npz",
            open_time_ms=arr[:, 0].astype(np.int64),
            open=arr[:, 1], high=arr[:, 2], low=arr[:, 3],
            close=arr[:, 4], volume=arr[:, 5], quote_volume=arr[:, 6])
    if funding:
        farr = np.asarray(sorted(set(funding)), dtype=np.float64)
        np.savez_compressed(
            CACHE_DIR / f"funding_{sym}.npz",
            funding_time_ms=farr[:, 0].astype(np.int64),
            funding_interval_hours=farr[:, 1], funding_rate=farr[:, 2])
    return {"symbol": 1, "klines": len(klines), "funding": len(funding)}


def main() -> int:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    universe = eligible_universe()
    print(f"eligible universe: {len(universe)} USDT perps", flush=True)
    (CACHE_DIR / "_universe.txt").write_text("\n".join(universe) + "\n", encoding="utf-8")
    summary: dict[str, dict[str, Any]] = {}
    done = 0
    with cf.ThreadPoolExecutor(max_workers=16) as ex:
        futs = {ex.submit(fetch_symbol, s): s for s in universe}
        for fut in cf.as_completed(futs):
            s = futs[fut]
            try:
                summary[s] = fut.result()
            except Exception as exc:
                summary[s] = {"error": str(exc)}
                print(f"  !! {s}: {exc}", flush=True)
            done += 1
            if done % 10 == 0:
                print(f"  {done}/{len(universe)}", flush=True)
    (CACHE_DIR / "_manifest.json").write_text(
        json.dumps({"eligibility_probe": ELIGIBILITY_PROBE, "universe": universe,
                    "per_symbol": summary}, indent=2, sort_keys=True) + "\n",
        encoding="utf-8")
    # re-probe the definite universe-from-disk
    n_perp = len(list(CACHE_DIR.glob("perp_daily_*.npz")))
    n_fund = len(list(CACHE_DIR.glob("funding_*.npz")))
    print(f"DONE: perp_daily files={n_perp} funding files={n_fund}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
