"""EDGE-03 risk parity — the research budget against the engine that actually runs.

WP-EDGE-02 compared the research budget's refusals with a *restatement* of the runtime's
rule order (``expected_runtime_decision``). That is a description of the engine, written by
hand, and a description can be wrong in exactly the way it is supposed to catch. This
module does the harder thing: it feeds the **real** ``RiskManager`` from
``src/trading_bot/risk/manager.py`` and the **real** research entry point
(``simulator._enter``) the same state and the same intent, and compares what each decides.

What "the same inputs" means here, precisely:

* the same equity, the same peak (all-time and since the day's open), the same open book —
  per asset and in total —, the same trades-per-day count, the same losing streak and the
  same cooldown deadline, the same instant (ms UTC) and the same kill-switch flag;
* the same intent: the same asset, the same direction, the same stop and the same price —
  expressed once, and then converted for each engine from that one number;
* the same limits: both read ``config/risk.yaml``; neither side is handed a looser copy.

The only asymmetry is *vocabulary*: the research budget names its own refusals
(``risk_drawdown_halt``) and the runtime names its blockers (``max_drawdown``). The mapping
between the two is declared below, before any case ran, so an agreement is not a
coincidence of strings.

Nothing here changes a limit to make the two agree, and nothing here is allowed to be
"fixed" by loosening a rule: a divergence is published under its own class with the state
that produced it.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from trading_bot.config.risk import Risk
from trading_bot.research.edge01 import simulator as SIM
from trading_bot.research.edge01.campaign import RISK_CONFIG, load_risk_policy
from trading_bot.research.edge01.candidates import CandidateSignal
from trading_bot.research.edge01.costs import CostPlane, cost_plane
from trading_bot.research.edge01.data import OHLCVBar
from trading_bot.risk.manager import RiskManager, RiskCheck
from trading_bot.strategies.types import Signal

from .shadow import HORIZON_MINUTES

__all__ = [
    "NOT_MODELLED_BY_RESEARCH",
    "PARITY_DECISION",
    "REASON_TO_RUNTIME_RULE",
    "case_from_capture",
    "compare",
    "declared_cases",
    "load_runtime_risk",
    "research_decision",
    "run_parity",
    "runtime_decision",
    "shadow_cases",
]

#: Research reason -> the runtime rule that fires for the same situation. Declared before
#: the run; a mismatch is reported, never smoothed over.
REASON_TO_RUNTIME_RULE: dict[str, str] = {
    "risk_max_trades_per_day": "daily_trade_limit",
    "risk_max_open_positions": "max_positions",
    "risk_loss_cooldown": "consecutive_loss_cooldown",
    "risk_drawdown_halt": "max_drawdown",
    "risk_exposure_cap": "position_sizing",
    "risk_notional_below_minimum": "position_sizing",
    "position_already_open": "max_positions",
    "stop_above_fill": "position_sizing",
    "fill_price_invalid": "position_sizing",
    "parity_approved": "APPROVED",
}

#: Rules the runtime enforces that the research budget does not model at all. A runtime
#: refusal under one of these is *expected*, not a defect: it means a live run blocks at
#: least as often as the research reading does.
NOT_MODELLED_BY_RESEARCH: tuple[str, ...] = (
    "kill_switch",
    "daily_loss_limit",
    "weekly_loss_limit",
    "daily_drawdown",
)

PARITY_DECISION: dict[str, Any] = {
    "id": "PARITY-EDGE03",
    "question": (
        "Fed identical state and identical intent, do the research budget and the runtime "
        "Risk Engine admit, refuse and size the same entry?"
    ),
    "harness": {
        "runtime": "trading_bot.risk.manager.RiskManager.check_signal (the real engine)",
        "research": "trading_bot.research.edge01.simulator._enter (the real call the "
        "simulator and the WP-EDGE-02 audit used)",
        "shared_authority": "config/risk.yaml, read by both sides for every limit",
        "intent_convention": (
            "the intent is stated once, at the cost-adjusted price the research entry would "
            "actually pay, and the runtime signal's stop_loss_pct is derived from that same "
            "price, so a sizing difference is a policy difference and not a rounding "
            "convention; the identity is asserted by a unit test, not assumed"
        ),
    },
    "classes": {
        "AGREE_APPROVED": "both admit the entry and size it identically (1e-6 USDT)",
        "AGREE_REFUSED_SAME_RULE": "both refuse and the mapped rule is the one that fired",
        "RULE_ORDER_DIFFERS": (
            "both refuse, but each engine names a different rule because their check order "
            "differs; the entry is refused either way"
        ),
        "RULE_NOT_MODELLED_BY_RESEARCH": (
            "the runtime refuses under a rule the research budget does not implement; a live "
            "run is therefore at least as strict as the reading"
        ),
        "RESEARCH_ONLY_REFUSAL": (
            "the research budget refuses where the runtime admits; the research side is "
            "stricter (a floor/cap convention or a cooldown that outlives the streak)"
        ),
        "SIZING_ROUNDING_ONLY": (
            "both admit the entry and the two sizes agree to within half a cent: the runtime "
            "publishes PositionSize.notional_usdt rounded to 2 decimals, so this is a "
            "presentation difference and not a policy one"
        ),
        "SIZING_DIFFERS": (
            "both admit the entry and size it differently by MORE than the runtime's own cent "
            "rounding (1e-6 USDT is the arithmetic tolerance; anything above 0.005 USDT is a "
            "policy difference)"
        ),
        "PARITY_DEFECT": (
            "the research budget admits an entry the runtime refuses under a rule BOTH "
            "implement, or the captured decision is not reproduced from its own state"
        ),
    },
    "tolerances": {
        "notional_usdt": 1e-6,
        "runtime_published_rounding_usdt": 0.005,
        "price": 1e-9,
        "note": (
            "the arithmetic tolerance is 1e-6 USDT; the runtime's published notional is "
            "rounded to cents, so a gap at or below half a cent is classified as "
            "SIZING_ROUNDING_ONLY and anything larger stays a substantive divergence"
        ),
    },
    "verdicts": {
        "PARITY_PASS": (
            "zero PARITY_DEFECT across the declared cases and every captured shadow "
            "decision is reproduced from its own state"
        ),
        "PARITY_FINDINGS": "at least one PARITY_DEFECT",
    },
    "not_claimed": (
        "parity between two risk models says nothing about profit; no limit is changed by "
        "this comparison and nothing here promotes a strategy"
    ),
}


# --------------------------------------------------------------------------- inputs
def load_runtime_risk() -> Risk:
    """The runtime's own policy object, validated by its own pydantic model."""
    payload = yaml.safe_load(RISK_CONFIG.read_text(encoding="utf-8"))["risk"]
    return Risk(**payload)


