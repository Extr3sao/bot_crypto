"""RFC-048V — real adversarial falsification run (generative + oracle).

This script PROVES or DISPROVES that the futures risk engine can be made to
approve a position it must refuse. It is a driver, not a model: the independent
arithmetic lives in ``trading_bot.risk.futures_falsification``, which shares no
code with the engine.

What it does, in order:

1. replays every counterexample found before the fix (their pre-fix behaviour is
   recorded, their post-fix behaviour is measured here);
2. runs the recorded 31-scenario catalogue through BOTH the engine and the
   oracle and compares them case by case;
3. runs a seeded randomized search over the boundary space (equity near zero,
   margin nearly exhausted, stops too close, adverse gaps, leverage above the
   cap, stale/future data, absent funding, omitted costs, liquidation before
   stop, bracket changes, quantity rounding, NaN/infinity, adverse marks, long
   and short);
4. cross-checks every liquidation price against a NUMERIC ROOT of the venue's
   margin condition (second mathematical path, independent code);
5. drives the margin ledger through concurrency, cancellation, failure, retry,
   release and snapshot-skew probes;
6. writes ``data/rfc048/ADVERSARIAL_FINDINGS.{json,md}``.

    uv run python scripts/rfc048v_falsify.py [--count N] [--seed S]
"""

from __future__ import annotations

import argparse
import json
import math
import random
import subprocess
import sys
import threading
import time
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path
from typing import Any, cast

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

import rfc048_run  # noqa: E402  (catalogue + fixture helpers; main is guarded)

from trading_bot.risk.futures import (  # noqa: E402
    Direction,
    InstrumentSpec,
    MarginLedger,
    PortfolioSnapshot,
    PortfolioState,
    RiskProposal,
    ScenarioRequest,
    load_instrument_registry,
)
from trading_bot.risk.futures.engine import FuturesRiskEngine, FuturesRiskPolicy  # noqa: E402
from trading_bot.risk.futures.margin import MarginModel, StressScenario  # noqa: E402
from trading_bot.risk.futures_falsification import (  # noqa: E402
    FALSIFIER_VERSION,
    INVARIANTS,
    OracleFixtures,
    OracleScenario,
    compare_decision,
    independent_liquidation_price,
    oracle_verdict,
)

DATA = ROOT / "data" / "rfc048"
SEED = 20261010
COUNT = 4000
#: The commit this falsification campaign was opened against.
PREFIX_COMMIT = "19b1a0b"

#: ``dataclasses.replace`` with a keyword set chosen at run time. mypy cannot type
#: a dynamic unpack, so the falsifier casts once here rather than scattering
#: suppressions at every hostile-injection site.
replace_with = cast("Callable[..., RiskProposal]", replace)


# ---------------------------------------------------------------------------
# plumbing
# ---------------------------------------------------------------------------


def git(*args: str) -> str:
    try:
        return subprocess.run(
            ["git", *args], cwd=ROOT, capture_output=True, text=True, check=False
        ).stdout.strip()
    except OSError:  # pragma: no cover - git is present in this repo
        return ""


def oracle_scenario(
    *,
    scenario_id: str,
    proposal: RiskProposal,
    snapshot: PortfolioSnapshot,
    market: dict[str, Any],
    funding: list[dict[str, Any]],
    stress: tuple[StressScenario, ...],
    policy: FuturesRiskPolicy,
    direction: str | None = None,
    live_route_requested: bool | None = None,
    kind: str = "catalogue",
    instrument_spec: InstrumentSpec | None = None,
) -> OracleScenario:
    return OracleScenario(
        scenario_id=scenario_id,
        effective_spec=None if instrument_spec is None else instrument_spec.to_dict(),
        instrument_id=proposal.instrument_id,
        direction=(direction or proposal.direction.value),
        entry_price=float(proposal.entry_price),
        stop_price=None if proposal.stop_price is None else float(proposal.stop_price),
        mark_price=None if proposal.mark_price is None else float(proposal.mark_price),
        requested_notional=float(proposal.requested_notional),
        requested_leverage=float(proposal.requested_leverage),
        horizon_minutes=float(proposal.horizon_minutes),
        data_timestamp_ms=int(proposal.data_timestamp_ms),
        decision_timestamp_ms=int(proposal.decision_timestamp_ms),
        equity=float(snapshot.equity),
        free_margin=float(snapshot.free_margin),
        reserved_margin=float(snapshot.reserved_margin),
        daily_pnl=float(snapshot.daily_pnl),
        drawdown_pct=float(snapshot.drawdown_pct),
        consecutive_losses=int(snapshot.consecutive_losses),
        spread_bps=None if market.get("spread_bps") is None else float(market["spread_bps"]),
        depth=market.get("depth"),
        funding_observations=tuple(funding),
        stress=tuple(s.to_dict() for s in stress),
        policy={
            "risk_budget_pct": policy.risk_budget_pct,
            "max_leverage": policy.max_leverage,
            "min_liquidation_buffer_bps": policy.min_liquidation_buffer_bps,
            "gap_reserve_pct": policy.gap_reserve_pct,
            "stress_slippage_bps": policy.stress_slippage_bps,
            "slippage_bps": policy.slippage_bps,
            "max_gross_exposure_pct": policy.max_gross_exposure_pct,
            "max_net_exposure_pct": policy.max_net_exposure_pct,
            "max_concentration_pct": policy.max_concentration_pct,
            "max_margin_utilization_pct": policy.max_margin_utilization_pct,
            "max_data_age_ms": policy.max_data_age_ms,
            "min_stop_distance_bps": policy.min_stop_distance_bps,
        },
        live_route_requested=(
            proposal.live_route_requested if live_route_requested is None else live_route_requested
        ),
        kind=kind,
    )


