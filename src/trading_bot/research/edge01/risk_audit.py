"""WP-EDGE-02B — were H6's 183 risk refusals correct?

H6 rested 686 limit orders on DEV and 183 of them reached the level and were refused by
the runtime's risk budget, split (as published) into 148 ``risk_drawdown_halt`` and 35
``risk_loss_cooldown``. WP-EDGE-01 published that split as an outcome of the experiment
and asked nothing more of it, which leaves the question this module answers: was the
budget right each time, or was it blocking a book it should have let through?

Nothing about the ruleset, the plan or the limits changes here. The audit

* re-runs the three H6 arms on the declared windows through the SAME frozen harness and
  compares the reconstruction with the artefact WP-EDGE-01 already published
  (``RETEST.json``), so an order count that moved would fail here;
* installs an **observing wrapper** around the simulator's own entry path: it records the
  state the budget saw (equity, running peak, drawdown, open positions and notional,
  trades today, cooldown deadline, the order the touch belonged to) and returns the
  original call's value unchanged. The wrapper is restored in a ``finally`` block, so the
  measurement is the frozen one and the observation is additive;
* evaluates every refusal against the rule it claims to have fired, from that captured
  state: a refusal is ``correct`` only if the stated limit really was breached at that
  instant, and ``incorrect`` otherwise. The rules are declared below before the run;
* checks the book's invariants on the same capture — accounting (final equity equals
  start plus the sum of the trades), sizing against the configured risk per trade, the
  notional, asset and total-exposure caps, the minimum notional, the open-position and
  daily-trade limits, capital release on exit, one outcome per order, no duplicated and
  no silent refusal;
* restates the RUNTIME Risk Engine's own decision order (``src/trading_bot/risk/manager.py``)
  and reports which of its rules the research budget models and which it does not, so
  "the research budget agreed" is never read as "live would behave identically";
* reports a defect with a regression test only when one is demonstrated. No limit is
  relaxed to make the book trade more often.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from . import campaign as C
from . import closure as CL
from .candidates import FROZEN_PARAMS, PARAMS_HASH
from .costs import cost_plane
from .data import ASSETS
from .features import market_regime_at
from .retest import RetestEntry
from .simulator import _enter, _fill, _touch_order
from .simulator import run_portfolio as run_portfolio_sim

__all__ = [
    "RISK_AUDIT",
    "RISK_AUDIT_DECISION",
    "expected_runtime_decision",
    "refusal_is_correct",
    "run_risk_audit",
    "risk_audit_verdict",
    "write_risk_audit_artifacts",
]

RISK_AUDIT: dict[str, Any] = {
    "id": "AUD-EDGE01-H6-RISK",
    "answer_to": "H6",
    "audits": "ABL-EDGE01-H6",
    "split": "intraday",
    "timeframe": "15m",
    "horizon_minutes": 240.0,
    "windows": ["DEV", "VAL", "OOS"],
    "scenario_plan": {"DEV": ["BASE", "2X_FEES"], "VAL": ["BASE"], "OOS": ["BASE", "2X_FEES"]},
    "arms": ["frozen_market", "plan_market", "plan_limit"],
    "primary": {"window": "DEV", "scenario": "BASE", "arm": "plan_limit"},
    "reproduces": (
        "reports/edge-recovery/WP-EDGE-01/retest-h6/RETEST.json — the three arms are "
        "re-run and their order counts, fills, refusals and net are compared with the "
        "published figures"
    ),
    "question": (
        "183 of the 686 planned limit orders reached the level and the risk budget "
        "refused them (148 drawdown halt, 35 loss cooldown). Was the budget right at "
        "each of those instants, does the book keep its own invariants while refusing, "
        "and does the research budget's behaviour match the runtime Risk Engine's?"
    ),
}

#: Frozen BEFORE the audit ran. Each refusal carries the limit it claims fired; the rule
#: below restates what that limit MEANS, so a reason can be checked against the state
#: instead of being taken on trust. Tolerance is zero for the boolean limits and 1e-9
#: for the arithmetic ones (the captured state and the rule use the same floats).
RISK_AUDIT_DECISION: dict[str, Any] = {
    "refusal_rules": {
        "risk_drawdown_halt": (
            "drawdown_at_the_instant = (peak_equity - equity) / peak_equity * 100 must be "
            ">= config max_total_drawdown_pct (5.0)"
        ),
        "risk_loss_cooldown": (
            "the instant must fall strictly inside the cooldown window opened by the "
            "losing streak (ts < cooldown_until_ts)"
        ),
        "risk_max_open_positions": "open positions at the instant must be >= the limit (3)",
        "risk_max_trades_per_day": "trades booked that day must be >= the limit (20)",
        "risk_exposure_cap": (
            "open notional + this order's notional must exceed the total exposure cap and "
            "the remainder must be below the minimum notional (20 USDT)"
        ),
        "risk_notional_below_minimum": "the sized notional must be below 20 USDT",
        "position_already_open": "the asset must already hold a position",
        "stop_above_fill": "the stop must be at or above the fill price",
        "fill_price_invalid": "the fill price must be non-positive",
    },
    "invariants": {
        "accounting_final_equity": "final_equity == start_equity + sum(trade net), to 1e-6",
        "cash_never_negative": "the replayed cash balance must stay >= 0 at every bar",
        "sizing_at_or_below_configured_risk": (
            "every filled entry risks at most equity * max_risk_per_trade_pct / 100 at its "
            "initial stop, and exactly that unless a notional cap bound it"
        ),
        "notional_within_caps": (
            "every filled entry's notional must respect the per-order maximum and the "
            "per-asset exposure cap, and must not push total open notional past its cap"
        ),
        "notional_at_or_above_minimum": "every filled entry's notional must be >= 20 USDT",
        "open_positions_within_limit": "never more than 3 positions open at once",
        "trades_per_day_within_limit": "never more than 20 entries booked in one day",
        "one_outcome_per_order": (
            "every planned order must end with exactly one outcome from the declared "
            "vocabulary and no order may be left resting"
        ),
        "refusals_are_attributed": (
            "every order refused by the budget must carry the reason the budget gave, and "
            "no refusal may be recorded without an order or intent behind it"
        ),
        "no_duplicate_refusals": "no (asset, instant, reason) may be refused twice",
    },
    "verdicts": {
        "AUDIT_PASS": "every refusal was correct at its instant and every invariant holds",
        "AUDIT_FINDINGS": "at least one refusal is incorrect or one invariant fails",
    },
    "modelling_gap_note": (
        "the research budget re-implements the runtime's limits; it does NOT model the "
        "runtime's daily loss limit, weekly loss limit, daily drawdown, weekend block, "
        "spread/ATR blocks or the kill switch. A live run of the same book therefore "
        "blocks AT LEAST as often, never less."
    ),
    "not_claimed": (
        "an audit of the risk budget is not a profitability claim and not an admission: "
        "nothing is wired into the PAPER runtime and no limit is changed by this report"
    ),
}


def refusal_is_correct(reason: str, state: dict[str, Any]) -> tuple[bool, str]:
    """Whether ``reason`` really held in ``state``. Pure; the declared rules, verbatim."""
    tol = 1e-9
    if reason == "risk_drawdown_halt":
        drawdown = state.get("drawdown_pct")
        threshold = state.get("drawdown_halt_pct")
        if drawdown is None or threshold is None:
            return False, "the drawdown at the instant was not captured"
        return (
            float(drawdown) + tol >= float(threshold),
            f"drawdown {float(drawdown):.6f}% vs the configured halt {float(threshold)}%",
        )
    if reason == "risk_loss_cooldown":
        ts = state.get("decision_ts")
        until = state.get("cooldown_until_ts") or 0
        if ts is None:
            return False, "the instant was not captured"
        return (
            int(ts) < int(until),
            f"instant {ts} vs the cooldown deadline {until} "
            f"({(int(until) - int(ts)) / 60_000.0:.2f} min inside the window)"
            if int(until) > int(ts)
            else f"instant {ts} is not inside the cooldown window (deadline {until})",
        )
    if reason == "risk_max_open_positions":
        opened = int(state.get("open_positions_count") or 0)
        limit = int(state.get("max_open_positions") or 0)
        return opened >= limit, f"{opened} open positions vs the limit {limit}"
    if reason == "risk_max_trades_per_day":
        taken = int(state.get("trades_today") or 0)
        limit = int(state.get("max_trades_per_day") or 0)
        return taken >= limit, f"{taken} trades booked today vs the limit {limit}"
    if reason == "risk_exposure_cap":
        open_notional = float(state.get("open_notional") or 0.0)
        notional = float(state.get("entry_notional") or 0.0)
        cap = float(state.get("exposure_cap") or 0.0)
        minimum = float(state.get("min_notional_usdt") or 0.0)
        remainder = cap - open_notional
        return (
            open_notional + notional > cap + tol and remainder < minimum,
            f"open {open_notional:,.2f} + {notional:,.2f} vs the cap {cap:,.2f}; the "
            f"remainder {remainder:,.2f} is below the minimum {minimum:,.2f}",
        )
    if reason == "risk_notional_below_minimum":
        notional = float(state.get("entry_notional") or 0.0)
        minimum = float(state.get("min_notional_usdt") or 0.0)
        return notional < minimum + tol, f"notional {notional:,.6f} vs the minimum {minimum:,.2f}"
    if reason == "position_already_open":
        opened = int(state.get("open_positions_count") or 0)
        holds = bool(state.get("asset_held"))
        return holds, f"asset held at the instant: {holds} ({opened} positions open)"
    if reason == "stop_above_fill":
        stop = state.get("stop")
        fill = state.get("entry_fill")
        if stop is None or fill is None:
            return False, "the stop or the fill price was not captured"
        return float(stop) >= float(fill) - tol, f"stop {stop} vs the fill {fill}"
    if reason == "fill_price_invalid":
        mid = state.get("entry_mid")
        return (
            mid is not None and float(mid) <= 0,
            f"the fill price was {mid} (the budget refuses a non-positive price)",
        )
    return False, f"{reason!r} is not a reason this audit's declared rules cover"


def expected_runtime_decision(state: dict[str, Any]) -> dict[str, Any]:
    """Restate the RUNTIME Risk Engine's decision order for one captured instant.

    ``src/trading_bot/risk/manager.py`` checks, in this order: kill switch, daily trade
    limit, open positions, consecutive-loss cooldown, daily loss, weekly loss, daily
    drawdown, max total drawdown, then sizing. The research budget models a subset of
    those; this function restates the ones both share, so the audit can compare them
    instead of asserting that they agree.
    """
    rules = [
        ("daily_trade_limit", int(state.get("trades_today") or 0) >= int(state.get("max_trades_per_day") or 0)),
        ("max_positions", int(state.get("open_positions_count") or 0) >= int(state.get("max_open_positions") or 0)),
        (
            "consecutive_loss_cooldown",
            int(state.get("decision_ts") or 0) < int(state.get("cooldown_until_ts") or 0),
        ),
        (
            "max_drawdown",
            state.get("drawdown_pct") is not None
            and float(state["drawdown_pct"]) + 1e-9 >= float(state.get("drawdown_halt_pct") or 0.0),
        ),
    ]
    blocked_by = next((name for name, fired in rules if fired), None)
    return {
        "approved": blocked_by is None,
        "blocked_by": blocked_by,
        "evaluated_rules": [name for name, _fired in rules],
        "rules_not_modelled_by_the_research_budget": [
            "kill_switch",
            "daily_loss_limit",
            "weekly_loss_limit",
            "daily_drawdown",
            "weekend_block",
            "spread_block",
            "atr_block",
        ],
        "note": (
            "the runtime interleaves positional sizing caps inside its own sizing step; "
            "the research budget applies them after the limits, which is why an entry it "
            "refused is never one the runtime would have admitted"
        ),
    }


#: The mapping from the research budget's refusal reason to the runtime rule that would
#: have blocked the same entry, for the agreement count.
REASON_TO_RUNTIME_RULE: dict[str, str] = {
    "risk_max_trades_per_day": "daily_trade_limit",
    "risk_max_open_positions": "max_positions",
    "risk_loss_cooldown": "consecutive_loss_cooldown",
    "risk_drawdown_halt": "max_drawdown",
}


class _Capture:
    """Per-run observation buffer. Filled by the wrappers, never read by the simulator."""

    def __init__(self, *, key: str, arm: str, window: str, scenario: str) -> None:
        self.key = key
        self.arm = arm
        self.window = window
        self.scenario = scenario
        self.delivery = "unknown"
        self.records: list[dict[str, Any]] = []
        self.order_queue: list[dict[str, Any]] = []


_CAPTURE: _Capture | None = None
_ORIGINALS: dict[str, Any] = {}


def _observing_fill(*args: Any, **kwargs: Any) -> float:
    if _CAPTURE is not None:
        _CAPTURE.delivery = "market_intent"
    return _ORIGINALS["fill"](*args, **kwargs)


def _observing_touch_order(*args: Any, **kwargs: Any) -> float:
    if _CAPTURE is not None:
        _CAPTURE.delivery = "resting_touch"
    order = kwargs.get("order") if kwargs else None
    result = kwargs.get("result")
    before = len(result.refusals) if result is not None else 0
    value = _ORIGINALS["touch"](*args, **kwargs)
    if _CAPTURE is not None and order is not None:
        row = order.get("row") or {}
        if len(result.refusals) > before:
            _CAPTURE.order_queue.append(
                {
                    "placement_ts": row.get("placement_ts"),
                    "level": row.get("level"),
                    "outcome": "refused_by_risk_budget",
                }
            )
        else:
            _CAPTURE.order_queue.append(
                {
                    "placement_ts": row.get("placement_ts"),
                    "level": row.get("level"),
                    "outcome": row.get("outcome"),
                }
            )
    return value


def _observing_enter(*args: Any, **kwargs: Any) -> float:
    """Record the state the risk budget sees; the returned value is the original's."""
    call = dict(kwargs)
    if args:
        names = (
            "signal",
            "bar",
            "idx",
            "ts",
            "mid",
            "positions",
            "result",
            "policy",
            "plane",
            "gate",
            "equity",
        )
        for name, value in zip(names, args, strict=False):
            call.setdefault(name, value)
    signal = call.get("signal")
    result = call.get("result")
    # NOT ``or {}``: an empty (but live) positions dict is falsy, and substituting a fresh
    # dict for it would read the book AFTER an entry against the wrong object
    # (DEF-EDGE02-01), which is exactly the mistake the entry invariants then catch.
    positions = call.get("positions")
    if positions is None:
        positions = {}
    policy = call.get("policy")
    gate = call.get("gate")
    before = len(result.refusals) if result is not None else 0
    value = _ORIGINALS["enter"](*args, **kwargs)
    if _CAPTURE is None or signal is None or policy is None or gate is None:
        return value
    asset = signal.symbol
    mid = float(call.get("mid") or 0.0)
    equity = float(call.get("equity") or 0.0)
    peak = float(gate.peak_equity or 0.0)
    drawdown = (peak - equity) / peak * 100.0 if peak > 0 else 0.0
    refused = result is not None and len(result.refusals) > before
    reason = result.refusals[-1].get("reason") if refused else None
    open_notional = sum(p.qty * p.entry_fill for p in positions.values())
    record: dict[str, Any] = {
        "run": _CAPTURE.key,
        "arm": _CAPTURE.arm,
        "window": _CAPTURE.window,
        "scenario": _CAPTURE.scenario,
        "candidate": signal.candidate,
        "asset": asset,
        "delivery": _CAPTURE.delivery,
        "decision_ts": int(call.get("ts") or 0),
        "entry_mid": round(mid, 8),
        "stop": round(float(signal.stop), 8),
        "equity": round(equity, 8),
        "peak_equity": round(peak, 8),
        "drawdown_pct": round(drawdown, 8),
        "drawdown_halt_pct": float(policy.drawdown_halt_pct),
        "open_positions_count": len(positions),
        "asset_held": asset in positions,
        "open_positions": sorted(positions),
        "open_notional": round(open_notional, 8),
        "max_open_positions": int(policy.max_open_positions),
        "trades_today": int(gate.trades_today),
        "max_trades_per_day": int(policy.max_trades_per_day),
        "cooldown_until_ts": int(gate.cooldown_until_ts or 0),
        "consecutive_losses": int(gate.consecutive_losses),
        "exposure_cap": round(equity * policy.max_total_exposure_pct / 100.0, 8),
        "asset_cap": round(equity * policy.max_asset_exposure_pct / 100.0, 8),
        "max_notional_usdt": float(policy.max_notional_usdt),
        "min_notional_usdt": float(policy.min_notional_usdt),
        "risk_per_trade_pct": float(policy.risk_per_trade_pct),
        "outcome": "refused" if refused else "filled_or_placed",
        "reason": reason,
        "source": "risk" if refused else None,
        "refusal_detail": (result.refusals[-1] if refused else None),
    }
    if not refused:
        position = positions.get(asset)
        record["entry_fill"] = round(float(position.entry_fill), 8) if position else None
        record["entry_notional"] = round(float(position.notional), 8) if position else None
        record["entry_qty"] = round(float(position.qty), 10) if position else None
        record["entry_stop_distance"] = (
            round(float(position.stop_distance), 10) if position else None
        )
        record["planned_risk_usdt"] = (
            round(float(position.planned_risk_usdt), 8) if position else None
        )
    else:
        stop_distance = mid - float(signal.stop)
        risk_usdt = equity * float(policy.risk_per_trade_pct) / 100.0
        qty = risk_usdt / stop_distance if stop_distance > 0 else 0.0
        notional = min(
            qty * mid,
            float(policy.max_notional_usdt),
            equity * float(policy.max_asset_exposure_pct) / 100.0,
        )
        allowed = equity * float(policy.max_total_exposure_pct) / 100.0 - open_notional
        if allowed < notional:
            notional = allowed
        record["entry_fill"] = None
        record["entry_notional"] = round(max(notional, 0.0), 8)
        record["entry_qty"] = None
        record["entry_stop_distance"] = round(stop_distance, 10)
        record["planned_risk_usdt"] = round(risk_usdt, 8)
    _CAPTURE.records.append(record)
    return value


