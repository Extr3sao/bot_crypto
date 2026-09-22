"""H3-RELVAL-BTCETH-BETANEUTRAL-SPREAD-01 — core evaluation (frozen prereg).

Implements EXACTLY the preregistered spec
``docs/external-audit-01/h3-relative-value-01/H3_SPEC.json``
(sha256 90c56699…, commit 83b3acd — the spec is the single authority).

Pure research evaluation over public OHLCV:

- no RiskManager / PaperBroker / campaign mutation,
- no parameter tuning, no fallback thresholds,
- PIT by construction: beta_t, mean_t, std_t, corr_t and z_t at decision
  bar ``t`` use ONLY observations with index <= t (trailing windows);
  entry uses the NEXT bar's open (the fill instant of the decision),
- two economic legs (BTC + ETH) with FOUR executions per round trip
  (entry+exit on each leg), costs applied with ABSOLUTE semantics
  (DEF-RESEARCH-COST-001 cannot recur: net(bps) = gross - cost(bps),
  cost linear and anchored at 0 bps = gross; monotone non-increasing),
- funding is EXCLUDED by preregistration (spec.cost_model.funding = N/A).

Frozen mechanics (do not modify without a NEW preregistration):

- spread s_t = ln(close_BTC_t) - beta_t * ln(close_ETH_t),
- beta_t: OLS of d(ln close_BTC) on d(ln close_ETH) over the trailing
  336 return observations; normalization mean/std of s over the same
  trailing 336-bar span; corr gate: Pearson corr of ln-returns >= 0.60,
- entry |z| >= 2.5 (spread SHORT at z >= +2.5, LONG at z <= -2.5),
- exit |z| <= 0.5, hard stop |z| >= 4.0 (assumed first), time stop 48 bars,
  cooldown 4 bars, sizing notional_B = |beta_t| * notional_A,
- R unit: trailing spread std (risk_frac = std_t); gross move measured
  from the pair spread at the entry fill instant (open[t+1] prices).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

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

# ---- frozen spec constants (mirrors of H3_SPEC.json; keep in sync) ----
LOOKBACK_BARS = 336
MIN_OBS_RETURNS = 168
CORR_GATE = 0.60
Z_ENTRY = 2.5
Z_EXIT = 0.5
Z_STOP = 4.0
HOLD_BARS = 48
COOLDOWN_BARS = 4
COST_SIDE_BPS = 5.0  # per side, per leg (binanceusdm taker reference basis)
MIN_TOTAL_TRADES = 30
MIN_DIRECTION_CELL = 15
SEED = 20260910
PF_NET_MIN = 1.15
P_SHARPE_MIN = 0.90
PERM_P_MAX = 0.05
WARMUP = LOOKBACK_BARS  # z additionally requires a full spread window: effective first decision bar = 2*LOOKBACK_BARS (beta history + full 336-bar spread window) — a deterministic consequence of the frozen formulas

ResultClass = str  # DISCOVERY_PASS | DISCOVERY_FAIL | INSUFFICIENT_SAMPLE | REDUNDANT_CANDIDATE


@dataclass(frozen=True, slots=True)
class H3Trade:
    """One simulated two-leg pair trade in spread-R multiples."""

    direction: str  # "SPREAD_SHORT" (z>=+2.5) | "SPREAD_LONG" (z<=-2.5)
    decision_index: int
    decision_ts: int
    entry_index: int
    entry_ts: int
    exit_index: int
    exit_ts: int
    beta: float
    spread_std: float  # R unit at entry (risk_frac)
    entry_z: float
    exit_z: float
    exit_reason: str  # "Z_REVERT" | "Z_STOP" | "TIME_STOP"
    gross_r: float  # pre-cost
    cost_r: float  # at COST_SIDE_BPS per side, 4 executions (absolute)
    net_r: float
    gross_exposure: float  # notional_A + notional_B (per unit A)
    net_dollar_exposure: float  # signed: long_B - short_A (per unit A)
    regime_at_entry: str = ""  # BTC canonical regime state label at decision bar
    kind: str = "H3"


# ---------------------------------------------------------------------------
# Rolling PIT features (vectorized, trailing windows only)
# ---------------------------------------------------------------------------


def _rolling_sum(x: NDArray[np.float64], w: int) -> NDArray[np.float64]:
    """out[i] = sum(x[i-w+1 .. i]); out[:w-1] = nan."""
    c = np.concatenate(([0.0], np.cumsum(x)))
    out = np.full(x.shape[0], np.nan)
    out[w - 1 :] = c[w:] - c[: x.shape[0] - w + 1]
    return out


def compute_features(
    close_a: NDArray[np.float64], close_b: NDArray[np.float64]
) -> dict[str, NDArray[np.float64]]:
    """PIT trailing features for every bar t (nan where the window is incomplete).

    beta over the trailing LOOKBACK_BARS return observations; mean/std of the
    spread LEVELS over the same trailing bar span; corr of ln-returns.
    """
    n = close_a.shape[0]
    la, lb = np.log(close_a), np.log(close_b)
    ra, rb = np.diff(la, prepend=la[0]), np.diff(lb, prepend=lb[0])
    ra[0] = 0.0
    rb[0] = 0.0
    w = LOOKBACK_BARS

    sa, ca = _rolling_sum(ra, w), _rolling_sum(ra * ra, w)
    sb, cb = _rolling_sum(rb, w), _rolling_sum(rb * rb, w)
    sab = _rolling_sum(ra * rb, w)
    cov = sab / w - (sa / w) * (sb / w)
    var_a = ca / w - (sa / w) ** 2
    var_b = cb / w - (sb / w) ** 2
    beta = np.where(var_b > 0, cov / np.maximum(var_b, 1e-18), np.nan)
    corr = np.where(
        (var_a > 0) & (var_b > 0),
        cov / np.sqrt(np.maximum(var_a * var_b, 1e-18)),
        np.nan,
    )

    s = la - beta * lb
    # nan-aware rolling mean/std of the spread levels: the window is valid
    # only when ALL w values are finite (beta exists across the whole span).
    s0 = np.where(np.isfinite(s), s, 0.0)
    sm, sv = _rolling_sum(s0, w), _rolling_sum(s0 * s0, w)
    cnt = _rolling_sum(np.isfinite(s).astype(np.float64), w)
    full = cnt == w
    mean = np.where(full, sm / w, np.nan)
    var_s = np.where(full, np.maximum(sv / w - (sm / w) ** 2, 0.0), np.nan)
    std = np.sqrt(var_s)

    with np.errstate(invalid="ignore", divide="ignore"):
        z = (s - mean) / std
    valid = (
        ~np.isnan(beta)
        & ~np.isnan(std)
        & (std > 0)
        & ~np.isnan(corr)
        & (np.arange(n) >= WARMUP)
        & (np.arange(n) >= MIN_OBS_RETURNS)
    )
    z = np.where(valid, z, np.nan)
    return {"beta": beta, "spread_mean": mean, "spread_std": std, "corr": corr, "z": z, "spread": s}


# ---------------------------------------------------------------------------
# Simulation (frozen entry/exit/cost, one position at a time)
# ---------------------------------------------------------------------------


def simulate_pair(
    timestamps: NDArray[Any],
    open_a: NDArray[np.float64],
    close_a: NDArray[np.float64],
    open_b: NDArray[np.float64],
    close_b: NDArray[np.float64],
    feat: dict[str, NDArray[np.float64]],
    regime_labels: dict[int, str] | None = None,
) -> tuple[list[H3Trade], int]:
    """Frozen pair simulation. Returns (trades, blocked_by_cooldown_count)."""
    trades: list[H3Trade] = []
    blocked = 0
    n = timestamps.shape[0]
    busy_until = -1  # last holding bar index (cooldown anchor)
    t = WARMUP
    while t < n - 1:  # entry needs bar t+1
        z = feat["z"][t]
        if not np.isfinite(z) or feat["corr"][t] < CORR_GATE or t <= busy_until:
            t += 1
            continue
        if abs(z) < Z_ENTRY:
            t += 1
            continue
        direction = "SPREAD_SHORT" if z >= Z_ENTRY else "SPREAD_LONG"
        d = -1.0 if z >= Z_ENTRY else 1.0
        beta = float(feat["beta"][t])
        std = float(feat["spread_std"][t])
        entry_index = t + 1
        # spread at the fill instant (open prices of both legs, PIT at entry)
        s_entry = float(np.log(open_a[entry_index]) - beta * np.log(open_b[entry_index]))
        exit_index = -1
        exit_z = float("nan")
        exit_reason = ""
        for j in range(entry_index, min(entry_index + HOLD_BARS, n)):
            zj = float(feat["z"][j])
            if not np.isfinite(zj):
                continue
            if abs(zj) >= Z_STOP:  # stop assumed first (pessimistic, frozen)
                exit_index, exit_z, exit_reason = j, zj, "Z_STOP"
                break
            if abs(zj) <= Z_EXIT:
                exit_index, exit_z, exit_reason = j, zj, "Z_REVERT"
                break
            if j == entry_index + HOLD_BARS - 1:
                exit_index, exit_z, exit_reason = j, zj, "TIME_STOP"
                break
        if exit_index < 0:  # incomplete tail: cannot complete frozen horizon
            break
        s_exit = float(feat["spread"][exit_index])
        gross_r = d * (s_exit - s_entry) / std
        # multi-leg absolute cost: 4 executions (entry+exit x 2 legs), 5 bps/side
        # leg A notional 1, leg B notional |beta| -> cost in spread log units
        # per unit A: 2*c + 2*c*|beta|; in R: / std  (c = bps/10000)
        cost_r = (2.0 * COST_SIDE_BPS / 10_000.0) * (1.0 + abs(beta)) / std
        trades.append(
            H3Trade(
                direction=direction,
                decision_index=t,
                decision_ts=int(timestamps[t]),
                entry_index=entry_index,
                entry_ts=int(timestamps[entry_index]),
                exit_index=exit_index,
                exit_ts=int(timestamps[exit_index]),
                beta=beta,
                spread_std=std,
                entry_z=float(z),
                exit_z=exit_z,
                exit_reason=exit_reason,
                gross_r=float(gross_r),
                cost_r=float(cost_r),
                net_r=float(gross_r - cost_r),
                gross_exposure=1.0 + abs(beta),
                net_dollar_exposure=abs(beta) - 1.0
                if direction == "SPREAD_SHORT"
                else 1.0 - abs(beta),
                regime_at_entry=(regime_labels or {}).get(t, ""),
            )
        )
        busy_until = exit_index + COOLDOWN_BARS
        t = exit_index + COOLDOWN_BARS + 1
    return trades, blocked


# ---------------------------------------------------------------------------
# Metrics (multi-leg ABSOLUTE cost scenarios; DEF-RESEARCH-COST-001-proof)
# ---------------------------------------------------------------------------


def cost_scenario_net_r(trades: list[H3Trade], cost_side_bps: float) -> list[float]:
    """Net R per trade at an absolute per-side cost scenario.

    cost scales LINEARLY in the per-side bps and is anchored at 0 bps = gross:
    net(bps) = gross - cost_r * (bps / COST_SIDE_BPS). Monotone non-increasing
    by construction for a fixed trade set (DEF-RESEARCH-COST-001 proof).
    """
    scale = cost_side_bps / COST_SIDE_BPS
    return [t.gross_r - t.cost_r * scale for t in trades]


def summarize(trades: list[H3Trade], cost_side_bps: float = COST_SIDE_BPS) -> dict[str, Any]:
    """B1 metrics at an absolute per-side cost scenario (frozen formulas)."""
    gross = [t.gross_r for t in trades]
    net = cost_scenario_net_r(trades, cost_side_bps)
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


def neutrality(trades: list[H3Trade]) -> dict[str, float]:
    """Track G: measured exposure at entry (per unit notional_A).

    net_beta_exposure uses the frozen hedge model: w_A*beta_BTC + w_B*beta_ETH
    with beta_ETH = 1/beta_t (the regression relation) -> structurally ~0;
    the realized imbalance metric is the dollar exposure |beta_t - 1|, which
    is the conservative gate quantity against the preregistered 0.10 average.
    """
    if not trades:
        return {
            "MEAN_GROSS_EXPOSURE": 0.0,
            "MEAN_ABS_NET_EXPOSURE": 0.0,
            "MEAN_ABS_BETA_EXPOSURE": 0.0,
            "P95_ABS_BETA_EXPOSURE": 0.0,
        }
    gross = [t.gross_exposure for t in trades]
    net_abs = [abs(t.net_dollar_exposure) for t in trades]
    beta_abs = [
        abs(t.beta**2 - 1.0) for t in trades
    ]  # w_A*1 + w_B*beta_ETH = beta^2-1 (conservative second-order term)
    return {
        "MEAN_GROSS_EXPOSURE": float(np.mean(gross)),
        "MEAN_ABS_NET_EXPOSURE": float(np.mean(net_abs)),
        "MEAN_ABS_BETA_EXPOSURE": float(np.mean(beta_abs)),
        "P95_ABS_BETA_EXPOSURE": float(np.percentile(beta_abs, 95)),
        "MEAN_ABS_DOLLAR_IMBALANCE": float(np.mean(net_abs)),
    }


def classify(metrics: dict[str, Any], n_direction_cells: list[int]) -> ResultClass:
    """Frozen B4 classification (pure function of metrics)."""
    n = int(metrics.get("N", 0))
    if n < MIN_TOTAL_TRADES or any(c < MIN_DIRECTION_CELL for c in n_direction_cells):
        return "INSUFFICIENT_SAMPLE"
    halves = metrics["halves"]
    thirds = metrics["thirds"]
    assert isinstance(halves, list) and isinstance(thirds, list)
    pass_all = (
        float(metrics["net_expectancy_R"]) > 0.0
        and float(metrics["PF_net"]) > PF_NET_MIN
        and float(metrics["P_Sharpe_gt_0"]) >= P_SHARPE_MIN
        and float(metrics["permutation_p"]) <= PERM_P_MAX
        and all(s == halves[0] for s in halves)
        and all(s == thirds[0] for s in thirds)
        and float(metrics["walk_forward_last_third_net_R"]) > 0.0
    )
    return "DISCOVERY_PASS" if pass_all else "DISCOVERY_FAIL"