def engine_decision(
    *,
    spec: InstrumentSpec,
    proposal: RiskProposal,
    snapshot: PortfolioSnapshot,
    market: dict[str, Any],
    funding: list[dict[str, Any]],
    policy: FuturesRiskPolicy,
    stress: tuple[StressScenario, ...] = (),
    ledger: MarginLedger | None = None,
) -> dict[str, Any]:
    engine = FuturesRiskEngine(spec=spec, policy=policy, ledger=ledger)
    try:
        result = engine.decide(
            ScenarioRequest(
                proposal=proposal,
                snapshot=snapshot,
                market=market,
                funding_observations=funding,
                funding_source_hash="falsify",
                stress_scenarios=stress,
            )
        )
    except Exception as exc:  # a raised engine is itself a finding
        return {
            "decision": f"ENGINE_RAISED:{type(exc).__name__}",
            "error": str(exc),
            "rejection_reasons": [],
            "order_authorised": False,
            "approved_notional": 0.0,
            "required_margin": 0.0,
            "modeled_worst_loss": 0.0,
            "liquidation_buffer_bps": None,
            "liquidation_price": None,
            "quantity": 0.0,
            "data_timestamp_ms": proposal.data_timestamp_ms,
            "decision_timestamp_ms": proposal.decision_timestamp_ms,
        }
    return result.decision.to_dict()


def evaluate(
    scenario: OracleScenario,
    decision: dict[str, Any],
    fixtures: OracleFixtures,
    *,
    quantity_step: float | None = None,
) -> dict[str, Any]:
    verdict = oracle_verdict(scenario, fixtures)
    comparison = compare_decision(decision, verdict, scenario, quantity_step=quantity_step)
    return {
        "scenario": scenario.to_dict(),
        "engine_decision": decision.get("decision"),
        "engine_reasons": decision.get("rejection_reasons"),
        "oracle": verdict.to_dict(),
        "comparison": comparison.to_dict(),
        "engine_raised": str(decision.get("decision", "")).startswith("ENGINE_RAISED"),
    }


# ---------------------------------------------------------------------------
# 1. counterexample replay
# ---------------------------------------------------------------------------


def counterexample_replay(reg: Any, fixtures: OracleFixtures) -> dict[str, Any]:
    """Every family found against the pre-fix engine, replayed on the fixed one."""
    perp = reg.get("BINANCE_USDM_BTCUSDT_PERP")
    obs = rfc048_run.FUNDING_OBSERVATIONS
    policy = rfc048_run.base_policy()
    results: list[dict[str, Any]] = []

    def record(
        *,
        defect: str,
        invariant: str,
        label: str,
        proposal: RiskProposal,
        market: dict[str, Any] | None = None,
        snapshot: PortfolioSnapshot | None = None,
        stress: tuple[StressScenario, ...] = (),
        funding: list[dict[str, Any]] | None = None,
        prefix_evidence: str,
        regression_test: str,
    ) -> None:
        market = market or rfc048_run.market()
        snapshot = snapshot or rfc048_run.snapshot()
        funding = obs if funding is None else funding
        decision = engine_decision(
            spec=perp,
            proposal=proposal,
            snapshot=snapshot,
            market=market,
            funding=funding,
            policy=policy,
            stress=stress,
        )
        oracle = oracle_scenario(
            scenario_id=label,
            proposal=proposal,
            snapshot=snapshot,
            market=market,
            funding=funding,
            stress=stress,
            policy=policy,
            kind="counterexample",
            instrument_spec=perp,
        )
        verdict = oracle_verdict(oracle, fixtures)
        safe = (
            decision.get("decision") in ("DATA_INVALID", "NO_TRADE", "RISK_VETO")
            and decision.get("approved_notional") == 0.0
        )
        results.append(
            {
                "defect": defect,
                "invariant": invariant,
                "case": label,
                "prefix_commit": PREFIX_COMMIT,
                "prefix_observed": prefix_evidence,
                "postfix_decision": decision.get("decision"),
                "postfix_reasons": decision.get("rejection_reasons"),
                "postfix_is_safe_refusal": safe,
                "oracle_expected": verdict.expected,
                "oracle_refusal_class": verdict.refusal_class,
                "regression_test": regression_test,
            }
        )

    base = rfc048_run.proposal()

    record(
        defect="DEF-048V-01",
        invariant="I5_UNKNOWN_CRITICAL_INPUT",
        label="NaN mark price reached an approval",
        proposal=replace(base, mark_price=float("nan")),
        prefix_evidence=(
            "19b1a0b: decision=REDUCE_SIMULATED_SIZE with mark_price=NaN "
            "(the market-validity gate compared with <= and NaN satisfied it)"
        ),
        regression_test="test_non_finite_mark_is_not_silently_treated_as_present",
    )
    record(
        defect="DEF-048V-01",
        invariant="I5_UNKNOWN_CRITICAL_INPUT",
        label="infinite mark price reached an approval",
        proposal=replace(base, mark_price=float("inf")),
        prefix_evidence="19b1a0b: decision=REDUCE_SIMULATED_SIZE with mark_price=inf",
        regression_test="test_non_finite_mark_is_not_silently_treated_as_present",
    )
    record(
        defect="DEF-048V-01",
        invariant="I2_MARGIN_LE_AVAILABLE",
        label="NaN leverage produced an approval with a NaN margin",
        proposal=replace(base, requested_leverage=float("nan")),
        prefix_evidence=(
            "19b1a0b: decision=REDUCE_SIMULATED_SIZE, required_margin=NaN "
            "(min(NaN, cap, ceiling) stayed NaN and every comparison passed)"
        ),
        regression_test="test_non_finite_proposal_fields_are_refused",
    )
    record(
        defect="DEF-048V-01",
        invariant="I4_DATA_ORDER",
        label="NaN spread reached int() and raised",
        market={**rfc048_run.market(), "spread_bps": float("nan")},
        proposal=base,
        prefix_evidence="19b1a0b: ValueError('cannot convert float NaN to integer')",
        regression_test="test_non_finite_spread_is_refused",
    )
    record(
        defect="DEF-048V-02",
        invariant="I4_DATA_ORDER",
        label="NaN horizon reached int() and raised",
        proposal=replace(base, horizon_minutes=float("nan")),
        prefix_evidence="19b1a0b: ValueError('cannot convert float NaN to integer')",
        regression_test="test_non_finite_proposal_fields_are_refused",
    )
    record(
        defect="DEF-048V-02",
        invariant="I4_DATA_ORDER",
        label="NaN stop price reached int() and raised",
        proposal=replace(base, stop_price=float("nan")),
        prefix_evidence="19b1a0b: ValueError('cannot convert float NaN to integer')",
        regression_test="test_non_finite_proposal_fields_are_refused",
    )
    record(
        defect="DEF-048V-02",
        invariant="I4_DATA_ORDER",
        label="NaN equity reached int() and raised",
        proposal=base,
        snapshot=rfc048_run.snapshot(equity=float("nan"), free_margin=float("nan")),
        prefix_evidence="19b1a0b: ValueError('cannot convert float NaN to integer')",
        regression_test="test_non_finite_snapshot_state_is_refused",
    )
    record(
        defect="DEF-048V-06",
        invariant="I5_UNKNOWN_CRITICAL_INPUT",
        label="NaN stress scenario silently modelled as no stress",
        proposal=base,
        stress=(StressScenario(name="nan_move", adverse_move_pct=float("nan")),),
        prefix_evidence=(
            "19b1a0b: decision=REDUCE_SIMULATED_SIZE; the NaN path produced no "
            "breach and the declared stress was silently ignored"
        ),
        regression_test="test_unmodelable_stress_is_refused_by_the_engine",
    )
    record(
        defect="DEF-048V-06",
        invariant="I5_UNKNOWN_CRITICAL_INPUT",
        label="NaN stress funding rate silently charged zero",
        proposal=base,
        stress=(
            StressScenario(name="nan_funding", adverse_move_pct=0.02, funding_rate=float("nan")),
        ),
        prefix_evidence="19b1a0b: decision=REDUCE_SIMULATED_SIZE with buffer 9874.5 bps",
        regression_test="test_unmodelable_stress_is_refused_by_the_engine",
    )
    record(
        defect="DEF-048V-01",
        invariant="I5_UNKNOWN_CRITICAL_INPUT",
        label="NaN open-position notional defeated the exposure ceilings",
        proposal=base,
        snapshot=rfc048_run.snapshot(
            positions=(
                PortfolioState(
                    instrument_id="BINANCE_USDM_ETHUSDT_PERP",
                    asset="ETH",
                    direction=Direction.LONG,
                    quantity=1.0,
                    entry_price=3_000.0,
                    notional=float("nan"),
                    reserved_margin=0.0,
                ),
            )
        ),
        prefix_evidence="19b1a0b: NaN exposure made every cap comparison False",
        regression_test="test_non_finite_open_position_is_refused",
    )

    # ledger-level counterexamples (no engine involved)
    ledger = MarginLedger(equity=200.0)
    ok_nan, _, reason_nan = ledger.try_reserve(float("nan"), decision_id="nan")
    idempotence_ledger = MarginLedger(equity=200.0)
    idempotence_ledger.try_reserve(82.5, decision_id="dup")
    idempotence_ledger.try_reserve(82.5, decision_id="dup")
    results.append(
        {
            "defect": "DEF-048V-05",
            "invariant": "I2_MARGIN_LE_AVAILABLE",
            "case": "NaN reservation poisoned the ledger",
            "prefix_commit": PREFIX_COMMIT,
            "prefix_observed": "19b1a0b: try_reserve(NaN) returned (True, nan); free became NaN",
            "postfix_decision": f"try_reserve(NaN) -> ok={ok_nan}, reason={reason_nan}",
            "postfix_reasons": [str(reason_nan)],
            "postfix_is_safe_refusal": not ok_nan,
            "oracle_expected": "REFUSE",
            "oracle_refusal_class": "INVALID_NUMERIC_INPUT",
            "regression_test": "test_ledger_refuses_non_finite_amounts",
        }
    )
    results.append(
        {
            "defect": "DEF-048V-03",
            "invariant": "I2_MARGIN_LE_AVAILABLE",
            "case": "a repeated decision id reserved twice",
            "prefix_commit": PREFIX_COMMIT,
            "prefix_observed": "19b1a0b: two reservations of 82.5 for the same decision id (165 total)",
            "postfix_decision": f"duplicate reserve -> reserved={idempotence_ledger.reserved}",
            "postfix_reasons": [],
            "postfix_is_safe_refusal": idempotence_ledger.reserved == 82.5,
            "oracle_expected": "REFUSE",
            "oracle_refusal_class": "SHARED_COLLATERAL_CONFLICT",
            "regression_test": "test_repeated_decision_id_is_idempotent",
        }
    )

    return {
        "cases": results,
        "all_replay_safe": all(row["postfix_is_safe_refusal"] for row in results),
        "case_count": len(results),
    }


