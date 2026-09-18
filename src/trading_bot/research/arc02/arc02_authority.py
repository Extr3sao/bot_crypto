"""ARC-02 frozen BTC -> ALT lead-lag authority reader, features and signal rules.

Mechanism (frozen, recovered from the ARC-02 candidate design and re-frozen under the
project's execution/estimator conventions): a sufficiently unusual **completed** BTC 5m
log return, together with a follower (ETH/SOL) that has moved in the SAME direction but
has not yet responded proportionally, predicts follower continuation in that direction.

Frozen primitives (no future information, no economics):

* leader return        ``r_btc(t) = ln(close_btc(t) / close_btc(t - BAR_MS))``
* trailing robust scale ``s(t) = median(|r_btc(t - j*BAR_MS)| for j = 1..288)``
  (location estimator: NONE — the scale is not centred; the mean 5m log return is
  treated as zero by construction rather than estimated)
* shock statistic      ``z(t) = r_btc(t) / s(t)``
* BTC_SHOCK(t)         ``|z(t)| > 3.0`` (STRICT)
* follower return      ``r_f(t) = ln(close_f(t) / close_f(t - BAR_MS))``
* SAME_SIGN(t)         ``r_btc(t) * r_f(t) > 0`` (both strictly non-zero)
* FOLLOWER_UNDERREACTION(t)  ``|r_f(t)| < 0.5 * |r_btc(t)|`` (STRICT)
* direction            BTC up-shock + positive underreaction -> LONG follower;
                       BTC down-shock + negative underreaction -> SHORT follower.

Time semantics (PIT):

* a bar is usable only once COMPLETE: the decision instant is the bar's close time;
* ``decision_time_ms = max(close_btc(t), close_f(t))`` over the aligned slot ``t``;
* every reference observation satisfies ``data_time <= decision_time``;
* entry is the OPEN of the first follower bar with ``open_time_ms > decision_time_ms``;
* exit is the OPEN of the follower bar at ``entry_open_time_ms + HOLDING_BARS*BAR_MS``.

The reader consumes only the ARC-02 projection partitions (``t``, ``ct``, ``o``, ``c``).
Volume, quote volume, trade count and taker-buy fields are absent from the projection by
construction, so ARC-02 structurally cannot read the H5 order-flow or ARC-03
participation families.
"""

from __future__ import annotations

import json
import math
import os
from bisect import bisect_right
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from trading_bot.research.arc02.arc02_normalize import (
    BAR_MS,
    DAY_MS,
    DROPPED_FIELDS,
    PROJECTED_FIELDS,
    PROJECTION_RELPATH,
    sha256_file,
)

REPO = Path(__file__).resolve().parents[4]
PARTITION_RELPATH = PROJECTION_RELPATH

# ------------------------------------------------------------------ frozen definition
LEADER: str = "BTCUSDT"
FOLLOWERS: tuple[str, ...] = ("ETHUSDT", "SOLUSDT")
ASSETS: tuple[str, ...] = (LEADER,) + FOLLOWERS

SHOCK_LOOKBACK_BARS: int = 288
SHOCK_MIN_OBS: int = SHOCK_LOOKBACK_BARS  # ALL references required, else fail closed
SHOCK_THRESHOLD: float = 3.0
SHOCK_INEQUALITY: str = "STRICT_GREATER_THAN"
UNDERREACTION_RATIO: float = 0.5
UNDERREACTION_INEQUALITY: str = "STRICT_LESS_THAN"
DECISION_TIMEFRAME: str = "5m"

HOLDING_BARS: int = 1
HOLDING_MS: int = HOLDING_BARS * BAR_MS

PRIMARY_COST_BPS: int = 10
COST_SCENARIOS_BPS: tuple[int, ...] = (0, 10, 20, 40)

NULL_SEED: int = 20260915
BOOTSTRAP_SEED: int = 20260915
PERMUTATION_SEED: int = 20260915
BOOTSTRAP_RESAMPLES: int = 10_000
PERMUTATION_DRAWS: int = 10_000
PERMUTATION_ALPHA: float = 0.05

TIMING_CONTROL_OFFSET_BARS: int = HOLDING_BARS  # +1 bar = +5 minutes
LEADER_CONTROL_LAG_BARS: int = SHOCK_LOOKBACK_BARS  # +24 hours

#: Frozen common-window span (a constant of the preregistration, NOT a trade-derived value).
COMMON_WINDOW_SPAN_DAYS: float = 2177.7083333333335

