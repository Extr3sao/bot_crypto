"""RFC-031 — TSMOM paper-candidate certification: independent audit engine.

READ-ONLY, RESEARCH-ONLY, PIT-AWARE, DETERMINISTIC (§53 no agents).

This module is RFC-031's *independent second implementation* relative to
``scripts/sprint030_lib.py`` (§17): it loads the raw cache, builds its own
calendar/matrices, re-derives the frozen TSMOM signal/weights/turnover/cost/PnL
and the audit quantities from scratch, sharing no PnL routine with the RFC-030
builder.  The raw loader is allowed to collide (same Binance archives) only
because it is independently hash-verified against the RFC-030 data hashes.

Nothing here is designed to find or improve an edge; it only measures what the
frozen RFC-030 candidate actually does so RFC-031 can CERTIFY or REJECT it.
"""

from __future__ import annotations

import hashlib
import json
import math
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
from numpy.typing import NDArray

REPO = Path(__file__).resolve().parents[1]
OUT_DIR = REPO / "reports" / "paper-certification"
RFC030_DIR = REPO / "reports" / "external-alpha"
CACHE_DIR = RFC030_DIR / "cache"

# ---------------------------------------------------------------------------
# frozen universe / splits / cost model (unchanged from RFC-030; §5, §23)
# ---------------------------------------------------------------------------
UNIVERSE: tuple[str, ...] = (
    "BTCUSDT", "ETHUSDT", "BNBUSDT", "XRPUSDT", "ADAUSDT", "SOLUSDT",
    "DOGEUSDT", "DOTUSDT", "LTCUSDT", "LINKUSDT", "BCHUSDT", "XLMUSDT",
    "TRXUSDT", "ETCUSDT", "EOSUSDT", "XTZUSDT", "ZECUSDT", "DASHUSDT",
    "NEOUSDT", "ATOMUSDT", "VETUSDT", "FILUSDT", "THETAUSDT", "ALGOUSDT",
    "AVAXUSDT", "MATICUSDT", "FTTUSDT", "LUNAUSDT", "ICPUSDT", "SHIBUSDT",
)

SPLIT_BOUNDS: dict[str, tuple[str, str]] = {
    "DISCOVERY": ("2018-01-01", "2021-06-30"),
    "VALIDATION": ("2021-07-01", "2023-12-31"),
    "HOLDOUT": ("2024-01-01", "2026-09-30"),
}
SPLIT_ORDER = ("DISCOVERY", "VALIDATION", "HOLDOUT")

COST_MODEL: dict[str, float] = {
    "taker_fee_bps": 10.0, "half_spread_bps": 3.0, "impact_bps": 2.0,
}
PER_SIDE_COST_BPS = float(sum(COST_MODEL.values()))          # 15.0
COST_STRESS_MULTIPLIERS = (1.0, 1.5, 2.0)

# Frozen publication parameters of EXT-TSMOM-001 (§5, §36).
FROZEN_TSMOM: dict[str, Any] = {
    "strategy_id": "EXT-TSMOM-001",
    "signal": "sign(trailing 365-calendar-day return)",
    "formation_days": 365,
    "rebalance": "monthly (first available daily bar of each calendar month)",
    "portfolio": "gross book normalised to 1; per-asset weight = sign*scale / sum|raw|",
    "vol_target": 0.40,
    "vol_lookback_days": 60,
    "vol_clip": (0.0, 4.0),
    "universe": list(UNIVERSE),
    "cost_model": "EXT_CRYPTO_COST_MODEL_V1",
    "per_side_cost_bps": PER_SIDE_COST_BPS,
    "execution_semantics_frozen": "signal on close T, fill at close T (co-timed)",
}


# ---------------------------------------------------------------------------
# hashing / io
# ---------------------------------------------------------------------------

def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def sha256_obj(obj: Any) -> str:
    payload = json.dumps(obj, sort_keys=True, default=str).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n",
                    encoding="utf-8")