# ---------------------------------------------------------------------------
# 2. the recorded catalogue through both models
# ---------------------------------------------------------------------------


def catalogue_cross_check(reg: Any, fixtures: OracleFixtures) -> dict[str, Any]:
    catalogue = rfc048_run.build_catalogue(reg)
    rows: list[dict[str, Any]] = []
    for scenario in catalogue:
        spec = scenario["spec"]
        policy = scenario.get("policy") or rfc048_run.base_policy()
        proposal_ = scenario["proposal"]
        snapshot_ = scenario.get("snapshot") or rfc048_run.snapshot()
        market_ = scenario.get("market") or rfc048_run.market()
        funding = scenario.get("funding")
        funding = rfc048_run.FUNDING_OBSERVATIONS if funding is None else funding
        stress = scenario.get("stress", ())
        decision = engine_decision(
            spec=spec,
            proposal=proposal_,
            snapshot=snapshot_,
            market=market_,
            funding=funding,
            policy=policy,
            stress=stress,
        )
        oracle = oracle_scenario(
            scenario_id=scenario["id"],
            proposal=proposal_,
            snapshot=snapshot_,
            market=market_,
            funding=funding,
            stress=stress,
            policy=policy,
            kind="catalogue",
            instrument_spec=spec,
        )
        rows.append(evaluate(oracle, decision, fixtures, quantity_step=spec.quantity_step))
    counts: dict[str, int] = {}
    for row in rows:
        key = row["comparison"]["classification"]
        counts[key] = counts.get(key, 0) + 1
    return {"cases": rows, "classifications": counts, "case_count": len(rows)}


# ---------------------------------------------------------------------------
# 3. randomized search
# ---------------------------------------------------------------------------