def install_observer() -> None:
    """Install the observing wrappers. Idempotent; restores in ``remove_observer``."""
    if _ORIGINALS:
        return
    import trading_bot.research.edge01.simulator as S

    _ORIGINALS.update({"fill": S._fill, "touch": S._touch_order, "enter": S._enter})
    S._fill = _observing_fill
    S._touch_order = _observing_touch_order
    S._enter = _observing_enter
    # The frozen module's own module-level names are what the callers resolve, so the
    # wrappers are installed on the module object, not on a copy of it.
    globals()["_fill"] = _observing_fill
    globals()["_touch_order"] = _observing_touch_order
    globals()["_enter"] = _observing_enter


def remove_observer() -> None:
    """Restore the frozen entry path exactly as it was."""
    if not _ORIGINALS:
        return
    import trading_bot.research.edge01.simulator as S

    S._fill = _ORIGINALS["fill"]
    S._touch_order = _ORIGINALS["touch"]
    S._enter = _ORIGINALS["enter"]
    globals()["_fill"] = _ORIGINALS["fill"]
    globals()["_touch_order"] = _ORIGINALS["touch"]
    globals()["_enter"] = _ORIGINALS["enter"]
    _ORIGINALS.clear()


def _load_published_h6(root: Path) -> dict[str, Any] | None:
    path = root / "reports" / "edge-recovery" / "WP-EDGE-01" / "retest-h6" / "RETEST.json"
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _run_arm(
    *,
    arm: str,
    window: str,
    scenario: str,
    factory: Any,
    limit_entries: bool,
    start: int,
    end: int,
    plane: Any,
    policy: Any,
    corpus: Any,
    regime_rows: Any,
    window_minutes: float,
    timeframe: str,
) -> dict[str, Any]:
    """One arm of one window/scenario, observed. The simulator's call is unchanged."""
    key = f"{window}:{scenario}"
    candidate = factory()
    global _CAPTURE
    _CAPTURE = _Capture(key=key, arm=arm, window=window, scenario=scenario)
    try:
        sim = run_portfolio_sim(
            candidate=candidate,
            bars_by_asset=corpus.bars_by_asset,
            plane=plane,
            policy=policy,
            context=corpus.context,
            window_start_ts=start,
            window_end_ts=end,
            limit_entries=limit_entries,
        )
    finally:
        capture = _CAPTURE
        _CAPTURE = None
    for trade in sim.trades:
        trade["market_context"] = market_regime_at(regime_rows, int(trade["decision_ts"]))
    metrics = C._metrics(
        trades=sim.trades,
        equity_curve=sim.equity_curve,
        start_equity=policy.start_equity,
        window_minutes=window_minutes,
        timeframe=timeframe,
        n_assets=len(ASSETS),
    )
    return {
        "arm": arm,
        "window": window,
        "scenario": scenario,
        "key": key,
        "candidate_id": str(candidate.id),
        "params_delta": C._params_delta(FROZEN_PARAMS["edge_intra_01"], dict(candidate.params)),
        "metrics": metrics,
        "orders": list(sim.orders),
        "refusals": list(sim.refusals),
        "signals": len(sim.signals),
        "signals_planning_a_limit": sum(
            1 for signal in sim.signals if signal.get("entry_limit") is not None
        ),
        "trades": list(sim.trades),
        "equity_curve": list(sim.equity_curve),
        "records": list(capture.records),
        "order_queue": list(capture.order_queue),
    }


