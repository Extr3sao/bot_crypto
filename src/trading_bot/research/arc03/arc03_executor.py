"""ARC-03 primary discovery EXECUTION implementation (EXPERIMENT_ID: ARC03_PRIMARY_DISCOVERY_01).

This module is the frozen-at-execution implementation of the primary economic discovery
authorized by the independently verified ARC-03 preregistration (PREREG_COMMIT
8ebf8a181a3cfaf03737ef585f8906d28f8d419f, INDEPENDENT_VERIFIER_COMMIT
2dfe96c88fd66953d3fee148415e2e837c1bd2c7).

Design invariants:

* The SIGNAL PATH is the frozen reference implementation
  ``trading_bot.research.arc03.arc03_prereg_reference.emit_trades`` (bound at the prereg
  commit). This executor does not re-implement signal semantics; it consumes the
  reference emission and adds only execution-level accounting, controls, exactly-once
  and persistence.
* Funding is CASHFLOW ONLY via the certified ``arc03_funding`` authority.
* Cost scenarios re-price the IDENTICAL trade set; costs never regenerate signals.
* Accounting identity per trade: NET = GROSS + FUNDING - COST.
* The exactly-once ledger is append-only JSONL with fsync durability; a completed
  economic execution can never be created twice.
* NULL_CONTROL uses ``random.Random(20260915)`` over the frozen emission order
  (assets BTCUSDT, ETHUSDT, SOLUSDT, then decision_time_ms) - never Python ``hash()``.
"""

from __future__ import annotations

import json
import os
import random
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from trading_bot.research.arc03.arc03_authority import (
    ASSETS,
    HOLDING_MS,
    LONG,
    NO_SIGNAL,
    REFERENCE_DAYS,
    SHORT,
    Kline5m,
    reference_slots,
)
from trading_bot.research.arc03.arc03_authority import (
    PRIMARY_COST_BPS as FROZEN_PRIMARY_COST_BPS,
)
from trading_bot.research.arc03.arc03_funding import FundingSeries, funding_cashflow_return
from trading_bot.research.arc03.arc03_gates import (
    GateResult,
    TradeRecord,
    all_critical_gates_pass,
    annualized_sharpe,
    evaluate_gates,
    profit_factor,
)
from trading_bot.research.arc03.arc03_prereg_reference import RefResult, RefTrade, emit_trades

EXPERIMENT_ID = "ARC03_PRIMARY_DISCOVERY_01"
NULL_SEED = 20260915
PRIMARY_COST_BPS = FROZEN_PRIMARY_COST_BPS  # 10, from the frozen module
COST_SCENARIOS_BPS = (0, 10, 20, 40)

#: Tolerance for the accounting identity NET = GROSS + FUNDING - COST (float64 round-off).
ACCOUNTING_TOLERANCE = 1e-12


# ------------------------------------------------------------------ ledger (exactly-once)
class ExperimentLedger:
    """Append-only durable experiment ledger (JSONL, fsync'd every write).

    States: REGISTERED -> STARTED -> COMPLETED. Exactly one COMPLETED economic
    execution may ever exist; violation raises :class:`ExactlyOnceViolation`.
    """

    class ExactlyOnceViolation(RuntimeError):
        pass

    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.entries: list[dict[str, Any]] = []
        if self.path.exists():
            with self.path.open("r", encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if line:
                        self.entries.append(json.loads(line))

    # -- queries
    def states(self) -> list[str]:
        return [e.get("state") for e in self.entries]

    def completed_count(self) -> int:
        return sum(1 for s in self.states() if s == "COMPLETED")

    def started_count(self) -> int:
        return sum(1 for s in self.states() if s == "STARTED")

    # -- assertions
    def assert_no_previous_completed(self) -> None:
        if self.completed_count() > 0:
            raise self.ExactlyOnceViolation(
                f"a COMPLETED economic execution already exists in {self.path}"
            )

    def assert_resumable(self) -> None:
        """A technical interruption may RESUME (STARTED without COMPLETED); it must not
        create a second economic experiment.

        A STARTED after a COMPLETED is NOT a resume: the single authorized economic
        execution has already been consumed, so it is rejected as a duplicate.
        """
        if self.completed_count() > 0:
            raise self.ExactlyOnceViolation(
                "cannot START: a COMPLETED economic execution already exists "
                f"in {self.path}"
            )
        if self.started_count() > 1:
            raise self.ExactlyOnceViolation("multiple STARTED entries present")

    # -- writes
    def append(self, state: str, payload: dict[str, Any]) -> dict[str, Any]:
        if state == "COMPLETED":
            self.assert_no_previous_completed()
        if state == "STARTED":
            self.assert_resumable()
        entry = {"state": state, **payload}
        self.entries.append(entry)
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry, sort_keys=True) + "\n")
            fh.flush()
            os.fsync(fh.fileno())
        return entry


