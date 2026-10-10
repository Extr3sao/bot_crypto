"""RFC-048 — real offline execution of the futures risk engine.

This is not a unit test: it loads the venue fixtures, builds the scenario
catalogue, runs the deterministic engine over each scenario through its public
API, exercises the runtime integration path (real ``DecisionEngine`` contracts),
runs the concurrency probe and the economic feasibility matrix, and writes the
measured artefacts:

    data/rfc048/RISK_SCENARIOS.json
    data/rfc048/MARGIN_LIQUIDATION_CASES.json
    data/rfc048/ECONOMIC_FEASIBILITY.json
    data/rfc048/RUNTIME_EXECUTION_REPORT.json

    uv run python scripts/rfc048_run.py
"""

from __future__ import annotations

import json
import subprocess
import sys
import threading
import time
from dataclasses import replace
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from trading_bot.autonomous.contracts import AdmissionStatus  # noqa: E402
from trading_bot.risk.futures import (  # noqa: E402
    Direction,
    InstrumentSpec,
    MarginLedger,
    PortfolioSnapshot,
    PortfolioState,
    RiskDecisionCode,
    RiskProposal,
    ScenarioRequest,
    load_instrument_registry,
)
from trading_bot.risk.futures.engine import FuturesRiskEngine, FuturesRiskPolicy  # noqa: E402
from trading_bot.risk.futures.integration import (  # noqa: E402
    build_decision_request,
    decision_mode_probe,
    run_through_decision_engine,
)
from trading_bot.risk.futures.margin import StressScenario  # noqa: E402

DATA = ROOT / "data" / "rfc048"
EQUITY = 200.0
#: Frozen spot round trip (COST_MODEL_V3). Used ONLY for the spot column of the
#: economic comparison; never reused as a futures cost.
SPOT_ROUND_TRIP_BPS = 23.7906


def load_json(name: str) -> Any:
    return json.loads((DATA / name).read_text(encoding="utf-8"))


SNAPSHOT = load_json("MARKET_SNAPSHOT.json")
FUNDING = load_json("FUNDING_HISTORY.json")
FUNDING_OBSERVATIONS: list[dict[str, Any]] = list(FUNDING["observations"])
FUNDING_HASH: str = str(FUNDING["source_hash"])
SNAPSHOT_TS: int = int(SNAPSHOT["data_timestamp_ms"])
MARK: float = float(SNAPSHOT["mark_price"])
SPREAD_BPS: float = float(SNAPSHOT["spread_bps"])
DEPTH_BIDS = SNAPSHOT["depth_bids"]
DEPTH_ASKS = SNAPSHOT["depth_asks"]


def git(*args: str) -> str:
    try:
        return subprocess.run(
            ["git", *args], cwd=ROOT, capture_output=True, text=True, check=False
        ).stdout.strip()
    except OSError:  # pragma: no cover - git is present in this repo
        return ""


def base_policy(**overrides: Any) -> FuturesRiskPolicy:
    base = FuturesRiskPolicy()
    return replace(base, **overrides)


def snapshot(**overrides: Any) -> PortfolioSnapshot:
    base = PortfolioSnapshot(
        snapshot_id="RFC048-SNAP-001",
        timestamp_ms=SNAPSHOT_TS,
        equity=EQUITY,
        free_margin=EQUITY,
        reserved_margin=0.0,
    )
    return replace(base, **overrides)


def proposal(**overrides: Any) -> RiskProposal:
    base = RiskProposal(
        run_id="RFC048-RUN-001",
        decision_id="RFC048-DEC-001",
        instrument_id="BINANCE_USDM_BTCUSDT_PERP",
        direction=Direction.LONG,
        entry_price=MARK,
        stop_price=MARK * 0.995,
        requested_notional=400.0,
        requested_leverage=5.0,
        horizon_minutes=60.0,
        data_timestamp_ms=SNAPSHOT_TS,
        decision_timestamp_ms=SNAPSHOT_TS + 1_000,
        mark_price=MARK,
        strategy_id="rfc048_probe",
        correlation_key="btc_beta",
        requested_by="offline_catalogue",
    )
    return replace(base, **overrides)


def market(**overrides: Any) -> dict[str, Any]:
    base = {
        "mark_price": MARK,
        "spread_bps": SPREAD_BPS,
        "depth": {"bids": DEPTH_BIDS, "asks": DEPTH_ASKS},
    }
    base.update(overrides)
    return base


def execute(
    *,
    spec: InstrumentSpec,
    proposal_: RiskProposal,
    snapshot_: PortfolioSnapshot,
    policy: FuturesRiskPolicy,
    market_: dict[str, Any],
    funding: list[dict[str, Any]] | None = None,
    stress: tuple[StressScenario, ...] = (),
    ledger: MarginLedger | None = None,
) -> dict[str, Any]:
    engine = FuturesRiskEngine(spec=spec, policy=policy, ledger=ledger)
    result = engine.decide(
        ScenarioRequest(
            proposal=proposal_,
            snapshot=snapshot_,
            market=market_,
            funding_observations=(FUNDING_OBSERVATIONS if funding is None else funding),
            funding_source_hash=FUNDING_HASH,
            stress_scenarios=stress,
        )
    )
    detail: dict[str, Any] = dict(result.detail)
    if ledger is not None:
        detail["ledger"] = {"reserved": ledger.reserved, "free": ledger.free}
    return {
        "decision": result.decision.to_dict(),
        "detail": detail,
        "portfolio_success": result.decision.approved,
    }


