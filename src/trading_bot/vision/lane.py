"""lane — the vertical slice: pixels in, net PnL out.

The lane is a paper replay with one substitution: where the deterministic system asks
its incremental machine what to do, this lane shows a model a rendered chart and asks
it instead. Everything downstream is the runtime's own machinery:

    chart -> model -> VisionDecision -> Signal -> RiskManager.check_signal
          -> PaperBroker.execute_signal -> ClosedTrade.pnl (net) -> record_trade_result

Timing is the same discipline the deterministic lane uses, and it matters:

* the decision is taken on the **close** of bar *i*, using bars ``[: i + 1]`` only, and
  is stamped at ``open + timeframe + data_delay`` — the instant that close was knowable;
* it becomes executable at the **open** of bar *i + 1*, so no fill can use a price the
  model had not seen, and an answer whose latency carries it past that open is dropped;
* the risk engine is marked with the same net equity the curve publishes, every bar, so
  its drawdown and sizing gates see the book the report describes.
* protective exits are checked before new entries on every bar, with the broker's
  conservative both-hit policy (``stop_first``).

Risk is not re-implemented here. ``RiskManager.check_signal`` is the only gate and sizing
comes from its ``PositionSize``. The stop the model declares is the **thesis'
invalidation** and it is honoured exactly: DEF-RUN-014 closed the path where this lane
built a ``Signal`` without ``stop_loss_pct``, which made the manager apply the policy
default (0.5 %) while the model had asked for something else. The resolution is now
explicit and published on every row (``requested`` / ``effective`` / ``source`` /
``reason`` / ``risk_at_stop_usdt``), and a distance shorter than the round trip it has to
survive is refused as ``stop_inside_costs`` instead of being executed as if it were a
loss limit.

What keeps the comparison with the deterministic lane honest is not ignoring the model's
distance but *sizing* under the policy: the notional is still ``RiskManager``'s, so a
tighter stop buys a smaller position, not a bigger risk.

One subtraction from parity, declared: a CLOSE is not passed through ``check_signal``.
A trade-count or cooldown gate that blocks an exit is a bug, not a policy, and the
deterministic lane closes through the broker's protective exits for the same reason.
Every bypassed close is recorded with ``risk_gate="BYPASSED_FOR_REDUCTION"``.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from itertools import pairwise
from pathlib import Path
from typing import Any, cast

from trading_bot.config.risk import Risk
from trading_bot.paper.broker import BrokerCost, ClosedTrade, PaperBroker
from trading_bot.research.economic_recovery.alpha15 import cost_for
from trading_bot.research.equity_drawdown import max_drawdown
from trading_bot.risk.manager import RiskManager
from trading_bot.strategies.types import Side, Signal
from trading_bot.vision.chart import ChartImage, render_chart_png, window_fingerprint
from trading_bot.vision.clock import bar_close_ms, information_ms, timeframe_ms
from trading_bot.vision.contract import (
    DecisionParseError,
    VisionDecision,
    parse_decision,
    resolve_intent,
)
from trading_bot.vision.execution import (
    BAR_OPEN_SOURCE,
    Quote,
    QuoteFeed,
    SubBarQuoteFeed,
    quote_at,
    schedule,
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
from trading_bot.vision.ledger import DecisionLedger, read_entries
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

#: Version of the accounting contract this lane publishes. Bumped when a field's
#: *meaning* changes, not when one is added: 003H added the open-position terms and kept
#: every pre-existing key with its old meaning, so the contract is additive.
ACCOUNTING_SCHEMA_VERSION = "paper-accounting/2"

#: One definition per published cost/PnL term. A reader should not have to infer whether
#: ``costs_usdt`` includes a position that is still open; 003G-D5 was exactly that guess.
COST_MEANINGS: dict[str, str] = {
    "costs_usdt": (
        "realised cost of closed trades only: execution + entry + exit commissions. "
        "Unchanged since 003B; it does NOT include open positions."
    ),
    "costs_realised_usdt": "same value as costs_usdt, named for symmetry with costs_total_usdt",
    "entry_commissions_realised_usdt": "entry commissions inside closed trades",
    "exit_commissions_realised_usdt": "exit commissions inside closed trades",
    "execution_costs_realised_usdt": "spread/impact cost embedded in closed-trade fills",
    "entry_commissions_accrued_open_usdt": (
        "entry commissions of positions still open: charged at close by the broker, but "
        "already owed and already withheld from marked equity"
    ),
    "costs_total_usdt": "costs_usdt + entry_commissions_accrued_open_usdt",
    "pnl_realised_usdt": "net PnL of closed trades (same value as net_realised_usdt)",
    "pnl_unrealised_usdt": (
        "open positions marked at the last observable close, net of accrued entry "
        "commissions"
    ),
    "pnl_total_usdt": "pnl_realised_usdt + pnl_unrealised_usdt",
    "marked_equity_usdt": "initial equity + pnl_total_usdt",
}


def _utc_iso(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000.0, tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


#: DEF-RUN-016: the two scheduling rules a replay may declare. The default is the one
#: the runtime uses; the other exists so a report can show what the pipeline did before.
OPINION_LIFECYCLE_DEFER = "DEFER"
OPINION_LIFECYCLE_SUPERSEDE = "SUPERSEDE"
OPINION_LIFECYCLES = (OPINION_LIFECYCLE_DEFER, OPINION_LIFECYCLE_SUPERSEDE)

#: DEF-RUN-016: las cinco clases terminales son disjuntas — una opinión pertenece a
#: exactamente una — y suman las opiniones generadas. ``expired``,
#: ``superseded``, ``pending_at_end`` y ``deferred_slots`` son **vistas** de alguna de
#: ellas (o de un turno que no llegó a ser opinión), nunca sumandos extra.
OPINION_ACCOUNTING_SCHEMA = "DEF_RUN_016_OPINION_ACCOUNTING_V1"
OPINION_ACCOUNTING_IDENTITY = (
    "generated == FILLED + CLOSED + BLOCKED_BY_RISK + GATED + REJECTED"
)
TERMINAL_CLASSES = ("FILLED", "CLOSED", "BLOCKED_BY_RISK", "GATED", "REJECTED")
ACTIONABLE_INTENTS = ("OPEN_LONG", "OPEN_SHORT", "CLOSE")


class OpinionLifecycleError(RuntimeError):
    """El ledger no explica todas las opiniones que el carril generó.

    Deliberadamente no es un ``assert``: ``python -O`` elimina los ``assert`` y un resumen
    que no cuadra se publicaría igual. Lleva el código, la cuenta reconstruida desde los
    bytes y las opiniones afectadas, y se escribe en el ledger **antes** de propagarse, de
    modo que el fallo sea reproducible y auditable desde el propio artefacto.
    """

    def __init__(self, code: str, detail: str, **fields: Any) -> None:
        super().__init__(f"{code}: {detail}")
        self.code = code
        self.detail = detail
        self.fields = dict(fields)

    def to_row(self) -> dict[str, Any]:
        return {"code": self.code, "detail": self.detail, **self.fields}


def _terminal_event(entry: Mapping[str, Any]) -> tuple[str, str] | None:
    """Qué clase terminal declara esta fila, si declara alguna.

    La fila de aprobación del riesgo de una entrada rellenada **no** es un cierre: no
    lleva ``executed`` y el relleno que la sigue es el evento terminal. Tratar cada fila
    con ``decision_seq`` como un cierre contaría la misma opinión dos veces.
    """
    kind = entry.get("kind")
    if kind == "FILL":
        return ("FILLED", "FILL")
    if kind == "DECISION_OUTCOME":
        intent = str(entry.get("intent") or "")
        executed = entry.get("executed")
        if intent == "CLOSE":
            if executed is True:
                return ("CLOSED", "CLOSE_EXECUTED")
            if executed is False:
                return ("GATED", str(entry.get("risk_gate") or "CLOSE_NOT_EXECUTED"))
            return None
        if entry.get("approved") is False:
            return ("BLOCKED_BY_RISK", str(entry.get("risk_blocked_by") or "unknown"))
        if entry.get("approved") is True and executed is False:
            return ("GATED", str(entry.get("risk_gate") or "unknown"))
        return None
    if kind == "GUARD_REJECT" and entry.get("decision_seq") is not None:
        return ("REJECTED", str(entry.get("code") or "UNKNOWN"))
    return None


def _latencies(values: Sequence[int]) -> dict[str, Any]:
    """p50/p95/p99 of a millisecond series, plus the sample it was measured on.

    ``None`` for an empty series: a percentile of nothing is not zero, and a report that
    printed 0 would read as a measured instant.
    """
    if not values:
        return {"samples": 0, "p50": None, "p95": None, "p99": None, "max": None}
    ordered = sorted(int(value) for value in values)

    def at(quantile: float) -> int:
        #: Nearest-rank, so every percentile is an observed value and never an average of
        #: two observations that no order ever had.
        index = max(0, min(len(ordered) - 1, math.ceil(quantile * len(ordered)) - 1))
        return ordered[index]

    return {
        "samples": len(ordered),
        "p50": at(0.50),
        "p95": at(0.95),
        "p99": at(0.99),
        "max": ordered[-1],
    }


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
    #: The open of the bar the opinion was formed on. Kept separately from
    #: ``decision_ts_ms`` (its close) because execution must refuse a bar that is not the
    #: immediately following one, and that comparison is between two opens.
    decision_bar_open_ms: int = 0
    expected_step_ms: int = 0
    #: When the provider's answer actually reached us: the decision instant (the close of
    #: the bar the opinion was formed on) plus measured latency. The fill price must be a
    #: quote that existed at or after this instant. Zero means "not measured".
    received_at_ms: int = 0
    #: The index of the bar the opinion was formed on, so a fill can name the bar it
    #: actually read. ``bar_index`` is where it is *expected* to execute.
    decision_bar_index: int = 0


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
        quote_feed: QuoteFeed | None = None,
        subbar_entries: bool = False,
        decision_from_ms: int | None = None,
        opinion_lifecycle: str = OPINION_LIFECYCLE_DEFER,
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
        #: DEF-RUN-016. ``DEFER`` is the runtime contract: an opinion still inside its TTL
        #: keeps the quote it is about to pay. ``SUPERSEDE`` is the pre-fix scheduling rule,
        #: kept **only** so CURRENT and PROPOSED can be replayed over the same data with the
        #: same code; it is not a tuning knob and the default is not negotiable at runtime.
        lifecycle = str(opinion_lifecycle).upper()
        if lifecycle not in OPINION_LIFECYCLES:
            raise ValueError(
                f"unknown opinion_lifecycle {opinion_lifecycle!r}; "
                f"allowed: {list(OPINION_LIFECYCLES)}"
            )
        self.opinion_lifecycle = lifecycle
        self.max_calls = int(max_calls or config.lane.max_calls_per_run)
        self.max_spend_usd = float(
            config.lane.max_estimated_spend_usd if max_spend_usd is None else max_spend_usd
        )
        self.cost_multiplier = float(cost_multiplier)
        self.ledger = DecisionLedger(ledger_path)
        self.window_bars = int(config.lane.window_bars)
        self.timeframe = config.lane.timeframe
        #: Bar duration and feed delay: the two terms that turn a bar's open into the
        #: instant its close was knowable. Read once, recorded in the ledger.
        self.interval_ms = timeframe_ms(self.timeframe)
        self.data_delay_ms = int(config.lane.data_delay_ms)
        #: Opt-in lower bound for the *instant a decision is formed*. A live session
        #: carries a warm-up window it must never decide on: those bars closed before the
        #: session existed, so a decision stamped there would be a replay dressed as a
        #: live run. ``None`` keeps the historical behaviour (every bar from the window).
        self.decision_from_ms = (
            None if decision_from_ms is None else int(decision_from_ms)
        )
        #: How long an opinion stays tradable once formed. Zero in the config means "one
        #: bar", which is the finest window this bar grid can express: a sub-bar latency
        #: costs exactly one bar of delay, and a latency beyond it is a stale view.
        self.max_opinion_age_ms = int(config.lane.max_opinion_age_ms) or self.interval_ms
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
        def round_trip_bps(symbol: str, notional: float) -> float:
            """What one round trip costs at the size the decision will actually take.

            The same schedule the broker will charge, with the same declared multiplier, so
            the number the risk gate compares a stop against is the number the fills pay.
            """
            terms = cost_for(symbol, stake_usdt=max(notional, 1.0))
            return float(terms.round_trip_bps(self.cost_multiplier))

        self.risk = RiskManager(
            risk=risk_policy,
            equity=self.equity,
            _clock=lambda: self._current_ms[0] / 1000.0,
            #: DEF-RUN-014: a stop shorter than the round trip is not a loss limit. The lane
            #: asks the manager to refuse it (``NO_TRADE`` with both numbers in the reason)
            #: instead of executing a distance that cannot pay for its own friction.
            cost_bps_for=round_trip_bps,
            stop_cost_policy="REJECT",
        )
        self._pending: dict[str, PendingOrder] = {}
        #: How many decision slots each in-flight opinion has cost. Published so a reader
        #: can tell a pipeline that is one bar behind from one that is starved.
        self._deferrals: dict[int, int] = {}
        #: Filled by the run-end sweep before the summary is taken; zero is "no opinion
        #: was still waiting", which is a measurement, not a missing value.
        self._pending_at_end = 0
        #: Median distance between consecutive bars, per symbol. Used to tell "the next
        #: bar" from "some later bar after a hole in the data".
        self._step_ms: dict[str, int] = {
            symbol: _median_step(bars) for symbol, bars in self.series.items()
        }
        #: A hole in one symbol's grid is detected by asking whether the bar that *should*
        #: follow the decision exists. That question needs the timestamps, not the median.
        self._bar_ts_ms: dict[str, set[int]] = {
            symbol: {int(bar.ts_ms) for bar in bars} for symbol, bars in self.series.items()
        }
        for symbol, step in self._step_ms.items():
            if step and step != self.interval_ms:
                raise ValueError(
                    f"{symbol} is sampled every {step} ms but the lane declares "
                    f"{self.timeframe!r} ({self.interval_ms} ms): mixed timeframes need an "
                    "event queue this lane does not have, so they are refused rather than "
                    "silently aligned to one clock"
                )
        #: The only source allowed to turn a data hole into an executable interval. It is
        #: not built from the bars being replayed, so it can say something the replay
        #: cannot: that the venue was open and priced while the bar was missing.
        self.quote_feed = quote_feed
        #: Opt-in. A feed that can price inside a bar is used only when the caller says so:
        #: the published behaviour (one fill per bar open) stays the default, so a caller
        #: that passes a feed for coverage does not silently change its fill prices.
        self.subbar_entries = bool(subbar_entries)
        #: The coarse contract only proves coverage. The finer one, if the same object
        #: offers it, can say when inside the bar a price existed. Duck-typed rather than
        #: asserted, because a coverage-only feed is a valid, weaker object.
        self.subbar_feed: SubBarQuoteFeed | None = (
            cast("SubBarQuoteFeed", quote_feed)
            if quote_feed is not None
            and callable(getattr(quote_feed, "first_quote_at_or_after", None))
            and callable(getattr(quote_feed, "range_between", None))
            else None
        )
        #: Set when a fill happens inside a bar, consumed by that bar's CLOSE phase and
        #: cleared there: the range of the entry bar must start at the fill, never at the
        #: bar's open.
        self._entry_bar: dict[str, dict[str, Any]] = {}
        self._marks: dict[str, float] = {}
        #: Where each open position's entry came from, keyed by position id: the quote and
        #: the answer's arrival. A CLOSE row without it cannot show that its exit happened
        #: after the entry existed.
        self._entry_provenance: dict[str, dict[str, Any]] = {}
        self.equity_curve: list[dict[str, Any]] = []
        self.calls_made = 0
        self.spend_usd = 0.0
        self.stop_reason: str | None = None
        self.counters: dict[str, int] = {}

    # -- helpers -------------------------------------------------------------

    def _bump(self, key: str) -> None:
        self.counters[key] = self.counters.get(key, 0) + 1


    def _reject_pending(
        self,
        symbol: str,
        ts_ms: int,
        pending: PendingOrder,
        code: str,
        detail: str,
        *,
        extra: dict[str, Any] | None = None,
        phase: str = "OPEN_ENTRY",
    ) -> None:
        """Name why an approved opinion could not be executed, and close it out.

        ``decision_seq`` is carried on purpose: a rejection is the terminal row of that
        decision, and a verifier that only learned to join fills to outcomes would call
        this decision orphaned.
        """
        self.ledger.append(
            "GUARD_REJECT",
            {
                "ts_ms": int(ts_ms),
                "ts_utc": _utc_iso(int(ts_ms)),
                "symbol": symbol,
                "code": code,
                "detail": detail,
                "stage": "EXECUTION",
                "phase": phase,
                "decision_seq": pending.decision_seq,
                **(extra or {}),
            },
        )
        self._bump(f"guard:{code}")

    def _defer_decision(
        self,
        symbol: str,
        ts_ms: int,
        pending: PendingOrder,
        next_open: int,
        source: str = "grid",
    ) -> None:
        """Say out loud that this decision slot was spent before it was taken.

        DEF-RUN-016. The lane formed an opinion at every bar close and replaced the one
        still waiting for its first executable quote with
        ``SUPERSEDED_BY_NEWER_OPINION``. When the answer is late enough that the next open
        is already after it, that replacement is a phase-ordering mistake: the supersede
        row was written at ``close_ms`` — the instant of the bar open that would price the
        waiting order — and it was written *before* that open was ever read. The only
        executable opinion was destroyed by an opinion whose answer arrives *after* that
        same price and can therefore never use it.

        The rule is now stated as an invariant: **at the instant a quote is read, the
        freshest arrived opinion is the one that gets it**. An opinion formed now answers at
        ``close(k+1) + L`` while the waiting one is priced at the first open at or after
        ``close(k) + L``, which is always earlier than that. The waiting opinion is therefore
        never obsolete at the price it is about to pay, and the newer answer could only
        arrive after that price. The slot is deferred — not paid for, not counted as an
        opinion.

        Nothing is kept alive past its TTL to manufacture trades. The deferral only applies
        while the waiting opinion can still be priced inside ``max_opinion_age_ms``; once
        its first open is already older than the window (a model slower than its own bar),
        the order is obsolete and a newer view supersedes it exactly as before, so a slow
        provider cannot starve the decision slot. A waiting order whose path is broken by a
        hole still meets ``DATA_GAP`` at the next bar that exists.
        """
        self.ledger.append(
            "OPINION_DEFERRED",
            {
                "ts_ms": int(ts_ms),
                "ts_utc": _utc_iso(int(ts_ms)),
                "symbol": symbol,
                "phase": "DECISION",
                "reason": "OPINION_IN_FLIGHT",
                "decision_seq": pending.decision_seq,
                "intent": pending.intent,
                "decision_ts_ms": int(pending.decision_ts_ms),
                "received_at_ms": int(pending.received_at_ms),
                "next_executable_open_ms": next_open,
                "next_executable_open_utc": _utc_iso(int(next_open)),
                #: ``grid`` siempre: la apertura se proyecta con el reloj declarado, no se
                #: lee de un futuro que el ciclo aún no tiene. Si el dataset tiene un hueco,
                #: la ejecución lo rechaza al leer el precio.
                "next_executable_open_source": source,
                "pending_deferrals": 1
                + int(self._deferrals.get(pending.decision_seq, 0)),
                "detail": (
                    "the opinion in flight has not been offered a quote at or after its "
                    "answer yet; a new answer could only compete for the same quote and "
                    "would arrive after it, so the paid call is not made"
                ),
            },
        )
        self._deferrals[pending.decision_seq] = 1 + int(
            self._deferrals.get(pending.decision_seq, 0)
        )
        self._bump("opinion:deferred")

    def _data_gap(
        self, symbol: str, pending: PendingOrder, at_ms: int
    ) -> dict[str, Any] | None:
        """Is a bar that should exist between the opinion and this quote missing?

        ``None`` means the grid is intact. Otherwise the record says which bar is absent,
        how many in a row, and whether an independent feed proved the venue stayed open
        and priced through the hole. A hole is only executable with that proof: the next
        quote is later than the hole, which is not the same as continuous.
        """
        stamps = self._bar_ts_ms.get(symbol, set())
        #: DEF-RUN-016: la orden puede esperar más de una barra (una opinión aplazada cruza
        #: al menos una). Antes solo se miraba la barra inmediatamente posterior, así que un
        #: hueco en medio de un camino más largo pasaba desapercibido. Ahora se recorre el
        #: tramo completo desde la barra de decisión hasta la cotización.
        probe = int(pending.decision_bar_open_ms) + self.interval_ms
        absent: list[int] = []
        while probe < int(at_ms):
            if probe not in stamps:
                absent.append(probe)
            probe += self.interval_ms
        if not absent:
            return None
        missing = absent[0]
        run = len(absent)
        record: dict[str, Any] = {
            "covered": False,
            "missing_bar_open_ms": missing,
            "missing_bars": run,
            "source": None,
            "reason": "no independent quote feed was supplied",
        }
        if run > 1:
            record["reason"] = f"{run} consecutive bars are missing, not a one-bar hole"
            return record
        if self.quote_feed is None:
            return record
        proof = self.quote_feed.prove_coverage(symbol, missing, self.interval_ms)
        if proof is None:
            record["reason"] = (
                f"{getattr(self.quote_feed, 'name', 'the feed')} returned no coverage proof"
            )
            return record
        covered, reason = proof.covers(self.interval_ms)
        record["covered"] = bool(covered)
        record["source"] = proof.source if covered else None
        record["reason"] = reason
        return record

    def _position_side(self, symbol: str) -> str | None:
        position = self.broker.positions.get(symbol)
        return None if position is None else str(position.side)

    def _record_close(
        self,
        trade: Any,
        *,
        exit_ts_ms: int,
        window_start_ms: int,
        bars_held: int | None = None,
        resolution: str = "BAR_WINDOW",
        gap_price_source: str | None = None,
        gap_open_price: float | None = None,
        phase: str = "INTRABAR",
    ) -> None:
        """Record one exit and hand its net PnL to the risk engine.

        ``resolution`` is the point of the row: ``OPEN_GAP`` means the instant is known
        exactly (the bar's open crossed the stop), ``BAR_WINDOW`` means only a range is
        knowable from OHLC, and ``QUOTE`` means a market order at a named quote. Inventing
        a precise tick for an intrabar touch is what the window is here to prevent.
        """
        equity_before = float(self.risk.equity)
        self.risk.record_trade_result(float(trade.pnl))
        self.risk.sync_open_positions(dict(self.broker.positions))
        #: Kept after the close, not popped: the reconciliation at the end of the run
        #: checks every close against the quote that opened it, and a discarded record
        #: would make that check pass by having nothing to compare.
        entry = self._entry_provenance.get(str(trade.position_id), {})
        self.ledger.append(
            "CLOSE",
            {
                "ts_ms": exit_ts_ms,
                "ts_utc": _utc_iso(exit_ts_ms),
                #: Which phase of the timestamp produced this row. Within one instant the
                #: order is the whole point, so it is written down rather than inferred.
                "phase": phase,
                # The stop is checked on the bar's range, which is only a fact when the
                # bar ends. The exit happened somewhere inside it, so the row declares
                # the window rather than inventing an intrabar instant. A stop crossed by
                # the OPEN is the exception: that instant is exactly known.
                "exit_ts_lower_bound_ms": window_start_ms,
                "exit_ts_upper_bound_ms": exit_ts_ms,
                "exit_ts_resolution": resolution,
                "gap_price_source": gap_price_source,
                "gap_open_price": gap_open_price,
                "exit_reference_price": round(float(trade.reference_exit_price), 8),
                #: The UTC day whose risk window this loss lands in: the day the *bar*
                #: opened, because that is the boundary ``reset_daily`` was called on.
                #: Using the exit instant instead would mis-file a bar that ends after
                #: midnight.
                "day_utc": _day_of(window_start_ms),
                "entry_quote_ts_ms": entry.get("quote_ts_ms"),
                "entry_decision_ts_ms": entry.get("decision_ts_ms"),
                "entry_received_at_ms": entry.get("received_at_ms"),
                "stop_loss_price": entry.get("stop_loss_price"),
                "take_profit_price": entry.get("take_profit_price"),
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
                #: The hand-off to the risk engine, as two numbers rather than a claim:
                #: the equity it held before the trade and the calendar windows the loss
                #: landed in. A verifier can rebuild all three from the rows alone.
                "risk_equity_before": round(equity_before, 8),
                "risk_equity_after": round(float(self.risk.equity), 8),
                "risk_daily_pnl_after": round(float(self.risk.daily_pnl), 8),
                "risk_weekly_pnl_after": round(float(self.risk.weekly_pnl), 8),
            },
        )
        self._bump("closed_trades")
        if resolution == "OPEN_GAP":
            self._bump("gap_exits")

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

        #: The close of the last bar in the window, not its open. This instant is the
        #: whole point of the clock module: a decision that reads the close cannot exist
        #: before the bar closed, and the ledger records when it really did.
        decision_ts_ms = information_ms(
            int(bar.ts_ms), self.interval_ms, self.data_delay_ms
        )
        chart: ChartImage = render_chart_png(
            bars_seen, symbol=symbol, timeframe=self.timeframe, window_bars=self.window_bars
        )
        context = self._context(symbol, bar, bars_seen)
        prompt = self._prompt_builder(context, bars_seen)
        request = VisionRequest(
            chart=chart,
            prompt=prompt,
            decision_ts_ms=decision_ts_ms,
            detail=self.config.provider.detail,
        )

        # The guards run *before* the paid call: a chart that is stale, about another
        # asset or built from a bar that had not closed cannot produce a tradeable
        # opinion, so paying for the answer would be paying for nothing.
        try:
            assert_causal(bars_seen, decision_ts_ms, bar_interval_ms=self.interval_ms)
            assert_fresh(chart.last_ts_ms, int(bar.ts_ms))
            assert_asset(chart.symbol, symbol)
        except OpinionRejected as exc:
            self.ledger.append(
                "GUARD_REJECT",
                {
                    "ts_ms": decision_ts_ms,
                    "ts_utc": _utc_iso(decision_ts_ms),
                    "symbol": symbol,
                    "code": exc.code,
                    "detail": exc.detail,
                    "chart": chart.fingerprint(),
                    "stage": "PRE_CALL",
                    "phase": "DECISION",
                },
            )
            self._bump(f"guard:{exc.code}")
            return None

        base = {
            "ts_ms": decision_ts_ms,
            "ts_utc": _utc_iso(decision_ts_ms),
            "symbol": symbol,
            "decision_bar_ts_ms": int(bar.ts_ms),
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
            # FAIL-CLOSED: an answer to a *different* image is not an opinion about this
            # chart. Logging it and carrying on would let a mis-attached or corrupted
            # image produce a proposal, a fill and a P&L attributed to a chart the model
            # never saw. Nothing downstream may run: no decision, no fill, no approval.
            self.ledger.append(
                "INTEGRITY_FAILURE",
                {
                    **base,
                    "expected_image_sha256": chart.sha256,
                    "request_image_sha256": response.image_sha256_in_request,
                    "decision": None,
                    "discarded": True,
                },
            )
            self._bump("integrity_failure")
            return None

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
                "phase": "DECISION",
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
        #: An actionable opinion is one the pipeline owes a fill or a verdict. Counted
        #: here, at the only place an opinion is born, so the lifecycle cannot double-count
        #: a decision row that was never tradable.
        self._bump("opinion:generated")
        return PendingOrder(
            bar_index=0,  # filled by the caller with the bar index
            intent=resolved.intent,
            decision=decision,
            decision_seq=line.seq,
            decision_bar_open_ms=int(bar.ts_ms),
            decision_ts_ms=decision_ts_ms,
            #: The answer's arrival time, on the bar clock: the close it was formed on
            #: plus measured latency. Execution refuses a fill whose bar opened before
            #: the answer existed, and with this clock that means any real latency.
            received_at_ms=decision_ts_ms + max(0, int(response.latency_ms or 0)),
        )

    def _entry_bar_range(
        self, symbol: str, quote: Quote, bar_open_ms: int
    ) -> dict[str, Any] | None:
        """The part of the entry bar that happened *after* the fill, or ``None``.

        A bar-open fill needs no adjustment: nothing of the bar predates its open. An
        inside-bar fill does, and using the bar's whole high/low would let the stop read a
        price that occurred before the position existed. The declared row is what a
        verifier recomputes from the raw minutes, so the claim is not just a comment.
        """

        if int(quote.ts_ms) <= int(bar_open_ms):
            return None
        feed = self.subbar_feed
        if feed is None:  # pragma: no cover - guarded by the caller's branch
            return None
        until_ms = int(bar_open_ms) + self.interval_ms
        span = feed.range_between(symbol, int(quote.ts_ms), until_ms)
        if span is None:
            #: No minute is observable after the fill inside this bar: the range is the
            #: fill itself. Zero minutes is a measured fact, not a missing value.
            return {
                "entry_bar_range_from_ms": int(quote.ts_ms),
                "entry_bar_range_until_ms": until_ms,
                "entry_bar_range_minutes": 0,
                "entry_bar_range_high": float(quote.price),
                "entry_bar_range_low": float(quote.price),
                "entry_bar_range_last": None,
                "entry_bar_range_source": feed.name,
            }
        return {
            "entry_bar_range_from_ms": int(quote.ts_ms),
            "entry_bar_range_until_ms": until_ms,
            "entry_bar_range_minutes": int(span.minutes),
            "entry_bar_range_high": float(span.high),
            "entry_bar_range_low": float(span.low),
            "entry_bar_range_last": float(span.last),
            "entry_bar_range_source": span.source,
        }

    # -- execution -----------------------------------------------------------

    def _execute(self, symbol: str, bar: Any, pending: PendingOrder, bar_index: int) -> str:
        """Execute one pending opinion at this bar's open, or say why it cannot.

        Returns ``"RESOLVED"`` when the order is finished (filled or rejected) and
        ``"WAITING"`` when this bar's open predates the answer, in which case the order
        survives to the next quote.

        The price is looked up in the dataset itself, never reconstructed: ``quote_at``
        only returns a bar **open**, and raises if a price strictly inside a bar is asked
        for. That is what keeps a fill from being invented out of OHLC.
        """
        decision = pending.decision
        assert decision is not None
        ts = int(bar.ts_ms)

        # A hole in the data is not a price and not permission to trade. It is refused
        # unless a *separate* feed proves the venue stayed open and priced through it;
        # a later timestamp only says the clock advanced.
        gap = self._data_gap(symbol, pending, ts)
        if gap is not None and not gap["covered"]:
            self._reject_pending(
                symbol,
                ts,
                pending,
                "DATA_GAP",
                (
                    f"the bar that should have followed the decision at "
                    f"{gap['missing_bar_open_ms']} is absent; a quote at {ts} is later, not "
                    f"proof of continuity ({gap['reason']})"
                ),
                extra={
                    "missing_bar_open_ms": gap["missing_bar_open_ms"],
                    "missing_bars": gap["missing_bars"],
                    "coverage_reason": gap["reason"],
                },
            )
            return "RESOLVED"

        open_price = float(bar.open)
        if open_price <= 0:
            self._reject_pending(
                symbol,
                ts,
                pending,
                "NO_EXECUTABLE_PRICE",
                (
                    f"the bar that opens at {ts} has no positive open price; a zero is a "
                    "missing observation, not a market"
                ),
                extra={"quote_bar_open_ms": ts, "quote_price": open_price},
            )
            return "RESOLVED"

        quote: Quote | None = quote_at(
            symbol, self.series[symbol], ts, interval_ms=self.interval_ms
        )
        if quote is None:
            self._reject_pending(
                symbol,
                ts,
                pending,
                "NO_QUOTE_AT_BAR",
                (
                    f"bar {ts} is not in the dataset the run declared, so its open is not "
                    "a price this replay can prove was available"
                ),
            )
            return "RESOLVED"

        outcome = schedule(
            quote,
            received_at_ms=pending.received_at_ms,
            decision_ts_ms=pending.decision_ts_ms,
            max_age_ms=self.max_opinion_age_ms,
        )
        if outcome.status == "WAIT" and self.subbar_entries and self.subbar_feed is not None:
            # The bar's open predates the answer, but a finer feed may have priced inside
            # this bar after it. It is the same rule as the bar quote, one resolution down:
            # never a price older than the answer, and never a price outside this bar.
            sub = self.subbar_feed.first_quote_at_or_after(
                symbol, pending.received_at_ms, horizon_ms=self.interval_ms
            )
            if sub is not None and int(sub.ts_ms) < int(pending.received_at_ms):
                self._reject_pending(
                    symbol,
                    ts,
                    pending,
                    "FEED_CONTRACT_VIOLATION",
                    (
                        f"the feed answered {sub.ts_ms} for an instant at "
                        f"{pending.received_at_ms}: a price older than the answer is not "
                        "executable, and a feed that returns one is refused rather than "
                        "trusted"
                    ),
                    extra={"feed_quote_ts_ms": int(sub.ts_ms)},
                )
                return "RESOLVED"
            if sub is not None and ts <= int(sub.ts_ms) < ts + self.interval_ms:
                quote = sub
                outcome = schedule(
                    quote,
                    received_at_ms=pending.received_at_ms,
                    decision_ts_ms=pending.decision_ts_ms,
                    max_age_ms=self.max_opinion_age_ms,
                )
        if outcome.status == "WAIT":
            # The price existed before the answer did. Waiting is not a rejection: a
            # provider that takes ninety seconds still gets its next quote.
            self._bump("requote:WAITING_FOR_QUOTE")
            return "WAITING"
        if outcome.status == "EXPIRED":
            self.ledger.append(
                "GUARD_REJECT",
                {
                    "ts_ms": int(bar.ts_ms),
                    "ts_utc": _utc_iso(int(bar.ts_ms)),
                    "symbol": symbol,
                    "code": "LATE_RESPONSE",
                    "detail": (
                        f"the answer arrived at {pending.received_at_ms} and the first "
                        f"executable quote is {quote.ts_ms}: the opinion is "
                        f"{outcome.age_ms} ms old against a {self.max_opinion_age_ms} ms "
                        "window, so filling it would trade a view that no longer exists"
                    ),
                    "opinion_age_ms": outcome.age_ms,
                    "max_opinion_age_ms": self.max_opinion_age_ms,
                    #: Sin ``decision_seq`` esta fila no se podía unir con su nacimiento:
                    #: la opinión expiraba y, para cualquier verificador, desaparecía.
                    "decision_seq": pending.decision_seq,
                    "decision_ts_ms": pending.decision_ts_ms,
                    "received_at_ms": pending.received_at_ms,
                    **quote.to_row(),
                    "stage": "EXECUTION",
                },
            )
            self._bump("guard:LATE_RESPONSE")
            self._bump("opinion:expired")
            return "RESOLVED"

        price = float(quote.price)
        if price <= 0:
            #: Un precio no positivo no es un mercado. Sin fila terminal la opinión
            #: desaparecía del ledger en lugar de morir con nombre.
            self._reject_pending(
                symbol,
                int(quote.ts_ms),
                pending,
                "NON_POSITIVE_QUOTE",
                (
                    f"the first executable quote is {price!r}: a non-positive price is a "
                    "missing observation, not an execution"
                ),
                extra={"quote_ts_ms": int(quote.ts_ms), "quote_price": price},
            )
            return "RESOLVED"

        if pending.intent == "CLOSE":
            position = self.broker.positions.get(symbol)
            if position is None:
                #: La posición desapareció entre la opinión y su precio (salida
                #: protectora en la fase anterior). La opinión no puede ejecutarse y
                #: tiene que decirlo: un ``return`` silencioso la borraba del recuento.
                self._reject_pending(
                    symbol,
                    int(bar.ts_ms),
                    pending,
                    "NO_POSITION_TO_CLOSE",
                    "the position this opinion asked to close no longer exists at its quote",
                    extra={"quote_ts_ms": int(quote.ts_ms)},
                )
                return "RESOLVED"
            opened = float(position.opened_at)
            bars_held = round((float(quote.ts_ms) / 1000.0 - opened) / 3600.0)
            #: DEF-RUN-015: an explicit close, not an opposite signal. The lane used to
            #: send a `sell` to close a `buy`, which the broker read as a close only by
            #: accident and which the new contract refuses outright.
            result = self.broker.close_position(symbol, price, "signal")
            if result is not None and hasattr(result, "pnl"):
                # A model CLOSE is a market order at the quote that carried it, so the
                # exit instant is the quote, not the end of the bar.
                self._record_close(
                    result,
                    exit_ts_ms=quote.ts_ms,
                    window_start_ms=quote.ts_ms,
                    bars_held=bars_held,
                    resolution="QUOTE",
                    phase="OPEN_ENTRY",
                )
            self.ledger.append(
                "DECISION_OUTCOME",
                {
                    "ts_ms": int(bar.ts_ms),
                    "symbol": symbol,
                    "decision_seq": pending.decision_seq,
                    "intent": "CLOSE",
                    "risk_gate": "BYPASSED_FOR_REDUCTION",
                    "phase": "OPEN_ENTRY",
                    "executed": result is not None,
                },
            )
            if result is not None:
                #: Una opinión CLOSE ejecutada no produce un ``FILL`` (produce un ``CLOSE``),
                #: así que su clase terminal se cuenta aquí o no se cuenta en ninguna parte.
                self._bump("opinion:closed")
            else:
                #: La fila ya declaró ``executed: False``; el contador tiene que decir lo
                #: mismo o la opinión queda con una clase terminal no publicada.
                self._bump("gate:CLOSE_NOT_EXECUTED")
            return "RESOLVED"

        side: Side = "buy" if pending.intent == "OPEN_LONG" else "sell"
        #: DEF-RUN-014: the model's own invalidation distance travels to the risk engine.
        #: Omitting it was the defect: the manager then applied the policy default and the
        #: ledger reported a stop nobody had asked for.
        signal = Signal(
            symbol=symbol,
            side=side,
            strategy_name="ai_vision",
            timeframe=self.timeframe,
            confidence=float(decision.confidence),
            price=price,
            stop_loss_pct=decision.stop_loss_pct,
            take_profit_pct=decision.take_profit_pct,
            metadata={"decision_seq": pending.decision_seq},
        )
        check = self.risk.check_signal(signal)
        stop_row = check.stop_resolution.to_row() if check.stop_resolution else {}
        self.ledger.append(
            "DECISION_OUTCOME",
            {
                "ts_ms": int(bar.ts_ms),
                "symbol": symbol,
                "decision_seq": pending.decision_seq,
                "intent": pending.intent,
                "risk_gate": "check_signal",
                "phase": "OPEN_ENTRY",
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
                #: The whole stop contract, resolved by the risk engine (DEF-RUN-014).
                "stop_contract": stop_row,
                **stop_row,
            },
        )
        if not check.approved or check.position_size is None:
            self._bump(f"risk_blocked:{check.blocked_by or 'unknown'}")
            return "RESOLVED"
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
                    "phase": "OPEN_ENTRY",
                    "approved": True,
                    "executed": False,
                    "risk_blocked_by": exc.code,
                    "risk_reason": exc.detail,
                    "notional_usdt": notional,
                },
            )
            self._bump(f"gate:{exc.code}")
            return "RESOLVED"
        if symbol in self.broker.positions:
            self.ledger.append(
                "DECISION_OUTCOME",
                {
                    "ts_ms": ts,
                    "symbol": symbol,
                    "decision_seq": pending.decision_seq,
                    "intent": pending.intent,
                    "risk_gate": "SYMBOL_SLOT_OCCUPIED",
                    "phase": "OPEN_ENTRY",
                    "approved": True,
                    "executed": False,
                    "risk_blocked_by": "SYMBOL_SLOT_OCCUPIED",
                    "risk_reason": "the book already holds this symbol",
                },
            )
            self._bump("dropped:SYMBOL_SLOT_OCCUPIED")
            return "RESOLVED"

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
            #: El broker puede negarse después de que el riesgo aprobase. Sin esta fila la
            #: opinión no tendría evento terminal y desaparecería del ledger: el defecto que
            #: ``DEF-RUN-016`` existe para hacer imposible.
            self.ledger.append(
                "DECISION_OUTCOME",
                {
                    "ts_ms": ts,
                    "symbol": symbol,
                    "decision_seq": pending.decision_seq,
                    "intent": pending.intent,
                    "risk_gate": "BROKER_REJECTED",
                    "phase": "OPEN_ENTRY",
                    "approved": True,
                    "executed": False,
                    "risk_blocked_by": "BROKER_REJECTED",
                    "risk_reason": "the broker returned no order for an approved signal",
                    "notional_usdt": notional,
                },
            )
            self._bump("broker_rejected")
            return "RESOLVED"
        self.risk.sync_open_positions(dict(self.broker.positions))
        position_id = str(getattr(filled, "position_id", ""))
        #: The protective levels the broker actually holds, read from the position it just
        #: created. Recomputing them here from ``stop_loss_pct`` would be a second source
        #: of truth for the same number, and the CLOSE row exists to check the first.
        position = self.broker.positions.get(symbol)
        stop_price = float(position.stop_loss_price) if position is not None else 0.0
        target_price = float(position.take_profit_price) if position is not None else 0.0
        self._entry_provenance[position_id] = {
            "decision_bar_open_ms": int(pending.decision_bar_open_ms),
            "quote_ts_ms": quote.ts_ms,
            "quote_source": quote.source,
            "quote_lag_ms": outcome.lag_ms,
            "decision_ts_ms": pending.decision_ts_ms,
            "received_at_ms": pending.received_at_ms,
            "stop_loss_price": stop_price,
            "take_profit_price": target_price,
        }
        #: The post-fill range of the entry bar, when the fill happened inside the bar.
        #: ``None`` for a bar-open fill: there, the bar's own range is already causal.
        range_row = self._entry_bar_range(symbol, quote, ts)
        if range_row is not None:
            self._entry_provenance[position_id].update(range_row)
            self._entry_bar[symbol] = {
                "entry": price,
                "high": float(range_row["entry_bar_range_high"]),
                "low": float(range_row["entry_bar_range_low"]),
                "last": range_row["entry_bar_range_last"],
            }
        self.ledger.append(
            "FILL",
            {
                "ts_ms": int(bar.ts_ms),
                "ts_utc": _utc_iso(int(bar.ts_ms)),
                "symbol": symbol,
                "side": side,
                "intent": pending.intent,
                "phase": "OPEN_ENTRY",
                "decision_seq": pending.decision_seq,
                "decision_ts_ms": pending.decision_ts_ms,
                "received_at_ms": pending.received_at_ms,
                "decision_bar_open_ms": int(pending.decision_bar_open_ms),
                "decision_bar_index": pending.decision_bar_index,
                "fill_bar_index": bar_index,
                "quote_ts_ms": quote.ts_ms,
                "quote_price": quote.price,
                "quote_source": quote.source,
                "entry_quote_source": quote.source,
                "quote_bar_open_ms": quote.bar_open_ms,
                "quote_lag_ms": outcome.lag_ms,
                "opinion_age_ms": outcome.age_ms,
                **(range_row or {}),
                "data_gap_covered_by": gap["source"] if gap is not None else None,
                "data_gap_missing_bar_open_ms": (
                    gap["missing_bar_open_ms"] if gap is not None else None
                ),
                "stop_loss_price": stop_price,
                "take_profit_price": target_price,
                "position_id": getattr(filled, "position_id", ""),
                "entry_price": float(getattr(filled, "entry_price", price)),
                "reference_price": price,
                "quantity": float(getattr(filled, "quantity", 0.0)),
                "notional_usdt": float(sized.notional_usdt),
                # 003H: the commission this fill already owes, with the schedule that
                # produced it, so the open-position accrual can be rebuilt from the ledger
                # alone instead of being taken on the summary's word.
                "entry_commission_usdt": (
                    round(float(position.entry_commission), 8)
                    if position is not None
                    else None
                ),
                "commission_bps": (
                    round(float(position.commission_bps), 8) if position is not None else None
                ),
                "price_bps_per_side": (
                    round(float(position.price_bps_per_side), 8)
                    if position is not None
                    else None
                ),
                "stop_loss_pct": float(sized.stop_loss_pct),
                "take_profit_pct": float(sized.take_profit_pct),
                #: DEF-RUN-014: the fill row states where its protective distance came
                #: from and what it costs to survive, so a verifier can check the model →
                #: risk → order → ledger chain from these bytes alone.
                **(sized.stop_resolution.to_row() if sized.stop_resolution else {}),
            },
        )
        self._bump("fills")
        return "RESOLVED"

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
                        "bar_interval_ms": self.interval_ms,
                        "data_delay_ms": self.data_delay_ms,
                        "decision_from_ms": self.decision_from_ms,
                        "max_opinion_age_ms": self.max_opinion_age_ms,
                        "opinion_lifecycle": self.opinion_lifecycle,
                        "max_calls": self.max_calls,
                        "max_spend_usd": self.max_spend_usd,
                        # Declared conventions a reader needs to interpret every fill:
                        "execution_quote": "bar_open",
                        "stop_coverage": "entry_at_open_full_bar",
                        "gap_policy": "open_on_gap",
                        # The order inside one timestamp. A reader who does not know it
                        # cannot tell an early stop from a late one in the rows.
                        "open_phase_order": "gap_close>mark>entries>intrabar",
                        "exit_ts_resolutions": ["OPEN_GAP", "BAR_WINDOW", "QUOTE"],
                        "gap_price_source": "bar_open",
                        "data_gap_policy": "fail_closed_unless_independent_coverage",
                        "quote_feed": getattr(self.quote_feed, "name", None),
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
            symbols = sorted(self.series)
            for ts in timeline:
                close_ms = bar_close_ms(ts, self.interval_ms)
                day = _day_of(ts)
                if previous_day is not None and day != previous_day:
                    self.risk.reset_daily()
                previous_day = day

                # Stable symbol order for every phase. A dict's insertion order is not a
                # policy: with one free slot, whoever is iterated first would take it.
                present = [
                    (symbol, self.series[symbol], index_of[symbol][ts])
                    for symbol in symbols
                    if ts in index_of[symbol]
                ]
                open_prices: dict[str, float] = {}
                for symbol, bars, index in present:
                    price = float(bars[index].open)
                    if price > 0:
                        open_prices[symbol] = price

                # -- OPEN(ts) --------------------------------------------------
                self._current_ms[0] = ts

                # 1. Stops the observable open already crossed, for positions that
                #    existed *before* it. Every symbol is settled before a single order
                #    is approved, so no symbol's position in the iteration decides what
                #    the risk engine sees.
                for symbol, price in sorted(open_prices.items()):
                    trade: ClosedTrade | None = self.broker.exit_on_open_gap(symbol, price)
                    if trade is None:
                        continue
                    opened_ms = int(float(trade.opened_at) * 1000)
                    self._record_close(
                        trade,
                        exit_ts_ms=ts,
                        window_start_ms=ts,
                        bars_held=max(0, round((ts - opened_ms) / self.interval_ms)),
                        resolution="OPEN_GAP",
                        phase="OPEN_GAP",
                        gap_price_source="bar_open",
                        gap_open_price=price,
                    )

                # 2. Mark what is left at the opens that are observable now. A held
                #    symbol without one makes the book's equity ambiguous — assuming its
                #    missing PnL is zero would understate the risk being approved.
                stale = sorted(
                    symbol for symbol in self.broker.positions if symbol not in open_prices
                )
                if stale:
                    self._bump("veto:STALE_VALUATION")
                else:
                    self.risk.mark_equity(
                        float(self.broker.mark_to_market_equity(dict(open_prices)))
                    )

                # 3. Entries, on quotes that exist at or after the answer.
                for symbol, bars, index in present:
                    pending = self._pending.get(symbol)
                    if pending is None:
                        continue
                    if stale:
                        self._reject_pending(
                            symbol,
                            ts,
                            pending,
                            "STALE_VALUATION",
                            (
                                f"{', '.join(stale)} has no quote at this open: the book's "
                                "equity is ambiguous, so no new risk is approved against it"
                            ),
                            extra={"stale_marks": stale},
                        )
                        self._pending.pop(symbol, None)
                        continue
                    if self._execute(symbol, bars[index], pending, index) == "RESOLVED":
                        self._pending.pop(symbol, None)

                # -- CLOSE(ts + interval) --------------------------------------
                self._current_ms[0] = close_ms
                candles = {
                    symbol: (
                        float(bars[index].open),
                        float(bars[index].high),
                        float(bars[index].low),
                        float(bars[index].close),
                    )
                    for symbol, bars, index in present
                }
                # A position that opened inside this bar may only see the bar from its
                # fill onwards. Replacing the candle for those symbols is the whole
                # look-ahead guard: the stop is checked on a range that did not exist
                # before the fill did. Symbols opened at the bar's open are untouched.
                for symbol, info in self._entry_bar.items():
                    current = candles.get(symbol)
                    if current is None:
                        continue
                    entry_price = float(info["entry"])
                    last = info.get("last")
                    candles[symbol] = (
                        entry_price,
                        max(entry_price, float(info["high"])),
                        min(entry_price, float(info["low"])),
                        float(current[3]) if last is None else float(last),
                    )
                # The bar has ended, so its range is a fact — including for a position
                # opened at this bar's open, which must be checked *after* it exists. The
                # exit is recorded at the close because that is the earliest instant an
                # intrabar touch could have been known; the level, not the range, is the
                # price. A stop the open itself crossed was already settled above.
                for trade in self.broker.check_positions_ohlc(
                    candles, gap_policy="open_on_gap"
                ):
                    opened_ms = int(float(trade.opened_at) * 1000)
                    self._record_close(
                        trade,
                        exit_ts_ms=close_ms,
                        window_start_ms=ts,
                        bars_held=max(0, round((close_ms - opened_ms) / self.interval_ms)),
                        resolution="BAR_WINDOW",
                        phase="INTRABAR",
                    )
                #: Consumed. A later bar starts from its own range, not from this override.
                self._entry_bar.clear()

                quoted = {
                    symbol
                    for symbol, bars, index in present
                    if float(bars[index].close) > 0
                }
                for symbol, bars, index in present:
                    if symbol in quoted:
                        self._marks[symbol] = float(bars[index].close)

                # Marking the risk engine with the same net equity the curve publishes is
                # what makes its drawdown and sizing gates describe the book the report
                # describes. A carried-over mark is declared, never passed off as fresh.
                marked = float(self.broker.mark_to_market_equity(dict(self._marks)))
                self.risk.mark_equity(marked)
                carried = sorted(symbol for symbol in self.broker.positions if symbol not in quoted)
                self.equity_curve.append(
                    {
                        "ts_ms": close_ms,
                        "ts_utc": _utc_iso(close_ms),
                        "equity": round(marked, 8),
                        "risk_equity": round(float(self.risk.equity), 8),
                        "stale_marks": carried,
                    }
                )

                # 4. Decisions are formed on the close, which is now known, and are sized
                #    against the equity this close produced.
                for symbol, bars, index in present:
                    if (
                        self.decision_from_ms is not None
                        and information_ms(ts, self.interval_ms, self.data_delay_ms)
                        < self.decision_from_ms
                    ):
                        # The bar closed before the session began: it is context, not a
                        # prospective decision, and paying for an opinion about it would
                        # be a replay inside a live run.
                        continue
                    if not decision_due(
                        index,
                        window_bars=self.window_bars,
                        every=self.decision_every,
                        stop_reason=self.stop_reason,
                    ):
                        continue
                    waiting = self._pending.get(symbol)
                    if waiting is not None:
                        # DEF-RUN-016. A newer opinion can never be available at the
                        # instant the waiting one is priced: the waiting answer is at
                        # ``close(k) + L`` and its first open is < ``close(k) + L + T``,
                        # while the next opinion answers at ``close(k) + T + L``. So the
                        # waiting opinion is the freshest one *that exists* when its quote
                        # is read, and replacing it destroys the only executable view. The
                        # paid call is not made; the slot is recorded as deferred.
                        #: At the live edge the next bar does not exist *yet*. Taking that as
                        #: "no quote" would supersede the newest opinion as a side effect of
                        #: the series being shorter, and the next cycle would then disagree
                        #: with the previous one about a decision that was already made. The
                        #: grid's next open is the honest candidate there, and it is labelled
                        #: as an assumption instead of passed off as a fact.
                        #: La decisión se toma sobre la **rejilla declarada**, nunca sobre si
                        #: la serie ya contiene esa barra. Si dependiera de los datos futuros,
                        #: el último turno de un ciclo se resolvería de una forma y, al
                        #: llegar la barra, de otra: el prefijo del ledger divergiría y la
                        #: sesión marcaría ``PREFIX_DIVERGENCE`` sobre una decisión pasada.
                        #: Un hueco sigue siendo un hueco: `_data_gap` lo comprueba al leer el
                        #: precio, y cubre ya todo el tramo recorrido.
                        #: La apertura se **proyecta** con la rejilla declarada, así que su
                        #: procedencia es ``grid`` y se dice: no se leyó del dataset. Si el
                        #: dataset tiene un hueco, `_data_gap` lo rechaza al leer el precio.
                        next_open_source = "grid"
                        ahead = max(0, int(waiting.received_at_ms) - int(close_ms))
                        steps = math.ceil(ahead / self.interval_ms)
                        planned = int(close_ms) + steps * self.interval_ms
                        #: Only an opinion that can still be priced inside its declared TTL is
                        #: worth protecting. If the first open at or after the answer is
                        #: already older than ``max_opinion_age_ms`` (a model slower than
                        #: its own window), the waiting order is obsolete by construction:
                        #: it is superseded as before and the slot is not starved forever.
                        still_tradable = (
                            self.opinion_lifecycle == OPINION_LIFECYCLE_DEFER
                            and int(planned) - int(waiting.decision_ts_ms)
                            <= self.max_opinion_age_ms
                        )
                        if still_tradable:
                            self._defer_decision(
                                symbol,
                                close_ms,
                                waiting,
                                int(planned),
                                next_open_source,
                            )
                            continue
                        decision = self._decide(symbol, bars[index], bars[: index + 1])
                        if decision is not None:
                            self._reject_pending(
                                symbol,
                                close_ms,
                                waiting,
                                "SUPERSEDED_BY_NEWER_OPINION",
                                (
                                    "the waiting opinion cannot be priced inside its "
                                    "declared window any more; a newer view replaced it"
                                ),
                                extra={
                                    "replaced_by_decision_seq": decision.decision_seq,
                                    "next_executable_open_ms": int(planned),
                                    "next_executable_open_source": next_open_source,
                                    "opinion_age_at_next_open_ms": (
                                        int(planned) - int(waiting.decision_ts_ms)
                                    ),
                                    "max_opinion_age_ms": self.max_opinion_age_ms,
                                },
                                phase="DECISION",
                            )
                            self._pending[symbol] = replace(
                                decision,
                                bar_index=index + 1,
                                decision_bar_index=index,
                                expected_step_ms=int(self._step_ms[symbol]),
                            )
                        continue
                    decision = self._decide(symbol, bars[index], bars[: index + 1])
                    if decision is not None:
                        self._pending[symbol] = replace(
                            decision,
                            bar_index=index + 1,
                            decision_bar_index=index,
                            expected_step_ms=int(self._step_ms[symbol]),
                        )

            #: An order still waiting when the dataset ends never became a trade, and
            #: saying so is the difference between "no fill" and "no record".
            self._pending_at_end = len(self._pending)

            for symbol, pending in sorted(self._pending.items()):
                self._reject_pending(
                    symbol,
                    self._current_ms[0],
                    pending,
                    "RUN_ENDED_WITH_ORDER_PENDING",
                    "the dataset ended before a quote existed at or after the answer",
                    phase="RUN_END",
                )
            self._pending.clear()

            summary = self._summary()
            #: DEF-RUN-016: la contabilidad se contrasta contra los bytes ya persistidos y
            #: **antes** de publicar el resumen. Un resumen que no explica todas sus
            #: opiniones no se escribe como ``RUN_END``: se escribe el fallo y se levanta,
            #: porque un PASS publicado no se puede retirar.
            self._enforce_opinion_lifecycle(summary)
            self.ledger.append("RUN_END", summary)
            return summary
        finally:
            self.ledger.close()

    # -- opinion lifecycle ---------------------------------------------------

    def _opinion_lifecycle_view(self) -> dict[str, Any]:
        """Reconstruye la vida de cada opinión desde los bytes del ledger.

        No se cree a los contadores: la identidad se comprueba sobre las filas que ya
        están en disco, y una opinión nacida sin evento terminal, cerrada dos veces o
        terminal sin nacimiento es un fallo, no un valor que cuadrar a mano. Es
        deliberadamente distinto del verificador independiente
        (``scripts/def_run_016_verify.py``), que no importa este paquete y vuelve a
        derivar clases, causas y cadenas: un defecto del algoritmo no puede esconderse en
        los dos sitios a la vez.
        """
        lines = read_entries(self.ledger.path)
        births: dict[int, str] = {}
        terminals: dict[int, list[dict[str, Any]]] = {}
        for line in lines:
            entry = line.get("entry") or {}
            seq = int(line["seq"])
            if entry.get("kind") == "DECISION" and entry.get("intent") in ACTIONABLE_INTENTS:
                births[seq] = str(entry["intent"])
                continue
            target = entry.get("decision_seq")
            if target is None:
                continue
            observed = _terminal_event(entry)
            if observed is None:
                continue
            terminals.setdefault(int(target), []).append(
                {
                    "seq": seq,
                    "kind": entry.get("kind"),
                    "class": observed[0],
                    "reason": observed[1],
                }
            )
        classes = dict.fromkeys(TERMINAL_CLASSES, 0)
        rejected: dict[str, int] = {}
        duplicate: list[dict[str, Any]] = []
        orphan: list[dict[str, Any]] = []
        for seq in sorted(terminals):
            events = terminals[seq]
            if seq not in births:
                orphan.append({"decision_seq": seq, "events": events})
                continue
            if len(events) > 1:
                #: Dos cierres de la misma opinión es la forma exacta de contarla dos
                #: veces. Se publica entera; elegir el primero la ocultaría.
                duplicate.append({"decision_seq": seq, "events": events})
            first = events[0]
            classes[first["class"]] += 1
            if first["class"] == "REJECTED":
                reason = str(first["reason"])
                rejected[reason] = rejected.get(reason, 0) + 1
        unrecorded = sorted(seq for seq in births if seq not in terminals)
        return {
            "schema_version": OPINION_ACCOUNTING_SCHEMA,
            "source": "ledger_bytes",
            "invariant": OPINION_ACCOUNTING_IDENTITY,
            #: No hay continuidad entre sesiones en este carril: cada ``run`` es un replay
            #: cerrado y sus órdenes en vuelo mueren con él. Se declara en lugar de
            #: dejar que un lector lo suponga, y una sesión que sí continuara tendría que
            #: publicar otra cosa aquí antes de terminalizar sus pendientes.
            "session_continuity": "NONE",
            "generated": len(births),
            "terminal_classes": dict(classes),
            "rejected_by_code": dict(sorted(rejected.items())),
            "unrecorded": unrecorded,
            "duplicate_terminals": duplicate,
            "orphan_terminals": orphan,
            #: El sha256 de la cadena no se publica aquí a propósito: incluye
            #: ``recorded_at_utc`` y por tanto dos corridas idénticas no producen el mismo
            #: valor. La integridad de la cadena la certifica el verificador desde los
            #: bytes publicados; el resumen solo declara sobre cuántas filas se comprobó.
            "ledger_lines": len(lines),
            "ok": not unrecorded and not duplicate and not orphan,
        }

    def _enforce_opinion_lifecycle(self, summary: dict[str, Any]) -> None:
        """Exige ``generated == sum(disjoint terminal classes)`` o no publica resumen.

        Tres comprobaciones, cada una capaz de tumbar la publicación por sí sola:

        1. estructural: toda opinión nace una vez y termina exactamente una vez;
        2. contable: los contadores publicados coinciden con las filas del ledger;
        3. de vistas: ``expired``, ``superseded`` y ``pending_at_end`` describen la misma
           opinión que su código de rechazo, no una segunda cuenta.
        """
        view = self._opinion_lifecycle_view()
        classes = view["terminal_classes"]
        published = summary.setdefault("execution", {}).setdefault("opinions", {})
        #: La vista publicada es la del ledger: ``rejected`` describe **opiniones**, y un
        #: guarda *pre-call* (causal, frescura, activo) rechaza una llamada que nunca fue
        #: opinión. Mezclarlos era lo que permitía que la identidad «cuadrara» contando
        #: llamadas que jamás llegaron a ser una decisión accionable.
        published["rejected"] = dict(view["rejected_by_code"])
        published["terminal_classes"] = dict(classes)
        published["lifecycle"] = view
        expected = {
            "generated": int(self.counters.get("opinion:generated", 0)),
            "executed_openings": int(self.counters.get("fills", 0)),
            "closed_by_intent": int(self.counters.get("opinion:closed", 0)),
            "blocked_by_risk": sum(
                value for key, value in self.counters.items() if key.startswith("risk_blocked:")
            ),
            "gated": (
                int(self.counters.get("broker_rejected", 0))
                + int(self.counters.get("dropped:SYMBOL_SLOT_OCCUPIED", 0))
                + sum(value for key, value in self.counters.items() if key.startswith("gate:"))
            ),
        }
        observed = {
            "generated": int(view["generated"]),
            "executed_openings": int(classes["FILLED"]),
            "closed_by_intent": int(classes["CLOSED"]),
            "blocked_by_risk": int(classes["BLOCKED_BY_RISK"]),
            "gated": int(classes["GATED"]),
        }
        disagreements: list[dict[str, Any]] = [
            {"field": key, "counter": expected[key], "ledger": observed[key]}
            for key in expected
            if expected[key] != observed[key]
        ]
        for code, count in sorted(view["rejected_by_code"].items()):
            counter = int(self.counters.get(f"guard:{code}", 0))
            if counter != int(count):
                disagreements.append(
                    {"field": f"rejected:{code}", "counter": counter, "ledger": int(count)}
                )
        for field, code in (
            ("expired", "LATE_RESPONSE"),
            ("superseded", "SUPERSEDED_BY_NEWER_OPINION"),
            ("pending_at_end", "RUN_ENDED_WITH_ORDER_PENDING"),
        ):
            declared = int(published.get(field) or 0)
            counted = int(view["rejected_by_code"].get(code, 0))
            if declared != counted:
                disagreements.append(
                    {"field": field, "view": declared, "ledger": counted}
                )
        adds_up = bool(view["ok"] and not disagreements)
        summary["opinion_accounting"] = {
            "schema_version": OPINION_ACCOUNTING_SCHEMA,
            "invariant": OPINION_ACCOUNTING_IDENTITY,
            "source": "ledger_bytes",
            "session_continuity": view["session_continuity"],
            "adds_up": adds_up,
            "generated": view["generated"],
            "terminal_classes": dict(classes),
            "terminal": sum(classes.values()),
            "unrecorded": view["unrecorded"],
            "duplicate_terminals": view["duplicate_terminals"],
            "orphan_terminals": view["orphan_terminals"],
            "deferred_slots": int(published.get("deferred_slots") or 0),
            "counter_disagreements": disagreements,
            "ledger_lines": view["ledger_lines"],
        }
        summary.setdefault("reconciliation", {}).setdefault("identities", {})[
            "opinion_lifecycle_adds_up"
        ] = adds_up
        if not adds_up:
            failure = {
                "ts_ms": int(self._current_ms[0]),
                "ts_utc": _utc_iso(int(self._current_ms[0])),
                "phase": "RUN_END",
                "code": "OPINION_LIFECYCLE_VIOLATION",
                "invariant": OPINION_ACCOUNTING_IDENTITY,
                "detail": (
                    "the ledger does not account for every opinion it produced, so no "
                    "summary is published as RUN_END"
                ),
                "opinion_accounting": summary["opinion_accounting"],
                "counters": dict(sorted(self.counters.items())),
                "persisted_before_raise": True,
            }
            self.ledger.append("INTEGRITY_FAILURE", failure)
            raise OpinionLifecycleError(
                "OPINION_LIFECYCLE_VIOLATION",
                OPINION_ACCOUNTING_IDENTITY + " is false; no summary was published",
                generated=view["generated"],
                terminal_classes=dict(classes),
                unrecorded=view["unrecorded"],
                duplicate_terminals=view["duplicate_terminals"],
                orphan_terminals=view["orphan_terminals"],
                counter_disagreements=disagreements,
            )

    def _accounting(self, trades: Sequence[Any]) -> dict[str, Any]:
        """The one place where costs and PnL are separated, for summary and reconciliation.

        003G-D5 lived here: the summary summed ``trades`` (closed operations) and published
        ``costs_usdt = 0`` while an open position had already accrued 0.5 USDT of entry
        commission and the marked equity already reflected it. Two readers of the same run
        could not both be right, so the terms are now computed once and returned under
        names that say which half of the book they describe.

        No cost is counted twice: a position is either open (its entry commission is
        accrued) or closed (its commissions are realised), never both — the broker pops
        the position when it closes, and the disjointness is checked as an identity.
        """
        realised_entry = sum(float(t.entry_commission) for t in trades)
        realised_exit = sum(float(t.exit_commission) for t in trades)
        realised_execution = sum(float(t.execution_cost_usdt) for t in trades)
        accrued_open = float(self.broker.accrued_entry_commissions())
        realised = sum(float(t.pnl) for t in trades)
        prices = {symbol: float(price) for symbol, price in self._marks.items()}
        unrealised_gross = float(self.broker.unrealized_pnl(prices))
        unrealised_net = float(self.broker.unrealized_pnl_net(prices))
        costs_realised = realised_entry + realised_exit + realised_execution
        costs_total = costs_realised + accrued_open
        pnl_total = realised + unrealised_net
        open_ids = {
            str(position.position_id): symbol
            for symbol, position in self.broker.positions.items()
        }
        closed_ids = {str(trade.position_id) for trade in trades}
        overlap = sorted(set(open_ids) & closed_ids)
        initial = float(self.equity)
        marked = float(self.broker.mark_to_market_equity(prices))
        return {
            "initial_equity_usdt": round(initial, 8),
            "entry_commissions_realised_usdt": round(realised_entry, 8),
            "exit_commissions_realised_usdt": round(realised_exit, 8),
            "execution_costs_realised_usdt": round(realised_execution, 8),
            "costs_realised_usdt": round(costs_realised, 8),
            "entry_commissions_accrued_open_usdt": round(accrued_open, 8),
            "costs_total_usdt": round(costs_total, 8),
            "pnl_realised_usdt": round(realised, 8),
            "pnl_unrealised_usdt": round(unrealised_net, 8),
            "pnl_unrealised_gross_usdt": round(unrealised_gross, 8),
            "pnl_total_usdt": round(pnl_total, 8),
            "marked_equity_usdt": round(marked, 8),
            "cash_equity_usdt": round(float(self.broker.equity), 8),
            "open_position_ids": sorted(open_ids),
            "overlapping_position_ids": overlap,
            "prices_used_for_mark": {symbol: round(price, 8) for symbol, price in prices.items()},
        }

    def _summary(self) -> dict[str, Any]:
        trades = list(self.broker.closed_trades)
        net = sum(float(trade.pnl) for trade in trades)
        accounting = self._accounting(trades)
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
            #: Unchanged meaning (realised closed-trade cost). The open half of the book is
            #: named next to it so the two can never be confused again.
            "costs_usdt": round(sum(float(t.total_cost_usdt) for t in trades), 6),
            "entry_commissions_realised_usdt": accounting["entry_commissions_realised_usdt"],
            "exit_commissions_realised_usdt": accounting["exit_commissions_realised_usdt"],
            "execution_costs_realised_usdt": accounting["execution_costs_realised_usdt"],
            "costs_realised_usdt": accounting["costs_realised_usdt"],
            "entry_commissions_accrued_open_usdt": accounting[
                "entry_commissions_accrued_open_usdt"
            ],
            "costs_total_usdt": accounting["costs_total_usdt"],
            "pnl_realised_usdt": accounting["pnl_realised_usdt"],
            "pnl_unrealised_usdt": accounting["pnl_unrealised_usdt"],
            "pnl_total_usdt": accounting["pnl_total_usdt"],
            "marked_equity_usdt": accounting["marked_equity_usdt"],
            "accounting": {
                "schema_version": ACCOUNTING_SCHEMA_VERSION,
                "initial_equity_usdt": accounting["initial_equity_usdt"],
                "mark_prices": accounting["prices_used_for_mark"],
                "meanings": dict(COST_MEANINGS),
            },
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
            "execution": self._execution_report(),
            "reconciliation": self._reconciliation(trades),
            "counters": dict(sorted(self.counters.items())),
            "open_positions_at_end": {
                symbol: {
                    "side": position.side,
                    "entry_price": float(position.entry_price),
                    "notional_usdt": float(position.notional_usdt),
                    "position_id": str(position.position_id),
                    "entry_commission_usdt": round(float(position.entry_commission), 8),
                    "mark_price": float(self._marks.get(symbol, 0.0)),
                    "unrealised_pnl_usdt": round(
                        float(
                            position.unrealized_pnl(float(self._marks.get(symbol, 0.0)))
                        ),
                        8,
                    )
                    if float(self._marks.get(symbol, 0.0)) > 0
                    else None,
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


    def _execution_report(self) -> dict[str, Any]:
        """What the fill model actually did, in the terms a reader has to check.

        ``quote_lag_ms`` is the wait between the answer and the price paid, which is the
        number the old lane could not report because it never waited: it rejected the
        order instead.
        """
        lags = [
            int(entry["quote_lag_ms"])
            for entry in self._entry_provenance.values()
            if "quote_lag_ms" in entry
        ]
        #: The four instants a pipeline audit has to separate. ``provider_ms`` is the model
        #: thinking, ``quote_wait_ms`` is the price waiting for the answer (and vice versa),
        #: ``decision_to_quote_ms`` is the whole delay the opinion survives, and
        #: ``data_to_decision_ms`` is the feed delay declared for this run.
        provider_gaps = [
            int(entry["received_at_ms"]) - int(entry["decision_ts_ms"])
            for entry in self._entry_provenance.values()
            if "received_at_ms" in entry and "decision_ts_ms" in entry
        ]
        quote_waits = [
            int(entry["quote_ts_ms"]) - int(entry["received_at_ms"])
            for entry in self._entry_provenance.values()
            if "quote_ts_ms" in entry and "received_at_ms" in entry
        ]
        decision_to_quote = [
            int(entry["quote_ts_ms"]) - int(entry["decision_ts_ms"])
            for entry in self._entry_provenance.values()
            if "quote_ts_ms" in entry and "decision_ts_ms" in entry
        ]
        data_to_decision = [
            int(entry["decision_ts_ms"])
            - (int(entry["decision_bar_open_ms"]) + self.interval_ms)
            for entry in self._entry_provenance.values()
            if "decision_ts_ms" in entry and "decision_bar_open_ms" in entry
        ]
        sources: dict[str, int] = {}
        for entry in self._entry_provenance.values():
            source = str(entry.get("quote_source") or "unknown")
            sources[source] = sources.get(source, 0) + 1
        sub_bar_fills = sum(
            1
            for entry in self._entry_provenance.values()
            if str(entry.get("quote_source") or BAR_OPEN_SOURCE) != BAR_OPEN_SOURCE
        )
        return {
            "quote_source": "bar_open",
            "entry_quote_sources": dict(sorted(sources.items())),
            "subbar_entries": self.subbar_entries,
            "sub_bar_fills": sub_bar_fills,
            #: A bar-open fill already sees its whole bar; an inside-bar fill only sees the
            #: minutes strictly after it. Named so the difference is auditable.
            "entry_bar_range_policy": (
                "minutes_strictly_after_the_fill"
                if sub_bar_fills
                else "full_bar_from_its_open"
            ),
            "bar_interval_ms": self.interval_ms,
            "max_opinion_age_ms": self.max_opinion_age_ms,
            "stop_coverage": (
                "entry_bar_from_the_fill"
                if sub_bar_fills
                else "entry_at_open_full_bar"
            ),
            "gap_policy": "open_on_gap",
            "open_phase_order": "gap_close>mark>entries>intrabar",
            "exit_ts_resolutions": ["OPEN_GAP", "BAR_WINDOW", "QUOTE"],
            "data_gap_policy": "fail_closed_unless_independent_coverage",
            "gap_exits": int(self.counters.get("gap_exits", 0)),
            "stale_valuation_vetoes": int(self.counters.get("veto:STALE_VALUATION", 0)),
            "fills": int(self.counters.get("fills", 0)),
            "waiting_events": int(self.counters.get("requote:WAITING_FOR_QUOTE", 0)),
            "expired_opinions": int(self.counters.get("guard:LATE_RESPONSE", 0)),
            #: DEF-RUN-016: one row per opinion, from birth to its terminal event. La
            #: identidad que este bloque publica es la de la fila terminal, no la del motivo:
            #:
            #:     generated = executed_openings + closed_by_intent + blocked_by_risk
            #:                 + gated + sum(rejected.values())
            #:
            #: ``superseded``, ``expired`` y ``pending_at_end`` son **vistas** de
            #: ``rejected`` (su código), no sumandos extra: contarlas además sería contar dos
            #: veces la misma opinión. Un `DATA_GAP` o un `RUN_ENDED_WITH_ORDER_PENDING` no
            #: cabían en la identidad anterior y hacían que una opinión «desapareciera».
            "opinions": {
                "generated": int(self.counters.get("opinion:generated", 0)),
                "deferred_slots": int(self.counters.get("opinion:deferred", 0)),
                "superseded": int(
                    self.counters.get("guard:SUPERSEDED_BY_NEWER_OPINION", 0)
                ),
                "expired": int(self.counters.get("opinion:expired", 0)),
                "executed_openings": int(self.counters.get("fills", 0)),
                "closed_by_intent": int(self.counters.get("opinion:closed", 0)),
                "blocked_by_risk": sum(
                    value
                    for key, value in self.counters.items()
                    if key.startswith("risk_blocked:")
                ),
                #: Aprobada por el riesgo y aun así sin orden: la ventana, el coste, el
                #: hueco del símbolo o el broker la pararon después del veredicto.
                "gated": (
                    int(self.counters.get("broker_rejected", 0))
                    + int(self.counters.get("dropped:SYMBOL_SLOT_OCCUPIED", 0))
                    + sum(
                        value
                        for key, value in self.counters.items()
                        if key.startswith("gate:")
                    )
                ),
                "rejected": dict(
                    sorted(
                        (key.split(":", 1)[1], int(value))
                        for key, value in self.counters.items()
                        if key.startswith("guard:")
                    )
                ),
                "pending_at_end": int(getattr(self, "_pending_at_end", 0)),
                "deferrals_per_opinion": dict(
                    sorted((str(seq), count) for seq, count in self._deferrals.items())
                ),
            },
            "stage_latency_ms": {
                "data_to_decision": _latencies(data_to_decision),
                "decision_to_received": _latencies(provider_gaps),
                "received_to_quote": _latencies(quote_waits),
                "decision_to_quote": _latencies(decision_to_quote),
            },
            "quote_lag_ms": {
                "min": min(lags) if lags else None,
                "max": max(lags) if lags else None,
                "median": (sorted(lags)[len(lags) // 2] if lags else None),
            },
        }

    def _close_after_entry(self, trade: Any) -> bool:
        """Did this exit happen after the quote that opened it existed?

        Missing provenance fails the check. A default that made it pass would be the same
        vacuous guard this block exists to remove.
        """
        provenance = self._entry_provenance.get(str(trade.position_id))
        if provenance is None:
            return False
        return float(trade.closed_at) * 1000 + 0.5 >= float(provenance["quote_ts_ms"])

    def _reconciliation(self, trades: Sequence[Any]) -> dict[str, Any]:
        """The four quantities kept apart, with every identity checked.

        A single "equity" number cannot show which of cash, realised PnL, costs or the
        risk engine's view went wrong, so the residual of each identity is computed and
        returned as a boolean. ``False`` here invalidates the run; it is not a warning.
        """
        initial = float(self.equity)
        final = float(self.broker.equity)
        realised = sum(float(trade.pnl) for trade in trades)
        reference_gross = sum(float(trade.reference_gross_pnl) for trade in trades)
        execution_cost = sum(float(trade.execution_cost_usdt) for trade in trades)
        entry_commission = sum(float(trade.entry_commission) for trade in trades)
        exit_commission = sum(float(trade.exit_commission) for trade in trades)
        accounting = self._accounting(trades)
        marked_now = float(self.broker.mark_to_market_equity(dict(self._marks)))
        curve_end = float(self.equity_curve[-1]["equity"]) if self.equity_curve else final
        tolerance = 1e-6
        return {
            "initial_equity_usdt": round(initial, 8),
            "final_equity_usdt": round(final, 8),
            "marked_equity_usdt": round(marked_now, 8),
            "curve_end_equity_usdt": round(curve_end, 8),
            "risk_equity_usdt": round(float(self.risk.equity), 8),
            "net_realised_usdt": round(realised, 8),
            "reference_gross_usdt": round(reference_gross, 8),
            "execution_cost_usdt": round(execution_cost, 8),
            "entry_commission_usdt": round(entry_commission, 8),
            "exit_commission_usdt": round(exit_commission, 8),
            #: The open half of the book, kept apart from the realised half.
            "accounting_schema_version": ACCOUNTING_SCHEMA_VERSION,
            "costs_realised_usdt": accounting["costs_realised_usdt"],
            "entry_commissions_accrued_open_usdt": accounting[
                "entry_commissions_accrued_open_usdt"
            ],
            "costs_total_usdt": accounting["costs_total_usdt"],
            "unrealised_pnl_gross_usdt": accounting["pnl_unrealised_gross_usdt"],
            "unrealised_pnl_net_usdt": accounting["pnl_unrealised_usdt"],
            "pnl_total_usdt": accounting["pnl_total_usdt"],
            "open_positions_at_end": len(self.broker.positions),
            "open_position_ids_at_end": accounting["open_position_ids"],
            "open_gap_exits": int(self.counters.get("gap_exits", 0)),
            "marks_complete_at_end": all(
                float(self._marks.get(symbol, 0.0)) > 0 for symbol in self.broker.positions
            ),
            "tolerance_usdt": tolerance,
            "identities": {
                "cash_rebuilds_from_realised_pnl": abs(final - (initial + realised))
                <= tolerance,
                "net_pnl_nets_every_named_cost": abs(
                    realised
                    - (reference_gross - execution_cost - entry_commission - exit_commission)
                )
                <= tolerance,
                "risk_equity_matches_marked_equity": abs(float(self.risk.equity) - marked_now)
                <= tolerance,
                "curve_ends_at_final_equity": abs(curve_end - marked_now) <= tolerance,
                "every_close_after_its_entry_quote": all(
                    self._close_after_entry(trade) for trade in trades
                ),
                "every_fill_pays_at_or_after_its_answer": all(
                    "quote_ts_ms" in entry
                    and "received_at_ms" in entry
                    and int(entry["quote_ts_ms"]) >= int(entry["received_at_ms"])
                    for entry in self._entry_provenance.values()
                ),
                # 003H: the open half of the book is accounted for, named and disjoint.
                "total_costs_equal_realised_plus_accrued": abs(
                    accounting["costs_total_usdt"]
                    - (accounting["costs_realised_usdt"] + accounting["entry_commissions_accrued_open_usdt"])
                )
                <= tolerance,
                "realised_costs_equal_closed_trade_legs": abs(
                    accounting["costs_realised_usdt"]
                    - (entry_commission + exit_commission + execution_cost)
                )
                <= tolerance,
                "marked_equity_rebuilds_from_open_position": abs(
                    marked_now
                    - (
                        final
                        + accounting["pnl_unrealised_gross_usdt"]
                        - accounting["entry_commissions_accrued_open_usdt"]
                    )
                )
                <= tolerance,
                "total_pnl_moves_the_marked_book": abs(
                    accounting["marked_equity_usdt"]
                    - (initial + accounting["pnl_total_usdt"])
                )
                <= tolerance,
                "open_positions_are_disjoint_from_closed_trades": not accounting[
                    "overlapping_position_ids"
                ],
            },
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