# ------------------------------------------------------------------ trade accounting
@dataclass(frozen=True)
class ExecutedTrade:
    """One executed trade with the complete frozen return decomposition."""

    trade_id: str
    asset: str
    direction: str
    direction_sign: int
    decision_bar_open_time_ms: int
    decision_time_ms: int
    volume: float
    reference_max_volume: float
    reference_observations_present: int
    range: float
    reference_max_range: float
    open_price: float
    high_price: float
    low_price: float
    close_price: float
    body: float
    entry_time_ms: int
    entry_price: float
    exit_time_ms: int
    exit_price: float
    gross_price_return: float
    funding_settlements_applied: int
    funding_cashflow_return: float
    emission_index: int

    def cost_return(self, cost_bps: int) -> float:
        return cost_bps / 10_000.0

    def net_return(self, cost_bps: int) -> float:
        return self.gross_price_return + self.funding_cashflow_return - self.cost_return(cost_bps)

    def net_return_ex_funding(self, cost_bps: int) -> float:
        return self.gross_price_return - self.cost_return(cost_bps)

    def with_direction_reversed(self) -> ExecutedTrade:
        """DIRECTION_CONTROL copy: direction sign (and therefore the funding cashflow
        sign) flipped; bars, timestamps, magnitudes and costs identical."""
        return ExecutedTrade(
            trade_id=self.trade_id,
            asset=self.asset,
            direction=("LONG" if self.direction == "SHORT" else "SHORT"),
            direction_sign=-self.direction_sign,
            decision_bar_open_time_ms=self.decision_bar_open_time_ms,
            decision_time_ms=self.decision_time_ms,
            volume=self.volume,
            reference_max_volume=self.reference_max_volume,
            reference_observations_present=self.reference_observations_present,
            range=self.range,
            reference_max_range=self.reference_max_range,
            open_price=self.open_price,
            high_price=self.high_price,
            low_price=self.low_price,
            close_price=self.close_price,
            body=self.body,
            entry_time_ms=self.entry_time_ms,
            entry_price=self.entry_price,
            exit_time_ms=self.exit_time_ms,
            exit_price=self.exit_price,
            gross_price_return=-self.gross_price_return,
            funding_settlements_applied=self.funding_settlements_applied,
            funding_cashflow_return=-self.funding_cashflow_return,
            emission_index=self.emission_index,
        )


def build_executed_trades(
    ref: RefResult,
    funding: dict[str, FundingSeries] | None,
    partitions: dict[str, Kline5m],
) -> list[ExecutedTrade]:
    """Convert reference-emission trades into fully-accounted executed trades.

    Funding settlements are derived per trade from the certified authority. Signal-bar
    OHLC is read from the certified partition at the signal bar's own open-time slot
    (ledger requirement: open/high/low/close/body of the decision bar).
    """
    out: list[ExecutedTrade] = []
    for idx, t in enumerate(ref.trades):
        if funding is not None and t.asset in funding:
            leg, applied = funding_cashflow_return(
                funding[t.asset],
                entry_time_ms=t.entry_time_ms,
                exit_time_ms=t.exit_time_ms,
                direction_sign=t.direction_sign,
            )
        else:
            leg, applied = 0.0, 0
        k = partitions[t.asset]
        si = k.slot_index(t.signal_bar_open_time_ms)
        if si is None:
            raise ValueError(f"signal bar slot missing for {t.asset} {t.signal_bar_open_time_ms}")
        out.append(
            ExecutedTrade(
                trade_id=t.trade_id,
                asset=t.asset,
                direction=t.direction,
                direction_sign=t.direction_sign,
                decision_bar_open_time_ms=t.signal_bar_open_time_ms,
                decision_time_ms=t.decision_time_ms,
                volume=t.volume,
                reference_max_volume=t.reference_volume_max,
                reference_observations_present=t.reference_observations_present,
                range=t.range,
                reference_max_range=t.reference_range_max,
                open_price=k.o[si],
                high_price=k.h[si],
                low_price=k.l[si],
                close_price=k.c[si],
                body=t.body,
                entry_time_ms=t.entry_time_ms,
                entry_price=t.entry_price,
                exit_time_ms=t.exit_time_ms,
                exit_price=t.exit_price,
                gross_price_return=t.gross_return(),
                funding_settlements_applied=applied,
                funding_cashflow_return=leg,
                emission_index=idx,
            )
        )
    return out


