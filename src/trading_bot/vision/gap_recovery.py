"""gap_recovery — what a 1-minute feed can prove about a hole in the 5-minute lane.

``durable.reconcile_book`` refuses a resumed session when the bar after the committed
barrier is missing (:data:`UNVERIFIED_GAP`). The refusal is correct as far as it goes: a
protective stop could have been crossed inside the hole, and a replay that only sees the
bar after it cannot tell a quiet market from one that took the position out. But it is
also final. The lane is stuck even when an independent feed observed every minute of the
hole, which is exactly the evidence the bar grid lacks.

This module turns that feed into a verdict. It never rebuilds a bar: the missing 5-minute
candles stay missing, and no decision is taken on data that was synthesised. What it does
is answer three questions, in increasing order of what they claim:

1. **Was the window observed?** Every minute of ``[barrier + interval, resume)`` must be
   present, consecutive and unique for every symbol with exposure, from a feed that is not
   the replay's own bar source. A partial grid proves nothing, so it is not rounded up.
2. **Was a protective level crossed?** A minute's high/low *is* the set of prices the venue
   printed inside that minute. If neither the stop nor the take-profit falls inside any
   minute's range, no protective exit can have happened in the hole — that is an
   observation, not an assumption, and it is enough to resume with the exposure intact.
3. **If one was crossed, can the exit be placed?** Across minutes the order is a fact: the
   earlier minute's level went first. Inside one minute it is not: a 1-minute OHLC does not
   say whether the high or the low printed first, so a stop and a take-profit touched in
   the same minute is an **ambiguous** result, and ambiguity blocks. This module refuses to
   apply the broker's ``stop_first`` convention here: that convention is a modelling choice
   for a *live* bar, and a recovery may not silently book an outcome the account never
   observed.

The conservative bound is always published, even when the verdict is ``INTACT``: for a
position that was never touched, the worst and best prices the hole printed are what the
mark could have been. They are evidence for a reader, not inputs to the book.

Nothing here imports :mod:`trading_bot.vision.durable` or the broker: a verifier that
reused the code under test would be checking that the code agrees with itself. The stop and
take-profit formulas are written out again on purpose, and a test pins them to
``PaperPosition`` so a change in one without the other fails loudly.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from itertools import pairwise
from typing import Any, Protocol

MINUTE_MS = 60_000

#: What the recovery decided about one position.
INTACT = "INTACT"
RECONSTRUCTIBLE = "RECONSTRUCTIBLE"
AMBIGUOUS = "AMBIGUOUS"
UNCOVERED = "UNCOVERED"

#: What the recovery decided about the hole as a whole.
VERDICT_CLEAR = "CLEAR"
VERDICT_RECONSTRUCT = "RECONSTRUCT"
VERDICT_BLOCKED = "BLOCKED"


class MinuteFeed(Protocol):
    """The part of a 1-minute feed this module needs, and no more.

    Deliberately narrow: a feed that can only prove coverage (``QuoteFeed``) does not
    qualify, because coverage without ranges cannot answer question 2.
    """

    name: str

    def has(self, symbol: str) -> bool: ...

    def minute_bars_between(self, symbol: str, start_ms: int, end_ms: int) -> Sequence[Any]: ...

    def series_digest(self, symbol: str) -> str: ...


@dataclass(frozen=True, slots=True)
class GapWindow:
    """The missing span: bars after the barrier, up to (not including) the resume bar."""

    barrier_ms: int
    resume_ms: int
    interval_ms: int

    def __post_init__(self) -> None:
        if self.interval_ms <= 0:
            raise ValueError("interval_ms must be positive")
        if self.resume_ms <= self.barrier_ms + self.interval_ms:
            raise ValueError("the window is empty: the next bar is not missing")

    @property
    def start_ms(self) -> int:
        """First instant the committed book does not cover."""
        return int(self.barrier_ms) + int(self.interval_ms)

    @property
    def end_ms(self) -> int:
        """The resume bar's open: exclusive, because that bar is processed normally."""
        return int(self.resume_ms)

    @property
    def missing_bars(self) -> list[int]:
        return list(range(self.start_ms, self.end_ms, int(self.interval_ms)))

    @property
    def minutes_expected(self) -> int:
        return (self.end_ms - self.start_ms) // MINUTE_MS