def write_md(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# independent panel load (own code path)
# ---------------------------------------------------------------------------

def load_raw() -> dict[str, dict[str, NDArray[Any]]]:
    raw: dict[str, dict[str, NDArray[Any]]] = {}
    for sym in UNIVERSE:
        p = CACHE_DIR / f"daily_{sym}.npz"
        if p.exists():
            with np.load(p, allow_pickle=False) as z:
                raw[sym] = {k: z[k] for k in z.files}
    if not raw:
        raise FileNotFoundError("no RFC-030 daily cache; cannot run RFC-031")
    return raw


def build_calendar(raw: dict[str, dict[str, NDArray[Any]]]) -> NDArray[Any]:
    days = sorted({int(t) for d in raw.values()
                   for t in d["open_time_ms"].astype(np.int64).tolist()})
    return np.asarray(days, dtype=np.int64)


def build_matrix(raw: dict[str, dict[str, NDArray[Any]]], syms: list[str],
                 days: NDArray[Any], field: str = "close") -> NDArray[Any]:
    di = {int(t): i for i, t in enumerate(days.tolist())}
    m = np.full((days.shape[0], len(syms)), np.nan, dtype=np.float64)
    for j, s in enumerate(syms):
        d = raw[s]
        ts = d["open_time_ms"].astype(np.int64)
        col = d[field].astype(np.float64)
        idx = np.array([di[int(t)] for t in ts.tolist()], dtype=np.int64)
        m[idx, j] = col
    return m


def listing_dates(raw: dict[str, dict[str, NDArray[Any]]]) -> dict[str, str]:
    out: dict[str, str] = {}
    for s, d in raw.items():
        ts = d["open_time_ms"].astype(np.int64)
        first = int(ts.min())
        out[s] = datetime.fromtimestamp(first / 1000, tz=UTC).date().isoformat()
    return out


def first_index(close: NDArray[Any]) -> NDArray[Any]:
    out = np.full(close.shape[1], -1, dtype=np.int64)
    for j in range(close.shape[1]):
        idx = np.where(np.isfinite(close[:, j]))[0]
        if idx.size:
            out[j] = int(idx[0])
    return out


# ---------------------------------------------------------------------------
# calendars / masks
# ---------------------------------------------------------------------------

def _ts(lo: str, hi: str) -> tuple[int, int]:
    lo_ms = int(datetime.fromisoformat(lo + "T00:00:00+00:00").timestamp() * 1000)
    hi_ms = int(datetime.fromisoformat(hi + "T23:59:59+00:00").timestamp() * 1000)
    return lo_ms, hi_ms


def split_mask(days: NDArray[Any], name: str) -> NDArray[Any]:
    lo_ms, hi_ms = _ts(*SPLIT_BOUNDS[name])
    return (days >= lo_ms) & (days <= hi_ms)


def month_first_days(days: NDArray[Any]) -> list[int]:
    seen: set[tuple[int, int]] = set()
    out: list[int] = []
    for i, t in enumerate(days.tolist()):
        d = datetime.fromtimestamp(t / 1000, tz=UTC)
        key = (d.year, d.month)
        if key not in seen:
            seen.add(key)
            out.append(int(i))
    return out


def week_mondays(days: NDArray[Any]) -> list[int]:
    return [i for i, t in enumerate(days.tolist())
            if datetime.fromtimestamp(t / 1000, tz=UTC).weekday() == 0]


# ---------------------------------------------------------------------------
# frozen TSMOM weight construction (independent re-derivation)
# ---------------------------------------------------------------------------

def tsmom_target(close: NDArray[Any], i: int, formation: int = 365,
                 vol_target: float = 0.40, vol_lookback: int = 60) -> dict[str, Any]:
    """Return the frozen EXT-TSMOM-001 target book for decision day ``i``.

    Uses ONLY data with index <= i (PIT-safe signal).  Reproduces the RFC-030
    rule exactly: 365-day sign signal, 60-day ex-ante vol, clip [0,4], gross
    book normalised to 1.  Negative entries are *short* positions.
    """
    a = close.shape[1]
    out: dict[str, Any] = {
        "eligible": np.zeros(a, dtype=bool), "signal": np.zeros(a),
        "vol": np.full(a, np.nan), "scale": np.zeros(a),
        "weights": np.zeros(a), "formation_end_idx": None,
    }
    back = i - formation
    if back < 0:
        return out
    out["formation_end_idx"] = back
    elig = np.isfinite(close[i]) & np.isfinite(close[back])
    out["eligible"] = elig
    sig = np.zeros(a)
    sig[elig] = np.sign(close[i, elig] / close[back, elig] - 1.0)
    out["signal"] = sig
    lo = max(0, i - vol_lookback)
    win = close[lo:i + 1]
    r = win[1:] / win[:-1] - 1.0
    vol = np.full(a, np.nan)
    for j in range(a):
        col = r[:, j]
        col = col[np.isfinite(col)]
        if col.size >= 2:
            vol[j] = float(np.std(col)) * math.sqrt(365.0)
    out["vol"] = vol
    scale = np.zeros(a)
    good = elig & np.isfinite(vol) & (vol > 0)
    scale[good] = np.clip(vol_target / vol[good], 0.0, 4.0)
    out["scale"] = scale
    raw = sig * scale
    s = float(np.sum(np.abs(raw)))
    if s > 0:
        out["weights"] = raw / s
    return out


def run_tsmom(close: NDArray[Any], days: NDArray[Any], mask: NDArray[Any],
              columns: NDArray[Any] | None = None, formation: int = 365,
              vol_target: float = 0.40, vol_lookback: int = 60,
              cost_bps: float = PER_SIDE_COST_BPS, exec_lag: int = 0,
              collect_detail: bool = False) -> dict[str, Any]:
    """Frozen TSMOM simulation.

    ``exec_lag=0`` reproduces RFC-030 exactly (signal close T, fill close T).
    ``exec_lag=1`` is a *diagnostic* T+1-execution variant: the target is built
    from closes through T but the position earns the return from T+1 to the next
    rebalance's T+1.
    """
    cols = np.arange(close.shape[1]) if columns is None else np.asarray(columns)
    cm = close[:, cols]
    rebal = [i for i in month_first_days(days) if mask[i]]
    prev = np.zeros(cm.shape[1])
    nets: list[float] = []
    gross: list[float] = []
    costs: list[float] = []
    traded: list[float] = []
    long_c: list[float] = []
    short_c: list[float] = []
    net_exp: list[float] = []
    detail: list[dict[str, Any]] = []
    skipped = 0
    for k, i in enumerate(rebal):
        j = rebal[k + 1] if k + 1 < len(rebal) else None
        if j is None:
            break
        tgt = tsmom_target(cm, i, formation, vol_target, vol_lookback)
        w = tgt["weights"]
        if not np.any(w):
            skipped += 1
            continue
        e0 = i + exec_lag
        e1 = j + exec_lag
        if e1 >= cm.shape[0]:
            skipped += 1
            continue
        good = np.isfinite(cm[e1]) & np.isfinite(cm[e0])
        ret = np.zeros(cm.shape[1])
        ret[good] = cm[e1, good] / cm[e0, good] - 1.0
        g = float(np.nansum(w * ret) * 1e4)
        tn = float(np.nansum(np.abs(w - prev)))
        c = tn * cost_bps
        nets.append(g - c)
        gross.append(g)
        costs.append(c)
        traded.append(tn)
        long_c.append(float(np.nansum(np.where(w > 0, w * ret, 0.0)) * 1e4))
        short_c.append(float(np.nansum(np.where(w < 0, w * ret, 0.0)) * 1e4))
        net_exp.append(float(np.sum(w)))
        if collect_detail:
            detail.append({
                "rebalance_idx": int(i), "decision_time": _iso(int(days[i])),
                "lookback_end": _iso(int(days[tgt["formation_end_idx"]]))
                if tgt["formation_end_idx"] is not None else None,
                "exec_time": _iso(int(days[e0])),
                "n_long": int(np.sum(w > 0)), "n_short": int(np.sum(w < 0)),
                "gross_exposure": float(np.sum(np.abs(w))),
                "net_exposure": float(np.sum(w)),
                "traded_notional": tn, "cost_bps": c,
                "gross_bps": g, "net_bps": g - c,
                "long_contrib_bps": long_c[-1], "short_contrib_bps": short_c[-1],
            })
        prev = w
    return {
        "nets": np.asarray(nets), "gross": np.asarray(gross),
        "costs": np.asarray(costs), "traded": np.asarray(traded),
        "long_contrib": np.asarray(long_c), "short_contrib": np.asarray(short_c),
        "net_exposure": np.asarray(net_exp), "skipped": skipped,
        "detail": detail,
    }


def _iso(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000, tz=UTC).date().isoformat()


# ---------------------------------------------------------------------------
# statistics (hand-rolled; scipy not installed)
# ---------------------------------------------------------------------------

def summarise(run: dict[str, Any], periods_per_year: float = 12.0) -> dict[str, Any]:
    nets = np.asarray(run["nets"], dtype=np.float64)
    if nets.size == 0:
        return {"status": "NO_TRADES", "rebalances": 0}
    gross = np.asarray(run["gross"], dtype=np.float64)
    costs = np.asarray(run["costs"], dtype=np.float64)
    traded = np.asarray(run["traded"], dtype=np.float64)
    cum = np.cumsum(nets)
    peak = np.maximum.accumulate(cum)
    return {
        "status": "OK",
        "rebalances": int(nets.size),
        "net_expectancy_bps": float(np.mean(nets)),
        "gross_expectancy_bps": float(np.mean(gross)),
        "cost_expectancy_bps": float(np.mean(costs)),
        "net_median_bps": float(np.median(nets)),
        "net_std_bps": float(np.std(nets, ddof=1)) if nets.size > 1 else None,
        "net_pnl_bps": float(np.sum(nets)),
        "mean_turnover_notional": float(np.mean(traded)),
        "net_annualised_pct": float(np.mean(nets) / 1e4 * periods_per_year * 100.0),
        "sharpe": _sharpe(nets, periods_per_year),
        "max_dd_bps": float(np.max(peak - cum)),
        "worst_month_bps": float(np.min(nets)),
        "best_month_bps": float(np.max(nets)),
        "win_rate": float(np.mean(nets > 0)),
        "mean_long_contrib_bps": float(np.mean(run["long_contrib"])),
        "mean_short_contrib_bps": float(np.mean(run["short_contrib"])),
        "mean_net_exposure": float(np.mean(run["net_exposure"])),
        "skipped": int(run["skipped"]),
    }


def _sharpe(x: NDArray[Any], ppy: float) -> float | None:
    x = np.asarray(x, dtype=np.float64)
    if x.size < 2 or float(np.std(x, ddof=1)) == 0.0:
        return None
    return float(np.mean(x) / np.std(x, ddof=1) * math.sqrt(ppy))


def bootstrap_mean_ci(x: NDArray[Any], n_boot: int = 5000, block: int = 1,
                      seed: int = 20261005, alpha: float = 0.05) -> dict[str, Any]:
    """Percentile bootstrap CI + P(mean<=0); block length >1 for serial dependence."""
    x = np.asarray(x, dtype=np.float64)
    if x.size < 3:
        return {"status": "TOO_FEW"}
    rng = np.random.default_rng(seed)
    n = x.size
    means = np.empty(n_boot, dtype=np.float64)
    if block <= 1:
        for b in range(n_boot):
            means[b] = float(np.mean(rng.choice(x, size=n, replace=True)))
    else:
        n_blocks = math.ceil(n / block)
        for b in range(n_boot):
            starts = rng.integers(0, n, size=n_blocks)
            sample = np.concatenate([x[s:s + block] for s in starts])[:n]
            means[b] = float(np.mean(sample))
    lo = float(np.quantile(means, alpha / 2))
    hi = float(np.quantile(means, 1 - alpha / 2))
    return {
        "status": "OK", "n": int(n), "block": int(block), "n_boot": int(n_boot),
        "observed_mean": float(np.mean(x)),
        "ci_low": lo, "ci_high": hi,
        "p_mean_le_zero": float(np.mean(means <= 0.0)),
        "boot_std": float(np.std(means)),
    }


def ols_beta(y: NDArray[Any], x: NDArray[Any]) -> dict[str, Any]:
    y = np.asarray(y, dtype=np.float64)
    x = np.asarray(x, dtype=np.float64)
    m = np.isfinite(y) & np.isfinite(x)
    y, x = y[m], x[m]
    if y.size < 3 or float(np.std(x)) == 0.0:
        return {"status": "TOO_FEW"}
    xm = x - np.mean(x)
    ym = y - np.mean(y)
    beta = float(np.sum(xm * ym) / np.sum(xm * xm))
    alpha = float(np.mean(y) - beta * np.mean(x))
    resid = ym - beta * xm
    ss_res = float(np.sum(resid ** 2))
    ss_tot = float(np.sum(ym ** 2))
    r2 = 1.0 - ss_res / ss_tot if ss_tot > 0 else None
    return {"status": "OK", "alpha_bps": alpha, "beta": beta, "r2": r2,
            "n": int(y.size)}