def ledger_row(trade: ExecutedTrade) -> dict[str, Any]:
    """Complete per-trade ledger row (mission §32 field list)."""
    row: dict[str, Any] = {
        "trade_id": trade.trade_id,
        "asset": trade.asset,
        "decision_bar_open_time_ms": trade.decision_bar_open_time_ms,
        "decision_time_ms": trade.decision_time_ms,
        "volume": trade.volume,
        "reference_max_volume": trade.reference_max_volume,
        "reference_observations_present": trade.reference_observations_present,
        "range": trade.range,
        "reference_max_range": trade.reference_max_range,
        "open": trade.open_price,
        "high": trade.high_price,
        "low": trade.low_price,
        "close": trade.close_price,
        "body": trade.body,
        "direction": trade.direction,
        "entry_time_ms": trade.entry_time_ms,
        "entry_price": trade.entry_price,
        "exit_time_ms": trade.exit_time_ms,
        "exit_price": trade.exit_price,
        "gross_price_return": trade.gross_price_return,
        "funding_settlements_applied": trade.funding_settlements_applied,
        "funding_cashflow_return": trade.funding_cashflow_return,
    }
    for bps in COST_SCENARIOS_BPS:
        row[f"net_{bps}bps"] = trade.net_return(bps)
    row["net_ex_funding_10bps"] = trade.net_return_ex_funding(PRIMARY_COST_BPS)
    return row


# ------------------------------------------------------------------ controls
def direction_control_trades(trades: list[ExecutedTrade]) -> list[ExecutedTrade]:
    """DIRECTION_CONTROL: reverse direction only; everything else identical."""
    return [t.with_direction_reversed() for t in trades]


def timing_control_trades(
    partitions: dict[str, Kline5m],
    trades: list[ExecutedTrade],
    funding: dict[str, FundingSeries] | None,
) -> tuple[list[ExecutedTrade], int]:
    """TIMING_CONTROL (frozen): entry delayed by exactly +12 bars (+3600000 ms)
    relative to the primary entry; holding remains 12 bars from the delayed entry.
    Signal set, direction, thresholds, costs and funding rules unchanged.

    A signal whose delayed entry or delayed exit has no certified partition slot is
    dropped from the CONTROL trade set only (counted and reported; the primary set is
    never touched).
    """
    out: list[ExecutedTrade] = []
    dropped = 0
    for t in trades:
        k = partitions[t.asset]
        entry_time_control = t.entry_time_ms + HOLDING_MS
        exit_time_control = entry_time_control + HOLDING_MS
        ei = k.slot_index(entry_time_control)
        xi = k.slot_index(exit_time_control)
        if ei is None or xi is None:
            dropped += 1
            continue
        gross = t.direction_sign * (k.o[xi] / k.o[ei] - 1.0)
        if funding is not None and t.asset in funding:
            leg, applied = funding_cashflow_return(
                funding[t.asset],
                entry_time_ms=entry_time_control,
                exit_time_ms=exit_time_control,
                direction_sign=t.direction_sign,
            )
        else:
            leg, applied = 0.0, 0
        out.append(
            ExecutedTrade(
                trade_id=t.trade_id,
                asset=t.asset,
                direction=t.direction,
                direction_sign=t.direction_sign,
                decision_bar_open_time_ms=t.decision_bar_open_time_ms,
                decision_time_ms=t.decision_time_ms,
                volume=t.volume,
                reference_max_volume=t.reference_max_volume,
                reference_observations_present=t.reference_observations_present,
                range=t.range,
                reference_max_range=t.reference_max_range,
                open_price=t.open_price,
                high_price=t.high_price,
                low_price=t.low_price,
                close_price=t.close_price,
                body=t.body,
                entry_time_ms=entry_time_control,
                entry_price=k.o[ei],
                exit_time_ms=exit_time_control,
                exit_price=k.o[xi],
                gross_price_return=gross,
                funding_settlements_applied=applied,
                funding_cashflow_return=leg,
                emission_index=t.emission_index,
            )
        )
    return out, dropped


