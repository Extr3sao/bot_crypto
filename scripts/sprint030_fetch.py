"""RFC-030 — External-alpha reproduction: daily crypto panel acquisition.

READ-ONLY RESEARCH ACQUISITION.  Materialises a *multi-coin* daily panel from
the official public Binance archive so that externally documented
cross-sectional and time-series edges can be reproduced faithfully:

    data/spot/monthly/klines/<SYMBOL>/1d/<SYMBOL>-1d-<YYYY-MM>.zip

Only OHLCV + quote volume + trade count are kept (what the archived 1d klines
offer).  Every symbol that the archive serves is downloaded; a 404 (symbol not
listed that month) is recorded as a *missing month*, never imputed.

SURVIVORSHIP (§57)
    The universe deliberately includes coins that were later delisted or
    collapsed (FTTUSDT, LUNAUSDT).  A purely current-listing universe would be
    survivorship-biased; the inclusion is disclosed in the DATA_AUDIT and the
    limitation (mainstream coins with surviving archives) is stated.

Epoch units are normalised to MILLISECONDS (the 1d archive is ms today, but the
unit is asserted rather than assumed).
"""

from __future__ import annotations

import csv
import io
import json
import time
import urllib.error
import urllib.request
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import numpy as np
from numpy.typing import NDArray

REPO = Path(__file__).resolve().parents[1]
OUT_DIR = REPO / "reports" / "external-alpha"
CACHE_DIR = OUT_DIR / "cache"

# A broad, liquid USDT spot universe.  Two dead names are kept on purpose.
UNIVERSE = (
    "BTCUSDT", "ETHUSDT", "BNBUSDT", "XRPUSDT", "ADAUSDT", "SOLUSDT",
    "DOGEUSDT", "DOTUSDT", "LTCUSDT", "LINKUSDT", "BCHUSDT", "XLMUSDT",
    "TRXUSDT", "ETCUSDT", "EOSUSDT", "XTZUSDT", "ZECUSDT", "DASHUSDT",
    "NEOUSDT", "ATOMUSDT", "VETUSDT", "FILUSDT", "THETAUSDT", "ALGOUSDT",
    "AVAXUSDT", "MATICUSDT", "FTTUSDT", "LUNAUSDT", "ICPUSDT", "SHIBUSDT",
)

START = date(2018, 1, 1)
END = date(2026, 9, 30)

SPOT_KLINES_BASE = "https://data.binance.vision/data/spot/monthly/klines"
US_THRESHOLD = 10**14   # ms epoch ~1.7e12; us epoch ~1.7e15

KLINES_COLUMNS = (
    "open_time", "open", "high", "low", "close", "volume", "close_time",
    "quote_volume", "count", "taker_buy_volume", "taker_buy_quote_volume", "ignore",
)


def _http_get(url: str, timeout: float = 40.0, retries: int = 3) -> bytes | None:
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


def _unzip_single_csv(payload: bytes) -> str:
    with zipfile.ZipFile(io.BytesIO(payload)) as zf:
        name = zf.namelist()[0]
        return zf.read(name).decode("utf-8")


def _month_iter(start: date, end: date) -> list[str]:
    out = []
    y, m = start.year, start.month
    while (y, m) <= (end.year, end.month):
        out.append(f"{y:04d}-{m:02d}")
        m += 1
        if m > 12:
            m = 1
            y += 1
    return out


def fetch_symbol(symbol: str) -> dict[str, Any]:
    rows: list[list[str]] = []
    missing: list[str] = []
    present: list[str] = []
    for ym in _month_iter(START, END):
        url = f"{SPOT_KLINES_BASE}/{symbol}/1d/{symbol}-1d-{ym}.zip"
        payload = _http_get(url)
        if payload is None:
            missing.append(ym)
            continue
        present.append(ym)
        text = _unzip_single_csv(payload)
        parsed = list(csv.reader(io.StringIO(text)))
        if parsed and parsed[0] and parsed[0][0] == "open_time":
            parsed = parsed[1:]
        rows.extend(r for r in parsed if r)
    return {"symbol": symbol, "rows": rows, "missing_months": missing,
            "present_months": present}


