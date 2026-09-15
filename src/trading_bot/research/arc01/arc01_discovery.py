"""ARC-01 primary discovery -- frozen implementation of the preregistered experiment.

Executes the frozen ARC-01 decision rules (``docs/arc01-prereg-01/ARC01_SPEC_V1.json``,
PREREG_COMMIT ``fa15fb4``) against the certified data authority and evaluates the frozen
G1-G11 critical gates plus the four preregistered falsification controls.

Design constraints satisfied here:

* **No retuning.** Every economic constant comes from the frozen prereg reference module
  (:mod:`trading_bot.research.arc01.prereg_reference`), whose functions are reused
  verbatim for the funding transform, the OI transform, direction rules, NO_SIGNAL
  precedence, funding cashflow and the deterministic null direction.
* **No hidden defaults.** Cost scenarios, holding period, seeds, resample/draw counts and
  the Sharpe/CI/permutation estimator conventions are module constants, cross-checked
  against the frozen gates file by ``scripts/run_arc01_primary_discovery.py``.
* **PIT.** A decision at ``T`` only ever reads observations with ``time <= T``; entries
  occur strictly after ``T``; the exit anchor is ``entry + 72h``.
* **Pure.** No I/O, no artifact writing, no global state: the engine takes already-loaded
  authorities and returns immutable records, so it can be exercised on synthetic fixtures
  before any real economic execution.

Estimator conventions (``ARC01_STATISTICAL_GATES.json`` G5/G6/G7 leave three standard
conventions unstated; they are pinned by the repository's sole pre-prereg statistical
authority ``trading_bot.backtesting.stat_validation``):

* G5 Sharpe: ``stat_validation._sharpe`` (ddof = 1) with ``periods_per_year =
  N / (window_days/365)``; ``window_days = (end_ms - start_ms + 1h)/24h = 1745.0``
  exactly (the closed interval of 1h bar opens spans exactly 1745 days).
* G6/G7: percentile bootstrap and one-sided sign-flip permutation using the same
  ``random.Random(seed)`` draw sequence and index formula as
  ``stat_validation``; statistic = **mean net trade return** (as frozen), not Sharpe.
* G8: equal-count chronological buckets of the **trade timeline** (the operative
  clarification recorded by the independent verifier, PASS_NOTE_RESOLVED).
"""

from __future__ import annotations

import math
import random
from collections import Counter
from dataclasses import dataclass
from typing import Any, Iterable, Sequence

from trading_bot.backtesting import stat_validation as sv
from trading_bot.research.arc01 import prereg_reference as ref
from trading_bot.research.arc01.arc01_authority import FundingSeries, Series

# --------------------------------------------------------------- frozen constants
ASSETS: tuple[str, ...] = ("BTCUSDT", "ETHUSDT", "SOLUSDT")

COMMON_WINDOW_START_MS: int = ref.COMMON_WINDOW_START_MS
COMMON_WINDOW_END_MS: int = ref.COMMON_WINDOW_END_MS
FUNDING_LOOKBACK_MS: int = ref.FUNDING_LOOKBACK_MS
FUNDING_MIN_OBSERVATIONS: int = ref.FUNDING_MIN_OBSERVATIONS
MAD_SCALE: float = ref.MAD_SCALE
FUNDING_Z_POSITIVE_THRESHOLD: float = ref.FUNDING_Z_POSITIVE_THRESHOLD
FUNDING_Z_NEGATIVE_THRESHOLD: float = ref.FUNDING_Z_NEGATIVE_THRESHOLD
OI_LOOKBACK_MS: int = ref.OI_LOOKBACK_MS
OI_MAX_STALENESS_MS: int = ref.OI_MAX_STALENESS_MS
HOLDING_MS: int = ref.HOLDING_MS
HOUR_MS: int = 3_600_000
NULL_SEED: int = ref.NULL_SEED

COST_SCENARIOS_BPS: tuple[int, ...] = (0, 10, 20, 40)
PRIMARY_COST_BPS: int = 10
BOOTSTRAP_SEED: int = 20260915
BOOTSTRAP_RESAMPLES: int = 10_000
PERMUTATION_DRAWS: int = 10_000
PERMUTATION_ALPHA: float = 0.05
G1_MIN_TOTAL_TRADES: int = 120
G1_MIN_TRADES_PER_ASSET: int = 40
G4_MIN_PROFIT_FACTOR: float = 1.15
G5_MIN_SHARPE: float = 0.50

#: Closed interval of 1h bar opens [start, end] spans exactly 1745 days.
WINDOW_DAYS: float = (COMMON_WINDOW_END_MS - COMMON_WINDOW_START_MS + HOUR_MS) / 86_400_000.0

FUNNEL_KEYS: tuple[str, ...] = (
    "funding_settlements_evaluated",
    "outside_window",
    "insufficient_funding_history",
    "scale_nonpositive",
    "funding_not_extreme",
    "oi_missing_or_stale",
    "oi_reference_missing_or_stale",
    "oi_reference_invalid",
    "oi_not_expanding",
    "position_already_open",
    "forward_price_unavailable",
    "long_signals",
    "short_signals",
    "executed_trades",
)