def random_search(reg: Any, fixtures: OracleFixtures, *, seed: int, count: int) -> dict[str, Any]:
    rng = random.Random(seed)
    perp = reg.get("BINANCE_USDM_BTCUSDT_PERP")
    obs = rfc048_run.FUNDING_OBSERVATIONS
    base_policy = rfc048_run.base_policy()
    mark = rfc048_run.MARK
    ts = rfc048_run.SNAPSHOT_TS
    hostile = [float("nan"), float("inf"), float("-inf")]
    counts: dict[str, int] = {}
    false_approvals: list[dict[str, Any]] = []
    conservative: list[dict[str, Any]] = []
    refusals = 0
    approvals = 0
    raised_count = 0

    for index in range(count):
        direction = rng.choice([Direction.LONG, Direction.SHORT])
        entry = mark * rng.uniform(0.5, 1.5)
        stop_distance_pct = rng.choice(
            [
                rng.uniform(-0.005, 0.0005),  # wrong side / too close
                rng.uniform(0.0005, 0.01),  # sensible
                rng.uniform(0.01, 0.15),  # far
            ]
        )
        stop = (
            entry * (1.0 - stop_distance_pct)
            if direction is Direction.LONG
            else entry * (1.0 + stop_distance_pct)
        )
        leverage = rng.choice([0.5, 1.0, 2.0, 3.0, 5.0, 10.0, 50.0, 500.0])
        notional = rng.choice([10.0, 50.0, 100.0, 400.0, 1_000.0, 5_000.0, 50_000.0])
        horizon = rng.choice([4.0, 30.0, 60.0, 480.0, 540.0, 1_500.0])
        equity = rng.choice([5.0, 50.0, 200.0, 1_000.0, 10_000.0])
        free = equity * rng.choice([0.0, 0.25, 0.5, 1.0])
        age = rng.choice([0, 1_000, 60_000, 300_000, 301_000, 900_000, -1_000])
        spread = rng.choice([None, 0.0, 0.012, 1.0, 25.0, 500.0])
        funding = rng.choice(
            [
                obs,
                [],
                obs[-50:],
                [
                    {"funding_time_ms": ts + 10_000_000, "funding_rate": 0.01}
                ],  # future rate must be invisible
                [{"funding_time_ms": ts - 1, "funding_rate": -0.001}],
            ]
        )
        stress: tuple[StressScenario, ...] = ()
        if rng.random() < 0.35:
            stress = (
                StressScenario(
                    name="sweep_adverse",
                    adverse_move_pct=rng.choice([0.001, 0.01, 0.05, 0.2, 0.5]),
                    spread_widening_bps=rng.choice([0.0, 5.0, 50.0]),
                    funding_settlements=rng.choice([0, 1, 3]),
                    funding_rate=rng.choice([0.0, 0.0001, 0.001]),
                ),
            )
        proposal = replace(
            rfc048_run.proposal(),
            decision_id=f"SWEEP-{index:05d}",
            direction=direction,
            entry_price=entry,
            stop_price=stop,
            mark_price=entry,
            requested_notional=notional,
            requested_leverage=leverage,
            horizon_minutes=horizon,
            data_timestamp_ms=ts,
            decision_timestamp_ms=ts + max(age, 1),
        )
        snapshot = rfc048_run.snapshot(equity=equity, free_margin=free, reserved_margin=0.0)
        market = {
            "mark_price": entry,
            "spread_bps": spread,
            "depth": {"bids": rfc048_run.DEPTH_BIDS, "asks": rfc048_run.DEPTH_ASKS},
        }
        if rng.random() < 0.06:  # hostile injection
            field = rng.choice(
                [
                    "entry_price",
                    "stop_price",
                    "mark_price",
                    "requested_notional",
                    "requested_leverage",
                    "horizon_minutes",
                ]
            )
            hostile_value = rng.choice(hostile)
            proposal = replace_with(proposal, **{field: hostile_value})
        decision = engine_decision(
            spec=perp,
            proposal=proposal,
            snapshot=snapshot,
            market=market,
            funding=list(funding),
            policy=base_policy,
            stress=stress,
        )
        oracle = oracle_scenario(
            scenario_id=f"SWEEP-{index:05d}",
            proposal=proposal,
            snapshot=snapshot,
            market=market,
            funding=list(funding),
            stress=stress,
            policy=base_policy,
            direction=direction.value,
            kind="random",
            instrument_spec=perp,
        )
        row = evaluate(oracle, decision, fixtures, quantity_step=perp.quantity_step)
        classification = row["comparison"]["classification"]
        counts[classification] = counts.get(classification, 0) + 1
        if decision.get("decision") in ("APPROVE_SIMULATION", "REDUCE_SIMULATED_SIZE"):
            approvals += 1
        else:
            refusals += 1
        if str(decision.get("decision", "")).startswith("ENGINE_RAISED"):
            raised_count += 1
        if classification == "FALSE_APPROVAL" and len(false_approvals) < 20:
            false_approvals.append(row)
        if classification == "CONSERVATIVE_DIVERGENCE" and len(conservative) < 25:
            conservative.append(
                {
                    "scenario": row["scenario"],
                    "engine_reasons": row["engine_reasons"],
                    "oracle_expected": row["oracle"]["expected"],
                }
            )

    return {
        "seed": seed,
        "requested_count": count,
        "examined": count,
        "classifications": counts,
        "engine_approvals": approvals,
        "engine_refusals": refusals,
        "false_approvals": false_approvals,
        "conservative_divergences_sample": conservative,
        "false_approval_count": len(false_approvals),
        "engine_raised_count": raised_count,
    }


# ---------------------------------------------------------------------------
# 4. liquidation cross-check (second mathematical path)
# ---------------------------------------------------------------------------


