"""H5-ORDERFLOW-IMBALANCE-CONTINUATION-01 — core evaluation (frozen prereg).

Implements EXACTLY the preregistered spec
``docs/external-audit-01/h5-orderflow-imbalance-01/H5_SPEC.json``
(sha256 c743fba4…, commit c426b35 — the spec is the single authority).

Pure research evaluation over public kline data:

- no RiskManager / PaperBroker / campaign mutation,
- no parameter tuning, no fallback thresholds,
- PIT-safe by construction: every decision at bar ``t`` consumes only bars
  with close_time <= decision time; entry uses the NEXT bar's open (the
  fill instant of the decision),
- one economic experiment; this file never fetches, never writes results
  (the runner script owns exactly-once ledger flow + artifacts).

Frozen mechanics (do not modify without a NEW preregistration):

- OFI_t = (2 * takerBuyBaseVolume_t / volume_t) - 1  (in (-1, +1]); volume
  == 0 -> NaN -> NO_SIGNAL (never divide by zero),
- zOFI_t: population mean/std of OFI over the trailing 336 bars ending at
  the decision bar (ddof=0, same window convention as the frozen H3 spread
  stats); std <= 0 -> NaN,
- P_t = numberOfTrades_t / SMA(numberOfTrades, trailing 336 bars ending at
  t); SMA == 0 -> NaN,
- entry LONG  zOFI >= +2.5 AND P >= 1.5; entry SHORT zOFI <= -2.5 AND
  P >= 1.5; flat only; direction comes ONLY from the sign of zOFI,
- entry at open[t+1]; SL = entry -/+ ATR14 (simple mean TR, bars t-13..t,
  frozen H1 convention); time exit at close of bar t+12; stop assumed
  first in any bar it touches (pessimistic); cooldown 4 bars after exit;
  incomplete tail skipped and counted,
- R unit: ATR14/entry risk fraction; cost: 10 bps round trip ABSOLUTE
  (net = gross - (bps/10000)/risk_frac); scenarios 0/5/10/20/40 bps are
  linear, anchored at 0 bps = gross (DEF-RESEARCH-COST-001 cannot recur).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, cast

import numpy as np
from numpy.typing import NDArray

from trading_bot.research.h1_regime_transition import (  # frozen stat primitives
    bootstrap_sharpe,
    max_drawdown_r,
    mc_dd95,
    permutation_p,
    profit_factor,
    split_sign,
)

# ---- frozen spec constants (mirrors of H5_SPEC.json; keep in sync) ----
LOOKBACK_BARS = 336
Z_ENTRY = 2.5
P_GATE = 1.5
HOLD_BARS = 12
COOLDOWN_BARS = 4
ATR_PERIOD = 14
COST_RT_BPS = 10.0  # round trip, single leg, absolute semantics
MIN_TOTAL_TRADES = 30
MIN_DIRECTION_CELL = 15
MIN_ASSET_CELL = 10
SEED = 20260910
PF_NET_MIN = 1.15
P_SHARPE_MIN = 0.90
PERM_P_MAX = 0.05
WARMUP = LOOKBACK_BARS - 1  # first decision index with a full 336-bar trailing window
_SHIFT_SECONDS = 3_600_000  # 1h bar span in ms

ResultClass = str  # DISCOVERY_PASS | DISCOVERY_FAIL | INSUFFICIENT_SAMPLE | REDUNDANT_CANDIDATE


@dataclass(frozen=True, slots=True)
class H5Trade:
    """One simulated single-asset flow-continuation trade in ATR-R multiples."""

    asset: str
    direction: str  # "LONG" (zOFI >= +2.5) | "SHORT" (zOFI <= -2.5)
    decision_index: int
    decision_ts: int
    entry_index: int
    entry_ts: int
    exit_index: int
    exit_ts: int
    entry_price: float
    stop_price: float
    exit_price: float
    atr: float
    risk_frac: float  # atr / entry (R unit in price fraction)
    zofi: float
    part: float
    gross_r: float  # pre-cost
    cost_r: float  # at COST_RT_BPS round trip, absolute
    net_r: float
    regime_at_entry: str = ""  # canonical regime state label at decision bar
    kind: str = "H5"


def close_time(ts_ms: int) -> int:
    """Close instant of a 1h bar (openTime + span - 1ms)."""
    return ts_ms + _SHIFT_SECONDS - 1


def _rolling_sum(x: NDArray[np.float64], w: int) -> NDArray[np.float64]:
    """out[i] = sum(x[i-w+1 .. i]); out[:w-1] = nan."""
    c = np.concatenate(([0.0], np.nancumsum(x)))
    out = np.full(x.shape[0], np.nan)
    out[w - 1 :] = c[w:] - c[: x.shape[0] - w + 1]
    return out


def compute_features(
    volume: NDArray[np.float64], ntrades: NDArray[np.float64], taker_buy: NDArray[np.float64]
) -> dict[str, NDArray[np.float64]]:
    """PIT trailing features for every bar t (nan where invalid).

    OFI uses only bar t; zOFI and participation use only the trailing
    LOOKBACK_BARS window ending at t. All nan positions are NO_SIGNAL.
    """
    n = volume.shape[0]
    with np.errstate(invalid="ignore", divide="ignore"):
        ofi = 2.0 * taker_buy / volume - 1.0
    ofi = np.where(volume > 0, ofi, np.nan)

    finite = np.isfinite(ofi)
    ofi0 = np.where(finite, ofi, 0.0)
    sm, sv = _rolling_sum(ofi0, LOOKBACK_BARS), _rolling_sum(ofi0 * ofi0, LOOKBACK_BARS)
    cnt = _rolling_sum(finite.astype(np.float64), LOOKBACK_BARS)
    full = cnt == LOOKBACK_BARS
    mean = np.where(full, sm / LOOKBACK_BARS, np.nan)
    var = np.where(full, np.maximum(sv / LOOKBACK_BARS - (sm / LOOKBACK_BARS) ** 2, 0.0), np.nan)
    std = np.sqrt(var)
    with np.errstate(invalid="ignore", divide="ignore"):
        zofi = (ofi - mean) / std
    zofi = np.where(full & (std > 0) & finite, zofi, np.nan)

    sm_n = _rolling_sum(ntrades.astype(np.float64), LOOKBACK_BARS)
    with np.errstate(invalid="ignore", divide="ignore"):
        part = ntrades.astype(np.float64) / (sm_n / LOOKBACK_BARS)
    part = np.where(full & (sm_n > 0), part, np.nan)

    valid = np.arange(n) >= WARMUP
    return {
        "ofi": ofi,
        "zofi": np.where(valid, zofi, np.nan),
        "part": np.where(valid, part, np.nan),
    }


def atr14(
    hi: NDArray[np.float64], lo: NDArray[np.float64], cl: NDArray[np.float64], end: int
) -> float:
    """Simple mean true range over bars ``end-13 .. end`` (frozen H1 convention)."""
    s = end - ATR_PERIOD + 1
    trs: list[float] = []
    for i in range(s + 1, end + 1):
        trs.append(
            max(
                hi[i] - lo[i],
                abs(hi[i] - cl[i - 1]),
                abs(lo[i] - cl[i - 1]),
            )
        )
    return sum(trs) / len(trs)


def simulate_h5(
    ts: NDArray[Any],
    op: NDArray[np.float64],
    hi: NDArray[np.float64],
    lo: NDArray[np.float64],
    cl: NDArray[np.float64],
    volume: NDArray[np.float64],
    ntrades: NDArray[np.float64],
    taker_buy: NDArray[np.float64],
    asset: str,
    feat: dict[str, NDArray[np.float64]] | None = None,
    regime_labels: dict[int, str] | None = None,
) -> tuple[list[H5Trade], int, int]:
    """Frozen H5 simulation. Returns (trades, skipped_incomplete, blocked_by_cooldown)."""
    if feat is None:
        feat = compute_features(volume, ntrades, taker_buy)
    zofi, part = feat["zofi"], feat["part"]
    n = ts.shape[0]
    trades: list[H5Trade] = []
    skipped_incomplete = 0
    blocked_by_cooldown = 0
    busy_until = -1  # last holding bar index per asset (cooldown anchor)
    for t in range(WARMUP, n - 1):
        z, p = zofi[t], part[t]
        if not (np.isfinite(z) and np.isfinite(p) and p >= P_GATE):
            continue
        if z >= Z_ENTRY:
            direction = "LONG"
        elif z <= -Z_ENTRY:
            direction = "SHORT"
        else:
            continue
        if t <= busy_until:
            blocked_by_cooldown += 1
            continue
        exit_index = t + HOLD_BARS  # close of bar t+12 (t = decision bar)
        if exit_index > n - 1:
            skipped_incomplete += 1  # mechanical completeness: frozen horizon
            continue
        entry_index = t + 1
        atr = atr14(hi, lo, cl, t)
        entry = op[entry_index]
        stop = entry - atr if direction == "LONG" else entry + atr
        exit_price: float | None = None
        exit_at = exit_index
        for j in range(entry_index, exit_index + 1):
            hit_stop = lo[j] <= stop if direction == "LONG" else hi[j] >= stop
            if hit_stop:  # pessimistic: stop assumed first in any bar it touches
                exit_price = stop
                exit_at = j
                break
        if exit_price is None:
            exit_price = cl[exit_index]
        move = (exit_price - entry) if direction == "LONG" else (entry - exit_price)
        risk_frac = atr / entry
        gross_r = move / atr
        cost_r = (COST_RT_BPS / 10_000.0) / risk_frac
        trades.append(
            H5Trade(
                asset=asset,
                direction=direction,
                decision_index=t,
                decision_ts=close_time(int(ts[t])),
                entry_index=entry_index,
                entry_ts=int(ts[entry_index]),
                exit_index=exit_at,
                exit_ts=close_time(int(ts[exit_at])),
                entry_price=entry,
                stop_price=stop,
                exit_price=exit_price,
                atr=atr,
                risk_frac=risk_frac,
                zofi=float(z),
                part=float(p),
                gross_r=gross_r,
                cost_r=cost_r,
                net_r=gross_r - cost_r,
                regime_at_entry=(regime_labels or {}).get(t, ""),
            )
        )
        busy_until = exit_index + COOLDOWN_BARS
    return trades, skipped_incomplete, blocked_by_cooldown


def cost_scenario_net_r(trades: list[H5Trade], cost_bps: float) -> list[float]:
    """Net R per trade at an ABSOLUTE round-trip cost scenario.

    cost scales LINEARLY in the round-trip bps and is anchored at
    0 bps = gross: net(bps) = gross - cost_r * (bps / COST_RT_BPS).
    Monotone non-increasing by construction for a fixed trade set
    (DEF-RESEARCH-COST-001 proof).
    """
    scale = cost_bps / COST_RT_BPS
    return [t.gross_r - t.cost_r * scale for t in trades]


def summarize(trades: list[H5Trade]) -> dict[str, Any]:
    """B1 metrics at the frozen base cost (absolute 10 bps RT)."""
    gross = [t.gross_r for t in trades]
    net = [t.net_r for t in trades]
    if not net:
        return {"N": 0}
    s, lo, hi, p_gt0 = bootstrap_sharpe(net)
    hold = [(t.exit_index - t.entry_index + 1) for t in trades]
    return {
        "N": len(net),
        "gross_expectancy_R": float(np.mean(gross)) if gross else 0.0,
        "net_expectancy_R": float(np.mean(net)),
        "PF_gross": profit_factor(gross),
        "PF_net": profit_factor(net),
        "Sharpe": s,
        "Sharpe_CI95": [lo, hi],
        "P_Sharpe_gt_0": p_gt0,
        "permutation_p": permutation_p(net),
        "win_rate": sum(1 for r in net if r > 0) / len(net),
        "wins": sum(1 for r in net if r > 0),
        "losses": sum(1 for r in net if r < 0),
        "max_drawdown_R": max_drawdown_r(net),
        "MC_DD95_R": mc_dd95(net),
        "cost_drag_R": float(np.mean(gross) - np.mean(net)),
        "halves": split_sign(net, 2),
        "thirds": split_sign(net, 3),
        "walk_forward_last_third_net_R": (
            float(np.mean(net[2 * (len(net) // 3) :])) if len(net) >= 3 else 0.0
        ),
        "mean_holding_bars": float(np.mean(hold)) if hold else 0.0,
    }


def classify(
    metrics: dict[str, Any], n_direction_cells: list[int], n_asset_cells: list[int]
) -> ResultClass:
    """Frozen B4 classification (pure function of metrics)."""
    n = int(metrics.get("N", 0))
    if (
        n < MIN_TOTAL_TRADES
        or any(c < MIN_DIRECTION_CELL for c in n_direction_cells)
        or any(c < MIN_ASSET_CELL for c in n_asset_cells)
    ):
        return "INSUFFICIENT_SAMPLE"
    halves = cast(Any, metrics["halves"])
    thirds = cast(Any, metrics["thirds"])
    gates = {
        "net_expectancy_R>0": float(metrics["net_expectancy_R"]) > 0.0,
        "PF_net>1.15": float(metrics["PF_net"]) > PF_NET_MIN,
        "P_Sharpe_gt_0>=0.90": float(metrics["P_Sharpe_gt_0"]) >= P_SHARPE_MIN,
        "permutation_p<=0.05": float(metrics["permutation_p"]) <= PERM_P_MAX,
        "halves_uniform_positive": all(h == 1 for h in halves),
        "thirds_uniform_positive": all(h == 1 for h in thirds),
        "walk_forward>0": float(metrics["walk_forward_last_third_net_R"]) > 0.0,
    }
    return "DISCOVERY_PASS" if all(gates.values()) else "DISCOVERY_FAIL"
