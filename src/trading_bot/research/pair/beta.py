"""RFC-030 §22/§23/§24 — beta book, fail-closed gate and empirical diagnostic.

Nominal (dollar) neutrality is **not** beta neutrality. The book beta is computed
exactly as the frozen EXP-ARP-023 contract declares: a through-origin OLS slope of
the held-name daily returns on BTCUSDT daily returns over a 60-day window.

    beta_i    = sum(r_i * r_btc) / sum(r_btc^2)          (through the origin)
    beta_book = sum_i w_i * beta_i                        (w = signed leg weight)

The gate is fail-closed (§23): ``|beta_book| > tolerance`` means *no rebalance* and
a flat book for the period. The tolerance is never optimised.

The diagnostic (§24) measures the distribution of ``beta_book`` over the frozen
score/universe **without any economic execution**. It changes nothing about the
frozen contract; it is evidence only.
"""

from __future__ import annotations

import math
import statistics
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Protocol

__all__ = [
    "BetaBookResult",
    "BetaDiagnostic",
    "BetaGateDecision",
    "beta_book",
    "beta_diagnostic",
    "beta_gate",
    "through_origin_beta",
]

BPS = 10_000.0


class BetaError(ValueError):
    """Raised when a beta cannot be computed without look-ahead or invention."""


#: §24 blocking-reason vocabulary (stable strings; never renamed silently).
BLOCK_UNIVERSE_SIZE = "universe_size_below_min_members"
BLOCK_FORMATION_HISTORY = "insufficient_formation_history"
BLOCK_BETA_HISTORY = "insufficient_beta_history"
BLOCK_MISSING_BTC = "missing_btc_window"
BLOCK_UNSYNCHRONIZED = "missing_asset_synchronization"
BLOCK_BETA_UNDEFINED = "beta_undefined"
BLOCK_OTHER = "other"


@dataclass(frozen=True, slots=True)
class BlockingReasons:
    """§24 — why candidate books could not be priced (never silently dropped).

    ``n_*`` counts *books* whose single blocking cause was that reason; their sum
    equals ``n_blocked``. ``names_excluded_*`` counts individual name-eligibility
    rejections aggregated across every decision time (a book may lose names for
    several reasons at once, so these are diagnostics, not a partition).
    """

    n_universe_size: int = 0
    n_formation_history: int = 0
    n_beta_history: int = 0
    n_missing_btc: int = 0
    n_unsynchronized: int = 0
    n_beta_undefined: int = 0
    n_other: int = 0
    names_excluded_formation_history: int = 0
    names_excluded_beta_history: int = 0

    @property
    def total(self) -> int:
        return (
            self.n_universe_size
            + self.n_formation_history
            + self.n_beta_history
            + self.n_missing_btc
            + self.n_unsynchronized
            + self.n_beta_undefined
            + self.n_other
        )

    def as_dict(self) -> dict[str, int]:
        return {
            "universe_size_below_min_members": self.n_universe_size,
            "insufficient_formation_history": self.n_formation_history,
            "insufficient_beta_history": self.n_beta_history,
            "missing_btc": self.n_missing_btc,
            "missing_asset_synchronization": self.n_unsynchronized,
            "beta_undefined": self.n_beta_undefined,
            "other": self.n_other,
            "total": self.total,
            "names_excluded_formation_history": self.names_excluded_formation_history,
            "names_excluded_beta_history": self.names_excluded_beta_history,
        }


class UniverseSnapshotLike(Protocol):
    """Structural view of the frozen PIT ``UniverseSnapshot`` (§24).

    Read-only ``@property`` members so a frozen dataclass (slots=True) satisfies
    the protocol without pretending its attributes are settable.
    """

    @property
    def eligible_assets(self) -> tuple[str, ...]: ...

    @property
    def exclusion_reasons(self) -> Mapping[str, str]: ...

    @property
    def synchronized(self) -> bool: ...

    @property
    def blocked_reason(self) -> str | None: ...


class PITUniverse(Protocol):
    """Structural view of ``DynamicAssetUniverse`` — only ``snapshot`` is needed."""

    def snapshot(self, decision_time: int) -> UniverseSnapshotLike: ...


def _log_returns(closes: Sequence[float]) -> list[float]:
    out: list[float] = []
    for i in range(1, len(closes)):
        a, b = closes[i - 1], closes[i]
        if a <= 0.0 or b <= 0.0:
            raise BetaError("non-positive close in beta window")
        out.append(math.log(b / a))
    return out