_REASON_TO_FUNNEL = {
    "OUTSIDE_COMMON_WINDOW": "outside_window",
    "INSUFFICIENT_FUNDING_HISTORY": "insufficient_funding_history",
    "SCALE_NONPOSITIVE": "scale_nonpositive",
    "FUNDING_NOT_EXTREME": "funding_not_extreme",
    "OI_MISSING_OR_STALE": "oi_missing_or_stale",
    "OI_REFERENCE_MISSING_OR_STALE": "oi_reference_missing_or_stale",
    "OI_REFERENCE_INVALID": "oi_reference_invalid",
    "OI_NOT_EXPANDING": "oi_not_expanding",
    "POSITION_ALREADY_OPEN": "position_already_open",
    "INSUFFICIENT_FORWARD_PRICE_DATA": "forward_price_unavailable",
}


def _opposite(direction: str | None) -> str | None:
    if direction == ref.LONG:
        return ref.SHORT
    if direction == ref.SHORT:
        return ref.LONG
    return None


def _cost_return(bps: float) -> float:
    return float(bps) / 10_000.0


# ------------------------------------------------------------------- decision unit
@dataclass(frozen=True)
class Decision:
    """One frozen decision instant, with every input used to reach it."""

    asset: str
    decision_time_ms: int
    result: str
    reason: str | None
    emitted: bool
    funding_rate: float | None
    z_funding: float | None
    funding_window_n: int
    funding_window_start_ms: int
    funding_window_end_ms: int
    funding_status: str
    funding_median: float | None
    funding_mad: float | None
    funding_scale: float | None
    funding_mad_fallback_used: bool
    oi_status: str
    oi_now_time_ms: int | None
    oi_now: float | None
    oi_ref_time_ms: int | None
    oi_ref: float | None
    oi_change_24h: float | None
    entry_time_ms: int | None
    entry_price: float | None
    exit_time_ms: int | None
    exit_price: float | None
    forward_price_status: str


def decide_at(
    *,
    asset: str,
    decision_time_ms: int,
    funding: FundingSeries,
    oi: Series | None,
    price: Series,
    position_open: bool,
    window_start_ms: int = COMMON_WINDOW_START_MS,
    window_end_ms: int = COMMON_WINDOW_END_MS,
    oi_leg: bool = True,
    direction_mode: str = "PRIMARY",
) -> Decision:
    """Frozen decision at ``T`` with the exact frozen NO_SIGNAL precedence.

    ``funding`` is pre-sliced with an equivalent closed-window filter before being handed
    to the verified :func:`prereg_reference.funding_extreme` (the estimator is unchanged;
    only the O(N) rescan per decision is removed, provably idempotent because
    ``funding_window`` re-applies the same closed bounds).
    """
    T = int(decision_time_ms)
    reasons: list[str] = []

    if not (window_start_ms <= T <= window_end_ms):
        reasons.append("OUTSIDE_COMMON_WINDOW")

    window_start = T - FUNDING_LOOKBACK_MS
    pre_sliced = funding.window_slice(window_start, T)
    fe = ref.funding_extreme(pre_sliced, T)
    funding_status = str(fe["status"])
    if funding_status == "INSUFFICIENT_FUNDING_HISTORY":
        reasons.append("INSUFFICIENT_FUNDING_HISTORY")
    if funding_status == "SCALE_NONPOSITIVE":
        reasons.append("SCALE_NONPOSITIVE")

    z = fe["z"]
    base_direction = ref.decide_direction(z)  # type: ignore[arg-type]
    if base_direction is None:
        reasons.append("FUNDING_NOT_EXTREME")
    if direction_mode == "PRIMARY":
        direction = base_direction
    elif direction_mode == "REVERSED":
        direction = _opposite(base_direction)
    elif direction_mode == "NULL":
        direction = ref.null_direction(asset, T) if base_direction is not None else None
    else:  # pragma: no cover - guarded by callers
        raise ValueError(f"unknown direction_mode: {direction_mode}")

    oi_status = "OI_LEG_DISABLED"
    oi_now: tuple[int, float] | None = None
    oi_ref_obs: tuple[int, float] | None = None
    change: float | None = None
    if oi_leg:
        oi_now = oi.last_at_or_before(T) if oi is not None else None
        oi_ref_obs = oi.last_at_or_before(T - OI_LOOKBACK_MS) if oi is not None else None
        oi_res = ref.oi_change_24h(oi_now, oi_ref_obs, T)
        oi_status = str(oi_res["status"])
        if oi_status != "OK":
            reasons.append(oi_status)
        else:
            change = float(oi_res["oi_change_24h"])  # type: ignore[arg-type]
            if not change > 0.0:
                reasons.append("OI_NOT_EXPANDING")

    if position_open:
        reasons.append("POSITION_ALREADY_OPEN")

    # ---- execution anchors (clock-only: never reads a price level to decide) ----
    entry_idx = price.first_index_strictly_after(T)
    entry_time = price.t[entry_idx] if entry_idx is not None else None
    exit_time = entry_time + HOLDING_MS if entry_time is not None else None
    forward_status = "OK"
    if entry_time is None:
        forward_status = "ENTRY_BAR_ABSENT"
    elif entry_time > window_end_ms:
        forward_status = "ENTRY_BAR_OUTSIDE_WINDOW"
    elif exit_time is None or exit_time > window_end_ms:
        forward_status = "EXIT_BAR_OUTSIDE_WINDOW"
    elif price.index_of_exact(exit_time) is None:
        forward_status = "EXIT_BAR_ABSENT"
    if forward_status != "OK":
        reasons.append("INSUFFICIENT_FORWARD_PRICE_DATA")

    first_reason = next((r for r in ref.NO_SIGNAL_PRECEDENCE if r in reasons), None)
    emitted = first_reason is None

    entry_price: float | None = None
    exit_price: float | None = None
    if emitted:
        assert entry_idx is not None and exit_time is not None
        exit_idx = price.index_of_exact(exit_time)
        assert exit_idx is not None
        entry_price = float(price.v[entry_idx])
        exit_price = float(price.v[exit_idx])

    current_rate = fe.get("current_rate")
    return Decision(
        asset=asset,
        decision_time_ms=T,
        result=direction if emitted else ref.NO_SIGNAL,  # type: ignore[arg-type]
        reason=first_reason,
        emitted=emitted,
        funding_rate=float(current_rate) if current_rate is not None else None,
        z_funding=float(z) if z is not None else None,
        funding_window_n=int(fe["observations"]),  # type: ignore[arg-type]
        funding_window_start_ms=int(fe["window_start_ms"]),  # type: ignore[arg-type]
        funding_window_end_ms=int(fe["window_end_ms"]),  # type: ignore[arg-type]
        funding_status=funding_status,
        funding_median=float(fe["median"]) if fe.get("median") is not None else None,
        funding_mad=float(fe["mad"]) if fe.get("mad") is not None else None,
        funding_scale=float(fe["scale"]) if fe.get("scale") is not None else None,
        funding_mad_fallback_used=bool(fe.get("mad_fallback_used", False)),
        oi_status=oi_status,
        oi_now_time_ms=int(oi_now[0]) if oi_now is not None else None,
        oi_now=float(oi_now[1]) if oi_now is not None else None,
        oi_ref_time_ms=int(oi_ref_obs[0]) if oi_ref_obs is not None else None,
        oi_ref=float(oi_ref_obs[1]) if oi_ref_obs is not None else None,
        oi_change_24h=change,
        entry_time_ms=entry_time,
        entry_price=entry_price,
        exit_time_ms=exit_time,
        exit_price=exit_price,
        forward_price_status=forward_status,
    )


