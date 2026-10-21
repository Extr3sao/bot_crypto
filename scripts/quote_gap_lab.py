#!/usr/bin/env python
"""quote_gap_lab — experiments for WP-PAPER-QUOTE-GAP-002.

Every scenario here is a *controlled* market: a 1-minute series is defined first and the
5-minute bars are its exact aggregation, so the arm that never lost a bar and the arm that
did can be compared without arguing about which dataset is the truth. The lane, the broker
and the risk engine are the production ones; the provider is a script, so no model is
called and no network is used.

The scenarios, and what each one is allowed to claim:

===========  ==================================================================
``split``    uninterrupted kill: A/B must agree on the whole economic state.
``quiet``    a bar is missing, its minutes are observed and nothing was touched:
             the resume must leave the book untouched and match A.
``stop``     the minutes prove the stop traded inside the missing bar: the resume
             must close at the same price A paid, at the minute that proves it.
``take``     the same for a take-profit.
``both``     stop and take-profit inside one minute: the resume must refuse,
             because the order is unobservable. A is reported for contrast only:
             it applied the broker's ``stop_first`` convention to a bar, which a
             recovery may not do to a minute.
``partial``  one minute of the hole is absent: refuse, do not round up.
``corrupt``  duplicated minutes: the feed refuses to load them at all.
``pending``  an opinion still executable when the data stopped: refuse.
===========  ==================================================================

Two more experiments do not need a scenario:

``kill-save``     a child is killed at a random instant while writing the book; the
                  next open must find a readable book every time.
``kill-resume``   a child is killed at a random instant while resuming across the hole;
                  the surviving state must converge to A, never to a double close and
                  never to a lost position.

Usage::

    python scripts/quote_gap_lab.py run --out reports/ai-bots/WP-PAPER-QUOTE-GAP-002/lab
    python scripts/quote_gap_lab.py child --state DIR --ledger FILE --bars holed \
        --feed stop --from-bar 31
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from trading_bot.config.settings import load_settings  # noqa: E402
from trading_bot.research.economic_recovery.experiments import Bar  # noqa: E402
from trading_bot.vision.durable import (  # noqa: E402
    LaneBookStore,
    RecoveryBlocked,
    SessionBusy,
)
from trading_bot.vision.lane import VisionLane  # noqa: E402
from trading_bot.vision.ledger import read_entries  # noqa: E402
from trading_bot.vision.provider import ReplayProvider, VisionResponse  # noqa: E402
from trading_bot.vision.quotes import (  # noqa: E402
    MINUTE_MS,
    MinuteBarQuoteFeed,
    MinuteSeries,
    QuoteFeedIntegrityError,
)
from trading_bot.vision.settings import load_vision_config  # noqa: E402

BAR_MS = 300_000
BARS = 48
OPEN_BAR = 29  #: la posición se abre en la apertura de esta vela
#: La primera sesión termina en la vela **inmediatamente anterior** al hueco: el hueco a
#: recuperar tiene que empezar en la barrera, no después de ella (si la vela siguiente
#: existe, la sesión la procesa y la barrera avanza; entonces el hueco ya no es de la
#: recuperación, y este WP no cambia lo que el bucle de velas hace con él).
SPLIT_BAR = 31
HOLE_BAR = 32  #: la vela que falta en el brazo con hueco
#: El minuto *dentro* de la vela del hueco que prueba el cruce. ``offset`` es 0..4: es la
#: posición dentro de los cinco minutos que forman la vela, no el índice global.
STOP_OFFSET = 2
T0 = 1_792_500_000_000 - (1_792_500_000_000 % BAR_MS)
SYMBOL = "BTC/USDT"
BOOK = "quote-gap-lab"
EQUITY = 10_000.0
PROVIDER_CALLS = 2


# -- the controlled market ------------------------------------------------------


def _minute_row(stamp: int, *, low: float, high: float, close: float) -> list[float]:
    return [stamp, 100.0, high, low, close, 5.0]


def minutes_for(scenario: str) -> list[list[float]]:
    """The complete 1-minute truth for one scenario.

    The 5-minute bars are always aggregated from *this* series, even in the scenarios whose
    feed is damaged: a damaged feed is a statement about what the recovery was given, not a
    licence to move the bars the continuous arm traded on.
    """

    minutes: list[list[float]] = []
    for minute in range(BARS * 5):
        bar = minute // 5
        offset = minute % 5
        rows_kwargs = {"low": 99.98, "high": 100.02, "close": 100.0}
        if bar == HOLE_BAR and offset == STOP_OFFSET:
            if scenario in {"stop", "both"}:
                rows_kwargs["low"] = 99.2
                rows_kwargs["close"] = 99.4
            if scenario in {"take", "both"}:
                rows_kwargs["high"] = 101.1
                rows_kwargs["close"] = 101.0
        minutes.append(_minute_row(T0 + minute * MINUTE_MS, **rows_kwargs))  # type: ignore[arg-type]
    return minutes


def feed_minutes(scenario: str) -> list[list[float]]:
    """The minutes the recovery is *given*: complete, partial or corrupt."""

    minutes = minutes_for(scenario)
    if scenario == "partial":
        drop = (HOLE_BAR * 5 + STOP_OFFSET) * MINUTE_MS + T0
        kept = [row for row in minutes if int(row[0]) != drop]
        if len(kept) != len(minutes) - 1:  # pragma: no cover - defensive
            raise SystemExit("the partial scenario failed to remove its minute")
        return kept
    if scenario == "corrupt":
        target = (HOLE_BAR * 5 + STOP_OFFSET) * MINUTE_MS + T0
        duplicated: list[list[float]] = []
        for row in minutes:
            duplicated.append(row)
            if int(row[0]) == target:
                duplicated.append(list(row))
        return duplicated
    return minutes


def bars_from_minutes(minutes: list[list[float]]) -> list[Bar]:
    """Exact 5-minute aggregation: same open, max high, min low, last close.

    Grouped by the bar the timestamp belongs to, never by position in the list: a minute
    that is missing from the feed would otherwise shift every later bar by one slot, and
    the arms would be compared on two different markets.
    """

    buckets: dict[int, list[list[float]]] = {}
    for row in minutes:
        stamp = int(row[0])
        buckets.setdefault(stamp - stamp % BAR_MS, []).append(row)
    out: list[Bar] = []
    for bucket in sorted(buckets):
        chunk = sorted(buckets[bucket], key=lambda row: int(row[0]))
        if len(chunk) != 5:  # pragma: no cover - a complete source always has five
            raise SystemExit(f"bar {bucket} has {len(chunk)} minutes, not five")
        out.append(
            Bar(
                ts_ms=bucket,
                open=float(chunk[0][1]),
                high=max(float(row[2]) for row in chunk),
                low=min(float(row[3]) for row in chunk),
                close=float(chunk[-1][4]),
                volume=sum(float(row[5]) for row in chunk),
            )
        )
    return out


def feed_for(minutes: list[list[float]]) -> MinuteBarQuoteFeed:
    rows = [[int(row[0]), *[float(value) for value in row[1:]]] for row in minutes]
    return MinuteBarQuoteFeed({SYMBOL: MinuteSeries.from_rows(SYMBOL, rows)})


# -- the lane -------------------------------------------------------------------


class ScriptedProvider(ReplayProvider):
    """One answer per *bar*, keyed by the decision instant rather than by call order.

    Keying on the call index would make the script depend on how many bars the process was
    handed: a resumed session starts calling later than a continuous one, so the same index
    would name a different bar in each arm. The decision instant travels in the request, so
    both arms see the same script at the same bar.
    """

    def __init__(self, long_at: int | None) -> None:
        self.long_at = long_at
        self.seen = 0
        super().__init__(self._script)

    def _script(self, request) -> str:  # type: ignore[no-untyped-def]
        bar_open = int(request.decision_ts_ms) - BAR_MS
        bar_index = (bar_open - T0) // BAR_MS
        action = "LONG" if self.long_at is not None and bar_index == self.long_at else "NO_TRADE"
        stop = 0.5 if action not in {"NO_TRADE", "CLOSE"} else None
        take = 0.75 if action not in {"NO_TRADE", "CLOSE"} else None
        return (
            f'{{"schema_version":"ai-vision-decision/1","symbol":"{request.chart.symbol}",'
            f'"action":"{action}","confidence":0.6,"horizon_bars":6,'
            f'"stop_loss_pct":{stop},"take_profit_pct":{take},'
            '"invalidation":null,"rationale":"Lab."}'
        )

    def analyze(self, request) -> VisionResponse:  # type: ignore[override]
        response = super().analyze(request)
        self.seen += 1
        return replace(response, latency_ms=0)


def _config():
    base = load_vision_config(env={})
    return base.__class__(
        provider=base.provider,
        lane=base.lane.__class__(
            timeframe="5m",
            window_bars=20,
            decision_every_bars=1,
            max_calls_per_run=BARS + 2,
            max_estimated_spend_usd=5.0,
            data_delay_ms=0,
        ),
    )


def _policy():
    return load_settings(config_dir=REPO / "config", env_file=None).risk


def run_lane(
    bars: list[Bar],
    ledger: Path,
    *,
    store: LaneBookStore | None = None,
    book=None,  # type: ignore[no-untyped-def]
    session_id: str = "s1",
    quote_feed=None,  # type: ignore[no-untyped-def]
):
    lane = VisionLane(
        series={SYMBOL: list(bars)},
        #: La opinión se forma en el cierre de la vela anterior a la apertura.
        provider=ScriptedProvider(OPEN_BAR - 1),
        config=_config(),
        risk_policy=_policy(),
        ledger_path=ledger,
        equity=EQUITY,
        book_id=BOOK,
        decision_every_bars=1,
        book_store=store,
        book=book,
        session_id=session_id,
        quote_feed=quote_feed,
    )
    summary = lane.run()
    return lane, summary, [row["entry"] for row in read_entries(ledger)]


# -- arms -----------------------------------------------------------------------


@dataclass
class Arm:
    name: str
    status: str
    detail: str
    summary: dict[str, Any] | None = None
    rows: list[dict[str, Any]] | None = None
    book: dict[str, Any] | None = None
    recovery: dict[str, Any] | None = None
    code: str | None = None

    def to_dict(self) -> dict[str, Any]:
        closes = [row for row in (self.rows or []) if row.get("kind") == "CLOSE"]
        fills = [row for row in (self.rows or []) if row.get("kind") == "FILL"]
        return {
            "name": self.name,
            "status": self.status,
            "detail": self.detail,
            "code": self.code,
            "summary": {
                key: (self.summary or {}).get(key)
                for key in (
                    "fills",
                    "closed_trades",
                    "net_realised_usdt",
                    "final_equity_usdt",
                    "open_positions_at_end",
                    "open_gap_exits",
                )
            }
            if self.summary
            else None,
            "closes": closes,
            "fills": fills,
            "book": self.book,
            "recovery": self.recovery,
        }


def _book_view(store: LaneBookStore) -> dict[str, Any] | None:
    book = store.load()
    if book is None:
        return None
    return {
        "state_digest": book.state_digest,
        "integrity_digest": book.digest,
        "barrier_ms": book.barrier_ms,
        "open_positions": [
            {
                "position_id": row["position_id"],
                "symbol": row["symbol"],
                "side": row["side"],
                "entry_price": row["entry_price"],
                "quantity": row["quantity"],
                #: Los porcentajes viajan para que un verificador derive las barreras con
                #: aritmética propia en vez de leer el precio de salida del cierre.
                "stop_loss_pct": row["stop_loss_pct"],
                "take_profit_pct": row["take_profit_pct"],
            }
            for row in book.open_positions
        ],
        "closed_trades": book.closed_trades,
        "equity": book.body["broker"]["equity"],
        "marked_equity": book.body.get("marked_equity"),
    }


def _arm(
    name: str,
    bars: list[Bar],
    directory: Path,
    *,
    store: LaneBookStore | None = None,
    book=None,  # type: ignore[no-untyped-def]
    session: str = "s1",
    feed=None,  # type: ignore[no-untyped-def]
) -> Arm:
    directory.mkdir(parents=True, exist_ok=True)
    ledger = directory / f"{name}.jsonl"
    try:
        _lane, summary, rows = run_lane(
            bars, ledger, store=store, book=book, session_id=session, quote_feed=feed
        )
    except RecoveryBlocked as exc:
        report = exc.report
        return Arm(
            name=name,
            status="BLOCKED",
            detail=report.detail,
            code=report.code,
            recovery=report.to_dict(),
            book=_book_view(store) if store is not None else None,
        )
    return Arm(
        name=name,
        status="RAN",
        detail=str(summary.get("session", {}).get("recovery", {}).get("status")),
        summary=summary,
        rows=rows,
        book=_book_view(store) if store is not None else None,
        recovery=(summary.get("session") or {}).get("recovery"),
    )


def _split_scenario(tmp: Path, bars: list[Bar], *, hole: bool, minutes: list[list[float]] | None):
    """Sesión 1 hasta la barrera, sesión 2 desde ahí (con o sin la vela del hueco)."""

    state = LaneBookStore(tmp / "state")
    lock = state.lock(session_id="s1")
    try:
        first = _arm(
            "s1",
            bars[: SPLIT_BAR + 1],
            tmp,
            store=state,
            session="s1",
        )
    finally:
        lock.release()
    if first.status != "RAN":  # pragma: no cover - the first session has no hole
        raise SystemExit(f"the first session did not run: {first.detail}")

    resumed = list(bars[: SPLIT_BAR + 1]) + [
        bar for bar in bars[SPLIT_BAR + 1 :] if not (hole and int(bar.ts_ms) == T0 + HOLE_BAR * BAR_MS)
    ]
    feed = None
    if hole and minutes is not None:
        feed = feed_for(minutes)
    book = state.load()
    lock = state.lock(session_id="s2")
    try:
        second = _arm(
            "s2",
            resumed,
            tmp,
            store=state,
            book=book,
            session="s2",
            feed=feed,
        )
    finally:
        lock.release()
    gap = None
    if second.recovery:
        gap = second.recovery.get("gap")
        second.recovery = {
            "status": second.recovery.get("status"),
            "code": second.recovery.get("code"),
            "resume_from_ms": second.recovery.get("resume_from_ms"),
            "checks": second.recovery.get("checks"),
            "gap": None
            if gap is None
            else {
                "verdict": gap.get("verdict"),
                "code": gap.get("code"),
                "detail": gap.get("detail"),
                "feed": gap.get("feed"),
                #: Las ventanas y los OHLC viajan con el veredicto: un verificador que sólo
                #: tuviera el resultado no podría recomputar el toque que lo justifica.
                "window": gap.get("window"),
                "positions": gap.get("positions"),
                "minutes": gap.get("minutes"),
                "evidence": gap.get("evidence"),
                "checks": gap.get("checks"),
            },
            "reconstruction": second.recovery.get("reconstruction"),
        }
    return first, second


COMPARE_FIELDS = (
    "symbol",
    "side",
    "entry_price",
    "exit_price",
    "quantity",
    "pnl_net_usdt",
    "gross_pnl_usdt",
    "reference_gross_pnl_usdt",
    "execution_cost_usdt",
    "entry_commission_usdt",
    "exit_commission_usdt",
    "commissions_usdt",
    "exit_reason",
    "position_id",
)


def _closes(arm: Arm) -> list[dict[str, Any]]:
    return [row for row in (arm.rows or []) if row.get("kind") == "CLOSE"]


def compare_economics(a: Arm, b: Arm, *, tolerance: float = 1e-6) -> dict[str, Any]:
    """Field by field on the money, not on a digest that also hashes timestamps."""

    closes_a, closes_b = _closes(a), _closes(b)
    differences: list[dict[str, Any]] = []
    if len(closes_a) != len(closes_b):
        differences.append(
            {"field": "closes", "a": len(closes_a), "b": len(closes_b)}
        )
    for index, (left, right) in enumerate(zip(closes_a, closes_b, strict=False)):
        for field in COMPARE_FIELDS:
            lvalue, rvalue = left.get(field), right.get(field)
            if isinstance(lvalue, (int, float)) and isinstance(rvalue, (int, float)):
                if abs(float(lvalue) - float(rvalue)) > tolerance:
                    differences.append(
                        {"close": index, "field": field, "a": lvalue, "b": rvalue}
                    )
            elif lvalue != rvalue:
                differences.append({"close": index, "field": field, "a": lvalue, "b": rvalue})
    return {
        "closes_a": len(closes_a),
        "closes_b": len(closes_b),
        "fields": list(COMPARE_FIELDS),
        "differences": differences,
        "ok": not differences,
    }


#: Paths that may differ between a continuous book and one that resumed across a hole,
#: each with the reason. Everything not listed here has to be identical, and the walk
#: reports every path it found different, not just the first one.
BOOK_EXEMPT: dict[str, str] = {
    "barrier/bars_committed": (
        "the holed arm never had that bar, so it never committed it"
    ),
    "closed_digest": (
        "it hashes the closed rows including closed_at, which the reconstruction observes "
        "at the minute instead of at the bar"
    ),
    "risk/last_loss_ms": "derived from the exit instant",
    #: Los dos digests cubren rutas que este mismo comparador declara distintas; si se
    #: compararan como valores, la exención no serviría de nada.
    "state_digest": "digest over the body, including the paths exempted here",
    "integrity_digest": "digest over the body, including the paths exempted here",
    "session_id": "process lineage",
    "session_index": "process lineage",
    "session_ids": "process lineage",
}
BOOK_EXEMPT_PREFIXES: dict[str, str] = {
    "contract/dataset": (
        "the holed dataset has one fewer bar under the barrier; the check that matters at "
        "the barrier the book was written at is `dataset_prefix_matches` in the report"
    ),
    "session": "process lineage: session_id / session_index / session_ids",
    "counters": "per-process action counters, excluded from the economic digest",
    "calls": "provider calls made by this process",
    "spend_usd": "provider spend of this process",
    "marks": "mark cache; the next bar rewrites it",
    "entry_provenance": "per-position notes, excluded from the economic digest",
    "pending": "orders in flight, excluded from the economic digest",
    "stop_reason": "process stop condition",
    "closed_trades[0]/closed_at": (
        "the reconstruction knows the minute; the continuous arm knows the bar close"
    ),
}


def compare_books(
    left: dict[str, Any] | None, right: dict[str, Any] | None
) -> dict[str, Any]:
    """Field by field over the whole book body, with the holes named out loud."""

    differences: list[dict[str, Any]] = []

    def walk(a: Any, b: Any, path: str) -> None:
        if path in BOOK_EXEMPT:
            return
        for prefix in BOOK_EXEMPT_PREFIXES:
            if path == prefix or path.startswith(prefix + "/") or path.startswith(prefix + "["):
                return
        if isinstance(a, dict) and isinstance(b, dict):
            for key in sorted(set(a) | set(b)):
                child = f"{path}/{key}" if path else key
                if key not in a or key not in b:
                    differences.append({"path": child, "a": a.get(key), "b": b.get(key)})
                else:
                    walk(a[key], b[key], child)
            return
        if isinstance(a, list) and isinstance(b, list):
            if len(a) != len(b):
                differences.append({"path": path, "a": len(a), "b": len(b)})
                return
            for index, (x, y) in enumerate(zip(a, b, strict=False)):
                walk(x, y, f"{path}[{index}]")
            return
        if isinstance(a, float) or isinstance(b, float):
            try:
                if abs(float(a) - float(b)) <= 1e-9:
                    return
            except (TypeError, ValueError):
                pass
        if a != b:
            differences.append({"path": path, "a": a, "b": b})

    if left is None or right is None:
        return {"ok": False, "differences": [{"path": "book", "a": left is None, "b": right is None}]}
    walk(left, right, "")
    return {
        "ok": not differences,
        "differences": differences,
        "exempt": BOOK_EXEMPT,
        "exempt_prefixes": BOOK_EXEMPT_PREFIXES,
    }


def _scenario(tmp: Path, name: str, *, hole: bool, minutes: list[list[float]] | None) -> dict[str, Any]:
    truth = minutes if minutes is not None else minutes_for("quiet")
    bars = bars_from_minutes(minutes_for(name) if name in {"partial", "corrupt"} else truth)
    root = tmp / name
    root.mkdir(parents=True, exist_ok=True)

    full_store = LaneBookStore(root / "A")
    lock = full_store.lock(session_id="A")
    try:
        arm_a = _arm("A", bars, root, store=full_store, session="A")
    finally:
        lock.release()

    given = minutes if minutes is not None else minutes_for(name)
    first, second = _split_scenario(root / "B", bars, hole=hole, minutes=given if hole else None)
    comparison = (
        compare_economics(arm_a, second) if arm_a.status == "RAN" and second.status == "RAN" else None
    )
    return {
        "scenario": name,
        "bars": len(bars),
        "hole_bar_ms": T0 + HOLE_BAR * BAR_MS if hole else None,
        "bars_sha256": hashlib.sha256(
            json.dumps([[bar.ts_ms, bar.open, bar.high, bar.low, bar.close, bar.volume] for bar in bars]).encode()
        ).hexdigest(),
        "A": arm_a.to_dict(),
        "session_1": first.to_dict(),
        "B": second.to_dict(),
        "comparison": comparison,
        "book_comparison": (
            compare_books(arm_a.book, second.book)
            if arm_a.book is not None and second.book is not None and second.status == "RAN"
            else None
        ),
    }


# -- kill experiments -----------------------------------------------------------


def kill_while_saving(iterations: int = 12) -> dict[str, Any]:
    """A child writes the book in a loop; the parent kills it at a random instant."""

    outcomes: list[dict[str, Any]] = []
    root = REPO / ".tmp" / "gap-lab-kill-save"
    for attempt in range(iterations):
        target = root / f"try-{attempt:02d}"
        shutil.rmtree(target, ignore_errors=True)
        state = LaneBookStore(target)
        state.save({"attempt": attempt, "padding": "x" * 4096})
        delay = 0.05 + 0.03 * attempt
        process = subprocess.Popen(
            [sys.executable, str(Path(__file__)), "child-save", "--state", str(target)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        time.sleep(delay)
        killed = process.poll() is None
        if killed:
            process.kill()
        process.wait(timeout=30)
        try:
            book = state.load()
            status = "READABLE" if book is not None else "MISSING"
            digest = None if book is None else book.digest
        except Exception as exc:  # a corrupt book is an outcome, not a crash
            status, digest = type(exc).__name__, None
        outcomes.append(
            {
                "attempt": attempt,
                "killed": killed,
                "exit_code": process.returncode,
                "delay_s": round(delay, 3),
                "status": status,
                "digest": digest,
                "generations": {
                    "book": state.path.exists(),
                    "prev": state.prev_path.exists(),
                },
            }
        )
    failures = [row for row in outcomes if row["status"] != "READABLE"]
    return {
        "iterations": iterations,
        "outcomes": outcomes,
        "failures": failures,
        "ok": not failures,
    }


def child_saving(state: Path) -> int:
    store = LaneBookStore(state)
    index = 0
    while True:
        index += 1
        store.save({"attempt": index, "padding": "x" * 4096})
    return 0  # pragma: no cover - the loop is the child


def child_resume(state: Path, ledger: Path, bars_kind: str, feed_kind: str, from_bar: int) -> int:
    truth = minutes_for(feed_kind if feed_kind != "quiet" else "quiet")
    bars = bars_from_minutes(truth)
    given = feed_minutes(feed_kind)
    resumed = list(bars[: from_bar + 1]) + [
        bar for bar in bars[from_bar + 1 :] if int(bar.ts_ms) != T0 + HOLE_BAR * BAR_MS
    ]
    store = LaneBookStore(state)
    book = store.load()
    feed = feed_for(given) if feed_kind != "none" else None
    lock = store.lock(session_id="child")
    try:
        run_lane(
            resumed if bars_kind == "holed" else bars[from_bar:],
            ledger,
            store=store,
            book=book,
            session_id="child",
            quote_feed=feed,
        )
    finally:
        lock.release()
    return 0


def kill_while_resuming(iterations: int = 14) -> dict[str, Any]:
    """Kill the resumed process at a random instant, restart, and check convergence.

    The invariant is the one that matters economically: whatever the kill interrupted, the
    final state must be A's — one close at the stop, no duplicate, no lost position. A kill
    before the reconstruction commits means the position is still there and the next
    attempt reconstructs it again; a kill after it means the position is gone and the next
    attempt resumes flat. There is no third outcome, and the run proves it by repeating.
    """

    truth = minutes_for("stop")
    bars = bars_from_minutes(truth)
    root = REPO / ".tmp" / "gap-lab-kill-resume"
    shutil.rmtree(root, ignore_errors=True)
    root.mkdir(parents=True, exist_ok=True)

    #: El brazo A, para saber cuál es el estado final correcto.
    reference_store = LaneBookStore(root / "reference")
    lock = reference_store.lock(session_id="A")
    try:
        run_lane(bars, root / "reference.jsonl", store=reference_store, session_id="A")
    finally:
        lock.release()

    #: La primera sesión crea el libro con la posición abierta.
    state = LaneBookStore(root / "state")
    lock = state.lock(session_id="s1")
    try:
        run_lane(bars[: SPLIT_BAR + 1], root / "s1.jsonl", store=state, session_id="s1")
    finally:
        lock.release()

    attempts: list[dict[str, Any]] = []
    for attempt in range(iterations):
        ledger = root / f"resume-{attempt:02d}.jsonl"
        before = state.load()
        before_closed = len(before.closed_trades) if before is not None else -1
        delay = 0.15 + 0.05 * attempt
        process = subprocess.Popen(
            [
                sys.executable,
                str(Path(__file__)),
                "child-resume",
                "--state",
                str(state.directory),
                "--ledger",
                str(ledger),
                "--bars",
                "holed",
                "--feed",
                "stop",
                "--from-bar",
                str(SPLIT_BAR),
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        time.sleep(delay)
        killed = process.poll() is None
        if killed:
            process.kill()
        process.wait(timeout=60)
        after = state.load()
        attempts.append(
            {
                "attempt": attempt,
                "killed": killed,
                "exit_code": process.returncode,
                "closed_before": before_closed,
                "closed_after": len(after.closed_trades) if after is not None else -1,
                "open_after": len(after.open_positions) if after is not None else -1,
                "state_digest": None if after is None else after.state_digest,
            }
        )
        if after is not None and after.open_positions == [] and after.closed_trades:
            break

    #: Una pasada final sin matar, para llegar al estado terminal.
    lock = state.lock(session_id="final")
    try:
        run_lane(
            list(bars[: SPLIT_BAR + 1])
            + [bar for bar in bars[SPLIT_BAR + 1 :] if int(bar.ts_ms) != T0 + HOLE_BAR * BAR_MS],
            root / "final.jsonl",
            store=state,
            book=state.load(),
            session_id="final",
            quote_feed=feed_for(truth),
        )
    finally:
        lock.release()

    final_book = state.load()
    reference_book = reference_store.load()
    assert final_book is not None and reference_book is not None
    closes = [row for row in read_entries(root / "final.jsonl") if row["entry"].get("kind") == "CLOSE"]
    #: El digest no puede coincidir por construcción: el brazo con hueco nunca comprometió
    #: esa vela (``bars_committed``) y su cierre se observó al minuto, no al cierre de la
    #: vela. Se comparan los cuerpos campo a campo, con esas rutas declaradas, en vez de
    #: fingir que un digest igual sería la prueba.
    comparison = compare_books(reference_book.body, final_book.body)
    return {
        "iterations": iterations,
        "attempts": attempts,
        "final_state_digest": final_book.state_digest,
        "reference_state_digest": reference_book.state_digest,
        "digests_equal": final_book.state_digest == reference_book.state_digest,
        "final_closed": len(final_book.closed_trades),
        "reference_closed": len(reference_book.closed_trades),
        "final_open": len(final_book.open_positions),
        "final_closes_in_last_ledger": len(closes),
        "final_equity": final_book.body["broker"]["equity"],
        "reference_equity": reference_book.body["broker"]["equity"],
        "book_comparison": comparison,
        "ok": (
            comparison["ok"]
            and len(final_book.closed_trades) == 1
            and len(final_book.open_positions) == 0
        ),
    }


# -- orchestration --------------------------------------------------------------


def run_all(out: Path) -> dict[str, Any]:
    out.mkdir(parents=True, exist_ok=True)
    tmp = REPO / ".tmp" / "gap-lab"
    shutil.rmtree(tmp, ignore_errors=True)
    tmp.mkdir(parents=True, exist_ok=True)

    scenarios: dict[str, Any] = {}
    scenarios["split"] = _scenario(tmp, "split", hole=False, minutes=None)
    scenarios["quiet"] = _scenario(tmp, "quiet", hole=True, minutes=minutes_for("quiet"))
    scenarios["stop"] = _scenario(tmp, "stop", hole=True, minutes=minutes_for("stop"))
    scenarios["take"] = _scenario(tmp, "take", hole=True, minutes=minutes_for("take"))
    scenarios["both"] = _scenario(tmp, "both", hole=True, minutes=minutes_for("both"))
    scenarios["partial"] = _scenario(tmp, "partial", hole=True, minutes=feed_minutes("partial"))

    #: La corrupción no llega a ser un veredicto: el feed se niega a construir la serie.
    corrupt: dict[str, Any]
    try:
        feed_for(feed_minutes("corrupt"))
        corrupt = {"status": "ACCEPTED", "ok": False}
    except QuoteFeedIntegrityError as exc:
        corrupt = {"status": "REFUSED_AT_LOAD", "detail": str(exc), "ok": True}

    #: Concurrencia: dos escritores sobre el mismo libro.
    concurrent: dict[str, Any]
    probe = LaneBookStore(tmp / "concurrent")
    holder = probe.lock(session_id="holder")
    try:
        try:
            probe.lock(session_id="intruder")
            concurrent = {"status": "ACQUIRED", "ok": False}
        except SessionBusy as exc:
            concurrent = {"status": "REFUSED", "detail": str(exc), "ok": True}
    finally:
        holder.release()

    saves = kill_while_saving()
    resumes = kill_while_resuming()

    receipt = {
        "scenarios": scenarios,
        "corrupt_feed": corrupt,
        "concurrent_writer": concurrent,
        "kill_while_saving": saves,
        "kill_while_resuming": resumes,
    }
    receipt["ok"] = all(
        [
            (scenarios["split"]["comparison"] or {}).get("ok"),
            (scenarios["quiet"]["comparison"] or {}).get("ok"),
            (scenarios["stop"]["comparison"] or {}).get("ok"),
            (scenarios["take"]["comparison"] or {}).get("ok"),
            scenarios["both"]["B"]["status"] == "BLOCKED"
            and scenarios["both"]["B"]["code"] == "GAP_EXIT_AMBIGUOUS",
            scenarios["partial"]["B"]["status"] == "BLOCKED"
            and scenarios["partial"]["B"]["code"] == "GAP_NOT_COVERED",
            corrupt["ok"],
            concurrent["ok"],
            saves["ok"],
            resumes["ok"],
        ]
    )
    (out / "GAP_LAB.json").write_text(
        json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    (out / "SHA256SUMS").write_text(
        "".join(
            f"{hashlib.sha256(path.read_bytes()).hexdigest()}  {path.name}\n"
            for path in sorted(out.glob("*.json"))
        ),
        encoding="utf-8",
    )
    return receipt


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    run_cmd = sub.add_parser("run")
    run_cmd.add_argument("--out", type=Path, default=REPO / "reports/ai-bots/WP-PAPER-QUOTE-GAP-002/lab")
    child = sub.add_parser("child-save")
    child.add_argument("--state", type=Path, required=True)
    resume = sub.add_parser("child-resume")
    resume.add_argument("--state", type=Path, required=True)
    resume.add_argument("--ledger", type=Path, required=True)
    resume.add_argument("--bars", choices=["holed", "full"], default="holed")
    resume.add_argument("--feed", default="stop")
    resume.add_argument("--from-bar", type=int, default=SPLIT_BAR)
    args = parser.parse_args(argv)

    if args.command == "child-save":
        return child_saving(args.state)
    if args.command == "child-resume":
        return child_resume(args.state, args.ledger, args.bars, args.feed, args.from_bar)

    receipt = run_all(args.out)
    print(json.dumps({"ok": receipt["ok"], "out": str(args.out)}, indent=2))
    summary = {name: scenario["B"]["status"] for name, scenario in receipt["scenarios"].items()}
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0 if receipt["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
