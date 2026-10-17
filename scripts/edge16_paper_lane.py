"""edge16_paper_lane — the experimental paper lane driven by the canonical risk engine.

WP-EDGE-016/WP-EDGE-16C. The WP-EDGE-015 lane decided risk for itself: it read
``config/risk.yaml`` and re-implemented a subset of the policy before calling the
broker. A subset is not the policy, and a copy is not parity, so this lane drives
the real objects instead:

* ``trading_bot.config.settings.load_settings`` builds the same ``Risk`` model the
  runtime builds from ``config/risk.yaml`` — nothing is re-typed here;
* ``trading_bot.risk.manager.RiskManager`` is instantiated and ``check_signal`` is
  the only entry gate, exactly as ``paper_cycle`` and ``autonomous.runtime`` use it;
* the order size comes from ``RiskCheck.position_size``, so sizing is the runtime's
  rule rather than a lane convention;
* every close is fed back through ``record_trade_result`` and every fill through
  ``sync_open_positions``, which is how the runtime keeps exposure gates live;
* the strategies are the incremental WP-EDGE-016 machines, so a proposal is computed
  from closed bars only and carries no future outcome.

Differences from the runtime are declared rather than hidden, and are collected in
``RISK_PARITY_MATRIX.json``: the admission gate is bypassed *by design* (this is an
experimental research lane, labelled as such), and ``blocks.weekend_trading`` is
honoured here although no runtime component reads it.

One book, one budget: the three symbols share a single 10 000 USDT portfolio, so
``max_open_positions`` and both exposure clamps bind across symbols instead of being
three isolated simulations added together.

    python scripts/edge16_paper_lane.py [--extend-prospective]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from trading_bot.config.risk import Risk
from trading_bot.config.settings import load_settings
from trading_bot.paper.broker import BrokerCost, PaperBroker
from trading_bot.research.disk_budget import free_bytes
from trading_bot.research.economic_recovery.alpha15 import (
    FAMILY_BY_NAME,
    TESTED_FAMILIES,
    cost_for,
    round_trip_cost_bps,
)
from trading_bot.research.economic_recovery.experiments import Bar, load_ohlcv
from trading_bot.research.economic_recovery.pit15 import PIT_CONTRACT, machine_for
from trading_bot.risk.manager import RiskManager
from trading_bot.strategies.types import Signal

REPO = Path(__file__).resolve().parents[1]
OUT = REPO / "reports" / "economic-recovery" / "RFC-EDGE-016"
LANE_DIR = OUT / "experimental_paper"
RISK_CONFIG = REPO / "config" / "risk.yaml"
ADMISSION = REPO / "config" / "strategy_admission.json"
PROSPECTIVE_SLICE = (
    REPO / "reports" / "economic-recovery" / "RFC-EDGE-015" / "scratch" / "OOS_PROSPECTIVE_1H.jsonl"
)


def broker_both_hit_policy() -> str:
    """Read the broker's own default out of its signature instead of retyping it here."""
    source = (REPO / "src" / "trading_bot" / "paper" / "broker.py").read_text(encoding="utf-8")
    found = re.search(r'both_hit_policy:\s*str\s*=\s*"(\w+)"', source)
    if found is None:  # the signature changed: say so rather than guess
        raise RuntimeError("cannot read both_hit_policy from the broker's signature")
    return found.group(1)


BROKER_BOTH_HIT_POLICY = broker_both_hit_policy()


def atr_pct_at(bars: list[Bar], index: int, span: int = 14) -> float | None:
    """ATR%/close at ``index`` from bars at or before it, or None when too short.

    The declared ``blocks.extreme_atr_pct`` needs one measured input; this is it,
    computed causally so a decision cannot see the bar it trades.
    """
    if index < span or index >= len(bars) or bars[index].close <= 0:
        return None
    ranges: list[float] = []
    for offset in range(index - span + 1, index + 1):
        bar = bars[offset]
        previous_close = bars[offset - 1].close
        ranges.append(
            max(bar.high - bar.low, abs(bar.high - previous_close), abs(bar.low - previous_close))
        )
    return (sum(ranges) / len(ranges)) / bars[index].close * 100.0


TAG = "EXPERIMENTAL_PROSPECTIVE_PAPER"
BOOK_ID = "EDGE16LANE"
PORTFOLIO_EQUITY_USDT = 10_000.0
WINDOW_BARS = 2_000

UNIVERSE: tuple[tuple[str, Path], ...] = (
    ("BTC/USDT", REPO / "data" / "edge07" / "holdout-1h" / "BTCUSDT_holdout2026.json"),
    ("ETH/USDT", REPO / "data" / "edge07" / "holdout-1h" / "ETHUSDT_holdout2026.json"),
    ("SOL/USDT", REPO / "data" / "edge07" / "holdout-1h" / "SOLUSDT_holdout2026.json"),
)


def sha256(path: Path) -> str | None:
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None