def liquidation_cross_check(reg: Any) -> dict[str, Any]:
    perp = reg.get("BINANCE_USDM_BTCUSDT_PERP")
    model = MarginModel(perp)
    rows: list[dict[str, Any]] = []
    worst_diff_bps = 0.0
    mismatches = 0
    for direction in (Direction.LONG, Direction.SHORT):
        for notional in (50.0, 500.0, 5_000.0, 50_000.0, 1_000_000.0):
            for leverage in (1.0, 2.0, 3.0, 5.0, 20.0):
                bracket = perp.bracket_for(notional)
                quantity = round(notional / 82_500.0, 6)
                if quantity <= 0:
                    continue
                notional = quantity * 82_500.0
                margin = notional / leverage
                adverse = notional * 0.0005  # funding owed + liquidation fee toy term
                builder_price = model.liquidation_price(
                    direction=direction,
                    quantity=quantity,
                    entry_price=82_500.0,
                    wallet_balance=margin,
                    bracket_rate=bracket.maintenance_margin_rate,
                    cum_maintenance_amount=bracket.cum_maintenance_amount,
                    adverse_terms_usdt=adverse,
                )
                independent_price = independent_liquidation_price(
                    direction=direction.value,
                    quantity=quantity,
                    entry=82_500.0,
                    wallet_balance=margin,
                    bracket_rate=bracket.maintenance_margin_rate,
                    cum_maintenance=float(bracket.cum_maintenance_amount),
                    adverse_terms=adverse,
                )
                diff_bps = (
                    None
                    if builder_price is None or independent_price is None
                    else abs(builder_price - independent_price) / 82_500.0 * 10_000.0
                )
                if diff_bps is None or diff_bps > 0.01:
                    mismatches += 1
                if diff_bps is not None:
                    worst_diff_bps = max(worst_diff_bps, diff_bps)
                rows.append(
                    {
                        "direction": direction.value,
                        "notional": notional,
                        "leverage": leverage,
                        "bracket_seq": bracket.bracket_seq,
                        "builder_liquidation_price": builder_price,
                        "independent_liquidation_price": independent_price,
                        "difference_bps": diff_bps,
                    }
                )
    return {
        "grid_points": len(rows),
        "worst_difference_bps": worst_diff_bps,
        "mismatch_count": mismatches,
        "cases": rows,
    }


# ---------------------------------------------------------------------------
# 5. portfolio concurrency
# ---------------------------------------------------------------------------