def _entry_fill(plane: CostPlane, mid: float) -> float:
    """The price a market intent actually pays, exactly as ``_enter`` computes it."""
    return mid * (
        1
        + plane.spread_bps / 2 / 10_000
        + plane.slippage_bps / 2 / 10_000
        + plane.impact_bps / 2 / 10_000
    )


def _research_signal(state: dict[str, Any]) -> CandidateSignal:
    return CandidateSignal(
        candidate=str(state.get("candidate") or "parity"),
        symbol=str(state["asset"]),
        bar_index=0,
        decision_ts=int(state["decision_ts"]),
        decision_timeframe=str(state.get("timeframe") or "4h"),
        entry_reference=float(state["entry_mid"]),
        direction="LONG",
        stop=float(state["stop"]),
        targets=tuple(float(t) for t in state.get("targets") or ()),
        invalidations=(),
        risk_reward=1.0,
        expected_gross_bps=0.0,
        expected_cost_bps=0.0,
        expected_net_bps=0.0,
        regime=str(state.get("regime") or "PARITY"),
    )


def _open_positions_for_research(state: dict[str, Any]) -> dict[str, Any]:
    """Rebuild the book the research budget measures itself against.

    Only ``qty * entry_fill`` (the notional, for the exposure caps) and membership matter
    to ``_enter``, so the pair is chosen to reproduce the recorded notional exactly.
    """
    by_asset = state.get("open_notional_by_asset")
    if by_asset is None:
        total = float(state.get("open_positions_notional") or 0.0)
        assets = list(state.get("open_assets") or [])
        if not assets or total <= 0:
            return {}
        share = total / len(assets)
        by_asset = {asset: share for asset in assets}
    return {
        str(asset): _position(str(asset), float(notional))
        for asset, notional in by_asset.items()
        if float(notional) > 0
    }


def _position(asset: str, notional: float) -> SIM.Position:
    return SIM.Position(
        asset=asset,
        candidate="parity",
        signal_bar=0,
        decision_ts=0,
        entry_bar=0,
        entry_ts=0,
        entry_mid=1.0,
        entry_fill=1.0,
        qty=notional,
        notional=notional,
        initial_stop=0.0,
        stop=0.0,
        stop_distance=0.0,
        targets=(),
        hard_invalidation=None,
        trailing_atr=None,
        trailing_atr_value=None,
        exit_ema_period=None,
        regime="PARITY",
        expected_gross_bps=0.0,
        expected_cost_bps=0.0,
        planned_risk_usdt=0.0,
        price_cost_half_bps=0.0,
        fee_bps=0.0,
    )