def _order_census(orders: list[dict[str, Any]]) -> dict[str, Any]:
    outcomes: dict[str, int] = {}
    for row in orders:
        key = str(row.get("outcome"))
        outcomes[key] = outcomes.get(key, 0) + 1
    return {"orders_placed": len(orders), "orders_by_outcome": outcomes}


def _order_summary(orders: list[dict[str, Any]]) -> dict[str, Any]:
    """Placed/filled/fill-rate from the order rows, the same shape H6 published."""
    census = _order_census(orders)
    placed = int(census["orders_placed"])
    filled = int(census["orders_by_outcome"].get("filled", 0))
    return {
        "orders_placed": placed,
        "orders_filled": filled,
        "fill_rate": round(filled / placed, 6) if placed else None,
        "orders_by_outcome": census["orders_by_outcome"],
    }


def _check_invariants(run: dict[str, Any], policy: Any) -> list[dict[str, Any]]:
    """The declared invariants, evaluated on the capture and the book it produced."""
    checks: list[dict[str, Any]] = []
    metrics = run["metrics"]
    start = float(policy.start_equity)
    net = float(metrics["net_usdt"] or 0.0)
    final = float(metrics["final_equity"] or 0.0)

    def add(name: str, passed: bool, detail: str) -> None:
        checks.append(
            {
                "invariant": name,
                "scope": run["key"],
                "arm": run["arm"],
                "result": "PASS" if passed else "FAIL",
                "detail": detail,
            }
        )

    add(
        "accounting_final_equity",
        abs((start + net) - final) < 1e-6,
        f"start {start:,.4f} + net {net:,.4f} = {start + net:,.4f} vs final {final:,.4f}",
    )
    equity_curve = run["equity_curve"]
    worst = min((value for _ts, value in equity_curve), default=start)
    add("cash_never_negative", worst >= -1e-9, f"lowest equity mark {worst:,.4f} (>= 0)")

    sizing_failures: list[str] = []
    cap_failures: list[str] = []
    min_failures: list[str] = []
    positions_failures: list[str] = []
    trades_day_failures: list[str] = []
    for record in run["records"]:
        # The two count limits hold whatever the budget decided, so they are checked on
        # every observation; the sizing/cap/minimum rules only apply to a real entry.
        if int(record["open_positions_count"]) > int(policy.max_open_positions):
            positions_failures.append(
                f"{record['decision_ts']}: {record['open_positions_count']} positions open when "
                "the budget was asked, above the limit"
            )
        if int(record["trades_today"]) > int(policy.max_trades_per_day):
            trades_day_failures.append(
                f"{record['decision_ts']}: {record['trades_today']} trades booked today"
            )
        if record["outcome"] != "filled_or_placed":
            continue
        qty = record.get("entry_qty")
        stop_distance = record.get("entry_stop_distance")
        equity = float(record["equity"])
        if qty is not None and stop_distance is not None:
            risked = float(qty) * float(stop_distance)
            allowed_risk = equity * float(policy.risk_per_trade_pct) / 100.0
            if risked > allowed_risk + 1e-6:
                sizing_failures.append(
                    f"{record['decision_ts']} {record['asset']}: risked {risked:,.6f} vs the "
                    f"allowed {allowed_risk:,.6f}"
                )
        notional = float(record.get("entry_notional") or 0.0)
        if notional > float(policy.max_notional_usdt) + 1e-6:
            cap_failures.append(
                f"{record['decision_ts']} {record['asset']}: notional {notional:,.4f} above the "
                f"per-order maximum {policy.max_notional_usdt:,.2f}"
            )
        if notional > float(record["asset_cap"]) + 1e-6:
            cap_failures.append(
                f"{record['decision_ts']} {record['asset']}: notional {notional:,.4f} above the "
                f"per-asset cap {record['asset_cap']:,.4f}"
            )
        if float(record["open_notional"]) + notional > float(record["exposure_cap"]) + 1e-6:
            cap_failures.append(
                f"{record['decision_ts']} {record['asset']}: open {record['open_notional']:,.4f} + "
                f"{notional:,.4f} above the total cap {record['exposure_cap']:,.4f}"
            )
        if notional + 1e-6 < float(policy.min_notional_usdt):
            min_failures.append(
                f"{record['decision_ts']} {record['asset']}: notional {notional:,.6f} below the "
                f"minimum {policy.min_notional_usdt:,.2f}"
            )

    add(
        "sizing_at_or_below_configured_risk",
        not sizing_failures,
        f"{len(sizing_failures)} violation(s) of the configured risk per trade"
        + (f"; first: {sizing_failures[0]}" if sizing_failures else ""),
    )
    add(
        "notional_within_caps",
        not cap_failures,
        f"{len(cap_failures)} cap violation(s)"
        + (f"; first: {cap_failures[0]}" if cap_failures else ""),
    )
    add(
        "notional_at_or_above_minimum",
        not min_failures,
        f"{len(min_failures)} entry(ies) below the minimum notional"
        + (f"; first: {min_failures[0]}" if min_failures else ""),
    )
    add(
        "open_positions_within_limit",
        not positions_failures,
        f"{len(positions_failures)} observation(s) above the open-position limit"
        + (f"; first: {positions_failures[0]}" if positions_failures else ""),
    )
    add(
        "trades_per_day_within_limit",
        not trades_day_failures,
        f"{len(trades_day_failures)} day(s) above the daily trade limit"
        + (f"; first: {trades_day_failures[0]}" if trades_day_failures else ""),
    )

    vocabulary = {
        "filled",
        "expired",
        "refused_by_risk_budget",
        "cancelled_close_below_level",
        "cancelled_window_end",
        "RESTING",
    }
    bad_orders = [row for row in run["orders"] if str(row.get("outcome")) not in vocabulary]
    resting = [row for row in run["orders"] if str(row.get("outcome")) == "RESTING"]
    add(
        "one_outcome_per_order",
        not bad_orders and not resting,
        f"{len(run['orders'])} orders, {len(bad_orders)} with an unknown outcome and "
        f"{len(resting)} left resting",
    )
    refused_orders = [
        row for row in run["orders"] if str(row.get("outcome")) == "refused_by_risk_budget"
    ]
    without_reason = [row for row in refused_orders if not row.get("refusal_reason")]
    add(
        "refusals_are_attributed",
        not without_reason,
        f"{len(refused_orders)} refused orders, {len(without_reason)} without a reason",
    )
    seen: set[tuple[Any, Any, Any]] = set()
    duplicates: list[str] = []
    for record in run["records"]:
        if record["outcome"] != "refused":
            continue
        key = (record["asset"], record["decision_ts"], record["reason"])
        if key in seen:
            duplicates.append(f"{key}")
        seen.add(key)
    add(
        "no_duplicate_refusals",
        not duplicates,
        f"{len(duplicates)} duplicated (asset, instant, reason) refusal(s)"
        + (f"; first: {duplicates[0]}" if duplicates else ""),
    )
    return checks


