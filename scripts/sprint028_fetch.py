"""RFC-028 — Carry data acquisition + PIT canonicalization.

READ-ONLY RESEARCH ACQUISITION.  Materialises the *additional* series RFC-028
needs on top of the RFC-027 canonical cache:

  * SPOT 5m klines (``data/spot/monthly/klines``)  -- the long-spot leg.
  * UM-PERP funding-rate history (``data/futures/um/monthly/fundingRate``) --
    the carry cashflow AND its point-in-time signal.

The UM-perp 5m klines already exist in ``reports/positioning-data/cache``
(RFC-027) and are reused unchanged.

FUNDING PIT CONTRACT (§6, §7, §34)
    Each funding archive row is the FINAL REALIZED rate for the period that
    ENDS at ``calc_time`` (the payment time).  The final rate is only
    knowable at the end of the period, therefore:

        observation_time   = payment_time - interval_hours
        funding_period     = [observation_time, payment_time)
        known_time         = payment_time      (conservative)
        payment_time       = calc_time
        final_realized_rate= last_funding_rate

    A decision at time ``T`` may only use rows with ``payment_time <= T``.
    The realized rate is used for OUTCOME accounting (funding actually paid
    during a holding window) but never as a prior signal.

Window (§11): 2024-03-04 -> 2026-09-10, the expanded RFC-027 window, chosen
because every required series covers it.
"""

from __future__ import annotations

import csv
import io
import json
import time
import urllib.error
import urllib.request
import zipfile
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import numpy as np
from numpy.typing import NDArray

REPO = Path(__file__).resolve().parents[1]

CARRY_DIR = REPO / "reports" / "carry"
CACHE_DIR = CARRY_DIR / "cache"

ASSETS = ("BTCUSDT", "ETHUSDT", "SOLUSDT")

COMMON_START = date(2024, 3, 4)
COMMON_END = date(2026, 9, 10)

SPOT_KLINES_BASE = "https://data.binance.vision/data/spot/monthly/klines"
FUNDING_BASE = "https://data.binance.vision/data/futures/um/monthly/fundingRate"

KLINES_COLUMNS = (
    "open_time", "open", "high", "low", "close", "volume", "close_time",
    "quote_volume", "count", "taker_buy_volume", "taker_buy_quote_volume", "ignore",
)
FUNDING_COLUMNS = ("calc_time", "funding_interval_hours", "last_funding_rate")


# ---------------------------------------------------------------------------
# http helpers
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# spot klines
# ---------------------------------------------------------------------------

def fetch_spot_asset(symbol: str, start: date, end: date) -> dict[str, Any]:
    rows: list[list[str]] = []
    missing: list[str] = []
    for ym in _month_iter(start, end):
        url = f"{SPOT_KLINES_BASE}/{symbol}/5m/{symbol}-5m-{ym}.zip"
        payload = _http_get(url)
        if payload is None:
            missing.append(ym)
            continue
        text = _unzip_single_csv(payload)
        parsed = list(csv.reader(io.StringIO(text)))
        if parsed and parsed[0] and parsed[0][0] == "open_time":
            parsed = parsed[1:]
        rows.extend(r for r in parsed if r)
    return {"symbol": symbol, "rows": rows, "missing_months": missing}


US_THRESHOLD = 10**14   # a millisecond epoch is ~1.7e12; a microsecond epoch ~1.7e15


def canonicalize_spot_klines(rows: list[list[str]]) -> dict[str, NDArray[Any]]:
    """Canonicalize spot 5m klines to MILLISECOND open_time.

    DATA AUDIT FINDING: the official spot monthly archive switched its epoch
    UNIT from milliseconds (2024 files) to **microseconds** (2025+ files).  The
    raw value is normalised here and the unit era histogram is recorded so the
    change is visible, never silently mixed.
    """
    start_ms = int(datetime(COMMON_START.year, COMMON_START.month, COMMON_START.day,
                            tzinfo=UTC).timestamp() * 1000)
    end_ms = int(datetime(COMMON_END.year, COMMON_END.month, COMMON_END.day,
                          tzinfo=UTC).timestamp() * 1000)
    seen: dict[int, tuple[float, float, float, float, float]] = {}
    unit_hist: dict[str, int] = {}
    us_days: set[str] = set()
    for r in rows:
        try:
            raw = int(r[0])
            o, h, lo, c, v = (float(r[1]), float(r[2]), float(r[3]),
                              float(r[4]), float(r[5]))
        except (ValueError, IndexError):
            continue
        if raw >= US_THRESHOLD:
            t = raw // 1000
            unit_hist["us"] = unit_hist.get("us", 0) + 1
            us_days.add(datetime.fromtimestamp(t / 1000, tz=UTC).date().isoformat())
        else:
            t = raw
            unit_hist["ms"] = unit_hist.get("ms", 0) + 1
        # keep a small right-margin: we need bars whose CLOSE is <= end of window
        if start_ms <= t <= end_ms + 86_400_000:
            seen[t] = (o, h, lo, c, v)
    ts = np.array(sorted(seen), dtype=np.int64)
    arrs = {k: np.array([seen[t][i] for t in ts], dtype=np.float64)
            for i, k in enumerate(("open", "high", "low", "close", "volume"))}
    return {"open_time_ms": ts} | arrs | {
        "_unit_hist": np.array([json.dumps(unit_hist)]),
        "_first_us_day": np.array([min(us_days) if us_days else ""]),
    }


# ---------------------------------------------------------------------------
# funding rate
# ---------------------------------------------------------------------------