G1_MIN_TOTAL_TRADES: int = 120
G1_MIN_TRADES_PER_FOLLOWER: int = 40
G4_MIN_PROFIT_FACTOR: float = 1.15
G5_MIN_SHARPE: float = 0.50
G10_MAX_FOLLOWER_SHARE: float = 0.70
G10_MAX_MONTH_SHARE: float = 0.40
G10_MAX_SINGLE_TRADE_SHARE: float = 0.25

LONG = "LONG"
SHORT = "SHORT"
NO_SIGNAL = "NO_SIGNAL"

#: Frozen NO_SIGNAL precedence (the FIRST satisfied reason is recorded; a signal is
#: emitted only when no reason applies).
NO_SIGNAL_PRECEDENCE: tuple[str, ...] = (
    "OUTSIDE_COMMON_WINDOW",
    "BAR_ALIGNMENT_FAILURE",
    "LEADER_HISTORY_INCOMPLETE",
    "LEADER_SCALE_ZERO",
    "NO_BTC_SHOCK",
    "FOLLOWER_BAR_MISSING",
    "FOLLOWER_NO_SAME_SIGN_RESPONSE",
    "FOLLOWER_NOT_UNDERREACTING",
    "POSITION_ALREADY_OPEN",
    "INSUFFICIENT_FORWARD_PRICE_DATA",
)


def resolve_partition_dir(data_root: Path | str | None = None) -> Path:
    """ARC-02 projection directory under an explicit or env-provided data root.

    Resolution order: explicit ``data_root`` argument -> ``ARC02_DATA_ROOT`` env ->
    the in-tree repository root. Used by the portable read-only verifier so a wrong or
    empty data root is detected and failed closed instead of being trusted.
    """
    if data_root is None:
        env = os.environ.get("ARC02_DATA_ROOT")
        if env:
            data_root = env
    base = Path(data_root) if data_root is not None else REPO
    if not base.is_absolute():
        raise ValueError(f"ARC02 data root must be an absolute path, got {base!r}")
    return base / PARTITION_RELPATH


@dataclass(frozen=True)
class Projection5m:
    """Certified ARC-02 projection partition for one symbol (PIT-causal reads)."""

    symbol: str
    t: tuple[int, ...]
    ct: tuple[int, ...]
    o: tuple[float, ...]
    c: tuple[float, ...]
    sha256: str
    path: str
    rows: int
    index: dict[int, int] = field(default_factory=dict, repr=False)

    def slot_index(self, open_time_ms: int) -> int | None:
        return self.index.get(open_time_ms)

    def last_completed_index(self, decision_time_ms: int) -> int | None:
        pos = bisect_right(self.ct, decision_time_ms) - 1
        return pos if pos >= 0 else None

    def first_index_strictly_after(self, t_ms: int) -> int | None:
        pos = bisect_right(self.t, t_ms)
        return pos if pos < len(self.t) else None


def load_partition(symbol: str, *, partition_dir: Path | None = None, verify: bool = True) -> Projection5m:
    base = partition_dir if partition_dir is not None else resolve_partition_dir()
    path = base / f"{symbol}.jsonl"
    if not path.exists():
        raise FileNotFoundError(f"missing ARC-02 projection partition: {path}")
    ts: list[int] = []
    cts: list[int] = []
    o: list[float] = []
    c: list[float] = []
    with path.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            r = json.loads(line)
            ts.append(int(r["t"]))
            cts.append(int(r["ct"]))
            o.append(float(r["o"]))
            c.append(float(r["c"]))
    order = sorted(range(len(ts)), key=lambda i: ts[i])
    if order != list(range(len(ts))):
        ts = [ts[i] for i in order]
        cts = [cts[i] for i in order]
        o = [o[i] for i in order]
        c = [c[i] for i in order]
    if len(set(ts)) != len(ts):
        raise ValueError(f"CONFLICTING_OR_DUPLICATE_SLOT in {symbol}")
    digest = sha256_file(path) if verify else ""
    return Projection5m(
        symbol=symbol,
        t=tuple(ts),
        ct=tuple(cts),
        o=tuple(o),
        c=tuple(c),
        sha256=digest,
        path=str(path),
        rows=len(ts),
        index={t: i for i, t in enumerate(ts)},
    )


def median(values: list[float]) -> float:
    """Order-statistic median; for an EVEN count the mean of the two central values.

    The estimator is stated explicitly because the lookback (288) is even. No runtime
    default or library convention is consulted.
    """
    if not values:
        raise ValueError("median of an empty sequence is undefined in ARC-02")
    s = sorted(values)
    n = len(s)
    mid = n // 2
    if n % 2:
        return s[mid]
    return (s[mid - 1] + s[mid]) / 2.0


