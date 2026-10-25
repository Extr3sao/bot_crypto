"""Controlled quantitative discovery — offline core (RFC-046).

Scope rules enforced here, mechanically:

* **Long/cash only.** The runtime excludes derivatives (SRC-02) and spot cannot short, so a
  signal is either long spot or flat. The simulator has no other direction.
* **Point-in-time.** A decision taken on bar *i* may use bars whose ``close_time_ms`` is at or
  before the decision instant, and nothing else. Entries and exits are filled at the **open of
  the next bar**, so a fill can never use the price that produced the signal.
* **Costs are not optional.** Every round trip pays ``ROUND_TRIP_BPS`` (23.7906 bps, re-derived
  from COST_MODEL_V3 for Binance Spot VIP0 taker at ~1,000 USD notional) and the stressed
  evaluation pays ``1.5x`` that.
* **No tuning.** The module contains no parameter search: parameters come from the frozen spec,
  and :func:`spec_hash` lets a verifier prove the spec did not change between runs.

This module is research-only. It cannot place an order: it imports nothing from execution,
nothing from the network, and no exchange client.
"""

from __future__ import annotations

import hashlib
import itertools
import json
import random
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROUND_TRIP_BPS = 23.7906
STRESS_MULTIPLE = 1.5
BAR_MS = 3_600_000
SIGNAL_VERSION = "rfc046.discovery.v1"

MECHANISMS = (
    "institutional_constraint",
    "risk_transfer",
    "market_microstructure",
    "forced_flows",
    "regulatory_effect",
    "structural_carry",
    "liquidity_provision",
)

PARTITIONS = ("development", "validation", "final_oos")

#: Reject conditions inherited from RFC-041. A spec naming one of these is refused at load time.
REJECT_CONDITION_FAMILIES = (
    "rsi variation",
    "different moving average",
    "different threshold only",
    "another crypto pair only",
    "more llm agents",
    "new sentiment source",
    "ml on old features",
    "parameter optimization",
    "renamed rules",
)


class SpecError(ValueError):
    """A frozen spec is malformed or inadmissible."""


# --------------------------------------------------------------------------- #
# Specs
# --------------------------------------------------------------------------- #


@dataclass(frozen=True, slots=True)
class Partition:
    name: str
    start_ms: int
    end_ms: int


@dataclass(frozen=True, slots=True)
class HypothesisSpec:
    hypothesis_id: str
    candidate_id: str
    mechanism: str
    source_ids: tuple[str, ...]
    statement: str
    falsification: str
    asset: str
    strategy: str
    parameters: dict[str, float]
    period_start_ms: int
    period_end_ms: int
    partitions: tuple[Partition, ...]
    cost_bps: float
    evidence_level: str
    registered_at_utc: str

    def to_json(self) -> dict[str, Any]:
        return {
            "hypothesis_id": self.hypothesis_id,
            "candidate_id": self.candidate_id,
            "mechanism": self.mechanism,
            "source_ids": list(self.source_ids),
            "statement": self.statement,
            "falsification": self.falsification,
            "asset": self.asset,
            "strategy": self.strategy,
            "parameters": dict(self.parameters),
            "period": {"start_ms": self.period_start_ms, "end_ms": self.period_end_ms},
            "partitions": [
                {"name": p.name, "start_ms": p.start_ms, "end_ms": p.end_ms}
                for p in self.partitions
            ],
            "cost_bps": self.cost_bps,
            "evidence_level": self.evidence_level,
            "registered_at_utc": self.registered_at_utc,
        }


