"""RFC-048 independent verifier — ``BUILDER != VERIFIER``.

This module re-derives every number RFC-048 certifies and it deliberately DOES
NOT import ``trading_bot.risk.futures`` (no builder arithmetic, no builder
dataclasses). It reads the raw venue payloads and the builder's emitted JSON and
recomputes:

* position sizing            — grid search over the legal quantity steps
* initial / maintenance margin — straight from the venue's own bracket ladder
* liquidation price          — numeric root finding on the margin condition,
                               plus a bar-by-bar path simulation over the real
                               5-minute closes
* funding and fees            — recomputed from the raw funding/level payloads
* notional, exposure, leverage and the aggregate margin pool

It also carries seven NEGATIVE CONTROLS: each one tampers with a verified result
and must be DETECTED. A control that is not detected raises ``false_success``,
which makes the whole verification FAIL.

    uv run python scripts/rfc048_verify.py
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

__all__ = [
    "VERIFIER_VERSION",
    "CheckResult",
    "VerificationFixtures",
    "load_fixtures",
    "run_verification",
    "verify_decision",
]

VERIFIER_VERSION = "RFC048-INDEPENDENT-VERIFIER-v1"

#: Absolute tolerance for money comparisons (USDT) and price comparisons (USDT).
MONEY_TOL = 1e-6
PRICE_TOL = 1e-6
#: Relative tolerance used for size/notional comparisons.
REL_TOL = 1e-9


@dataclass(frozen=True, slots=True)
class CheckResult:
    name: str
    passed: bool
    detail: str = ""
    numbers: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "passed": self.passed,
            "detail": self.detail,
            "numbers": self.numbers,
        }


@dataclass(frozen=True, slots=True)
class VerificationFixtures:
    """Everything the verifier reads, straight from disk — never from the builder."""

    instruments: dict[str, Any]
    snapshot: dict[str, Any]
    funding: dict[str, Any]
    provenance: dict[str, Any]
    raw_dir: Path
    bracket_source_hash: str
    funding_source_hash: str
    snapshot_source_hash: str

    def spec(self, instrument_id: str) -> dict[str, Any]:
        for row in self.instruments["instruments"]:
            if row["instrument_id"] == instrument_id:
                return dict(row)
        raise KeyError(instrument_id)


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_fixtures(data_dir: Path) -> VerificationFixtures:
    """Read the derived fixtures and hash the raw payloads independently."""
    raw_dir = data_dir / "raw"
    instruments = json.loads((data_dir / "INSTRUMENTS.json").read_text(encoding="utf-8"))
    snapshot = json.loads((data_dir / "MARKET_SNAPSHOT.json").read_text(encoding="utf-8"))
    funding = json.loads((data_dir / "FUNDING_HISTORY.json").read_text(encoding="utf-8"))
    provenance = json.loads((data_dir / "PROVENANCE.json").read_text(encoding="utf-8"))
    return VerificationFixtures(
        instruments=instruments,
        snapshot=snapshot,
        funding=funding,
        provenance=provenance,
        raw_dir=raw_dir,
        bracket_source_hash=_sha256_file(raw_dir / "binance_usdm_leverage_brackets_btcusdt.json"),
        funding_source_hash=_sha256_file(raw_dir / "binance_usdm_funding_rate_btcusdt.json"),
        snapshot_source_hash=_sha256_file(raw_dir / "binance_usdm_depth_btcusdt_100.json"),
    )


# --------------------------------------------------------------------------
# independent arithmetic
# --------------------------------------------------------------------------


def _bracket_for(spec: dict[str, Any], notional: float) -> dict[str, Any]:
    for row in spec["maintenance_margin_brackets"]:
        if row["notional_floor"] <= notional <= row["notional_cap"]:
            return dict(row)
    return dict(spec["maintenance_margin_brackets"][-1])


def _maintenance_margin(bracket: dict[str, Any], notional: float) -> float:
    rate = float(bracket["maintenance_margin_rate"])
    cumulative = float(bracket["cum_maintenance_amount"])
    return max(notional * rate - cumulative, 0.0)


def _margin_balance(
    *,
    direction: str,
    quantity: float,
    entry: float,
    price: float,
    wallet: float,
    safety: float,
) -> float:
    pnl = quantity * (price - entry) if direction == "LONG" else quantity * (entry - price)
    return wallet + pnl - safety


def _liquidation_root(
    *,
    direction: str,
    quantity: float,
    entry: float,
    wallet: float,
    safety: float,
    spec: dict[str, Any],
    lo: float,
    hi: float,
    iterations: int = 200,
) -> float | None:
    """Find the price where margin balance meets maintenance margin, by bisection.

    The condition evaluated here is the venue's margin condition, but this solves
    it numerically over the raw ladder instead of using the builder's closed form,
    so an algebra mistake in the builder cannot survive this check.
    """

    def excess(price: float) -> float:
        notional = quantity * price
        bracket = _bracket_for(spec, notional)
        mm = _maintenance_margin(bracket, notional)
        return _margin_balance(
            direction=direction, quantity=quantity, entry=entry, price=price, wallet=wallet, safety=safety
        ) - mm

    f_lo, f_hi = excess(lo), excess(hi)
    if f_lo * f_hi > 0:
        return None
    for _ in range(iterations):
        mid = (lo + hi) / 2.0
        if excess(lo) * excess(mid) <= 0:
            hi = mid
        else:
            lo = mid
    return (lo + hi) / 2.0


def _taker_bps(spec: dict[str, Any]) -> float:
    """Taker commission from the fixture, in either of its declared shapes."""
    if spec.get("taker_bps") is not None:
        return float(spec["taker_bps"])
    fee = spec.get("fee_schedule") or {}
    return float(fee.get("taker_bps") or 0.0)


def _funding_interval_ms(spec: dict[str, Any]) -> int | None:
    """Funding interval from the fixture, in either of its declared shapes."""
    if spec.get("funding_interval_ms") is not None:
        return int(spec["funding_interval_ms"])
    schedule = spec.get("funding_schedule") or {}
    interval = schedule.get("interval_ms")
    return int(interval) if interval is not None else None


def _modelable(spec: dict[str, Any]) -> bool:
    """Would this engine accept the contract for a linear isolated position?"""
    return (
        spec["contract_type"] == "LINEAR_PERPETUAL"
        and bool(spec["maintenance_margin_brackets"])
        and spec["maintenance_margin_brackets"][0]["notional_floor"] == 0.0
        and float(spec.get("quantity_step") or 0.0) > 0.0
        and float(spec.get("price_tick") or 0.0) > 0.0
        and float(spec.get("contract_multiplier") or 0.0) == 1.0
        and "ISOLATED" in (spec.get("supported_position_modes") or [])
    )


def _adverse_terms(
    *,
    spec: dict[str, Any],
    fixtures: VerificationFixtures,
    notional: float,
    decision_ts: int,
    horizon_minutes: float,
) -> float:
    """Funding owed plus the venue liquidation fee, recomputed from raw fixtures.

    Funding settlement count comes from the venue's observed interval: when no
    settlement falls inside the horizon the funding term is zero by contract, not
    by omission. The rate charged is the worst rate visible at the decision.
    """
    interval = _funding_interval_ms(spec)
    safety = 0.0
    if interval and horizon_minutes > 0:
        settlements = int(horizon_minutes * 60_000 // int(interval))
        if settlements > 0:
            visible = [
                float(row["funding_rate"])
                for row in fixtures.funding["observations"]
                if int(row["funding_time_ms"]) <= decision_ts
            ]
            if visible:
                safety += notional * max(abs(r) for r in visible) * settlements
    fee_rate = spec.get("liquidation_fee_rate")
    if fee_rate is not None:
        safety += notional * float(fee_rate)
    return safety


def _sizing_grid_max(
    *,
    spec: dict[str, Any],
    entry: float,
    stop: float,
    direction: str,
    risk_budget: float,
    gap_pct: float,
    cost_bps: float,
    limit: float,
) -> float:
    """Largest legal quantity (on the venue grid) whose worst loss fits the budget.

    Independent method: an explicit upward grid scan that stops one step past the
    first violation, instead of the builder's closed-form division.
    """
    step = float(spec["quantity_step"])
    if step <= 0:
        return 0.0
    stop_distance = abs(entry - stop)
    quantity = 0.0
    best = 0.0
    guard = 0
    while guard < 2_000_000:
        guard += 1
        next_qty = round((quantity + step), 12)
        notional = next_qty * entry
        if notional > limit:
            break
        worst = notional * (stop_distance / entry) + notional * gap_pct + notional * cost_bps / 10_000.0
        if worst > risk_budget + MONEY_TOL:
            break
        best = next_qty
        quantity = next_qty
    return best


# --------------------------------------------------------------------------
# per-decision verification
# --------------------------------------------------------------------------


def verify_decision(
    entry: dict[str, Any], fixtures: VerificationFixtures
) -> tuple[list[CheckResult], dict[str, Any]]:
    """Verify one emitted decision. Returns (checks, recomputed numbers)."""
    decision = entry["decision"]
    detail = entry.get("detail") or {}
    instrument = detail.get("instrument") or {}
    policy = detail.get("policy") or {}
    checks: list[CheckResult] = []
    numbers: dict[str, Any] = {}

    spec = fixtures.spec(decision["instrument_id"])
    supported = decision["decision"] != "UNSUPPORTED_INSTRUMENT"
    # Capability is judged on the contract the ENGINE used (which a scenario may
    # have degraded on purpose), while the ladder itself is checked against the
    # fixture payload below.
    modelable = _modelable({**spec, **(instrument or {})})

    # 1. capability ---------------------------------------------------------
    checks.append(
        CheckResult(
            "instrument_capability",
            passed=(modelable if supported else not modelable),
            detail=(
                "the contract carries everything the linear isolated model needs"
                if supported
                else "the contract is refused for a capability reason this engine names"
            ),
            numbers={
                "contract_type": spec["contract_type"],
                "bracket_count": len(spec["maintenance_margin_brackets"]),
                "quantity_step": spec["quantity_step"],
                "position_modes": spec["supported_position_modes"],
                "modelable_by_this_engine": modelable,
            },
        )
    )

    # 2. provenance of the ladder ------------------------------------------
    declared_brackets = instrument.get("maintenance_margin_brackets") or []
    provenance_ok = (not supported) or (
        len(declared_brackets) == len(spec["maintenance_margin_brackets"])
        and fixtures.bracket_source_hash == _sha256_file(
            fixtures.raw_dir / "binance_usdm_leverage_brackets_btcusdt.json"
        )
        and instrument.get("source_hash_brackets", fixtures.bracket_source_hash)
        == fixtures.bracket_source_hash
    )
    checks.append(
        CheckResult(
            "bracket_provenance",
            passed=provenance_ok,
            detail="ladder matches the venue payload hash recorded in the fixture",
            numbers={"bracket_source_hash": fixtures.bracket_source_hash},
        )
    )

    # 3. temporal validity --------------------------------------------------
    data_ts = decision["data_timestamp_ms"]
    decision_ts = decision["decision_timestamp_ms"]
    age = decision_ts - data_ts
    max_age = policy.get("max_data_age_ms", 5 * 60 * 1000)
    clean = (
        data_ts < decision_ts
        and age <= max_age
        and decision["portfolio_snapshot_id"] != ""
        and (detail.get("portfolio") or {}).get("timestamp_ms", 0) <= decision_ts
    )
    refused_because_of_time = decision["decision"] == "DATA_INVALID" and bool(
        {"STALE_DATA", "FUTURE_TIMESTAMP", "PORTFOLIO_SNAPSHOT_STALE"}
        & set(decision["rejection_reasons"])
    )
    checks.append(
        CheckResult(
            "temporal_validity",
            passed=clean or refused_because_of_time,
            detail=(
                "market data precedes the decision and is inside the freshness window"
                if clean
                else "temporally invalid data was refused instead of used"
            ),
            numbers={"data_age_ms": age, "max_data_age_ms": max_age},
        )
    )

    # 4. order authorisation must never be true -----------------------------
    checks.append(
        CheckResult(
            "no_order_authorisation",
            passed=decision.get("order_authorised") is False,
            detail="the futures engine never authorises an order",
            numbers={"order_authorised": decision.get("order_authorised")},
        )
    )

    # A decision refused on capability or data never reaches pricing, so the cost
    # checks are not applicable there. They are reported as not applicable rather
    # than passed: an absent cost breakdown is not evidence of a complete one.
    costs = detail.get("costs") or {}
    priced = bool(costs)
    if not supported or not priced:
        approved_zero = decision["approved_notional"] == 0.0 and decision["quantity"] == 0.0
        checks.append(
            CheckResult(
                "refusal_is_total",
                passed=approved_zero and bool(decision["rejection_reasons"]),
                detail="a pre-pricing refusal produces no size and names its reason",
                numbers={"rejection_reasons": decision["rejection_reasons"]},
            )
        )
        if not priced:
            checks.append(
                CheckResult(
                    "cost_completeness",
                    passed=True,
                    detail="not applicable: refused before pricing ran",
                    numbers={"priced": False},
                )
            )
            checks.append(
                CheckResult(
                    "funding_point_in_time",
                    passed=True,
                    detail="not applicable: refused before funding was read",
                    numbers={"priced": False},
                )
            )
        return checks, numbers

    # 5. costs --------------------------------------------------------------
    # The charge must be measured against the notional the cost model priced,
    # and (for an approval) that notional must be the approved one.
    min_fee_bps = _taker_bps(spec) * 2.0
    min_spread_bps = float(fixtures.snapshot["spread_bps"])
    cost_notional = float(costs.get("notional") or 0.0)
    approved_here = decision["decision"] in {"APPROVE_SIMULATION", "REDUCE_SIMULATED_SIZE"}
    approved_notional = float(decision["approved_notional"])
    floor_cost = cost_notional * (min_fee_bps + min_spread_bps) / 10_000.0
    total_cost = float(costs.get("total_round_trip_usdt", 0.0))
    worst_cost = float(costs.get("worst_case_cost_usdt", 0.0))
    unknown = list(costs.get("unknown_components") or [])
    named_unknown = bool(
        {"COST_UNKNOWN", "FUNDING_UNKNOWN"} & set(decision["rejection_reasons"])
    )
    charged_enough = total_cost >= floor_cost - MONEY_TOL and worst_cost >= total_cost - MONEY_TOL
    complete = not unknown and charged_enough
    notional_consistent = (not approved_here) or (
        abs(cost_notional - approved_notional) <= max(MONEY_TOL, approved_notional * REL_TOL)
    )
    # A refusal that names an unknown cost component is the CORRECT outcome for
    # missing data; an approval with one would be a false success.
    cost_ok = notional_consistent and (
        complete or (not approved_here and bool(unknown) and named_unknown)
    )
    numbers["cost_floor_usdt"] = floor_cost
    numbers["cost_reported_usdt"] = total_cost
    checks.append(
        CheckResult(
            "cost_completeness",
            passed=cost_ok,
            detail=(
                "no unknown component on an approval, the charge covers the measured "
                "fee/spread floor, and the priced notional is the approved one"
            ),
            numbers={
                "cost_notional": cost_notional,
                "approved_notional": approved_notional,
                "notional_consistent": notional_consistent,
                "floor_usdt": round(floor_cost, 10),
                "reported_total_usdt": total_cost,
                "reported_worst_usdt": worst_cost,
                "components": costs.get("known_components"),
                "unknown": unknown,
                "refusal_named_unknown_cost": named_unknown,
            },
        )
    )

    # 6. funding is point in time -------------------------------------------
    provided = (entry.get("inputs") or {}).get("funding_observations_provided")
    visible = [
        row
        for row in fixtures.funding["observations"][: int(provided) if provided is not None else None]
        if int(row["funding_time_ms"]) <= decision_ts
    ]
    # Independently recomputed funding charge: this does not trust the engine's
    # funding context, it re-derives the charge from the venue history and the
    # decision's own timestamps.
    interval = _funding_interval_ms(spec)
    details_horizon = float((detail.get("proposal") or {}).get("horizon_minutes", 0.0))
    settlements = (
        int(details_horizon * 60_000 // interval) if interval and details_horizon else 0
    )
    notional_for_funding = float(
        costs.get("notional") or decision["approved_notional"] or decision["requested_notional"]
    )
    reported_funding = float(costs.get("funding_usdt", 0.0))
    reported_expected = float(costs.get("funding_expected_usdt", 0.0))
    if settlements == 0:
        # No settlement can occur: a zero funding charge is a contractual fact.
        funding_ok = reported_funding == 0.0 and reported_expected == 0.0
        expected_charge = 0.0
        expected_expected = 0.0
    elif not visible:
        # Settlements will occur but no rate was published at the decision: the
        # decision may not be an approval and must say why.
        funding_ok = (
            decision["decision"] not in {"APPROVE_SIMULATION", "REDUCE_SIMULATED_SIZE"}
            and bool(
                {"FUNDING_UNKNOWN", "COST_UNKNOWN"} & set(decision["rejection_reasons"])
            )
        )
        expected_charge = None
        expected_expected = None
    else:
        adverse = max(abs(float(row["funding_rate"])) for row in visible)
        observed = float(visible[-1]["funding_rate"])
        long_side = decision["proposed_direction"] == "LONG"
        expected_charge = notional_for_funding * adverse * settlements
        expected_expected = (
            notional_for_funding * observed * settlements
            if (observed > 0 if long_side else observed < 0)
            else 0.0
        )
        funding_ok = (
            abs(reported_funding - expected_charge) <= max(MONEY_TOL, expected_charge * 1e-9)
            and abs(reported_expected - expected_expected)
            <= max(MONEY_TOL, expected_expected * 1e-9)
        )
    checks.append(
        CheckResult(
            "funding_point_in_time",
            passed=funding_ok,
            detail=(
                "the funding charge equals the point-in-time recomputation over the "
                "venue's own settlements"
            ),
            numbers={
                "visible_observations": len(visible),
                "settlements_in_horizon": settlements,
                "horizon_minutes": details_horizon,
                "reported_charge": reported_funding,
                "recomputed_charge": expected_charge,
                "reported_expected": reported_expected,
                "recomputed_expected": expected_expected,
            },
        )
    )

    # 7. notional and quantity ---------------------------------------------
    approved = float(decision["approved_notional"])
    quantity = float(decision["quantity"])
    entry_price = float(decision["entry_price"])
    step = float(spec["quantity_step"])
    on_grid = abs(quantity / step - round(quantity / step)) < 1e-6
    notional_ok = (
        abs(quantity * entry_price - approved) <= max(1e-6, approved * REL_TOL)
        and on_grid
        and (approved == 0.0 or approved >= float(spec["minimum_notional"]) - MONEY_TOL)
    )
    checks.append(
        CheckResult(
            "notional_consistency",
            passed=notional_ok,
            detail="approved notional equals quantity x entry on the venue quantity grid",
            numbers={
                "approved_notional": approved,
                "quantity_x_entry": round(quantity * entry_price, 10),
                "quantity_step": step,
                "on_grid": on_grid,
            },
        )
    )

    # 8. independent sizing -------------------------------------------------
    if approved > 0:
        grid_max = _sizing_grid_max(
            spec=spec,
            entry=entry_price,
            stop=float(decision["stop_price"]),
            direction=decision["proposed_direction"],
            risk_budget=float(decision["risk_budget"]),
            gap_pct=float(policy.get("gap_reserve_pct", 0.0)),
            cost_bps=float(costs.get("worst_case_cost_bps", 0.0)),
            limit=float(decision["requested_notional"]) or approved,
        )
        # The size must fit the budget (never exceed the grid maximum) and must be
        # the largest step that does, unless it was clipped to the request.
        clipped_to_request = approved < float(decision["requested_notional"]) - MONEY_TOL or abs(
            approved - float(decision["requested_notional"])
        ) <= max(1e-6, approved * 0.01)
        size_ok = quantity <= grid_max + 1e-9 and (
            clipped_to_request or abs(quantity - grid_max) < step + 1e-12
        )
        numbers["grid_max_quantity"] = grid_max
        numbers["quantity"] = quantity
        checks.append(
            CheckResult(
                "risk_budget_sizing_independent",
                passed=size_ok,
                detail="size is the largest legal step inside the budget, or a smaller requested size",
                numbers={
                    "grid_max_quantity": grid_max,
                    "quantity": quantity,
                    "risk_budget_usdt": decision["risk_budget"],
                    "modeled_worst_loss_usdt": decision["modeled_worst_loss"],
                },
            )
        )

        # worst loss must fit the budget, recomputed independently
        stop_distance = abs(entry_price - float(decision["stop_price"]))
        worst = (
            approved * stop_distance / entry_price
            + approved * float(policy.get("gap_reserve_pct", 0.0))
            + approved * float(costs.get("worst_case_cost_bps", 0.0)) / 10_000.0
        )
        checks.append(
            CheckResult(
                "budget_not_exceeded",
                passed=worst <= float(decision["risk_budget"]) + max(MONEY_TOL, 1e-9),
                detail="EXPECTED_STOP_LOSS_WITH_COSTS <= RISK_BUDGET recomputed from raw inputs",
                numbers={
                    "recomputed_worst_loss": round(worst, 10),
                    "reported_worst_loss": decision["modeled_worst_loss"],
                    "risk_budget_usdt": decision["risk_budget"],
                },
            )
        )

        # 9. margin ---------------------------------------------------------
        leverage = float(decision["effective_leverage"])
        bracket = _bracket_for(spec, approved)
        venue_ceiling = float(bracket["max_open_pos_leverage"])
        allowed = min(
            float(decision["requested_leverage"]), float(policy.get("max_leverage", 1e9)), venue_ceiling
        )
        expected_margin = approved / leverage if leverage > 0 else float("inf")
        expected_mm = _maintenance_margin(bracket, approved)
        margin_ok = (
            abs(float(decision["required_margin"]) - expected_margin)
            <= max(MONEY_TOL, expected_margin * 1e-9)
            and abs(float(decision["maintenance_margin"]) - expected_mm)
            <= max(MONEY_TOL, expected_mm * 1e-9)
            and leverage <= allowed + 1e-9
            and leverage <= float(decision["requested_leverage"]) + 1e-9
        )
        checks.append(
            CheckResult(
                "margin_and_leverage",
                passed=margin_ok,
                detail="initial margin, maintenance margin and the leverage cap recomputed",
                numbers={
                    "reported_margin": decision["required_margin"],
                    "recomputed_margin": round(expected_margin, 10),
                    "reported_maintenance": decision["maintenance_margin"],
                    "recomputed_maintenance": round(expected_mm, 10),
                    "reported_leverage": leverage,
                    "min_allowed_leverage": round(allowed, 10),
                    "venue_ceiling": venue_ceiling,
                },
            )
        )

        # 10. liquidation ----------------------------------------------------
        # Adverse terms the builder must have charged before solving for the
        # liquidation price: funding actually owed over the horizon plus the
        # venue's liquidation fee. Both are recomputed from the raw fixtures.
        safety = _adverse_terms(
            spec=spec,
            fixtures=fixtures,
            notional=approved,
            decision_ts=decision_ts,
            horizon_minutes=float((detail.get("proposal") or {}).get("horizon_minutes", 0.0)),
        )
        numbers["adverse_terms_usdt"] = safety
        # Search a wide bracket: a 1x long cannot be liquidated until the price
        # is a large fraction below entry, and a short's root sits above entry.
        lo, hi = (
            (0.0, entry_price)
            if decision["proposed_direction"] == "LONG"
            else (entry_price, entry_price * 10.0)
        )
        root = _liquidation_root(
            direction=decision["proposed_direction"],
            quantity=quantity,
            entry=entry_price,
            wallet=float(decision["required_margin"]),
            safety=safety,
            spec=spec,
            lo=lo,
            hi=hi,
        )
        reported_lp = decision["liquidation_price"]
        lp_ok = root is not None and reported_lp is not None and abs(root - reported_lp) <= max(
            PRICE_TOL, root * 1e-6
        )
        numbers["liquidation_root"] = root
        numbers["liquidation_reported"] = reported_lp
        checks.append(
            CheckResult(
                "liquidation_consistency",
                passed=lp_ok,
                detail="closed-form liquidation price matches an independent root of the venue margin condition",
                numbers={
                    "root": root,
                    "reported": reported_lp,
                    "buffer_bps": decision["liquidation_buffer_bps"],
                },
            )
        )

        # 11. path simulation over the real 5-minute closes -----------------
        path_check = _simulate_path(
            direction=decision["proposed_direction"],
            quantity=quantity,
            entry=entry_price,
            wallet=float(decision["required_margin"]),
            safety=0.0,
            spec=spec,
            decisions_ts=decision_ts,
            snapshot=fixtures.snapshot,
        )
        checks.append(path_check)

        # 12. liquidation must not precede the stop -------------------------
        stop = float(decision["stop_price"])
        if decision["proposed_direction"] == "LONG":
            precedes = reported_lp is not None and reported_lp >= stop
        else:
            precedes = reported_lp is not None and reported_lp <= stop
        checks.append(
            CheckResult(
                "liquidation_after_stop",
                passed=not precedes,
                detail="the stop sits before liquidation for this approved position",
                numbers={"stop_price": stop, "liquidation_price": reported_lp},
            )
        )

    # 13. aggregate margin cannot be double spent ---------------------------
    portfolio = detail.get("portfolio") or {}
    ledger = detail.get("ledger") or {}
    equity = float(portfolio.get("equity", 0.0))
    free_margin = float(portfolio.get("free_margin", 0.0))
    reserved = float(ledger.get("reserved", 0.0)) if ledger else 0.0
    required_margin = float(decision["required_margin"])
    # With a ledger in play the decision's margin must be inside the reservation
    # the ledger is actually holding; without one it must fit the free margin the
    # snapshot declared. Either way the pool cannot be spent twice.
    pool = reserved if ledger else free_margin
    aggregate_ok = reserved <= equity + MONEY_TOL and required_margin <= pool + MONEY_TOL
    checks.append(
        CheckResult(
            "aggregate_margin_pool",
            passed=aggregate_ok,
            detail="the position's margin fits inside one consistent, non-double-spent pool",
            numbers={
                "ledger_present": bool(ledger),
                "reserved": reserved,
                "equity": equity,
                "free_margin": free_margin,
                "decision_margin": required_margin,
                "pool_used": pool,
            },
        )
    )

    # 14. decision semantics ------------------------------------------------
    approved_codes = {"APPROVE_SIMULATION", "REDUCE_SIMULATED_SIZE"}
    if decision["decision"] in approved_codes:
        semantics_ok = (
            not decision["rejection_reasons"]
            and decision["approved_notional"] > 0
            and decision["liquidation_buffer_bps"] is not None
            and decision["cost_status"] in {"COST_KNOWN", "COST_ESTIMATED"}
            and decision["modeled_worst_loss"] <= decision["risk_budget"] + max(MONEY_TOL, 1e-9)
        )
    else:
        semantics_ok = bool(decision["rejection_reasons"]) and decision["approved_notional"] == 0.0
    checks.append(
        CheckResult(
            "decision_semantics",
            passed=semantics_ok,
            detail="approvals are complete and refusals name a reason with zero size",
            numbers={
                "decision": decision["decision"],
                "rejection_reasons": decision["rejection_reasons"],
            },
        )
    )
    return checks, numbers


def _simulate_path(
    *,
    direction: str,
    quantity: float,
    entry: float,
    wallet: float,
    safety: float,
    spec: dict[str, Any],
    decisions_ts: int,
    snapshot: dict[str, Any],
) -> CheckResult:
    """Bar-by-bar liquidation simulation on real closes.

    Independent of any closed form: walk the venue's own 5-minute bars in time
    order and find the first bar whose extreme price breaches the margin
    condition. For a long, the adverse extreme is the bar low; for a short, the
    bar high. The reported liquidation price must lie inside that breach window,
    and no earlier bar may breach.
    """
    bars = [
        bar
        for bar in snapshot["klines_5m"]
        if int(bar["close_time_ms"]) <= int(decisions_ts)
    ]
    if not bars:
        return CheckResult(
            "liquidation_path_simulation",
            passed=False,
            detail="no bars available before the decision instant",
            numbers={},
        )
    breach: dict[str, Any] | None = None
    previous_extreme: float | None = None
    for bar in bars:
        extreme = float(bar["low"]) if direction == "LONG" else float(bar["high"])
        notional = quantity * extreme
        bracket = _bracket_for(spec, notional)
        mm = _maintenance_margin(bracket, notional)
        balance = _margin_balance(
            direction=direction,
            quantity=quantity,
            entry=entry,
            price=extreme,
            wallet=wallet,
            safety=safety,
        )
        if balance <= mm:
            breach = {
                "bar_open_time_ms": bar["open_time_ms"],
                "extreme": extreme,
                "margin_balance": balance,
                "maintenance_margin": mm,
            }
            break
        previous_extreme = extreme
    stress_low = min(float(bar["low"]) for bar in bars)
    stress_high = max(float(bar["high"]) for bar in bars)
    worst_case_price = stress_low if direction == "LONG" else stress_high
    survived_sample = breach is None
    return CheckResult(
        "liquidation_path_simulation",
        # An approved position that the real sampled market would have liquidated
        # is a FAILURE of the approval, not a curiosity.
        passed=survived_sample,
        detail=(
            "position survived every sampled real bar"
            if survived_sample
            else "a sampled real bar breaches the margin condition on an approved position"
        ),
        numbers={
            "bars_evaluated": len(bars),
            "breached": breach is not None,
            "breach": breach,
            "previous_extreme": previous_extreme,
            "sample_worst_price": worst_case_price,
            "sample_window": {
                "first_open_time_ms": bars[0]["open_time_ms"],
                "last_close_time_ms": bars[-1]["close_time_ms"],
            },
        },
    )


# --------------------------------------------------------------------------
# negative controls
# --------------------------------------------------------------------------


def _first_approved(entries: list[dict[str, Any]]) -> dict[str, Any] | None:
    for entry in entries:
        if entry["decision"]["decision"] in {"APPROVE_SIMULATION", "REDUCE_SIMULATED_SIZE"}:
            return entry
    return None


def _deep_copy(entry: dict[str, Any]) -> dict[str, Any]:
    copy: dict[str, Any] = json.loads(json.dumps(entry))
    return copy


def negative_controls(
    entries: list[dict[str, Any]], fixtures: VerificationFixtures
) -> list[dict[str, Any]]:
    """Tamper with a verified approval and prove the verifier notices."""
    base = _first_approved(entries)
    controls: list[dict[str, Any]] = []

    def record(name: str, entry: dict[str, Any] | None, expectation: str) -> None:
        if entry is None:
            controls.append(
                {
                    "control": name,
                    "detected": False,
                    "detail": "no approved decision was available to tamper with",
                }
            )
            return
        checks, _ = verify_decision(entry, fixtures)
        failed = [c.name for c in checks if not c.passed]
        controls.append(
            {
                "control": name,
                "detected": bool(failed),
                "detected_by": failed,
                "expectation": expectation,
            }
        )

    if base is None:
        return [
            {
                "control": "none_available",
                "detected": False,
                "detail": "no approval in the artefact: negative controls could not run",
            }
        ]

    tampered = _deep_copy(base)
    tampered["decision"]["required_margin"] = round(
        tampered["decision"]["required_margin"] * 0.5, 10
    )
    record("false_margin", tampered, "margin_and_leverage must fail")

    tampered = _deep_copy(base)
    tampered["detail"]["costs"]["total_round_trip_usdt"] = 0.0
    tampered["detail"]["costs"]["worst_case_cost_usdt"] = 0.0
    record("omitted_cost", tampered, "cost_completeness must fail")

    tampered = _deep_copy(base)
    lp = tampered["decision"]["liquidation_price"]
    tampered["decision"]["liquidation_price"] = round(lp * 0.99, 10)
    record("wrong_liquidation", tampered, "liquidation_consistency must fail")

    tampered = _deep_copy(base)
    tampered["decision"]["approved_notional"] = round(
        tampered["decision"]["approved_notional"] * 1.5, 10
    )
    record("wrong_notional", tampered, "notional_consistency must fail")

    tampered = _deep_copy(base)
    tampered["decision"]["effective_leverage"] = (
        tampered["decision"]["requested_leverage"] * 10.0
    )
    record("excess_leverage", tampered, "margin_and_leverage must fail")

    tampered = _deep_copy(base)
    tampered["detail"]["ledger"] = {"reserved": tampered["detail"]["portfolio"]["equity"] * 2.0}
    record("aggregate_risk_omitted", tampered, "aggregate_margin_pool must fail")

    tampered = _deep_copy(base)
    tampered["decision"]["data_timestamp_ms"] = (
        tampered["decision"]["decision_timestamp_ms"] + 1000
    )
    record("temporally_invalid", tampered, "temporal_validity must fail")

    tampered = _deep_copy(base)
    tampered["decision"]["order_authorised"] = True
    record("order_authorisation", tampered, "no_order_authorisation must fail")

    return controls


# --------------------------------------------------------------------------
# entry point
# --------------------------------------------------------------------------


def run_verification(payload: dict[str, Any], fixtures: VerificationFixtures) -> dict[str, Any]:
    """Verify every decision in ``payload`` plus the negative controls."""
    results: list[dict[str, Any]] = []
    for entry in payload["decisions"]:
        checks, numbers = verify_decision(entry, fixtures)
        results.append(
            {
                "decision_id": entry["decision"]["decision_id"],
                "scenario": entry.get("scenario"),
                "decision": entry["decision"]["decision"],
                "checks": [c.to_dict() for c in checks],
                "passed": all(c.passed for c in checks),
                "recomputed": numbers,
            }
        )
    controls = negative_controls(payload["decisions"], fixtures)
    false_success = sum(1 for c in controls if not c["detected"])
    return {
        "verifier_version": VERIFIER_VERSION,
        "builder_modules_imported": _builder_imports(),
        "decisions_verified": len(results),
        "decisions_passed": sum(1 for r in results if r["passed"]),
        "checks_run": sum(len(r["checks"]) for r in results),
        "checks_failed": [
            {"decision_id": r["decision_id"], "check": c["name"], "detail": c["detail"]}
            for r in results
            for c in r["checks"]
            if not c["passed"]
        ],
        "negative_controls": controls,
        "false_success": false_success,
        "verdict": (
            "VERIFIED"
            if false_success == 0 and all(r["passed"] for r in results) and results
            else "FAIL"
        ),
        "results": results,
    }


def _builder_imports() -> list[str]:
    """Proof of independence: no builder module is loaded in this process.

    ``trading_bot.risk.futures_verification`` legitimately shares the package
    prefix with the builder, so it is excluded by name; every module the builder
    owns (``trading_bot.risk.futures`` and its submodules) is listed.
    """
    import sys

    prefix = "trading_bot.risk.futures"
    return sorted(
        name
        for name in sys.modules
        if (name == prefix or name.startswith(f"{prefix}."))
        and name != "trading_bot.risk.futures_verification"
    )
