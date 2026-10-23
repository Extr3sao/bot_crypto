"""RFC-032 — EXT-TSMOM-002 remediation engine: long-or-cash spot + T+1 execution.

READ-ONLY, RESEARCH-ONLY, PIT-AWARE, DETERMINISTIC (§37, §38 no agents).

This module builds the *remediated* candidate EXT-TSMOM-002 from raw cache.  It
reuses the frozen EXT-TSMOM-001 economic idea (sign of the trailing 365-day
return, monthly rebalance, 40% vol target, same universe and costs) and applies
**exactly two** material remediations, no more (§5, §6):

    R1  negative desired weight -> 0 (CASH).  No shorts, no borrow, no leverage.
    R2  decision using close T  ->  execution at the T+1 daily OPEN (pre-registered
        executable field), instead of filling at the same close T.

Nothing here searches for an edge, tunes parameters, or tries to rescue the
invalidated EXT-TSMOM-001.  The only question is whether the *executable*
version even keeps enough economics to be worth forward observation (§79).
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
OUT_DIR = REPO / "reports" / "tsmom-remediation"
PAPER_DIR = REPO / "reports" / "paper" / "tsmom002"
RFC031_DIR = REPO / "reports" / "paper-certification"
CACHE_DIR = REPO / "reports" / "external-alpha" / "cache"

CANDIDATE_ID = "EXT-TSMOM-002"
SOURCE_CANDIDATE = "EXT-TSMOM-001"

# §8/§9/§66: the already-observed corpus may only ever be labelled diagnostic.
EVIDENCE_CLASS_HISTORICAL = "HISTORICAL_DIAGNOSTIC"


def is_forward_evidence(timestamp_ms: int, forward_evidence_start_ms: int) -> bool:
    """§67: only data at or after the frozen forward boundary is forward evidence."""
    return int(timestamp_ms) >= int(forward_evidence_start_ms)


# ---------------------------------------------------------------------------
# frozen universe / splits / cost model (identical to EXT-TSMOM-001; §25, §22)
# ---------------------------------------------------------------------------
UNIVERSE: tuple[str, ...] = (
    "BTCUSDT",
    "ETHUSDT",
    "BNBUSDT",
    "XRPUSDT",
    "ADAUSDT",
    "SOLUSDT",
    "DOGEUSDT",
    "DOTUSDT",
    "LTCUSDT",
    "LINKUSDT",
    "BCHUSDT",
    "XLMUSDT",
    "TRXUSDT",
    "ETCUSDT",
    "EOSUSDT",
    "XTZUSDT",
    "ZECUSDT",
    "DASHUSDT",
    "NEOUSDT",
    "ATOMUSDT",
    "VETUSDT",
    "FILUSDT",
    "THETAUSDT",
    "ALGOUSDT",
    "AVAXUSDT",
    "MATICUSDT",
    "FTTUSDT",
    "LUNAUSDT",
    "ICPUSDT",
    "SHIBUSDT",
)

SPLIT_BOUNDS: dict[str, tuple[str, str]] = {
    "DISCOVERY": ("2018-01-01", "2021-06-30"),
    "VALIDATION": ("2021-07-01", "2023-12-31"),
    "HOLDOUT": ("2024-01-01", "2026-09-30"),
}
SPLIT_ORDER = ("DISCOVERY", "VALIDATION", "HOLDOUT")

COST_MODEL: dict[str, float] = {
    "taker_fee_bps": 10.0,
    "half_spread_bps": 3.0,
    "impact_bps": 2.0,
}
PER_SIDE_COST_BPS = float(sum(COST_MODEL.values()))  # 15.0
COST_STRESS_MULTIPLIERS = (1.0, 1.5, 2.0)

# Frozen publication parameters of EXT-TSMOM-002 (§4, §7).
FROZEN_TSMOM_002: dict[str, Any] = {
    "candidate_id": CANDIDATE_ID,
    "source_candidate": SOURCE_CANDIDATE,
    "signal": "sign(trailing 365-calendar-day total return) [unchanged from EXT-TSMOM-001]",
    "instrument": "Binance USDT spot",
    "long_cash_semantics": (
        "positive signal -> LONG spot; negative or zero signal -> CASH (weight 0)"
    ),
    "execution_timing": "decision after close T is available; fill at the T+1 daily OPEN",
    "executable_field": "open",
    "executable_field_note": "pre-registered before computing PnL; not chosen by results",
    "formation_days": 365,
    "rebalance": "monthly (first available daily bar of each calendar month)",
    "weighting": (
        "same frozen RFC-030 weighting: raw = signal*vol_scale; long book "
        "renormalised so sum(long_weights) = 1"
    ),
    "vol_target": 0.40,
    "vol_lookback_days": 60,
    "vol_clip": (0.0, 4.0),
    "universe": list(UNIVERSE),
    "cost_model": "EXT_CRYPTO_COST_MODEL_V1",
    "per_side_cost_bps": PER_SIDE_COST_BPS,
    "cash_yield": 0.0,
    "short_exposure": "FORBIDDEN (R1: negative desired weight -> 0/CASH)",
    "leverage": "FORBIDDEN (sum(long_weights) <= 1)",
    "remediations": [
        "R1 negative desired weight -> 0/CASH",
        "R2 close-T decision -> T+1 open execution",
    ],
    "prohibited_changes": [
        "lookback",
        "vol_target",
        "rebalance_frequency",
        "asset_ranking",
        "universe",
        "signal_threshold",
        "weighting_method",
        "cost_assumptions",
        "risk_scaling",
        "portfolio_leverage",
    ],
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
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8"
    )


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
        raise FileNotFoundError("no external-alpha daily cache; cannot run RFC-032")
    return raw


def build_calendar(raw: dict[str, dict[str, NDArray[Any]]]) -> NDArray[Any]:
    days = sorted(
        {int(t) for d in raw.values() for t in d["open_time_ms"].astype(np.int64).tolist()}
    )
    return np.asarray(days, dtype=np.int64)


def build_matrix(
    raw: dict[str, dict[str, NDArray[Any]]],
    syms: list[str],
    days: NDArray[Any],
    field: str = "close",
) -> NDArray[Any]:
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
        out[s] = datetime.fromtimestamp(int(ts.min()) / 1000, tz=UTC).date().isoformat()
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


def _iso(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000, tz=UTC).date().isoformat()


# ---------------------------------------------------------------------------
# long-or-cash target construction (R1 applied; independent re-derivation)
# ---------------------------------------------------------------------------


def tsmom_long_cash_target(
    close: NDArray[Any],
    i: int,
    formation: int = 365,
    vol_target: float = 0.40,
    vol_lookback: int = 60,
) -> dict[str, Any]:
    """Return the frozen EXT-TSMOM-002 long-or-cash book for decision day ``i``.

    Uses ONLY data with index <= i (PIT-safe signal).  Reproduces the RFC-030
    rule exactly (365-day sign signal, 60-day ex-ante vol, clip [0,4]) and then
    applies remediation R1: every negative desired weight becomes 0 (CASH).  The
    remaining long book is renormalised so that ``sum(weights) == 1`` when any
    long exists; otherwise the whole book is cash.
    """
    a = close.shape[1]
    out: dict[str, Any] = {
        "eligible": np.zeros(a, dtype=bool),
        "signal": np.zeros(a),
        "vol": np.full(a, np.nan),
        "scale": np.zeros(a),
        "weights": np.zeros(a),
        "n_long": 0,
        "n_short": 0,
        "formation_end_idx": None,
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
    win = close[lo : i + 1]
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
    raw = np.where(raw > 0.0, raw, 0.0)  # R1: negative -> cash, never a short
    s = float(np.sum(raw))
    if s > 0:
        out["weights"] = raw / s
    out["n_long"] = int(np.sum(out["weights"] > 0))
    out["n_short"] = 0
    return out


def run_tsmom002(
    close: NDArray[Any],
    open_: NDArray[Any],
    days: NDArray[Any],
    mask: NDArray[Any],
    exec_mode: str = "next_open",
    formation: int = 365,
    vol_target: float = 0.40,
    vol_lookback: int = 60,
    cost_bps: float = PER_SIDE_COST_BPS,
    collect_detail: bool = False,
) -> dict[str, Any]:
    """Frozen EXT-TSMOM-002 simulation.

    ``exec_mode="next_open"`` is the candidate (R2): signal from closes through T,
    filled at the T+1 OPEN, held to the next rebalance's T+1 open.  ``exec_mode=
    "cotimed"`` reproduces the RFC-031 long-or-cash *diagnostic* (close T -> close
    next rebalance) and is used only to recompute the RFC-031 prior (§12).

    Cash months are real observations: the book can be entirely in cash and pays
    the unwind turnover, with zero gross return and zero cash yield (§23).
    """
    a = close.shape[1]
    price = open_ if exec_mode == "next_open" else close
    rebal = [i for i in month_first_days(days) if mask[i]]
    prev = np.zeros(a, dtype=np.float64)
    nets: list[float] = []
    gross: list[float] = []
    costs: list[float] = []
    traded: list[float] = []
    net_exp: list[float] = []
    invested: list[float] = []
    nlong: list[float] = []
    detail: list[dict[str, Any]] = []
    skipped = 0
    for k, i in enumerate(rebal):
        j = rebal[k + 1] if k + 1 < len(rebal) else None
        if j is None:
            break
        tgt = tsmom_long_cash_target(close, i, formation, vol_target, vol_lookback)
        if tgt["formation_end_idx"] is None:
            skipped += 1
            continue
        e0 = i + 1 if exec_mode == "next_open" else i
        e1 = j + 1 if exec_mode == "next_open" else j
        if e1 >= price.shape[0]:
            skipped += 1
            continue
        w = np.asarray(tgt["weights"], dtype=np.float64)
        good = np.isfinite(price[e1]) & np.isfinite(price[e0])
        ret = np.zeros(a)
        ret[good] = price[e1, good] / price[e0, good] - 1.0
        g = float(np.nansum(w * ret) * 1e4)
        tn = float(np.nansum(np.abs(w - prev)))
        c = tn * cost_bps
        nets.append(g - c)
        gross.append(g)
        costs.append(c)
        traded.append(tn)
        net_exp.append(float(np.sum(w)))
        invested.append(float(np.sum(w)))
        nlong.append(float(np.sum(w > 0)))
        if collect_detail:
            detail.append(
                {
                    "rebalance_idx": int(i),
                    "decision_time": _iso(int(days[i])),
                    "exec_time": _iso(int(days[e0])),
                    "n_long": int(np.sum(w > 0)),
                    "invested_capital": float(np.sum(w)),
                    "gross_exposure": float(np.sum(np.abs(w))),
                    "net_exposure": float(np.sum(w)),
                    "traded_notional": tn,
                    "cost_bps": c,
                    "gross_bps": g,
                    "net_bps": g - c,
                }
            )
        prev = w
    return {
        "nets": np.asarray(nets),
        "gross": np.asarray(gross),
        "costs": np.asarray(costs),
        "traded": np.asarray(traded),
        "net_exposure": np.asarray(net_exp),
        "invested": np.asarray(invested),
        "n_long": np.asarray(nlong),
        "skipped": skipped,
        "detail": detail,
    }


# ---------------------------------------------------------------------------
# statistics (hand-rolled; scipy is not installed)
# ---------------------------------------------------------------------------


def _sharpe(x: NDArray[Any], ppy: float) -> float | None:
    x = np.asarray(x, dtype=np.float64)
    if x.size < 2 or float(np.std(x, ddof=1)) == 0.0:
        return None
    return float(np.mean(x) / np.std(x, ddof=1) * math.sqrt(ppy))


def summarise(run: dict[str, Any], periods_per_year: float = 12.0) -> dict[str, Any]:
    nets = np.asarray(run["nets"], dtype=np.float64)
    if nets.size == 0:
        return {"status": "NO_TRADES", "rebalances": 0}
    gross = np.asarray(run["gross"], dtype=np.float64)
    costs = np.asarray(run["costs"], dtype=np.float64)
    traded = np.asarray(run["traded"], dtype=np.float64)
    invested = np.asarray(run["invested"], dtype=np.float64)
    nlong = np.asarray(run["n_long"], dtype=np.float64)
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
        "mean_net_exposure": float(np.mean(run["net_exposure"])),
        "pct_time_long": float(np.mean(nlong > 0)),
        "pct_time_cash": float(np.mean(nlong == 0)),
        "mean_invested_capital": float(np.mean(invested)),
        "mean_n_long": float(np.mean(nlong)),
        "skipped": int(run["skipped"]),
    }


def bootstrap_mean_ci(
    x: NDArray[Any], n_boot: int = 5000, block: int = 1, seed: int = 20261005, alpha: float = 0.05
) -> dict[str, Any]:
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
            sample = np.concatenate([x[s : s + block] for s in starts])[:n]
            means[b] = float(np.mean(sample))
    return {
        "status": "OK",
        "n": int(n),
        "block": int(block),
        "n_boot": int(n_boot),
        "observed_mean": float(np.mean(x)),
        "ci_low": float(np.quantile(means, alpha / 2)),
        "ci_high": float(np.quantile(means, 1 - alpha / 2)),
        "p_mean_le_zero": float(np.mean(means <= 0.0)),
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
    ss_res = float(np.sum(resid**2))
    ss_tot = float(np.sum(ym**2))
    r2 = 1.0 - ss_res / ss_tot if ss_tot > 0 else None
    return {"status": "OK", "alpha_bps": alpha, "beta": beta, "r2": r2, "n": int(y.size)}