def _gate(state: dict[str, Any]) -> SIM._Gate:
    return SIM._Gate(
        peak_equity=float(state.get("peak_equity") or state.get("equity") or 0.0),
        day_key=-1,
        trades_today=int(state.get("trades_today") or 0),
        consecutive_losses=int(state.get("consecutive_losses") or 0),
        cooldown_until_ts=int(state.get("cooldown_until_ts") or 0),
    )


def research_decision(
    state: dict[str, Any],
    *,
    policy: SIM.RiskPolicy,
    plane: CostPlane,
) -> dict[str, Any]:
    """Ask the REAL research entry point what it does with this state and intent."""
    positions = _open_positions_for_research(state)
    asset = str(state["asset"])
    if bool(state.get("asset_held")) and asset not in positions:
        # ``asset_held`` with no recorded notional still means the asset is held; the
        # research budget refuses on membership alone, so a nominal slot is enough.
        positions[asset] = _position(asset, 1.0)
    result = SIM.PortfolioResult()
    mid = float(state["entry_mid"])
    before = len(result.refusals)
    bar = OHLCVBar(ts=int(state["decision_ts"]), open=mid, high=mid, low=mid, close=mid, volume=0.0)
    SIM._enter(
        _research_signal(state),
        bar=bar,
        idx=0,
        ts=int(state["decision_ts"]),
        mid=mid,
        positions=positions,
        result=result,
        policy=policy,
        plane=plane,
        gate=_gate(state),
        equity=float(state["equity"]),
    )
    if len(result.refusals) > before:
        refusal = result.refusals[-1]
        return {
            "approved": False,
            "reason": str(refusal.get("reason")),
            "notional": None,
            "quantity": None,
            "entry_fill": None,
            "detail": refusal.get("detail") or {},
        }
    position = positions[str(state["asset"])]
    return {
        "approved": True,
        "reason": "parity_approved",
        "notional": float(position.notional),
        "quantity": float(position.qty),
        "entry_fill": float(position.entry_fill),
        "detail": {},
    }


def runtime_decision(state: dict[str, Any], *, risk: Risk, plane: CostPlane) -> dict[str, Any]:
    """Ask the REAL runtime engine what it does with the same state and intent."""
    mid = float(state["entry_mid"])
    fill = _entry_fill(plane, mid)
    stop = float(state["stop"])
    stop_distance = fill - stop
    signal = Signal(
        symbol=f"{state['asset']}/USDT",
        side="buy",
        strategy_name=str(state.get("candidate") or "parity"),
        timeframe=str(state.get("timeframe") or "4h"),
        confidence=1.0,
        price=fill,
        stop_loss_pct=(stop_distance / fill * 100.0) if fill > 0 else None,
        take_profit_pct=(
            (float(state["targets"][0]) - fill) / fill * 100.0
            if state.get("targets") and fill > 0
            else None
        ),
        metadata={},
    )
    book = {
        str(asset): {"asset": str(asset), "notional_usdt": float(notional)}
        for asset, notional in (state.get("open_notional_by_asset") or {}).items()
        if float(notional) > 0
    }
    if not book:
        for asset in state.get("open_assets") or []:
            total = float(state.get("open_positions_notional") or 0.0)
            if total > 0:
                book[str(asset)] = {"asset": str(asset), "notional_usdt": total / len(state["open_assets"])}
    manager = RiskManager(
        risk=risk,
        equity=float(state["equity"]),
        open_positions=book,
        daily_pnl=float(state.get("daily_pnl") or 0.0),
        weekly_pnl=float(state.get("weekly_pnl") or 0.0),
        trades_today=int(state.get("trades_today") or 0),
        consecutive_losses=int(state.get("consecutive_losses") or 0),
        peak_equity=float(state.get("peak_equity") or state.get("equity") or 0.0),
        day_peak_equity=float(
            state.get("day_peak_equity") or state.get("peak_equity") or state.get("equity") or 0.0
        ),
        # Both engines must see the SAME deadline. The research budget compares the instant
        # with an absolute ``cooldown_until_ts``; the runtime compares an elapsed time with
        # ``_last_loss_ms``. The anchor is therefore derived from the deadline with the
        # configured window, so the two rules are the same rule expressed twice.
        _last_loss_ms=max(
            0,
            int(state.get("cooldown_until_ts") or 0)
            - int(risk.consecutive_loss_cooldown_minutes) * 60_000,
        ),
        _kill_switch_active=bool(state.get("kill_switch")),
        _clock=lambda: int(state["decision_ts"]) / 1000.0,
    )
    check: RiskCheck = manager.check_signal(signal)
    return {
        "approved": bool(check.approved),
        "blocked_by": check.blocked_by,
        "reason": check.reason,
        "notional": float(check.position_size.notional_usdt) if check.position_size else None,
        "quantity": float(check.position_size.quantity) if check.position_size else None,
    }