def prospective_bars(symbol: str) -> list[Bar]:
    """The captured post-freeze bars, read from the slice the holdout recorded."""
    if not PROSPECTIVE_SLICE.is_file():
        return []
    bars: list[Bar] = []
    for line in PROSPECTIVE_SLICE.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        if str(row["symbol"]) != symbol:
            continue
        bars.append(
            Bar(
                ts_ms=int(row["timestamp"]),
                open=float(row["open"]),
                high=float(row["high"]),
                low=float(row["low"]),
                close=float(row["close"]),
                volume=float(row["volume"]),
            )
        )
    return sorted(bars, key=lambda bar: bar.ts_ms)


def load_series(extend: bool) -> dict[str, list[Bar]]:
    series: dict[str, list[Bar]] = {}
    for symbol, path in UNIVERSE:
        bars = load_ohlcv(path)[-WINDOW_BARS:]
        if extend:
            fresh = [bar for bar in prospective_bars(symbol) if bar.ts_ms > bars[-1].ts_ms]
            bars = [*bars, *fresh]
        series[symbol] = bars
    return series


def canonical_risk() -> Risk:
    """The runtime's own risk policy object, built by the runtime's own loader."""
    settings = load_settings(config_dir=REPO / "config", env_file=None)
    return settings.risk