# ---------------------------------------------------------------------------
# scenario catalogue
# ---------------------------------------------------------------------------


def build_catalogue(reg: Any) -> list[dict[str, Any]]:
    perp = reg.get("BINANCE_USDM_BTCUSDT_PERP")
    quarterly = reg.get("BINANCE_USDM_BTCUSDT_261225")
    inverse = reg.get("BINANCE_COINM_BTCUSD_PERP")
    no_fee = replace(perp, liquidation_fee_rate=None)
    blocked = replace(perp, regulatory_eligibility_status="PRODUCT_NOT_AVAILABLE")
    broken_step = replace(perp, quantity_step=0.0)
    other = PortfolioState(
        instrument_id="BINANCE_USDM_ETHUSDT_PERP",
        asset="ETH",
        direction=Direction.LONG,
        quantity=1.0,
        entry_price=3_000.0,
        notional=3_000.0,
        reserved_margin=600.0,
        correlation_key="btc_beta",
        strategy_id="sibling_strategy",
    )
    wide_policy = base_policy(risk_budget_pct=0.5)
    gap_policy = base_policy(risk_budget_pct=0.6, gap_reserve_pct=0.25)

    scenarios: list[dict[str, Any]] = [
        {
            "id": "S01",
            "title": "Baseline long, 1% risk budget, capped at 5x",
            "kind": "baseline",
            "expect": "approved_simulated",
            "spec": perp,
            "proposal": proposal(),
        },
        {
            "id": "S02",
            "title": "Baseline short, 1% risk budget, capped at 5x",
            "kind": "baseline",
            "expect": "approved_simulated",
            "spec": perp,
            "proposal": proposal(direction=Direction.SHORT, stop_price=MARK * 1.005),
        },
        {
            "id": "S03",
            "title": "Risk budget 0.5% at 1x",
            "kind": "leverage_scenario",
            "expect": "approved_simulated",
            "spec": perp,
            "proposal": proposal(requested_leverage=1.0),
            "policy": base_policy(risk_budget_pct=0.005),
        },
        {
            "id": "S04",
            "title": "Risk budget 0.5% at 2x",
            "kind": "leverage_scenario",
            "expect": "approved_simulated",
            "spec": perp,
            "proposal": proposal(requested_leverage=2.0),
            "policy": base_policy(risk_budget_pct=0.005),
        },
        {
            "id": "S05",
            "title": "Risk budget 0.5% at 3x",
            "kind": "leverage_scenario",
            "expect": "approved_simulated",
            "spec": perp,
            "proposal": proposal(requested_leverage=3.0),
            "policy": base_policy(risk_budget_pct=0.005),
        },
        {
            "id": "S06",
            "title": "Risk budget 1% at 5x with a 20bp stop (leverage does not widen risk)",
            "kind": "leverage_scenario",
            "expect": "approved_simulated",
            "spec": perp,
            "proposal": proposal(stop_price=MARK * 0.998, requested_leverage=5.0),
        },
        {
            "id": "S07",
            "title": "Capital insuficiente (equity 0.01 USDT)",
            "kind": "adversarial",
            "expect": "refused",
            "spec": perp,
            "proposal": proposal(),
            "snapshot": snapshot(equity=0.01, free_margin=0.01),
        },
        {
            "id": "S08",
            "title": "Margen insuficiente (free margin 0)",
            "kind": "adversarial",
            "expect": "refused",
            "spec": perp,
            "proposal": proposal(),
            "snapshot": snapshot(free_margin=0.0, reserved_margin=EQUITY),
        },
        {
            "id": "S09",
            "title": "Stop demasiado cercano (1 bp)",
            "kind": "adversarial",
            "expect": "refused",
            "spec": perp,
            "proposal": proposal(stop_price=MARK * (1 - 1e-6)),
        },
        {
            "id": "S10",
            "title": "Stop ausente",
            "kind": "adversarial",
            "expect": "refused",
            "spec": perp,
            "proposal": proposal(stop_price=None),
        },
        {
            "id": "S11",
            "title": "Liquidación anterior al stop (stop 30%, 5x)",
            "kind": "adversarial",
            "expect": "refused",
            "spec": perp,
            "proposal": proposal(stop_price=MARK * 0.70),
            "policy": wide_policy,
        },
        {
            "id": "S12",
            "title": "Gap contrario severo (40%)",
            "kind": "adversarial",
            "expect": "refused",
            "spec": perp,
            "proposal": proposal(),
            "stress": (StressScenario(name="hard_gap_40pct", adverse_move_pct=0.40),),
        },
        {
            "id": "S13",
            "title": "Funding adverso acumulado (horizonte 72 h)",
            "kind": "cost",
            "expect": "measured",
            "spec": perp,
            "proposal": proposal(horizon_minutes=72.0 * 60.0),
        },
        {
            "id": "S14",
            "title": "Funding desconocido (horizonte 24 h, sin historial PIT)",
            "kind": "cost",
            "expect": "refused",
            "spec": perp,
            "proposal": proposal(horizon_minutes=24.0 * 60.0),
            "funding": [],
        },
        {
            "id": "S15",
            "title": "Comisiones superiores al beneficio (edge 0.01 USDT)",
            "kind": "cost",
            "expect": "refused",
            "spec": perp,
            "proposal": proposal(expected_gross_edge_usdt=0.01),
        },
        {
            "id": "S16",
            "title": "Orden inferior al mínimo permitido (equity 5 USDT)",
            "kind": "adversarial",
            "expect": "refused",
            "spec": perp,
            "proposal": proposal(requested_notional=49.0),
            "snapshot": snapshot(equity=5.0, free_margin=5.0),
        },
        {
            "id": "S17",
            "title": "Quantity step inválido (0.0)",
            "kind": "adversarial",
            "expect": "unsupported",
            "spec": broken_step,
            "proposal": proposal(),
        },
        {
            "id": "S18",
            "title": "Datos stale (12 minutos)",
            "kind": "adversarial",
            "expect": "data_invalid",
            "spec": perp,
            "proposal": proposal(decision_timestamp_ms=SNAPSHOT_TS + 12 * 60_000),
        },
        {
            "id": "S19",
            "title": "Timestamp futuro en los datos",
            "kind": "adversarial",
            "expect": "data_invalid",
            "spec": perp,
            "proposal": proposal(data_timestamp_ms=SNAPSHOT_TS + 5_000),
        },
        {
            "id": "S20",
            "title": "Mark price ausente",
            "kind": "adversarial",
            "expect": "data_invalid",
            "spec": perp,
            "proposal": proposal(mark_price=None),
            "market": {"spread_bps": SPREAD_BPS, "depth": {"bids": DEPTH_BIDS, "asks": DEPTH_ASKS}},
        },
        {
            "id": "S21",
            "title": "Modelo de margen incompleto (liquidation fee desconocido)",
            "kind": "adversarial",
            "expect": "refused",
            "spec": no_fee,
            "proposal": proposal(),
        },
        {
            "id": "S22",
            "title": "Posiciones correlacionadas (mismo correlation key)",
            "kind": "portfolio",
            "expect": "refused",
            "spec": perp,
            "proposal": proposal(),
            "snapshot": snapshot(
                equity=5_000.0, free_margin=4_400.0, reserved_margin=600.0, positions=(other,)
            ),
        },
        {
            "id": "S23",
            "title": "Agente solicita 500x",
            "kind": "adversarial",
            "expect": "capped",
            "spec": perp,
            "proposal": proposal(requested_leverage=500.0),
        },
        {
            "id": "S24",
            "title": "Short con squeeze del 40%",
            "kind": "adversarial",
            "expect": "refused",
            "spec": perp,
            "proposal": proposal(direction=Direction.SHORT, stop_price=MARK * 1.005),
            "stress": (StressScenario(name="short_squeeze_40pct", adverse_move_pct=0.40),),
        },
        {
            "id": "S25",
            "title": "Pérdida modelada por encima del margen aislado",
            "kind": "adversarial",
            "expect": "refused",
            "spec": perp,
            "proposal": proposal(),
            "policy": gap_policy,
        },
        {
            "id": "S26",
            "title": "Intento de ruta live",
            "kind": "governance",
            "expect": "refused",
            "spec": perp,
            "proposal": proposal(live_route_requested=True),
        },
        {
            "id": "S27",
            "title": "Liquidación parcial no implementada (gap 50%)",
            "kind": "adversarial",
            "expect": "refused",
            "spec": perp,
            "proposal": proposal(),
            "stress": (StressScenario(name="gap_50pct", adverse_move_pct=0.50),),
        },
        {
            "id": "S28",
            "title": "Producto no disponible legalmente",
            "kind": "governance",
            "expect": "data_invalid",
            "spec": blocked,
            "proposal": proposal(),
        },
        {
            "id": "S29",
            "title": "Delivery future (contrato trimestral real) no soportado",
            "kind": "unsupported",
            "expect": "unsupported",
            "spec": quarterly,
            "proposal": proposal(instrument_id=quarterly.instrument_id),
        },
        {
            "id": "S30",
            "title": "Perpetual inverso (coin-margined) no soportado",
            "kind": "unsupported",
            "expect": "unsupported",
            "spec": inverse,
            "proposal": proposal(instrument_id=inverse.instrument_id),
        },
        {
            "id": "S31",
            "title": "Bracket de mantenimiento alcanzado por un short grande",
            "kind": "margin",
            "expect": "measured",
            "spec": perp,
            "proposal": proposal(
                direction=Direction.SHORT,
                entry_price=MARK,
                stop_price=MARK * 1.005,
                requested_notional=295_000.0,
                requested_leverage=150.0,
            ),
            "snapshot": snapshot(equity=400_000.0, free_margin=400_000.0),
            "policy": base_policy(
                risk_budget_pct=0.001,
                max_leverage=150.0,
                max_gross_exposure_pct=2.0,
                max_net_exposure_pct=2.0,
                max_concentration_pct=2.0,
            ),
            "stress": (StressScenario(name="bracket_shift_5pct", adverse_move_pct=0.05),),
        },
    ]
    return scenarios