# ------------------------------------------------------------------------ comparison
@dataclass(frozen=True, slots=True)
class Comparison:
    """One case, both decisions, and the class the pair falls into."""

    case_id: str
    origin: str
    klass: str
    detail: str
    state: dict[str, Any]
    research: dict[str, Any]
    runtime: dict[str, Any]

    def to_row(self) -> dict[str, Any]:
        return {
            "case_id": self.case_id,
            "origin": self.origin,
            "class": self.klass,
            "detail": self.detail,
            "asset": self.state.get("asset"),
            "decision_ts": self.state.get("decision_ts"),
            "research_decision": "APPROVED" if self.research["approved"] else "REFUSED",
            "research_reason": self.research["reason"],
            "research_notional": self.research["notional"],
            "runtime_decision": "APPROVED" if self.runtime["approved"] else "REFUSED",
            "runtime_blocked_by": self.runtime.get("blocked_by"),
            "runtime_notional": self.runtime["notional"],
            "equity": self.state.get("equity"),
            "peak_equity": self.state.get("peak_equity"),
            "drawdown_pct": self.state.get("drawdown_pct"),
            "open_positions_count": self.state.get("open_positions_count"),
            "trades_today": self.state.get("trades_today"),
            "consecutive_losses": self.state.get("consecutive_losses"),
            "daily_pnl": self.state.get("daily_pnl"),
            "weekly_pnl": self.state.get("weekly_pnl"),
            "kill_switch": self.state.get("kill_switch"),
        }


def compare(
    case_id: str,
    origin: str,
    state: dict[str, Any],
    *,
    policy: SIM.RiskPolicy,
    risk: Risk,
    plane: CostPlane,
    tolerance: float = 1e-6,
) -> Comparison:
    """Run both engines on one case and classify the pair. No side is told the other's answer."""
    research = research_decision(state, policy=policy, plane=plane)
    runtime = runtime_decision(state, risk=risk, plane=plane)
    klass, detail = _classify(
        research,
        runtime,
        tolerance=tolerance,
        rounding=float(PARITY_DECISION["tolerances"]["runtime_published_rounding_usdt"]),
    )
    return Comparison(
        case_id=case_id,
        origin=origin,
        klass=klass,
        detail=detail,
        state=state,
        research=research,
        runtime=runtime,
    )


def _classify(
    research: dict[str, Any],
    runtime: dict[str, Any],
    *,
    tolerance: float,
    rounding: float = 0.005,
) -> tuple[str, str]:
    if research["approved"] and runtime["approved"]:
        gap = abs(float(research["notional"]) - float(runtime["notional"]))
        if gap <= tolerance:
            return "AGREE_APPROVED", f"notional {research['notional']:.6f} USDT on both sides"
        if gap <= rounding:
            return (
                "SIZING_ROUNDING_ONLY",
                f"research {research['notional']:.6f} vs runtime {runtime['notional']:.2f} "
                f"(gap {gap:.6f} USDT, inside the runtime's published cent rounding)",
            )
        return (
            "SIZING_DIFFERS",
            f"research {research['notional']:.6f} vs runtime {runtime['notional']:.6f} "
            f"(gap {gap:.6f} USDT)",
        )
    if not research["approved"] and not runtime["approved"]:
        mapped = REASON_TO_RUNTIME_RULE.get(str(research["reason"]), "UNMAPPED")
        if mapped == runtime.get("blocked_by"):
            return (
                "AGREE_REFUSED_SAME_RULE",
                f"both refuse under {mapped}",
            )
        return (
            "RULE_ORDER_DIFFERS",
            f"research fired {research['reason']} (maps to {mapped}), runtime fired "
            f"{runtime.get('blocked_by')}: both refuse, different rule named first",
        )
    if research["approved"] and not runtime["approved"]:
        blocker = str(runtime.get("blocked_by"))
        if blocker in NOT_MODELLED_BY_RESEARCH:
            return (
                "RULE_NOT_MODELLED_BY_RESEARCH",
                f"the runtime refuses under {blocker}, which the research budget does not model",
            )
        return (
            "PARITY_DEFECT",
            f"the research budget admits the entry the runtime refuses under {blocker}, a "
            f"rule both implement",
        )
    return (
        "RESEARCH_ONLY_REFUSAL",
        f"the research budget refuses ({research['reason']}) where the runtime admits the entry",
    )


