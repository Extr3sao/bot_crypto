"""Measured round-trip cost from the ST-6 observation tape.

Every number below carries one of the repository's existing knowledge classes — ``KNOWN`` for a
contractual fact, ``OBSERVED`` for something measured, ``ESTIMATED`` for something derived through
a stated transformation, ``ASSUMED`` for a constant nobody measured. A total is never better than
its weakest component, and :func:`measure_round_trip` computes that weakest class rather than
letting a caller assume the total is measured.

Three rules keep this honest:

* **The spread is one crossing, not two.** A round trip pays half the quoted spread on entry and
  half on exit, so its spread cost is the full quoted ``spread_bps``. Doubling it would inflate the
  toll by the amount that decides several of this repository's verdicts.
* **A size that was not walked is not a measurement.** ST-6 walked 200 USDT in every window. At
  500 USDT the only defensible statement is a lower bound (impact >= 0), and that bound is labelled
  ``ESTIMATED`` with the reason, never published as ``MEASURED``.
* **No observation, no number.** An empty tape returns ``INSUFFICIENT_EVIDENCE``; it does not
  return zero, because a cost of zero is a claim about the venue.
"""

from __future__ import annotations

import json
import math
import statistics
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..microstructure.cost_model_v3 import VENUE_SPECS

__all__ = [
    "COST_CONFIRMED",
    "COST_LOWER",
    "DEFAULT_TAKER_FEE_BPS",
    "FEE_SCENARIO_ID",
    "INSUFFICIENT_EVIDENCE",
    "MEASURED",
    "NOT_A_DECISION",
    "SIZE_NOT_WALKED",
    "AssetMeasurement",
    "CostComponent",
    "MeasuredRoundTrip",
    "Quote",
    "evaluate_cost_question",
    "load_st6_quotes",
    "measure_asset",
    "measure_round_trip",
    "percentile",
    "weakest_class",
]

#: The fee the runtime would actually pay, read from the shared venue registry rather than typed
#: here a second time. VIP0 spot on Binance is 10 bps, identical maker and taker.
FEE_SCENARIO_ID = "BINANCE_SPOT_STANDARD_TAKER"
DEFAULT_TAKER_FEE_BPS = VENUE_SPECS[FEE_SCENARIO_ID].taker_fee_bps
FEE_SOURCE_ID = VENUE_SPECS[FEE_SCENARIO_ID].fee_source_id

MEASURED = "MEASURED"
SIZE_NOT_WALKED = "DECLARED_SIZE_NOT_WALKED"
INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"
NOT_A_DECISION = "NOT_A_DECISION"
COST_LOWER = "COST_LOWER"
COST_CONFIRMED = "COST_CONFIRMED"

#: Weakest-wins ordering. ``KNOWN`` is a contractual fact, ``OBSERVED`` a measurement, ``ESTIMATED``
#: a derivation, ``ASSUMED`` a declared constant with no evidence behind it.
_RANK: dict[str, int] = {"KNOWN": 0, "OBSERVED": 1, "ESTIMATED": 2, "ASSUMED": 3}

#: The thresholds `docs/agentic/NEXT_EXPERIMENT_PROPOSAL.md` §3 froze on 2026-10-21, before any
#: measurement existed. Reproduced here as defaults, never adjusted after the fact.
FROZEN_COST_LOWER_BPS = 20.0
FROZEN_MODEL_BPS = 24.786
FROZEN_MODEL_SOL_BPS = 27.310
FROZEN_MIN_DAYS = 60


def weakest_class(classes: Iterable[str]) -> str:
    """The least trustworthy knowledge class present."""
    worst = "KNOWN"
    for value in classes:
        if value not in _RANK:
            raise ValueError(f"unknown knowledge class {value!r}")
        if _RANK[value] > _RANK[worst]:
            worst = value
    return worst


def percentile(values: Sequence[float], q: float) -> float:
    """Nearest-rank percentile. No interpolation, so the answer is always a measured value."""
    if not values:
        raise ValueError("percentile of no values")
    if not 0.0 <= q <= 100.0:
        raise ValueError("q must be in [0, 100]")
    ordered = sorted(values)
    if q == 0.0:
        return ordered[0]
    index = math.ceil(q / 100.0 * len(ordered)) - 1
    return ordered[min(max(index, 0), len(ordered) - 1)]