# ------------------------------------------------------------------------ trades
@dataclass(frozen=True)
class Trade:
    """One executed ARC-01 round trip with its full frozen decomposition."""

    trade_id: str
    variant: str
    asset: str
    direction: str
    direction_sign: int
    decision_time_ms: int
    funding_time_ms: int
    funding_rate: float
    funding_z: float
    funding_window_n: int
    funding_median: float
    funding_mad: float
    funding_scale: float
    funding_mad_fallback_used: bool
    funding_scale_estimator: str
    oi_now_time_ms: int | None
    oi_now: float | None
    oi_reference_time_ms: int | None
    oi_reference: float | None
    oi_change_24h: float | None
    oi_staleness_now_ms: int | None
    oi_staleness_reference_ms: int | None
    entry_time_ms: int
    entry_price: float
    exit_time_ms: int
    exit_price: float
    holding_ms: int
    funding_settlements_applied: int
    funding_cashflow: float
    gross_return: float
    net_return_0bps: float
    net_return_10bps: float
    net_return_20bps: float
    net_return_40bps: float
    net_return_ex_funding_10bps: float

    def net(self, bps: int) -> float:
        return {0: self.net_return_0bps, 10: self.net_return_10bps, 20: self.net_return_20bps, 40: self.net_return_40bps}[bps]