#: Frozen reason tuple for the PARTICIPATION_CONTROL (the volume record is not a reason).
PARTICIPATION_CONTROL_PRECEDENCE: tuple[str, ...] = (
    "OUTSIDE_COMMON_WINDOW",
    "REFERENCE_HISTORY_INCOMPLETE",
    "NO_EXCURSION_RECORD",
    "NO_EXHAUSTION",
    "POSITION_ALREADY_OPEN",
    "INSUFFICIENT_FORWARD_PRICE_DATA",
)


def _evaluate_without_participation(k: Kline5m, i: int) -> dict[str, Any]:
    """EXCURSION_RECORD + EXHAUSTION evaluation with the PARTICIPATION_SHOCK condition
    REMOVED, exactly as the frozen PARTICIPATION_CONTROL prescribes.

    The 30 same-slot reference set, the strict ``>`` inequalities, the exhaustion
    geometry, the direction semantics and the fail-closed behaviour are byte-for-byte the
    frozen ones; only the volume record is neither required nor consulted.
    """
    t = k.t[i]
    ref_ranges: list[float] = []
    missing = 0
    for slot in reference_slots(t):
        j = k.index.get(slot)
        if j is None:
            missing += 1
            continue
        ref_ranges.append(k.h[j] - k.l[j])
    out: dict[str, Any] = {
        "symbol": k.symbol,
        "bar_open_time_ms": t,
        "decision_time_ms": k.ct[i],
        "reference_observations_present": len(ref_ranges),
        "reference_observations_required": REFERENCE_DAYS,
        "reference_missing": missing,
    }
    if missing:
        out.update(result=NO_SIGNAL, reason="REFERENCE_HISTORY_INCOMPLETE", emitted=False)
        return out
    range_ = k.h[i] - k.l[i]
    body = k.c[i] - k.o[i]
    out["volume"] = k.v[i]
    out["range"] = range_
    out["body"] = body
    out["reference_volume_max"] = max(k.v[k.index[s]] for s in reference_slots(t))
    out["reference_range_max"] = max(ref_ranges)
    if not (range_ > out["reference_range_max"]):
        out.update(result=NO_SIGNAL, reason="NO_EXCURSION_RECORD", emitted=False)
        return out
    if range_ <= 0.0 or body == 0.0:
        out.update(result=NO_SIGNAL, reason="NO_EXHAUSTION", emitted=False)
        return out
    if body > 0.0:
        exhausted = (k.h[i] - k.c[i]) > range_ / 2.0
        direction = SHORT
        wick_fraction = (k.h[i] - k.c[i]) / range_
    else:
        exhausted = (k.c[i] - k.l[i]) > range_ / 2.0
        direction = LONG
        wick_fraction = (k.c[i] - k.l[i]) / range_
    out["wick_fraction"] = wick_fraction
    if not exhausted:
        out.update(result=NO_SIGNAL, reason="NO_EXHAUSTION", emitted=False)
        return out
    out.update(result=direction, reason=None, emitted=True)
    return out