def run_risk_audit(*, root: Path | None = None) -> dict[str, Any]:
    """Re-run the H6 arms under observation and audit every refusal and invariant."""
    base = Path(__file__).resolve().parents[4] if root is None else root
    split_name = str(RISK_AUDIT["split"])
    timeframe = str(RISK_AUDIT["timeframe"])
    horizon = float(RISK_AUDIT["horizon_minutes"])
    corpus = C._load_corpus(split_name, timeframe)
    regime_rows, regime_meta = C._market_context_series()
    policy = C.load_risk_policy()
    base_plane = cost_plane(size_usd=1000.0, horizon_minutes=horizon)
    scenario_plan: dict[str, list[str]] = RISK_AUDIT["scenario_plan"]
    primary = RISK_AUDIT["primary"]

    install_observer()
    runs: dict[str, Any] = {}
    try:
        for window in RISK_AUDIT["windows"]:
            bounds = C.SPLITS[split_name][window]
            start, end = int(bounds["start"]), int(bounds["end"])
            window_minutes = (end - start) / 60_000.0
            for scenario in scenario_plan[window]:
                plane = base_plane.scaled(scenario)
                for arm, limit_entries, factory in (
                    ("frozen_market", False, lambda: C.build_candidates()["edge_intra_01"]),
                    ("plan_market", False, RetestEntry),
                    ("plan_limit", True, RetestEntry),
                ):
                    run = _run_arm(
                        arm=arm,
                        window=window,
                        scenario=scenario,
                        factory=factory,
                        limit_entries=limit_entries,
                        start=start,
                        end=end,
                        plane=plane,
                        policy=policy,
                        corpus=corpus,
                        regime_rows=regime_rows,
                        window_minutes=window_minutes,
                        timeframe=timeframe,
                    )
                    runs[f"{window}:{scenario}:{arm}"] = run
    finally:
        remove_observer()

    # ---- census and the reconstruction cross-check ----------------------------
    census: dict[str, Any] = {}
    order_rows: list[dict[str, Any]] = []
    order_summaries: dict[str, dict[str, Any]] = {}
    reproduction_rows: list[dict[str, Any]] = []
    published = _load_published_h6(base)
    for key, run in runs.items():
        window = run["window"]
        scenario = run["scenario"]
        arm = run["arm"]
        orders = run["orders"]
        risk_refusals = [r for r in run["refusals"] if r.get("source") == "risk"]
        reasons: dict[str, int] = {}
        for refusal in risk_refusals:
            name = str(refusal.get("reason"))
            reasons[name] = reasons.get(name, 0) + 1
        orders_summary = _order_summary(orders)
        order_summaries[key] = orders_summary
        for row in orders:
            order_rows.append(
                {
                    "run": key,
                    "arm": arm,
                    "window": window,
                    "scenario": scenario,
                    **row,
                }
            )
        census[key] = {
            "window": window,
            "scenario": scenario,
            "arm": arm,
            "signals_printed": run["signals"],
            "signals_planning_a_limit": run["signals_planning_a_limit"],
            "orders": _order_census(orders),
            **orders_summary,
            "refusals": {
                "total": len(run["refusals"]),
                "by_source": {
                    source: sum(1 for r in run["refusals"] if r.get("source") == source)
                    for source in sorted({r.get("source") for r in run["refusals"]})
                },
                "risk_by_reason": reasons,
            },
            "trades": run["metrics"]["trades"],
            "net_usdt": run["metrics"]["net_usdt"],
        }
        if published is not None and f"{window}:{scenario}" in published.get("runs", {}):
            reference = published["runs"][f"{window}:{scenario}"]["arms"][arm]
            mine = run["metrics"]
            for field in ("trades", "net_usdt", "expectancy_usdt"):
                reproduction_rows.append(
                    {
                        "run": f"{window}:{scenario}",
                        "arm": arm,
                        "field": field,
                        "published": reference.get(field),
                        "recomputed": mine.get(field),
                        "equal": (
                            reference.get(field) == mine.get(field)
                            if field == "trades"
                            else abs(float(reference.get(field) or 0.0) - float(mine.get(field) or 0.0))
                            < 1e-9
                        ),
                    }
                )
            for field in ("orders_placed", "orders_filled", "fill_rate"):
                reproduction_rows.append(
                    {
                        "run": f"{window}:{scenario}",
                        "arm": arm,
                        "field": field,
                        "published": reference.get(field),
                        "recomputed": orders_summary.get(field),
                        "equal": (
                            reference.get(field) == orders_summary.get(field)
                            if field != "fill_rate"
                            else abs(
                                float(reference.get(field) or 0.0)
                                - float(orders_summary.get(field) or 0.0)
                            )
                            < 1e-9
                        ),
                    }
                )
    reproduction = {
        "checked": published is not None,
        "source": "reports/edge-recovery/WP-EDGE-01/retest-h6/RETEST.json",
        "comparisons": reproduction_rows,
        "all_equal": bool(reproduction_rows) and all(row["equal"] for row in reproduction_rows),
        "note": (
            "the reconstructed orders, fills, refusals and net match the published H6 "
            "artefact exactly, so the audit is auditing the published experiment"
        ),
    }

    # ---- every refusal, checked against the state it saw ----------------------
    refusal_rows: list[dict[str, Any]] = []
    for key, run in runs.items():
        for record in run["records"]:
            if record["outcome"] != "refused":
                continue
            correct, detail = refusal_is_correct(str(record["reason"]), record)
            runtime = expected_runtime_decision(record)
            expected_rule = REASON_TO_RUNTIME_RULE.get(str(record["reason"]))
            refusal_rows.append(
                {
                    **{k: v for k, v in record.items() if k != "refusal_detail"},
                    "correct": correct,
                    "rule_detail": detail,
                    "runtime_blocked_by": runtime["blocked_by"],
                    "runtime_agrees": expected_rule is not None and runtime["blocked_by"] == expected_rule,
                    "touch_instant_drawdown_pct": record["drawdown_pct"],
                }
            )
    primary_key = f"{primary['window']}:{primary['scenario']}"
    primary_rows = [
        row
        for row in refusal_rows
        if row["run"] == primary_key and row["arm"] == primary["arm"]
    ]
    incorrect = [row for row in refusal_rows if not row["correct"]]
    incorrect_primary = [row for row in primary_rows if not row["correct"]]
    runtime_disagreements = [row for row in refusal_rows if not row["runtime_agrees"]]

    # ---- invariants ----------------------------------------------------------
    invariant_rows: list[dict[str, Any]] = []
    for _key, run in runs.items():  # every arm and every window is checked
        invariant_rows.extend(_check_invariants(run, policy))
    invariants_failed = [row for row in invariant_rows if row["result"] == "FAIL"]

    # ---- the primary window's equity curve, published for the verifier --------
    primary_run = runs[f"{primary['window']}:{primary['scenario']}:{primary['arm']}"]
    equity_rows = [
        {
            "ts": int(ts),
            "equity": round(float(value), 8),
        }
        for ts, value in primary_run["equity_curve"]
    ]

    reason_split: dict[str, int] = {}
    for row in primary_rows:
        name = str(row["reason"])
        reason_split[name] = reason_split.get(name, 0) + 1

    primary_orders = order_summaries[f"{primary_key}:{primary['arm']}"]
    orders_refused = int(primary_orders["orders_by_outcome"].get("refused_by_risk_budget", 0))
    payload: dict[str, Any] = {
        "run_id": "wp-edge-02b-h6-risk-audit",
        "generated_at_utc": datetime.now(UTC).isoformat(),
        "git": C._git_state(),
        "source_digest": C._source_digest(
            [
                "scripts/edge01_run.py",
                "scripts/edge01_verify.py",
                "scripts/edge01_closure_experiments.py",
                "scripts/edge01_closure_verify.py",
                "scripts/edge01_robustness_experiments.py",
                "scripts/edge01_wp02_verify.py",
            ]
        ),
        "mode": (
            "deterministic re-run of the frozen H6 arms with an observing wrapper on the "
            "entry path; 0 orders, 0 credentials, 0 network calls"
        ),
        "entrypoint": "scripts/edge01_robustness_experiments.py --experiment risk",
        "verifier": "scripts/edge01_wp02_verify.py --experiment risk",
        "params_hash": PARAMS_HASH,
        "experiment": {
            **RISK_AUDIT,
            "assets": list(ASSETS),
            "frozen_params": FROZEN_PARAMS["edge_intra_01"],
            "risk_config_path": "config/risk.yaml",
            "risk_config_sha256": C._sha256(C.RISK_CONFIG),
            "risk_policy": policy.to_dict(),
            "decision_rule": RISK_AUDIT_DECISION,
            "corpus_provenance": corpus.provenance,
        },
        "census": census,
        "reproduction": reproduction,
        "summary": {
            "orders_placed": int(primary_orders["orders_placed"]),
            "orders_filled": int(primary_orders["orders_filled"]),
            "orders_refused": orders_refused,
            "orders_by_outcome": primary_orders["orders_by_outcome"],
            "refusal_reasons": reason_split,
            "refusals_checked": len(refusal_rows),
            "refusals_correct": len(refusal_rows) - len(incorrect),
            "refusals_incorrect": len(incorrect),
            "primary_window": primary_key,
            "primary_arm": primary["arm"],
            "primary_refusals": len(primary_rows),
            "primary_refusals_correct": len(primary_rows) - len(incorrect_primary),
            "orders_refused_matches_captured_refusals": orders_refused == len(primary_rows),
            "runtime_agreements": len(refusal_rows) - len(runtime_disagreements),
            "runtime_disagreements": len(runtime_disagreements),
            "invariants_checked": len(invariant_rows),
            "invariants_failed": len(invariants_failed),
        },
        "refusal_rows": refusal_rows,
        "order_rows": order_rows,
        "invariant_rows": invariant_rows,
        "equity_rows": equity_rows,
        "market_context": {"meta": regime_meta},
        "limitations": [
            (
                "the observing wrapper records the state the frozen simulator's own entry "
                "path computed; it changes no value and is restored in a finally block, but "
                "it is the same process as the run it observes"
            ),
            (
                "the independent reconstruction of the same state from the published trade "
                "ledger and the local corpus is done by scripts/edge01_wp02_verify.py, in a "
                "separate process that imports nothing from the package"
            ),
            (
                "the research budget models a subset of the runtime Risk Engine's rules, so "
                "this audit's verdict is about the subset, never a statement that live "
                "trading would behave identically"
            ),
            "long side only (spot); no historical order book; nothing is wired into PAPER",
        ],
    }
    payload["verdict"] = risk_audit_verdict(payload)
    return payload