def make_trade(*, decision: Decision, funding: FundingSeries, variant: str, seq: int) -> Trade:
    """Frozen return accounting: NET = GROSS + FUNDING_CASHFLOW - COST."""
    assert decision.emitted, "make_trade requires an emitted decision"
    assert decision.entry_price is not None and decision.exit_price is not None
    assert decision.entry_time_ms is not None and decision.exit_time_ms is not None
    # The OI leg is absent only for OI_CONTROL (a preregistered control variant); the
    # primary discovery always carries the full crowding-confirmation evidence.
    oi_present = decision.oi_now_time_ms is not None and decision.oi_ref_time_ms is not None
    if variant != "OI_CONTROL":
        assert oi_present, "primary variant must carry the OI confirmation evidence"
    assert decision.funding_rate is not None and decision.z_funding is not None

    dsign = 1 if decision.result == ref.LONG else -1
    entry_time = int(decision.entry_time_ms)
    exit_time = int(decision.exit_time_ms)
    entry_price = float(decision.entry_price)
    exit_price = float(decision.exit_price)

    gross = dsign * (exit_price / entry_price - 1.0)
    settlement_rates = funding.settlements_between(entry_time, exit_time)
    cashflow = ref.funding_cashflow_return(dsign, settlement_rates)

    nets = {bps: gross + cashflow - _cost_return(bps) for bps in COST_SCENARIOS_BPS}
    return Trade(
        trade_id=f"{variant}:{decision.asset}:{seq:05d}",
        variant=variant,
        asset=decision.asset,
        direction=decision.result,
        direction_sign=dsign,
        decision_time_ms=int(decision.decision_time_ms),
        funding_time_ms=int(decision.decision_time_ms),
        funding_rate=float(decision.funding_rate),
        funding_z=float(decision.z_funding),
        funding_window_n=int(decision.funding_window_n),
        funding_median=float(decision.funding_median if decision.funding_median is not None else 0.0),
        funding_mad=float(decision.funding_mad if decision.funding_mad is not None else 0.0),
        funding_scale=float(decision.funding_scale if decision.funding_scale is not None else 0.0),
        funding_mad_fallback_used=bool(decision.funding_mad_fallback_used),
        funding_scale_estimator="SAMPLE_STDEV(ddof=1)[MAD==0]" if decision.funding_mad_fallback_used else "1.4826*MAD",
        oi_now_time_ms=int(decision.oi_now_time_ms) if decision.oi_now_time_ms is not None else None,
        oi_now=float(decision.oi_now) if decision.oi_now is not None else None,
        oi_reference_time_ms=int(decision.oi_ref_time_ms) if decision.oi_ref_time_ms is not None else None,
        oi_reference=float(decision.oi_ref) if decision.oi_ref is not None else None,
        oi_change_24h=float(decision.oi_change_24h) if decision.oi_change_24h is not None else None,
        oi_staleness_now_ms=(int(decision.decision_time_ms) - int(decision.oi_now_time_ms)) if decision.oi_now_time_ms is not None else None,
        oi_staleness_reference_ms=((int(decision.decision_time_ms) - OI_LOOKBACK_MS) - int(decision.oi_ref_time_ms)) if decision.oi_ref_time_ms is not None else None,
        entry_time_ms=entry_time,
        entry_price=entry_price,
        exit_time_ms=exit_time,
        exit_price=exit_price,
        holding_ms=exit_time - entry_time,
        funding_settlements_applied=len(settlement_rates),
        funding_cashflow=cashflow,
        gross_return=gross,
        net_return_0bps=nets[0],
        net_return_10bps=nets[10],
        net_return_20bps=nets[20],
        net_return_40bps=nets[40],
        net_return_ex_funding_10bps=gross - _cost_return(PRIMARY_COST_BPS),
    )


def decision_instants(funding: FundingSeries, *, start_ms: int, end_ms: int) -> list[int]:
    """The certified funding settlement instants inside the common window.

    Provider-native: the instants are the authority rows themselves, never an assumed
    8h grid, so SOL's historical 2h/4h settlements are first-class decisions.
    """
    out = [int(ts) for ts in funding.t if start_ms <= int(ts) <= end_ms]
    out.sort()
    return out


def run_variant(
    *,
    variant: str,
    funding: FundingSeries,
    oi: Series | None,
    price: Series,
    start_ms: int = COMMON_WINDOW_START_MS,
    end_ms: int = COMMON_WINDOW_END_MS,
    shift_ms: int = 0,
    oi_leg: bool = True,
    direction_mode: str = "PRIMARY",
) -> tuple[list[Trade], dict[str, Any]]:
    """Run one frozen variant of the experiment for one asset.

    ``shift_ms`` implements the frozen TIMING_CONTROL: the *same* decision set as the
    primary is re-evaluated with every instant moved by the offset. Shifted instants that
    fall outside the common window are evaluated and fail closed as
    NO_SIGNAL / OUTSIDE_COMMON_WINDOW (they are never silently dropped).
    """
    instants = [t + int(shift_ms) for t in decision_instants(funding, start_ms=start_ms, end_ms=end_ms)]
    instants.sort()
    funnel: Counter[str] = Counter({k: 0 for k in FUNNEL_KEYS})
    trades: list[Trade] = []
    open_until: int | None = None
    seq = 0
    for T in instants:
        funnel["funding_settlements_evaluated"] += 1
        position_open = open_until is not None and T < open_until
        d = decide_at(
            asset=funding.asset,
            decision_time_ms=T,
            funding=funding,
            oi=oi,
            price=price,
            position_open=position_open,
            window_start_ms=start_ms,
            window_end_ms=end_ms,
            oi_leg=oi_leg,
            direction_mode=direction_mode,
        )
        if d.emitted:
            seq += 1
            trades.append(make_trade(decision=d, funding=funding, variant=variant, seq=seq))
            funnel["executed_trades"] += 1
            funnel["long_signals" if d.result == ref.LONG else "short_signals"] += 1
            open_until = int(d.exit_time_ms)  # type: ignore[arg-type]
        else:
            funnel[_REASON_TO_FUNNEL[str(d.reason)]] += 1
    funnel["asset"] = funding.asset  # type: ignore[assignment]
    return trades, dict(funnel)


# ----------------------------------------------------------------------- statistics
def _mean(xs: Sequence[float]) -> float:
    return float(sum(xs) / len(xs)) if xs else 0.0


def _profit_factor(xs: Sequence[float]) -> float:
    gross_profit = sum(x for x in xs if x > 0.0)
    gross_loss = sum(x for x in xs if x < 0.0)
    if gross_loss == 0.0:
        return math.inf if gross_profit > 0.0 else 0.0
    return gross_profit / abs(gross_loss)