@dataclass(frozen=True, slots=True)
class Touch:
    """One minute whose range contains a protective level."""

    minute_ms: int
    open: float
    high: float
    low: float
    close: float
    level_price: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "minute_ms": self.minute_ms,
            "open": self.open,
            "high": self.high,
            "low": self.low,
            "close": self.close,
            "level_price": self.level_price,
        }


@dataclass(frozen=True, slots=True)
class PositionVerdict:
    """The recovery's answer for one open position."""

    position_id: str
    symbol: str
    side: str
    entry_price: float
    quantity: float
    stop_price: float
    take_profit_price: float
    status: str
    minutes_observed: int = 0
    stop_touch: Touch | None = None
    take_profit_touch: Touch | None = None
    ambiguous_minute_ms: int | None = None
    worst_price: float | None = None
    best_price: float | None = None
    worst_unrealised_usdt: float | None = None
    detail: str = ""

    @property
    def first_touch(self) -> Touch | None:
        """The touch that happened first, or ``None`` when the order is not a fact.

        Across minutes the order is observed; inside one minute it is not, and such a case
        is never ``RECONSTRUCTIBLE``. Comparing instants here — rather than preferring the
        stop — is what keeps a take-profit that printed on an earlier minute from being
        reported as a loss.
        """
        touches = [item for item in (self.stop_touch, self.take_profit_touch) if item]
        if not touches:
            return None
        return min(touches, key=lambda item: item.minute_ms)

    @property
    def exit_minute_ms(self) -> int | None:
        if self.status != RECONSTRUCTIBLE:
            return None
        touch = self.first_touch
        return None if touch is None else touch.minute_ms

    @property
    def exit_reason(self) -> str | None:
        if self.status != RECONSTRUCTIBLE:
            return None
        touch = self.first_touch
        if touch is None:
            return None
        return "stop_loss" if touch is self.stop_touch else "take_profit"

    @property
    def exit_price(self) -> float | None:
        if self.status != RECONSTRUCTIBLE:
            return None
        touch = self.first_touch
        return None if touch is None else touch.level_price

    def to_dict(self) -> dict[str, Any]:
        return {
            "position_id": self.position_id,
            "symbol": self.symbol,
            "side": self.side,
            "entry_price": self.entry_price,
            "quantity": self.quantity,
            "stop_price": self.stop_price,
            "take_profit_price": self.take_profit_price,
            "status": self.status,
            "minutes_observed": self.minutes_observed,
            "stop_touch": None if self.stop_touch is None else self.stop_touch.to_dict(),
            "take_profit_touch": None
            if self.take_profit_touch is None
            else self.take_profit_touch.to_dict(),
            "ambiguous_minute_ms": self.ambiguous_minute_ms,
            "exit_reason": self.exit_reason,
            "exit_minute_ms": self.exit_minute_ms,
            "exit_price": self.exit_price,
            "worst_price": self.worst_price,
            "best_price": self.best_price,
            "worst_unrealised_usdt": self.worst_unrealised_usdt,
            "detail": self.detail,
        }