def log_return(k: Projection5m, i: int) -> float | None:
    """Completed 5m log return of bar ``i``; ``None`` when the previous slot is absent."""
    if i <= 0:
        return None
    if k.t[i] - k.t[i - 1] != BAR_MS:
        return None
    prev = k.c[i - 1]
    cur = k.c[i]
    if prev <= 0.0 or cur <= 0.0:
        return None
    return math.log(cur / prev)


def leader_scale(k: Projection5m, i: int, *, lag_bars: int = 0) -> float | None:
    """Trailing robust scale of the (optionally lagged) leader return series.

    References are the returns at slots ``t(i) - (lag+j)*BAR_MS`` for ``j = 1..288``.
    Every reference must be present; otherwise ``None`` (fail closed).
    """
    base = i - lag_bars
    if base < 0:
        return None
    refs: list[float] = []
    for j in range(1, SHOCK_LOOKBACK_BARS + 1):
        pos = k.index.get(k.t[base] - j * BAR_MS)
        if pos is None:
            return None
        r = log_return(k, pos)
        if r is None:
            return None
        refs.append(abs(r))
    return median(refs)


def evaluate_at_slot(
    leader: Projection5m,
    follower: Projection5m,
    slot_open_ms: int,
    *,
    leader_lag_bars: int = 0,
) -> dict[str, Any]:
    """Frozen ARC-02 feature evaluation at one aligned 5m slot (no outcome information).

    ``leader_lag_bars = 0`` is the PRIMARY rule. ``leader_lag_bars = 288`` is the frozen
    LEADER_CONTROL substitution: the leader's contemporaneous information is replaced by
    a strictly past (24h-old) leader return and the matching trailing scale, while every
    follower execution semantic is untouched.
    """
    out: dict[str, Any] = {
        "symbol": follower.symbol,
        "leader": leader.symbol,
        "bar_open_time_ms": slot_open_ms,
        "leader_lag_bars": leader_lag_bars,
        "shock_lookback_bars": SHOCK_LOOKBACK_BARS,
        "shock_threshold": SHOCK_THRESHOLD,
        "underreaction_ratio": UNDERREACTION_RATIO,
    }
    li = leader.index.get(slot_open_ms)
    if li is None:
        out.update(result=NO_SIGNAL, reason="BAR_ALIGNMENT_FAILURE", emitted=False)
        return out
    out["decision_time_ms"] = max(leader.ct[li], _follower_close(follower, slot_open_ms))

    # ---- leader history: references first (frozen precedence), then the driver bar
    scale = leader_scale(leader, li, lag_bars=leader_lag_bars)
    if scale is None:
        out.update(result=NO_SIGNAL, reason="LEADER_HISTORY_INCOMPLETE", emitted=False)
        return out
    driver_pos = li - leader_lag_bars
    if driver_pos < 0:
        out.update(result=NO_SIGNAL, reason="LEADER_HISTORY_INCOMPLETE", emitted=False)
        return out
    r_btc = log_return(leader, driver_pos)
    if r_btc is None:
        out.update(result=NO_SIGNAL, reason="LEADER_HISTORY_INCOMPLETE", emitted=False)
        return out
    out["leader_return"] = r_btc
    out["leader_scale"] = scale
    if scale == 0.0:
        out.update(result=NO_SIGNAL, reason="LEADER_SCALE_ZERO", emitted=False)
        return out
    z = r_btc / scale
    out["leader_shock_statistic"] = z
    out["leader_shock_abs"] = abs(z)

    # ---- follower response
    fi = follower.index.get(slot_open_ms)
    if fi is None:
        out.update(result=NO_SIGNAL, reason="FOLLOWER_BAR_MISSING", emitted=False)
        return out
    out["decision_time_ms"] = max(leader.ct[li], follower.ct[fi])
    r_f = log_return(follower, fi)
    if r_f is None:
        out.update(result=NO_SIGNAL, reason="FOLLOWER_BAR_MISSING", emitted=False)
        return out
    out["follower_return"] = r_f
    out["follower_response_ratio"] = abs(r_f) / abs(r_btc) if r_btc != 0.0 else None

    if not abs(z) > SHOCK_THRESHOLD:
        out.update(result=NO_SIGNAL, reason="NO_BTC_SHOCK", emitted=False)
        return out
    same_sign = (r_btc > 0.0 and r_f > 0.0) or (r_btc < 0.0 and r_f < 0.0)
    if not same_sign:
        out.update(result=NO_SIGNAL, reason="FOLLOWER_NO_SAME_SIGN_RESPONSE", emitted=False)
        return out
    if not abs(r_f) < UNDERREACTION_RATIO * abs(r_btc):
        out.update(result=NO_SIGNAL, reason="FOLLOWER_NOT_UNDERREACTING", emitted=False)
        return out
    direction = LONG if r_btc > 0.0 else SHORT
    out.update(result=direction, reason=None, emitted=True, direction=direction)
    return out