def trades_per_year(n: int, window_days: float = WINDOW_DAYS) -> float:
    """Frozen G5 annualization basis: N / (window_days/365)."""
    return float(n) / (window_days / 365.0)


def annualized_sharpe(nets: Sequence[float], window_days: float = WINDOW_DAYS) -> float:
    """G5: per-trade Sharpe * sqrt(trades_per_year) via the project authority.

    Delegates the arithmetic to ``stat_validation._sharpe`` (ddof = 1, annualization by
    ``mean/std * sqrt(periods_per_year)``). A degenerate (zero-variance) series is failed
    closed to 0.0 *before* delegation, exactly as ``stat_validation.bootstrap_sharpe_ci``
    and ``stat_validation.permutation_significance`` already do with their own
    ``len(set(returns)) == 1`` guard: the module's documented contract is "zero variance ->
    no fabricated numbers", and ``_sharpe`` alone relies on an exact ``std == 0.0`` test
    that float cancellation can miss (a constant series yields |Sharpe| ~ 1e15 instead of
    0.0). This guard can only ever make G5 more conservative -- it never manufactures a
    pass -- and it makes the gate deterministic on degenerate input.
    """
    n = len(nets)
    if n < 2:
        return 0.0
    if min(nets) == max(nets):
        return 0.0
    return float(sv._sharpe(tuple(float(x) for x in nets), periods_per_year=trades_per_year(n, window_days)))


def replicate_annualized_sharpe(nets: Sequence[float], window_days: float = WINDOW_DAYS) -> float:
    """Independent replication of :func:`annualized_sharpe` (asserted equal by tests)."""
    n = len(nets)
    if n < 2:
        return 0.0
    if min(nets) == max(nets):
        return 0.0
    mean = sum(nets) / n
    var = sum((x - mean) ** 2 for x in nets) / (n - 1)
    std = math.sqrt(var)
    if std == 0.0:
        return 0.0
    return mean / std * math.sqrt(trades_per_year(n, window_days))


def bootstrap_mean_ci(
    nets: Sequence[float],
    *,
    resamples: int = BOOTSTRAP_RESAMPLES,
    confidence: float = 0.95,
    seed: int = BOOTSTRAP_SEED,
) -> dict[str, Any]:
    """G6: percentile bootstrap CI of the MEAN net trade return.

    Same resampling unit (i.i.d. trade, with replacement), RNG draw sequence
    (``random.Random(seed)`` + ``randrange``) and percentile index formula as
    ``stat_validation.bootstrap_sharpe_ci``; only the statistic differs (mean, as frozen).
    """
    n = len(nets)
    if n < 2:
        return {"lower": None, "upper": None, "prob_positive": None, "degenerate": True, "n": n}
    if len(set(nets)) == 1:
        v = float(nets[0])
        return {
            "lower": v,
            "upper": v,
            "prob_positive": 1.0 if v > 0.0 else 0.0,
            "degenerate": True,
            "n": n,
            "reason": "ZERO_VARIANCE_FAIL_CLOSED",
        }
    rng = random.Random(seed)
    stats: list[float] = []
    for _ in range(resamples):
        sample = [nets[rng.randrange(n)] for _ in range(n)]
        stats.append(sum(sample) / n)
    stats.sort()
    alpha = (1.0 - confidence) / 2.0
    lower_idx = max(0, math.floor(alpha * len(stats)))
    upper_idx = min(len(stats) - 1, math.ceil((1.0 - alpha) * len(stats)) - 1)
    return {
        "lower": stats[lower_idx],
        "upper": stats[upper_idx],
        "prob_positive": sum(1 for s in stats if s > 0.0) / len(stats),
        "degenerate": False,
        "n": n,
        "resamples": resamples,
        "seed": seed,
    }


def permutation_p_value(
    nets: Sequence[float],
    *,
    draws: int = PERMUTATION_DRAWS,
    seed: int = BOOTSTRAP_SEED,
) -> dict[str, Any]:
    """G7: one-sided sign-flip permutation p-value of the MEAN net trade return.

    Same draw sequence (one ``random()`` per element, ``< 0.5`` flips the sign) and
    one-sided upper-tail convention (``exceed`` counts null statistics >= observed,
    ``p = exceed/draws``) as ``stat_validation.permutation_significance``.
    """
    n = len(nets)
    if n < 2:
        return {"p_value": 1.0, "observed": None, "degenerate": True, "n": n}
    observed = _mean(nets)
    if len(set(nets)) == 1:
        return {"p_value": 1.0, "observed": observed, "degenerate": True, "n": n, "reason": "ZERO_VARIANCE_FAIL_CLOSED"}
    rng = random.Random(seed)
    exceed = 0
    for _ in range(draws):
        s = 0.0
        for x in nets:
            s += x if rng.random() < 0.5 else -x
        if (s / n) >= observed:
            exceed += 1
    return {"p_value": exceed / draws, "observed": observed, "degenerate": False, "n": n, "draws": draws, "seed": seed}