# ----------------------------------------------------------------------------- cases
class _Sweep:
    """Deterministic pseudo-random sweep: same seed, same cases, on every machine."""

    def __init__(self, seed: int = 0x51ED_0301) -> None:
        self.state = seed & 0xFFFF_FFFF_FFFF_FFFF or 1

    def next(self) -> float:
        x = self.state
        x ^= (x << 13) & 0xFFFF_FFFF_FFFF_FFFF
        x ^= x >> 7
        x ^= (x << 17) & 0xFFFF_FFFF_FFFF_FFFF
        self.state = x & 0xFFFF_FFFF_FFFF_FFFF
        return (self.state >> 11) / float(1 << 53)

    def pick(self, values: list[Any]) -> Any:
        return values[int(self.next() * len(values)) % len(values)]


def _case(
    *,
    case_id: str,
    equity: float,
    peak_equity: float,
    day_peak_equity: float | None = None,
    open_notional_by_asset: dict[str, float] | None = None,
    trades_today: int = 0,
    consecutive_losses: int = 0,
    cooldown_until_ts: int = 0,
    daily_pnl: float = 0.0,
    weekly_pnl: float = 0.0,
    kill_switch: bool = False,
    asset: str = "BTC",
    entry_mid: float = 50_000.0,
    stop: float = 49_000.0,
    targets: tuple[float, ...] = (52_000.0,),
    decision_ts: int = 1_791_372_600_000,
    candidate: str = "edge_trend_01",
    timeframe: str = "4h",
) -> dict[str, Any]:
    book = dict(open_notional_by_asset or {})
    drawdown = (peak_equity - equity) / peak_equity * 100.0 if peak_equity > 0 else 0.0
    return {
        "case_id": case_id,
        "equity": round(equity, 6),
        "peak_equity": round(peak_equity, 6),
        "day_peak_equity": round(day_peak_equity if day_peak_equity is not None else peak_equity, 6),
        "open_notional_by_asset": {k: round(v, 6) for k, v in book.items()},
        "open_assets": sorted(book),
        "open_positions_count": len(book),
        "open_positions_notional": round(sum(book.values()), 6),
        "asset_held": asset in book,
        "trades_today": int(trades_today),
        "consecutive_losses": int(consecutive_losses),
        "cooldown_until_ts": int(cooldown_until_ts),
        "daily_pnl": round(daily_pnl, 6),
        "weekly_pnl": round(weekly_pnl, 6),
        "kill_switch": bool(kill_switch),
        "drawdown_pct": round(drawdown, 6),
        "asset": asset,
        "candidate": candidate,
        "timeframe": timeframe,
        "entry_mid": round(entry_mid, 8),
        "stop": round(stop, 8),
        "targets": [round(t, 8) for t in targets],
        "decision_ts": int(decision_ts),
    }