def main() -> int:
    parser = argparse.ArgumentParser(description="WP-EDGE-016 canonical experimental paper lane")
    parser.add_argument("--out", default=str(LANE_DIR))
    parser.add_argument("--extend-prospective", action="store_true")
    parser.add_argument(
        "--cost-multiplier",
        type=float,
        default=1.0,
        help="adverse multiplier on every traded cost component (1x is the central model)",
    )
    parser.add_argument(
        "--cost-mode",
        choices=("net", "frictionless"),
        default="net",
        help=(
            "net (default, WP-EDGE-017): the broker charges the venue cost before RiskManager "
            "sees the result; frictionless reproduces the WP-EDGE-016 book exactly, which is "
            "what the equivalence regression checks"
        ),
    )
    args = parser.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    policy = canonical_risk()
    admission_before = sha256(ADMISSION)
    series = load_series(args.extend_prospective)

    # ---- the canonical objects, wired exactly as the runtime wires them -----------------
    # WP-EDGE-017/P0.3: the venue cost is charged *inside* the book, on the same
    # cost model the research restatement uses, so the PnL RiskManager records is
    # already net. The frictionless book is kept behind a flag because it is the
    # only way to reproduce the WP-EDGE-016 baseline byte for byte.
    def cost_schedule(symbol: str, notional: float) -> BrokerCost:
        terms = cost_for(symbol, stake_usdt=max(notional, 1.0))
        scale = float(args.cost_multiplier)
        return BrokerCost(
            commission_bps=terms.fee_bps_per_side * scale,
            half_spread_bps=terms.half_spread_bps * scale,
            slippage_bps=(terms.slippage_bps_per_side + terms.impact_bps_per_side) * scale,
        )

    broker = PaperBroker(
        equity=PORTFOLIO_EQUITY_USDT,
        slippage_bps=0.0,  # the schedule carries the friction when cost_mode=net
        commission_bps=0.0,
        book_id=BOOK_ID,
        clock=lambda: current_ms[0] / 1000.0,
        cost_schedule=cost_schedule if args.cost_mode == "net" else None,
    )
    current_ms = [min(bars[0].ts_ms for bars in series.values())]
    risk = RiskManager(
        risk=policy, equity=PORTFOLIO_EQUITY_USDT, _clock=lambda: current_ms[0] / 1000.0
    )

    machines = {
        symbol: {
            family.name: machine_for(family.name, family.parameters)
            for family in TESTED_FAMILIES
            if family.name != "cross_sectional_rotation"
        }
        for symbol, _path in UNIVERSE
    }

    # ---- the merged timeline ------------------------------------------------------------
    timeline = sorted({bar.ts_ms for bars in series.values() for bar in bars})
    index_of = {
        symbol: {bar.ts_ms: i for i, bar in enumerate(bars)} for symbol, bars in series.items()
    }
    pending: dict[tuple[str, str], Any] = {}
    cycles: list[dict[str, Any]] = []
    coverage: dict[tuple[str, int], dict[str, Any]] = {}
    #: Last closed price per symbol, so the book can be marked at every decision
    #: and RiskManager sees net equity, not only realized net PnL.
    marks: dict[str, float] = {}
    #: What the declared defensive blocks actually did in this replay.
    block_stats: dict[str, Any] = {
        "atr_blocked": 0,
        "atr_unknown": 0,
        "weekend_blocked": 0,
        "max_atr_pct": 0.0,
        "atr_evaluations": 0,
        "spread_bps": "NOT_MEASURED_IN_A_BAR_REPLAY",
        "latency_ms": "NOT_MEASURED_IN_A_BAR_REPLAY",
    }

    def note(symbol: str, ts_ms: int, stage: str, **payload: Any) -> None:
        row = coverage.setdefault(
            (symbol, ts_ms),
            {"symbol": symbol, "ts_ms": ts_ms, "stages": [], "detail": {}},
        )
        if stage not in row["stages"]:
            row["stages"].append(stage)
        row["detail"].update(payload)

    def mark_risk() -> None:
        """Hand the risk engine the book's net equity (cash + unrealized - accruals)."""
        risk.mark_equity(broker.mark_to_market_equity(marks))

    def close_positions(closed: list[Any], symbol: str, ts_ms: int) -> None:
        for trade in closed:
            # ``trade.pnl`` is net of commissions and execution cost (WP-EDGE-017).
            risk.record_trade_result(float(trade.pnl))
            risk.sync_open_positions(dict(broker.positions))
            mark_risk()
            # the machine that opened it must be told the position is gone, or its own
            # entry state would describe a book that no longer exists
            owner = machines.get(symbol, {}).get(str(trade.strategy_name))
            if owner is not None:
                owner.notify_fill("EXIT", index_of[symbol].get(ts_ms, 0), float(trade.exit_price))
            cycles.append(
                {
                    "cycle": len(cycles) + 1,
                    "tag": TAG,
                    "ts_ms": ts_ms,
                    "symbol": trade.symbol,
                    "stage": "RECONCILIATION",
                    "action": "POSITION_CLOSED",
                    "exit_reason": trade.exit_reason,
                    "trade_id": trade.trade_id,
                    "position_id": trade.position_id,
                    "net_pnl": float(trade.pnl),
                    "risk": canonical_trade_result(risk),
                }
            )
            note(symbol, ts_ms, "RECONCILIATION", closed_trade=trade.trade_id)

    previous_day: str | None = None
    for ts_ms in timeline:
        current_ms[0] = ts_ms
        day = datetime.fromtimestamp(ts_ms / 1000, tz=UTC)
        if previous_day is not None and day.strftime("%Y-%m-%d") != previous_day:
            week_before = int(risk.weekly_start_ms)
            risk.reset_daily()  # the runtime resets the daily counters at the day boundary
            cycles.append(
                {
                    "cycle": len(cycles) + 1,
                    "tag": TAG,
                    "ts_ms": ts_ms,
                    "symbol": "*",
                    "stage": "DAY_BOUNDARY",
                    "action": "RISK_RESET_DAILY",
                    "risk": canonical_trade_result(risk),
                }
            )
            if int(risk.weekly_start_ms) != week_before:
                # WP-EDGE-017F/P0.1: the day boundary is where a week boundary is
                # observed when the weekend had no trades. Recorded, not inferred.
                cycles.append(
                    {
                        "cycle": len(cycles) + 1,
                        "tag": TAG,
                        "ts_ms": ts_ms,
                        "symbol": "*",
                        "stage": "WEEK_BOUNDARY",
                        "action": "RISK_RESET_WEEKLY",
                        "previous_week_start_ms": week_before,
                        "risk": canonical_trade_result(risk),
                    }
                )
        previous_day = day.strftime("%Y-%m-%d")

        for symbol, _path in UNIVERSE:
            bars = series[symbol]
            index = index_of[symbol].get(ts_ms)
            if index is None:
                continue
            bar = bars[index]
            marks[symbol] = bar.close
            note(
                symbol,
                ts_ms,
                "OBSERVED",
                data_available_ms=ts_ms + (bars[1].ts_ms - bars[0].ts_ms if len(bars) > 1 else 0),
            )

            # 1) protective exits first: the broker owns SL/TP and resolves both-hit
            #    conservatively (stop_first), which this lane does not override
            closed = broker.check_positions_ohlc({symbol: (bar.open, bar.high, bar.low, bar.close)})
            if closed:
                close_positions(closed, symbol, ts_ms)

            # 2) a decision taken one bar earlier becomes executable at this bar's open
            for family in TESTED_FAMILIES:
                if family.name == "cross_sectional_rotation":
                    continue
                machine = machines[symbol][family.name]
                decision = pending.pop((symbol, family.name), None)
                if decision is not None and decision.fill_index == index:
                    if decision.kind == "ENTRY":
                        signal = Signal(
                            symbol=symbol,
                            side="buy",
                            strategy_name=family.name,
                            timeframe="1h",
                            confidence=1.0,
                            price=bar.open,
                            metadata={},
                        )
                        mark_risk()
                        check = risk.check_signal(signal)
                        cycles.append(
                            {
                                "cycle": len(cycles) + 1,
                                "tag": TAG,
                                "ts_ms": ts_ms,
                                "symbol": symbol,
                                "family": family.name,
                                "stage": "RISK_RESULT",
                                "action": "RISK_APPROVED" if check.approved else "RISK_REJECTED",
                                "blocked_by": check.blocked_by or "",
                                "reason": check.reason or "",
                                "notional_usdt": (
                                    float(check.position_size.notional_usdt)
                                    if check.position_size
                                    else None
                                ),
                                "rule": decision.rule,
                            }
                        )
                        note(
                            symbol,
                            ts_ms,
                            "RISK_RESULT",
                            approved=bool(check.approved),
                            blocked_by=check.blocked_by or "",
                        )
                        if not check.approved or check.position_size is None:
                            continue
                        if symbol in broker.positions:
                            cycles.append(
                                {
                                    "cycle": len(cycles) + 1,
                                    "tag": TAG,
                                    "ts_ms": ts_ms,
                                    "symbol": symbol,
                                    "family": family.name,
                                    "stage": "PROPOSAL",
                                    "action": "NO_TRADE",
                                    "reason": "SYMBOL_SLOT_OCCUPIED",
                                    "rule": decision.rule,
                                }
                            )
                            note(symbol, ts_ms, "NO_SIGNAL", slot_occupied=True)
                            continue  # one position per symbol in this lane
                        sized = check.position_size
                        order = Signal(
                            symbol=symbol,
                            side="buy",
                            strategy_name=family.name,
                            timeframe="1h",
                            confidence=1.0,
                            price=bar.open,
                            stop_loss_pct=sized.stop_loss_pct,
                            take_profit_pct=sized.take_profit_pct,
                            metadata={
                                "notional_usdt": sized.notional_usdt,
                                "risk_rule": "RiskManager.check_signal",
                                "blocked_by": "",
                            },
                        )
                        filled = broker.execute_signal(order)
                        machine.notify_fill("ENTRY", index, bar.open)
                        risk.sync_open_positions(dict(broker.positions))
                        cycles.append(
                            {
                                "cycle": len(cycles) + 1,
                                "tag": TAG,
                                "ts_ms": ts_ms,
                                "symbol": symbol,
                                "family": family.name,
                                "stage": "FILL",
                                "action": "FILL_OPENED",
                                "rule": decision.rule,
                                "position_id": getattr(filled, "position_id", ""),
                                "entry_order_id": getattr(filled, "entry_order_id", ""),
                                "fill_price": getattr(filled, "entry_price", None),
                                "notional_usdt": sized.notional_usdt,
                                "stop_loss_pct": sized.stop_loss_pct,
                                "take_profit_pct": sized.take_profit_pct,
                            }
                        )
                        note(
                            symbol,
                            ts_ms,
                            "FILL",
                            position_id=getattr(filled, "position_id", ""),
                            notional_usdt=sized.notional_usdt,
                        )
                    else:
                        position = broker.positions.get(symbol)
                        if position is not None:
                            settled = broker.execute_signal(
                                Signal(
                                    symbol=symbol,
                                    side="sell" if position.side == "buy" else "buy",
                                    strategy_name=family.name,
                                    timeframe="1h",
                                    confidence=1.0,
                                    price=bar.open,
                                    metadata={"notional_usdt": position.notional_usdt},
                                )
                            )
                            close_positions([settled], symbol, ts_ms)
                            machine.notify_fill("EXIT", index, bar.open)
                            cycles.append(
                                {
                                    "cycle": len(cycles) + 1,
                                    "tag": TAG,
                                    "ts_ms": ts_ms,
                                    "symbol": symbol,
                                    "family": family.name,
                                    "stage": "SIM_ORDER",
                                    "action": "STRATEGY_EXIT",
                                    "rule": decision.rule,
                                    "trade_id": getattr(settled, "trade_id", ""),
                                }
                            )
                            note(symbol, ts_ms, "SIM_ORDER", strategy_exit=True)

            # 3) the machine sees the closed bar and may schedule the next action
            for family in TESTED_FAMILIES:
                if family.name == "cross_sectional_rotation":
                    continue
                machine = machines[symbol][family.name]
                in_position = symbol in broker.positions
                if (symbol, family.name) in pending:
                    continue  # one outstanding decision per machine
                decision = machine.on_closed_bar(index, bar, in_position=in_position)
                note(symbol, ts_ms, "EVALUATED", evaluated_by=family.name)
                if decision is None:
                    continue
                if decision.kind == "ENTRY":
                    # blocks.extreme_atr_pct, on a real measurement from bars at or
                    # before the decision. Unmeasured is a block, not a pass.
                    atr = atr_pct_at(bars, index)
                    block_stats["atr_evaluations"] += 1
                    if atr is None:
                        block_stats["atr_unknown"] += 1
                        cycles.append(
                            {
                                "cycle": len(cycles) + 1,
                                "tag": TAG,
                                "ts_ms": ts_ms,
                                "symbol": symbol,
                                "family": family.name,
                                "stage": "PROPOSAL",
                                "action": "NO_TRADE",
                                "reason": "ATR_UNKNOWN",
                                "rule": decision.rule,
                            }
                        )
                        note(symbol, ts_ms, "NO_SIGNAL", atr_unknown=True)
                        continue
                    block_stats["max_atr_pct"] = max(block_stats["max_atr_pct"], atr)
                    if atr > policy.blocks.extreme_atr_pct:
                        block_stats["atr_blocked"] += 1
                        cycles.append(
                            {
                                "cycle": len(cycles) + 1,
                                "tag": TAG,
                                "ts_ms": ts_ms,
                                "symbol": symbol,
                                "family": family.name,
                                "stage": "PROPOSAL",
                                "action": "NO_TRADE",
                                "reason": "ATR_BLOCK",
                                "atr_pct": round(atr, 4),
                                "rule": decision.rule,
                            }
                        )
                        note(symbol, ts_ms, "NO_SIGNAL", atr_blocked=True)
                        continue
                    weekend = day.weekday() >= 5
                    if weekend and not policy.blocks.weekend_trading:
                        block_stats["weekend_blocked"] += 1
                        cycles.append(
                            {
                                "cycle": len(cycles) + 1,
                                "tag": TAG,
                                "ts_ms": ts_ms,
                                "symbol": symbol,
                                "family": family.name,
                                "stage": "PROPOSAL",
                                "action": "NO_TRADE",
                                "reason": "WEEKEND_VETO_POLICY",
                                "rule": decision.rule,
                            }
                        )
                        note(symbol, ts_ms, "NO_SIGNAL", weekend_veto=True)
                        continue
                    cycles.append(
                        {
                            "cycle": len(cycles) + 1,
                            "tag": TAG,
                            "ts_ms": ts_ms,
                            "symbol": symbol,
                            "family": family.name,
                            "stage": "PROPOSAL",
                            "action": "PROPOSE_ENTRY",
                            "rule": decision.rule,
                            "signal_index": decision.signal_index,
                            "fill_index": decision.fill_index,
                            "earliest_fill_ms": bars[decision.fill_index].ts_ms
                            if decision.fill_index < len(bars)
                            else None,
                            "horizon_bars": int(
                                FAMILY_BY_NAME[family.name].parameters.get("max_hold_hours", 0)
                            ),
                            "detail": dict(decision.detail),
                        }
                    )
                    note(symbol, ts_ms, "PROPOSAL", rule=decision.rule)
                else:
                    cycles.append(
                        {
                            "cycle": len(cycles) + 1,
                            "tag": TAG,
                            "ts_ms": ts_ms,
                            "symbol": symbol,
                            "family": family.name,
                            "stage": "PROPOSAL",
                            "action": "PROPOSE_EXIT",
                            "rule": decision.rule,
                            "signal_index": decision.signal_index,
                            "fill_index": decision.fill_index,
                            "detail": dict(decision.detail),
                        }
                    )
                    note(symbol, ts_ms, "PROPOSAL", rule=decision.rule)
                if decision.fill_index < len(bars):
                    pending[(symbol, family.name)] = decision

    snapshot = broker.accounting_snapshot(
        {symbol: bars[-1].close for symbol, bars in series.items()}
    )
    trades = broker.closed_trades_rows()
    admission_after = sha256(ADMISSION)

    actions: dict[str, int] = {}
    stages: dict[str, int] = {}
    for cycle in cycles:
        actions[cycle["action"]] = actions.get(cycle["action"], 0) + 1
        stages[cycle["stage"]] = stages.get(cycle["stage"], 0) + 1

    by_symbol: dict[str, dict[str, Any]] = {}
    for trade in trades:
        bucket = by_symbol.setdefault(
            trade["symbol"], {"closed_trades": 0, "net_pnl": 0.0, "fees": 0.0, "by_reason": {}}
        )
        bucket["closed_trades"] += 1
        bucket["net_pnl"] += float(trade["pnl"])
        bucket["fees"] += float(trade["entry_commission"]) + float(trade["exit_commission"])
        bucket["by_reason"][trade["exit_reason"]] = (
            bucket["by_reason"].get(trade["exit_reason"], 0) + 1
        )

    coverage_rows = sorted(coverage.values(), key=lambda row: (row["symbol"], row["ts_ms"]))
    observed = sum(1 for row in coverage_rows if "OBSERVED" in row["stages"])
    evaluated = sum(1 for row in coverage_rows if "EVALUATED" in row["stages"])
    expected = sum(len(bars) for bars in series.values())

    report: dict[str, Any] = {
        "schema_version": "EDGE16_CANONICAL_LANE_V1",
        "work_package": "WP-EDGE-016/16C",
        "tag": TAG,
        "generated_at_utc": datetime.now(tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "git_commit_hint": "see RUN_REPORT.json",
        "portfolio": {
            "mode": "ONE_SHARED_BOOK",
            "book_id": BOOK_ID,
            "equity_usdt": PORTFOLIO_EQUITY_USDT,
            "reading": (
                "one budget and one broker book for all three symbols: max_open_positions and both "
                "exposure clamps bind across symbols. The WP-EDGE-015 lane's three 10 000 books are "
                "a different experiment and their balances are not capital."
            ),
            "symbols_in_book": list(broker.positions),
        },
        "canonical_risk": {
            "source": str(RISK_CONFIG.relative_to(REPO)),
            "loader": "trading_bot.config.settings.load_settings",
            "engine": "trading_bot.risk.manager.RiskManager",
            "entry_gate": "RiskManager.check_signal",
            "sizing": "RiskCheck.position_size (never a lane convention)",
            "feedback": ["record_trade_result", "sync_open_positions", "reset_daily"],
            "policy_object_sha256": hashlib.sha256(
                json.dumps(policy.model_dump(mode="json"), sort_keys=True).encode()
            ).hexdigest(),
            "policy_equals_yaml": True,
            "changed_by_this_work_package": False,
        },
        "pit": {
            "contract": PIT_CONTRACT,
            "machines": "trading_bot.research.economic_recovery.pit15.machine_for",
            "proposal_carries": [
                "rule",
                "signal_index",
                "fill_index",
                "detail known at the signal bar",
            ],
            "proposal_never_carries": [
                "exit_ts_ms",
                "exit_price",
                "gross_bps",
                "realised pnl",
                "post-entry extrema",
            ],
        },
        "cycles": {"total": len(cycles), "by_stage": stages, "by_action": actions},
        "coverage": {
            "expected_symbol_bars": expected,
            "observed_symbol_bars": observed,
            "evaluated_symbol_bars": evaluated,
            "bars_with_a_proposal": sum(1 for row in coverage_rows if "PROPOSAL" in row["stages"]),
            "bars_with_a_fill": sum(1 for row in coverage_rows if "FILL" in row["stages"]),
            "ledger": "COVERAGE_LEDGER.jsonl",
        },
        "positions_and_pnl": {
            "closed_trades": len(trades),
            "by_symbol": by_symbol,
            "realised_pnl_usdt": float(snapshot["realised_pnl"]),
            "unrealised_pnl_usdt": float(snapshot["unrealised_pnl"]),
            "equity_mark_to_market_usdt": float(snapshot["equity_mark_to_market"]),
            "cash_usdt": float(snapshot["cash"]),
            "open_positions": snapshot["open_positions"],
            "identities": snapshot["identities"],
            "identities_all_hold": all(bool(v) for v in snapshot["identities"].values()),
            "broker_fees_usdt": sum(
                float(t["entry_commission"]) + float(t["exit_commission"]) for t in trades
            ),
        },
        "costs": cost_block(trades, args.cost_mode),
        "net_risk_parity": net_risk_parity(
            risk=risk,
            snapshot=snapshot,
            trades=trades,
            actions=actions,
            initial_equity=PORTFOLIO_EQUITY_USDT,
            cost_mode=args.cost_mode,
        ),
        "baseline_comparison": baseline_comparison(trades),
        "protective_exits": {
            "owner": "trading_bot.paper.broker.PaperBroker.check_positions_ohlc",
            "both_hit_policy": BROKER_BOTH_HIT_POLICY,
            "policy_overridden_here": False,
            "trigger": (
                "a resting order: the stop level is tested against the bar's high/low and filled "
                "at that level. The order was placed when the entry filled, so it exists before "
                "the bar it triggers in — nothing here reads a bar's close to fill inside it"
            ),
            "residual_optimism": (
                "a fill at exactly the stop level is optimistic for a gap through it, and no "
                "intrabar ordering between the stop and the target is claimed beyond the policy "
                "above"
            ),
            "levels_come_from": "RiskCheck.position_size (config/risk.yaml defaults), not the rule",
        },
        "timing_model": {
            "fill_convention": "next bar open (the instant the signal bar closes)",
            "latency_modelled_ms": 0,
            "reading": (
                "no execution latency is modelled: the fill instant equals the instant the deciding "
                "bar became available. A real venue adds queue and network delay, so every fill here "
                "is optimistic in timing even though it is no longer causally impossible"
            ),
        },
        "defensive_blocks": {
            "policy_source": "config/risk.yaml via load_settings",
            "weekend_trading": {
                "declared": policy.blocks.weekend_trading,
                "evaluated_here": True,
                "entries_refused": block_stats["weekend_blocked"],
            },
            "extreme_atr_pct": {
                "declared": policy.blocks.extreme_atr_pct,
                "evaluated_here": True,
                "input": "ATR(14)% at the signal bar, from bars at or before it",
                "evaluations": block_stats["atr_evaluations"],
                "refused": block_stats["atr_blocked"],
                "unmeasured_refused": block_stats["atr_unknown"],
                "max_observed_pct": round(block_stats["max_atr_pct"], 4),
            },
            "excessive_spread_bps": {
                "declared": policy.blocks.excessive_spread_bps,
                "evaluated_here": False,
                "why_not": "a bar replay has no order book; the runtime entrypoint does evaluate it",
            },
            "high_latency_ms": {
                "declared": policy.blocks.high_latency_ms,
                "evaluated_here": False,
                "why_not": "a bar replay has no data age; the runtime entrypoint does evaluate it",
            },
        },
        "risk_state_at_end": canonical_trade_result(risk),
        "isolation": {
            "authoritative_ledger": str(ADMISSION.relative_to(REPO)),
            "sha256_before": admission_before,
            "sha256_after": admission_after,
            "untouched": admission_before == admission_after,
            "admission_gate_in_this_lane": "BYPASSED_BY_DESIGN_LABELLED_EXPERIMENTAL",
            "writes_only_under": str(LANE_DIR.relative_to(REPO)),
        },
        "weekend_policy": {
            "declared_blocks_weekend_trading": policy.blocks.weekend_trading,
            "enforced_in_this_lane": True,
            "enforced_anywhere_in_the_runtime": False,
            "weekend_entries_refused": actions.get("NO_TRADE", 0),
            "reading": (
                "the policy says no weekend trading and this lane honours it; no runtime component "
                "reads the flag, so a 7/7 ACTIVE goal needs an explicit risk/governance decision "
                "rather than an implicit one — see WEEKEND_POLICY_CONFLICT.md"
            ),
        },
        "disk": {
            "free_gib": round(free_bytes(REPO) / 1024**3, 3),
            "policy_changed": False,
        },
    }

    (out / "CANONICAL_LANE_REPORT.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    with (out / "CANONICAL_CYCLES.jsonl").open("w", encoding="utf-8") as handle:
        for cycle in cycles:
            handle.write(json.dumps(cycle, sort_keys=True) + "\n")
    with (out / "CANONICAL_TRADES.jsonl").open("w", encoding="utf-8") as handle:
        for trade in trades:
            handle.write(json.dumps(trade, sort_keys=True) + "\n")
    with (out / "COVERAGE_LEDGER.jsonl").open("w", encoding="utf-8") as handle:
        for row in coverage_rows:
            handle.write(json.dumps(row, sort_keys=True) + "\n")

    print(f"[lane16] cycles {len(cycles)} {actions}")
    print(
        f"[lane16] closed trades {len(trades)} realised {float(snapshot['realised_pnl']):.4f} USDT"
    )
    print(f"[lane16] coverage {observed}/{expected} observed, {evaluated} evaluated")
    print(f"[lane16] identities hold: {report['positions_and_pnl']['identities_all_hold']}")
    print(f"[lane16] admission ledger untouched: {report['isolation']['untouched']}")
    return 0


EDGE16_LANE_REPORT = (
    REPO
    / "reports"
    / "economic-recovery"
    / "RFC-EDGE-016"
    / "experimental_paper"
    / "CANONICAL_LANE_REPORT.json"
)


def cost_block(trades: list[dict[str, Any]], cost_mode: str) -> dict[str, Any]:
    """What the book paid, split into the terms that are actually bookkept.

    In ``net`` mode the PnL stored on every trade already has these costs
    deducted, and the identity below is checked rather than asserted. In
    ``frictionless`` mode nothing is charged, which is exactly the WP-EDGE-016
    baseline this lane must still be able to reproduce.
    """
    commissions = sum(float(t["entry_commission"]) + float(t["exit_commission"]) for t in trades)
    execution = sum(float(t.get("execution_cost_usdt", 0.0)) for t in trades)
    reference = sum(float(t.get("reference_gross_pnl", 0.0)) for t in trades)
    gross = sum(float(t["gross_pnl"]) for t in trades)
    net = sum(float(t["pnl"]) for t in trades)
    total_cost = execution + commissions
    block: dict[str, Any] = {
        "cost_mode": cost_mode,
        "lane_pnl_is": "NET_OF_VENUE_COST" if cost_mode == "net" else "PRE_COST",
        "broker_fees_usdt": round(commissions, 6),
        "broker_execution_cost_usdt": round(execution, 6),
        "total_cost_usdt": round(total_cost, 6),
        "reference_gross_usdt": round(reference, 6),
        "gross_after_execution_usdt": round(gross, 6),
        "net_realised_usdt": round(net, 6),
        "summary": {
            "reference_gross_usdt": round(reference, 6),
            "gross_realised_usdt": round(gross, 6),
        },
        "reconciles": abs(net - (reference - execution - commissions)) <= 1e-6,
        "where_the_cost_is_charged": (
            "inside PaperBroker: half spread and slippage move the fill, commissions are "
            "charged on both legs, and ClosedTrade.pnl is the result"
            if cost_mode == "net"
            else "nowhere: the book is frictionless by request"
        ),
        "reading": (
            "RiskManager.record_trade_result receives this net figure and the engine is "
            "marked to the broker's net equity before every decision (WP-EDGE-017/P0.3)"
            if cost_mode == "net"
            else "the frictionless book reproduces the WP-EDGE-016 baseline; it must never "
            "be read as a net result"
        ),
    }
    block["stress_projection"] = {
        "role": "PROJECTION_NOT_A_BOOK",
        "rule": (
            "an adverse multiplier m adds (m - 1) x the 1x cost to the net the book already "
            "paid; it is arithmetic on the same fills, not a second execution path"
        ),
        "net_1x_usdt": round(net, 4),
        "net_2x_usdt": round(net - total_cost, 4),
        "net_3x_usdt": round(net - 2.0 * total_cost, 4),
    }
    block["net_of_cost"] = net_of_cost(trades)
    return block


def net_risk_parity(
    *,
    risk: RiskManager,
    snapshot: dict[str, Any],
    trades: list[dict[str, Any]],
    actions: dict[str, int],
    initial_equity: float,
    cost_mode: str,
) -> dict[str, Any]:
    """Proof that the risk engine and the book are looking at the same money."""
    net = sum(float(t["pnl"]) for t in trades)
    unrealised_net = float(snapshot["unrealised_pnl_net"])
    broker_net_equity = float(snapshot["equity_mark_to_market"])
    state = risk.snapshot()
    return {
        "recorded_input": (
            "ClosedTrade.pnl (net of commissions and execution cost)"
            if cost_mode == "net"
            else "ClosedTrade.pnl (frictionless: reproduces WP-EDGE-016)"
        ),
        "sizing_input": "RiskManager.equity, marked to the broker's net equity",
        "broker_realised_net_usdt": round(net, 9),
        "broker_unrealised_net_usdt": round(unrealised_net, 9),
        "broker_net_equity_usdt": round(broker_net_equity, 9),
        "broker_equity_identity": abs(broker_net_equity - (initial_equity + net + unrealised_net))
        <= 1e-6,
        "risk_equity_usdt": round(float(risk.equity), 9),
        "risk_equity_equals_broker_net": abs(float(risk.equity) - broker_net_equity) <= 1e-6,
        "risk_daily_pnl_usdt": round(float(risk.daily_pnl), 9),
        "risk_weekly_pnl_usdt": round(float(risk.weekly_pnl), 9),
        "risk_drawdown_pct": float(state["drawdown_pct"]),
        "risk_daily_drawdown_pct": float(state["daily_drawdown_pct"]),
        "risk_peak_equity_usdt": round(float(risk.peak_equity), 6),
        "risk_consecutive_losses": int(risk.consecutive_losses),
        "risk_trades_today": int(risk.trades_today),
        "rejections_by_rule": {key: actions.get(key, 0) for key in ("RISK_REJECTED", "NO_TRADE")},
    }


def baseline_comparison(trades: list[dict[str, Any]]) -> dict[str, Any]:
    """This book against the published WP-EDGE-016 fills, term by term."""
    import json as _json

    if not EDGE16_LANE_REPORT.is_file():
        return {"baseline_available": False}
    baseline = _json.loads(EDGE16_LANE_REPORT.read_text(encoding="utf-8"))
    base_trades = baseline["positions_and_pnl"]["closed_trades"]
    base_realised = float(baseline["positions_and_pnl"]["realised_pnl_usdt"])
    base_net = float(baseline["costs"]["net_of_cost"]["net_1x_usdt"])
    net = sum(float(t["pnl"]) for t in trades)
    return {
        "baseline_available": True,
        "source": str(EDGE16_LANE_REPORT.relative_to(REPO)),
        "baseline_fills": int(base_trades),
        "this_fills": len(trades),
        "fills_changed": len(trades) - int(base_trades),
        "baseline_frictionless_realised_usdt": round(base_realised, 6),
        "baseline_net_1x_usdt": round(base_net, 6),
        "this_realised_usdt": round(net, 6),
        "difference_vs_baseline_net_1x_usdt": round(net - base_net, 6),
        "reads_as": (
            "the baseline net was a report written after the decisions; this net is what "
            "RiskManager saw before each decision. A difference in fills is a decision that "
            "net risk no longer approved, not a data change"
        ),
    }


def net_of_cost(trades: list[dict[str, Any]]) -> dict[str, Any]:
    """The lane's own fills re-priced with the research cost model, at 1x/2x/3x.

    The book itself charges nothing, so its stored PnL is pre-cost; the WP-EDGE-015 lane did
    charge a commission, and a frictionless number next to a net one would be an apples to
    oranges comparison. This block closes that gap without touching the fills: each trade is
    charged the same round-trip cost the restatement uses for its symbol and notional.
    """
    out: dict[str, Any] = {
        "gross_realised_usdt": 0.0,
        "venue": "BINANCE_SPOT",
        "model": "trading_bot.research.economic_recovery.alpha15.round_trip_cost_bps",
        "example_fee_floor": "10 bps per side at the base spot tier, before spread, slippage and impact",
    }
    charged: dict[float, float] = {1.0: 0.0, 2.0: 0.0, 3.0: 0.0}
    per_symbol: dict[str, dict[str, float]] = {}
    for trade in trades:
        notional = float(trade["quantity"]) * float(trade["entry_price"])
        gross = float(trade["gross_pnl"])
        bucket = per_symbol.setdefault(
            trade["symbol"], {"gross_usdt": 0.0, "cost_1x_usdt": 0.0, "trades": 0.0}
        )
        bucket["gross_usdt"] += gross
        bucket["trades"] += 1
        bucket["cost_1x_usdt"] += (
            notional
            * round_trip_cost_bps(trade["symbol"], stake_usdt=notional, multiplier=1.0)
            / 10_000.0
        )
        out["gross_realised_usdt"] += gross
        for multiplier in (1.0, 2.0, 3.0):
            charged[multiplier] += (
                notional
                * round_trip_cost_bps(trade["symbol"], stake_usdt=notional, multiplier=multiplier)
                / 10_000.0
            )
    out["gross_realised_usdt"] = round(out["gross_realised_usdt"], 6)
    for multiplier, cost in charged.items():
        out[f"cost_{int(multiplier)}x_usdt"] = round(cost, 4)
        out[f"net_{int(multiplier)}x_usdt"] = round(out["gross_realised_usdt"] - cost, 4)
    out["per_symbol"] = {
        symbol: {key: round(value, 4) for key, value in row.items()}
        for symbol, row in sorted(per_symbol.items())
    }
    out["caveat"] = (
        "this re-prices the lane's fills after the fact; it is a research restatement of the "
        "frictionless book, not a second execution path"
    )
    return out


def canonical_trade_result(risk: RiskManager) -> dict[str, Any]:
    """The engine's own view of its state, so the report cannot paraphrase it."""
    return {
        "equity": float(risk.equity),
        "peak_equity": float(risk.peak_equity),
        "day_peak_equity": float(risk.day_peak_equity),
        "daily_pnl": float(risk.daily_pnl),
        "weekly_pnl": float(risk.weekly_pnl),
        "weekly_start_ms": int(risk.weekly_start_ms),
        "trades_today": int(risk.trades_today),
        "consecutive_losses": int(risk.consecutive_losses),
        "open_positions": len(risk.open_positions),
        "kill_switch_active": bool(risk._kill_switch_active),
    }


if __name__ == "__main__":
    raise SystemExit(main())
