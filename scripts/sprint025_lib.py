"""RFC-025 — Orthogonal market intelligence: shared research library.

READ-ONLY, PIT-SAFE BY CONSTRUCTION.

This library consumes the orthogonal sources that already exist in the
repository (``reports/microstructure-v1/data/``) and the certified price
corpus (``reports/strategy-baseline/data/``). It never places orders, never
uses credentials, and never reads the RFC-024 / RFC-023 holdout.

PIT CONTRACT
    ``available_at`` is the first instant at which a datum is knowable:
      * premium klines / klines : ``open_ts + tf_ms`` (close time)
      * funding                 : ``fundingTime`` (payment time)
      * open interest           : ``timestamp + period_ms``
    A feature at decision bar ``i`` may only use samples with
    ``available_at <= decision_time`` where ``decision_time`` is the close of
    bar ``i``. Alignment is strictly backward / as-of (``bisect_right``).

NO IMPUTATION (§21): a missing orthogonal datum stays NaN. The consumer
decides NO_SIGNAL / exclusion; this library never forward-fills with 0 or with
a future value.
"""

from __future__ import annotations

import bisect
import hashlib
import json
import math
import sys
from pathlib import Path
from typing import Any

import numpy as np
from numpy.typing import NDArray

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))

import sprint002_lib as L  # noqa: E402
import sprint002_pipeline as P  # noqa: E402
import sprint002_signals as S  # noqa: E402

MICRO_DIR = REPO / "reports" / "microstructure-v1" / "data"
ORTHO_OUT = REPO / "reports" / "orthogonal-data"
SPRINT_OUT = REPO / "reports" / "edge-discovery" / "sprint003"

ASSETS = ("BTCUSDT", "ETHUSDT", "SOLUSDT")
TF_MS = 300_000  # 5m source grid

# forward-return horizons (bars on the 5m grid): 30m / 1h / 2h / 4h / 8h
HORIZON_BARS = (6, 12, 24, 48, 96)
HORIZON_LABEL = {6: "30m", 12: "1h", 24: "2h", 48: "4h", 96: "8h"}
HORIZONS_MIN = (30, 60, 120, 240, 480)


# ---------------------------------------------------------------------------
# raw orthogonal series (repository data, already downloaded & verified)
# ---------------------------------------------------------------------------


def _load(name: str) -> Any:
    return json.loads((MICRO_DIR / name).read_text(encoding="utf-8"))


def load_funding(asset: str) -> tuple[NDArray[Any], NDArray[Any]]:
    """(available_at=fundingTime, fundingRate) sorted ascending."""
    raw = _load(f"FUNDING_{asset}.json")
    ts = np.array([int(r["fundingTime"]) for r in raw], dtype=np.int64)
    rate = np.array([float(r["fundingRate"]) for r in raw], dtype=np.float64)
    order = np.argsort(ts, kind="mergesort")
    return ts[order], rate[order]


def load_premium(asset: str) -> tuple[NDArray[Any], NDArray[Any]]:
    """(available_at=close_time+1, premium_close) 5m premium index klines."""
    raw = _load(f"PREMIUM_{asset}_5m.json")
    avail = np.array([int(r[6]) + 1 for r in raw], dtype=np.int64)
    val = np.array([float(r[4]) for r in raw], dtype=np.float64)  # close premium
    order = np.argsort(avail, kind="mergesort")
    return avail[order], val[order]


def load_klines(asset: str) -> dict[str, NDArray[Any]]:
    """Spot 5m klines with taker-buy flow. avail = close_time + 1."""
    raw = _load(f"KLINES_{asset}_5m.json")
    ts = np.array([int(r[0]) for r in raw], dtype=np.int64)
    avail = np.array([int(r[6]) + 1 for r in raw], dtype=np.int64)
    close = np.array([float(r[4]) for r in raw], dtype=np.float64)
    vol = np.array([float(r[5]) for r in raw], dtype=np.float64)
    taker_buy = np.array([float(r[9]) for r in raw], dtype=np.float64)
    order = np.argsort(avail, kind="mergesort")
    return {
        "ts": ts[order],
        "avail": avail[order],
        "close": close[order],
        "vol": vol[order],
        "taker_buy": taker_buy[order],
    }


def load_oi(asset: str, period_ms: int = TF_MS) -> tuple[NDArray[Any], NDArray[Any]]:
    """(available_at=timestamp+period, sumOpenInterest). LIMITED_HISTORY (~30d)."""
    raw = _load(f"OPENINTEREST_{asset}.json")
    seen: dict[int, float] = {}
    for r in raw:
        seen[int(r["timestamp"])] = float(r["sumOpenInterest"])
    ts = np.array(sorted(seen), dtype=np.int64)
    val = np.array([seen[int(t)] for t in ts], dtype=np.float64)
    return ts + period_ms, val