@dataclass(frozen=True, slots=True)
class CostComponent:
    """One additive term, with the evidence behind it."""

    name: str
    bps: float | None
    knowledge: str
    source_id: str
    note: str = ""

    def __post_init__(self) -> None:
        if self.knowledge not in _RANK:
            raise ValueError(f"unknown knowledge class {self.knowledge!r}")
        if self.bps is not None and self.bps < 0.0:
            raise ValueError(f"component {self.name!r} is negative ({self.bps})")

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "bps": None if self.bps is None else round(self.bps, 6),
            "knowledge": self.knowledge,
            "source_id": self.source_id,
            "note": self.note,
        }


@dataclass(frozen=True, slots=True)
class Quote:
    """One stored ST-6 observation, already rejected/stale-filtered by the caller."""

    asset: str
    window_id: str
    day: str
    observed_at_utc: str
    bid: float
    ask: float
    spread_bps: float
    impact_buy_bps: float | None
    impact_sell_bps: float | None
    impact_size_usdt: float | None
    raw_sha256: str | None
    rejected: bool = False
    stale: bool = False
    book_age_ms: float | None = None

    def __post_init__(self) -> None:
        if not self.asset:
            raise ValueError("quote without an asset")
        if self.ask < self.bid and not (self.rejected or self.stale):
            # A crossed book is not a wide spread; it is a capture defect, and averaging it in
            # would move a median in a direction nobody can explain later. The loader marks such a
            # row rejected instead of dropping it, so the count of defects stays visible.
            raise ValueError(f"{self.asset} {self.window_id}: ask {self.ask} < bid {self.bid}")

    @property
    def usable(self) -> bool:
        return not self.rejected and not self.stale


@dataclass(frozen=True, slots=True)
class MeasuredRoundTrip:
    """The cost of one round trip under stated execution assumptions."""

    asset: str
    size_usdt: float
    components: tuple[CostComponent, ...]
    total_bps: float | None
    total_knowledge: str
    observations: int
    status: str
    size_status: str
    notes: tuple[str, ...] = ()

    @property
    def measurable(self) -> bool:
        return self.total_bps is not None

    def as_dict(self) -> dict[str, Any]:
        return {
            "asset": self.asset,
            "size_usdt": self.size_usdt,
            "components": [component.as_dict() for component in self.components],
            "total_bps": None if self.total_bps is None else round(self.total_bps, 6),
            "total_knowledge": self.total_knowledge,
            "observations": self.observations,
            "status": self.status,
            "size_status": self.size_status,
            "notes": list(self.notes),
        }


def load_st6_quotes(path: Path) -> tuple[Quote, ...]:
    """Read ``ST6_OBSERVATIONS.jsonl`` into quotes, failing closed on a malformed line."""
    path = Path(path)
    if not path.is_file():
        raise FileNotFoundError(path)
    quotes: list[Quote] = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError as error:
            raise ValueError(f"{path}:{number} is not JSON: {error}") from error
        if not isinstance(record, dict):
            raise ValueError(f"{path}:{number} is not an object")
        impact = record.get("impact") or {}
        market = record.get("market") or {}
        raw = record.get("raw") or {}
        bid = float(record["bid"])
        ask = float(record["ask"])
        quotes.append(
            Quote(
                asset=str(record.get("asset")),
                window_id=str(record.get("window_id")),
                day=str(market.get("day") or str(record.get("observed_at_utc"))[:10]),
                observed_at_utc=str(record.get("observed_at_utc")),
                bid=bid,
                ask=ask,
                spread_bps=float(record["spread_bps"]),
                impact_buy_bps=_opt_float(impact.get("buy_bps")),
                impact_sell_bps=_opt_float(impact.get("sell_bps")),
                impact_size_usdt=_opt_float(impact.get("size_usdt")),
                raw_sha256=raw.get("uncompressed_sha256") or raw.get("compressed_sha256"),
                rejected=bool(record.get("rejected", False)) or ask < bid,
                stale=bool(record.get("stale", False)),
                book_age_ms=_opt_float(record.get("book_age_ms")),
            )
        )
    return tuple(quotes)


