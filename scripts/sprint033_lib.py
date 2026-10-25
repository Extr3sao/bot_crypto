"""RFC-033 -- EXT-TSMOM-003 engine: executable LONG/SHORT USDT-perpetual TSMOM.

READ-ONLY, RESEARCH-ONLY, PIT-AWARE, DETERMINISTIC (§50 no agents).

This module implements the *product pivot* decided after RFC-032: the same frozen
external TSMOM hypothesis (sign of the trailing ~365-day return, monthly
rebalance) is now run on an instrument that supports shorting **natively** --
USD-M USDT perpetual futures -- with the signal instrument equal to the
execution instrument (§6, no spot-signal/perp-execution porting).

Differences from the (rejected) long-or-cash spot candidate EXT-TSMOM-002:

    * negative trend -> SHORT perpetual (never neutralised)          (§7)
    * signal == execution instrument == perpetual                     (§6)
    * T+1 daily OPEN execution preserved                              (§8)
    * funding cashflows accounted separately from price PnL           (§17-§19)
    * 1x gross leverage cap, margin / liquidation awareness           (§22-§25)

Nothing here tunes a parameter to make the candidate work: the lookback, the vol
scaling and the rebalance frequency are the frozen external values.
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
OUT_DIR = REPO / "reports" / "perp-tsmom"
CACHE_DIR = OUT_DIR / "cache"

CANDIDATE_ID = "EXT-TSMOM-003"
SOURCE_CANDIDATE = "EXT-TSMOM-002 (rejected) / EXT-TSMOM-001 (concept)"
PRODUCT = "USDT PERPETUAL FUTURES"

# ---------------------------------------------------------------------------
# frozen new chronological splits (§30-§32), declared BEFORE any futures result
# ---------------------------------------------------------------------------
SPLIT_BOUNDS: dict[str, tuple[str, str]] = {
    "DISCOVERY": ("2020-01-01", "2023-06-30"),
    "VALIDATION": ("2023-07-01", "2025-03-31"),
    "HOLDOUT": ("2025-04-01", "2026-09-30"),
}
SPLIT_ORDER = ("DISCOVERY", "VALIDATION", "HOLDOUT")

# §31/§32: the futures corpus has NOT been used to build/select EXT-TSMOM-003.
HOLDOUT_START = "2025-04-01"
HOLDOUT_END = "2026-09-30"
HOLDOUT_ANALYTICS_READ_AT_FREEZE = False

# ---------------------------------------------------------------------------
# TSMOM_PERP_COST_MODEL_V1 (§17, §20, §21) -- realistic conservative public
# taker tier; no VIP / maker / rebate assumption.  Funding is NOT in here.
# ---------------------------------------------------------------------------
COST_MODEL: dict[str, float] = {
    "taker_fee_bps": 5.0,  # Binance USD-M public taker, 0.05% (no BNB/VIP)
    "half_spread_bps": 2.0,  # conservative top-book half spread on liquid perps
    "impact_bps": 1.5,  # conservative small-size impact
}
PER_SIDE_COST_BPS = float(sum(COST_MODEL.values()))  # 8.5
COST_STRESS_MULTIPLIERS = (1.0, 1.5, 2.0)

# §41 funding stress quantile (adverse) multipliers on the realized funding rate
FUNDING_STRESS_QUANTILES = (0.5, 0.75, 0.90)

# §48 headroom thresholds (net / total-cost ratio), predeclared
HEADROOM_THRESHOLDS: dict[str, float] = {
    "THIN": 1.0,
    "INTERESTING": 3.0,
    "STRONG": 6.0,
}

FROZEN_TSMOM_003: dict[str, Any] = {
    "candidate_id": CANDIDATE_ID,
    "source_candidate": SOURCE_CANDIDATE,
    "product": PRODUCT,
    "signal": "sign(trailing 365-calendar-day total return) of the perpetual",
    "instrument": "Binance USD-M USDT perpetual (signal == execution instrument)",
    "long_short_semantics": (
        "positive signal -> LONG perpetual; negative signal -> "
        "SHORT perpetual (no neutralisation of negative trend)"
    ),
    "execution_timing": "decision after close T; fill at the T+1 daily OPEN",
    "executable_field": "open",
    "executable_field_note": "pre-registered before computing PnL; not chosen by results",
    "formation_days": 365,
    "rebalance": "monthly (first available daily bar of each calendar month)",
    "weighting": (
        "raw = signal * clip(vol_target/vol,0,4); gross normalised so "
        "sum(|w|) = min(sum(|raw|), 1.0)  (1x gross leverage cap)"
    ),
    "vol_target": 0.40,
    "vol_lookback_days": 60,
    "vol_clip": (0.0, 4.0),
    "gross_leverage_cap": 1.0,
    "cost_model": "TSMOM_PERP_COST_MODEL_V1",
    "per_side_cost_bps": PER_SIDE_COST_BPS,
    "cash_yield": 0.0,
    "funding": (
        "accounted separately: cashflow = -sign(w) * |w| * realized funding "
        "rate summed over every funding event inside the holding window"
    ),
    "margin": (
        "1x gross; initial margin = gross notional; conservative maintenance "
        "assumption; liquidation safety checked per period"
    ),
    "universe": "PIT futures-eligible universe (perp exists at T; enter only after listing)",
    "splits": {k: list(v) for k, v in SPLIT_BOUNDS.items()},
    "prohibited_changes": [
        "lookback",
        "vol_target",
        "rebalance_frequency",
        "signal_threshold",
        "weighting_method",
        "cost_assumptions",
        "gross_leverage_cap",
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


def sha256_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


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
# panel load
# ---------------------------------------------------------------------------


def universe_from_cache() -> list[str]:
    txt = CACHE_DIR / "_universe.txt"
    if txt.exists():
        return [s for s in txt.read_text(encoding="utf-8").split() if s]
    return sorted(p.stem.replace("perp_daily_", "") for p in CACHE_DIR.glob("perp_daily_*.npz"))


def load_raw(sym: str) -> dict[str, NDArray[Any]]:
    p = CACHE_DIR / f"perp_daily_{sym}.npz"
    with np.load(p, allow_pickle=False) as z:
        return {k: z[k] for k in z.files}


def load_funding(sym: str) -> dict[str, NDArray[Any]] | None:
    p = CACHE_DIR / f"funding_{sym}.npz"
    if not p.exists():
        return None
    with np.load(p, allow_pickle=False) as z:
        return {
            "t": z["funding_time_ms"].astype(np.int64),
            "rate": z["funding_rate"].astype(np.float64),
        }


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


def last_dates(raw: dict[str, dict[str, NDArray[Any]]]) -> dict[str, str]:
    out: dict[str, str] = {}
    for s, d in raw.items():
        ts = d["open_time_ms"].astype(np.int64)
        out[s] = datetime.fromtimestamp(int(ts.max()) / 1000, tz=UTC).date().isoformat()
    return out


def first_index(close: NDArray[Any]) -> NDArray[Any]:
    out = np.full(close.shape[1], -1, dtype=np.int64)
    for j in range(close.shape[1]):
        idx = np.where(np.isfinite(close[:, j]))[0]
        if idx.size:
            out[j] = int(idx[0])
    return out


def last_index(close: NDArray[Any]) -> NDArray[Any]:
    out = np.full(close.shape[1], -1, dtype=np.int64)
    for j in range(close.shape[1]):
        idx = np.where(np.isfinite(close[:, j]))[0]
        if idx.size:
            out[j] = int(idx[-1])
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
# funding accumulator: per-symbol cumulative sum for O(log n) window sums
# ---------------------------------------------------------------------------


class FundingBook:
    def __init__(self, syms: list[str]) -> None:
        self.t: list[NDArray[Any]] = []
        self.cum: list[NDArray[Any]] = []
        self.n_events: list[int] = []
        for s in syms:
            fb = load_funding(s)
            if fb is None or fb["t"].size == 0:
                self.t.append(np.zeros(0, dtype=np.int64))
                self.cum.append(np.zeros(0, dtype=np.float64))
                self.n_events.append(0)
            else:
                order = np.argsort(fb["t"])
                t = fb["t"][order]
                cum = np.concatenate([[0.0], np.cumsum(fb["rate"][order])])
                self.t.append(t)
                self.cum.append(cum)
                self.n_events.append(int(t.size))

    def window_sum(self, j: int, t_left: int, t_right: int) -> float:
        """Sum of realized funding rates with t_left < funding_time <= t_right."""
        t, cum = self.t[j], self.cum[j]
        if t.size == 0:
            return 0.0
        lo = int(np.searchsorted(t, t_left, side="right"))  # first > t_left
        hi = int(np.searchsorted(t, t_right, side="right"))  # first > t_right
        return float(cum[hi] - cum[lo])


# ---------------------------------------------------------------------------
# long/short perpetual target construction (frozen signal, gross-capped)
# ---------------------------------------------------------------------------


def tsmom_perp_target(
    close: NDArray[Any],
    i: int,
    formation: int = 365,
    vol_target: float = 0.40,
    vol_lookback: int = 60,
    gross_cap: float = 1.0,
) -> dict[str, Any]:
    """Return the frozen EXT-TSMOM-003 long/short perp book for decision day ``i``.

    Uses ONLY data with index <= i (PIT-safe signal).  Same 365-day sign rule and
    60-day ex-ante vol as the external reproduction, but negative signals stay
    negative (short) and the whole book is scaled so gross exposure never exceeds
    ``gross_cap`` (1x).
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
        "desired_gross": 0.0,
        "actual_gross": 0.0,
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
    desired_gross = float(np.sum(np.abs(raw)))
    out["desired_gross"] = desired_gross
    if desired_gross > gross_cap and desired_gross > 0:
        w = raw * (gross_cap / desired_gross)
    else:
        w = raw
    out["weights"] = w
    out["actual_gross"] = float(np.sum(np.abs(w)))
    out["n_long"] = int(np.sum(w > 0))
    out["n_short"] = int(np.sum(w < 0))
    return out