def declared_cases(*, sweep_cases: int = 384, seed: int = 0x51ED_0301) -> list[dict[str, Any]]:
    """Every shared limit at its boundary, plus a deterministic sweep of the combinations.

    The boundary cases are the ones where an off-by-one lives; the sweep is what catches a
    rule that only misbehaves when two limits are close at the same time.
    """
    cases: list[dict[str, Any]] = []
    equity = 10_000.0
    # -- drawdown halt (5% of peak)
    for dd in (0.0, 4.99, 5.0, 5.01, 6.0):
        cases.append(
            _case(
                case_id=f"boundary:drawdown:{dd}",
                equity=equity * (1 - dd / 100.0),
                peak_equity=equity,
                day_peak_equity=equity,
            )
        )
    # -- open positions (3)
    for count in (0, 2, 3, 4):
        book = {f"A{i}": 1_000.0 for i in range(count)}
        cases.append(
            _case(case_id=f"boundary:positions:{count}", equity=equity, peak_equity=equity, open_notional_by_asset=book)
        )
    # -- trades per day (20)
    for traded in (0, 19, 20, 21):
        cases.append(
            _case(case_id=f"boundary:trades_per_day:{traded}", equity=equity, peak_equity=equity, trades_today=traded)
        )
    # -- losing streak and its cooldown (3 losses, 60 min)
    ts = 1_791_372_600_000
    for streak in (0, 2, 3, 5):
        for minutes in (None, 61.0, 60.0, 59.0, 1.0):
            deadline = 0 if minutes is None else ts + int(minutes * 60_000)
            cases.append(
                _case(
                    case_id=f"boundary:cooldown:streak{streak}:{minutes}",
                    equity=equity,
                    peak_equity=equity,
                    consecutive_losses=streak,
                    cooldown_until_ts=deadline,
                    decision_ts=ts,
                )
            )
    # -- daily and weekly loss limits, which only the runtime models
    for pct in (0.5, 0.99, 1.0, 1.01, 1.5):
        cases.append(
            _case(
                case_id=f"boundary:daily_loss:{pct}",
                equity=equity,
                peak_equity=equity,
                daily_pnl=-equity * pct / 100.0,
            )
        )
    for pct in (1.0, 2.99, 3.0, 3.01, 4.0):
        cases.append(
            _case(
                case_id=f"boundary:weekly_loss:{pct}",
                equity=equity,
                peak_equity=equity,
                weekly_pnl=-equity * pct / 100.0,
            )
        )
    # -- daily drawdown (2% since the day's open), also runtime-only
    for pct in (1.0, 1.99, 2.0, 2.01, 3.0):
        cases.append(
            _case(
                case_id=f"boundary:daily_drawdown:{pct}",
                equity=equity * (1 - pct / 100.0),
                peak_equity=equity,
                day_peak_equity=equity,
            )
        )
    # -- the order-book floor: a stop so wide the risk-sized notional falls under 20 USDT
    cases.append(
        _case(
            case_id="boundary:notional_floor",
            equity=equity,
            peak_equity=equity,
            entry_mid=50_000.0,
            stop=2_000.0,
            targets=(90_000.0,),
        )
    )
    # -- the exposure cap (25% of equity) with the book already near it
    for used in (0.0, 2_000.0, 2_499.0, 2_500.0, 2_600.0):
        book = {"BTC": used} if used else {}
        cases.append(
            _case(
                case_id=f"boundary:exposure:{used}",
                equity=equity,
                peak_equity=equity,
                open_notional_by_asset=book,
            )
        )
    # -- the per-asset cap (10%) with the asset itself already loaded
    for used in (900.0, 999.0, 1_000.0, 1_100.0):
        cases.append(
            _case(
                case_id=f"boundary:asset_cap:{used}",
                equity=equity,
                peak_equity=equity,
                open_notional_by_asset={"BTC": used},
            )
        )
    # -- kill switch (runtime-only)
    cases.append(
        _case(case_id="boundary:kill_switch", equity=equity, peak_equity=equity, kill_switch=True)
    )

    # -- deterministic sweep over the same dimensions
    sweep = _Sweep(seed)
    for index in range(sweep_cases):
        dd = sweep.pick([0.0, 1.0, 2.5, 4.9, 5.0, 5.2, 8.0])
        peak = equity
        current = peak * (1 - dd / 100.0)
        count = sweep.pick([0, 1, 2, 3, 4])
        book = {f"B{i}": round(sweep.next() * 2_500.0, 2) for i in range(count)}
        streak = sweep.pick([0, 1, 2, 3, 4])
        minutes = sweep.pick([None, 0.0, 5.0, 59.0, 60.0, 61.0, 120.0])
        # The stop is stated as a distance BELOW the entry rather than as an independent
        # price, so a swept case is a real intent and not an accidental stop-above-fill.
        mid = sweep.pick([150.0, 2_500.0, 50_000.0])
        stop_pct = sweep.pick([0.5, 1.0, 2.0, 5.0, 25.0, 60.0])
        target_pct = sweep.pick([1.0, 2.0, 5.0, 20.0, 60.0])
        cases.append(
            _case(
                case_id=f"sweep:{index:04d}",
                equity=current,
                peak_equity=peak,
                day_peak_equity=peak * (1 - sweep.pick([0.0, 0.5, 1.0, 2.0, 2.5]) / 100.0),
                open_notional_by_asset=book,
                trades_today=sweep.pick([0, 5, 18, 19, 20, 21, 30]),
                consecutive_losses=streak,
                cooldown_until_ts=(
                    0 if minutes is None else ts + int(minutes * 60_000)
                ),
                daily_pnl=-peak * sweep.pick([0.0, 0.4, 0.9, 1.0, 1.2]) / 100.0,
                weekly_pnl=-peak * sweep.pick([0.0, 1.5, 2.9, 3.0, 3.5]) / 100.0,
                kill_switch=sweep.pick([False, False, False, True]),
                asset=sweep.pick(["BTC", "ETH", "SOL"]),
                entry_mid=mid,
                stop=mid * (1.0 - stop_pct / 100.0),
                targets=(mid * (1.0 + target_pct / 100.0),),
                decision_ts=ts + index * 60_000,
            )
        )
    return cases