def canonicalize_daily(rows: list[list[str]]) -> dict[str, NDArray[Any]]:
    start_ms = int(datetime(START.year, START.month, START.day, tzinfo=UTC).timestamp() * 1000)
    end_ms = int(datetime(END.year, END.month, END.day, tzinfo=UTC).timestamp() * 1000)
    seen: dict[int, tuple[float, float, float, float, float, float, float]] = {}
    unit_hist: dict[str, int] = {}
    for r in rows:
        try:
            raw = int(r[0])
            o, h, lo, c, v = (float(r[1]), float(r[2]), float(r[3]),
                              float(r[4]), float(r[5]))
            qv = float(r[7]) if len(r) > 7 and r[7] != "" else float("nan")
            cnt = float(r[8]) if len(r) > 8 and r[8] != "" else float("nan")
        except (ValueError, IndexError):
            continue
        if raw >= US_THRESHOLD:
            t = raw // 1000
            unit_hist["us"] = unit_hist.get("us", 0) + 1
        else:
            t = raw
            unit_hist["ms"] = unit_hist.get("ms", 0) + 1
        if start_ms <= t <= end_ms + 86_400_000:
            seen[t] = (o, h, lo, c, v, qv, cnt)
    ts = np.array(sorted(seen), dtype=np.int64)
    arrs = {k: np.array([seen[t][i] for t in ts], dtype=np.float64)
            for i, k in enumerate(("open", "high", "low", "close", "volume",
                                   "quote_volume", "trades"))}
    return {"open_time_ms": ts} | arrs | {
        "_unit_hist": np.array([json.dumps(unit_hist)]),
    }


def _save_npz(path: Path, cols: dict[str, NDArray[Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(path, **cols)


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    audit: dict[str, Any] = {
        "window": {"start": START.isoformat(), "end": END.isoformat()},
        "universe": list(UNIVERSE),
        "source": SPOT_KLINES_BASE + "/{symbol}/1d/{symbol}-1d-{YYYY-MM}.zip",
        "columns_documented": list(KLINES_COLUMNS),
        "survivorship_note": (
            "Universe includes delisted/collapsed names (FTTUSDT, LUNAUSDT). "
            "A current-listing-only universe would be survivorship-biased; the "
            "residual limitation (coins which never had a Binance archive) is "
            "disclosed in DATA_AUDIT."
        ),
        "assets": {},
    }

    def work(sym: str) -> tuple[str, dict[str, Any], dict[str, NDArray[Any]]]:
        raw = fetch_symbol(sym)
        canon = canonicalize_daily(raw["rows"])
        return sym, raw, canon

    with ThreadPoolExecutor(max_workers=6) as pool:
        futures = {pool.submit(work, s): s for s in UNIVERSE}
        for fut in as_completed(futures):
            sym = futures[fut]
            sym, raw, canon = fut.result()
            _save_npz(CACHE_DIR / f"daily_{sym}.npz", canon)
            n = int(canon["open_time_ms"].shape[0])
            audit["assets"][sym] = {
                "rows": n,
                "missing_months": len(raw["missing_months"]),
                "present_months": len(raw["present_months"]),
                "first_open_ms": int(canon["open_time_ms"][0]) if n else None,
                "last_open_ms": int(canon["open_time_ms"][-1]) if n else None,
                "epoch_unit_histogram": json.loads(str(canon["_unit_hist"][0])),
                "nan_quote_volume": int(np.isnan(canon["quote_volume"]).sum()),
            }
            print(f"[fetch030] {sym}: rows={n} months={len(raw['present_months'])}", flush=True)

    (OUT_DIR / "_fetch_source_audit.json").write_text(
        json.dumps(audit, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
    print("[fetch030] done", flush=True)


if __name__ == "__main__":
    main()