@dataclass(frozen=True, slots=True)
class GapAssessment:
    """One verdict for one hole, with the evidence it was reached on."""

    window: GapWindow
    verdict: str
    code: str | None
    detail: str
    checks: tuple[dict[str, Any], ...] = ()
    positions: tuple[PositionVerdict, ...] = ()
    feed: str = ""
    evidence: dict[str, Any] = field(default_factory=dict)
    minutes: tuple[dict[str, Any], ...] = ()

    @property
    def ok(self) -> bool:
        return self.verdict in {VERDICT_CLEAR, VERDICT_RECONSTRUCT}

    @property
    def exits(self) -> list[PositionVerdict]:
        return [item for item in self.positions if item.status == RECONSTRUCTIBLE]

    def to_dict(self) -> dict[str, Any]:
        return {
            "verdict": self.verdict,
            "code": self.code,
            "detail": self.detail,
            "feed": self.feed,
            "window": {
                "barrier_ms": self.window.barrier_ms,
                "start_ms": self.window.start_ms,
                "end_ms": self.window.end_ms,
                "resume_ms": self.window.resume_ms,
                "interval_ms": self.window.interval_ms,
                "missing_bars": self.window.missing_bars,
                "minutes_expected": self.window.minutes_expected,
            },
            "evidence": dict(self.evidence),
            "positions": [item.to_dict() for item in self.positions],
            #: La tabla de minutos viaja con el veredicto: sin ella, un verificador sólo
            #: puede creer el resultado, no recomputar el toque que lo justifica.
            "minutes": [dict(minute) for minute in self.minutes],
            "checks": [dict(check) for check in self.checks],
        }


def stop_price(side: str, entry_price: float, stop_loss_pct: float) -> float:
    """The broker's stop, restated here so a verifier does not import the broker."""
    if side == "buy":
        return float(entry_price) * (1.0 - float(stop_loss_pct) / 100.0)
    return float(entry_price) * (1.0 + float(stop_loss_pct) / 100.0)


def take_profit_price(side: str, entry_price: float, take_profit_pct: float) -> float:
    if side == "buy":
        return float(entry_price) * (1.0 + float(take_profit_pct) / 100.0)
    return float(entry_price) * (1.0 - float(take_profit_pct) / 100.0)


def _record(
    checks: list[dict[str, Any]],
    name: str,
    ok: bool,
    detail: str = "",
    fail_detail: str = "",
) -> bool:
    checks.append({"check": name, "ok": bool(ok), "detail": detail if ok else (fail_detail or detail)})
    return bool(ok)