def emit_participation_control_trades(
    partitions: dict[str, Kline5m],
    *,
    start_ms: int,
    end_ms: int,
    asset_order: tuple[str, ...] | None = None,
) -> RefResult:
    """Signal generation for the PARTICIPATION_CONTROL (volume record removed).

    Mirrors the frozen reference emission loop exactly (same window handling, same
    strict-after decision entry, same 12-bar exit, same overlap/re-entry rule, same
    reason precedence minus NO_PARTICIPATION_SHOCK). This is an isolated experimental
    comparator with its OWN (larger) trade set; it never touches the primary set.
    """
    if asset_order is None:
        asset_order = tuple(a for a in ASSETS if a in partitions)
    trades: list[RefTrade] = []
    funnel: dict[str, int] = {reason: 0 for reason in PARTICIPATION_CONTROL_PRECEDENCE}
    decisions = 0

    for asset in asset_order:
        k = partitions[asset]
        next_free_index = 0
        for i in range(k.rows):
            bar_open = k.t[i]
            if bar_open > end_ms:
                break
            if bar_open < start_ms:
                funnel["OUTSIDE_COMMON_WINDOW"] += 1
                continue
            decisions += 1
            ev = _evaluate_without_participation(k, i)
            if not ev["emitted"]:
                funnel[ev["reason"]] += 1
                continue
            if i < next_free_index:
                funnel["POSITION_ALREADY_OPEN"] += 1
                continue
            decision_time_ms = int(ev["decision_time_ms"])
            entry_i = k.first_index_strictly_after(decision_time_ms)
            if entry_i is None:
                funnel["INSUFFICIENT_FORWARD_PRICE_DATA"] += 1
                continue
            entry_time_ms = k.t[entry_i]
            if entry_time_ms > end_ms:
                funnel["INSUFFICIENT_FORWARD_PRICE_DATA"] += 1
                continue
            exit_time_ms = entry_time_ms + HOLDING_MS
            if exit_time_ms > end_ms:
                funnel["INSUFFICIENT_FORWARD_PRICE_DATA"] += 1
                continue
            exit_i = k.slot_index(exit_time_ms)
            if exit_i is None:
                funnel["INSUFFICIENT_FORWARD_PRICE_DATA"] += 1
                continue
            direction = ev["result"]
            trades.append(
                RefTrade(
                    trade_id=f"{asset}-{i:08d}",
                    asset=asset,
                    direction=direction,
                    direction_sign=1 if direction == LONG else -1,
                    signal_bar_open_time_ms=bar_open,
                    decision_time_ms=decision_time_ms,
                    reference_observations_present=int(ev["reference_observations_present"]),
                    volume=float(ev["volume"]),
                    reference_volume_max=float(ev["reference_volume_max"]),
                    range=float(ev["range"]),
                    reference_range_max=float(ev["reference_range_max"]),
                    body=float(ev["body"]),
                    wick_fraction=float(ev["wick_fraction"]),
                    entry_bar_index=entry_i,
                    entry_time_ms=entry_time_ms,
                    entry_price=k.o[entry_i],
                    exit_bar_index=exit_i,
                    exit_time_ms=exit_time_ms,
                    exit_price=k.o[exit_i],
                )
            )
            next_free_index = exit_i

    return RefResult(trades=tuple(trades), funnel=funnel, decisions_evaluated=decisions)


def null_control_series(trades: list[ExecutedTrade], *, cost_bps: int = PRIMARY_COST_BPS) -> dict[str, Any]:
    """NULL_CONTROL (frozen): deterministic sign-flip with ``random.Random(20260915)``
    over the frozen emission order. Never Python ``hash()``.

    The flip factor per trade is applied to the realized net return; the SAME factor is
    applied to the ex-funding leg so the full critical gate set (including G3) remains
    evaluable on the control series. Timestamps, assets, magnitudes and counts unchanged.

    Frozen-before-observation interpretation: ``ARC03_CONTROL_PLAN.json`` defines the flip
    on the 10 bps realized net returns and requires the FULL critical gate set (which
    includes G3 and G11) to be evaluated on the flipped series. The same per-trade factor
    is therefore applied to the ex-funding leg and to the 20/40 bps re-pricings; no
    parameter of the flip itself depends on any realized outcome.
    """
    rng = random.Random(NULL_SEED)
    ordered = sorted(trades, key=lambda x: x.emission_index)
    factors: list[int] = [1 if rng.random() < 0.5 else -1 for _ in ordered]
    nets = [t.net_return(cost_bps) * f for t, f in zip(ordered, factors, strict=True)]
    nets_ex = [
        t.net_return_ex_funding(cost_bps) * f for t, f in zip(ordered, factors, strict=True)
    ]
    return {
        "nets": nets,
        "nets_ex_funding": nets_ex,
        "factors": factors,
        "order": [t.trade_id for t in ordered],
        "nets_by_scenario": {
            bps: [t.net_return(bps) * f for t, f in zip(ordered, factors, strict=True)]
            for bps in COST_SCENARIOS_BPS
        },
        "nets_ex_funding_by_scenario": {
            bps: [
                t.net_return_ex_funding(bps) * f
                for t, f in zip(ordered, factors, strict=True)
            ]
            for bps in COST_SCENARIOS_BPS
        },
    }