# ---------------------------------------------------------------------------
# statistics primitives (reuse sprint023 where possible; keep local np-only)
# ---------------------------------------------------------------------------


def rolling_z(x: NDArray[Any], n: int) -> NDArray[Any]:
    """Trailing z-score of ``x`` over ``n`` finite observations (inclusive)."""
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


def rolling_mean_nan(x: NDArray[Any], n: int) -> NDArray[Any]:
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


def diff1(x: NDArray[Any]) -> NDArray[Any]:
    out = np.full(x.shape, np.nan, dtype=np.float64)
    out[1:] = x[1:] - x[:-1]
    return out


def asof(times: NDArray[Any], values: NDArray[Any], decisions: NDArray[Any]) -> NDArray[Any]:
    """Backward / as-of join: latest value with time <= decision."""
    t = times.tolist()
    out = np.full(decisions.shape, np.nan, dtype=np.float64)
    for k, d in enumerate(decisions):
        i = bisect.bisect_right(t, int(d)) - 1
        if i >= 0:
            out[k] = values[i]
    return out


# ---------------------------------------------------------------------------
# orthogonal feature build on the 5m grid, then attach to a certified bundle
# ---------------------------------------------------------------------------

FEATURE_NAMES = (
    "funding_rate",
    "funding_z",
    "funding_diff",
    "basis",
    "basis_z",
    "basis_diff",
    "taker_imbalance",
    "taker_z",
    "taker_persist",
)


def features_from_arrays(
    grid_ts: NDArray[Any],
    p_avail: NDArray[Any],
    p_val: NDArray[Any],
    f_avail: NDArray[Any],
    f_rate: NDArray[Any],
    vol: NDArray[Any],
    taker_buy: NDArray[Any],
) -> dict[str, NDArray[Any]]:
    """Build the orthogonal features from raw arrays (PIT as-of only).

    Extracted so the adversarial future-poisoning test can rebuild features
    from a mutated tail and prove decisions <= T are unchanged.
    """
    decision = grid_ts + TF_MS  # close of each grid bar
    basis = asof(p_avail, p_val, decision)
    funding = asof(f_avail, f_rate, decision)
    funding_diff = diff1(funding)
    fz_vals = rolling_z(f_rate, 21)
    mask = np.isfinite(fz_vals)
    funding_z = asof(f_avail[mask], fz_vals[mask], decision)
    with np.errstate(invalid="ignore", divide="ignore"):
        imb = np.where(vol > 0, (2.0 * taker_buy - vol) / vol, np.nan)
    return {
        "funding_rate": funding,
        "funding_z": funding_z,
        "funding_diff": funding_diff,
        "basis": basis,
        "basis_z": rolling_z(basis, 120),
        "basis_diff": diff1(basis),
        "taker_imbalance": imb,
        "taker_z": rolling_z(imb, 20),
        "taker_persist": rolling_mean_nan(imb, 12),
    }


def build_asset_grid(asset: str) -> dict[str, Any]:
    """Orthogonal features on the asset's own 5m grid (ts = bar OPEN)."""
    kl = load_klines(asset)
    p_avail, p_val = load_premium(asset)
    f_avail, f_rate = load_funding(asset)
    feats = features_from_arrays(
        kl["ts"], p_avail, p_val, f_avail, f_rate, kl["vol"], kl["taker_buy"]
    )
    return {"asset": asset, "ts": kl["ts"], "features": feats}


def ortho_on_bundle(asset: str, bundle: L.Bundle, at: str = "close") -> dict[str, NDArray[Any]]:
    """Map the asset grid features onto a certified bundle's bar axis by ts.

    ``at="close"`` (default) uses, for each bundle bar, the last 5m grid bar
    inside that bar (open + tf - 5m), i.e. the freshest PIT value knowable at
    the decision (close of the bundle bar). ``at="open"`` uses the bundle bar's
    own open. Both are PIT-safe (never a future grid bar); "close" is fresher.

    Missing bars -> NaN (NO IMPUTATION). Both axes are on the same UTC grid.
    """
    grid = build_asset_grid(asset)
    idx = {int(t): k for k, t in enumerate(grid["ts"])}
    bts = [int(t) for t in bundle.bars.ts]
    n = len(bts)
    off = int(bundle.tf_min - 5.0) * 60_000 if at == "close" else 0
    out: dict[str, NDArray[Any]] = {}
    for name, series in grid["features"].items():
        col = np.full(n, np.nan, dtype=np.float64)
        for i, t in enumerate(bts):
            k = idx.get(t + off)
            if k is not None:
                col[i] = series[k]
        out[name] = col
    return out