def through_origin_beta(returns: Sequence[float], market_returns: Sequence[float]) -> float:
    """Through-origin OLS slope of ``returns`` on ``market_returns`` (§22).

    Fails closed (raises) when the market window has zero variance or the lengths
    disagree — an undefined beta is never silently reported as 0.
    """
    if len(returns) != len(market_returns):
        raise BetaError("return series length mismatch")
    if not returns:
        raise BetaError("empty return window")
    sxx = math.fsum(x * x for x in market_returns)
    if sxx <= 1e-18:
        raise BetaError("market return window has zero variance")
    sxy = math.fsum(y * x for y, x in zip(returns, market_returns, strict=True))
    return sxy / sxx


@dataclass(frozen=True, slots=True)
class BetaBookResult:
    """§22 — the beta of one candidate book plus the per-name decomposition."""

    beta_book: float
    name_betas: Mapping[str, float]
    window_days: int
    computed: bool
    blocked_reason: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "beta_book": self.beta_book,
            "name_betas": dict(self.name_betas),
            "window_days": self.window_days,
            "computed": self.computed,
            "blocked_reason": self.blocked_reason,
        }


def beta_book(
    weights: Mapping[str, float],
    closes_by_symbol: Mapping[str, Mapping[int, float]],
    market_closes: Mapping[int, float],
    timestamps: Sequence[int],
) -> BetaBookResult:
    """Beta of a book from signed weights and PIT closes (§22).

    ``weights`` maps symbol -> signed weight (long positive, short negative).
    Only exact bars at the supplied timestamps are used; a missing bar fails the
    whole computation closed rather than interpolating.
    """
    window_days = max(0, len(timestamps) - 1)
    if len(timestamps) < 3:
        return BetaBookResult(
            beta_book=0.0,
            name_betas={},
            window_days=window_days,
            computed=False,
            blocked_reason="beta_window_too_short",
        )
    try:
        market_series = [market_closes[t] for t in timestamps]
        market_returns = _log_returns(market_series)
    except (KeyError, BetaError):
        return BetaBookResult(
            beta_book=0.0,
            name_betas={},
            window_days=window_days,
            computed=False,
            blocked_reason="market_beta_window_incomplete",
        )

    name_betas: dict[str, float] = {}
    for symbol, weight in weights.items():
        if weight == 0.0:
            continue
        series = closes_by_symbol.get(symbol)
        if series is None or any(t not in series for t in timestamps):
            return BetaBookResult(
                beta_book=0.0,
                name_betas={},
                window_days=window_days,
                computed=False,
                blocked_reason=f"name_beta_window_incomplete:{symbol}",
            )
        try:
            r = _log_returns([series[t] for t in timestamps])
            name_betas[symbol] = through_origin_beta(r, market_returns)
        except BetaError:
            return BetaBookResult(
                beta_book=0.0,
                name_betas={},
                window_days=window_days,
                computed=False,
                blocked_reason=f"name_beta_undefined:{symbol}",
            )

    total = math.fsum(weights[s] * b for s, b in name_betas.items())
    return BetaBookResult(
        beta_book=total,
        name_betas=name_betas,
        window_days=window_days,
        computed=True,
    )


@dataclass(frozen=True, slots=True)
class BetaGateDecision:
    """§23 — the fail-closed gate outcome for one book."""

    beta_book: float
    tolerance: float
    passes: bool
    action: str
    reason: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "beta_book": self.beta_book,
            "tolerance": self.tolerance,
            "passes": self.passes,
            "action": self.action,
            "reason": self.reason,
        }


def beta_gate(beta_value: float, tolerance: float, *, computed: bool = True) -> BetaGateDecision:
    """Apply the frozen fail-closed rule; never re-weight to force a pass (§23)."""
    if not computed:
        return BetaGateDecision(
            beta_book=beta_value,
            tolerance=tolerance,
            passes=False,
            action="FLAT",
            reason="BETA_UNDEFINED_FAIL_CLOSED",
        )
    if abs(beta_value) > tolerance + 1e-12:
        return BetaGateDecision(
            beta_book=beta_value,
            tolerance=tolerance,
            passes=False,
            action="FLAT",
            reason="REJECT_BETA",
        )
    return BetaGateDecision(
        beta_book=beta_value,
        tolerance=tolerance,
        passes=True,
        action="REBALANCE",
        reason="BETA_WITHIN_TOLERANCE",
    )