def _opt_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def measure_round_trip(
    quotes: Sequence[Quote],
    *,
    asset: str,
    size_usdt: float,
    taker_fee_bps: float = DEFAULT_TAKER_FEE_BPS,
    fee_source_id: str = FEE_SOURCE_ID,
) -> MeasuredRoundTrip:
    """Measure one asset's round-trip cost, or say why it cannot be measured.

    ``size_usdt`` is the notional the strategy would trade. Impact is only usable when the tape
    walked that same notional; otherwise the total becomes an explicitly-labelled lower bound.
    """
    if size_usdt <= 0.0:
        raise ValueError("size_usdt must be > 0")
    if taker_fee_bps < 0.0:
        raise ValueError("taker_fee_bps must be >= 0")
    usable = [quote for quote in quotes if quote.asset == asset and quote.usable]
    if not usable:
        return MeasuredRoundTrip(
            asset=asset,
            size_usdt=size_usdt,
            components=(),
            total_bps=None,
            total_knowledge="ASSUMED",
            observations=0,
            status=INSUFFICIENT_EVIDENCE,
            size_status="NO_OBSERVATION",
            notes=("no usable quote for this asset; a cost of zero would be a claim, not a measurement",),
        )

    spread = statistics.median(quote.spread_bps for quote in usable)
    components = [
        CostComponent(
            name="fee_round_trip",
            bps=2.0 * taker_fee_bps,
            knowledge="KNOWN",
            source_id=fee_source_id,
            note=f"venue schedule, {taker_fee_bps} bps per side, charged on entry and exit",
        ),
        CostComponent(
            name="spread_crossed",
            bps=spread,
            knowledge="OBSERVED",
            source_id=f"ST6_OBSERVATIONS median over {len(usable)} windows",
            note="half the quoted spread on entry plus half on exit is one full spread",
        ),
    ]

    walked = [quote for quote in usable if quote.impact_size_usdt == size_usdt]
    complete = [
        quote
        for quote in walked
        if quote.impact_buy_bps is not None and quote.impact_sell_bps is not None
    ]
    notes: list[str] = []
    if complete:
        impact = statistics.median(
            (quote.impact_buy_bps or 0.0) + (quote.impact_sell_bps or 0.0) for quote in complete
        )
        components.append(
            CostComponent(
                name="depth_impact_round_trip",
                bps=impact,
                knowledge="OBSERVED",
                source_id=f"ST6_OBSERVATIONS depth walk at {size_usdt:g} USDT over {len(complete)} windows",
                note="buy-side plus sell-side walk of the recorded book",
            )
        )
        total = sum(component.bps or 0.0 for component in components)
        status = MEASURED
        size_status = "OBSERVED_AT_DECLARED_SIZE"
    else:
        sizes = sorted({quote.impact_size_usdt for quote in usable if quote.impact_size_usdt})
        components.append(
            CostComponent(
                name="depth_impact_round_trip",
                bps=None,
                knowledge="ASSUMED",
                source_id="not measured",
                note=(
                    f"the tape walked {sizes or 'no size'} USDT, not {size_usdt:g}; depth is not "
                    "linear in size, so scaling would invent the number"
                ),
            )
        )
        total = sum(component.bps or 0.0 for component in components)
        status = SIZE_NOT_WALKED
        size_status = "DECLARED_SIZE_NOT_WALKED"
        notes.append(
            "total is a LOWER BOUND: impact is non-negative, so the true round trip is at least "
            "fee + spread, and by how much is unmeasured at this size"
        )

    return MeasuredRoundTrip(
        asset=asset,
        size_usdt=size_usdt,
        components=tuple(components),
        total_bps=total,
        total_knowledge=weakest_class(
            component.knowledge for component in components if component.bps is not None
        ),
        observations=len(usable),
        status=status,
        size_status=size_status,
        notes=tuple(notes),
    )


@dataclass(frozen=True, slots=True)
class AssetMeasurement:
    """One asset's measured distribution and the verdict vocabulary attached to it."""

    asset: str
    size_usdt: float
    observations: int
    days: int
    median_bps: float
    p10_bps: float
    p90_bps: float
    worst_bps: float
    knowledge: str
    size_status: str
    status: str
    detail: MeasuredRoundTrip

    def as_dict(self) -> dict[str, Any]:
        return {
            "asset": self.asset,
            "size_usdt": self.size_usdt,
            "observations": self.observations,
            "distinct_days": self.days,
            "median_bps": round(self.median_bps, 6),
            "p10_bps": round(self.p10_bps, 6),
            "p90_bps": round(self.p90_bps, 6),
            "worst_bps": round(self.worst_bps, 6),
            "knowledge": self.knowledge,
            "size_status": self.size_status,
            "status": self.status,
            "components": self.detail.as_dict()["components"],
        }


