"""Cross-asset aggressive-flow panel and V2 hypothesis primitives.

Phase: MICROSTRUCTURE-EDGE & FORWARD-DATA V1 (research plane only).

This module exists because the V1 experiments treated each asset *in isolation*
within a day (`scripts/aggtrades_experiments.py`) and therefore could not express
hypotheses that are inherently cross-sectional:

* ``M-09`` BTC flow -> ETH/SOL future return (lead/lag),
* ``M-10`` cross-sectional flow (an asset's flow relative to the panel),
* ``M-02`` flow *impulse* (change vs. recent baseline, not the level).

Everything here is point-in-time strict. A signal for a decision taken at
``available_at`` of bar ``i`` may use only bars whose own ``available_at`` is
``<= decisions[i]``. The single decision clock is the *bar close* availability
(``open_time + bar_minutes * minute_ms + 1``), never the bar open.

No function in this module is imported by the runtime/trading path.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass

__all__ = [
    "BAR_MINUTES",
    "COST_STRESS_MULTIPLES",
    "FLOW_IMPULSE_PATH",
    "IC_INFORMATIVE_MIN",
    "MINUTE_MS",
    "OI_STATES",
    "PanelAlignmentError",
    "PanelBar",
    "PanelSlice",
    "PanelSummary",
    "aggregate_minutes_to_bars",
    "conditional_stats",
    "cross_sectional_flow",
    "flow_impulse_series",
    "information_content",
    "mean",
    "oi_price_state",
    "parse_minute_row",
    "pit_lead_lag",
    "quantile_table",
    "spearman",
    "stdev",
    "summarize_panel",
    "trade_stats",
]

MINUTE_MS = 60_000
BAR_MINUTES = 5
BAR_MS = BAR_MINUTES * MINUTE_MS

#: A feature counts as informative only if the rank correlation with the
#: forward return reaches this magnitude on a sample of at least
#: :data:`IC_MIN_OBSERVATIONS` decisions. Pre-registered, never tuned.
IC_INFORMATIVE_MIN = 0.01
IC_MIN_OBSERVATIONS = 100

#: Cost-stress envelopes applied to every candidate (pre-registered).
COST_STRESS_MULTIPLES: tuple[float, ...] = (1.25, 1.5, 2.0)

#: Hypotheses that require the *change* in flow, not its level.
FLOW_IMPULSE_PATH = "M-02"

#: The four price/open-interest quadrants (M-07), plus the unchanged bucket.
OI_STATES: tuple[str, ...] = (
    "PRICE_UP_OI_UP",
    "PRICE_UP_OI_DOWN",
    "PRICE_DOWN_OI_UP",
    "PRICE_DOWN_OI_DOWN",
)
OI_UNCHANGED = "UNCHANGED"


class PanelAlignmentError(ValueError):
    """Raised when a panel cannot be aligned without breaking point-in-time."""


# ---------------------------------------------------------------------------
# Inputs
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class MinuteRow:
    """One UTC minute of aggregated trades (aggTrades, SRC-04).

    ``aggressor_from`` is ``isBuyerMaker``: ``True`` means the *seller* was the
    aggressor, so ``sell_vol`` receives the print's quantity.
    """

    symbol: str
    minute_ms: int
    available_at_ms: int
    n_trades: int
    buy_volume: float
    sell_volume: float
    buy_quote: float
    sell_quote: float
    sum_qty_sq: float
    large_buy_volume: float
    large_sell_volume: float
    first_price: float
    last_price: float
    high: float
    low: float
    max_trade_qty: float
    min_interarrival_ms: int | None

    def __post_init__(self) -> None:
        if not self.symbol:
            raise ValueError("symbol must be non-empty")
        if self.n_trades < 0:
            raise ValueError(f"n_trades must be >= 0, got {self.n_trades}")
        for name in (
            "buy_volume",
            "sell_volume",
            "buy_quote",
            "sell_quote",
            "sum_qty_sq",
            "large_buy_volume",
            "large_sell_volume",
            "max_trade_qty",
        ):
            value = getattr(self, name)
            if value < 0.0:
                raise ValueError(f"{name} must be >= 0, got {value}")
        for name in ("first_price", "last_price", "high", "low"):
            if getattr(self, name) <= 0.0:
                raise ValueError(f"{name} must be > 0, got {getattr(self, name)}")
        if self.high < self.low:
            raise ValueError(f"high < low at {self.minute_ms}")
        if not (self.low - 1e-9 <= self.first_price <= self.high + 1e-9):
            raise ValueError(f"first_price outside [low, high] at {self.minute_ms}")
        if not (self.low - 1e-9 <= self.last_price <= self.high + 1e-9):
            raise ValueError(f"last_price outside [low, high] at {self.minute_ms}")
        if self.min_interarrival_ms is not None and self.min_interarrival_ms < 0:
            raise ValueError("min_interarrival_ms must be >= 0 when present")
        if self.available_at_ms <= self.minute_ms:
            raise ValueError(
                f"available_at_ms ({self.available_at_ms}) must be after minute_ms "
                f"({self.minute_ms})"
            )

    @property
    def total_volume(self) -> float:
        return self.buy_volume + self.sell_volume


def _as_float(raw: Mapping[str, object], key: str) -> float:
    value = raw.get(key)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"minute row field {key!r} must be numeric, got {value!r}")
    return float(value)


def _as_int(raw: Mapping[str, object], key: str) -> int:
    value = raw.get(key)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"minute row field {key!r} must be numeric, got {value!r}")
    return int(value)


def parse_minute_row(raw: Mapping[str, object]) -> MinuteRow:
    """Parse one persisted minute-aggregate record, failing closed.

    A missing, non-numeric or inconsistent field raises ``ValueError``; it is
    never silently defaulted to zero.
    """
    symbol = raw.get("symbol")
    if symbol is None:
        raise ValueError("minute row is missing 'symbol'")
    if not isinstance(symbol, str):
        raise ValueError(f"minute row 'symbol' must be a string, got {symbol!r}")
    return MinuteRow(
        symbol=symbol,
        minute_ms=_as_int(raw, "minute_ms"),
        available_at_ms=_as_int(raw, "available_at"),
        n_trades=_as_int(raw, "n_trades"),
        buy_volume=_as_float(raw, "buy_vol"),
        sell_volume=_as_float(raw, "sell_vol"),
        buy_quote=_as_float(raw, "buy_quote"),
        sell_quote=_as_float(raw, "sell_quote"),
        sum_qty_sq=_as_float(raw, "sum_qty_sq"),
        large_buy_volume=_as_float(raw, "large_buy_vol"),
        large_sell_volume=_as_float(raw, "large_sell_vol"),
        first_price=_as_float(raw, "first_price"),
        last_price=_as_float(raw, "last_price"),
        high=_as_float(raw, "high"),
        low=_as_float(raw, "low"),
        max_trade_qty=_as_float(raw, "max_trade_qty"),
        min_interarrival_ms=(
            None
            if raw.get("min_interarrival_ms") is None
            else _as_int(raw, "min_interarrival_ms")
        ),
    )


@dataclass(frozen=True, slots=True)
class PanelBar:
    """One aligned aggregation bar enriched with aggressor flow."""

    symbol: str
    open_time_ms: int
    available_at_ms: int
    close: float
    buy_volume: float
    sell_volume: float
    n_trades: int
    large_buy_volume: float
    large_sell_volume: float
    min_interarrival_ms: int | None
    vwap: float | None

    def __post_init__(self) -> None:
        if not self.symbol:
            raise ValueError("symbol must be non-empty")
        if self.close <= 0.0:
            raise ValueError(f"close must be > 0, got {self.close}")
        if self.n_trades < 0:
            raise ValueError("n_trades must be >= 0")
        for name in ("buy_volume", "sell_volume", "large_buy_volume", "large_sell_volume"):
            value = getattr(self, name)
            if value < 0.0:
                raise ValueError(f"{name} must be >= 0, got {value}")
        if self.vwap is not None and self.vwap <= 0.0:
            raise ValueError("vwap must be > 0 when present")
        if self.available_at_ms <= self.open_time_ms:
            raise ValueError(
                "available_at_ms must be after open_time_ms (a bar is knowable only "
                "at its close)"
            )

    @property
    def volume(self) -> float:
        return self.buy_volume + self.sell_volume

    @property
    def flow_imbalance(self) -> float:
        """Aggressive-flow imbalance in ``[-1, 1]``; ``0`` on a volume-less bar."""
        total = self.volume
        if total <= 0.0:
            return 0.0
        return (self.buy_volume - self.sell_volume) / total


def aggregate_minutes_to_bars(
    rows: Sequence[MinuteRow],
    *,
    bar_minutes: int = BAR_MINUTES,
    minute_ms: int = MINUTE_MS,
) -> list[PanelBar]:
    """Aggregate minute rows into aligned UTC bars.

    Only **complete** groups of ``bar_minutes`` consecutive minutes are emitted;
    a truncated day therefore drops its trailing partial bucket instead of
    producing a partially-aggregated bar. ``available_at_ms`` is the bucket open
    plus the bucket width plus 1 ms, i.e. the close.
    """
    if bar_minutes < 1:
        raise ValueError("bar_minutes must be >= 1")
    if not rows:
        return []
    width = bar_minutes * minute_ms
    by_minute: dict[int, MinuteRow] = {r.minute_ms: r for r in rows}
    if len(by_minute) != len(rows):
        raise ValueError("duplicate minute rows in input")
    symbols = {r.symbol for r in rows}
    if len(symbols) != 1:
        raise ValueError(f"aggregate_minutes_to_bars expects one symbol, got {symbols}")

    buckets: dict[int, list[MinuteRow]] = {}
    for row in rows:
        buckets.setdefault((row.minute_ms // width) * width, []).append(row)

    bars: list[PanelBar] = []
    for open_ms in sorted(buckets):
        bucket = sorted(buckets[open_ms], key=lambda r: r.minute_ms)
        expected = [open_ms + k * minute_ms for k in range(bar_minutes)]
        if [r.minute_ms for r in bucket] != expected:
            continue
        buy = sum(r.buy_volume for r in bucket)
        sell = sum(r.sell_volume for r in bucket)
        quote = sum(r.buy_quote + r.sell_quote for r in bucket)
        total = buy + sell
        interarrivals = [r.min_interarrival_ms for r in bucket if r.min_interarrival_ms is not None]
        bars.append(
            PanelBar(
                symbol=bucket[0].symbol,
                open_time_ms=open_ms,
                available_at_ms=open_ms + width + 1,
                close=bucket[-1].last_price,
                buy_volume=buy,
                sell_volume=sell,
                n_trades=sum(r.n_trades for r in bucket),
                large_buy_volume=sum(r.large_buy_volume for r in bucket),
                large_sell_volume=sum(r.large_sell_volume for r in bucket),
                min_interarrival_ms=min(interarrivals) if interarrivals else None,
                vwap=(quote / total) if total > 0.0 else None,
            )
        )
    return bars


# ---------------------------------------------------------------------------
# Panel alignment
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class PanelSlice:
    """One bar clock shared by every asset in the panel.

    ``decision_time_ms`` is the earliest instant the slice is usable: the bar
    close. All members must agree on it, otherwise the assets are not on the
    same clock and no cross-sectional statistic may be formed.
    """

    open_time_ms: int
    decision_time_ms: int
    bars: tuple[PanelBar, ...]

    def __post_init__(self) -> None:
        if len(self.bars) < 2:
            raise ValueError("a panel slice needs at least two assets")
        names = [b.symbol for b in self.bars]
        if len(set(names)) != len(names):
            raise PanelAlignmentError(f"duplicate symbol in panel slice: {names}")
        if len({b.available_at_ms for b in self.bars}) != 1:
            raise PanelAlignmentError(
                "panel slice assets disagree on availability; cross-sectional "
                "statistics would mix clocks"
            )
        if len({b.open_time_ms for b in self.bars}) != 1:
            raise PanelAlignmentError("panel slice assets disagree on open time")
        if self.decision_time_ms != self.bars[0].available_at_ms:
            raise PanelAlignmentError(
                "decision_time_ms must equal the shared bar availability"
            )

    @property
    def symbols(self) -> tuple[str, ...]:
        return tuple(b.symbol for b in self.bars)

    def bar(self, symbol: str) -> PanelBar:
        for b in self.bars:
            if b.symbol == symbol:
                return b
        raise KeyError(f"symbol {symbol!r} not in panel slice")

    def flow(self, symbol: str) -> float:
        return self.bar(symbol).flow_imbalance


def build_panel(
    bars_by_symbol: Mapping[str, Sequence[PanelBar]],
    *,
    symbols: Sequence[str] | None = None,
    require_all: bool = True,
) -> list[PanelSlice]:
    """Intersect per-asset bar series into a common-clock panel.

    With ``require_all`` (the default and the only mode used for admission), a
    timestamp is kept only when **every** requested asset has a bar there: a
    cross-sectional statistic over a partially observed timestamp is not the
    statistic that was pre-registered.
    """
    names = list(symbols) if symbols is not None else sorted(bars_by_symbol)
    if len(names) < 2:
        raise ValueError("a panel needs at least two symbols")
    for name in names:
        if name not in bars_by_symbol:
            raise KeyError(f"missing bars for panel symbol {name!r}")

    by_key: dict[str, dict[int, PanelBar]] = {
        name: {b.open_time_ms: b for b in bars_by_symbol[name]} for name in names
    }
    common: set[int] = set(by_key[names[0]])
    for name in names[1:]:
        common &= set(by_key[name])
    if require_all is False:  # pragma: no cover - explicit opt-out, never used
        common = set().union(*(set(v) for v in by_key.values()))

    slices: list[PanelSlice] = []
    for open_ms in sorted(common):
        members = tuple(by_key[name][open_ms] for name in names)
        slices.append(
            PanelSlice(
                open_time_ms=open_ms,
                decision_time_ms=members[0].available_at_ms,
                bars=members,
            )
        )
    return slices


@dataclass(frozen=True, slots=True)
class PanelSummary:
    symbols: tuple[str, ...]
    slices: int
    first_decision_time_ms: int | None
    last_decision_time_ms: int | None
    max_gap_ms: int
    duplicate_timestamps: int

    def as_dict(self) -> dict[str, object]:
        return {
            "symbols": list(self.symbols),
            "slices": self.slices,
            "first_decision_time_ms": self.first_decision_time_ms,
            "last_decision_time_ms": self.last_decision_time_ms,
            "max_gap_ms": self.max_gap_ms,
            "duplicate_timestamps": self.duplicate_timestamps,
        }


def summarize_panel(panel: Sequence[PanelSlice]) -> PanelSummary:
    """Structural quality summary of an aligned panel (gaps, duplicates)."""
    if not panel:
        return PanelSummary((), 0, None, None, 0, 0)
    decisions = [s.decision_time_ms for s in panel]
    gaps = [
        decisions[i] - decisions[i - 1]
        for i in range(1, len(decisions))
    ]
    return PanelSummary(
        symbols=panel[0].symbols,
        slices=len(panel),
        first_decision_time_ms=decisions[0],
        last_decision_time_ms=decisions[-1],
        max_gap_ms=max(gaps) if gaps else 0,
        duplicate_timestamps=len(decisions) - len(set(decisions)),
    )


# ---------------------------------------------------------------------------
# Hypotheses
# ---------------------------------------------------------------------------


def pit_lead_lag(
    source: Sequence[PanelSlice],
    target: Sequence[PanelSlice],
    *,
    source_symbol: str,
    lag: int,
) -> list[tuple[int, int, float]]:
    """PIT-safe ``(target_index, source_index, source_value)`` lead/lag pairs.

    ``lag == 0`` is the contemporaneous cross-sectional case; ``lag >= 1`` asks
    whether the source asset's flow predicts the target *later*. ``lag < 0``
    would require the future and is rejected outright: this function is the only
    sanctioned way to build a cross-asset signal, so a look-ahead cannot be
    expressed by accident.

    The hard rule ``source.available_at <= target.decision_time`` is checked per
    pair and raises :class:`PanelAlignmentError` when it fails, rather than
    dropping the observation silently.
    """
    if lag < 0:
        raise PanelAlignmentError(
            f"negative lag {lag} would use information published after the decision"
        )
    if not source or not target:
        return []
    if source_symbol not in source[0].symbols:
        raise KeyError(f"source symbol {source_symbol!r} absent from source panel")
    out: list[tuple[int, int, float]] = []
    for j, target_slice in enumerate(target):
        i = j - lag
        if i < 0:
            continue
        source_slice = source[i]
        if source_slice.decision_time_ms > target_slice.decision_time_ms:
            raise PanelAlignmentError(
                f"source decision time {source_slice.decision_time_ms} is after target "
                f"{target_slice.decision_time_ms} (lag {lag})"
            )
        out.append((j, i, source_slice.flow(source_symbol)))
    return out


def cross_sectional_flow(
    panel: Sequence[PanelSlice],
) -> dict[str, list[float]]:
    """Per-asset flow deviation from the cross-sectional mean, plus dispersion.

    Keys are the panel symbols plus ``"__dispersion__"`` (population standard
    deviation of the flows at that timestamp). A cross-sectional deviation is
    only defined when every asset is observed, which :func:`build_panel`
    guarantees.
    """
    if not panel:
        return {}
    symbols = panel[0].symbols
    out: dict[str, list[float]] = {s: [] for s in symbols}
    out["__dispersion__"] = []
    for sl in panel:
        flows = [sl.flow(s) for s in symbols]
        mu = sum(flows) / len(flows)
        for s, f in zip(symbols, flows, strict=True):
            out[s].append(f - mu)
        out["__dispersion__"].append(stdev(flows))
    return out


def flow_impulse_series(flows: Sequence[float], window: int) -> list[float | None]:
    """M-02 flow *impulse*: z-score of the first difference of flow.

    The level of aggressive flow is a different hypothesis (M-01) and is
    deliberately not reproducible here: the first observation of a window is
    consumed by differencing, and the result is ``None`` until ``window`` deltas
    exist. A burst is "flow changing fast relative to its own recent baseline",
    not "flow high".

    A degenerate baseline (zero variance of the recent deltas) yields exactly
    ``0.0`` — "no impulse" — rather than ``None``, because the window *is*
    complete; conflating that with "not enough data" would hide the case.
    """
    if window < 2:
        raise ValueError("window must be >= 2")
    deltas: list[float] = []
    for i in range(1, len(flows)):
        deltas.append(flows[i] - flows[i - 1])
    out: list[float | None] = [None] * len(flows)
    for k in range(len(deltas)):
        if k + 1 < window:
            continue
        w = deltas[k + 1 - window : k + 1]
        mu = sum(w) / len(w)
        var = sum((x - mu) ** 2 for x in w) / len(w)
        sd = math.sqrt(var)
        out[k + 1] = (deltas[k] - mu) / sd if sd > 0.0 else 0.0
    return out


def oi_price_state(price_change_bps: float, oi_change_pct: float) -> str:
    """Classify one bar into an M-07 quadrant.

    A zero change in either dimension is not forced into a sign: it is labelled
    :data:`OI_UNCHANGED` and excluded from the positive/negative quadrant
    statistics, so the four states keep their pre-registered meaning.
    """
    if price_change_bps == 0.0 or oi_change_pct == 0.0:
        return OI_UNCHANGED
    price_up = price_change_bps > 0.0
    oi_up = oi_change_pct > 0.0
    if price_up and oi_up:
        return "PRICE_UP_OI_UP"
    if price_up and not oi_up:
        return "PRICE_UP_OI_DOWN"
    if not price_up and oi_up:
        return "PRICE_DOWN_OI_UP"
    return "PRICE_DOWN_OI_DOWN"


# ---------------------------------------------------------------------------
# Statistics (research-only, no numpy dependency)
# ---------------------------------------------------------------------------


def mean(values: Sequence[float]) -> float:
    if not values:
        raise ValueError("mean of an empty sequence is undefined")
    return sum(values) / len(values)


def stdev(values: Sequence[float]) -> float:
    if not values:
        raise ValueError("stdev of an empty sequence is undefined")
    mu = sum(values) / len(values)
    return math.sqrt(sum((v - mu) ** 2 for v in values) / len(values))


def _average_ranks(values: Sequence[float]) -> list[float]:
    order = sorted(range(len(values)), key=lambda i: values[i])
    ranks = [0.0] * len(values)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and values[order[j + 1]] == values[order[i]]:
            j += 1
        average = (i + j) / 2.0
        for k in range(i, j + 1):
            ranks[order[k]] = average
        i = j + 1
    return ranks


def spearman(xs: Sequence[float], ys: Sequence[float]) -> float:
    """Tie-aware Spearman rank correlation (V1 used an untied variant)."""
    if len(xs) != len(ys):
        raise ValueError("spearman needs equal-length inputs")
    if len(xs) < 3:
        return 0.0
    rx, ry = _average_ranks(xs), _average_ranks(ys)
    mx, my = mean(rx), mean(ry)
    num = sum((rx[i] - mx) * (ry[i] - my) for i in range(len(rx)))
    dx = math.sqrt(sum((v - mx) ** 2 for v in rx))
    dy = math.sqrt(sum((v - my) ** 2 for v in ry))
    return num / (dx * dy) if dx > 0.0 and dy > 0.0 else 0.0


def quantile_table(
    xs: Sequence[float], ys: Sequence[float], buckets: int = 5
) -> dict[str, object]:
    """Bucket ``ys`` by ``xs`` quantile and report each bucket's mean.

    ``monotone_score`` is the Spearman correlation between bucket index and
    bucket mean, in ``[-1, 1]``; ``top_minus_bottom_bps`` is the raw difference
    between the extreme buckets. Both are descriptive — the *pre-registered*
    decision rule is the survivor/filter ladder, not a bucket extreme.
    """
    if len(xs) != len(ys):
        raise ValueError("quantile_table needs equal-length inputs")
    n = len(xs)
    if n < buckets * 2:
        return {
            "n": n,
            "buckets": [],
            "top_minus_bottom_bps": None,
            "monotone_score": None,
            "status": "INSUFFICIENT_DATA",
        }
    order = sorted(range(n), key=lambda i: xs[i])
    size = n // buckets
    rows: list[dict[str, object]] = []
    means: list[float] = []
    for b in range(buckets):
        lo = b * size
        hi = n if b == buckets - 1 else (b + 1) * size
        idx = order[lo:hi]
        if not idx:
            continue
        bucket_mean = sum(ys[i] for i in idx) / len(idx)
        means.append(bucket_mean)
        rows.append(
            {
                "bucket": b,
                "n": len(idx),
                "mean_forward_bps": round(bucket_mean, 4),
                "x_min": round(xs[idx[0]], 6),
                "x_max": round(xs[idx[-1]], 6),
            }
        )
    spread = means[-1] - means[0] if len(means) >= 2 else None
    mono = spearman([float(i) for i in range(len(means))], means) if len(means) >= 3 else None
    return {
        "n": n,
        "buckets": rows,
        "top_minus_bottom_bps": None if spread is None else round(spread, 4),
        "monotone_score": None if mono is None else round(mono, 4),
        "status": "OK",
    }


def conditional_stats(groups: Mapping[str, Sequence[float]]) -> dict[str, dict[str, object]]:
    """Per-group forward-return statistics (used by the M-07 4-state test)."""
    out: dict[str, dict[str, object]] = {}
    for name, values in groups.items():
        if not values:
            out[name] = {"n": 0}
            continue
        out[name] = {
            "n": len(values),
            "mean_bps": round(mean(values), 4),
            "median_bps": round(sorted(values)[len(values) // 2], 4),
            "stdev_bps": round(stdev(values), 4) if len(values) > 1 else 0.0,
            "share_positive": round(sum(1 for v in values if v > 0) / len(values), 4),
        }
    return out


def trade_stats(pnl: Sequence[float]) -> dict[str, object]:
    """Trade-level statistics on a per-decision P&L series (in bps)."""
    if not pnl:
        return {"n": 0}
    n = len(pnl)
    mu = sum(pnl) / n
    wins = [p for p in pnl if p > 0.0]
    losses = [p for p in pnl if p < 0.0]
    gross_pos = sum(wins)
    gross_neg = abs(sum(losses))
    sd = stdev(pnl) if n > 1 else 0.0
    cumulative = 0.0
    peak = 0.0
    max_dd = 0.0
    for p in pnl:
        cumulative += p
        peak = max(peak, cumulative)
        max_dd = max(max_dd, peak - cumulative)
    return {
        "n": n,
        "mean_bps": round(mu, 4),
        "total_bps": round(sum(pnl), 2),
        "win_rate": round(len(wins) / n, 4),
        "pf": round(gross_pos / gross_neg, 4) if gross_neg > 0.0 else None,
        "sharpe_per_trade": round(mu / sd, 4) if sd > 0.0 else None,
        "max_dd_bps": round(max_dd, 2),
    }


def information_content(
    xs: Iterable[float | None], ys: Iterable[float | None]
) -> dict[str, object]:
    """Filter 0: does the feature track the forward return on DEV?

    ``observed`` and ``features`` are the honest outputs: a feature whose rank
    correlation is below :data:`IC_INFORMATIVE_MIN` on fewer than
    :data:`IC_MIN_OBSERVATIONS` decisions is ``NO_INFORMATION``, not a weak
    edge to be traded smaller.
    """
    xv: list[float] = []
    yv: list[float] = []
    for x, y in zip(xs, ys, strict=True):
        if x is None or y is None:
            continue
        xv.append(x)
        yv.append(y)
    n = len(xv)
    if n < IC_MIN_OBSERVATIONS:
        return {
            "n": n,
            "ic_spearman": None,
            "top_bottom_bps": None,
            "monotone_score": None,
            "status": "INSUFFICIENT_DATA",
        }
    ic = spearman(xv, yv)
    table = quantile_table(xv, yv, buckets=5)
    status = "HAS_INFORMATION" if abs(ic) >= IC_INFORMATIVE_MIN else "NO_INFORMATION"
    return {
        "n": n,
        "ic_spearman": round(ic, 6),
        "top_bottom_bps": table["top_minus_bottom_bps"],
        "monotone_score": table["monotone_score"],
        "buckets": table["buckets"],
        "status": status,
    }