@dataclass(frozen=True, slots=True)
class BetaDiagnostic:
    """§24 — distribution of ``beta_book`` over candidate books (evidence only)."""

    n_books: int
    n_computed: int
    n_blocked: int
    mean: float
    median: float
    p5: float
    p25: float
    p75: float
    p95: float
    max_abs_beta: float
    fraction_within_tolerance: float
    tolerance: float
    betas: tuple[float, ...]
    blocking: BlockingReasons = BlockingReasons()
    fraction_within_0p05: float = 0.0
    fraction_within_0p10: float = 0.0
    fraction_within_0p20: float = 0.0
    median_eligible_names: float = 0.0

    def as_dict(self) -> dict[str, Any]:
        return {
            "n_books": self.n_books,
            "n_computed": self.n_computed,
            "n_blocked": self.n_blocked,
            "mean": self.mean,
            "median": self.median,
            "p5": self.p5,
            "p25": self.p25,
            "p75": self.p75,
            "p95": self.p95,
            "max_abs_beta": self.max_abs_beta,
            "fraction_within_tolerance": self.fraction_within_tolerance,
            "fraction_within_0p05": self.fraction_within_0p05,
            "fraction_within_0p10": self.fraction_within_0p10,
            "fraction_within_0p20": self.fraction_within_0p20,
            "median_eligible_names": self.median_eligible_names,
            "tolerance": self.tolerance,
            "blocking": self.blocking.as_dict(),
            "betas": list(self.betas),
        }


def _percentile(sorted_values: Sequence[float], q: float) -> float:
    """Linear-interpolation percentile (deterministic, no external deps)."""
    if not sorted_values:
        return 0.0
    if len(sorted_values) == 1:
        return sorted_values[0]
    pos = q * (len(sorted_values) - 1)
    lo = math.floor(pos)
    hi = math.ceil(pos)
    if lo == hi:
        return sorted_values[lo]
    frac = pos - lo
    return sorted_values[lo] * (1.0 - frac) + sorted_values[hi] * frac


def _frozen_score(
    closes: Mapping[int, float], decision_time: int, formation_days: int, ms_per_day: int
) -> float | None:
    """The frozen EXP-ARP-023 score: ``-log(close_t / close_{t-30})`` (PIT)."""
    t0 = decision_time - formation_days * ms_per_day
    p0 = closes.get(t0)
    p1 = closes.get(decision_time)
    if p0 is None or p1 is None or p0 <= 0.0 or p1 <= 0.0:
        return None
    return -math.log(p1 / p0)


