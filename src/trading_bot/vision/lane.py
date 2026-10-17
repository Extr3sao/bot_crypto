"""lane — the vertical slice: pixels in, net PnL out.

The lane is a paper replay with one substitution: where the deterministic system asks
its incremental machine what to do, this lane shows a model a rendered chart and asks
it instead. Everything downstream is the runtime's own machinery:

    chart -> model -> VisionDecision -> Signal -> RiskManager.check_signal
          -> PaperBroker.execute_signal -> ClosedTrade.pnl (net) -> record_trade_result

Timing is the same discipline the deterministic lane uses, and it matters:

* the decision is taken on the **close** of bar *i*, using bars ``[: i + 1]`` only;
* it becomes executable at the **open** of bar *i + 1*, so no fill can use a price the
  model had not seen;
* protective exits are checked before new entries on every bar, with the broker's
  conservative both-hit policy (``stop_first``).

Risk is not re-implemented here. ``RiskManager.check_signal`` is the only gate, sizing
comes from its ``PositionSize``, and the stops are the policy's defaults — the model's
own stop is recorded as advice, never substituted into the book, because letting the
prompt choose the stop distance would let the prompt change the risk per trade and the
comparison with the deterministic lane would be between two policies, not two decisions.

One subtraction from parity, declared: a CLOSE is not passed through ``check_signal``.
A trade-count or cooldown gate that blocks an exit is a bug, not a policy, and the
deterministic lane closes through the broker's protective exits for the same reason.
Every bypassed close is recorded with ``risk_gate="BYPASSED_FOR_REDUCTION"``.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from itertools import pairwise
from pathlib import Path
from typing import Any

from trading_bot.config.risk import Risk
from trading_bot.paper.broker import BrokerCost, PaperBroker
from trading_bot.research.economic_recovery.alpha15 import cost_for
from trading_bot.research.equity_drawdown import max_drawdown
from trading_bot.risk.manager import RiskManager
from trading_bot.strategies.types import Side, Signal
from trading_bot.vision.chart import ChartImage, render_chart_png, window_fingerprint
from trading_bot.vision.contract import (
    DecisionParseError,
    VisionDecision,
    parse_decision,
    resolve_intent,
)
from trading_bot.vision.guards import (
    OpinionRejected,
    assert_asset,
    assert_causal,
    assert_fresh,
    assert_level_inside_market,
    assert_tradeable_window,
    check_costs,
)
from trading_bot.vision.ledger import DecisionLedger
from trading_bot.vision.prompt import PromptBundle, build_prompt
from trading_bot.vision.provider import (
    ProviderError,
    VisionProvider,
    VisionRequest,
    VisionResponse,
)
from trading_bot.vision.settings import VisionConfig

#: Kept identical to the deterministic lane so the comparison is about decisions.
PORTFOLIO_EQUITY_USDT = 10_000.0
BOOK_ID = "ai-vision-paper"
MAX_RAW_ANSWER_CHARS = 4_000


def _utc_iso(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000.0, tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _day_of(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000.0, tz=UTC).strftime("%Y-%m-%d")


def _atr_pct(bars: Sequence[Any], window: int = 14) -> float | None:
    """ATR as a percentage of the last close, for context only (not a signal)."""
    rows = list(bars)[-(window + 1) :]
    if len(rows) < 3:
        return None
    ranges: list[float] = []
    for previous, current in pairwise(rows):
        high = float(current.high)
        low = float(current.low)
        prev_close = float(previous.close)
        ranges.append(max(high - low, abs(high - prev_close), abs(low - prev_close)))
    if not ranges:
        return None
    last_close = float(rows[-1].close)
    if last_close <= 0:
        return None
    return sum(ranges) / len(ranges) / last_close * 100.0


@dataclass(frozen=True, slots=True)
class PendingOrder:
    bar_index: int
    intent: str
    decision: VisionDecision | None
    decision_seq: int
    #: The bar the opinion was formed on, and the step between bars. They are kept so
    #: execution can refuse a bar that is not the *immediately following* one: after a
    #: data hole the next available bar may be hours later, and executing there would
    #: fill at a price the opinion never described.
    decision_ts_ms: int = 0
    expected_step_ms: int = 0


class VisionLane:
    """One paper book, one risk engine, one model."""

    def __init__(
        self,
        *,
        series: dict[str, list[Any]],
        provider: VisionProvider,
        config: VisionConfig,
        risk_policy: Risk,
        ledger_path: Path | str,
        equity: float = PORTFOLIO_EQUITY_USDT,
        book_id: str = BOOK_ID,
        decision_every_bars: int | None = None,
        max_calls: int | None = None,
        max_spend_usd: float | None = None,
        cost_multiplier: float = 1.0,
        prompt_builder: Callable[[dict[str, Any], Sequence[Any]], PromptBundle] | None = None,
    ) -> None:
        if not series:
            raise ValueError("series is empty")
        self.series = {symbol: list(bars) for symbol, bars in series.items()}
        self.provider = provider
        self.config = config
        self.equity = float(equity)
        self.book_id = book_id
        self.decision_every = int(
            decision_every_bars or config.lane.decision_every_bars
        )
        self.max_calls = int(max_calls or config.lane.max_calls_per_run)
        self.max_spend_usd = float(
            config.lane.max_estimated_spend_usd if max_spend_usd is None else max_spend_usd
        )
        self.cost_multiplier = float(cost_multiplier)
        self.ledger = DecisionLedger(ledger_path)
        self.window_bars = int(config.lane.window_bars)
        self.timeframe = config.lane.timeframe
        self.risk_policy = risk_policy
        #: Which prompt a bot is asked with. BOT-VIS-01 draws a chart and uses the visual
        #: prompt; BOT-CTX-01 sends numbers and must not be told an image exists, so the
        #: prompt is a property of the bot rather than of the book.
        self._prompt_builder = prompt_builder or (
            lambda context, _bars: build_prompt(context)
        )

        self._current_ms = [min(bars[0].ts_ms for bars in self.series.values())]

        def cost_schedule(symbol: str, notional: float) -> BrokerCost:
            terms = cost_for(symbol, stake_usdt=max(notional, 1.0))
            return BrokerCost(
                commission_bps=terms.fee_bps_per_side * self.cost_multiplier,
                half_spread_bps=terms.half_spread_bps * self.cost_multiplier,
                slippage_bps=(terms.slippage_bps_per_side + terms.impact_bps_per_side)
                * self.cost_multiplier,
            )

        self.broker = PaperBroker(
            equity=self.equity,
            slippage_bps=0.0,
            commission_bps=0.0,
            book_id=book_id,
            clock=lambda: self._current_ms[0] / 1000.0,
            cost_schedule=cost_schedule,
        )
        self.risk = RiskManager(
            risk=risk_policy,
            equity=self.equity,
            _clock=lambda: self._current_ms[0] / 1000.0,
        )
        self._pending: dict[str, PendingOrder] = {}
        #: Median distance between consecutive bars, per symbol. Used to tell "the next
        #: bar" from "some later bar after a hole in the data".
        self._step_ms: dict[str, int] = {
            symbol: _median_step(bars) for symbol, bars in self.series.items()
        }
        self._marks: dict[str, float] = {}
        self.equity_curve: list[dict[str, Any]] = []
        self.calls_made = 0
        self.spend_usd = 0.0
        self.stop_reason: str | None = None
        self.counters: dict[str, int] = {}

    # -- helpers -------------------------------------------------------------

    def _bump(self, key: str) -> None:
        self.counters[key] = self.counters.get(key, 0) + 1

    def _position_side(self, symbol: str) -> str | None:
        position = self.broker.positions.get(symbol)
        return None if position is None else str(position.side)

    def _record_close(self, trade: Any, ts_ms: int, bars_held: int | None = None) -> None:
        self.risk.record_trade_result(float(trade.pnl))
        self.risk.sync_open_positions(dict(self.broker.positions))
        self.ledger.append(
            "CLOSE",
            {
                "ts_ms": ts_ms,
                "ts_utc": _utc_iso(ts_ms),
                "symbol": trade.symbol,
                "side": trade.side,
                "exit_reason": trade.exit_reason,
                "pnl_net_usdt": round(float(trade.pnl), 8),
                # Both gross terms are recorded because only one of them closes the
                # accounting identity: ``pnl = reference_gross - execution_cost -
                # commissions``. ``gross`` is the move at the prices actually paid, so it
                # already contains the execution cost and must not be subtracted again.
                "gross_pnl_usdt": round(float(trade.gross_pnl), 8),
                "reference_gross_pnl_usdt": round(float(trade.reference_gross_pnl), 8),
                "execution_cost_usdt": round(float(trade.execution_cost_usdt), 8),
                "entry_commission_usdt": round(float(trade.entry_commission), 8),
                "exit_commission_usdt": round(float(trade.exit_commission), 8),
                "commissions_usdt": round(
                    float(trade.entry_commission) + float(trade.exit_commission), 8
                ),
                "quantity": float(trade.quantity),
                "entry_price": float(trade.entry_price),
                "exit_price": float(trade.exit_price),
                "trade_id": trade.trade_id,
                "position_id": trade.position_id,
                "bars_held": bars_held,
                "risk_equity_after": round(float(self.risk.equity), 8),
            },
        )
        self._bump("closed_trades")

    # -- context for the prompt ---------------------------------------------

    def _context(self, symbol: str, bar: Any, bars_seen: Sequence[Any]) -> dict[str, Any]:
        closes = [float(b.close) for b in bars_seen]
        ret20 = None
        if len(closes) > 20 and closes[-21] > 0:
            ret20 = (closes[-1] / closes[-21] - 1.0) * 100.0
        position = self.broker.positions.get(symbol)
        position_ctx = None
        if position is not None:
            price = float(bar.close)
            unrealised = float(position.unrealized_pnl(price))
            notional = float(position.notional_usdt) or 1.0
            position_ctx = {
                "side": position.side,
                "entry_price": float(position.entry_price),
                "unrealised_usdt": round(unrealised, 6),
                "unrealised_pct": round(unrealised / notional * 100.0, 4),
            }
        recent = [
            {"symbol": trade.symbol, "side": trade.side, "pnl_usdt": round(float(trade.pnl), 6)}
            for trade in self.broker.closed_trades[-3:]
        ]
        return {
            "symbol": symbol,
            "timeframe": self.timeframe,
            "window_bars": min(len(bars_seen), self.window_bars),
            "last_close": float(bar.close),
            "atr_pct": _atr_pct(bars_seen),
            "return_20_bars_pct": ret20,
            "position": position_ctx,
            "equity": float(self.risk.equity),
            "open_positions": len(self.broker.positions),
            "max_open_positions": int(self.risk_policy.max_open_positions),
            "risk_per_trade_pct": float(self.risk_policy.max_risk_per_trade_pct),
            "max_weekly_loss_pct": float(self.risk_policy.max_weekly_loss_pct),
            "recent_closed": recent,
        }

    # -- one decision --------------------------------------------------------

    def _decide(self, symbol: str, bar: Any, bars_seen: Sequence[Any]) -> PendingOrder | None:
        if self.calls_made >= self.max_calls:
            self.stop_reason = "MAX_CALLS_REACHED"
            return None
        if self.spend_usd >= self.max_spend_usd:
            self.stop_reason = "SPEND_BUDGET_REACHED"
            return None

        chart: ChartImage = render_chart_png(
            bars_seen, symbol=symbol, timeframe=self.timeframe, window_bars=self.window_bars
        )
        context = self._context(symbol, bar, bars_seen)
        prompt = self._prompt_builder(context, bars_seen)
        request = VisionRequest(
            chart=chart,
            prompt=prompt,
            decision_ts_ms=int(bar.ts_ms),
            detail=self.config.provider.detail,
        )

        # The guards run *before* the paid call: a chart that is stale, about another
        # asset or built from a bar that had not closed cannot produce a tradeable
        # opinion, so paying for the answer would be paying for nothing.
        try:
            assert_causal(bars_seen, int(bar.ts_ms))
            assert_fresh(chart.last_ts_ms, int(bar.ts_ms))
            assert_asset(chart.symbol, symbol)
        except OpinionRejected as exc:
            self.ledger.append(
                "GUARD_REJECT",
                {
                    "ts_ms": int(bar.ts_ms),
                    "ts_utc": _utc_iso(int(bar.ts_ms)),
                    "symbol": symbol,
                    "code": exc.code,
                    "detail": exc.detail,
                    "chart": chart.fingerprint(),
                    "stage": "PRE_CALL",
                },
            )
            self._bump(f"guard:{exc.code}")
            return None

        base = {
            "ts_ms": int(bar.ts_ms),
            "ts_utc": _utc_iso(int(bar.ts_ms)),
            "symbol": symbol,
            "chart": chart.fingerprint(),
            "window_fingerprint": window_fingerprint(bars_seen, window_bars=self.window_bars),
            "prompt": {"version": prompt.version, "sha256": prompt.sha256, "context": context},
        }

        try:
            response: VisionResponse = self.provider.analyze(request)
        except ProviderError as exc:
            self.ledger.append(
                "PROVIDER_FAILURE",
                {
                    **base,
                    "code": exc.code,
                    "detail": exc.detail[:500],
                    "attempts": exc.attempts,
                    "decision": None,
                },
            )
            self._bump(f"provider_failure:{exc.code}")
            return None

        self.calls_made += 1
        if response.cost_usd:
            self.spend_usd += float(response.cost_usd)

        if response.image_sha256_in_request and response.image_sha256_in_request != chart.sha256:
            self.ledger.append(
                "INTEGRITY_FAILURE",
                {
                    **base,
                    "expected_image_sha256": chart.sha256,
                    "request_image_sha256": response.image_sha256_in_request,
                },
            )
            self._bump("integrity_failure")

        entry: dict[str, Any] = {
            **base,
            "provider": response.to_row(),
            "raw_answer": response.text[:MAX_RAW_ANSWER_CHARS],
            "raw_answer_truncated": len(response.text) > MAX_RAW_ANSWER_CHARS,
        }

        try:
            decision = parse_decision(response.text, symbol=symbol)
        except DecisionParseError as exc:
            self.ledger.append(
                "DECISION",
                {
                    **entry,
                    "decision": None,
                    "parse_error": exc.code,
                    "parse_detail": exc.detail[:400],
                    "coherence_reason": None,
                    "risk_blocked_by": None,
                },
            )
            self._bump(f"parse_error:{exc.code}")
            return None

        try:
            assert_level_inside_market(decision.invalidation_price, bars_seen)
        except OpinionRejected as exc:
            self.ledger.append(
                "GUARD_REJECT",
                {
                    **base,
                    "code": exc.code,
                    "detail": exc.detail,
                    "provider": response.to_row(),
                    "stage": "POST_PARSE",
                    "decision": decision.model_dump(mode="json"),
                },
            )
            self._bump(f"guard:{exc.code}")
            return None

        resolved = resolve_intent(decision, position_side=self._position_side(symbol))
        line = self.ledger.append(
            "DECISION",
            {
                **entry,
                "decision": decision.model_dump(mode="json"),
                "intent": resolved.intent,
                "coherence_reason": resolved.reason,
                "risk_blocked_by": None,
                "parse_error": None,
            },
        )
        self._bump(f"action:{decision.action}")
        if not resolved.actionable:
            self._bump(f"dropped:{resolved.reason}")
            return None
        return PendingOrder(
            bar_index=0,  # filled by the caller with the bar index
            intent=resolved.intent,
            decision=decision,
            decision_seq=line.seq,
        )

    # -- execution -----------------------------------------------------------

    def _execute(self, symbol: str, bar: Any, pending: PendingOrder, bar_index: int) -> None:
        price = float(bar.open)
        if price <= 0:
            return
        decision = pending.decision
        assert decision is not None

        if (
            pending.expected_step_ms
            and int(bar.ts_ms) - pending.decision_ts_ms != pending.expected_step_ms
        ):
            # A hole in the data means this bar is not the one the opinion was formed for:
            # the next available bar may be hours later, and filling there would trade at a
            # price the model never described.
            self.ledger.append(
                "GUARD_REJECT",
                {
                    "ts_ms": int(bar.ts_ms),
                    "ts_utc": _utc_iso(int(bar.ts_ms)),
                    "symbol": symbol,
                    "code": "STALE_EXECUTION",
                    "detail": (
                        f"the opinion was formed at {pending.decision_ts_ms} and the next "
                        f"available bar is {int(bar.ts_ms)} "
                        f"({int(bar.ts_ms) - pending.decision_ts_ms} ms later, expected "
                        f"{pending.expected_step_ms}); dropping it instead of filling late"
                    ),
                    "stage": "EXECUTION",
                },
            )
            self._bump("guard:STALE_EXECUTION")
            return

        if pending.intent == "CLOSE":
            position = self.broker.positions.get(symbol)
            if position is None:
                return
            closing_side: Side = "sell" if str(position.side) == "buy" else "buy"
            close_signal = Signal(
                symbol=symbol,
                side=closing_side,
                strategy_name="ai_vision",
                timeframe=self.timeframe,
                confidence=float(decision.confidence),
                price=price,
                metadata={
                    "notional_usdt": float(position.notional_usdt),
                    "decision_seq": pending.decision_seq,
                },
            )
            opened = float(position.opened_at)
            bars_held = round((float(bar.ts_ms) / 1000.0 - opened) / 3600.0)
            result = self.broker.execute_signal(close_signal)
            if result is not None and hasattr(result, "pnl"):
                self._record_close(result, int(bar.ts_ms), bars_held=bars_held)
            self.ledger.append(
                "DECISION_OUTCOME",
                {
                    "ts_ms": int(bar.ts_ms),
                    "symbol": symbol,
                    "decision_seq": pending.decision_seq,
                    "intent": "CLOSE",
                    "risk_gate": "BYPASSED_FOR_REDUCTION",
                    "executed": result is not None,
                },
            )
            return

        side: Side = "buy" if pending.intent == "OPEN_LONG" else "sell"
        signal = Signal(
            symbol=symbol,
            side=side,
            strategy_name="ai_vision",
            timeframe=self.timeframe,
            confidence=float(decision.confidence),
            price=price,
            metadata={"decision_seq": pending.decision_seq},
        )
        check = self.risk.check_signal(signal)
        self.ledger.append(
            "DECISION_OUTCOME",
            {
                "ts_ms": int(bar.ts_ms),
                "symbol": symbol,
                "decision_seq": pending.decision_seq,
                "intent": pending.intent,
                "risk_gate": "check_signal",
                "approved": bool(check.approved),
                "risk_blocked_by": check.blocked_by,
                "risk_reason": check.reason,
                "notional_usdt": (
                    float(check.position_size.notional_usdt) if check.position_size else None
                ),
                "policy_stop_loss_pct": (
                    float(check.position_size.stop_loss_pct) if check.position_size else None
                ),
                "model_stop_loss_pct": decision.stop_loss_pct,
                "model_stop_inside_policy": (
                    decision.stop_loss_pct is not None
                    and check.position_size is not None
                    and float(decision.stop_loss_pct) <= float(check.position_size.stop_loss_pct)
                ),
            },
        )
        if not check.approved or check.position_size is None:
            self._bump(f"risk_blocked:{check.blocked_by or 'unknown'}")
            return
        notional = float(check.position_size.notional_usdt)
        try:
            assert_tradeable_window(
                int(bar.ts_ms), weekend_trading=bool(self.risk_policy.blocks.weekend_trading)
            )
            check_costs(
                self.broker.cost_for(symbol, notional),
                declared_frictionless=self.cost_multiplier == 0.0,
            )
        except OpinionRejected as exc:
            self.ledger.append(
                "DECISION_OUTCOME",
                {
                    "ts_ms": int(bar.ts_ms),
                    "symbol": symbol,
                    "decision_seq": pending.decision_seq,
                    "intent": pending.intent,
                    "risk_gate": exc.code,
                    "approved": True,
                    "executed": False,
                    "risk_blocked_by": exc.code,
                    "risk_reason": exc.detail,
                    "notional_usdt": notional,
                },
            )
            self._bump(f"gate:{exc.code}")
            return
        if symbol in self.broker.positions:
            self._bump("dropped:SYMBOL_SLOT_OCCUPIED")
            return

        sized = check.position_size
        order = Signal(
            symbol=symbol,
            side=side,
            strategy_name="ai_vision",
            timeframe=self.timeframe,
            confidence=float(decision.confidence),
            price=price,
            stop_loss_pct=sized.stop_loss_pct,
            take_profit_pct=sized.take_profit_pct,
            metadata={
                "notional_usdt": sized.notional_usdt,
                "decision_seq": pending.decision_seq,
                "risk_rule": "RiskManager.check_signal",
            },
        )
        filled = self.broker.execute_signal(order)
        if filled is None:
            self._bump("broker_rejected")
            return
        self.risk.sync_open_positions(dict(self.broker.positions))
        self.ledger.append(
            "FILL",
            {
                "ts_ms": int(bar.ts_ms),
                "ts_utc": _utc_iso(int(bar.ts_ms)),
                "symbol": symbol,
                "side": side,
                "intent": pending.intent,
                "decision_seq": pending.decision_seq,
                "decision_bar_index": bar_index - 1,
                "fill_bar_index": bar_index,
                "position_id": getattr(filled, "position_id", ""),
                "entry_price": float(getattr(filled, "entry_price", price)),
                "reference_price": price,
                "quantity": float(getattr(filled, "quantity", 0.0)),
                "notional_usdt": float(sized.notional_usdt),
                "stop_loss_pct": float(sized.stop_loss_pct),
                "take_profit_pct": float(sized.take_profit_pct),
            },
        )
        self._bump("fills")

    # -- the run -------------------------------------------------------------

    def run(self) -> dict[str, Any]:
        index_of = {
            symbol: {int(bar.ts_ms): i for i, bar in enumerate(bars)}
            for symbol, bars in self.series.items()
        }
        timeline = sorted({ts for bars in self.series.values() for ts in index_of_ts(bars)})

        self.ledger.open()
        try:
            self.ledger.append(
                "RUN",
                {
                    "book_id": self.book_id,
                    "provider": self.config.as_public_dict(),
                    "equity_usdt": self.equity,
                    "cost_multiplier": self.cost_multiplier,
                    "risk_policy": {
                        "max_risk_per_trade_pct": float(self.risk_policy.max_risk_per_trade_pct),
                        "max_daily_loss_pct": float(self.risk_policy.max_daily_loss_pct),
                        "max_weekly_loss_pct": float(self.risk_policy.max_weekly_loss_pct),
                        "max_total_drawdown_pct": float(self.risk_policy.max_total_drawdown_pct),
                        "max_open_positions": int(self.risk_policy.max_open_positions),
                        "default_stop_loss_pct": float(self.risk_policy.default_stop_loss_pct),
                        "default_take_profit_pct": float(self.risk_policy.default_take_profit_pct),
                    },
                    "lane": {
                        "decision_every_bars": self.decision_every,
                        "window_bars": self.window_bars,
                        "timeframe": self.timeframe,
                        "max_calls": self.max_calls,
                        "max_spend_usd": self.max_spend_usd,
                    },
                    "dataset": {
                        symbol: {
                            "bars": len(bars),
                            "first_open_utc": _utc_iso(int(bars[0].ts_ms)),
                            "last_open_utc": _utc_iso(int(bars[-1].ts_ms)),
                            "sha256": series_digest(bars),
                        }
                        for symbol, bars in self.series.items()
                    },
                },
            )

            previous_day: str | None = None
            for ts in timeline:
                self._current_ms[0] = ts
                day = _day_of(ts)
                if previous_day is not None and day != previous_day:
                    self.risk.reset_daily()
                previous_day = day

                for symbol, bars in self.series.items():
                    index = index_of[symbol].get(ts)
                    if index is None:
                        continue
                    bar = bars[index]
                    self._marks[symbol] = float(bar.close)

                    closed = self.broker.check_positions_ohlc(
                        {symbol: (float(bar.open), float(bar.high), float(bar.low), float(bar.close))}
                    )
                    for trade in closed:
                        opened_ms = int(float(trade.opened_at) * 1000)
                        held = max(0, round((ts - opened_ms) / 3_600_000))
                        self._record_close(trade, ts, bars_held=held)

                    pending = self._pending.pop(symbol, None)
                    if pending is not None and pending.bar_index == index:
                        self._execute(symbol, bar, pending, index)

                    if decision_due(
                        index,
                        window_bars=self.window_bars,
                        every=self.decision_every,
                        stop_reason=self.stop_reason,
                    ):
                            bars_seen = bars[: index + 1]
                            decision = self._decide(symbol, bar, bars_seen)
                            if decision is not None:
                                self._pending[symbol] = PendingOrder(
                                    bar_index=index + 1,
                                    intent=decision.intent,
                                    decision=decision.decision,
                                    decision_seq=decision.decision_seq,
                                    decision_ts_ms=int(bar.ts_ms),
                                    expected_step_ms=int(self._step_ms[symbol]),
                                )

                self.equity_curve.append(
                    {
                        "ts_ms": ts,
                        "ts_utc": _utc_iso(ts),
                        "equity": round(
                            float(self.broker.mark_to_market_equity(dict(self._marks))), 8
                        ),
                        "risk_equity": round(float(self.risk.equity), 8),
                    }
                )

            summary = self._summary()
            self.ledger.append("RUN_END", summary)
            return summary
        finally:
            self.ledger.close()

    def _summary(self) -> dict[str, Any]:
        trades = list(self.broker.closed_trades)
        net = sum(float(trade.pnl) for trade in trades)
        drawdown = max_drawdown(
            (int(point["ts_ms"]), float(point["equity"])) for point in self.equity_curve
        )
        return {
            "book_id": self.book_id,
            "provider": getattr(self.provider, "name", "unknown"),
            "decision_points": sum(
                1 for key, value in self.counters.items() if key.startswith("action:")
            ),
            "calls": self.calls_made,
            "estimated_spend_usd": round(self.spend_usd, 6),
            "stop_reason": self.stop_reason,
            # ``fills`` counts openings, not closed trades: a fill that is still open at
            # the end of the run is a fill, and reporting only closes would hide it.
            "fills": int(self.counters.get("fills", 0)),
            "closed_trades": len(trades),
            "net_realised_usdt": round(net, 6),
            "gross_realised_usdt": round(sum(float(t.gross_pnl) for t in trades), 6),
            "costs_usdt": round(sum(float(t.total_cost_usdt) for t in trades), 6),
            "final_equity_usdt": round(float(self.broker.equity), 6),
            "risk_equity_usdt": round(float(self.risk.equity), 6),
            "drawdown_pct": (
                None
                if not drawdown.measured
                else round(float(drawdown.drawdown_pct or 0.0), 6)
            ),
            "drawdown_status": drawdown.status,
            "drawdown_usdt": (
                None
                if not drawdown.measured
                else round(float(drawdown.drawdown_usdt or 0.0), 6)
            ),
            "equity_points": len(self.equity_curve),
            "counters": dict(sorted(self.counters.items())),
            "open_positions_at_end": {
                symbol: {
                    "side": position.side,
                    "entry_price": float(position.entry_price),
                    "notional_usdt": float(position.notional_usdt),
                }
                for symbol, position in self.broker.positions.items()
            },
            "trades": [
                {
                    "symbol": trade.symbol,
                    "side": trade.side,
                    "entry_price": float(trade.entry_price),
                    "exit_price": float(trade.exit_price),
                    "pnl_net_usdt": round(float(trade.pnl), 8),
                    "exit_reason": trade.exit_reason,
                    "opened_at_utc": _utc_iso(int(float(trade.opened_at) * 1000)),
                    "closed_at_utc": _utc_iso(int(float(trade.closed_at) * 1000)),
                }
                for trade in trades
            ],
        }


def _median_step(bars: Sequence[Any]) -> int:
    """Median gap between consecutive bars, or 0 when it cannot be measured."""
    stamps = sorted(int(bar.ts_ms) for bar in bars)
    gaps = [b - a for a, b in pairwise(stamps) if b > a]
    if not gaps:
        return 0
    gaps.sort()
    return gaps[len(gaps) // 2]


def decision_due(
    index: int, *, window_bars: int, every: int, stop_reason: str | None
) -> bool:
    """Is a decision taken on this bar?

    Needs a full window behind it, lands on the declared cadence, and stops as soon as
    the budget has stopped the run — a bar evaluated after the budget is a call the
    experiment did not pay for.
    """
    return index >= window_bars - 1 and index % every == 0 and stop_reason is None


def index_of_ts(bars: Sequence[Any]) -> list[int]:
    return [int(bar.ts_ms) for bar in bars]


def series_digest(bars: Sequence[Any]) -> str:
    payload = json.dumps(
        [
            [
                int(bar.ts_ms),
                round(float(bar.open), 8),
                round(float(bar.high), 8),
                round(float(bar.low), 8),
                round(float(bar.close), 8),
                round(float(bar.volume), 8),
            ]
            for bar in bars
        ],
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode()).hexdigest()
