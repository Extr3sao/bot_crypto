"""RFC-027 — Positioning-data edge discovery (Sprint 004): shared library.

READ-ONLY, RESEARCH-ONLY, PIT-SAFE BY CONSTRUCTION.

Consumes the canonical positioning dataset materialised by
``scripts/sprint027_fetch.py`` (Binance public archive) and answers a single
question: *does deep, point-in-time derivatives positioning information create
reproducible net edge?*

PIT CONTRACT (§10)
    Every canonical row carries ``interval_start_ms``, ``interval_end_ms`` and
    ``available_time_ms``.  A feature at decision time ``D`` may only use rows
    with ``available_time_ms <= D``; alignment is strictly backward / as-of.

SPLITS (§18)
    Chronological only, frozen BEFORE any alpha is measured.  ``HOLDOUT`` is
    never loaded into analytics (``HOLDOUT_ANALYTICS_READ = False``, §19): the
    analytics loader truncates at the VALIDATION boundary.

NO IMPUTATION (§12): a missing datum stays NaN and excludes the observation;
nothing is forward-filled.

COST (§40): ``COST_MODEL_V3 = 23.790569`` bps is reused unchanged as the control.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
from numpy.typing import NDArray

REPO = Path(__file__).resolve().parents[1]
POS_DIR = REPO / "reports" / "positioning-data"
CACHE_DIR = POS_DIR / "cache"
OUT_DIR = REPO / "reports" / "edge-discovery" / "sprint004"

ASSETS = ("BTCUSDT", "ETHUSDT", "SOLUSDT")
COST_MODEL_V3_BPS = 23.790569
ROOT_NOTIONAL = 500.0

TF_SRC_MIN = 5          # source kline grid
TF_DEC_MIN = 30         # decision grid
SRC_MS = TF_SRC_MIN * 60_000
DEC_MS = TF_DEC_MIN * 60_000

# Forward horizons on the 30m decision grid (§33).
HORIZON_BARS = (1, 2, 4, 8, 16)
HORIZON_LABEL = {1: "30m", 2: "1h", 4: "2h", 8: "4h", 16: "8h"}

# Fractional chronological splits (§18).  Frozen, never shuffled.
SPLIT_FRACTIONS = {"DISCOVERY": (0.0, 0.6), "VALIDATION": (0.6, 0.8), "HOLDOUT": (0.8, 1.0)}
SPLIT_ORDER = ("DISCOVERY", "VALIDATION", "HOLDOUT")

# Trailing feature windows (bars on the 30m grid).
OI_Z_WIN = 48       # 24h
VOL_WIN_5M = 288    # 24h of 5m returns
VOL_Z_WIN = 48
RET_Z_WIN = 48

HOLDOUT_ANALYTICS_READ = False


# ---------------------------------------------------------------------------
# raw canonical loaders
# ---------------------------------------------------------------------------


def _npz(path: Path) -> dict[str, NDArray[Any]]:
    with np.load(path, allow_pickle=False) as z:
        return {k: z[k] for k in z.files}


def load_metrics(asset: str) -> dict[str, NDArray[Any]]:
    return _npz(CACHE_DIR / f"metrics_{asset}.npz")


def load_klines(asset: str) -> dict[str, NDArray[Any]]:
    return _npz(CACHE_DIR / f"klines_{asset}.npz")


# ---------------------------------------------------------------------------
# decision grid + PIT as-of
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Panel:
    """A pooled, PIT-safe decision panel over the assets (analytics-ready)."""

    ts: NDArray[Any]           # decision time (bar close), ms
    asset: NDArray[Any]        # asset index per row
    open: NDArray[Any]
    high: NDArray[Any]
    low: NDArray[Any]
    close: NDArray[Any]
    features: dict[str, NDArray[Any]]
    fwd_bps: dict[int, NDArray[Any]]

    def __len__(self) -> int:
        return int(self.ts.shape[0])


def _complete_30m_from_5m(k: dict[str, NDArray[Any]]) -> dict[str, NDArray[Any]]:
    """Deterministic complete-bucket 5m->30m resample, label = bar OPEN."""
    ts = k["open_time_ms"].astype(np.int64)
    n = len(ts)
    per = TF_DEC_MIN // TF_SRC_MIN
    acc: dict[str, list[float]] = {key: [] for key in ("open", "high", "low", "close", "volume")}
    out_ts: list[int] = []
    cur: list[int] = []
    bucket: int | None = None

    def flush(c: list[int]) -> None:
        if len(c) == per and int(ts[c[0]]) // DEC_MS == int(ts[c[-1]]) // DEC_MS:
            out_ts.append(int(ts[c[0]]))
            acc["open"].append(float(k["open"][c[0]]))
            acc["high"].append(float(np.max(k["high"][c])))
            acc["low"].append(float(np.min(k["low"][c])))
            acc["close"].append(float(k["close"][c[-1]]))
            acc["volume"].append(float(np.sum(k["volume"][c])))

    for i in range(n):
        bk = int(ts[i]) // DEC_MS
        if bucket is None:
            bucket = bk
        if bk != bucket:
            flush(cur)
            cur = []
            bucket = bk
        cur.append(i)
    flush(cur)  # do not drop the final bucket
    return {"open_time_ms": np.array(out_ts, dtype=np.int64)} | {
        key: np.array(vals, dtype=np.float64) for key, vals in acc.items()
    }


def _asof(times: NDArray[Any], values: NDArray[Any], decisions: NDArray[Any]) -> NDArray[Any]:
    """Backward / as-of join: latest value with time <= decision (ms)."""
    t = times.tolist()
    out = np.full(decisions.shape, np.nan, dtype=np.float64)
    import bisect
    for k, d in enumerate(decisions):
        i = bisect.bisect_right(t, int(d)) - 1
        if i >= 0:
            v = values[i]
            if np.isfinite(v):
                out[k] = v
    return out


def _rolling_z(x: NDArray[Any], n: int) -> NDArray[Any]:
    out = np.full(x.shape, np.nan, dtype=np.float64)
    if x.shape[0] < n:
        return out
    w = np.lib.stride_tricks.sliding_window_view(x, n)
    finite = np.isfinite(w).sum(axis=1)
    with np.errstate(invalid="ignore", divide="ignore"):
        mu = np.nanmean(w, axis=1)
        sd = np.nanstd(w, axis=1)
        good = (finite == n) & (sd > 0)
        out[n - 1 :] = np.where(good, (x[n - 1 :] - mu) / sd, np.nan)
    return out


def _diff1(x: NDArray[Any]) -> NDArray[Any]:
    out = np.full(x.shape, np.nan, dtype=np.float64)
    out[1:] = x[1:] - x[:-1]
    return out


def _rolling_mean(x: NDArray[Any], n: int) -> NDArray[Any]:
    out = np.full(x.shape, np.nan, dtype=np.float64)
    if x.shape[0] < n:
        return out
    w = np.lib.stride_tricks.sliding_window_view(x, n)
    finite = np.isfinite(w)
    cnt = finite.sum(axis=1)
    with np.errstate(invalid="ignore", divide="ignore"):
        tot = np.where(finite, w, 0.0).sum(axis=1)
        out[n - 1 :] = np.where(cnt == n, tot / cnt, np.nan)
    return out


def _asset_rows(asset: str) -> dict[str, Any]:
    """PIT-aligned rows on the 30m decision grid for one asset.

    Returns raw aligned metric series + grid OHLC + a trailing realized-vol
    series computed from the 5m source (never future).
    """
    m = load_metrics(asset)
    k = load_klines(asset)
    grid = _complete_30m_from_5m(k)
    gts = grid["open_time_ms"].astype(np.int64)
    decision = gts + DEC_MS  # bar close

    avail = m["available_time_ms"].astype(np.int64)
    order = np.argsort(avail, kind="mergesort")
    avail = avail[order]

    aligned: dict[str, NDArray[Any]] = {}
    for key in (
        "sum_open_interest",
        "sum_open_interest_value",
        "count_toptrader_long_short_ratio",
        "sum_toptrader_long_short_ratio",
        "count_long_short_ratio",
        "sum_taker_long_short_vol_ratio",
    ):
        aligned[key] = _asof(avail, m[key][order], decision)

    # trailing realized vol on the 5m grid, then as-of onto the decision grid
    kts = k["open_time_ms"].astype(np.int64)
    kc = k["close"].astype(np.float64)
    ret5 = np.full(kc.shape, np.nan, dtype=np.float64)
    ret5[1:] = kc[1:] / kc[:-1] - 1.0
    rv5 = _rolling_std(ret5, VOL_WIN_5M)
    rv_avail = kts + SRC_MS
    vol_real = _asof(rv_avail, rv5, decision)

    return {
        "asset": asset,
        "grid_ts": gts,
        "decision": decision,
        "open": grid["open"], "high": grid["high"], "low": grid["low"],
        "close": grid["close"], "volume": grid["volume"],
        "metrics": aligned,
        "vol_real": vol_real,
    }


def _rolling_std(x: NDArray[Any], n: int) -> NDArray[Any]:
    out = np.full(x.shape, np.nan, dtype=np.float64)
    if x.shape[0] < n:
        return out
    w = np.lib.stride_tricks.sliding_window_view(x, n)
    finite = np.isfinite(w).sum(axis=1)
    with np.errstate(invalid="ignore", divide="ignore"):
        sd = np.nanstd(w, axis=1)
        out[n - 1 :] = np.where(finite == n, sd, np.nan)
    return out


# ---------------------------------------------------------------------------
# features (§23) — all trailing / causal
# ---------------------------------------------------------------------------

FEATURE_NAMES = (
    "oi", "oi_value", "doi", "pct_doi", "oi_z", "oi_accel",
    "ls_global", "ls_top", "top_global_div", "top_global_ratio",
    "taker", "taker_chg", "taker_persist",
    "ret1", "ret_z", "vol_real", "vol_z",
)


def build_asset_features(asset: str) -> dict[str, Any]:
    r = _asset_rows(asset)
    m = r["metrics"]
    oi = m["sum_open_interest"]
    doi = _diff1(oi)
    pct_doi = np.full(oi.shape, np.nan, dtype=np.float64)
    prev = np.full(oi.shape, np.nan, dtype=np.float64)
    prev[1:] = oi[:-1]
    with np.errstate(invalid="ignore", divide="ignore"):
        pct_doi = np.where(prev > 0, doi / prev, np.nan)
    ls_global = m["count_long_short_ratio"]
    ls_top = m["sum_toptrader_long_short_ratio"]
    with np.errstate(invalid="ignore", divide="ignore"):
        tdiv = ls_top - ls_global
        tratio = np.where(ls_global > 0, ls_top / ls_global, np.nan)
    taker = m["sum_taker_long_short_vol_ratio"]
    close = r["close"]
    ret1 = np.full(close.shape, np.nan, dtype=np.float64)
    ret1[1:] = close[1:] / close[:-1] - 1.0

    feats: dict[str, NDArray[Any]] = {
        "oi": oi,
        "oi_value": m["sum_open_interest_value"],
        "doi": doi,
        "pct_doi": pct_doi,
        "oi_z": _rolling_z(oi, OI_Z_WIN),
        "oi_accel": _diff1(doi),
        "ls_global": ls_global,
        "ls_top": ls_top,
        "top_global_div": tdiv,
        "top_global_ratio": tratio,
        "taker": taker,
        "taker_chg": _diff1(taker),
        "taker_persist": _rolling_mean(taker, 12),
        "ret1": ret1,
        "ret_z": _rolling_z(ret1, RET_Z_WIN),
        "vol_real": r["vol_real"],
        "vol_z": _rolling_z(r["vol_real"], VOL_Z_WIN),
    }
    return {
        "asset": asset,
        "ts": r["grid_ts"],
        "decision": r["decision"],
        "open": r["open"], "high": r["high"], "low": r["low"], "close": r["close"],
        "volume": r["volume"],
        "features": feats,
    }


# ---------------------------------------------------------------------------
# pooled panel
# ---------------------------------------------------------------------------


def build_panel(upto: str = "VALIDATION") -> Panel:
    """Build the pooled decision panel, truncated at a split boundary.

    ``upto="VALIDATION"`` (default) loads only DISCOVERY+VALIDATION rows;
    HOLDOUT is never materialised here (``HOLDOUT_ANALYTICS_READ`` stays False).
    """
    per_asset: list[dict[str, Any]] = []
    for ai, asset in enumerate(ASSETS):
        fa = build_asset_features(asset)
        n = len(fa["ts"])
        cut = int(n * SPLIT_FRACTIONS["VALIDATION"][1]) if upto == "VALIDATION" else n
        if upto == "DISCOVERY":
            cut = int(n * SPLIT_FRACTIONS["DISCOVERY"][1])
        sub = {k: (v[:cut] if isinstance(v, np.ndarray) else v) for k, v in fa.items()}
        sub = dict(sub)
        sub["features"] = {k: v[:cut] for k, v in fa["features"].items()}
        sub["asset_idx"] = np.full(cut, ai, dtype=np.int64)
        per_asset.append(sub)

    ts = np.concatenate([a["ts"] for a in per_asset])
    asset_idx = np.concatenate([a["asset_idx"] for a in per_asset])
    feats = {name: np.concatenate([a["features"][name] for a in per_asset])
             for name in FEATURE_NAMES}
    close = np.concatenate([a["close"] for a in per_asset])

    # forward returns per asset (never cross asset boundaries): compute on the
    # per-asset segment then concatenate.
    fwd: dict[int, NDArray[Any]] = {}
    for h in HORIZON_BARS:
        cols = []
        for a in per_asset:
            c = a["close"]
            out = np.full(c.shape, np.nan, dtype=np.float64)
            if c.shape[0] > h:
                out[: c.shape[0] - h] = (c[h:] / c[: c.shape[0] - h] - 1.0) * 1e4
            cols.append(out)
        fwd[h] = np.concatenate(cols)

    return Panel(
        ts=ts, asset=asset_idx,
        open=np.concatenate([a["open"] for a in per_asset]),
        high=np.concatenate([a["high"] for a in per_asset]),
        low=np.concatenate([a["low"] for a in per_asset]),
        close=close,
        features=feats, fwd_bps=fwd,
    )


def split_masks(panel: Panel, upto: str = "VALIDATION") -> dict[str, NDArray[Any]]:
    """Boolean masks per split for a panel built over the non-holdout span."""
    # split boundaries are per-asset by index; the panel concatenates assets in
    # order with equal-length segments only if the assets share a grid length.
    masks: dict[str, NDArray[Any]] = {}
    n = len(panel)
    # derive per-asset segment boundaries
    seg = []
    start = 0
    for ai in range(len(ASSETS)):
        idx = np.where(panel.asset == ai)[0]
        if idx.size:
            seg.append((start, int(idx[-1]) + 1, idx))
            start = int(idx[-1]) + 1
    m_disc = np.zeros(n, dtype=bool)
    m_val = np.zeros(n, dtype=bool)
    for _, end, idx in seg:
        m = end - idx[0]
        _a, b = SPLIT_FRACTIONS["DISCOVERY"]
        c, _d = SPLIT_FRACTIONS["VALIDATION"]
        disc = idx[: int(m * b)]
        val = idx[int(m * c): int(m * _d)]
        m_disc[disc] = True
        m_val[val] = True
    masks["DISCOVERY"] = m_disc
    masks["VALIDATION"] = m_val
    return masks


# ---------------------------------------------------------------------------
# statistics primitives
# ---------------------------------------------------------------------------


def _rank(x: NDArray[Any]) -> NDArray[Any]:
    v = np.asarray(x, dtype=np.float64)
    n = v.shape[0]
    order = np.argsort(v, kind="mergesort")
    ranks = np.empty(n, dtype=np.float64)
    ranks[order] = np.arange(1, n + 1, dtype=np.float64)
    sx = v[order]
    i = 0
    while i < n:
        j = i
        while j + 1 < n and sx[j + 1] == sx[i]:
            j += 1
        if j > i:
            avg = float((ranks[order[i]] + ranks[order[j]]) / 2.0)
            for kk in range(i, j + 1):
                ranks[order[kk]] = avg
        i = j + 1
    return ranks


def spearman_ic(sig: NDArray[Any], fwd: NDArray[Any]) -> float | None:
    x = np.asarray(sig, dtype=np.float64)
    y = np.asarray(fwd, dtype=np.float64)
    m = np.isfinite(x) & np.isfinite(y)
    if int(m.sum()) < 50:
        return None
    rx, ry = _rank(x[m]), _rank(y[m])
    if float(np.std(rx)) == 0.0 or float(np.std(ry)) == 0.0:
        return None
    return float(np.corrcoef(rx, ry)[0, 1])


def quantile_spread(sig: NDArray[Any], fwd: NDArray[Any], q: int = 5) -> dict[str, Any]:
    x = np.asarray(sig, dtype=np.float64)
    y = np.asarray(fwd, dtype=np.float64)
    m = np.isfinite(x) & np.isfinite(y)
    x, y = x[m], y[m]
    n = x.shape[0]
    if n < q * 20:
        return {"status": "N/A", "n": int(n)}
    order = np.argsort(x, kind="mergesort")
    ys = y[order]
    size = n // q
    means = [float(np.mean(ys[kk * size : (kk + 1) * size])) for kk in range(q)]
    steps = sum(1 for kk in range(q - 1) if means[kk + 1] >= means[kk]) / (q - 1)
    mono = steps if steps >= 0.5 else steps - 1.0
    return {
        "status": "OK", "n": int(n),
        "quantile_means_bps": [round(v, 4) for v in means],
        "top_minus_bottom_bps": round(means[-1] - means[0], 4),
        "monotonicity": round(mono, 3),
    }


def hit_rate(sig: NDArray[Any], fwd: NDArray[Any]) -> float | None:
    x = np.asarray(sig, dtype=np.float64)
    y = np.asarray(fwd, dtype=np.float64)
    m = np.isfinite(x) & np.isfinite(y) & (x != 0)
    if int(m.sum()) < 50:
        return None
    agree = np.sign(x[m]) == np.sign(y[m])
    return float(np.mean(agree))


def mde_bps(sigma: float, n: int) -> float | None:
    if n <= 1 or not math.isfinite(sigma):
        return None
    return round((1.959964 + 0.841621) * sigma / math.sqrt(n), 4)


# ---------------------------------------------------------------------------
# writers / hashing
# ---------------------------------------------------------------------------


def sha256_obj(obj: Any) -> str:
    import hashlib
    payload = json.dumps(obj, sort_keys=True, default=str).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n",
                    encoding="utf-8")


def write_md(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