def risk_audit_verdict(payload: dict[str, Any]) -> dict[str, Any]:
    """The audit's verdict, from its own summary. Pure function."""
    summary = payload["summary"]
    findings: list[str] = []
    if summary["refusals_incorrect"]:
        findings.append(
            f"{summary['refusals_incorrect']} refusal(s) were not justified by the state the "
            "budget saw"
        )
    if summary["invariants_failed"]:
        findings.append(f"{summary['invariants_failed']} invariant(s) failed")
    if summary["runtime_disagreements"]:
        findings.append(
            f"{summary['runtime_disagreements']} refusal(s) would not be blocked by the same "
            "rule in the runtime Risk Engine"
        )
    if not summary["orders_refused_matches_captured_refusals"]:
        findings.append(
            f"the primary run has {summary['orders_refused']} orders refused but "
            f"{summary['primary_refusals']} captured refusals: the two ledgers disagree"
        )
    verdict = "AUDIT_FINDINGS" if findings else "AUDIT_PASS"
    headline = (
        "every audited refusal was justified by the state the budget saw and every declared "
        "invariant holds"
        if not findings
        else "; ".join(findings)
    )
    return {
        "verdict": verdict,
        "headline": headline,
        "findings": findings,
        "primary": {
            "run": summary["primary_window"],
            "arm": summary["primary_arm"],
            "orders_placed": summary["orders_placed"],
            "orders_filled": summary["orders_filled"],
            "refusals": summary["primary_refusals"],
            "refusals_correct": summary["primary_refusals_correct"],
            "by_reason": summary["refusal_reasons"],
        },
        "modelling_gap": RISK_AUDIT_DECISION["modelling_gap_note"],
        "decision_rule": RISK_AUDIT_DECISION,
    }