def frozen_gate_order(trades: list[ExecutedTrade]) -> list[ExecutedTrade]:
    """The FROZEN G8 ordering: ``entry_time_ms`` ascending, ties broken by the frozen
    emission order (asset order BTCUSDT, ETHUSDT, SOLUSDT, then decision_time_ms).

    ``ARC03_STATISTICAL_GATES.json#convention_bindings.temporal_split.ordering`` binds
    this ordering for the chronological half/quartile split. Because the emission order
    is asset-major, a settlement grouping by emission index alone would NOT be a
    chronological split of the trade timeline, so the sort key is explicit here.
    """
    return sorted(trades, key=lambda x: (x.entry_time_ms, x.emission_index))


def participation_control_records(
    trades: list[ExecutedTrade], *, cost_bps: int = PRIMARY_COST_BPS
) -> tuple[list[TradeRecord], list[float], list[float]]:
    """Gate inputs for the PARTICIPATION_CONTROL trade set (its own, larger set)."""
    return gate_inputs(trades, cost_bps=cost_bps)


def gate_records(trades: list[ExecutedTrade], *, cost_bps: int) -> list[TradeRecord]:
    """TradeRecords in the frozen G8 ordering for the gate evaluators."""
    return [
        TradeRecord(
            trade_id=t.trade_id,
            asset=t.asset,
            entry_time_ms=t.entry_time_ms,
            net_return=t.net_return(cost_bps),
            net_return_ex_funding=t.net_return_ex_funding(cost_bps),
        )
        for t in frozen_gate_order(trades)
    ]


def gate_inputs(
    trades: list[ExecutedTrade], *, cost_bps: int = PRIMARY_COST_BPS
) -> tuple[list[TradeRecord], list[float], list[float]]:
    """(records, net@20bps, net@40bps) all in the SAME frozen G8 order.

    The 20/40 bps vectors are re-priced on the IDENTICAL trade set (frozen cost model:
    costs never regenerate signals).
    """
    ordered = frozen_gate_order(trades)
    records = [
        TradeRecord(
            trade_id=t.trade_id,
            asset=t.asset,
            entry_time_ms=t.entry_time_ms,
            net_return=t.net_return(cost_bps),
            net_return_ex_funding=t.net_return_ex_funding(cost_bps),
        )
        for t in ordered
    ]
    nets20 = [t.net_return(20) for t in ordered]
    nets40 = [t.net_return(40) for t in ordered]
    return records, nets20, nets40


def control_summary(trades: list[ExecutedTrade], *, cost_bps: int = PRIMARY_COST_BPS) -> dict[str, Any]:
    records = gate_records(trades, cost_bps=cost_bps)
    nets = [r.net_return for r in records]
    n = len(nets)
    pf, _ = profit_factor(nets)
    sharpe, _ = annualized_sharpe(nets)
    return {
        "trade_count": n,
        "mean_net_return_10bps": (sum(nets) / n if n else 0.0),
        "mean_net_return_ex_funding_10bps": (
            sum(r.net_return_ex_funding for r in records) / n if n else 0.0
        ),
        "profit_factor": (pf if pf != float("inf") else "Infinity"),
        "sharpe": sharpe,
    }


def evaluate_control_gates(
    records: list[TradeRecord], nets20: list[float], nets40: list[float]
) -> list[GateResult]:
    return evaluate_gates(records, net_returns_20bps=nets20, net_returns_40bps=nets40)