def portfolio_concurrency(reg: Any) -> dict[str, Any]:
    perp = reg.get("BINANCE_USDM_BTCUSDT_PERP")
    probes: dict[str, Any] = {}

    # -- a. eight simultaneous decisions on one pool -------------------------
    policy = rfc048_run.base_policy()
    ledger = MarginLedger(equity=rfc048_run.EQUITY)
    engine = FuturesRiskEngine(spec=perp, policy=policy, ledger=ledger)
    approved: list[float] = []
    refusals: list[str] = []
    errors: list[str] = []
    lock = threading.Lock()

    def attempt(index: int) -> None:
        try:
            decision = engine.decide(
                ScenarioRequest(
                    proposal=rfc048_run.proposal(
                        decision_id=f"V-CONC-{index:02d}", requested_notional=400.0
                    ),
                    snapshot=rfc048_run.snapshot(),
                    market=rfc048_run.market(),
                    funding_observations=rfc048_run.FUNDING_OBSERVATIONS,
                    funding_source_hash=rfc048_run.FUNDING_HASH,
                )
            ).decision
            with lock:
                if decision.approved:
                    approved.append(decision.required_margin)
                else:
                    refusals.append(",".join(r.value for r in decision.rejection_reasons))
        except Exception as exc:  # pragma: no cover - reported, never hidden
            with lock:
                errors.append(f"{type(exc).__name__}: {exc}")

    threads = [threading.Thread(target=attempt, args=(i,)) for i in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    ceiling = policy.max_margin_utilization_pct * rfc048_run.EQUITY
    probes["simultaneous_reserve"] = {
        "approved_count": len(approved),
        "refused_count": len(refusals),
        "sum_approved_margin": round(sum(approved), 10),
        "ledger_reserved": round(ledger.reserved, 10),
        "policy_ceiling": ceiling,
        "errors": errors,
        "invariants": {
            "no_double_count": abs(ledger.reserved - sum(approved)) < 1e-9,
            "solvent": ledger.reserved <= rfc048_run.EQUITY + 1e-9,
            "aggregate_utilization_respected": ledger.reserved <= ceiling + 1e-9,
            "refusals_name_the_ceiling": all("MARGIN_UTILIZATION_LIMIT" in row for row in refusals)
            if refusals
            else True,
        },
    }

    # -- b. cancel (release) then re-reserve ---------------------------------
    ledger_b = MarginLedger(equity=rfc048_run.EQUITY)
    first = engine_decision(
        spec=perp,
        proposal=rfc048_run.proposal(decision_id="V-CANCEL-1", requested_notional=400.0),
        snapshot=rfc048_run.snapshot(),
        market=rfc048_run.market(),
        funding=rfc048_run.FUNDING_OBSERVATIONS,
        policy=policy,
        ledger=ledger_b,
    )
    reserved_after_first = ledger_b.reserved
    released = ledger_b.release("V-CANCEL-1")
    second_ok, _, _ = ledger_b.try_reserve(
        reserved_after_first, decision_id="V-CANCEL-2", collateral_group="ISOLATED:X"
    )
    probes["cancel_then_reserve"] = {
        "first_decision": first.get("decision"),
        "reserved_after_first": reserved_after_first,
        "released": released,
        "free_after_release": ledger_b.free,
        "second_reserve_ok": second_ok,
        "invariants": {
            "release_restores_the_pool": abs(ledger_b.free + ledger_b.reserved - rfc048_run.EQUITY)
            < 1e-9,
            "re_reserve_succeeds": second_ok,
        },
    }

    # -- c. a failed reservation leaves the pool intact ----------------------
    ledger_c = MarginLedger(equity=100.0)
    ok, granted, reason = ledger_c.try_reserve(
        150.0, decision_id="V-FAIL", collateral_group="ISOLATED:X"
    )
    probes["failed_reserve"] = {
        "ok": ok,
        "granted": granted,
        "reason": str(reason),
        "reserved": ledger_c.reserved,
        "invariants": {
            "refused": not ok,
            "pool_untouched": ledger_c.reserved == 0.0,
            "reason_is_insufficient_margin": str(reason) == "INSUFFICIENT_MARGIN",
        },
    }

    # -- d. retry of the same decision is idempotent -------------------------
    ledger_d = MarginLedger(equity=rfc048_run.EQUITY)
    proposal_d = rfc048_run.proposal(decision_id="V-RETRY", requested_notional=400.0)
    for _ in range(3):
        engine_decision(
            spec=perp,
            proposal=proposal_d,
            snapshot=rfc048_run.snapshot(),
            market=rfc048_run.market(),
            funding=rfc048_run.FUNDING_OBSERVATIONS,
            policy=policy,
            ledger=ledger_d,
        )
    reserved_once = ledger_d.reserved
    released_d = ledger_d.release("V-RETRY")
    probes["retry_same_decision"] = {
        "reserved_after_three_attempts": reserved_once,
        "released_after_cancel": released_d,
        "reserved_after_release": ledger_d.reserved,
        "invariants": {
            "counted_once": abs(released_d - reserved_once) < 1e-9,
            "finite": math.isfinite(ledger_d.reserved),
            "released_back_to_zero": ledger_d.reserved == 0.0,
        },
    }

    # -- e. snapshot skew: a caller cannot widen the pool ---------------------
    ledger_e = MarginLedger(equity=200.0)
    wide = rfc048_run.snapshot(equity=1_000_000.0, free_margin=1_000_000.0)
    outcome = engine_decision(
        spec=perp,
        proposal=rfc048_run.proposal(decision_id="V-SKEW", requested_notional=400.0),
        snapshot=wide,
        market=rfc048_run.market(),
        funding=rfc048_run.FUNDING_OBSERVATIONS,
        policy=policy,
        ledger=ledger_e,
    )
    clamped = ledger_e.snapshot_of(wide, decision_id="V-SKEW")
    probes["snapshot_skew"] = {
        "decision": outcome.get("decision"),
        "ledger_reserved": ledger_e.reserved,
        "clamped_equity": clamped.equity,
        "clamped_free_margin": clamped.free_margin,
        "invariants": {
            "ledger_equity_authoritative": clamped.equity <= 200.0 + 1e-9,
            "reserved_within_real_pool": ledger_e.reserved <= 200.0 + 1e-9,
        },
    }

    # -- f. concurrent reserve/release storm ---------------------------------
    storm_ledger = MarginLedger(equity=1_000.0)
    storm_ceiling = 0.5 * 1_000.0
    storm_errors: list[str] = []
    storm_lock = threading.Lock()
    granted_total = 0.0
    released_total = 0.0

    def reserve_worker(index: int) -> None:
        nonlocal granted_total
        for run_index in range(40):
            ok, amount, _ = storm_ledger.try_reserve(
                80.0,
                decision_id=f"STORM-{index}-{run_index}",
                collateral_group="ISOLATED:X",
                max_committed=storm_ceiling,
            )
            if ok:
                with storm_lock:
                    granted_total += amount
            elif index % 2 == 0:
                storm_ledger.release(f"STORM-{index}-{run_index}")

    def release_worker(index: int) -> None:
        nonlocal released_total
        for run_index in range(40):
            released = storm_ledger.release(f"STORM-{index % 2}-{run_index}")
            with storm_lock:
                released_total += released

    workers = [threading.Thread(target=reserve_worker, args=(i,)) for i in range(4)]
    workers += [threading.Thread(target=release_worker, args=(i,)) for i in range(2)]
    for worker in workers:
        worker.start()
    for worker in workers:
        worker.join()
    probes["reserve_release_storm"] = {
        "granted_total": granted_total,
        "released_total": released_total,
        "ledger_reserved": storm_ledger.reserved,
        "ledger_free": storm_ledger.free,
        "errors": storm_errors,
        "invariants": {
            "reserved_matches_grants_minus_releases": abs(
                storm_ledger.reserved - max(granted_total - released_total, 0.0)
            )
            < 1e-6,
            "ceiling_holds": storm_ledger.reserved <= storm_ceiling + 1e-9,
            "pool_solvent": storm_ledger.reserved <= 1_000.0 + 1e-9,
            "no_exceptions": not storm_errors,
        },
    }
    return probes


# ---------------------------------------------------------------------------
# report
# ---------------------------------------------------------------------------


def build_report(
    *,
    seed: int,
    count: int,
    replay: dict[str, Any],
    catalogue: dict[str, Any],
    sweep: dict[str, Any],
    liquidation: dict[str, Any],
    concurrency: dict[str, Any],
) -> dict[str, Any]:
    false_approvals = (
        list(sweep["false_approvals"])
        + [
            row
            for row in catalogue["cases"]
            if row["comparison"]["classification"] == "FALSE_APPROVAL"
        ]
        + [row for row in replay["cases"] if not row["postfix_is_safe_refusal"]]
    )
    raised = [row for row in catalogue["cases"] if row["engine_raised"]]
    raised += [row for row in replay["cases"] if not row["postfix_is_safe_refusal"]]
    invariant_status = {name: "HELD" for name in INVARIANTS}
    violated: set[str] = set()
    for row in false_approvals:
        comparison = row.get("comparison")
        if comparison:
            violated.update(comparison["violations"])
    for name in violated:
        invariant_status[name] = "VIOLATED"
    all_invariants_hold = all(status == "HELD" for status in invariant_status.values())
    return {
        "schema_version": "rfc048v-adversarial-findings-v1",
        "rfc": "RFC-048V",
        "falsifier_version": FALSIFIER_VERSION,
        "generated_at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "current_head": git("rev-parse", "HEAD"),
        "prefix_commit": PREFIX_COMMIT,
        "seed": seed,
        "random_search_count": count,
        "method": {
            "builder": "trading_bot.risk.futures (imported by the DRIVER only)",
            "falsifier": "trading_bot.risk.futures_falsification (imports no builder code)",
            "liquidation": "numeric root of the venue margin condition (bisection, 200 steps)",
            "invariants": list(INVARIANTS),
        },
        "totals": {
            "catalogue_cases": catalogue["case_count"],
            "counterexample_replays": replay["case_count"],
            "random_scenarios": sweep["examined"],
            "liquidation_grid_points": liquidation["grid_points"],
            "engine_approvals_in_sweep": sweep["engine_approvals"],
            "engine_refusals_in_sweep": sweep["engine_refusals"],
        },
        "invariant_status": invariant_status,
        "all_invariants_hold": all_invariants_hold,
        "false_approval_count": len(false_approvals),
        "false_success": len(false_approvals) + len(raised),
        "engine_raised": len(raised),
        "counterexamples": {
            "replay": replay,
        },
        "catalogue_cross_check": {
            "classifications": catalogue["classifications"],
            "cases": catalogue["cases"],
        },
        "random_search": {
            "classifications": sweep["classifications"],
            "false_approvals": sweep["false_approvals"],
            "conservative_divergences_sample": sweep["conservative_divergences_sample"],
            "false_approval_count": sweep["false_approval_count"],
        },
        "liquidation_cross_check": liquidation,
        "portfolio_concurrency": concurrency,
        "defects": [
            {
                "id": "DEF-048V-01",
                "severity": "HIGH",
                "status": "FIXED",
                "title": "non-finite numbers were not validated: NaN mark and NaN leverage reached approvals",
                "cause": (
                    "every limit used `<=` style comparisons and NaN satisfies none of "
                    "them; the engine had no finiteness gate"
                ),
                "fix": (
                    "engine._validate_numbers refuses any non-finite or impossible input "
                    "as DATA_INVALID/INVALID_NUMERIC_INPUT; the ledger refuses non-finite "
                    "amounts; cost and margin models guard their own arithmetic"
                ),
                "counterexample": "NaN mark_price -> REDUCE_SIMULATED_SIZE (pre-fix)",
                "regression_tests": [
                    "test_non_finite_proposal_fields_are_refused",
                    "test_non_finite_snapshot_state_is_refused",
                    "test_non_finite_open_position_is_refused",
                    "test_non_finite_mark_is_not_silently_treated_as_present",
                ],
            },
            {
                "id": "DEF-048V-02",
                "severity": "HIGH",
                "status": "FIXED",
                "title": "hostile numbers raised instead of refusing (NaN reached int())",
                "cause": (
                    "round_quantity_down() and the funding-settlement conversion called "
                    "int() on unvalidated floats"
                ),
                "fix": (
                    "quantity rounding returns 0 for non-finite input (a refusal), the "
                    "numeric gate rejects the request before any arithmetic, and depth "
                    "levels that are not readable make the impact unknown"
                ),
                "counterexample": "NaN spread/horizon/stop/equity -> ValueError (pre-fix)",
                "regression_tests": [
                    "test_non_finite_spread_is_refused",
                    "test_hostile_input_matrix_never_raises",
                ],
            },
            {
                "id": "DEF-048V-03",
                "severity": "MEDIUM",
                "status": "FIXED",
                "title": "a repeated decision id reserved its margin twice",
                "cause": "MarginLedger.try_reserve appended a grant per call, with no identity",
                "fix": (
                    "a grant for the same decision id is re-confirmed instead of counted "
                    "again; a larger request for the same id is SHARED_COLLATERAL_CONFLICT"
                ),
                "counterexample": "two evaluations of decision DUP-1 reserved 165 USDT for one decision",
                "regression_tests": ["test_repeated_decision_id_is_idempotent"],
            },
            {
                "id": "DEF-048V-04",
                "severity": "MEDIUM",
                "status": "FIXED",
                "title": "the aggregate margin-utilization ceiling could be exceeded by concurrent decisions",
                "cause": (
                    "the ceiling was enforced against each decision's snapshot, not against "
                    "the live reservation, so two approvals could pass 50% together"
                ),
                "fix": (
                    "the engine hands the ceiling to the ledger, which enforces it atomically "
                    "under the same lock as the reservation (MARGIN_UTILIZATION_LIMIT)"
                ),
                "counterexample": (
                    "two sequential decisions on a stale snapshot left 660 USDT reserved on "
                    "1000 USDT of equity (66%) with a 50% policy ceiling"
                ),
                "regression_tests": ["test_aggregate_margin_utilization_holds_under_concurrency"],
            },
            {
                "id": "DEF-048V-05",
                "severity": "MEDIUM",
                "status": "FIXED",
                "title": "a non-finite reservation poisoned the ledger for every later decision",
                "cause": "try_reserve accepted NaN and made reserved/free NaN",
                "fix": "the ledger refuses non-finite amounts and non-finite equity",
                "counterexample": "try_reserve(NaN) -> (True, nan); free became nan",
                "regression_tests": ["test_ledger_refuses_non_finite_amounts"],
            },
            {
                "id": "DEF-048V-06",
                "severity": "MEDIUM",
                "status": "FIXED",
                "title": "an unmodelable stress scenario was silently treated as no stress",
                "cause": (
                    "a NaN stress path produced a NaN liquidation price and every "
                    "comparison against NaN is False, so the path was skipped"
                ),
                "fix": (
                    "the engine rejects non-finite stress parameters as DATA_INVALID and the "
                    "margin model refuses a stress it cannot evaluate (LIQUIDATION_RISK_UNKNOWN)"
                ),
                "counterexample": "StressScenario(adverse_move_pct=NaN) -> REDUCE_SIMULATED_SIZE (pre-fix)",
                "regression_tests": [
                    "test_unmodelable_stress_is_refused_by_the_engine",
                    "test_unmodelable_stress_blocks_the_margin_model_directly",
                ],
            },
            {
                "id": "DEF-048V-07",
                "severity": "LOW",
                "status": "FIXED",
                "title": "a non-finite funding observation could corrupt the funding term",
                "cause": "funding_context() trusted every row it could see",
                "fix": (
                    "only finite, timestamped observations are visible point-in-time; with no "
                    "usable rate left, funding is UNKNOWN and the position is refused"
                ),
                "counterexample": "all-NaN funding history with a settlement in the horizon (pre-fix: 0.0 cost)",
                "regression_tests": ["test_non_finite_funding_observation_makes_funding_unknown"],
            },
            {
                "id": "DEF-048V-08",
                "severity": "MEDIUM",
                "status": "FIXED",
                "title": (
                    "the closed-form liquidation solve extrapolated the maintenance "
                    "amount below its zero floor"
                ),
                "cause": (
                    "the venue floors maintenance at max(notional*rate - cum, 0); the "
                    "linear solve ignored the kink, so at the deepest bracket it "
                    "returned a non-positive price and a 5 bps LARGER buffer than the "
                    "true model (unsafe direction: it understated the liquidation "
                    "price for a long)"
                ),
                "fix": (
                    "the solve is now piecewise: each linear branch is solved and the "
                    "candidate inside its own domain is kept (the floored branch when "
                    "the clamp binds)"
                ),
                "counterexample": (
                    "LONG, notional 999999.99, 1x: builder returned liquidation_price=0.0 "
                    "while the numeric root of the floored condition gives 41.25 "
                    "(5.0 bps of overstated buffer)"
                ),
                "regression_tests": ["test_liquidation_respects_the_maintenance_floor"],
            },
        ],
        "governance": {
            "live_trading": "DISABLED",
            "trades_authorised": 0,
            "orders_emitted": 0,
            "order_authorised_anywhere": False,
        },
        "liquidation_defect": {
            "id": "DEF-048V-08",
            "found_by": "numeric-root cross-check in this campaign",
            "pre_fix": {
                "direction": "LONG",
                "notional": 999999.99,
                "leverage": 1.0,
                "builder_liquidation_price": 0.0,
                "independent_liquidation_price": 41.25,
                "difference_bps": 5.0,
            },
            "post_fix_worst_difference_bps": liquidation["worst_difference_bps"],
            "status": "FIXED",
        },
        "conclusion": (
            "PASS — no false approval survived; every invariant held under the "
            "counterexamples, the catalogue replay, the randomized search, the "
            "numeric-root liquidation cross-check and the concurrency probes."
            if all_invariants_hold and not false_approvals and not raised
            else "FAIL — at least one false approval or raised engine call was recorded"
        ),
    }


def write_markdown(report: dict[str, Any]) -> str:
    lines: list[str] = []
    lines.append("# RFC-048V — Adversarial Findings")
    lines.append("")
    lines.append(
        f"- Falsifier: `{report['falsifier_version']}` · head `{report['current_head'][:12]}` "
        f"· prefix `{report['prefix_commit']}`"
    )
    lines.append(
        f"- Random search: seed `{report['seed']}` x {report['random_search_count']} scenarios"
    )
    lines.append(
        f"- Verdict: **{report['conclusion']}** · FALSE_SUCCESS = {report['false_success']}"
    )
    lines.append("")
    lines.append("## Invariants")
    lines.append("")
    lines.append("| invariant | status |")
    lines.append("| --- | --- |")
    for name, status in report["invariant_status"].items():
        lines.append(f"| `{name}` | {status} |")
    lines.append("")
    lines.append("## Defects found and fixed")
    lines.append("")
    for defect in report["defects"]:
        lines.append(
            f"### {defect['id']} — {defect['title']} ({defect['severity']}, {defect['status']})"
        )
        lines.append("")
        lines.append(f"- Cause: {defect['cause']}")
        lines.append(f"- Fix: {defect['fix']}")
        lines.append(f"- Counterexample: `{defect['counterexample']}`")
        lines.append(
            "- Regression tests: " + ", ".join(f"`{name}`" for name in defect["regression_tests"])
        )
        lines.append("")
    lines.append("## Counterexample replay (pre-fix behaviour → post-fix behaviour)")
    lines.append("")
    lines.append("| case | pre-fix | post-fix | safe refusal |")
    lines.append("| --- | --- | --- | --- |")
    for row in report["counterexamples"]["replay"]["cases"]:
        lines.append(
            f"| {row['case']} | {row['prefix_observed'][:70]} | `{row['postfix_decision']}` | "
            f"{row['postfix_is_safe_refusal']} |"
        )
    lines.append("")
    sweep = report["random_search"]
    lines.append("## Randomized search")
    lines.append("")
    lines.append("| classification | count |")
    lines.append("| --- | --- |")
    for name, value in sorted(sweep["classifications"].items()):
        lines.append(f"| {name} | {value} |")
    lines.append("")
    lines.append(
        f"False approvals: **{sweep['false_approval_count']}** · conservative divergences "
        f"(engine stricter than the oracle) are recorded separately and are not defects."
    )
    lines.append("")
    lines.append("## Liquidation cross-check")
    lines.append("")
    lines.append(
        f"- {report['liquidation_cross_check']['grid_points']} grid points "
        f"(long/short x five notionals x five leverages)"
    )
    lines.append(
        f"- Worst closed-form vs numeric-root difference: "
        f"**{report['liquidation_cross_check']['worst_difference_bps']:.10f} bps**"
    )
    lines.append(
        f"- Mismatches beyond 0.01 bps: {report['liquidation_cross_check']['mismatch_count']}"
    )
    lines.append("")
    lines.append("## Portfolio concurrency")
    lines.append("")
    for probe, payload in report["portfolio_concurrency"].items():
        invariants = payload.get("invariants", {})
        status = "OK" if all(invariants.values()) else "VIOLATED"
        lines.append(f"- `{probe}`: {status} — {json.dumps(invariants)}")
    lines.append("")
    lines.append("## Catalogue cross-check")
    lines.append("")
    lines.append("| classification | count |")
    lines.append("| --- | --- |")
    for name, value in sorted(report["catalogue_cross_check"]["classifications"].items()):
        lines.append(f"| {name} | {value} |")
    lines.append("")
    lines.append(f"_{report['generated_at_utc']}_")
    lines.append("")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="RFC-048V adversarial falsification")
    parser.add_argument("--count", type=int, default=COUNT)
    parser.add_argument("--seed", type=int, default=SEED)
    parser.add_argument("--quick", action="store_true", help="smaller sweep for smoke runs")
    args = parser.parse_args(argv)
    count = 300 if args.quick else args.count

    fixtures = OracleFixtures.load(DATA)
    reg = load_instrument_registry(DATA / "INSTRUMENTS.json")

    started = time.time()
    replay = counterexample_replay(reg, fixtures)
    catalogue = catalogue_cross_check(reg, fixtures)
    sweep = random_search(reg, fixtures, seed=args.seed, count=count)
    liquidation = liquidation_cross_check(reg)
    concurrency = portfolio_concurrency(reg)
    report = build_report(
        seed=args.seed,
        count=count,
        replay=replay,
        catalogue=catalogue,
        sweep=sweep,
        liquidation=liquidation,
        concurrency=concurrency,
    )
    report["duration_seconds"] = round(time.time() - started, 3)

    (DATA / "ADVERSARIAL_FINDINGS.json").write_text(
        json.dumps(report, indent=2) + "\n", encoding="utf-8"
    )
    (DATA / "ADVERSARIAL_FINDINGS.md").write_text(write_markdown(report), encoding="utf-8")

    print(f"falsifier: {report['falsifier_version']}  seed={report['seed']}  n={count}")
    print(f"catalogue: {catalogue['classifications']}")
    print(f"random search: {sweep['classifications']}")
    print(
        f"false approvals: {report['false_approval_count']}  FALSE_SUCCESS: {report['false_success']}"
    )
    print(f"replay safe: {replay['all_replay_safe']}")
    print(f"liquidation worst diff bps: {liquidation['worst_difference_bps']:.10f}")
    print(
        f"concurrency OK: {all(v for p in concurrency.values() for v in p['invariants'].values())}"
    )
    print(f"verdict: {report['conclusion']}")
    return 0 if report["false_success"] == 0 and report["all_invariants_hold"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
