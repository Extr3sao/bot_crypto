"""RFC-048V independent falsification oracle — ``BUILDER != FALSIFIER``.

This module tries to PROVE that a decision emitted by the futures risk engine is
wrong. It shares no arithmetic with ``trading_bot.risk.futures``: it reads the
same raw venue fixtures and re-derives every number the safety case depends on,
using its own formulas and its own (documented) tolerances.

Its definitions are deliberately narrower than the builder's: the oracle only
refuses when an RFC-048 §04 invariant is provably violated, so a "false
approval" reported here is a counterexample, not a style disagreement.

Invariants re-derived here (name → meaning)::

    I1_APPROVED_RISK_LE_BUDGET      modelled worst loss <= declared risk budget
    I2_MARGIN_LE_AVAILABLE          required isolated margin <= free margin
    I3_NOTIONAL_LE_MAX_ALLOWED      approved notional <= requested and <= caps
    I4_DATA_ORDER                   data time <= decision time, age inside policy
    I5_UNKNOWN_CRITICAL_INPUT       unknown cost/margin/mark => not approved
    I6_UNSUPPORTED_CONTRACT         a refused contract type is never approved
    I7_LIQUIDATION_KNOWN_AND_SAFE   liquidation known, buffer ok, not before stop
    I8_LIVE_ROUTE_BLOCKED           a live-route request is refused
    I9_NO_ORDER_AUTHORISED          no decision authorises an order, ever
    I10_ROUNDING_REDUCES            the quantity step never increases risk

The numeric core (step 1..7 below) is also exported so the driver can compare
the builder's numbers with an independently computed second opinion:

1. cost worst case: fees + spread + slippage + book impact + adverse funding
2. risk-bounded sizing with floor-to-step and the requested-notional clip
3. leverage = min(requested, policy cap, venue bracket ceiling)
4. initial / maintenance margin from the venue's own bracket ladder
5. liquidation price by NUMERIC ROOT of the venue's margin condition
6. portfolio ceilings (gross, net, concentration, free margin, utilisation)
7. data validity: timestamps, mark, provider, finite numbers

    uv run python scripts/rfc048v_falsify.py
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

__all__ = [
    "FALSIFIER_VERSION",
    "INVARIANTS",
    "Comparison",
    "OracleFixtures",
    "OracleScenario",
    "OracleVerdict",
    "compare_decision",
    "independent_liquidation_price",
    "oracle_verdict",
]

FALSIFIER_VERSION = "RFC048V-FALSIFIER-v1"

INVARIANTS = (
    "I1_APPROVED_RISK_LE_BUDGET",
    "I2_MARGIN_LE_AVAILABLE",
    "I3_NOTIONAL_LE_MAX_ALLOWED",
    "I4_DATA_ORDER",
    "I5_UNKNOWN_CRITICAL_INPUT",
    "I6_UNSUPPORTED_CONTRACT",
    "I7_LIQUIDATION_KNOWN_AND_SAFE",
    "I8_LIVE_ROUTE_BLOCKED",
    "I9_NO_ORDER_AUTHORISED",
    "I10_ROUNDING_REDUCES",
)

#: Independent money/price tolerances. The oracle must not become a copy of the
#: builder, so those are absolute (not relative to builder output) and small.
MONEY_TOL = 1e-6
PRICE_TOL = 1e-4
REL_TOL = 1e-9

#: Default experimental policy, re-declared here on purpose: the oracle needs
#: its own copy so a builder-side policy edit cannot move the falsifier's bar.
DEFAULT_POLICY: dict[str, float] = {
    "risk_budget_pct": 0.01,
    "max_leverage": 5.0,
    "min_liquidation_buffer_bps": 50.0,
    "gap_reserve_pct": 0.002,
    "stress_slippage_bps": 5.0,
    "slippage_bps": 1.0,
    "max_gross_exposure_pct": 1.0,
    "max_net_exposure_pct": 1.0,
    "max_concentration_pct": 0.6,
    "max_margin_utilization_pct": 0.5,
    "max_positions": 3,
    "max_data_age_ms": 5 * 60 * 1000,
    "min_stop_distance_bps": 5.0,
    "max_drawdown_pct": 5.0,
    "max_daily_loss_pct": 1.0,
    "max_consecutive_losses": 3,
}


def _finite(value: Any) -> bool:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    return math.isfinite(float(value))


def _f(value: Any, default: float = 0.0) -> float:
    return float(value) if _finite(value) else default


# ---------------------------------------------------------------------------
# fixtures
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class OracleFixtures:
    """Raw inputs, read from disk by the oracle itself."""

    instruments: dict[str, dict[str, Any]]
    funding: dict[str, Any]
    snapshot: dict[str, Any]

    @classmethod
    def load(cls, data_dir: Path) -> OracleFixtures:
        instruments_payload = json.loads(
            (data_dir / "INSTRUMENTS.json").read_text(encoding="utf-8")
        )
        return cls(
            instruments={
                row["instrument_id"]: dict(row) for row in instruments_payload["instruments"]
            },
            funding=json.loads((data_dir / "FUNDING_HISTORY.json").read_text(encoding="utf-8")),
            snapshot=json.loads((data_dir / "MARKET_SNAPSHOT.json").read_text(encoding="utf-8")),
        )


# ---------------------------------------------------------------------------
# scenario / verdict
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class OracleScenario:
    """Everything the oracle and the engine are given, in plain values."""

    scenario_id: str
    instrument_id: str
    direction: str
    entry_price: float
    stop_price: float | None
    mark_price: float | None
    requested_notional: float
    requested_leverage: float
    horizon_minutes: float
    data_timestamp_ms: int
    decision_timestamp_ms: int
    equity: float
    free_margin: float
    reserved_margin: float = 0.0
    daily_pnl: float = 0.0
    drawdown_pct: float = 0.0
    consecutive_losses: int = 0
    spread_bps: float | None = None
    depth: dict[str, Any] | None = None
    funding_observations: tuple[dict[str, Any], ...] = ()
    stress: tuple[dict[str, Any], ...] = ()
    policy: dict[str, float] = field(default_factory=lambda: dict(DEFAULT_POLICY))
    live_route_requested: bool = False
    kind: str = "generated"
    #: The exact contract the engine priced against (``InstrumentSpec.to_dict``).
    #: Data, not arithmetic: the oracle still derives every number itself.
    effective_spec: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "scenario_id": self.scenario_id,
            "kind": self.kind,
            "instrument_id": self.instrument_id,
            "direction": self.direction,
            "entry_price": self.entry_price,
            "stop_price": self.stop_price,
            "mark_price": self.mark_price,
            "requested_notional": self.requested_notional,
            "requested_leverage": self.requested_leverage,
            "horizon_minutes": self.horizon_minutes,
            "data_timestamp_ms": self.data_timestamp_ms,
            "decision_timestamp_ms": self.decision_timestamp_ms,
            "equity": self.equity,
            "free_margin": self.free_margin,
            "reserved_margin": self.reserved_margin,
            "daily_pnl": self.daily_pnl,
            "drawdown_pct": self.drawdown_pct,
            "consecutive_losses": self.consecutive_losses,
            "spread_bps": self.spread_bps,
            "depth_levels": {
                "bids": len((self.depth or {}).get("bids") or []),
                "asks": len((self.depth or {}).get("asks") or []),
            },
            "funding_observations": len(self.funding_observations),
            "stress": [dict(row) for row in self.stress],
            "live_route_requested": self.live_route_requested,
        }


@dataclass(frozen=True, slots=True)
class OracleVerdict:
    """What the independent model says, plus the numbers behind it."""

    expected: str  # "APPROVE_OR_REDUCE" | "REFUSE"
    refusal_class: str | None  # DATA_INVALID | NO_TRADE | RISK_VETO | UNSUPPORTED_INSTRUMENT
    refusal_reasons: tuple[str, ...]
    numbers: dict[str, Any]
    violations: tuple[str, ...] = ()
    notes: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "expected": self.expected,
            "refusal_class": self.refusal_class,
            "refusal_reasons": list(self.refusal_reasons),
            "numbers": self.numbers,
            "violations": list(self.violations),
            "notes": list(self.notes),
        }


@dataclass(frozen=True, slots=True)
class Comparison:
    """Engine decision vs oracle verdict."""

    classification: str  # AGREE | FALSE_APPROVAL | CONSERVATIVE_DIVERGENCE | SUSPICION
    violations: tuple[str, ...]
    detail: str
    numbers: dict[str, Any]

    @property
    def is_false_approval(self) -> bool:
        return self.classification == "FALSE_APPROVAL"

    def to_dict(self) -> dict[str, Any]:
        return {
            "classification": self.classification,
            "violations": list(self.violations),
            "detail": self.detail,
            "numbers": self.numbers,
        }


# ---------------------------------------------------------------------------
# the independent model
# ---------------------------------------------------------------------------


def _normalize_spec(raw: dict[str, Any]) -> dict[str, Any]:
    """Accept either fixture shape (nested schedules or flattened to_dict)."""
    fee = raw.get("fee_schedule") or {}
    funding = raw.get("funding_schedule") or {}
    return {
        "contract_type": raw.get("contract_type"),
        "supported_position_modes": list(raw.get("supported_position_modes") or []),
        "minimum_notional": raw.get("minimum_notional", 0.0),
        "maximum_notional": raw.get("maximum_notional"),
        "quantity_step": raw.get("quantity_step", 0.0),
        "quantity_min": raw.get("quantity_min", 0.0),
        "quantity_max": raw.get("quantity_max"),
        "maintenance_margin_brackets": list(raw.get("maintenance_margin_brackets") or []),
        "liquidation_fee_rate": raw.get("liquidation_fee_rate"),
        "regulatory_eligibility_status": raw.get("regulatory_eligibility_status"),
        "taker_bps": fee.get("taker_bps", raw.get("taker_bps")),
        "funding_interval_ms": funding.get("interval_ms", raw.get("funding_interval_ms")),
    }


def _bracket(spec: dict[str, Any], notional: float) -> dict[str, Any]:
    for row in spec["maintenance_margin_brackets"]:
        if row["notional_floor"] <= notional <= row["notional_cap"]:
            return dict(row)
    return dict(spec["maintenance_margin_brackets"][-1])


def _maintenance(bracket: dict[str, Any], notional: float) -> float:
    rate = float(bracket["maintenance_margin_rate"])
    cumulative = float(bracket["cum_maintenance_amount"])
    return max(notional * rate - cumulative, 0.0)


def _floor_to_step(quantity: float, step: float) -> float:
    if step <= 0 or not math.isfinite(quantity) or quantity <= 0:
        return 0.0
    return round(int(quantity / step + 1e-9) * step, 12)


def _impact_bps(levels: list[list[float]] | None, notional: float) -> float | None:
    """Independent book-impact VWAP walk. ``None`` = the book cannot absorb it."""
    if not levels or notional <= 0:
        return None
    remaining = notional
    consumed_notional = 0.0
    consumed_qty = 0.0
    for level in levels:
        if len(level) < 2:
            return None
        price, size = level[0], level[1]
        if not (_finite(price) and _finite(size)) or float(price) <= 0 or float(size) <= 0:
            return None
        price = float(price)
        level_notional = price * float(size)
        take = min(remaining, level_notional)
        consumed_notional += take
        consumed_qty += take / price
        remaining -= take
        if remaining <= 0:
            break
    if remaining > 0 or consumed_qty <= 0:
        return None
    best = float(levels[0][0])
    if not _finite(best) or best <= 0:
        return None
    vwap = consumed_notional / consumed_qty
    if not math.isfinite(vwap):
        return None
    return abs(vwap - best) / best * 10_000.0


def _costs(scenario: OracleScenario, spec: dict[str, Any], notional: float) -> dict[str, Any]:
    """Independent worst-case round-trip cost, with its honest status."""
    unknown: list[str] = []
    taker_bps: Any = spec.get("taker_bps")
    if _finite(taker_bps):
        fees = float(taker_bps) * 2.0  # entry + exit
    else:
        unknown.append("commission")
        fees = 0.0

    spread_bps = _f(scenario.spread_bps, float("nan"))
    if not math.isfinite(spread_bps):
        unknown.append("spread")
        spread = 0.0
    else:
        spread = spread_bps * 2.0

    slippage = float(scenario.policy["slippage_bps"]) * 2.0
    stress_extra = (
        max(
            float(scenario.policy["stress_slippage_bps"]) - float(scenario.policy["slippage_bps"]),
            0.0,
        )
        * 2.0
    )

    depth = scenario.depth or {}
    entry_side = "asks" if scenario.direction == "LONG" else "bids"
    exit_side = "bids" if scenario.direction == "LONG" else "asks"
    impact_entry = _impact_bps(depth.get(entry_side), notional)
    impact_exit = _impact_bps(depth.get(exit_side), notional)
    if impact_entry is None or impact_exit is None:
        unknown.append("market_impact")
        impact = 0.0
    else:
        impact = impact_entry + impact_exit

    interval = _f(spec.get("funding_interval_ms"), float("nan"))
    settlements = 0
    if math.isfinite(interval) and interval > 0:
        settlements = int(scenario.horizon_minutes * 60_000 // interval)
    funding_paid_bps = 0.0
    funding_state = "NO_SETTLEMENT_IN_HORIZON"
    if settlements > 0:
        visible = [
            row
            for row in scenario.funding_observations
            if _finite(row.get("funding_time_ms"))
            and _finite(row.get("funding_rate"))
            and int(row["funding_time_ms"]) <= scenario.decision_timestamp_ms
        ]
        if not visible:
            unknown.append("funding")
            funding_state = "NO_PIT_RATE_KNOWN"
        else:
            adverse = max(abs(_f(row["funding_rate"])) for row in visible)
            funding_paid_bps = adverse * settlements * 10_000.0
            funding_state = f"PIT_ADVERSE_{adverse:.8f}x{settlements}"

    liquidation_fee = _f(spec.get("liquidation_fee_rate"), float("nan"))
    if not math.isfinite(liquidation_fee):
        unknown.append("liquidation_fee")
        liquidation_fee_usdt = None
    else:
        # Priced on the notional it is computed for; the caller re-bases it on the
        # APPROVED notional before solving the liquidation root.
        liquidation_fee_usdt = notional * liquidation_fee

    worst_bps = fees + spread + slippage + impact + stress_extra + funding_paid_bps
    return {
        "status": "COST_UNKNOWN" if unknown else "COST_ESTIMATED",
        "unknown_components": unknown,
        "worst_case_cost_bps": worst_bps,
        "worst_case_cost_usdt": worst_bps / 10_000.0 * notional,
        "funding_paid_bps": funding_paid_bps,
        "funding_state": funding_state,
        "settlements": settlements,
        "liquidation_fee_usdt": liquidation_fee_usdt,
        "liquidation_fee_rate": None if not math.isfinite(liquidation_fee) else liquidation_fee,
    }


def independent_liquidation_price(
    *,
    direction: str,
    quantity: float,
    entry: float,
    wallet_balance: float,
    bracket_rate: float,
    cum_maintenance: float,
    adverse_terms: float,
) -> float | None:
    """Numeric root of the venue's margin condition (independent of the builder).

    LONG   residual(P) = WB + qty*(P - E) - A - (qty*P*rate - cum)
    SHORT  residual(P) = WB + qty*(E - P) - A - (qty*P*rate - cum)
    """

    def residual(price: float) -> float:
        pnl = quantity * (price - entry) if direction == "LONG" else quantity * (entry - price)
        maintenance = max(quantity * price * bracket_rate - cum_maintenance, 0.0)
        return wallet_balance + pnl - adverse_terms - maintenance

    if quantity <= 0 or entry <= 0:
        return None
    if direction == "LONG":
        lo, hi = 0.0, entry
        if residual(hi) <= 0:
            return None  # already liquidated at entry: no room at all
        for _ in range(200):
            mid = (lo + hi) / 2.0
            if residual(mid) > 0:
                hi = mid
            else:
                lo = mid
        return round((lo + hi) / 2.0, 8)
    lo, hi = entry, entry * 100.0
    if residual(lo) <= 0:
        return None
    for _ in range(200):
        mid = (lo + hi) / 2.0
        if residual(mid) > 0:
            lo = mid
        else:
            hi = mid
    return round((lo + hi) / 2.0, 8)


def oracle_verdict(scenario: OracleScenario, fixtures: OracleFixtures) -> OracleVerdict:
    """Re-derive the whole decision and decide whether an approval is allowed."""
    raw_spec = scenario.effective_spec or fixtures.instruments.get(scenario.instrument_id)
    if raw_spec is None:
        return OracleVerdict(
            expected="REFUSE",
            refusal_class="UNSUPPORTED_INSTRUMENT",
            refusal_reasons=("INSTRUMENT_NOT_SUPPORTED",),
            numbers={},
        )
    spec = _normalize_spec(raw_spec)
    policy = {**DEFAULT_POLICY, **scenario.policy}
    numbers: dict[str, Any] = {}
    notes: list[str] = []

    def refuse(code: str, reason: str, **extra: Any) -> OracleVerdict:
        return OracleVerdict(
            expected="REFUSE",
            refusal_class=code,
            refusal_reasons=(reason,),
            numbers={**numbers, **extra},
            notes=tuple(notes),
        )

    # 0. live route / numeric validity / contract capability ------------------
    if scenario.live_route_requested:
        return refuse("RISK_VETO", "LIVE_ROUTE_ATTEMPTED")
    if spec.get("contract_type") != "LINEAR_PERPETUAL":
        return refuse("UNSUPPORTED_INSTRUMENT", "CONTRACT_TYPE_NOT_IMPLEMENTED")
    if "ISOLATED" not in spec.get("supported_position_modes", []):
        return refuse("UNSUPPORTED_INSTRUMENT", "POSITION_MODE_NOT_SUPPORTED")

    numbers["risk_budget"] = scenario.equity * float(policy["risk_budget_pct"])
    hostile: list[str] = []
    positive_checks: dict[str, float | None] = {
        "entry_price": scenario.entry_price,
        "stop_price": scenario.stop_price,
        "mark_price": scenario.mark_price,
        "requested_notional": scenario.requested_notional,
        "requested_leverage": scenario.requested_leverage,
        "horizon_minutes": scenario.horizon_minutes,
        "equity": scenario.equity,
    }
    for name, value in positive_checks.items():
        if value is None:
            if name not in ("stop_price", "mark_price"):
                # Those two are optional in the contract: an absent stop is
                # refused later as STOP_MISSING and an absent mark falls back to
                # the market payload, which is checked right below.
                hostile.append(name)
            continue
        number = float(value)
        if not math.isfinite(number) or number <= 0:
            hostile.append(name)
    signed_checks: dict[str, float] = {
        "free_margin": scenario.free_margin,
        "reserved_margin": scenario.reserved_margin,
        "daily_pnl": scenario.daily_pnl,
        "drawdown_pct": scenario.drawdown_pct,
    }
    for name, value in signed_checks.items():
        if not math.isfinite(float(value)):
            hostile.append(name)
    if scenario.mark_price is None and not _finite(fixtures.snapshot.get("mark_price")):
        hostile.append("market_mark_price")
    if not _finite(scenario.spread_bps):
        hostile.append("spread_bps")
    for index, stress in enumerate(scenario.stress):
        move = _f(stress.get("adverse_move_pct"), float("nan"))
        if not math.isfinite(move) or move < 0:
            hostile.append(f"stress[{index}].adverse_move_pct")
    if hostile:
        return refuse(
            "DATA_INVALID",
            "INVALID_NUMERIC_INPUT",
            invalid_inputs=sorted(set(hostile)),
        )

    # 1. data validity --------------------------------------------------------
    numbers["data_age_ms"] = scenario.decision_timestamp_ms - scenario.data_timestamp_ms
    if scenario.decision_timestamp_ms <= scenario.data_timestamp_ms:
        return refuse("DATA_INVALID", "FUTURE_TIMESTAMP")
    if numbers["data_age_ms"] > policy["max_data_age_ms"]:
        return refuse("DATA_INVALID", "STALE_DATA")
    if not spec.get("maintenance_margin_brackets"):
        return refuse("RISK_VETO", "INCOMPLETE_MARGIN_MODEL")
    if spec.get("regulatory_eligibility_status") == "PRODUCT_NOT_AVAILABLE":
        return refuse("DATA_INVALID", "VENUE_OR_PRODUCT_NOT_ELIGIBLE")

    mark = _f(
        scenario.mark_price
        if scenario.mark_price is not None
        else fixtures.snapshot.get("mark_price"),
        float("nan"),
    )
    if not math.isfinite(mark) or mark <= 0:
        return refuse("DATA_INVALID", "MISSING_MARK_PRICE")

    # 2. costs ----------------------------------------------------------------
    minimum_notional = float(spec["minimum_notional"])
    priced_notional = max(float(scenario.requested_notional), minimum_notional)
    costs = _costs(scenario, spec, priced_notional)
    numbers["cost_status"] = costs["status"]
    numbers["worst_case_cost_bps"] = costs["worst_case_cost_bps"]
    if costs["status"] == "COST_UNKNOWN":
        return refuse("NO_TRADE", "COST_UNKNOWN", unknown_components=costs["unknown_components"])

    stop = scenario.stop_price
    if stop is None:
        return refuse("RISK_VETO", "STOP_MISSING")
    stop_distance = (
        scenario.entry_price - stop if scenario.direction == "LONG" else stop - scenario.entry_price
    )
    if not math.isfinite(stop_distance) or stop_distance <= 0:
        return refuse("RISK_VETO", "STOP_MISSING")
    stop_bps = stop_distance / scenario.entry_price * 10_000.0
    numbers["stop_distance_bps"] = stop_bps
    if stop_bps < policy["min_stop_distance_bps"]:
        return refuse("RISK_VETO", "STOP_TOO_CLOSE")

    # 3. risk-bounded sizing --------------------------------------------------
    gap_pct = float(policy["gap_reserve_pct"])
    cost_bps = float(costs["worst_case_cost_bps"])
    if cost_bps >= 10_000.0:
        return refuse("RISK_VETO", "RISK_BUDGET_EXCEEDED")
    per_unit = stop_distance + scenario.entry_price * gap_pct
    quantity = numbers["risk_budget"] / (per_unit + scenario.entry_price * cost_bps / 10_000.0)
    quantity_step = _f(spec.get("quantity_step"), 0.0)
    quantity = _floor_to_step(quantity, quantity_step)
    if quantity <= 0:
        return refuse("NO_TRADE", "BELOW_MIN_NOTIONAL")
    quantity_min = _f(spec.get("quantity_min"), 0.0)
    if quantity_min and quantity < quantity_min:
        return refuse("NO_TRADE", "BELOW_MIN_NOTIONAL")
    quantity_max = _f(spec.get("quantity_max"), float("nan"))
    if math.isfinite(quantity_max) and quantity > quantity_max:
        quantity = _floor_to_step(quantity_max, quantity_step)
    notional = quantity * scenario.entry_price
    if notional > float(scenario.requested_notional):
        quantity = _floor_to_step(
            float(scenario.requested_notional) / scenario.entry_price, quantity_step
        )
        notional = quantity * scenario.entry_price
    numbers["quantity"] = quantity
    numbers["notional"] = notional
    if notional < minimum_notional:
        return refuse("NO_TRADE", "BELOW_MIN_NOTIONAL")
    maximum_notional = _f(spec.get("maximum_notional"), float("nan"))
    if math.isfinite(maximum_notional) and notional > maximum_notional:
        return refuse("NO_TRADE", "ABOVE_MAX_NOTIONAL")
    modelled_worst = (
        notional * (stop_distance / scenario.entry_price)
        + notional * gap_pct
        + notional * cost_bps / 10_000.0
    )
    numbers["modeled_worst_loss"] = modelled_worst
    if modelled_worst > numbers["risk_budget"] + 1e-9:
        return refuse("RISK_VETO", "RISK_BUDGET_EXCEEDED")

    # 4. leverage and margin --------------------------------------------------
    bracket = _bracket(spec, notional)
    effective_leverage = min(
        float(scenario.requested_leverage),
        float(policy["max_leverage"]),
        float(bracket["max_open_pos_leverage"]),
    )
    if effective_leverage <= 0:
        return refuse("RISK_VETO", "LEVERAGE_ABOVE_ALLOWED")
    initial_margin = notional / effective_leverage
    maintenance = _maintenance(bracket, notional)
    numbers["effective_leverage"] = effective_leverage
    numbers["initial_margin"] = initial_margin
    numbers["maintenance_margin"] = maintenance
    # ``free_margin`` already excludes the reserved part (that is its meaning in
    # the portfolio snapshot), so subtracting ``reserved_margin`` again would
    # double-count the reservation.
    # Margin and utilisation are NOT independent refusals here: the engine treats
    # them as ceilings that SHRINK the size, so they enter the portfolio cap
    # below and the result is verified after the clip.
    utilisation_pct = (scenario.reserved_margin + initial_margin) / scenario.equity * 100.0
    numbers["margin_utilization_pct"] = utilisation_pct

    # 5. portfolio ceilings ---------------------------------------------------
    gross_cap = scenario.equity * float(policy["max_gross_exposure_pct"])
    concentration_cap = scenario.equity * float(policy["max_concentration_pct"])
    net_ceiling = scenario.equity * float(policy["max_net_exposure_pct"])
    signed = 1.0 if scenario.direction == "LONG" else -1.0
    caps = [
        gross_cap,
        concentration_cap,
        scenario.free_margin * effective_leverage,
        max(
            scenario.equity * float(policy["max_margin_utilization_pct"])
            - scenario.reserved_margin,
            0.0,
        )
        * effective_leverage,
        max((net_ceiling * signed - 0.0) * signed, 0.0),
    ]
    portfolio_cap = max(min(caps), 0.0)
    numbers["portfolio_cap"] = portfolio_cap
    if portfolio_cap < notional - 1e-9:
        clipped = _floor_to_step(portfolio_cap / scenario.entry_price, quantity_step)
        if clipped <= 0 or clipped * scenario.entry_price < minimum_notional:
            return refuse("NO_TRADE", "EXPOSURE_LIMIT")
        quantity = clipped
        notional = clipped * scenario.entry_price
        numbers["quantity"] = quantity
        numbers["notional"] = notional
        modelled_worst = (
            notional * (stop_distance / scenario.entry_price)
            + notional * gap_pct
            + notional * cost_bps / 10_000.0
        )
        numbers["modeled_worst_loss"] = modelled_worst
        bracket = _bracket(spec, notional)
        effective_leverage = min(
            float(scenario.requested_leverage),
            float(policy["max_leverage"]),
            float(bracket["max_open_pos_leverage"]),
        )
        initial_margin = notional / effective_leverage
        numbers["effective_leverage"] = effective_leverage
        numbers["initial_margin"] = initial_margin
        if modelled_worst > numbers["risk_budget"] + 1e-9:
            return refuse("RISK_VETO", "RISK_BUDGET_EXCEEDED")

    # 5b. the clipped size must fit the margin ceilings -----------------------
    if initial_margin > scenario.free_margin + 1e-9:
        return refuse("NO_TRADE", "INSUFFICIENT_MARGIN")
    utilisation_pct = (scenario.reserved_margin + initial_margin) / scenario.equity * 100.0
    numbers["margin_utilization_pct"] = utilisation_pct
    if utilisation_pct > float(policy["max_margin_utilization_pct"]) * 100.0 + 1e-6:
        return refuse("NO_TRADE", "MARGIN_UTILIZATION_LIMIT")

    # 6. liquidation by numeric root -----------------------------------------
    fee_rate = _f(costs["liquidation_fee_rate"], float("nan"))
    if not math.isfinite(fee_rate):
        return refuse("NO_TRADE", "COST_UNKNOWN", unknown_components=["liquidation_fee"])
    # Both adverse terms are re-based on the APPROVED notional: the venue charges
    # the liquidation fee on the position it liquidates, not on what was asked for.
    safety = float(costs["funding_paid_bps"]) / 10_000.0 * notional + fee_rate * notional
    numbers["liquidation_safety_usdt"] = safety
    if initial_margin > modelled_worst + 1e-9:
        pass  # the engine's LOSS_ABOVE_MARGIN check belongs to its own policy
    liquidation = independent_liquidation_price(
        direction=scenario.direction,
        quantity=quantity,
        entry=scenario.entry_price,
        wallet_balance=initial_margin,
        bracket_rate=float(bracket["maintenance_margin_rate"]),
        cum_maintenance=float(bracket["cum_maintenance_amount"]),
        adverse_terms=safety,
    )
    numbers["liquidation_price"] = liquidation
    if liquidation is None or not math.isfinite(liquidation):
        return refuse("RISK_VETO", "LIQUIDATION_RISK_UNKNOWN")
    buffer_bps = (
        (scenario.entry_price - liquidation) / scenario.entry_price * 10_000.0
        if scenario.direction == "LONG"
        else (liquidation - scenario.entry_price) / scenario.entry_price * 10_000.0
    )
    numbers["liquidation_buffer_bps"] = buffer_bps
    if buffer_bps < float(policy["min_liquidation_buffer_bps"]) - 1e-9:
        return refuse("RISK_VETO", "LIQUIDATION_BUFFER_TOO_SMALL")
    if scenario.direction == "LONG":
        if stop is not None and liquidation >= stop:
            return refuse("RISK_VETO", "LIQUIDATION_BEFORE_STOP")
    elif stop is not None and liquidation <= stop:
        return refuse("RISK_VETO", "LIQUIDATION_BEFORE_STOP")

    # 7. stress: the same numeric root at the stressed mark -------------------
    for stress in scenario.stress:
        move = float(stress["adverse_move_pct"])
        stress_mark = (
            scenario.entry_price * (1.0 - move)
            if scenario.direction == "LONG"
            else scenario.entry_price * (1.0 + move)
        )
        if scenario.direction == "LONG" and stress_mark <= liquidation:
            return refuse("RISK_VETO", "GAP_BEYOND_STOP")
        if scenario.direction == "SHORT" and stress_mark >= liquidation:
            return refuse("RISK_VETO", "GAP_BEYOND_STOP")
        notes.append(f"stress {stress.get('name')} survives at mark {stress_mark:.6f}")

    numbers["mark_price"] = mark
    numbers["requested_notional"] = float(scenario.requested_notional)
    numbers["order_authorised_invariant"] = "MUST_BE_FALSE"
    return OracleVerdict(
        expected="APPROVE_OR_REDUCE",
        refusal_class=None,
        refusal_reasons=(),
        numbers=numbers,
        notes=tuple(notes),
    )


# ---------------------------------------------------------------------------
# comparison: engine decision vs oracle
# ---------------------------------------------------------------------------


#: Which §04 invariant a refusal reason belongs to when the engine APPROVES
#: anyway. Only the reasons that are copied from the oracle's own refusal path
#: are mapped; anything else stays conservatively unmapped under I5.
_INVARIANT_BY_REASON = {
    "STALE_DATA": "I4_DATA_ORDER",
    "FUTURE_TIMESTAMP": "I4_DATA_ORDER",
    "INVALID_NUMERIC_INPUT": "I4_DATA_ORDER",
    "MISSING_MARK_PRICE": "I5_UNKNOWN_CRITICAL_INPUT",
    "COST_UNKNOWN": "I5_UNKNOWN_CRITICAL_INPUT",
    "FUNDING_UNKNOWN": "I5_UNKNOWN_CRITICAL_INPUT",
    "INCOMPLETE_MARGIN_MODEL": "I5_UNKNOWN_CRITICAL_INPUT",
    "LIQUIDATION_RISK_UNKNOWN": "I5_UNKNOWN_CRITICAL_INPUT",
    "INSUFFICIENT_MARGIN": "I2_MARGIN_LE_AVAILABLE",
    "MARGIN_UTILIZATION_LIMIT": "I2_MARGIN_LE_AVAILABLE",
    "EXPOSURE_LIMIT": "I3_NOTIONAL_LE_MAX_ALLOWED",
    "BELOW_MIN_NOTIONAL": "I3_NOTIONAL_LE_MAX_ALLOWED",
    "ABOVE_MAX_NOTIONAL": "I3_NOTIONAL_LE_MAX_ALLOWED",
    "STOP_MISSING": "I7_LIQUIDATION_KNOWN_AND_SAFE",
    "STOP_TOO_CLOSE": "I7_LIQUIDATION_KNOWN_AND_SAFE",
    "LIQUIDATION_BEFORE_STOP": "I7_LIQUIDATION_KNOWN_AND_SAFE",
    "LIQUIDATION_BUFFER_TOO_SMALL": "I7_LIQUIDATION_KNOWN_AND_SAFE",
    "GAP_BEYOND_STOP": "I7_LIQUIDATION_KNOWN_AND_SAFE",
    "LIVE_ROUTE_ATTEMPTED": "I8_LIVE_ROUTE_BLOCKED",
}


def compare_decision(
    decision: dict[str, Any],
    verdict: OracleVerdict,
    scenario: OracleScenario,
    *,
    quantity_step: float | None = None,
) -> Comparison:
    """Classify one engine decision against the independent verdict.

    ``FALSE_APPROVAL`` is claimed ONLY when an approved decision provably
    violates one of the RFC-048 §04 invariants. A refusal the oracle would have
    allowed is reported as a conservative divergence, not as a defect: being
    stricter than the independent model is not a safety failure.
    """
    approved = decision.get("decision") in ("APPROVE_SIMULATION", "REDUCE_SIMULATED_SIZE")
    violations: list[str] = []
    numbers: dict[str, Any] = {
        "engine_decision": decision.get("decision"),
        "engine_models": {
            "approved_notional": decision.get("approved_notional"),
            "effective_leverage": decision.get("effective_leverage"),
            "required_margin": decision.get("required_margin"),
            "modeled_worst_loss": decision.get("modeled_worst_loss"),
            "liquidation_price": decision.get("liquidation_price"),
            "liquidation_buffer_bps": decision.get("liquidation_buffer_bps"),
        },
        "oracle": verdict.numbers,
    }

    # I9 — no decision authorises an order, approved or not.
    if decision.get("order_authorised") is not False:
        violations.append("I9_NO_ORDER_AUTHORISED")
    if decision.get("decision") == "APPROVE_SIMULATION" and decision.get("order_authorised"):
        violations.append("I9_NO_ORDER_AUTHORISED")

    if approved:
        oracle_numbers = verdict.numbers
        budget = _f(oracle_numbers.get("risk_budget"))
        modelled = _f(decision.get("modeled_worst_loss"))
        if modelled > budget + max(MONEY_TOL, abs(budget) * REL_TOL):
            violations.append("I1_APPROVED_RISK_LE_BUDGET")
        margin = _f(decision.get("required_margin"))
        if margin > scenario.free_margin + MONEY_TOL:
            violations.append("I2_MARGIN_LE_AVAILABLE")
        notional = _f(decision.get("approved_notional"))
        if notional > float(scenario.requested_notional) + MONEY_TOL:
            violations.append("I3_NOTIONAL_LE_MAX_ALLOWED")
        oracle_cap = _f(oracle_numbers.get("portfolio_cap"), float("inf"))
        if notional > oracle_cap + max(MONEY_TOL, abs(oracle_cap) * 1e-9):
            violations.append("I3_NOTIONAL_LE_MAX_ALLOWED")
        if int(decision.get("data_timestamp_ms") or 0) > int(
            decision.get("decision_timestamp_ms") or 0
        ):
            violations.append("I4_DATA_ORDER")
        age = scenario.decision_timestamp_ms - scenario.data_timestamp_ms
        if age > scenario.policy.get("max_data_age_ms", DEFAULT_POLICY["max_data_age_ms"]):
            violations.append("I4_DATA_ORDER")
        # The engine approved although the independent model refuses: map the
        # refusal reason onto the §04 invariant it belongs to.
        if verdict.expected == "REFUSE":
            mapped = sorted(
                {
                    _INVARIANT_BY_REASON.get(reason, "I5_UNKNOWN_CRITICAL_INPUT")
                    for reason in verdict.refusal_reasons
                }
            )
            if verdict.refusal_class == "UNSUPPORTED_INSTRUMENT":
                mapped = ["I6_UNSUPPORTED_CONTRACT"]
            elif verdict.refusal_class == "RISK_VETO" and "LIVE_ROUTE_ATTEMPTED" in (
                verdict.refusal_reasons
            ):
                mapped = ["I8_LIVE_ROUTE_BLOCKED"]
            violations.extend(mapped or ["I5_UNKNOWN_CRITICAL_INPUT"])
        # I7: liquidation known, buffer inside the policy floor, not before stop,
        # and numerically consistent with the independent root.
        buffer_bps = decision.get("liquidation_buffer_bps")
        policy_min = float(
            scenario.policy.get(
                "min_liquidation_buffer_bps", DEFAULT_POLICY["min_liquidation_buffer_bps"]
            )
        )
        oracle_buffer = _f(oracle_numbers.get("liquidation_buffer_bps"), float("nan"))
        if buffer_bps is None or not math.isfinite(oracle_buffer):
            violations.append("I7_LIQUIDATION_KNOWN_AND_SAFE")
        else:
            if float(buffer_bps) < policy_min - 1e-6:
                violations.append("I7_LIQUIDATION_KNOWN_AND_SAFE")
            if abs(float(buffer_bps) - oracle_buffer) > 1.0:
                violations.append("I7_LIQUIDATION_KNOWN_AND_SAFE")
        liquidation = decision.get("liquidation_price")
        stop = scenario.stop_price
        if (
            liquidation is None
            or stop is None
            or (scenario.direction == "LONG" and float(liquidation) >= float(stop))
            or (scenario.direction == "SHORT" and float(liquidation) <= float(stop))
        ):
            violations.append("I7_LIQUIDATION_KNOWN_AND_SAFE")
        # I10: the quantity floors to the venue step and never inflates.
        if quantity_step is not None and quantity_step > 0:
            ratio = _f(decision.get("quantity")) / float(quantity_step)
            if abs(ratio - round(ratio)) > 1e-6:
                violations.append("I10_ROUNDING_REDUCES")
        if (
            decision.get("decision") == "REDUCE_SIMULATED_SIZE"
            and notional > float(scenario.requested_notional) + MONEY_TOL
        ):
            violations.append("I10_ROUNDING_REDUCES")
        violations = sorted(set(violations))
        if violations:
            return Comparison(
                classification="FALSE_APPROVAL",
                violations=tuple(violations),
                detail=(
                    "the engine approved a position the independent model refuses "
                    f"({verdict.refusal_class}: {', '.join(verdict.refusal_reasons)}) "
                    f"or that violates {', '.join(violations)}"
                ),
                numbers=numbers,
            )
        return Comparison(
            classification="AGREE",
            violations=(),
            detail="approved decision satisfies every re-derived invariant",
            numbers=numbers,
        )

    # A refusal: report only whether the independent model would have allowed it.
    if verdict.expected == "APPROVE_OR_REDUCE":
        return Comparison(
            classification="CONSERVATIVE_DIVERGENCE",
            violations=(),
            detail=(
                "the engine refused a request the independent model permits: "
                + ", ".join(rd for rd in decision.get("rejection_reasons", []))
            ),
            numbers=numbers,
        )
    return Comparison(
        classification="AGREE",
        violations=(),
        detail="both models refuse",
        numbers=numbers,
    )
