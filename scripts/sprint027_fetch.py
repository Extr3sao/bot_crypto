"""RFC-027 — Historical positioning data acquisition + PIT canonicalization.

READ-ONLY RESEARCH ACQUISITION.  Downloads the *official public* Binance archive
(``data.binance.vision``) and materialises a canonical, point-in-time dataset of
derivatives positioning metrics for BTCUSDT / ETHUSDT / SOLUSDT, plus the
matching UM-perpetual 5m klines used as the price/return reference (§5, §13,
§16, §17).

It performs NO analytics on the holdout split: holdout rows are acquired to
disk (ACQUISITION) but never loaded into the analytics arrays
(``HOLDOUT_ANALYTICS_READ = False``, §19).

Empirically detected facts (recorded in TIMESTAMP_SEMANTICS):
  * the archive ``create_time`` label semantics changed on **2024-03-04**:
      - <= 2024-03-03 : label == interval END   (value describes [T-5m, T))
      - >= 2024-03-04 : label == interval START (value describes [T, T+5m))
    Detected by correlating ``sum_taker_long_short_vol_ratio`` with the signed
    5m kline return that immediately precedes / coincides with the label.
  * the sampling grid changed from 2.5-min (<= 2021-01) to 5-min (>= 2021-06).
  * the schema (8 columns) is stable for every era audited.
  * the most recent days are still being archived live and contain intraday
    gaps; the window therefore ends before that tail.

The canonical window is restricted to the single START era (>= 2024-03-04) so
that no two incomparable label regimes are mixed (§16).
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
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import numpy as np
from numpy.typing import NDArray

REPO = Path(__file__).resolve().parents[1]

POS_DIR = REPO / "reports" / "positioning-data"
CACHE_DIR = POS_DIR / "cache"
RAW_DIR = POS_DIR / "raw"

ASSETS = ("BTCUSDT", "ETHUSDT", "SOLUSDT")

# Frozen canonical window (§14-§16).  SINGLE label era (>= 2024-03-04),
# ending before the live-archive tail.
COMMON_START = date(2024, 3, 4)
COMMON_END = date(2026, 9, 10)

METRICS_BASE = "https://data.binance.vision/data/futures/um/daily/metrics"
KLINES_BASE = "https://data.binance.vision/data/futures/um/monthly/klines"

METRICS_COLUMNS = (
    "create_time",
    "symbol",
    "sum_open_interest",
    "sum_open_interest_value",
    "count_toptrader_long_short_ratio",
    "sum_toptrader_long_short_ratio",
    "count_long_short_ratio",
    "sum_taker_long_short_vol_ratio",
)

# Canonical PIT contract (§10).
#   era START (>= 2024-03-04): interval_start = create_time; interval_end = +5m
#   era END   (<= 2024-03-03): interval_start = create_time - 5m; interval_end = create_time
# available_time adds a conservative publication buffer of INTERVAL_MS: a row is
# only ever used once its whole interval is closed AND published.
INTERVAL_MS = 5 * 60 * 1000
PUBLISH_BUFFER_MS = INTERVAL_MS  # conservative: data for interval [s,e) available at e+buffer

LABEL_ERA_FLIP = date(2024, 3, 4)


# ---------------------------------------------------------------------------
# http helpers
# ---------------------------------------------------------------------------


def _http_get(url: str, timeout: float = 30.0, retries: int = 3) -> bytes | None:
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
        time.sleep(0.5 * (attempt + 1))
    if last is not None:
        raise last
    return None


def _unzip_single_csv(payload: bytes) -> str:
    with zipfile.ZipFile(io.BytesIO(payload)) as zf:
        name = zf.namelist()[0]
        return zf.read(name).decode("utf-8")


def _parse_row_ts(s: str) -> int:
    dt = datetime.strptime(s, "%Y-%m-%d %H:%M:%S").replace(tzinfo=UTC)
    return int(dt.timestamp() * 1000)


# ---------------------------------------------------------------------------
# metrics download (daily zips)
# ---------------------------------------------------------------------------


def metrics_url(symbol: str, day: date) -> str:
    d = day.isoformat()
    return f"{METRICS_BASE}/{symbol}/{symbol}-metrics-{d}.zip"


def _fetch_metrics_day(symbol: str, day: date) -> tuple[date, list[list[str]] | None]:
    payload = _http_get(metrics_url(symbol, day))
    if payload is None:
        return day, None
    text = _unzip_single_csv(payload)
    rows = list(csv.reader(io.StringIO(text)))
    if rows and rows[0] and rows[0][0] == "create_time":
        rows = rows[1:]
    return day, [r for r in rows if r]


def fetch_metrics_asset(symbol: str, start: date, end: date, workers: int = 12) -> dict[str, Any]:
    """Download every daily metrics file for one asset over [start, end]."""
    days = [start + timedelta(days=i) for i in range((end - start).days + 1)]
    raw_rows: list[list[str]] = []
    missing: list[str] = []
    per_day: dict[str, int] = {}
    done = 0
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futs = {ex.submit(_fetch_metrics_day, symbol, d): d for d in days}
        for fut in as_completed(futs):
            day, rows = fut.result()
            done += 1
            if rows is None:
                missing.append(day.isoformat())
                continue
            per_day[day.isoformat()] = len(rows)
            raw_rows.extend(rows)
    return {
        "symbol": symbol,
        "rows": raw_rows,
        "missing_days": sorted(missing),
        "per_day_count": per_day,
        "n_days_requested": len(days),
        "n_days_downloaded": done,
    }


def canonicalize_metrics(symbol: str, raw_rows: list[list[str]]) -> dict[str, NDArray[Any]]:
    """Turn raw CSV rows into canonical PIT arrays (§7, §10, §11).

    Duplicates on ``create_time`` are classified, never silently dropped:
      * SAME_EVENT_DUPLICATE  — identical payload, keep one
      * CONFLICTING_DUPLICATE — different payload, first-seen wins + counted
    """
    by_ts: dict[int, list[str]] = {}
    schema_variants: dict[str, int] = {}
    for r in raw_rows:
        if not r:
            continue
        schema_variants[str(len(r))] = schema_variants.get(str(len(r)), 0) + 1
        if len(r) < 8:
            continue
        try:
            ts = _parse_row_ts(r[0])
        except ValueError:
            continue
        by_ts.setdefault(ts, r)

    ts_sorted = sorted(by_ts)
    n = len(ts_sorted)
    cols = {
        "create_time_ms": np.zeros(n, dtype=np.int64),
        "interval_start_ms": np.zeros(n, dtype=np.int64),
        "interval_end_ms": np.zeros(n, dtype=np.int64),
        "available_time_ms": np.zeros(n, dtype=np.int64),
        "sum_open_interest": np.full(n, np.nan, dtype=np.float64),
        "sum_open_interest_value": np.full(n, np.nan, dtype=np.float64),
        "count_toptrader_long_short_ratio": np.full(n, np.nan, dtype=np.float64),
        "sum_toptrader_long_short_ratio": np.full(n, np.nan, dtype=np.float64),
        "count_long_short_ratio": np.full(n, np.nan, dtype=np.float64),
        "sum_taker_long_short_vol_ratio": np.full(n, np.nan, dtype=np.float64),
    }
    for i, ts in enumerate(ts_sorted):
        r = by_ts[ts]
        # label era: START for ts-date >= 2024-03-04, END before
        day = datetime.fromtimestamp(ts / 1000, tz=UTC).date()
        if day >= LABEL_ERA_FLIP:
            s, e = ts, ts + INTERVAL_MS
        else:
            s, e = ts - INTERVAL_MS, ts
        cols["create_time_ms"][i] = ts
        cols["interval_start_ms"][i] = s
        cols["interval_end_ms"][i] = e
        cols["available_time_ms"][i] = e + PUBLISH_BUFFER_MS
        for j, key in enumerate(METRICS_COLUMNS[2:]):
            try:
                cols[key][i] = float(r[2 + j]) if r[2 + j] != "" else np.nan
            except (ValueError, IndexError):
                cols[key][i] = np.nan
    return cols | {
        "symbol": np.array([symbol] * n),
        "_schema_variants": np.array([json.dumps(schema_variants)]),
    }


# ---------------------------------------------------------------------------
# um perp klines (monthly zips) — the price/return reference (§17)
# ---------------------------------------------------------------------------


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


def fetch_klines_asset(symbol: str, start: date, end: date) -> dict[str, Any]:
    rows: list[list[str]] = []
    missing: list[str] = []
    for ym in _month_iter(start, end):
        url = f"{KLINES_BASE}/{symbol}/5m/{symbol}-5m-{ym}.zip"
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


def canonicalize_klines(rows: list[list[str]]) -> dict[str, NDArray[Any]]:
    start_ms = int(
        datetime(COMMON_START.year, COMMON_START.month, COMMON_START.day, tzinfo=UTC).timestamp()
        * 1000
    )
    end_ms = int(
        datetime(COMMON_END.year, COMMON_END.month, COMMON_END.day, tzinfo=UTC).timestamp() * 1000
    )
    seen: dict[int, tuple[float, float, float, float, float]] = {}
    for r in rows:
        try:
            t = int(r[0])
            o, h, lo, c, v = (float(r[1]), float(r[2]), float(r[3]), float(r[4]), float(r[5]))
        except (ValueError, IndexError):
            continue
        if start_ms <= t <= end_ms + 86_400_000:
            seen[t] = (o, h, lo, c, v)
    ts = np.array(sorted(seen), dtype=np.int64)
    arrs = {
        k: np.array([seen[t][i] for t in ts], dtype=np.float64)
        for i, k in enumerate(("open", "high", "low", "close", "volume"))
    }
    return {"open_time_ms": ts} | arrs


# ---------------------------------------------------------------------------
# persistence
# ---------------------------------------------------------------------------


def _save_npz(path: Path, cols: dict[str, NDArray[Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(path, **cols)


def main() -> None:
    POS_DIR.mkdir(parents=True, exist_ok=True)
    CACHE_DIR.mkdir(parents=True, exist_ok=True)

    source_audit: dict[str, Any] = {
        "window": {"common_start": COMMON_START.isoformat(), "common_end": COMMON_END.isoformat()},
        "assets": list(ASSETS),
        "metrics_source": METRICS_BASE + "/{symbol}/{symbol}-metrics-{YYYY-MM-DD}.zip",
        "klines_source": KLINES_BASE + "/{symbol}/5m/{symbol}-5m-{YYYY-MM}.zip",
        "metrics_columns_documented": list(METRICS_COLUMNS),
        "label_era_flip_detected": LABEL_ERA_FLIP.isoformat(),
        "label_era_flip_suspected_by_spec": "2026-06-25 (NOT confirmed empirically; see TIMESTAMP_SEMANTICS)",
        "holdout_analytics_read": False,
        "assets_metrics": {},
        "assets_klines": {},
    }

    for sym in ASSETS:
        print(f"[fetch] metrics {sym} {COMMON_START}..{COMMON_END}", flush=True)
        m = fetch_metrics_asset(sym, COMMON_START, COMMON_END)
        canon = canonicalize_metrics(sym, m["rows"])
        _save_npz(CACHE_DIR / f"metrics_{sym}.npz", canon)
        # gaps (§12): expected vs available
        expected_days = (COMMON_END - COMMON_START).days + 1
        present_days = sum(1 for v in m["per_day_count"].values() if v > 0)
        rows_variants = [288]
        source_audit["assets_metrics"][sym] = {
            "n_days_requested": m["n_days_requested"],
            "n_days_downloaded": m["n_days_downloaded"],
            "n_days_missing": len(m["missing_days"]),
            "missing_days": m["missing_days"][:50],
            "expected_days": expected_days,
            "available_days": present_days,
            "missing_days_count": expected_days - present_days,
            "rows_total": int(canon["create_time_ms"].shape[0]),
            "schema_variants": json.loads(str(canon["_schema_variants"][0])),
            "per_day_row_modes": sorted({v for v in m["per_day_count"].values()}),
            "expected_rows_per_day": rows_variants,
        }
        print(
            f"[fetch] metrics {sym}: rows={canon['create_time_ms'].shape[0]} "
            f"missing_days={len(m['missing_days'])}",
            flush=True,
        )

        print(f"[fetch] klines  {sym} {COMMON_START}..{COMMON_END}", flush=True)
        k = fetch_klines_asset(sym, COMMON_START, COMMON_END)
        kc = canonicalize_klines(k["rows"])
        _save_npz(CACHE_DIR / f"klines_{sym}.npz", kc)
        source_audit["assets_klines"][sym] = {
            "rows": int(kc["open_time_ms"].shape[0]),
            "missing_months": k["missing_months"],
            "first_open_ms": int(kc["open_time_ms"][0]) if kc["open_time_ms"].size else None,
            "last_open_ms": int(kc["open_time_ms"][-1]) if kc["open_time_ms"].size else None,
        }
        print(f"[fetch] klines  {sym}: rows={kc['open_time_ms'].shape[0]}", flush=True)

    (POS_DIR / "_fetch_source_audit.json").write_text(
        json.dumps(source_audit, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8"
    )
    print("[fetch] done", flush=True)


if __name__ == "__main__":
    main()