def equal_count_buckets(trades: Sequence[Trade], k: int) -> list[list[Trade]]:
    """Equal-count chronological buckets of the trade timeline (G8 operative reading)."""
    ordered = sorted(trades, key=lambda t: (t.entry_time_ms, t.asset, t.trade_id))
    n = len(ordered)
    if n == 0:
        return [[] for _ in range(k)]
    bounds = [(n * i) // k for i in range(k + 1)]
    return [ordered[bounds[i] : bounds[i + 1]] for i in range(k)]


def equal_duration_buckets(trades: Sequence[Trade], k: int, start_ms: int, end_ms: int) -> list[list[Trade]]:
    """Equal-duration buckets of the common window (reported as a non-gating diagnostic)."""
    span = end_ms - start_ms
    out: list[list[Trade]] = [[] for _ in range(k)]
    for t in sorted(trades, key=lambda t: (t.entry_time_ms, t.asset, t.trade_id)):
        idx = min(k - 1, max(0, int((t.entry_time_ms - start_ms) * k / (span + 1))))
        out[idx].append(t)
    return out


def nets_at(trades: Sequence[Trade], bps: int) -> list[float]:
    return [t.net(bps) for t in trades]


def nets_ex_funding_at(trades: Sequence[Trade], bps: int = PRIMARY_COST_BPS) -> list[float]:
    if bps == PRIMARY_COST_BPS:
        return [t.net_return_ex_funding_10bps for t in trades]
    return [t.gross_return - _cost_return(bps) for t in trades]


def month_key(ts_ms: int) -> str:
    """Calendar-month attribution key (UTC), by trade entry instant."""
    import datetime as _dt

    return _dt.datetime.fromtimestamp(ts_ms / 1000, tz=_dt.timezone.utc).strftime("%Y-%m")


def evaluate_gates(
    trades: Sequence[Trade],
    *,
    window_start_ms: int = COMMON_WINDOW_START_MS,
    window_end_ms: int = COMMON_WINDOW_END_MS,
    window_days: float = WINDOW_DAYS,
) -> dict[str, Any]:
    """Evaluate ALL frozen critical gates G1-G11 exactly as preregistered."""
    n = len(trades)
    net10 = nets_at(trades, PRIMARY_COST_BPS)
    net20 = nets_at(trades, 20)
    net40 = nets_at(trades, 40)
    net0 = nets_at(trades, 0)
    ex10 = nets_ex_funding_at(trades, PRIMARY_COST_BPS)

    per_asset_counts: dict[str, int] = {a: 0 for a in ASSETS}
    per_asset_mean: dict[str, float] = {}
    for a in ASSETS:
        sub = nets_at([t for t in trades if t.asset == a], PRIMARY_COST_BPS)
        per_asset_counts[a] = len(sub)
        per_asset_mean[a] = _mean(sub)

    g1 = n >= G1_MIN_TOTAL_TRADES and all(per_asset_counts[a] >= G1_MIN_TRADES_PER_ASSET for a in ASSETS)

    mean10 = _mean(net10)
    mean_ex10 = _mean(ex10)
    g2 = mean10 > 0.0
    g3 = mean_ex10 > 0.0

    pf = _profit_factor(net10)
    g4 = pf >= G4_MIN_PROFIT_FACTOR

    sharpe = annualized_sharpe(net10, window_days)
    sharpe_replicated = replicate_annualized_sharpe(net10, window_days)
    g5 = sharpe >= G5_MIN_SHARPE

    ci = bootstrap_mean_ci(net10)
    g6 = ci["lower"] is not None and float(ci["lower"]) > 0.0

    perm = permutation_p_value(net10)
    g7 = float(perm["p_value"]) <= PERMUTATION_ALPHA

    halves = equal_count_buckets(trades, 2)
    quartiles = equal_count_buckets(trades, 4)
    half_means = [_mean(nets_at(b, PRIMARY_COST_BPS)) for b in halves]
    quarter_means = [_mean(nets_at(b, PRIMARY_COST_BPS)) for b in quartiles]
    quarters_positive = sum(1 for m in quarter_means if m > 0.0)
    g8 = all(m > 0.0 for m in half_means) and quarters_positive >= 3

    positive_assets = sum(1 for a in ASSETS if per_asset_mean[a] > 0.0)
    g9 = positive_assets >= 2

    total = sum(net10)
    if total > 0.0:
        asset_share = {a: sum(nets_at([t for t in trades if t.asset == a], PRIMARY_COST_BPS)) / total for a in ASSETS}
        month_totals: dict[str, float] = {}
        for t in trades:
            month_totals[month_key(t.entry_time_ms)] = month_totals.get(month_key(t.entry_time_ms), 0.0) + t.net(PRIMARY_COST_BPS)
        month_share = {k: v / total for k, v in month_totals.items()}
        trade_share_max = max((t.net(PRIMARY_COST_BPS) / total for t in trades), default=0.0)
        max_asset_share = max(asset_share.values(), default=0.0)
        max_month_share = max(month_share.values(), default=0.0)
        g10 = max_asset_share <= 0.60 and max_month_share <= 0.40 and trade_share_max <= 0.25
    else:
        asset_share, month_share, trade_share_max = {}, {}, None
        max_asset_share = max_month_share = None
        g10 = False

    mean20 = _mean(net20)
    mean40 = _mean(net40)
    g11 = mean20 > 0.0 and mean40 >= 0.0

    gates = {
        "G1_SAMPLE": {"pass": bool(g1), "trades_total": n, "trades_per_asset": per_asset_counts, "requirement": f">= {G1_MIN_TOTAL_TRADES} total AND >= {G1_MIN_TRADES_PER_ASSET} per asset"},
        "G2_NET_EXPECTANCY": {"pass": bool(g2), "value": mean10, "requirement": "> 0"},
        "G3_NET_EXPECTANCY_EX_FUNDING": {"pass": bool(g3), "value": mean_ex10, "requirement": "> 0"},
        "G4_PROFIT_FACTOR": {"pass": bool(g4), "value": pf, "requirement": f">= {G4_MIN_PROFIT_FACTOR}"},
        "G5_SHARPE": {
            "pass": bool(g5),
            "value": sharpe,
            "value_replicated_independently": sharpe_replicated,
            "trades_per_year": trades_per_year(n, window_days),
            "window_days": window_days,
            "requirement": f">= {G5_MIN_SHARPE}",
        },
        "G6_BOOTSTRAP_CI": {"pass": bool(g6), "ci_lower": ci["lower"], "ci_upper": ci["upper"], "prob_mean_positive": ci["prob_positive"], "resamples": ci.get("resamples"), "seed": ci.get("seed"), "requirement": "95% CI lower bound of mean net return > 0"},
        "G7_PERMUTATION": {"pass": bool(g7), "p_value": perm["p_value"], "draws": perm.get("draws"), "seed": perm.get("seed"), "requirement": f"p <= {PERMUTATION_ALPHA}"},
        "G8_TEMPORAL_STABILITY": {
            "pass": bool(g8),
            "half_expectancies": half_means,
            "quartile_expectancies": quarter_means,
            "quartiles_positive": quarters_positive,
            "bucket_sizes_half": [len(b) for b in halves],
            "bucket_sizes_quartile": [len(b) for b in quartiles],
            "requirement": "both halves > 0 AND >= 3/4 quartiles > 0",
        },
        "G9_ASSET_STABILITY": {"pass": bool(g9), "positive_assets": positive_assets, "per_asset_expectancy": per_asset_mean, "requirement": ">= 2 of 3 assets > 0"},
        "G10_CONCENTRATION": {
            "pass": bool(g10),
            "total_net_pnl": total,
            "max_asset_share": max_asset_share,
            "max_month_share": max_month_share,
            "max_single_trade_share": trade_share_max,
            "asset_shares": asset_share,
            "month_shares": month_share,
            "requirement": "max asset <= 60% AND max month <= 40% AND max single trade <= 25%",
        },
        "G11_COST_SENSITIVITY": {"pass": bool(g11), "mean_20bps": mean20, "mean_40bps": mean40, "mean_0bps": _mean(net0), "requirement": "> 0 at 20bps AND >= 0 at 40bps"},
    }
    critical = [k for k in gates if k.startswith(("G1", "G2", "G3", "G4", "G5", "G6", "G7", "G8", "G9", "G10", "G11"))]
    gates["ALL_CRITICAL_GATES_PASS"] = all(gates[k]["pass"] for k in critical)
    gates["failed_gates"] = [k for k in critical if not gates[k]["pass"]]
    return gates


# ------------------------------------------------------------------------ controls
CONTROL_SPECS: dict[str, dict[str, Any]] = {
    "DIRECTION_CONTROL": {"kind": "direction", "direction_mode": "REVERSED", "oi_leg": True, "shift_ms": 0},
    "TIMING_CONTROL_PLUS_8H": {"kind": "timing", "direction_mode": "PRIMARY", "oi_leg": True, "shift_ms": 8 * HOUR_MS, "group": "TIMING_CONTROL"},
    "TIMING_CONTROL_MINUS_8H": {"kind": "timing", "direction_mode": "PRIMARY", "oi_leg": True, "shift_ms": -8 * HOUR_MS, "group": "TIMING_CONTROL"},
    "OI_CONTROL": {"kind": "oi_absent", "direction_mode": "PRIMARY", "oi_leg": False, "shift_ms": 0},
    "NULL_CONTROL": {"kind": "null", "direction_mode": "NULL", "oi_leg": True, "shift_ms": 0},
}


def merge_funnels(funnels: Iterable[dict[str, Any]]) -> dict[str, Any]:
    total: Counter[str] = Counter()
    for f in funnels:
        for k in FUNNEL_KEYS:
            total[k] += int(f.get(k, 0))
    return {k: total[k] for k in FUNNEL_KEYS}


def summarize_trades(trades: Sequence[Trade], *, window_days: float = WINDOW_DAYS) -> dict[str, Any]:
    """Descriptive decomposition (gross / funding / cost / net) pooled and per asset."""
    def block(ts: Sequence[Trade]) -> dict[str, Any]:
        net10 = nets_at(ts, PRIMARY_COST_BPS)
        return {
            "n": len(ts),
            "gross_expectancy": _mean([t.gross_return for t in ts]),
            "funding_cashflow_expectancy": _mean([t.funding_cashflow for t in ts]),
            "net_expectancy_0bps": _mean(nets_at(ts, 0)),
            "net_expectancy_10bps": _mean(net10),
            "net_expectancy_20bps": _mean(nets_at(ts, 20)),
            "net_expectancy_40bps": _mean(nets_at(ts, 40)),
            "net_expectancy_ex_funding_10bps": _mean(nets_ex_funding_at(ts)),
            "profit_factor_10bps": _profit_factor(net10),
            "annualized_sharpe_10bps": annualized_sharpe(net10, window_days),
            "win_rate_10bps": (sum(1 for x in net10 if x > 0.0) / len(net10)) if net10 else None,
            "mean_holding_hours": (_mean([t.holding_ms for t in ts]) / HOUR_MS) if ts else None,
            "mean_funding_settlements_applied": _mean([t.funding_settlements_applied for t in ts]) if ts else None,
            "long_trades": sum(1 for t in ts if t.direction == ref.LONG),
            "short_trades": sum(1 for t in ts if t.direction == ref.SHORT),
            "total_net_pnl_10bps": sum(net10),
        }

    per_asset = {a: block([t for t in trades if t.asset == a]) for a in ASSETS}
    return {"pooled": block(trades), "per_asset": per_asset}


def cost_curve(trades: Sequence[Trade]) -> dict[str, Any]:
    return {
        "basis": "IDENTICAL trade set across all scenarios; signals are never regenerated",
        "scenarios": {f"{bps}bps": {"mean_net_return": _mean(nets_at(trades, bps)), "n": len(trades)} for bps in COST_SCENARIOS_BPS},
    }


def diagnostics(trades: Sequence[Trade], *, window_start_ms: int = COMMON_WINDOW_START_MS, window_end_ms: int = COMMON_WINDOW_END_MS) -> dict[str, Any]:
    """Reported-but-non-gating diagnostics (never promotable to gates)."""
    net10 = nets_at(trades, PRIMARY_COST_BPS)
    equity = 0.0
    peak = 0.0
    max_dd = 0.0
    for t in sorted(trades, key=lambda t: (t.exit_time_ms, t.trade_id)):
        equity += t.net(PRIMARY_COST_BPS)
        peak = max(peak, equity)
        max_dd = min(max_dd, equity - peak)
    q_alt = equal_duration_buckets(trades, 4, window_start_ms, window_end_ms)
    month_counts = Counter(month_key(t.entry_time_ms) for t in trades)
    return {
        "max_drawdown_diagnostic_only": max_dd,
        "max_drawdown_units": "sum of unit-notional trade returns (no compounding)",
        "drawdown_is_a_gate": False,
        "equal_duration_quartile_expectancies_diagnostic": [_mean(nets_at(b, PRIMARY_COST_BPS)) for b in q_alt],
        "equal_duration_quartile_sizes_diagnostic": [len(b) for b in q_alt],
        "equal_duration_quartile_role": "NON_GATING_DIAGNOSTIC (G8 uses the frozen trade-timeline reading)",
        "trades_per_calendar_month": dict(sorted(month_counts.items())),
        "equal_duration_quartile_note": "reported for transparency only; cannot change PASS/FAIL",
    }


def variance_diagnostics(trades: Sequence[Trade]) -> dict[str, Any]:
    """Frozen sensitivity of the two conventions the verifier flagged as non-blocking."""
    net10 = nets_at(trades, PRIMARY_COST_BPS)
    alt_window_days = (COMMON_WINDOW_END_MS - COMMON_WINDOW_START_MS) / 86_400_000.0
    exit_month = {}
    for t in trades:
        exit_month[month_key(t.exit_time_ms)] = exit_month.get(month_key(t.exit_time_ms), 0.0) + t.net(PRIMARY_COST_BPS)
    total = sum(net10)
    return {
        "sharpe_window_days_primary": WINDOW_DAYS,
        "sharpe_window_days_alternative": alt_window_days,
        "sharpe_alternative": annualized_sharpe(net10, alt_window_days),
        "month_attribution_primary": "TRADE_ENTRY_MONTH",
        "max_month_share_exit_attribution_alternative": (max(exit_month.values()) / total) if total > 0 else None,
    }


__all__ = [
    "ASSETS",
    "BOOTSTRAP_RESAMPLES",
    "BOOTSTRAP_SEED",
    "COMMON_WINDOW_END_MS",
    "COMMON_WINDOW_START_MS",
    "CONTROL_SPECS",
    "COST_SCENARIOS_BPS",
    "Decision",
    "FUNNEL_KEYS",
    "HOLDING_MS",
    "PERMUTATION_ALPHA",
    "PERMUTATION_DRAWS",
    "PRIMARY_COST_BPS",
    "Trade",
    "WINDOW_DAYS",
    "annualized_sharpe",
    "bootstrap_mean_ci",
    "cost_curve",
    "decide_at",
    "decision_instants",
    "diagnostics",
    "equal_count_buckets",
    "equal_duration_buckets",
    "evaluate_gates",
    "make_trade",
    "merge_funnels",
    "month_key",
    "nets_at",
    "nets_ex_funding_at",
    "permutation_p_value",
    "replicate_annualized_sharpe",
    "run_variant",
    "summarize_trades",
    "trades_per_year",
    "variance_diagnostics",
]