def _follower_close(follower: Projection5m, slot_open_ms: int) -> int:
    """Follower close time for the slot, or the slot's own close when the bar is absent."""
    fi = follower.index.get(slot_open_ms)
    return follower.ct[fi] if fi is not None else slot_open_ms + BAR_MS - 1


def forward_exit_index(follower: Projection5m, entry_open_ms: int, *, offset_bars: int = 0) -> int | None:
    """Exit bar index for a position anchored at ``entry_open_ms`` (+ optional frozen offset).

    The exit bar is identified by CLOCK ARITHMETIC ONLY: ``entry + (HOLDING_BARS + offset)
    * BAR_MS``. The exit price is never inspected to decide whether to trade.
    """
    target = entry_open_ms + (HOLDING_BARS + offset_bars) * BAR_MS
    return follower.index.get(target)


def entry_index_for_decision(follower: Projection5m, decision_time_ms: int, *, offset_bars: int = 0) -> int | None:
    """First follower bar strictly after the decision instant (+ optional frozen offset)."""
    pos = follower.first_index_strictly_after(decision_time_ms)
    if pos is None:
        return None
    if offset_bars:
        pos += offset_bars
        if pos >= len(follower.t):
            return None
    return pos


def common_causal_window(partitions: dict[str, Projection5m]) -> dict[str, Any]:
    """Exact intersection of the admitted projection coverage across assets."""
    firsts = {s: k.t[0] for s, k in partitions.items()}
    lasts = {s: k.t[-1] for s, k in partitions.items()}
    start = max(firsts.values())
    end = min(lasts.values())
    return {
        "derivation": "INTERSECTION of the admitted ARC-02 projection partitions of all three assets on 5m bar-OPEN times (max of first opens, min of last opens)",
        "start_ms": start,
        "end_ms": end,
        "per_asset_first_open_ms": firsts,
        "per_asset_last_open_ms": lasts,
        "bound_semantics": "CLOSED interval on 5m bar-OPEN times: bar_open_time_ms in [start_ms, end_ms]",
        "window_span_days_inclusive": (end - start + BAR_MS) / DAY_MS,
        "no_observation_outside_window": True,
    }


def partition_fingerprint(partitions: dict[str, Projection5m]) -> dict[str, Any]:
    from trading_bot.research.arc02.arc02_normalize import canonical_json, sha256_bytes

    return {
        "partition_sha256": {s: k.sha256 for s, k in partitions.items()},
        "rows": {s: k.rows for s, k in partitions.items()},
        "aggregate_sha256": sha256_bytes(canonical_json({s: k.sha256 for s, k in sorted(partitions.items())})),
    }


__all__ = [
    "ASSETS",
    "BAR_MS",
    "BOOTSTRAP_RESAMPLES",
    "BOOTSTRAP_SEED",
    "COMMON_WINDOW_SPAN_DAYS",
    "COST_SCENARIOS_BPS",
    "DAY_MS",
    "DECISION_TIMEFRAME",
    "DROPPED_FIELDS",
    "FOLLOWERS",
    "G1_MIN_TOTAL_TRADES",
    "G1_MIN_TRADES_PER_FOLLOWER",
    "G10_MAX_FOLLOWER_SHARE",
    "G10_MAX_MONTH_SHARE",
    "G10_MAX_SINGLE_TRADE_SHARE",
    "G4_MIN_PROFIT_FACTOR",
    "G5_MIN_SHARPE",
    "HOLDING_BARS",
    "HOLDING_MS",
    "LEADER",
    "LEADER_CONTROL_LAG_BARS",
    "LONG",
    "NO_SIGNAL",
    "NO_SIGNAL_PRECEDENCE",
    "NULL_SEED",
    "PARTITION_RELPATH",
    "PERMUTATION_ALPHA",
    "PERMUTATION_DRAWS",
    "PERMUTATION_SEED",
    "PRIMARY_COST_BPS",
    "PROJECTED_FIELDS",
    "Projection5m",
    "SHOCK_LOOKBACK_BARS",
    "SHOCK_MIN_OBS",
    "SHOCK_THRESHOLD",
    "SHORT",
    "TIMING_CONTROL_OFFSET_BARS",
    "UNDERREACTION_RATIO",
    "common_causal_window",
    "entry_index_for_decision",
    "evaluate_at_slot",
    "forward_exit_index",
    "leader_scale",
    "load_partition",
    "log_return",
    "median",
    "partition_fingerprint",
    "resolve_partition_dir",
]
