"""Shadow outcome engine — PIT resolution of captured rejected candidates.

SHADOW-AND-LEGACY-VALIDATION-01 (Track B2). Consumes
:class:`trading_bot.shadow.capture.ShadowCandidateCapture` records against
point-in-time market updates and produces immutable ``ShadowTrade`` records
with hypothetical entry/SL/TP/exit and cost-adjusted PnL.

Hard isolation guarantees:

- No PaperBroker, no PortfolioStore, no RiskManager, no campaign accounting.
- Resolution is strictly causal: only bars with timestamp strictly AFTER the
  capture's ``decision_time`` may influence the outcome. Pre-decision bars
  are skipped defensively, and appending future bars never changes an
  already-resolved trade (no look-ahead, no retro mutation).
- Within a bar, stop-loss is evaluated BEFORE take-profit (adverse-first,
  conservative). No intrabar path is assumed.
- Costs come exclusively from ``ExecutionCostModel`` (the same model class
  the paper path uses) — no parallel cost math.

Analytical only: outcomes are COUNTERFACTUAL evidence, excluded from paper
PnL and frequency by construction (labels on the capture).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from pathlib import Path
from typing import Any

from trading_bot.execution.cost_model import ExecutionCostModel
from trading_bot.shadow.capture import ShadowCandidateCapture

__all__ = [
    "ShadowBar",
    "ShadowOutcomeEngine",
    "ShadowOutcomeLedger",
    "ShadowTrade",
    "ShadowTradeOutcome",
]


class ShadowTradeOutcome(StrEnum):
    TAKE_PROFIT_HIT = "TAKE_PROFIT_HIT"
    STOP_LOSS_HIT = "STOP_LOSS_HIT"
    STILL_OPEN = "STILL_OPEN"


@dataclass(frozen=True, slots=True)
class ShadowBar:
    """One PIT market update used for shadow resolution (UTC ISO time)."""

    time: str
    high: float
    low: float
    close: float

    def __post_init__(self) -> None:
        if self.high < max(self.low, self.close) or self.low > min(self.high, self.close):
            raise ValueError(f"OHLC invariant violated in shadow bar: {self!r}")
        if self.high <= 0 or self.low <= 0:
            raise ValueError("shadow bar prices must be positive")


@dataclass(frozen=True, slots=True)
class ShadowTrade:
    """Immutable counterfactual outcome of one captured rejected candidate."""

    shadow_candidate_id: str
    decision_id: str
    asset: str
    direction: str
    strategy_id: str
    timeframe: str
    risk_rejection_reason: str
    regime_signature: str
    strategy_health_state: str

    entry_price: float
    exit_price: float | None
    exit_time: str | None
    outcome: ShadowTradeOutcome

    gross_pnl: float
    net_pnl: float
    r_multiple: float | None  # on net pnl; None while STILL_OPEN
    entry_fee_usdt: float
    exit_fee_usdt: float
    entry_slippage_usdt: float
    exit_slippage_usdt: float
    bars_evaluated: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "shadow_candidate_id": self.shadow_candidate_id,
            "decision_id": self.decision_id,
            "asset": self.asset,
            "direction": self.direction,
            "strategy_id": self.strategy_id,
            "timeframe": self.timeframe,
            "risk_rejection_reason": self.risk_rejection_reason,
            "regime_signature": self.regime_signature,
            "strategy_health_state": self.strategy_health_state,
            "resolution": {
                "entry_price": self.entry_price,
                "exit_price": self.exit_price,
                "exit_time": self.exit_time,
                "outcome": self.outcome.value,
                "bars_evaluated": self.bars_evaluated,
            },
            "economics": {
                "gross_pnl": self.gross_pnl,
                "net_pnl": self.net_pnl,
                "r_multiple": self.r_multiple,
                "entry_fee_usdt": self.entry_fee_usdt,
                "exit_fee_usdt": self.exit_fee_usdt,
                "entry_slippage_usdt": self.entry_slippage_usdt,
                "exit_slippage_usdt": self.exit_slippage_usdt,
            },
            "labels": [
                "SHADOW_ONLY",
                "COUNTERFACTUAL",
                "EXCLUDED_FROM_PAPER_PNL",
                "EXCLUDED_FROM_PAPER_FREQUENCY",
            ],
        }


def _parse_utc(value: str) -> datetime:
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        raise ValueError(f"shadow timestamp must carry UTC offset: {value!r}")
    return dt


class ShadowOutcomeEngine:
    """Resolve captures against PIT bars. Pure: no external state mutated."""

    def __init__(self, cost_model: ExecutionCostModel | None = None) -> None:
        self._cost_model = cost_model or ExecutionCostModel()

    def resolve(
        self,
        capture: ShadowCandidateCapture,
        bars: list[ShadowBar],
        *,
        quantity: float = 1.0,
    ) -> ShadowTrade:
        """Resolve one capture. Raises ValueError on plan inconsistencies."""
        if quantity <= 0:
            raise ValueError("quantity must be > 0")
        entry = capture.entry_reference
        if entry <= 0:
            raise ValueError("entry_reference must be > 0")

        # Plan geometry must be consistent for the direction (fail closed).
        if capture.direction == "LONG":
            if not (capture.stop_loss < entry <= capture.take_profit):
                raise ValueError(
                    "LONG plan must satisfy stop_loss < entry <= take_profit"
                )
        else:  # SHORT
            if not (capture.take_profit < entry <= capture.stop_loss):
                raise ValueError(
                    "SHORT plan must satisfy take_profit < entry <= stop_loss"
                )

        decision_dt = _parse_utc(capture.decision_time)

        # PIT filter: only strictly-post-decision bars may be consumed.
        usable = [b for b in bars if _parse_utc(b.time) > decision_dt]
        bars_evaluated = len(usable)

        exit_bar: ShadowBar | None = None
        outcome = ShadowTradeOutcome.STILL_OPEN
        for bar in usable:
            if capture.direction == "LONG":
                hit_sl = bar.low <= capture.stop_loss
                hit_tp = bar.high >= capture.take_profit
                if hit_sl:  # adverse-first within the bar (conservative)
                    outcome, exit_bar = ShadowTradeOutcome.STOP_LOSS_HIT, bar
                    break
                if hit_tp:
                    outcome, exit_bar = ShadowTradeOutcome.TAKE_PROFIT_HIT, bar
                    break
            else:
                hit_sl = bar.high >= capture.stop_loss
                hit_tp = bar.low <= capture.take_profit
                if hit_sl:
                    outcome, exit_bar = ShadowTradeOutcome.STOP_LOSS_HIT, bar
                    break
                if hit_tp:
                    outcome, exit_bar = ShadowTradeOutcome.TAKE_PROFIT_HIT, bar
                    break

        if exit_bar is not None:
            exit_ref = (
                capture.stop_loss if outcome is ShadowTradeOutcome.STOP_LOSS_HIT else capture.take_profit
            )
        else:
            exit_ref = usable[-1].close if usable else entry

        side_entry = "buy" if capture.direction == "LONG" else "sell"
        notional = entry * quantity

        costs_entry_ref = entry
        costs_exit_ref = exit_ref
        costs = self._cost_model.compute_costs(
            notional_usdt=notional,
            entry_price=costs_entry_ref,
            exit_price=costs_exit_ref,
            quantity=quantity,
            side=side_entry,
        )

        if capture.direction == "LONG":
            gross = (exit_ref - entry) * quantity
        else:
            gross = (entry - exit_ref) * quantity

        # compute_costs derives gross/net from its inputs; align to our exit
        # semantics by reconstructing net from gross minus explicit costs.
        explicit_costs = (
            costs.entry_fee_usdt
            + costs.exit_fee_usdt
            + costs.entry_slippage_usdt
            + costs.exit_slippage_usdt
        )
        net = gross - explicit_costs

        risk_per_unit = abs(entry - capture.stop_loss)
        r_multiple: float | None = None
        if exit_bar is not None and risk_per_unit > 0:
            r_multiple = net / (risk_per_unit * quantity)

        return ShadowTrade(
            shadow_candidate_id=capture.shadow_candidate_id,
            decision_id=capture.decision_id,
            asset=capture.asset,
            direction=capture.direction,
            strategy_id=capture.strategy_id,
            timeframe=capture.timeframe,
            risk_rejection_reason=capture.risk_rejection_reason,
            regime_signature=capture.regime_signature,
            strategy_health_state=capture.strategy_health_state,
            entry_price=entry,
            exit_price=exit_ref if exit_bar is not None else None,
            exit_time=exit_bar.time if exit_bar is not None else None,
            outcome=outcome,
            gross_pnl=gross,
            net_pnl=net,
            r_multiple=r_multiple,
            entry_fee_usdt=costs.entry_fee_usdt,
            exit_fee_usdt=costs.exit_fee_usdt,
            entry_slippage_usdt=costs.entry_slippage_usdt,
            exit_slippage_usdt=costs.exit_slippage_usdt,
            bars_evaluated=bars_evaluated,
        )


class ShadowOutcomeLedger:
    """Append-only JSONL ledger of resolved shadow trades (separate store)."""

    def __init__(self) -> None:
        self._trades: list[ShadowTrade] = []
        self._ids: set[str] = set()

    def __len__(self) -> int:
        return len(self._trades)

    @property
    def trades(self) -> tuple[ShadowTrade, ...]:
        return tuple(self._trades)

    def record(self, trade: ShadowTrade) -> None:
        if trade.shadow_candidate_id in self._ids:
            raise ValueError(
                f"duplicate shadow trade: {trade.shadow_candidate_id}"
            )
        self._ids.add(trade.shadow_candidate_id)
        self._trades.append(trade)

    def by_reason(self) -> dict[str, list[ShadowTrade]]:
        grouped: dict[str, list[ShadowTrade]] = {}
        for t in self._trades:
            grouped.setdefault(t.risk_rejection_reason, []).append(t)
        return grouped

    # -- durability ---------------------------------------------------------

    def to_jsonl(self) -> str:
        return "".join(
            json.dumps(t.to_dict(), separators=(",", ":")) + "\n" for t in self._trades
        )

    def save(self, path: Path | str) -> None:
        Path(path).write_text(self.to_jsonl(), encoding="utf-8")

    @classmethod
    def load(cls, path: Path | str) -> ShadowOutcomeLedger:
        ledger = cls()
        p = Path(path)
        if not p.exists():
            return ledger
        for line in p.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            payload = json.loads(line)
            ledger.record(
                ShadowTrade(
                    shadow_candidate_id=payload["shadow_candidate_id"],
                    decision_id=payload["decision_id"],
                    asset=payload["asset"],
                    direction=payload["direction"],
                    strategy_id=payload["strategy_id"],
                    timeframe=payload["timeframe"],
                    risk_rejection_reason=payload["risk_rejection_reason"],
                    regime_signature=payload["regime_signature"],
                    strategy_health_state=payload["strategy_health_state"],
                    entry_price=float(payload["resolution"]["entry_price"]),
                    exit_price=payload["resolution"]["exit_price"],
                    exit_time=payload["resolution"]["exit_time"],
                    outcome=ShadowTradeOutcome(payload["resolution"]["outcome"]),
                    gross_pnl=float(payload["economics"]["gross_pnl"]),
                    net_pnl=float(payload["economics"]["net_pnl"]),
                    r_multiple=payload["economics"]["r_multiple"],
                    entry_fee_usdt=float(payload["economics"]["entry_fee_usdt"]),
                    exit_fee_usdt=float(payload["economics"]["exit_fee_usdt"]),
                    entry_slippage_usdt=float(payload["economics"]["entry_slippage_usdt"]),
                    exit_slippage_usdt=float(payload["economics"]["exit_slippage_usdt"]),
                    bars_evaluated=int(payload["resolution"]["bars_evaluated"]),
                )
            )
        return ledger