def case_from_capture(capture: dict[str, Any], *, index: int) -> dict[str, Any]:
    """Turn one shadow decision into a parity case, keeping the instant it happened at."""
    return {
        "case_id": f"shadow:{index:04d}:{capture.get('arm')}:{capture.get('asset')}",
        "equity": float(capture["equity"]),
        "peak_equity": float(capture["peak_equity"]),
        "day_peak_equity": float(capture.get("day_peak_equity") or capture["peak_equity"]),
        "open_notional_by_asset": {
            str(k): float(v) for k, v in (capture.get("open_notional_by_asset") or {}).items()
        },
        "open_assets": [str(a) for a in capture.get("open_assets") or []],
        "open_positions_count": int(capture.get("open_positions_count") or 0),
        "open_positions_notional": float(capture.get("open_positions_notional") or 0.0),
        "asset_held": bool(capture.get("asset_held")),
        "trades_today": int(capture.get("trades_today") or 0),
        "consecutive_losses": int(capture.get("consecutive_losses") or 0),
        "cooldown_until_ts": int(capture.get("cooldown_until_ts") or 0),
        "daily_pnl": 0.0,
        "weekly_pnl": 0.0,
        "kill_switch": False,
        "drawdown_pct": float(capture.get("drawdown_pct") or 0.0),
        "asset": str(capture.get("asset")),
        "candidate": str(capture.get("candidate")),
        "timeframe": str(capture.get("timeframe") or "4h"),
        "entry_mid": float(capture["entry_mid"]),
        "stop": float(capture["stop"]),
        "targets": [float(t) for t in capture.get("targets") or []],
        "decision_ts": int(capture["decision_ts"]),
        "captured_decision": str(capture.get("decision")),
        "captured_reason": capture.get("reason"),
    }