def _minute_digest(bars: Sequence[Any]) -> str:
    import hashlib
    import json

    payload = json.dumps(
        [
            [
                int(bar.ts_ms),
                float(bar.open),
                float(bar.high),
                float(bar.low),
                float(bar.close),
                float(bar.volume),
            ]
            for bar in bars
        ],
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def assess_gap(
    *,
    window: GapWindow,
    positions: Sequence[Mapping[str, Any]],
    feed: MinuteFeed | None,
    pending: Mapping[str, Any] | None = None,
    max_opinion_age_ms: int | None = None,
) -> GapAssessment:
    """Decide whether the hole can be crossed, and on what evidence.

    ``positions`` are the durable rows (``PaperPosition.to_row()``): they carry the entry,
    the percentages and the identity, which is everything the levels need. ``pending`` is
    the book's in-flight orders: an opinion that could still have filled inside the hole
    makes the exposure itself unknowable, so it blocks — the minute grid can price the
    fill but not the position that would have existed after it.
    """
    checks: list[dict[str, Any]] = []
    #: Keyed by symbol *and* minute. A minute belongs to one instrument: judging a SOL
    #: position against ETH's range would be a fabricated observation, so the rows are kept
    #: apart and the published list names its symbol.
    minutes_by_symbol: dict[str, list[dict[str, Any]]] = {}
    minutes_used: dict[tuple[str, int], dict[str, Any]] = {}
    evidence: dict[str, Any] = {
        "barrier_ms": window.barrier_ms,
        "resume_ms": window.resume_ms,
        "minutes_expected": window.minutes_expected,
        "symbols": {},
    }

    if feed is None:
        _record(checks, "feed_present", False, "", "no 1-minute feed was supplied")
        return GapAssessment(
            window=window,
            verdict=VERDICT_BLOCKED,
            code="GAP_NOT_COVERED",
            detail=(
                "the hole cannot be crossed: no independent 1-minute feed was supplied, so "
                "nothing observed the minutes between the committed bar and the next one"
            ),
            checks=tuple(checks),
            evidence=evidence,
        )
    _record(checks, "feed_present", True, f"feed {feed.name!r} supplied")

    #: A feed built from the bars being replayed would prove its own hole was a hole.
    independent = str(getattr(feed, "name", "")) not in {"", "bar_open"}
    if not _record(
        checks,
        "feed_is_independent",
        independent,
        f"the feed names itself {getattr(feed, 'name', None)!r}",
        "the feed is the replay's own bar source, so its coverage proves nothing",
    ):
        return GapAssessment(
            window=window,
            verdict=VERDICT_BLOCKED,
            code="GAP_FEED_NOT_INDEPENDENT",
            detail=(
                "the only feed available is the bar source being replayed; a hole cannot be "
                "proven covered by the data that has the hole"
            ),
            checks=tuple(checks),
            evidence=evidence,
        )

    symbols = sorted({str(row.get("symbol", "")) for row in positions})
    evidence["symbols"] = {symbol: {} for symbol in symbols}
    missing: list[str] = []
    for symbol in symbols:
        if not feed.has(symbol):
            missing.append(f"{symbol} is not in {feed.name}")
            continue
        bars = list(feed.minute_bars_between(symbol, window.start_ms, window.end_ms))
        observed = len(bars)
        expected = window.minutes_expected
        if observed != expected:
            stamps = {int(bar.ts_ms) for bar in bars}
            absent = [
                window.start_ms + index * MINUTE_MS
                for index in range(expected)
                if window.start_ms + index * MINUTE_MS not in stamps
            ]
            missing.append(
                f"{symbol}: {observed}/{expected} minutes observed in the hole "
                f"({len(absent)} missing, first {absent[0] if absent else '-'})"
            )
            evidence["symbols"][symbol] = {
                "minutes_observed": observed,
                "minutes_expected": expected,
                "missing_minutes": absent,
            }
            continue
        steps_ok = all(
            int(right.ts_ms) - int(left.ts_ms) == MINUTE_MS
            for left, right in pairwise(bars)
        )
        if not steps_ok:
            missing.append(f"{symbol}: the observed minutes are not consecutive")
        last_ok = int(bars[-1].ts_ms) == window.end_ms - MINUTE_MS
        if not last_ok:
            missing.append(
                f"{symbol}: the last observed minute is {int(bars[-1].ts_ms)}, not "
                f"{window.end_ms - MINUTE_MS}; the grid stops before the resume bar"
            )
        evidence["symbols"][symbol] = {
            "minutes_observed": observed,
            "minutes_expected": expected,
            "first_minute_ms": int(bars[0].ts_ms),
            "last_minute_ms": int(bars[-1].ts_ms),
            "window_sha256": _minute_digest(bars),
            "feed": feed.name,
            "series_sha256": feed.series_digest(symbol),
        }
        minutes_by_symbol[symbol] = [
            {
                "symbol": symbol,
                "ts_ms": int(bar.ts_ms),
                "open": float(bar.open),
                "high": float(bar.high),
                "low": float(bar.low),
                "close": float(bar.close),
            }
            for bar in bars
        ]
        for minute in minutes_by_symbol[symbol]:
            minutes_used[(symbol, int(minute["ts_ms"]))] = minute

    if not _record(
        checks,
        "minute_grid_complete",
        not missing,
        f"every minute of the hole is present for {', '.join(symbols) or 'no symbol'}",
        "; ".join(missing),
    ):
        return GapAssessment(
            window=window,
            verdict=VERDICT_BLOCKED,
            code="GAP_NOT_COVERED",
            detail=(
                "the 1-minute feed does not cover the hole completely: "
                + "; ".join(missing)
            ),
            checks=tuple(checks),
            positions=tuple(
                PositionVerdict(
                    position_id=str(row.get("position_id", "")),
                    symbol=str(row.get("symbol", "")),
                    side=str(row.get("side", "")),
                    entry_price=float(row.get("entry_price", 0.0)),
                    quantity=float(row.get("quantity", 0.0)),
                    stop_price=stop_price(
                        str(row.get("side")), float(row.get("entry_price", 0.0)),
                        float(row.get("stop_loss_pct", 0.0)),
                    ),
                    take_profit_price=take_profit_price(
                        str(row.get("side")), float(row.get("entry_price", 0.0)),
                        float(row.get("take_profit_pct", 0.0)),
                    ),
                    status=UNCOVERED,
                    detail="coverage failed before this position could be judged",
                )
                for row in positions
            ),
            feed=str(feed.name),
            evidence=evidence,
        )

    #: An opinion that could still have filled inside the hole changes what was held, not
    #: just at what price. The minutes can price a fill; they cannot say which position the
    #: opinion would have opened, so the exposure after the hole would be a guess.
    risky_pending: list[str] = []
    age = None if max_opinion_age_ms is None else int(max_opinion_age_ms)
    for symbol, row in sorted((pending or {}).items()):
        received = int(dict(row).get("received_at_ms") or 0)
        if age is not None and received + age <= window.start_ms:
            continue
        risky_pending.append(f"{symbol} (received {received})")
    if not _record(
        checks,
        "no_opinion_spans_the_hole",
        not risky_pending,
        "no in-flight opinion could have filled inside the hole",
        "in-flight opinion(s) could have filled inside the hole: " + ", ".join(risky_pending),
    ):
        return GapAssessment(
            window=window,
            verdict=VERDICT_BLOCKED,
            code="GAP_PENDING_OPINION",
            detail=(
                "an opinion was still executable when the data stopped: the fill it would "
                "have produced inside the hole, and the position that would have existed "
                "after it, cannot be reconstructed from minutes alone without inventing "
                "the entry the account never observed"
            ),
            checks=tuple(checks),
            positions=tuple(
                PositionVerdict(
                    position_id=str(row.get("position_id", "")),
                    symbol=str(row.get("symbol", "")),
                    side=str(row.get("side", "")),
                    entry_price=float(row.get("entry_price", 0.0)),
                    quantity=float(row.get("quantity", 0.0)),
                    stop_price=stop_price(
                        str(row.get("side")), float(row.get("entry_price", 0.0)),
                        float(row.get("stop_loss_pct", 0.0)),
                    ),
                    take_profit_price=take_profit_price(
                        str(row.get("side")), float(row.get("entry_price", 0.0)),
                        float(row.get("take_profit_pct", 0.0)),
                    ),
                    status=UNCOVERED,
                    detail="an in-flight opinion spans the hole",
                )
                for row in positions
            ),
            feed=str(feed.name),
            evidence=evidence,
        )

    verdicts: list[PositionVerdict] = []
    ambiguous: list[str] = []
    for row in positions:
        symbol = str(row.get("symbol", ""))
        side = str(row.get("side", ""))
        entry = float(row.get("entry_price", 0.0))
        quantity = float(row.get("quantity", 0.0))
        stop = stop_price(side, entry, float(row.get("stop_loss_pct", 0.0)))
        take = take_profit_price(side, entry, float(row.get("take_profit_pct", 0.0)))
        #: Only this symbol's minutes: see the note where they are collected.
        bars = minutes_by_symbol.get(symbol, [])

        stop_touch: Touch | None = None
        take_touch: Touch | None = None
        worst: float | None = None
        best: float | None = None
        for bar in bars:
            high = float(bar["high"])
            low = float(bar["low"])
            if side == "buy":
                worst = low if worst is None else min(worst, low)
                best = high if best is None else max(best, high)
                hit_stop = low <= stop
                hit_take = high >= take
            else:
                worst = high if worst is None else max(worst, high)
                best = low if best is None else min(best, low)
                hit_stop = high >= stop
                hit_take = low <= take
            if hit_stop and stop_touch is None:
                stop_touch = Touch(
                    minute_ms=int(bar["ts_ms"]),
                    open=float(bar["open"]),
                    high=high,
                    low=low,
                    close=float(bar["close"]),
                    level_price=stop,
                )
            if hit_take and take_touch is None:
                take_touch = Touch(
                    minute_ms=int(bar["ts_ms"]),
                    open=float(bar["open"]),
                    high=high,
                    low=low,
                    close=float(bar["close"]),
                    level_price=take,
                )

        worst_unrealised = None
        if worst is not None:
            worst_unrealised = (
                (worst - entry) * quantity if side == "buy" else (entry - worst) * quantity
            )

        if stop_touch is None and take_touch is None:
            status = INTACT
            detail = (
                "neither the stop nor the take-profit falls inside any observed minute: no "
                "protective exit can have happened"
            )
        elif (
            stop_touch is not None
            and take_touch is not None
            and stop_touch.minute_ms == take_touch.minute_ms
        ):
            status = AMBIGUOUS
            detail = (
                f"stop and take-profit are both inside the range of minute "
                f"{stop_touch.minute_ms}; a 1-minute OHLC does not say which printed first, "
                "so the exit and its sign are unknown"
            )
            ambiguous.append(str(row.get("position_id", "")))
        else:
            status = RECONSTRUCTIBLE
            first = min(
                (item for item in (stop_touch, take_touch) if item is not None),
                key=lambda item: item.minute_ms,
            )
            detail = (
                f"the {'stop' if first is stop_touch else 'take-profit'} was crossed in "
                f"minute {first.minute_ms}, which is an observed price, not an inferred one"
            )

        verdicts.append(
            PositionVerdict(
                position_id=str(row.get("position_id", "")),
                symbol=symbol,
                side=side,
                entry_price=entry,
                quantity=quantity,
                stop_price=stop,
                take_profit_price=take,
                status=status,
                minutes_observed=len(bars),
                stop_touch=stop_touch,
                take_profit_touch=take_touch,
                ambiguous_minute_ms=(
                    stop_touch.minute_ms
                    if status == AMBIGUOUS and stop_touch is not None
                    else None
                ),
                worst_price=worst,
                best_price=best,
                worst_unrealised_usdt=worst_unrealised,
                detail=detail,
            )
        )

    if ambiguous:
        return GapAssessment(
            window=window,
            verdict=VERDICT_BLOCKED,
            code="GAP_EXIT_AMBIGUOUS",
            detail=(
                "stop and take-profit were both crossed inside one minute for "
                + ", ".join(ambiguous)
                + "; the order inside that minute is not observable, so the PnL is a range "
                "and not a number this book may publish"
            ),
            checks=tuple(checks),
            positions=tuple(verdicts),
            feed=str(feed.name),
            evidence=evidence,
            minutes=tuple(minutes_used[key] for key in sorted(minutes_used)),
        )

    exits = [item for item in verdicts if item.status == RECONSTRUCTIBLE]
    _record(
        checks,
        "protective_exits_placed",
        True,
        f"{len(exits)} exit(s) placeable, {len(verdicts) - len(exits)} position(s) never "
        "touched a level",
    )
    if exits:
        return GapAssessment(
            window=window,
            verdict=VERDICT_RECONSTRUCT,
            code=None,
            detail=(
                f"{len(exits)} protective exit(s) were crossed inside the hole and are "
                f"placed at their observed minute by {feed.name}; the remaining "
                f"{len(verdicts) - len(exits)} position(s) were provably untouched"
            ),
            checks=tuple(checks),
            positions=tuple(verdicts),
            feed=str(feed.name),
            evidence=evidence,
            minutes=tuple(minutes_used[key] for key in sorted(minutes_used)),
        )

    if not verdicts:
        #: No exposure and no in-flight opinion: nothing could have produced an economic
        #: event inside the hole, so coverage is not owed. It is still recorded as absent
        #: rather than implied, because "no position" is the reason, not "a quiet market".
        _record(
            checks,
            "exposure_present",
            True,
            "no open position and no in-flight opinion: no economic event could occur",
        )

    return GapAssessment(
        window=window,
        verdict=VERDICT_CLEAR,
        code=None,
        detail=(
            f"every minute of the hole was observed by {feed.name} and no protective level "
            f"was crossed for {len(verdicts)} open position(s)"
            if verdicts
            else f"every minute of the hole was observed by {feed.name}; no position is open"
        ),
        checks=tuple(checks),
        positions=tuple(verdicts),
        feed=str(feed.name),
        evidence=evidence,
        minutes=tuple(minutes_used[key] for key in sorted(minutes_used)),
    )