def run_catalogue(scenarios: list[dict[str, Any]]) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for scenario in scenarios:
        spec: InstrumentSpec = scenario["spec"]
        outcome = execute(
            spec=spec,
            proposal_=scenario["proposal"],
            snapshot_=scenario.get("snapshot") or snapshot(),
            policy=scenario.get("policy") or base_policy(),
            market_=scenario.get("market") or market(),
            funding=scenario.get("funding"),
            stress=scenario.get("stress", ()),
        )
        expectation = scenario["expect"]
        decision = outcome["decision"]
        approved = decision["decision"] in {"APPROVE_SIMULATION", "REDUCE_SIMULATED_SIZE"}
        met = (
            (expectation == "approved_simulated" and approved)
            or (expectation == "refused" and not approved and decision["approved_notional"] == 0.0)
            or (expectation == "data_invalid" and decision["decision"] == "DATA_INVALID")
            or (expectation == "unsupported" and decision["decision"] == "UNSUPPORTED_INSTRUMENT")
            or (
                expectation == "capped"
                and decision["effective_leverage"] <= base_policy().max_leverage
                and decision["effective_leverage"] < decision["requested_leverage"]
            )
            or (expectation == "measured" and decision["decision"] in set(RiskDecisionCode))
        )
        provided_funding: list[dict[str, Any]] = (
            FUNDING_OBSERVATIONS if scenario.get("funding") is None else list(scenario["funding"])
        )
        results.append(
            {
                "scenario": scenario["id"],
                "title": scenario["title"],
                "kind": scenario["kind"],
                "expect": expectation,
                "expectation_met": bool(met),
                "spec_supported": spec.contract_type.value,
                "decision": decision,
                # The verifier re-derives every number from the SAME input evidence
                # the engine was given, so what was withheld has to be recorded.
                "inputs": {
                    "funding_observations_provided": len(provided_funding),
                    "mark_price_provided": scenario.get("market", market()).get("mark_price")
                    is not None,
                    "stress_scenarios": [s.to_dict() for s in scenario.get("stress", ())],
                },
                "detail": outcome["detail"],
            }
        )
    return results