def shadow_cases(captures: list[dict[str, Any]], *, limit: int | None = None) -> list[dict[str, Any]]:
    """Every distinct captured instant, deduplicated by (arm, asset, instant, decision)."""
    seen: set[tuple[Any, ...]] = set()
    cases: list[dict[str, Any]] = []
    for capture in captures:
        key = (
            capture.get("arm"),
            capture.get("asset"),
            int(capture.get("decision_ts") or 0),
            capture.get("decision"),
        )
        if key in seen:
            continue
        seen.add(key)
        cases.append(case_from_capture(capture, index=len(cases)))
    if limit is not None and len(cases) > limit:
        # Keep both ends of the run: the first decisions (when the book is empty) and the
        # last ones (when it has been shaped by the whole window).
        head = cases[: limit // 2]
        tail = cases[-(limit - len(head)) :]
        return head + tail
    return cases


def run_parity(
    *,
    captures: list[dict[str, Any]] | None = None,
    sweep_cases: int = 384,
    shadow_case_limit: int | None = 600,
    scenario: str = "BASE",
    horizon_minutes: float = 1440.0,
) -> dict[str, Any]:
    """Run the declared grid and the captured instants through both engines."""
    policy = load_risk_policy()
    risk = load_runtime_risk()
    tolerance = float(PARITY_DECISION["tolerances"]["notional_usdt"])
    planes: dict[str, CostPlane] = {}

    def plane_for(timeframe: str) -> CostPlane:
        """The same cost plane the arm was shadowed with, for that arm's own horizon."""
        key = str(timeframe)
        if key not in planes:
            planes[key] = cost_plane(
                size_usd=1000.0,
                horizon_minutes=HORIZON_MINUTES.get(key, horizon_minutes),
            ).scaled(scenario)
        return planes[key]

    rows: list[Comparison] = []
    for case in declared_cases(sweep_cases=sweep_cases):
        rows.append(
            compare(
                case["case_id"],
                "declared",
                case,
                policy=policy,
                risk=risk,
                plane=plane_for(case["timeframe"]),
                tolerance=tolerance,
            )
        )

    reproduced = {"checked": 0, "reproduced": 0, "mismatches": []}
    capture_cases = shadow_cases(captures or [], limit=shadow_case_limit)
    for case in capture_cases:
        comparison = compare(
            case["case_id"],
            "shadow",
            case,
            policy=policy,
            risk=risk,
            plane=plane_for(case["timeframe"]),
            tolerance=tolerance,
        )
        rows.append(comparison)
        if case.get("captured_decision"):
            reproduced["checked"] += 1
            call = comparison.research
            recorded = "APPROVED" if call["approved"] else "REFUSED"
            same_reason = (
                True if call["approved"] else str(call["reason"]) == str(case.get("captured_reason"))
            )
            if recorded == case["captured_decision"] and same_reason:
                reproduced["reproduced"] += 1
            else:
                reproduced["mismatches"].append(
                    {
                        "case_id": case["case_id"],
                        "captured": case["captured_decision"],
                        "captured_reason": case.get("captured_reason"),
                        "recomputed": recorded,
                        "recomputed_reason": call["reason"],
                    }
                )

    counts: dict[str, int] = {}
    for row in rows:
        counts[row.klass] = counts.get(row.klass, 0) + 1
    by_origin: dict[str, dict[str, int]] = {}
    for row in rows:
        by_origin.setdefault(row.origin, {})
        by_origin[row.origin][row.klass] = by_origin[row.origin].get(row.klass, 0) + 1

    defects = [row.to_row() for row in rows if row.klass == "PARITY_DEFECT"]
    divergences = [
        row.to_row()
        for row in rows
        if row.klass
        in {
            "RULE_ORDER_DIFFERS",
            "RULE_NOT_MODELLED_BY_RESEARCH",
            "RESEARCH_ONLY_REFUSAL",
            "SIZING_ROUNDING_ONLY",
            "SIZING_DIFFERS",
        }
    ]
    verdict = (
        "PARITY_PASS"
        if not defects and not reproduced["mismatches"]
        else "PARITY_FINDINGS"
    )
    return {
        "id": PARITY_DECISION["id"],
        "decision": PARITY_DECISION,
        "policy": policy.to_dict(),
        "plane": plane_for("4h").to_dict(),
        "planes": {key: value.to_dict() for key, value in sorted(planes.items())},
        "cases": [row.to_row() for row in rows],
        "counts": counts,
        "counts_by_origin": by_origin,
        "defects": defects,
        "divergences": divergences[:200],
        "divergence_total": len(divergences),
        "captured_reproduction": reproduced,
        "verdict": verdict,
        "verdict_reasons": [
            reason
            for reason in (
                f"{len(defects)} PARITY_DEFECT case(s)" if defects else None,
                (
                    f"{len(reproduced['mismatches'])} captured decision(s) were not reproduced "
                    "from their own state"
                )
                if reproduced["mismatches"]
                else None,
            )
            if reason
        ],
        "not_claimed": PARITY_DECISION["not_claimed"],
    }


def parity_markdown(payload: dict[str, Any]) -> str:
    """The findings, in prose, with the states that produced them."""
    lines = [
        "# EDGE-03 — research budget vs runtime Risk Engine",
        "",
        f"Verdict: **{payload['verdict']}**",
        "",
        f"Cases: {len(payload['cases'])} — "
        + ", ".join(f"`{k}` {v}" for k, v in sorted(payload["counts"].items()))
        + ".",
        "",
    ]
    if payload["verdict_reasons"]:
        lines += ["Reasons: " + "; ".join(payload["verdict_reasons"]) + ".", ""]
    lines += [
        "| class | declared | shadow |",
        "| --- | --- | --- |",
    ]
    for klass in sorted({k for origin in payload["counts_by_origin"].values() for k in origin}):
        declared = payload["counts_by_origin"].get("declared", {}).get(klass, 0)
        shadow = payload["counts_by_origin"].get("shadow", {}).get(klass, 0)
        lines.append(f"| `{klass}` | {declared} | {shadow} |")
    lines += ["", "## Divergences", ""]
    if not payload["divergences"]:
        lines.append("None: the two engines agreed on every case.")
    else:
        lines += [
            "| case | class | research | runtime | detail |",
            "| --- | --- | --- | --- | --- |",
        ]
        for row in payload["divergences"]:
            lines.append(
                f"| `{row['case_id']}` | `{row['class']}` | "
                f"{row['research_decision']} ({row['research_reason']}) | "
                f"{row['runtime_decision']} ({row['runtime_blocked_by']}) | {row['detail']} |"
            )
    lines += ["", "## Captured decisions reproduced from their own state", ""]
    rep = payload["captured_reproduction"]
    lines.append(
        f"{rep['reproduced']} of {rep['checked']} captured decision(s) reproduced by the "
        "research budget fed the state it recorded."
    )
    for mismatch in rep["mismatches"][:20]:
        lines.append(
            f"- `{mismatch['case_id']}`: captured {mismatch['captured']} "
            f"({mismatch.get('captured_reason')}), recomputed {mismatch['recomputed']} "
            f"({mismatch.get('recomputed_reason')})"
        )
    lines += [
        "",
        f"> {payload['not_claimed']}",
        "",
        "```json",
        json.dumps(payload["plane"], indent=2, sort_keys=True),
        "```",
        "",
    ]
    return "\n".join(lines)


def write_parity_artifacts(payload: dict[str, Any], outdir: Path) -> dict[str, Path]:
    """Publish the parity payload, its rows as CSV and the readable findings."""
    import csv

    outdir = Path(outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    written: dict[str, Path] = {}
    json_path = outdir / "PARITY.json"
    json_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    written["json"] = json_path
    rows = payload["cases"]
    if rows:
        columns = list(rows[0].keys())
        csv_path = outdir / "PARITY_CASES.csv"
        with csv_path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=columns)
            writer.writeheader()
            writer.writerows(rows)
        written["cases_csv"] = csv_path
    md_path = outdir / "PARITY.md"
    md_path.write_text(parity_markdown(payload), encoding="utf-8")
    written["markdown"] = md_path
    return written