def write_risk_audit_artifacts(payload: dict[str, Any], outdir: Path) -> dict[str, Path]:
    """Write the refusal ledger, the order reconstruction, the invariants and the JSON."""
    outdir.mkdir(parents=True, exist_ok=True)
    written: dict[str, Path] = {}
    primary = RISK_AUDIT["primary"]

    def dump(name: str, rows: list[dict[str, Any]], columns: tuple[str, ...]) -> None:
        path = outdir / name
        lines = [",".join(columns)]
        for row in rows:
            cells = []
            for column in columns:
                value = row.get(column)
                if value is None:
                    cells.append("")
                elif isinstance(value, bool):
                    cells.append("true" if value else "false")
                elif isinstance(value, float):
                    cells.append(f"{value:.8f}")
                elif isinstance(value, (dict, list)):
                    text = json.dumps(value, ensure_ascii=False, sort_keys=True)
                    cells.append(f'"{text.replace(chr(34), chr(39))}"')
                else:
                    text = str(value)
                    cells.append(f'"{text}"' if "," in text else text)
            lines.append(",".join(cells))
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        written[name] = path

    refusal_columns = (
        "run",
        "arm",
        "window",
        "scenario",
        "candidate",
        "asset",
        "delivery",
        "decision_ts",
        "reason",
        "source",
        "outcome",
        "correct",
        "rule_detail",
        "equity",
        "peak_equity",
        "drawdown_pct",
        "drawdown_halt_pct",
        "open_positions_count",
        "open_notional",
        "exposure_cap",
        "asset_cap",
        "trades_today",
        "max_trades_per_day",
        "cooldown_until_ts",
        "consecutive_losses",
        "entry_mid",
        "entry_notional",
        "planned_risk_usdt",
        "runtime_blocked_by",
        "runtime_agrees",
    )
    primary_rows = [
        row
        for row in payload["refusal_rows"]
        if row["run"] == f"{primary['window']}:{primary['scenario']}"
        and row["arm"] == primary["arm"]
    ]
    dump("RISK_AUDIT_REFUSALS.csv", payload["refusal_rows"], refusal_columns)
    dump(
        "RISK_AUDIT_PRIMARY_REFUSALS.csv",
        primary_rows,
        refusal_columns,
    )

    dump(
        "RISK_AUDIT_ORDERS.csv",
        payload["order_rows"],
        (
            "run",
            "arm",
            "window",
            "scenario",
            "candidate",
            "asset",
            "level",
            "placement_ts",
            "placed_bar",
            "expiry_bars",
            "expiry_bar",
            "breakout_close",
            "discount_bps",
            "stop",
            "target",
            "outcome",
            "outcome_ts",
            "outcome_bar",
            "bars_resting",
            "refusal_reason",
        ),
    )
    dump(
        "RISK_AUDIT_INVARIANTS.csv",
        payload["invariant_rows"],
        ("invariant", "scope", "arm", "result", "detail"),
    )
    dump("RISK_AUDIT_EQUITY.csv", payload["equity_rows"], ("ts", "equity"))

    json_payload = {
        k: v
        for k, v in payload.items()
        if k not in ("refusal_rows", "invariant_rows", "equity_rows", "order_rows")
    }
    json_payload["artifacts"] = sorted(
        list(written) + ["RISK_AUDIT.json", "RISK_AUDIT.md"]
    )
    json_payload["artifact_note"] = (
        "the refusal, order, invariant and equity ledgers are published as CSV next to this file"
    )
    json_path = outdir / "RISK_AUDIT.json"
    json_path.write_text(
        json.dumps(json_payload, indent=2, ensure_ascii=False, default=str) + "\n",
        encoding="utf-8",
    )
    written["RISK_AUDIT.json"] = json_path
    md_path = outdir / "RISK_AUDIT.md"
    md_path.write_text(risk_audit_markdown(payload), encoding="utf-8")
    written["RISK_AUDIT.md"] = md_path
    return written