# ------------------------------------------------------------------ reconciliation
def accounting_reconciliation(
    trades: list[ExecutedTrade], *, tolerance: float = ACCOUNTING_TOLERANCE
) -> dict[str, Any]:
    """Verify NET = GROSS + FUNDING - COST exactly (within declared tolerance) for every
    trade at every frozen cost scenario, and that the ex-funding leg contains ZERO
    funding contribution."""
    checks = 0
    violations: list[dict[str, Any]] = []
    for t in trades:
        for bps in COST_SCENARIOS_BPS:
            net = t.net_return(bps)
            identity = t.gross_price_return + t.funding_cashflow_return - t.cost_return(bps)
            checks += 1
            if abs(net - identity) > tolerance:
                violations.append(
                    {"trade_id": t.trade_id, "cost_bps": bps, "net": net, "identity": identity}
                )
        ex = t.net_return_ex_funding(PRIMARY_COST_BPS)
        identity_ex = t.gross_price_return - t.cost_return(PRIMARY_COST_BPS)
        checks += 1
        if abs(ex - identity_ex) > tolerance:
            violations.append(
                {"trade_id": t.trade_id, "cost_bps": "ex_funding", "net": ex, "identity": identity_ex}
            )
    return {
        "checks": checks,
        "violations": violations,
        "tolerance": tolerance,
        "verdict": "PASS" if not violations else "FAIL",
    }


def trade_ledger_reconciliation(
    trades: list[ExecutedTrade],
    ref: RefResult,
    ledger_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    """Funnel/ledger identity checks (mission §34)."""
    evaluated = ref.decisions_evaluated
    funnel = dict(ref.funnel)
    # OUTSIDE_COMMON_WINDOW bars are bars the frozen window deliberately EXCLUDES; they
    # are reported, but they are not decisions and therefore not part of the decision
    # reconciliation universe (the prereg: "decision_must_lie_in_common_window").
    outside = int(funnel.get("OUTSIDE_COMMON_WINDOW", 0))
    rejected = sum(v for k, v in funnel.items() if k != "OUTSIDE_COMMON_WINDOW")
    executed = len(ref.trades)
    checks: dict[str, Any] = {
        "decisions_evaluated": evaluated,
        "explicitly_rejected": rejected,
        "bars_outside_common_window": outside,
        "bars_examined_total": evaluated + outside,
        "executed": executed,
        "evaluated_equals_rejected_plus_executed": evaluated == rejected + executed,
        "full_accounting_identity": evaluated + outside == sum(funnel.values()) + executed,
        "ledger_rows": len(ledger_rows),
        "ledger_rows_equal_trades": len(ledger_rows) == executed,
        "trade_ids_identical": [t.trade_id for t in trades] == [r["trade_id"] for r in ledger_rows],
        "funnel": funnel,
    }
    per_asset: dict[str, int] = {a: 0 for a in ASSETS}
    longs = shorts = 0
    for t in trades:
        per_asset[t.asset] = per_asset.get(t.asset, 0) + 1
        if t.direction == "LONG":
            longs += 1
        else:
            shorts += 1
    checks["per_asset_counts"] = per_asset
    checks["asset_counts_sum_to_total"] = sum(per_asset.values()) == executed
    checks["long_count"] = longs
    checks["short_count"] = shorts
    checks["long_plus_short_equals_total"] = longs + shorts == executed
    ok = (
        checks["evaluated_equals_rejected_plus_executed"]
        and checks["full_accounting_identity"]
        and checks["ledger_rows_equal_trades"]
        and checks["trade_ids_identical"]
        and checks["asset_counts_sum_to_total"]
        and checks["long_plus_short_equals_total"]
    )
    checks["verdict"] = "PASS" if ok else "FAIL"
    return checks


__all__ = [
    "ACCOUNTING_TOLERANCE",
    "ASSETS",
    "COST_SCENARIOS_BPS",
    "EXPERIMENT_ID",
    "NULL_SEED",
    "PARTICIPATION_CONTROL_PRECEDENCE",
    "PRIMARY_COST_BPS",
    "ExecutedTrade",
    "ExperimentLedger",
    "RefResult",
    "RefTrade",
    "accounting_reconciliation",
    "all_critical_gates_pass",
    "build_executed_trades",
    "control_summary",
    "direction_control_trades",
    "emit_participation_control_trades",
    "emit_trades",
    "evaluate_control_gates",
    "frozen_gate_order",
    "gate_inputs",
    "gate_records",
    "ledger_row",
    "null_control_series",
    "participation_control_records",
    "timing_control_trades",
    "trade_ledger_reconciliation",
]