def beta_diagnostic(
    closes_by_symbol: Mapping[str, Mapping[int, float]],
    decision_times: Sequence[int],
    *,
    top_k: int,
    min_members: int,
    formation_days: int = 30,
    beta_window_days: int = 60,
    beta_tolerance: float = 0.10,
    market_symbol: str = "BTCUSDT",
    ms_per_day: int = 86_400_000,
    universe: PITUniverse | None = None,
) -> BetaDiagnostic:
    """Measure the distribution of candidate-book beta without executing (§24).

    For each decision time the diagnostic reproduces the frozen EXP-ARP-023 book:

    * the PIT eligible universe is taken from the frozen ``ARP-006-UNIVERSE-v1``
      snapshot when ``universe`` is supplied (exactly the universe EXP-ARP-023
      uses), otherwise from an explicit fail-closed bar-availability filter;
    * the frozen score ``-log(close_t / close_{t-30})`` ranks the names;
    * the long top-k / short bottom-k book is beta-weighted and the frozen 60-day
      through-origin book beta is computed.

    Every book that cannot be priced is counted as *blocked* under a **single
    dominant, deterministic reason** — never silently treated as beta = 0. The
    reason priority is: missing BTC window > no eligible universe > insufficient
    formation history > insufficient beta history > unsynchronized names >
    undefined beta > other. Per-name exclusions are additionally aggregated.
    """
    market_closes = closes_by_symbol.get(market_symbol, {})
    betas: list[float] = []
    eligible_counts: list[int] = []
    n_universe_size = 0
    n_formation_history = 0
    n_beta_history = 0
    n_missing_btc = 0
    n_unsynchronized = 0
    n_beta_undefined = 0
    n_other = 0
    names_excl_formation = 0
    names_excl_beta = 0

    for t in decision_times:
        window = [t - (beta_window_days - k) * ms_per_day for k in range(beta_window_days + 1)]
        if any(ts not in market_closes for ts in window):
            n_missing_btc += 1
            continue

        n_unsync_excluded = 0
        if universe is not None:
            snap = universe.snapshot(t)
            candidates = list(snap.eligible_assets)
            n_unsync_excluded = sum(
                1 for reason in snap.exclusion_reasons.values() if "synchron" in reason
            )
        else:
            candidates = [s for s in closes_by_symbol if s != market_symbol]

        # formation history: exact bars at t and t - formation_days
        t_form = t - formation_days * ms_per_day
        with_formation = [
            s for s in candidates if t in closes_by_symbol[s] and t_form in closes_by_symbol[s]
        ]
        names_excl_formation += len(candidates) - len(with_formation)
        # beta history: every exact bar in the 61-observation beta window
        with_beta = [s for s in with_formation if all(ts in closes_by_symbol[s] for ts in window)]
        names_excl_beta += len(with_formation) - len(with_beta)

        scored: list[tuple[float, str]] = []
        for symbol in with_beta:
            s = _frozen_score(closes_by_symbol[symbol], t, formation_days, ms_per_day)
            if s is not None:
                scored.append((s, symbol))

        # Single dominant blocking reason (deterministic priority order).
        if len(scored) < max(min_members, 2 * top_k):
            if not candidates:
                n_universe_size += 1
            elif len(with_formation) < max(min_members, 2 * top_k):
                n_formation_history += 1
            elif len(with_beta) < max(min_members, 2 * top_k):
                n_beta_history += 1
            elif n_unsync_excluded > 0:
                n_unsynchronized += 1
            else:
                n_other += 1
            continue

        scored.sort(key=lambda pair: (-pair[0], pair[1]))
        long_names = [sym for _, sym in scored[:top_k]]
        short_names = [sym for _, sym in scored[-top_k:]]
        weights: dict[str, float] = {}
        for sym in long_names:
            weights[sym] = weights.get(sym, 0.0) + 1.0 / top_k
        for sym in short_names:
            weights[sym] = weights.get(sym, 0.0) - 1.0 / top_k

        result = beta_book(weights, closes_by_symbol, market_closes, window)
        if not result.computed:
            n_beta_undefined += 1
            continue
        betas.append(result.beta_book)
        eligible_counts.append(len(scored))

    ordered = sorted(betas)
    n = len(ordered)
    mean = statistics.fmean(ordered) if ordered else 0.0
    median = statistics.median(ordered) if ordered else 0.0
    max_abs = max((abs(b) for b in ordered), default=0.0)
    within = sum(1 for b in ordered if abs(b) <= beta_tolerance + 1e-12)
    within_05 = sum(1 for b in ordered if abs(b) <= 0.05 + 1e-12)
    within_20 = sum(1 for b in ordered if abs(b) <= 0.20 + 1e-12)
    blocking = BlockingReasons(
        n_universe_size=n_universe_size,
        n_formation_history=n_formation_history,
        n_beta_history=n_beta_history,
        n_missing_btc=n_missing_btc,
        n_unsynchronized=n_unsynchronized,
        n_beta_undefined=n_beta_undefined,
        n_other=n_other,
        names_excluded_formation_history=names_excl_formation,
        names_excluded_beta_history=names_excl_beta,
    )
    return BetaDiagnostic(
        n_books=len(decision_times),
        n_computed=n,
        n_blocked=blocking.total,
        mean=mean,
        median=median,
        p5=_percentile(ordered, 0.05),
        p25=_percentile(ordered, 0.25),
        p75=_percentile(ordered, 0.75),
        p95=_percentile(ordered, 0.95),
        max_abs_beta=max_abs,
        fraction_within_tolerance=(within / n if n else 0.0),
        tolerance=beta_tolerance,
        betas=tuple(ordered),
        blocking=blocking,
        fraction_within_0p05=(within_05 / n if n else 0.0),
        fraction_within_0p10=(within / n if n else 0.0),
        fraction_within_0p20=(within_20 / n if n else 0.0),
        median_eligible_names=(statistics.median(eligible_counts) if eligible_counts else 0.0),
    )