def fetch_funding_asset(symbol: str, start: date, end: date) -> dict[str, Any]:
    rows: list[list[str]] = []
    missing: list[str] = []
    for ym in _month_iter(start, end):
        url = f"{FUNDING_BASE}/{symbol}/{symbol}-fundingRate-{ym}.zip"
        payload = _http_get(url)
        if payload is None:
            missing.append(ym)
            continue
        text = _unzip_single_csv(payload)
        parsed = list(csv.reader(io.StringIO(text)))
        if parsed and parsed[0] and parsed[0][0] == "calc_time":
            parsed = parsed[1:]
        rows.extend(r for r in parsed if r)
    return {"symbol": symbol, "rows": rows, "missing_months": missing}


def canonicalize_funding(rows: list[list[str]]) -> dict[str, NDArray[Any]]:
    """PIT-canonicalize the funding archive (§6)."""
    seen: dict[int, tuple[float, float]] = {}   # payment_time -> (interval_h, rate)
    for r in rows:
        try:
            t = int(r[0])
            ih = float(r[1])
            rv = float(r[2])
        except (ValueError, IndexError):
            continue
        seen[t] = (ih, rv)
    ts = np.array(sorted(seen), dtype=np.int64)
    n = ts.shape[0]
    interval_h = np.zeros(n, dtype=np.float64)
    rate_arr = np.full(n, np.nan, dtype=np.float64)
    obs = np.zeros(n, dtype=np.int64)
    period_end = np.zeros(n, dtype=np.int64)
    known = np.zeros(n, dtype=np.int64)
    avail = np.zeros(n, dtype=np.int64)
    for i, t in enumerate(ts.tolist()):
        ih, rr = seen[t]
        interval_h[i] = ih
        rate_arr[i] = rr
        ms = int(ih * 3600 * 1000)
        obs[i] = t - ms                # observation_time = period start
        period_end[i] = t              # funding_period end
        known[i] = t                   # final rate only known at payment time
        avail[i] = t                   # available for signals at decisions >= t
    return {
        "funding_time_ms": ts,
        "observation_time_ms": obs,
        "period_end_ms": period_end,
        "known_time_ms": known,
        "available_time_ms": avail,
        "funding_interval_hours": interval_h,
        "funding_rate": rate_arr,
    }


# ---------------------------------------------------------------------------
# persistence
# ---------------------------------------------------------------------------

def _save_npz(path: Path, cols: dict[str, NDArray[Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(path, **cols)


def main() -> None:
    CARRY_DIR.mkdir(parents=True, exist_ok=True)
    CACHE_DIR.mkdir(parents=True, exist_ok=True)

    audit: dict[str, Any] = {
        "window": {"common_start": COMMON_START.isoformat(),
                   "common_end": COMMON_END.isoformat()},
        "assets": list(ASSETS),
        "spot_source": SPOT_KLINES_BASE + "/{symbol}/5m/{symbol}-5m-{YYYY-MM}.zip",
        "funding_source": FUNDING_BASE + "/{symbol}/{symbol}-fundingRate-{YYYY-MM}.zip",
        "spot_columns_documented": list(KLINES_COLUMNS),
        "epoch_unit_note": "spot monthly archive: ms in 2024, MICROSECONDS from 2025; normalized to ms",
        "perp_klines_note": "reused unchanged from RFC-027 cache (millisecond epoch throughout)",
        "funding_columns_documented": list(FUNDING_COLUMNS),
        "funding_pit_contract": {
            "observation_time": "payment_time - interval_hours",
            "known_time": "payment_time (conservative)",
            "payment_time": "calc_time",
            "signal_rule": "decisions may only use rows with payment_time <= T",
        },
        "holdout_analytics_read": False,
        "assets_spot": {},
        "assets_funding": {},
    }

    for sym in ASSETS:
        print(f"[fetch028] spot {sym} {COMMON_START}..{COMMON_END}", flush=True)
        s = fetch_spot_asset(sym, COMMON_START, COMMON_END)
        sc = canonicalize_spot_klines(s["rows"])
        _save_npz(CACHE_DIR / f"spot_{sym}.npz", sc)
        audit["assets_spot"][sym] = {
            "rows": int(sc["open_time_ms"].shape[0]),
            "missing_months": s["missing_months"],
            "first_open_ms": int(sc["open_time_ms"][0]) if sc["open_time_ms"].size else None,
            "last_open_ms": int(sc["open_time_ms"][-1]) if sc["open_time_ms"].size else None,
            "epoch_unit_histogram": json.loads(str(sc["_unit_hist"][0])),
            "first_microsecond_day": str(sc["_first_us_day"][0]),
        }
        print(f"[fetch028] spot {sym}: rows={sc['open_time_ms'].shape[0]}", flush=True)

        print(f"[fetch028] funding {sym} {COMMON_START}..{COMMON_END}", flush=True)
        f = fetch_funding_asset(sym, COMMON_START, COMMON_END)
        fc = canonicalize_funding(f["rows"])
        _save_npz(CACHE_DIR / f"funding_{sym}.npz", fc)
        intervals = sorted({float(x) for x in np.unique(fc["funding_interval_hours"]).tolist()})
        audit["assets_funding"][sym] = {
            "rows": int(fc["funding_time_ms"].shape[0]),
            "missing_months": f["missing_months"],
            "intervals_hours": intervals,
            "first_payment_ms": int(fc["funding_time_ms"][0]) if fc["funding_time_ms"].size else None,
            "last_payment_ms": int(fc["funding_time_ms"][-1]) if fc["funding_time_ms"].size else None,
        }
        print(f"[fetch028] funding {sym}: rows={fc['funding_time_ms'].shape[0]} "
              f"intervals={intervals}", flush=True)

    (CARRY_DIR / "_fetch_source_audit.json").write_text(
        json.dumps(audit, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
    print("[fetch028] done", flush=True)


if __name__ == "__main__":
    main()