def measure_asset(
    quotes: Sequence[Quote], *, asset: str, size_usdt: float, taker_fee_bps: float = DEFAULT_TAKER_FEE_BPS
) -> AssetMeasurement:
    """Per-window distribution of the measured round trip, not just its median."""
    detail = measure_round_trip(quotes, asset=asset, size_usdt=size_usdt, taker_fee_bps=taker_fee_bps)
    usable = [quote for quote in quotes if quote.asset == asset and quote.usable]
    spread_component = next((c.bps for c in detail.components if c.name == "spread_crossed"), None)
    impact_component = next(
        (c.bps for c in detail.components if c.name == "depth_impact_round_trip"), None
    )
    per_window = [
        quote.spread_bps + 2.0 * taker_fee_bps + (impact_component or 0.0)
        for quote in usable
        if spread_component is not None
    ]
    if not per_window:
        raise ValueError(f"no usable observations for {asset}")
    return AssetMeasurement(
        asset=asset,
        size_usdt=size_usdt,
        observations=detail.observations,
        days=len({quote.day for quote in usable}),
        median_bps=percentile(per_window, 50.0),
        p10_bps=percentile(per_window, 10.0),
        p90_bps=percentile(per_window, 90.0),
        worst_bps=percentile(per_window, 100.0),
        knowledge=detail.total_knowledge,
        size_status=detail.size_status,
        status=detail.status,
        detail=detail,
    )


def evaluate_cost_question(
    measurements: Mapping[str, AssetMeasurement],
    *,
    observed_days: int,
    coverage: float,
    reference_bps: Mapping[str, float] | None = None,
) -> dict[str, Any]:
    """Apply EXP-004A's frozen rule to a set of measurements, and refuse to promote anything.

    The rule is transcribed, not chosen: `NEXT_EXPERIMENT_PROPOSAL.md` §3 fixed it on 2026-10-21,
    before a single quote in this report existed. It can return ``INSUFFICIENT_EVIDENCE`` — and does,
    today — but it can never return a strategy, a paper run or an authorisation.
    """
    reference = dict(reference_bps or {})
    assets = sorted(measurements)
    if observed_days < FROZEN_MIN_DAYS or coverage < 0.90 or not assets or any(row.status != MEASURED for row in measurements.values()):
        outcome = INSUFFICIENT_EVIDENCE
    elif all(row.median_bps <= FROZEN_COST_LOWER_BPS for row in measurements.values()) and all(
        row.p90_bps <= reference.get(row.asset, FROZEN_MODEL_SOL_BPS) for row in measurements.values()
    ):
        outcome = COST_LOWER
    elif any(row.median_bps > reference.get(row.asset, FROZEN_MODEL_BPS) for row in measurements.values()):
        outcome = COST_CONFIRMED
    else:
        outcome = NOT_A_DECISION
    return {
        "outcome": outcome,
        "frozen_rule": {
            "cost_lower_bps": FROZEN_COST_LOWER_BPS,
            "model_btc_eth_bps": FROZEN_MODEL_BPS,
            "model_sol_bps": FROZEN_MODEL_SOL_BPS,
            "min_observed_days": FROZEN_MIN_DAYS,
            "min_coverage": 0.90,
            "source": "docs/agentic/NEXT_EXPERIMENT_PROPOSAL.md §3, frozen 2026-10-21",
        },
        "observed_days": observed_days,
        "coverage": coverage,
        "assets": assets,
        "median_bps": {asset: round(row.median_bps, 6) for asset, row in measurements.items()},
        "delta_vs_model_bps": {
            asset: round(row.median_bps - reference[asset], 6)
            for asset, row in measurements.items()
            if asset in reference
        },
        "authorises": "nothing",
        "economic_executions": 0,
        "live_orders": 0,
        "reading": (
            f"{outcome}: the rule cannot fire on this sample, which is a statement about the "
            "sample rather than about the venue"
            if outcome == INSUFFICIENT_EVIDENCE
            else f"{outcome}: the rule fired, and it authorises nothing beyond a re-frozen toll"
        ),
    }