# ---------------------------------------------------------------------------
# forward returns on the certified bundle axis
# ---------------------------------------------------------------------------


def forward_return_bps(close: NDArray[Any], h: int) -> NDArray[Any]:
    n = int(close.shape[0])
    out = np.full(n, np.nan, dtype=np.float64)
    if n > h:
        out[: n - h] = (close[h:] / close[: n - h] - 1.0) * 1e4
    return out


# ---------------------------------------------------------------------------
# hashing / writers
# ---------------------------------------------------------------------------


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def sha256_obj(obj: Any) -> str:
    payload = json.dumps(obj, sort_keys=True, default=str).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False, default=str) + "\n",
        encoding="utf-8",
    )


def write_md(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def bundle_for(asset: str, window: str, tf: str = "5m") -> L.Bundle:
    return P.B.get(asset, window, tf)


def window_month(window: str) -> str:
    return {
        "W1": "2026-03",
        "W2": "2026-04",
        "W3": "2026-05",
        "W4": "2026-06",
        "W5": "2026-07",
        "W6": "2026-08",
        "W7": "2026-09",
    }[window]


def vol_shock_of(bundle: L.Bundle) -> NDArray[Any]:
    """The certified RFC-023/RFC-024 volatility detector (imported, never redefined)."""
    return np.asarray(S._vol_shock(bundle), dtype=bool)


def ci95_mean(x: NDArray[Any], n_boot: int = 2000, seed: int = 20261025) -> list[float] | None:
    v = np.asarray(x, dtype=np.float64)
    v = v[np.isfinite(v)]
    if v.shape[0] < 10:
        return None
    rng = np.random.default_rng(seed)
    nb = v.shape[0]
    draws = np.array([float(np.mean(v[rng.integers(0, nb, size=nb)])) for _ in range(n_boot)])
    return [round(float(np.percentile(draws, 2.5)), 4), round(float(np.percentile(draws, 97.5)), 4)]


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
            for k in range(i, j + 1):
                ranks[order[k]] = avg
        i = j + 1
    return ranks


def spearman_ic(sig: NDArray[Any], fwd: NDArray[Any]) -> float | None:
    x = np.asarray(sig, dtype=np.float64)
    y = np.asarray(fwd, dtype=np.float64)
    m = np.isfinite(x) & np.isfinite(y)
    if int(m.sum()) < 20:
        return None
    rx, ry = _rank(x[m]), _rank(y[m])
    if float(np.std(rx)) == 0.0 or float(np.std(ry)) == 0.0:
        return None
    return float(np.corrcoef(rx, ry)[0, 1])


def pearson(a: NDArray[Any], b: NDArray[Any]) -> float | None:
    x = np.asarray(a, dtype=np.float64)
    y = np.asarray(b, dtype=np.float64)
    m = np.isfinite(x) & np.isfinite(y)
    if int(m.sum()) < 3:
        return None
    x, y = x[m], y[m]
    if float(np.std(x)) == 0.0 or float(np.std(y)) == 0.0:
        return None
    return float(np.corrcoef(x, y)[0, 1])


def quantile_spread(sig: NDArray[Any], fwd: NDArray[Any], q: int = 5) -> dict[str, Any]:
    """Top-minus-bottom mean forward return (equal-count quantiles) + monotonicity."""
    x = np.asarray(sig, dtype=np.float64)
    y = np.asarray(fwd, dtype=np.float64)
    m = np.isfinite(x) & np.isfinite(y)
    x, y = x[m], y[m]
    n = x.shape[0]
    if n < q * 5:
        return {"status": "N/A", "n": int(n)}
    order = np.argsort(x, kind="mergesort")
    ys = y[order]
    size = n // q
    means = [float(np.mean(ys[k * size : (k + 1) * size])) for k in range(q)]
    steps = sum(1 for k in range(q - 1) if means[k + 1] >= means[k]) / (q - 1)
    mono = steps if steps >= 0.5 else steps - 1.0
    return {
        "status": "OK",
        "n": int(n),
        "quantile_means_bps": [round(v, 4) for v in means],
        "top_minus_bottom_bps": round(means[-1] - means[0], 4),
        "monotonicity": round(mono, 3),
    }


def mde_table(sigma: float, ns: tuple[int, ...] = (20, 50, 100, 250, 500, 1000)) -> dict[str, Any]:
    factor = 1.959964 + 0.841621
    return {str(n): round(factor * sigma / math.sqrt(n), 4) for n in ns}