def run_tsmom003(
    close: NDArray[Any],
    open_: NDArray[Any],
    high: NDArray[Any],
    low: NDArray[Any],
    days: NDArray[Any],
    funding: FundingBook,
    mask: NDArray[Any],
    exec_mode: str = "next_open",
    formation: int = 365,
    vol_target: float = 0.40,
    vol_lookback: int = 60,
    cost_bps: float = PER_SIDE_COST_BPS,
    gross_cap: float = 1.0,
    funding_scale: float = 1.0,
    cost_mult: float = 1.0,
    collect_detail: bool = False,
    target_fn: Any = None,
) -> dict[str, Any]:
    """Frozen EXT-TSMOM-003 simulation.

    ``exec_mode="next_open"`` is the candidate (§8): signal from closes through T,
    filled at the T+1 OPEN, held to the next rebalance's T+1 open.  ``exec_mode=
    "cotimed"`` is a diagnostic variant (close T -> close next rebalance).

    Returns price PnL, funding PnL, trading cost and net separately (§19).  Also
    tracks the worst intraperiod adverse excursion for margin safety (§22-§25).
    """
    a = close.shape[1]
    price = open_ if exec_mode == "next_open" else close
    rebal = [i for i in month_first_days(days) if mask[i]]
    prev = np.zeros(a, dtype=np.float64)
    price_bps: list[float] = []
    fund_bps: list[float] = []
    cost_list: list[float] = []
    traded: list[float] = []
    net_exp: list[float] = []
    gross_exp: list[float] = []
    des_gross: list[float] = []
    nlong: list[float] = []
    nshort: list[float] = []
    long_px: list[float] = []
    short_px: list[float] = []
    long_fund: list[float] = []
    short_fund: list[float] = []
    worst_adverse: list[float] = []
    detail: list[dict[str, Any]] = []
    skipped = 0
    for k, i in enumerate(rebal):
        j = rebal[k + 1] if k + 1 < len(rebal) else None
        if j is None:
            break
        tgt = (
            target_fn(close, i)
            if target_fn is not None
            else tsmom_perp_target(close, i, formation, vol_target, vol_lookback, gross_cap)
        )
        if tgt["formation_end_idx"] is None:
            skipped += 1
            continue
        e0 = i + 1 if exec_mode == "next_open" else i
        e1 = j + 1 if exec_mode == "next_open" else j
        if e1 >= price.shape[0]:
            skipped += 1
            continue
        w = np.asarray(tgt["weights"], dtype=np.float64)
        good = np.isfinite(price[e1]) & np.isfinite(price[e0]) & (price[e0] > 0)
        ret = np.zeros(a)
        ret[good] = price[e1, good] / price[e0, good] - 1.0
        # price PnL (signed: shorts profit when price falls)
        px = w * ret
        g = float(np.nansum(px) * 1e4)
        # funding over the holding window, charged on entry notional
        f_sum = np.zeros(a)
        t_left, t_right = int(days[e0]), int(days[e1])
        for jj in range(a):
            if w[jj] != 0.0:
                f_sum[jj] = funding.window_sum(jj, t_left, t_right)
        f = float(-np.nansum(w * f_sum) * 1e4 * funding_scale)
        tn = float(np.nansum(np.abs(w - prev)))
        c = tn * cost_bps * cost_mult
        price_bps.append(g)
        fund_bps.append(f)
        cost_list.append(c)
        traded.append(tn)
        net_exp.append(float(np.sum(w)))
        gross_exp.append(float(np.sum(np.abs(w))))
        des_gross.append(float(tgt["desired_gross"]))
        nlong.append(float(np.sum(w > 0)))
        nshort.append(float(np.sum(w < 0)))
        long_px.append(float(np.nansum(px[w > 0]) * 1e4))
        short_px.append(float(np.nansum(px[w < 0]) * 1e4))
        long_fund.append(float(-np.nansum((w * f_sum)[w > 0]) * 1e4 * funding_scale))
        short_fund.append(float(-np.nansum((w * f_sum)[w < 0]) * 1e4 * funding_scale))
        # worst intraperiod adverse excursion (margin safety)
        adverse = 0.0
        for jj in range(a):
            if w[jj] > 0 and np.isfinite(low[e0 : e1 + 1, jj]).any():
                adverse += w[jj] * (float(np.nanmin(low[e0 : e1 + 1, jj])) / price[e0, jj] - 1.0)
            elif w[jj] < 0 and np.isfinite(high[e0 : e1 + 1, jj]).any():
                adverse += w[jj] * (float(np.nanmax(high[e0 : e1 + 1, jj])) / price[e0, jj] - 1.0)
        worst_adverse.append(float(adverse))
        if collect_detail:
            detail.append(
                {
                    "rebalance_idx": int(i),
                    "decision_time": _iso(int(days[i])),
                    "exec_time": _iso(int(days[e0])),
                    "n_long": int(np.sum(w > 0)),
                    "n_short": int(np.sum(w < 0)),
                    "gross_exposure": float(np.sum(np.abs(w))),
                    "net_exposure": float(np.sum(w)),
                    "traded_notional": tn,
                    "price_bps": g,
                    "funding_bps": f,
                    "cost_bps": c,
                    "net_bps": g + f - c,
                }
            )
        prev = w
    price_a = np.asarray(price_bps)
    fund_a = np.asarray(fund_bps)
    cost_a = np.asarray(cost_list)
    return {
        "price": price_a,
        "funding": fund_a,
        "costs": cost_a,
        "nets": price_a + fund_a - cost_a,
        "traded": np.asarray(traded),
        "net_exposure": np.asarray(net_exp),
        "gross_exposure": np.asarray(gross_exp),
        "desired_gross": np.asarray(des_gross),
        "n_long": np.asarray(nlong),
        "n_short": np.asarray(nshort),
        "long_price": np.asarray(long_px),
        "short_price": np.asarray(short_px),
        "long_funding": np.asarray(long_fund),
        "short_funding": np.asarray(short_fund),
        "worst_adverse": np.asarray(worst_adverse),
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
    price = np.asarray(run["price"], dtype=np.float64)
    funding = np.asarray(run["funding"], dtype=np.float64)
    costs = np.asarray(run["costs"], dtype=np.float64)
    cum = np.cumsum(nets)
    peak = np.maximum.accumulate(cum)
    return {
        "status": "OK",
        "rebalances": int(nets.size),
        "net_expectancy_bps": float(np.mean(nets)),
        "price_expectancy_bps": float(np.mean(price)),
        "funding_expectancy_bps": float(np.mean(funding)),
        "cost_expectancy_bps": float(np.mean(costs)),
        "gross_expectancy_bps": float(np.mean(price)),  # price-only "gross"
        "net_median_bps": float(np.median(nets)),
        "net_std_bps": float(np.std(nets, ddof=1)) if nets.size > 1 else None,
        "net_pnl_bps": float(np.sum(nets)),
        "price_pnl_bps": float(np.sum(price)),
        "funding_pnl_bps": float(np.sum(funding)),
        "cost_pnl_bps": float(np.sum(costs)),
        "mean_turnover_notional": float(np.mean(run["traded"])),
        "net_annualised_pct": float(np.mean(nets) / 1e4 * periods_per_year * 100.0),
        "sharpe": _sharpe(nets, periods_per_year),
        "max_dd_bps": float(np.max(peak - cum)),
        "worst_month_bps": float(np.min(nets)),
        "best_month_bps": float(np.max(nets)),
        "win_rate": float(np.mean(nets > 0)),
        "mean_net_exposure": float(np.mean(run["net_exposure"])),
        "mean_gross_exposure": float(np.mean(run["gross_exposure"])),
        "mean_desired_gross": float(np.mean(run["desired_gross"])),
        "pct_time_net_long": float(np.mean(np.asarray(run["net_exposure"]) > 0)),
        "pct_time_net_short": float(np.mean(np.asarray(run["net_exposure"]) < 0)),
        "mean_n_long": float(np.mean(run["n_long"])),
        "mean_n_short": float(np.mean(run["n_short"])),
        "long_price_bps": float(np.sum(run["long_price"])),
        "short_price_bps": float(np.sum(run["short_price"])),
        "long_funding_bps": float(np.sum(run["long_funding"])),
        "short_funding_bps": float(np.sum(run["short_funding"])),
        "worst_adverse_bps": float(np.min(run["worst_adverse"]) * 1e4),
        "skipped": int(run["skipped"]),
    }


def bootstrap_mean_ci(
    x: NDArray[Any], n_boot: int = 5000, block: int = 1, seed: int = 20261005, alpha: float = 0.05
) -> dict[str, Any]:
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


def headroom_class(net_bps: float, cost_bps: float, adverse_funding_bps: float) -> dict[str, Any]:
    total_cost = abs(cost_bps) + max(0.0, adverse_funding_bps)
    ratio = (net_bps / total_cost) if total_cost > 0 else None
    if ratio is None:
        cls = "UNDEFINED"
    elif ratio < HEADROOM_THRESHOLDS["THIN"]:
        cls = "THIN"
    elif ratio < HEADROOM_THRESHOLDS["INTERESTING"]:
        cls = "INTERESTING"
    elif ratio < HEADROOM_THRESHOLDS["STRONG"]:
        cls = "STRONG"
    else:
        cls = "HIGH_MARGIN"
    return {
        "net_bps": net_bps,
        "total_cost_bps": total_cost,
        "net_over_cost": ratio,
        "classification": cls,
        "thresholds": HEADROOM_THRESHOLDS,
    }