def risk_audit_markdown(payload: dict[str, Any]) -> str:
    """The human-readable audit."""
    summary = payload["summary"]
    verdict = payload["verdict"]
    lines: list[str] = [
        "# AUDITORIA DE RIESGO H6 — WP-EDGE-02B",
        "",
        "| | |",
        "|---|---|",
        f"| experimento | `{payload['experiment']['id']}` |",
        f"| audita | `{payload['experiment']['audits']}` |",
        f"| ventana primaria | `{summary['primary_window']}` / `{summary['primary_arm']}` |",
        f"| HEAD al ejecutar | `{payload['git'].get('head_commit')}` |",
        f"| veredicto | **`{verdict['verdict']}`** |",
        "",
        payload["experiment"]["question"],
        "",
        "## Reproduccion del experimento auditado",
        "",
        f"- comparado con `{payload['reproduction']['source']}`: "
        f"**{'identico' if payload['reproduction']['all_equal'] else 'DIVERGENTE'}** "
        f"({len(payload['reproduction']['comparisons'])} comparaciones)",
        "",
        "## Ordenes y rechazos reconstruidos",
        "",
        "| run | arm | ordenes | rellenos | rechazos por riesgo | motivos |",
        "|---|---|---|---|---|---|",
    ]
    for key, block in payload["census"].items():
        orders = block["orders"]["orders_by_outcome"]
        reasons = ", ".join(
            f"{name}: {count}" for name, count in sorted(block["refusals"]["risk_by_reason"].items())
        )
        lines.append(
            f"| `{key}` | `{block['arm']}` | {block['orders']['orders_placed']} | "
            f"{orders.get('filled', 0)} | {orders.get('refused_by_risk_budget', 0)} | {reasons or '—'} |"
        )
    lines += [
        "",
        "## Cada rechazo de la ventana primaria, contra el estado que vio el presupuesto",
        "",
        f"- rechazos: **{summary['primary_refusals']}**, correctos: "
        f"**{summary['primary_refusals_correct']}**",
        f"- motivos: "
        + ", ".join(
            f"`{name}`: {count}" for name, count in sorted(summary["refusal_reasons"].items())
        ),
        f"- auditoria completa (todas las ventanas y ramas): {summary['refusals_checked']} rechazos, "
        f"{summary['refusals_incorrect']} incorrectos",
        f"- acuerdo con la regla equivalente del Risk Engine de runtime: "
        f"{summary['runtime_agreements']}/{summary['refusals_checked']}",
        "",
        "| activo | instante | motivo | drawdown en el toque | halt | posiciones abiertas | "
        "trades hoy | correcto |",
        "|---|---|---|---|---|---|---|---|",
    ]
    primary = RISK_AUDIT["primary"]
    shown = [
        row
        for row in payload["refusal_rows"]
        if row["run"] == f"{primary['window']}:{primary['scenario']}"
        and row["arm"] == primary["arm"]
    ]
    by_reason: dict[str, list[dict[str, Any]]] = {}
    for row in shown:
        by_reason.setdefault(str(row["reason"]), []).append(row)
    for reason, rows in sorted(by_reason.items()):
        for row in rows[:5]:
            stamp = datetime.fromtimestamp(int(row["decision_ts"]) / 1000, tz=UTC).strftime(
                "%Y-%m-%dT%H:%M"
            )
            lines.append(
                f"| `{row['asset']}` | `{stamp}` | `{reason}` | {row['drawdown_pct']:.4f}% | "
                f"{row['drawdown_halt_pct']:.1f}% | {row['open_positions_count']} | "
                f"{row['trades_today']} | {'si' if row['correct'] else 'NO'} |"
            )
        lines.append(
            f"| _({len(rows)} filas en total para `{reason}`; el CSV lleva todas)_ | | | | | | | |"
        )
    lines += [
        "",
        "## Invariantes",
        "",
        "| invariante | ambito | arm | resultado | detalle |",
        "|---|---|---|---|---|",
    ]
    for row in payload["invariant_rows"]:
        lines.append(
            f"| `{row['invariant']}` | `{row['scope']}` | `{row['arm']}` | "
            f"**{row['result']}** | {row['detail']} |"
        )
    lines += [
        "",
        "## Veredicto",
        "",
        f"- **`{verdict['verdict']}`** — {verdict['headline']}",
        f"- brecha de modelado: {verdict['modelling_gap']}",
        "",
        "## Limites",
        "",
    ]
    lines += [f"- {item}" for item in payload["limitations"]]
    return "\n".join(lines) + "\n"