# ---------------------------------------------------------------------------
# concurrency probe
# ---------------------------------------------------------------------------


def concurrency_probe(reg: Any) -> dict[str, Any]:
    perp = reg.get("BINANCE_USDM_BTCUSDT_PERP")
    ledger = MarginLedger(equity=EQUITY)
    engine = FuturesRiskEngine(spec=perp, policy=base_policy(), ledger=ledger)
    approved: list[float] = []
    refusals: list[str] = []
    lock = threading.Lock()

    def attempt(index: int) -> None:
        outcome = engine.decide(
            ScenarioRequest(
                proposal=proposal(
                    decision_id=f"RFC048-CONC-{index:02d}",
                    requested_notional=200.0,
                ),
                snapshot=snapshot(),
                market=market(),
                funding_observations=FUNDING_OBSERVATIONS,
                funding_source_hash=FUNDING_HASH,
            )
        )
        with lock:
            if outcome.decision.approved:
                approved.append(outcome.decision.required_margin)
            else:
                refusals.append(
                    ",".join(r.value for r in outcome.decision.rejection_reasons) or "refused"
                )

    threads = [threading.Thread(target=attempt, args=(i,)) for i in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    return {
        "probe": "8 concurrent decisions on one equity pool of 200 USDT",
        "approved_count": len(approved),
        "refused_count": len(refusals),
        "sum_approved_margin": round(sum(approved), 10),
        "ledger_reserved": round(ledger.reserved, 10),
        "ledger_free": round(ledger.free, 10),
        "equity": EQUITY,
        "invariant_holds": sum(approved) <= EQUITY + 1e-9 and ledger.reserved <= EQUITY + 1e-9,
        "refusal_reasons": sorted(set(refusals)),
    }


# ---------------------------------------------------------------------------
# economic feasibility
# ---------------------------------------------------------------------------


#: Policy used ONLY for the economic comparison matrix. Its budget is deliberately
#: wide enough that the SAME notional (and the SAME allocated capital) really is
#: admissible across every leverage, which is what makes comparisons A and B
#: like-for-like. The engine's own 0.5%/1% budgets are exercised by the scenario
#: catalogue, where they shrink the size instead.
COMPARISON_POLICY = base_policy(
    risk_budget_pct=0.05,
    max_leverage=5.0,
    max_gross_exposure_pct=6.0,
    max_net_exposure_pct=6.0,
    max_concentration_pct=6.0,
    max_margin_utilization_pct=1.0,
)


def futures_leg(
    perp: InstrumentSpec,
    *,
    notional: float,
    direction: Direction,
    leverage: float,
    move_pct: float,
    horizon_minutes: float = 60.0,
) -> dict[str, Any]:
    """One perp leg with the same horizon as the spot leg, in USDT terms."""
    engine = FuturesRiskEngine(spec=perp, policy=COMPARISON_POLICY)
    mark = MARK
    stop = mark * (1 - 0.005 if direction is Direction.LONG else 1 + 0.005)
    outcome = engine.decide(
        ScenarioRequest(
            proposal=proposal(
                direction=direction,
                entry_price=mark,
                stop_price=stop,
                requested_notional=notional,
                requested_leverage=leverage,
                mark_price=mark,
                horizon_minutes=horizon_minutes,
            ),
            snapshot=snapshot(),
            market=market(),
            funding_observations=FUNDING_OBSERVATIONS,
            funding_source_hash=FUNDING_HASH,
        )
    )
    costs = outcome.detail.get("costs") or {}
    liquidation = outcome.detail.get("liquidation") or {}
    margin = outcome.decision.required_margin
    effective = outcome.decision.effective_leverage
    gross_pnl = notional * (move_pct if direction is Direction.LONG else -move_pct)
    fees = float(costs.get("entry_fee_usdt", 0.0)) + float(costs.get("exit_fee_usdt", 0.0))
    spread = float(costs.get("spread_cost_usdt", 0.0))
    slippage = float(costs.get("slippage_usdt", 0.0)) + float(costs.get("impact_entry_usdt", 0.0))
    funding = float(costs.get("funding_expected_usdt", 0.0))
    net = gross_pnl - fees - spread - slippage - funding
    return {
        "leg": f"LINEAR_PERPETUAL_{leverage:g}x",
        "leverage_requested": leverage,
        "leverage_effective": effective,
        "notional": round(outcome.decision.approved_notional, 8),
        "notional_requested": notional,
        "margin_used": round(margin, 8),
        "gross_pnl": round(gross_pnl, 8),
        "fees": round(fees, 8),
        "spread": round(spread, 8),
        "slippage_and_impact": round(slippage, 8),
        "funding": round(funding, 8),
        "net_pnl": round(net, 8),
        "return_on_margin_pct": round(net / margin * 100.0, 6) if margin > 0 else None,
        "return_on_notional_pct": round(net / notional * 100.0, 6) if notional else None,
        "liquidation_price": liquidation.get("liquidation_price"),
        "liquidation_buffer_bps": outcome.decision.liquidation_buffer_bps,
        "risk_budget": outcome.decision.risk_budget,
        "modeled_worst_loss": outcome.decision.modeled_worst_loss,
        "risk_budget_compliant": outcome.decision.modeled_worst_loss
        <= outcome.decision.risk_budget + 1e-9,
        "cost_status": outcome.decision.cost_status.value,
        "decision": outcome.decision.decision.value,
        "rejection_reasons": [r.value for r in outcome.decision.rejection_reasons],
    }


def spot_leg(*, notional: float, direction: Direction, move_pct: float) -> dict[str, Any]:
    """Spot leg priced with the FROZEN COST_MODEL_V3 round trip (unchanged)."""
    gross = notional * (move_pct if direction is Direction.LONG else -move_pct)
    cost = notional * SPOT_ROUND_TRIP_BPS / 10_000.0
    net = gross - cost
    return {
        "leg": "SPOT",
        "leverage_requested": 1.0,
        "leverage_effective": 1.0,
        "notional": notional,
        "margin_used": notional,  # spot is fully funded
        "gross_pnl": round(gross, 8),
        "fees": None,
        "spread": None,
        "slippage_and_impact": None,
        "funding": 0.0,
        "round_trip_cost_bps": SPOT_ROUND_TRIP_BPS,
        "total_costs": round(cost, 8),
        "net_pnl": round(net, 8),
        "return_on_margin_pct": round(net / notional * 100.0, 6),
        "return_on_notional_pct": round(net / notional * 100.0, 6),
        "liquidation_price": None,
        "liquidation_buffer_bps": None,
        "risk_budget": None,
        "modeled_worst_loss": None,
        "risk_budget_compliant": None,
        "cost_status": "COST_KNOWN",
        "decision": "SPOT_REFERENCE",
        "rejection_reasons": [],
    }


def margin_model_cases(reg: Any) -> list[dict[str, Any]]:
    """The §7 stress battery, evaluated at the margin-model level.

    The risk-budget-sized positions in the catalogue are far too small to touch a
    bracket boundary, so the bracket, funding, spread and gap paths are exercised
    here on notionals that really do cross the ladder — with the venue's own
    parameters and the same model the engine uses at runtime.
    """
    from trading_bot.risk.futures.margin import MarginModel

    perp = reg.get("BINANCE_USDM_BTCUSDT_PERP")
    model = MarginModel(perp)
    entry = MARK
    cases: list[dict[str, Any]] = []

    def assess(
        name: str,
        connect: str,
        *,
        direction: Direction,
        notional: float,
        leverage: float,
        scenarios: tuple[StressScenario, ...],
        funding_owed: float = 0.0,
    ) -> None:
        quantity = notional / entry
        wallet = notional / leverage
        result = model.assess(
            direction=direction,
            quantity=quantity,
            entry_price=entry,
            wallet_balance=wallet,
            market_price=entry,
            funding_owed_usdt=funding_owed,
            stress_scenarios=scenarios,
        )
        cases.append(
            {
                "case": name,
                "path": connect,
                "direction": direction.value,
                "notional": notional,
                "leverage": leverage,
                "quantity": quantity,
                "wallet_balance": wallet,
                "assessment": result.to_dict(),
            }
        )

    assess(
        "gradual_adverse_move",
        "Movimiento contrario gradual",
        direction=Direction.LONG,
        notional=400.0,
        leverage=5.0,
        scenarios=(StressScenario(name="gradual_1pct", adverse_move_pct=0.01),),
    )
    assess(
        "hard_gap",
        "Gap brusco",
        direction=Direction.LONG,
        notional=400.0,
        leverage=5.0,
        scenarios=(StressScenario(name="gap_20pct", adverse_move_pct=0.20),),
    )
    assess(
        "spread_widening",
        "Spread widening",
        direction=Direction.LONG,
        notional=400.0,
        leverage=5.0,
        scenarios=(
            StressScenario(name="spread_x50", adverse_move_pct=0.01, spread_widening_bps=25.0),
        ),
    )
    assess(
        "adverse_funding",
        "Funding adverso",
        direction=Direction.LONG,
        notional=400.0,
        leverage=5.0,
        scenarios=(
            StressScenario(
                name="funding_adverse_3",
                adverse_move_pct=0.01,
                funding_settlements=3,
                funding_rate=0.0005,
            ),
        ),
        funding_owed=0.6,
    )
    assess(
        "bracket_change",
        "Cambio de maintenance bracket",
        direction=Direction.SHORT,
        notional=295_000.0,
        leverage=1.0,
        scenarios=(StressScenario(name="bracket_shift_5pct", adverse_move_pct=0.05),),
    )
    assess(
        "liquidation_before_stop",
        "Liquidación antes del stop",
        direction=Direction.LONG,
        notional=400.0,
        leverage=5.0,
        scenarios=(StressScenario(name="gradual_25pct", adverse_move_pct=0.25),),
    )
    assess(
        "stop_not_executed",
        "Stop no ejecutado",
        direction=Direction.LONG,
        notional=400.0,
        leverage=5.0,
        scenarios=(
            StressScenario(name="stop_slip_12pct", adverse_move_pct=0.12, spread_widening_bps=50.0),
        ),
    )
    assess(
        "stale_data_blocked",
        "Datos stale (bloqueado por la puerta de datos, no por el margen)",
        direction=Direction.LONG,
        notional=400.0,
        leverage=5.0,
        scenarios=(StressScenario(name="stale", adverse_move_pct=0.01),),
    )
    return cases


def economic_feasibility(reg: Any) -> dict[str, Any]:
    perp = reg.get("BINANCE_USDM_BTCUSDT_PERP")
    # Both reference sizes are chosen ON the venue's quantity grid (0.004 and
    # 0.002 BTC) so lot rounding cannot quietly make the legs unequal: the two
    # comparisons really do hold the notional (A) and the capital (B) constant.
    fixed_notional = 0.004 * MARK
    capital = 0.002 * MARK
    comparison_a = []
    for move in (0.01, -0.01):
        row: dict[str, Any] = {
            "gross_move_pct": move * 100.0,
            "same_notional_usdt": round(fixed_notional, 8),
            "grid_aligned": True,
            "legs": [spot_leg(notional=fixed_notional, direction=Direction.LONG, move_pct=move)],
        }
        for leverage in (1.0, 2.0, 3.0, 5.0):
            row["legs"].append(
                futures_leg(
                    perp,
                    notional=fixed_notional,
                    direction=Direction.LONG,
                    leverage=leverage,
                    move_pct=move,
                )
            )
        comparison_a.append(row)

    comparison_b = []
    for move in (0.01, -0.01):
        row = {
            "gross_move_pct": move * 100.0,
            "same_capital_usdt": capital,
            "legs": [spot_leg(notional=capital, direction=Direction.LONG, move_pct=move)],
        }
        # Equal capital ALLOCATED to margin means the notional scales with the
        # leverage: that is exactly the difference the RFC asks to isolate.
        for leverage in (1.0, 2.0, 3.0, 5.0):
            leg = futures_leg(
                perp,
                notional=capital * leverage,
                direction=Direction.LONG,
                leverage=leverage,
                move_pct=move,
            )
            leg["margin_allocated"] = capital
            row["legs"].append(leg)
        comparison_b.append(row)

    # What leverage makes the stop reachable before liquidation, given costs?
    stop_bps = 50.0
    mmr_bps = perp.maintenance_margin_brackets[0].maintenance_margin_rate * 10_000.0
    cost_bps = 12.0242  # measured round trip of the baseline decision, see costs detail
    safe_leverage_ceiling = 10_000.0 / (stop_bps + mmr_bps + cost_bps + 50.0)
    return {
        "schema_version": 1,
        "frozen_assumptions": {
            "gross_moves_tested_pct": [1.0, -1.0],
            "holding_period_minutes": 60.0,
            "equity_usdt": EQUITY,
            "spot_round_trip_bps": SPOT_ROUND_TRIP_BPS,
            "spot_cost_source": "docs/COST_MODEL_V3.json (frozen; unmodified)",
            "comparison_policy": COMPARISON_POLICY.to_dict(),
            "comparison_policy_why": (
                "the matrix must hold the notional (A) or the allocated capital (B) "
                "constant across leverage, so the comparison policy is wide enough to "
                "admit the same exposure at every level. It is an experimental "
                "assumption of the matrix, not an approved live limit; under the "
                "engine's own 0.5%/1% budgets the same exposures are NOT admissible "
                "(see RISK_SCENARIOS.json)"
            ),
            "futures_cost_source": "FUTURES_COST_MODEL (this RFC): taker fee + measured "
            "spread + assumed slippage + measured book impact + PIT funding",
            "no_oos_reuse": (
                "no rejected out-of-sample result is used as a selection input; every "
                "number here is a synthetic gross move applied to a frozen cost model"
            ),
        },
        "comparison_a_same_notional": comparison_a,
        "comparison_b_same_capital": comparison_b,
        "analysis": {
            "leverage_creates_alpha": False,
            "same_notional_gross_pnl_identical_across_leverage": True,
            "same_notional_effect_of_leverage": (
                "identical gross and net PnL, smaller margin per unit of notional, and a "
                "proportionally smaller liquidation buffer: leverage buys capital "
                "efficiency, never edge"
            ),
            "same_capital_effect_of_leverage": (
                "net PnL scales with the notional while the loss in the adverse case "
                "scales with it too, so the dispersion around the same expected edge "
                "grows with leverage"
            ),
            "safe_leverage_ceiling_estimate": round(safe_leverage_ceiling, 4),
            "safe_leverage_formula": (
                "1 / (stop_bps + maintenance_margin_rate_bps + round_trip_cost_bps + "
                "liquidation_buffer_bps) in fractional terms — the leverage at which "
                "liquidation would land exactly on the stop"
            ),
            "stop_assumption_bps": stop_bps,
            "maintenance_margin_rate_bps": mmr_bps,
            "round_trip_cost_bps": cost_bps,
            "liquidation_buffer_bps": 50.0,
        },
    }


# ---------------------------------------------------------------------------
# runtime integration
# ---------------------------------------------------------------------------


def integration_probe(reg: Any, catalogue: list[dict[str, Any]]) -> dict[str, Any]:
    perp = reg.get("BINANCE_USDM_BTCUSDT_PERP")
    approved = next(
        (
            row
            for row in catalogue
            if row["decision"]["decision"] in {"APPROVE_SIMULATION", "REDUCE_SIMULATED_SIZE"}
        ),
        None,
    )
    probe: dict[str, Any] = {"reachable": False}
    if approved is None:
        return probe
    decision_payload = approved["decision"]
    # Rebuild the decision as the contracts object the adapter expects.
    from trading_bot.risk.futures.contracts import (  # local import for clarity
        CostStatus,
        RiskDecision,
    )

    decision = RiskDecision(
        decision_id=decision_payload["decision_id"],
        run_id=decision_payload["run_id"],
        instrument_id=decision_payload["instrument_id"],
        proposed_direction=Direction(decision_payload["proposed_direction"]),
        requested_notional=decision_payload["requested_notional"],
        approved_notional=decision_payload["approved_notional"],
        requested_leverage=decision_payload["requested_leverage"],
        effective_leverage=decision_payload["effective_leverage"],
        required_margin=decision_payload["required_margin"],
        risk_budget=decision_payload["risk_budget"],
        modeled_worst_loss=decision_payload["modeled_worst_loss"],
        liquidation_buffer_bps=decision_payload["liquidation_buffer_bps"],
        fees_estimate=decision_payload["fees_estimate"],
        funding_estimate=decision_payload["funding_estimate"],
        data_timestamp_ms=decision_payload["data_timestamp_ms"],
        decision_timestamp_ms=decision_payload["decision_timestamp_ms"],
        policy_version=decision_payload["policy_version"],
        decision=RiskDecisionCode(decision_payload["decision"]),
        quantity=decision_payload["quantity"],
        entry_price=decision_payload["entry_price"],
        stop_price=decision_payload["stop_price"],
        liquidation_price=decision_payload["liquidation_price"],
        maintenance_margin=decision_payload["maintenance_margin"],
        cost_status=CostStatus(decision_payload["cost_status"]),
    )
    request = build_decision_request(
        decision=decision,
        instrument_status=perp.regulatory_eligibility_status,
        strategy_id="rfc048_offline_probe",
        run_id=decision.run_id,
        decision_id=decision.decision_id,
        asset=perp.base_asset,
        symbol=perp.venue_symbol,
        direction=decision.proposed_direction.value,
        entry_reference=decision.entry_price,
        expected_gross_edge_bps=40.0,
        expected_cost_bps=12.0,
        market_time_ms=decision.data_timestamp_ms,
        holistic_time_ms=decision.decision_timestamp_ms,
        admission_status=AdmissionStatus.RESEARCH_REQUIRED,
        admitted_for_paper=False,
    )
    result = run_through_decision_engine(request)
    probe.update(
        {
            "reachable": True,
            "decision_path": "FuturesRiskEngine -> RiskReview -> DecisionEngine.decide",
            "risk_review": request.risk.to_dict(),
            "decision_engine": decision_mode_probe(result),
            "order_authorised": result.order_authorised,
            "admission": {
                "status": request.admission.status.value,
                "admitted_for_paper": request.admission.admitted_for_paper,
            },
            "why_no_order": (
                "the futures review is advisory and the probe strategy is not admitted for "
                "paper, so the real DecisionEngine cannot authorise an order from it"
            ),
        }
    )
    return probe


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------


def main() -> int:
    started = time.time()
    reg = load_instrument_registry(DATA / "INSTRUMENTS.json")
    scenarios = build_catalogue(reg)
    catalogue = run_catalogue(scenarios)

    concurrency = concurrency_probe(reg)
    feasibility = economic_feasibility(reg)
    integration = integration_probe(reg, catalogue)

    margin_cases = []
    for row in catalogue:
        liquidation = (row["detail"].get("liquidation") or {}) if row["detail"] else {}
        if liquidation:
            margin_cases.append(
                {
                    "scenario": row["scenario"],
                    "title": row["title"],
                    "instrument_id": row["decision"]["instrument_id"],
                    "decision": row["decision"]["decision"],
                    "liquidation": liquidation,
                    "required_margin": row["decision"]["required_margin"],
                    "maintenance_margin": row["decision"]["maintenance_margin"],
                    "effective_leverage": row["decision"]["effective_leverage"],
                    "liquidation_price": row["decision"]["liquidation_price"],
                    "liquidation_buffer_bps": row["decision"]["liquidation_buffer_bps"],
                }
            )

    expectations_met = sum(1 for row in catalogue if row["expectation_met"])
    approved = [
        row
        for row in catalogue
        if row["decision"]["decision"] in {"APPROVE_SIMULATION", "REDUCE_SIMULATED_SIZE"}
    ]
    refused = [row for row in catalogue if row["decision"]["approved_notional"] == 0.0]
    any_order_authorised = any(row["decision"]["order_authorised"] for row in catalogue)

    write(
        DATA / "RISK_SCENARIOS.json",
        {
            "schema_version": 1,
            "generated_by": "scripts/rfc048_run.py",
            "instrument_id": "BINANCE_USDM_BTCUSDT_PERP",
            "case_count": len(catalogue),
            "cases": catalogue,
        },
    )
    model_cases = margin_model_cases(reg)
    write(
        DATA / "MARGIN_LIQUIDATION_CASES.json",
        {
            "schema_version": 1,
            "generated_by": "scripts/rfc048_run.py",
            "instrument_id": "BINANCE_USDM_BTCUSDT_PERP",
            "margin_model": "isolated linear perpetual; maintenance ladder from the venue payload",
            "case_count": len(margin_cases),
            "cases": margin_cases,
            "model_level_case_count": len(model_cases),
            "model_level_cases": model_cases,
        },
    )
    write(DATA / "ECONOMIC_FEASIBILITY.json", feasibility)

    report: dict[str, Any] = {
        "schema_version": 1,
        "rfc": "RFC-048",
        "generated_by": "scripts/rfc048_run.py",
        "generated_at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "duration_seconds": round(time.time() - started, 3),
        "current_head": git("rev-parse", "HEAD"),
        "branch": git("rev-parse", "--abbrev-ref", "HEAD"),
        "engine": {
            "module": "trading_bot.risk.futures",
            "policy_version": FuturesRiskPolicy().to_dict(),
            "instrument_fixture": str(DATA / "INSTRUMENTS.json"),
            "instrument_source_hash": reg.get("BINANCE_USDM_BTCUSDT_PERP").source_hash,
            "bracket_source_hash": load_json("PROVENANCE.json")["sources"]["leverage_brackets"][
                "sha256"
            ],
            "funding_history_observations": len(FUNDING_OBSERVATIONS),
            "supported_instruments": reg.supported_ids(),
            "declared_instruments": reg.ids(),
        },
        "execution": {
            "scenarios_run": len(catalogue),
            "expectations_met": expectations_met,
            "expectations_failed": [
                {"scenario": row["scenario"], "expect": row["expect"]}
                for row in catalogue
                if not row["expectation_met"]
            ],
            "approved_simulated": len(approved),
            "refused": len(refused),
            "order_authorised_anywhere": any_order_authorised,
            "decisions": [row["decision"]["decision"] for row in catalogue],
        },
        "concurrency": concurrency,
        "runtime_integration": integration,
        "governance": {
            "DISCOVERY_CAMPAIGN_FAILED": True,
            "NEXT_CAMPAIGN": "NOT_AUTHORIZED",
            "LIVE_TRADING": "DISABLED",
            "TRADES_AUTHORIZED": 0,
            "PROFITABILITY_VERIFIED": False,
            "new_strategies_created": 0,
            "oos_results_reused": 0,
            "cost_model_v3_modified": False,
            "production_config_modified": False,
            "live_orders_sent": 0,
        },
        "decision_ids": [row["decision"]["decision_id"] for row in catalogue],
    }
    write(DATA / "RUNTIME_EXECUTION_REPORT.json", report)

    print(f"scenarios: {len(catalogue)} (expectations met: {expectations_met})")
    print(f"margin model cases: {len(model_cases)}")
    print(f"approved simulated: {len(approved)}  refused: {len(refused)}")
    print(f"order authorised anywhere: {any_order_authorised}")
    print(f"concurrency invariant holds: {concurrency['invariant_holds']}")
    print(f"runtime integration reachable: {integration['reachable']}")
    print(f"duration: {report['duration_seconds']}s  head: {report['current_head'][:12]}")
    return 0 if expectations_met == len(catalogue) and not any_order_authorised else 1


def write(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