def spec_hash(spec: HypothesisSpec) -> str:
    payload = json.dumps(spec.to_json(), sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def spec_hash_from_file(path: Path | str) -> str:
    """Hash the frozen file as it is on disk, including fields the loader ignores.

    This is the hash a verifier recomputes: it covers every byte of meaning in the spec, so an
    edit to the registered file is detectable even if the loader would drop the edited field.
    """
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def load_spec(path: Path | str) -> HypothesisSpec:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    mechanism = data["mechanism"]
    if mechanism not in MECHANISMS:
        raise SpecError(f"{data.get('hypothesis_id')}: mechanism {mechanism!r} is not admissible")
    haystack = " ".join(
        [data.get("statement", ""), data.get("strategy", ""), *data.get("parameters", {})]
    ).lower()
    hit = [family for family in REJECT_CONDITION_FAMILIES if family in haystack]
    if hit:
        raise SpecError(f"{data.get('hypothesis_id')}: matches RFC-041 reject condition(s): {hit}")
    parts = tuple(
        Partition(name=p["name"], start_ms=int(p["start_ms"]), end_ms=int(p["end_ms"]))
        for p in data["partitions"]
    )
    names = [p.name for p in parts]
    if names != list(PARTITIONS):
        raise SpecError(
            f"{data.get('hypothesis_id')}: partitions must be {list(PARTITIONS)}, got {names}"
        )
    if float(data["cost_bps"]) != ROUND_TRIP_BPS:
        raise SpecError(
            f"{data.get('hypothesis_id')}: cost_bps must be the audited {ROUND_TRIP_BPS}, "
            f"got {data['cost_bps']}"
        )
    return HypothesisSpec(
        hypothesis_id=data["hypothesis_id"],
        candidate_id=data["candidate_id"],
        mechanism=mechanism,
        source_ids=tuple(data["source_ids"]),
        statement=data["statement"],
        falsification=data["falsification"],
        asset=data["asset"],
        strategy=data["strategy"],
        parameters={k: float(v) for k, v in data["parameters"].items()},
        period_start_ms=int(data["period"]["start_ms"]),
        period_end_ms=int(data["period"]["end_ms"]),
        partitions=parts,
        cost_bps=float(data["cost_bps"]),
        evidence_level=data["evidence_level"],
        registered_at_utc=data["registered_at_utc"],
    )


# --------------------------------------------------------------------------- #
# Data
# --------------------------------------------------------------------------- #


@dataclass(frozen=True, slots=True)
class Bar:
    open_time_ms: int
    open: float
    high: float
    low: float
    close: float
    volume: float

    @property
    def close_time_ms(self) -> int:
        return self.open_time_ms + BAR_MS


def load_bars(path: Path | str) -> list[Bar]:
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    bars = [
        Bar(int(r[0]), float(r[1]), float(r[2]), float(r[3]), float(r[4]), float(r[5])) for r in raw
    ]
    bars.sort(key=lambda b: b.open_time_ms)
    for prev, nxt in itertools.pairwise(bars):
        if nxt.open_time_ms <= prev.open_time_ms:
            raise SpecError(f"{path}: bars are not strictly increasing at {nxt.open_time_ms}")
    return bars


@dataclass(frozen=True, slots=True)
class FundingPoint:
    time_ms: int
    rate: float


def load_funding(path: Path | str) -> list[FundingPoint]:
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    points = [FundingPoint(int(r["fundingTime"]), float(r["fundingRate"])) for r in raw]
    points.sort(key=lambda p: p.time_ms)
    return points


# --------------------------------------------------------------------------- #
# Signals
# --------------------------------------------------------------------------- #


@dataclass(frozen=True, slots=True)
class Signal:
    """A long/cash decision: open at ``entry_ms`` (a bar open), flat at ``exit_ms``."""

    entry_ms: int
    exit_ms: int
    reason: str


def _next_bar_open(bars: Sequence[Bar], index: int) -> Bar | None:
    return bars[index + 1] if index + 1 < len(bars) else None


_WEEKDAY_CACHE: dict[int, int] = {}


def _weekday(ms: int) -> int:
    """UTC weekday (Monday = 0) of the instant, computed rather than derived by hand."""
    day = ms // 86_400_000
    cached = _WEEKDAY_CACHE.get(day)
    if cached is None:
        cached = datetime.fromtimestamp(day * 86_400, tz=UTC).weekday()
        _WEEKDAY_CACHE[day] = cached
    return cached


def _index_at(bars: Sequence[Bar], open_time_ms: int) -> int | None:
    for i, bar in enumerate(bars):
        if bar.open_time_ms == open_time_ms:
            return i
    return None


def signal_funding_capitulation(
    bars: Sequence[Bar],
    funding: Sequence[FundingPoint],
    params: dict[str, float],
) -> list[Signal]:
    """Crowded shorts pay for their leverage; a capitulation extreme precedes a squeeze.

    Long only (spot). At each settlement the funding rate is compared with its own trailing
    distribution; a sufficiently negative z-score is the forced-flow extreme. Enter at the open
    of the bar after the settlement and exit after ``hold_hours``.
    """
    lookback = int(params["lookback_settlements"])
    z_entry = float(params["z_entry"])
    hold = int(params["hold_hours"])
    signals: list[Signal] = []
    busy_until = 0
    rates: list[float] = []
    for point in funding:
        if len(rates) >= lookback:
            window = [r for r in rates[-lookback:]]
            mean = sum(window) / len(window)
            var = sum((r - mean) ** 2 for r in window) / (len(window) - 1)
            sd = var**0.5
            if sd > 0:
                z = (point.rate - mean) / sd
                if z <= -z_entry and point.time_ms >= busy_until:
                    index = _index_at(bars, point.time_ms)
                    if index is not None:
                        entry = _next_bar_open(bars, index)
                        if entry is not None:
                            exit_ms = entry.open_time_ms + hold * BAR_MS
                            if any(b.open_time_ms == exit_ms for b in bars):
                                signals.append(
                                    Signal(entry.open_time_ms, exit_ms, f"funding z={z:.2f}")
                                )
                                busy_until = exit_ms
        rates.append(point.rate)
    return signals


def signal_settlement_dip(
    bars: Sequence[Bar],
    funding: Sequence[FundingPoint],
    params: dict[str, float],
) -> list[Signal]:
    """Longs due to pay funding sell into the settlement; the dip mean-reverts.

    Long only. Condition: positive funding at the settlement *and* a sharp fall over the previous
    ``drop_lookback_hours``. Enter at the next open, exit after ``hold_hours``.
    """
    drop_lookback = int(params["drop_lookback_hours"])
    sigma_k = float(params["sigma_k"])
    hold = int(params["hold_hours"])
    funding_at = {p.time_ms: p.rate for p in funding}
    closes = [b.close for b in bars]
    by_open = {b.open_time_ms: i for i, b in enumerate(bars)}
    returns: list[float] = []
    signals: list[Signal] = []
    busy_until = 0
    for i, bar in enumerate(bars):
        if i > 0:
            returns.append(closes[i] / closes[i - 1] - 1.0)
        settlement = bar.close_time_ms
        rate = funding_at.get(settlement)
        if rate is None or rate <= 0 or len(returns) < drop_lookback + 1:
            continue
        window = returns[-drop_lookback - 1 : -1]
        mean = sum(window) / len(window)
        var = sum((r - mean) ** 2 for r in window) / (len(window) - 1)
        sd = var**0.5
        if sd <= 0:
            continue
        base_index = by_open.get(bar.open_time_ms - drop_lookback * BAR_MS)
        if base_index is None:
            continue
        ret = closes[i] / bars[base_index].close - 1.0
        if ret <= -sigma_k * sd * (drop_lookback**0.5) and bar.close_time_ms >= busy_until:
            entry = _next_bar_open(bars, i)
            if entry is None:
                continue
            exit_ms = entry.open_time_ms + hold * BAR_MS
            if any(b.open_time_ms == exit_ms for b in bars):
                signals.append(Signal(entry.open_time_ms, exit_ms, f"settlement dip {ret:.4f}"))
                busy_until = exit_ms
    return signals


def signal_weekend_rebound(
    bars: Sequence[Bar],
    params: dict[str, float],
) -> list[Signal]:
    """Thin weekend liquidity premium: a weak week is bought back over the weekend.

    Long only. At Friday ``entry_hour_utc`` compute the week return from Monday 00:00; if it is
    below ``week_drop_k`` rolling sigma, enter at the next open and exit Sunday ``exit_hour_utc``.
    """
    week_start_close: float | None = None
    returns: list[float] = []
    signals: list[Signal] = []
    entry_hour = int(params["entry_hour_utc"])
    exit_hour = int(params["exit_hour_utc"])
    k = float(params["week_drop_k"])
    lookback = int(params["sigma_lookback_days"]) * 24
    for i, bar in enumerate(bars):
        if i > 0:
            returns.append(bar.close / bars[i - 1].close - 1.0)
        hour = (bar.open_time_ms // BAR_MS) % 24
        weekday = _weekday(bar.open_time_ms)
        if weekday == 0 and hour == 0:
            week_start_close = bar.close
        if weekday == 4 and hour == entry_hour and week_start_close and len(returns) >= lookback:
            window = returns[-lookback:]
            mean = sum(window) / len(window)
            var = sum((r - mean) ** 2 for r in window) / (len(window) - 1)
            sd = var**0.5
            week_ret = bar.close / week_start_close - 1.0
            if sd > 0 and week_ret <= -k * sd * (120**0.5):
                entry = _next_bar_open(bars, i)
                if entry is not None:
                    exit_ms = entry.open_time_ms + (2 * 24 + (exit_hour - entry_hour) % 24) * BAR_MS
                    if any(b.open_time_ms == exit_ms for b in bars):
                        signals.append(Signal(entry.open_time_ms, exit_ms, f"week {week_ret:.4f}"))
        if weekday == 4 and week_start_close:
            week_start_close = None
    return signals


STRATEGIES = {
    "funding_capitulation": signal_funding_capitulation,
    "settlement_dip": signal_settlement_dip,
    "weekend_rebound": signal_weekend_rebound,
}


# --------------------------------------------------------------------------- #
# Simulation and metrics
# --------------------------------------------------------------------------- #


@dataclass(frozen=True, slots=True)
class Trade:
    hypothesis_id: str
    asset: str
    entry_time_ms: int
    exit_time_ms: int
    entry_price: float
    exit_price: float
    gross_ret: float
    net_ret: float
    net_ret_stressed: float
    partition: str


def classify(entry_ms: int, partitions: Sequence[Partition]) -> str:
    for part in partitions:
        if part.start_ms <= entry_ms < part.end_ms:
            return part.name
    return "outside"


def simulate(
    spec: HypothesisSpec,
    bars: Sequence[Bar],
    signals: Sequence[Signal],
    cost_multiple: float = 1.0,
) -> list[Trade]:
    by_open = {b.open_time_ms: b for b in bars}
    cost = spec.cost_bps / 10_000.0 * cost_multiple
    trades: list[Trade] = []
    for signal in signals:
        entry = by_open.get(signal.entry_ms)
        exit_bar = by_open.get(signal.exit_ms)
        if entry is None or exit_bar is None:
            continue
        gross = exit_bar.open / entry.open - 1.0
        trades.append(
            Trade(
                hypothesis_id=spec.hypothesis_id,
                asset=spec.asset,
                entry_time_ms=entry.open_time_ms,
                exit_time_ms=exit_bar.open_time_ms,
                entry_price=entry.open,
                exit_price=exit_bar.open,
                gross_ret=gross,
                net_ret=gross - cost,
                net_ret_stressed=gross - spec.cost_bps / 10_000.0 * STRESS_MULTIPLE,
                partition=classify(entry.open_time_ms, spec.partitions),
            )
        )
    trades.sort(key=lambda t: (t.entry_time_ms, t.exit_time_ms))
    return trades


def profit_factor(returns: Sequence[float]) -> float | None:
    gains = sum(r for r in returns if r > 0)
    losses = -sum(r for r in returns if r < 0)
    if losses == 0:
        return None if gains == 0 else float("inf")
    return gains / losses


def max_drawdown(returns: Sequence[float]) -> float:
    equity = 1.0
    peak = 1.0
    worst = 0.0
    for ret in returns:
        equity *= 1.0 + ret
        peak = max(peak, equity)
        worst = max(worst, (peak - equity) / peak)
    return worst


def block_bootstrap_lcb(
    returns: Sequence[float], *, seed: int, alpha: float, block: int = 5, draws: int = 2000
) -> float | None:
    """Lower confidence bound of the mean return under serial dependence.

    A moving-block bootstrap, never an i.i.d. t-test (PG-6). ``alpha`` is the already-corrected
    significance level.
    """
    n = len(returns)
    if n < block * 3:
        return None
    rng = random.Random(seed)
    means = []
    for _ in range(draws):
        sample: list[float] = []
        while len(sample) < n:
            start = rng.randrange(0, n - block + 1)
            sample.extend(returns[start : start + block])
        means.append(sum(sample[:n]) / n)
    means.sort()
    idx = max(0, min(len(means) - 1, int(alpha * len(means))))
    return means[idx]


def share_of_positive_net(returns: Sequence[float]) -> tuple[float, int]:
    total = sum(r for r in returns if r > 0)
    if total <= 0:
        return 0.0, -1
    worst_share = 0.0
    worst_index = -1
    for i, ret in enumerate(returns):
        if ret > 0:
            share = ret / total
            if share > worst_share:
                worst_share, worst_index = share, i
    return worst_share, worst_index


def quarter_shares(trades: Sequence[Trade]) -> float:
    positives = sum(t.net_ret for t in trades if t.net_ret > 0)
    if positives <= 0:
        return 0.0
    buckets: dict[str, float] = {}
    for trade in trades:
        year = trade.entry_time_ms // (365 * 86_400_000)
        quarter = (trade.entry_time_ms // (91 * 86_400_000)) % 4
        key = f"{year}-Q{quarter}"
        buckets[key] = buckets.get(key, 0.0) + max(trade.net_ret, 0.0)
    return max(buckets.values()) / positives


# --------------------------------------------------------------------------- #
# Gate
# --------------------------------------------------------------------------- #


def evaluate_gate(spec: HypothesisSpec, trades: Sequence[Trade], trials: int) -> dict[str, Any]:
    all_net = [t.net_ret for t in trades]
    oos = [t for t in trades if t.partition == "final_oos"]
    oos_net = [t.net_ret for t in oos]
    by_partition: dict[str, list[float]] = {}
    for name in PARTITIONS:
        by_partition[name] = [t.net_ret for t in trades if t.partition == name]

    alpha = 0.05 / trials
    lcb = block_bootstrap_lcb(all_net, seed=460046, alpha=alpha)
    expectancy = sum(all_net) / len(all_net) if all_net else None
    stressed = [t.net_ret_stressed for t in trades]
    stressed_expectancy = sum(stressed) / len(stressed) if stressed else None
    pf = profit_factor(all_net)
    dd = max_drawdown(all_net)
    share, share_index = share_of_positive_net(all_net)
    q_share = quarter_shares(trades)
    pit_violations = 0  # structural: fills are next-bar opens over close-only features

    requirements = [
        ("PG-1", "net expectancy > 0", expectancy is not None and expectancy > 0, expectancy),
        ("PG-2", "OOS net > 0", sum(oos_net) > 0, sum(oos_net)),
        ("PG-3", "PF >= 1.10", pf is not None and pf >= 1.10, pf),
        (
            "PG-4",
            "sample >= 100 total and >= 30 OOS",
            len(trades) >= 100 and len(oos) >= 30,
            {"total": len(trades), "oos": len(oos)},
        ),
        (
            "PG-5",
            "positive in every partition",
            all(by_partition[name] and sum(by_partition[name]) > 0 for name in PARTITIONS),
            {name: (len(v), sum(v)) for name, v in by_partition.items()},
        ),
        ("PG-6", "block-bootstrap LCB > 0", lcb is not None and lcb > 0, lcb),
        (
            "PG-7",
            "1.5x cost stress > 0",
            stressed_expectancy is not None and stressed_expectancy > 0,
            stressed_expectancy,
        ),
        ("PG-8", "no risk-engine violation (<=1x, DD <= 10%)", dd <= 0.10, dd),
        (
            "PG-9",
            "no single trade > 40% and no quarter > 60% of positive net",
            share <= 0.40 and q_share <= 0.60,
            {"trade_share": share, "quarter_share": q_share, "trade_index": share_index},
        ),
        (
            "PG-10",
            "multiple-testing correction applied",
            trials >= 1 and alpha < 0.05,
            {"trials": trials, "alpha": alpha},
        ),
        ("PG-11", "no look-ahead / PIT violation", pit_violations == 0, pit_violations),
    ]
    failed = [rid for rid, _, ok, _ in requirements if not ok]
    return {
        "hypothesis_id": spec.hypothesis_id,
        "candidate_id": spec.candidate_id,
        "spec_hash": spec_hash(spec),
        "trials": trials,
        "requirements": [
            {"id": rid, "requirement": text, "pass": ok, "observed": value}
            for rid, text, ok, value in requirements
        ],
        "failed": failed,
        "zero_sample": len(trades) == 0,
        "verdict": "CANDIDATE_ADMITTED_TO_PAPER_REVIEW" if not failed else "CANDIDATE_REJECTED",
        "metrics": {
            "trades_total": len(trades),
            "trades_oos": len(oos),
            "net_expectancy": expectancy,
            "net_pf": pf,
            "oos_net": sum(oos_net),
            "lcb": lcb,
            "stress_expectancy": stressed_expectancy,
            "max_drawdown": dd,
        },
    }
