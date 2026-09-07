"""ADMISSION-FOUNDATION-01 — Shadow Plane V1 (§10-§15, ADM-11..15).

A completely NON-AUTHORITATIVE plane: evaluates hypothetical outcomes of
opportunities that production Risk rejected, or research candidates not
admitted to PAPER. Structural isolation:

- never imports or calls PaperBroker / RiskManager (fail-closed runtime
  guard rejects any object with execution/risk authority methods);
- separate, append-only accounting never merged with campaign PnL;
- duplicate prevention on ``source_decision_id``.
"""

from __future__ import annotations

import enum
import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from .registry import canonical_hash


class ShadowIsolationError(TypeError):
    """Raised when an object with execution/risk authority reaches the Shadow Plane."""


_FORBIDDEN_METHODS = (
    "place_order", "submit_order", "create_order", "execute_order",
    "cancel_order", "set_risk", "apply_risk", "evaluate_risk",
    "open_position", "close_position", "set_sizing", "update_limits",
)


def assert_no_execution_authority(*objects: Any) -> None:
    """Fail closed if any object carries broker/risk authority (ADM-11/21)."""
    for obj in objects:
        if obj is None:
            continue
        for name in _FORBIDDEN_METHODS:
            if callable(getattr(obj, name, None)):
                raise ShadowIsolationError(
                    f"object of type {type(obj).__name__} exposes authority method "
                    f"'{name}()' — execution/risk objects may not enter the Shadow Plane"
                )


class ShadowLabel(enum.StrEnum):
    SHADOW_ONLY = "SHADOW_ONLY"
    COUNTERFACTUAL = "COUNTERFACTUAL"
    EXCLUDED_FROM_POC01_PNL = "EXCLUDED_FROM_POC01_PNL"
    EXCLUDED_FROM_POC01_FREQUENCY = "EXCLUDED_FROM_POC01_FREQUENCY"


@dataclass(frozen=True, slots=True)
class ShadowTrade:
    """Immutable hypothetical trade record (checkpoint §11)."""

    shadow_trade_id: str
    source_decision_id: str
    asset: str
    direction: str
    strategy: str
    hypothetical_entry_time: str
    hypothetical_entry_price: float
    sl_tp_policy_ref: str          # canonical SL/TP policy reference (§11)
    cost_assumptions: dict[str, float]
    exit_time: str
    exit_price: float
    outcome: str                   # win | loss | flat
    gross_pnl: float
    net_pnl: float
    risk_rejection_reason: str | None
    market_data_fingerprint: str
    evidence_refs: tuple[str, ...] = ()
    labels: tuple[str, ...] = (
        ShadowLabel.SHADOW_ONLY.value,
        ShadowLabel.EXCLUDED_FROM_POC01_PNL.value,
        ShadowLabel.EXCLUDED_FROM_POC01_FREQUENCY.value,
    )
    created_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    trade_sha256: str = field(default="")

    def __post_init__(self) -> None:
        if not self.trade_sha256:
            object.__setattr__(self, "trade_sha256", canonical_hash(self.to_dict()))

    def to_dict(self) -> dict[str, Any]:
        return {
            "shadow_trade_id": self.shadow_trade_id,
            "source_decision_id": self.source_decision_id,
            "asset": self.asset,
            "direction": self.direction,
            "strategy": self.strategy,
            "hypothetical_entry_time": self.hypothetical_entry_time,
            "hypothetical_entry_price": self.hypothetical_entry_price,
            "sl_tp_policy_ref": self.sl_tp_policy_ref,
            "cost_assumptions": self.cost_assumptions,
            "exit_time": self.exit_time,
            "exit_price": self.exit_price,
            "outcome": self.outcome,
            "gross_pnl": self.gross_pnl,
            "net_pnl": self.net_pnl,
            "risk_rejection_reason": self.risk_rejection_reason,
            "market_data_fingerprint": self.market_data_fingerprint,
            "evidence_refs": list(self.evidence_refs),
            "labels": list(self.labels),
            "created_at": self.created_at,
        }


class DuplicateShadowTradeError(ValueError):
    """Raised when the same source decision produces a second shadow trade."""


class ShadowLedger:
    """Append-only, ISOLATED shadow accounting (§13, ADM-13/ADM-15)."""

    SCHEMA_VERSION = "shadow-ledger-v1"

    def __init__(self) -> None:
        self._trades: dict[str, ShadowTrade] = {}

    def record(self, trade: ShadowTrade) -> str:
        if trade.source_decision_id in self._trades:
            raise DuplicateShadowTradeError(
                f"duplicate shadow trade for source decision {trade.source_decision_id}"
            )
        self._trades[trade.source_decision_id] = trade
        return trade.shadow_trade_id

    def trades(self) -> list[ShadowTrade]:
        return sorted(self._trades.values(), key=lambda t: t.hypothetical_entry_time)

    def accounting(self) -> dict[str, Any]:
        """Separate shadow accounting — NEVER merged with PaperBroker/campaign."""
        trades = self.trades()
        wins = [t for t in trades if t.net_pnl > 0]
        losses = [t for t in trades if t.net_pnl < 0]
        net = [t.net_pnl for t in trades]
        gross = [t.gross_pnl for t in trades]
        pf = (
            sum(p for p in net if p > 0) / abs(sum(p for p in net if p < 0))
            if any(p < 0 for p in net) and any(p > 0 for p in net)
            else None
        )
        equity, peak, mdd = 0.0, 0.0, 0.0
        for p in net:
            equity += p
            peak = max(peak, equity)
            mdd = min(mdd, equity - peak)
        by_reason: dict[str, dict[str, Any]] = {}
        for t in trades:
            if t.risk_rejection_reason:
                b = by_reason.setdefault(
                    t.risk_rejection_reason, {"n": 0, "wins": 0, "net_pnl": 0.0}
                )
                b["n"] += 1
                b["wins"] += 1 if t.net_pnl > 0 else 0
                b["net_pnl"] = round(b["net_pnl"] + t.net_pnl, 9)
        return {
            "schema_version": self.SCHEMA_VERSION,
            "shadow_trades": len(trades),
            "shadow_wins": len(wins),
            "shadow_losses": len(losses),
            "shadow_gross_pnl": round(sum(gross), 9) if gross else 0.0,
            "shadow_net_pnl": round(sum(net), 9) if net else 0.0,
            "shadow_expectancy": round(sum(net) / len(net), 9) if net else None,
            "shadow_pf": round(pf, 6) if pf is not None else None,
            "shadow_drawdown": round(mdd, 9),
            "by_risk_rejection_reason": by_reason,
            "note": "ISOLATED: excluded from POC01 PnL, equity, trade count and frequency",
        }

    def save(self, path: str) -> None:
        import pathlib

        payload = {
            "schema_version": self.SCHEMA_VERSION,
            "accounting": self.accounting(),
            "trades": [t.to_dict() for t in self.trades()],
        }
        pathlib.Path(path).write_text(
            json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8"
        )


def simulate_sl_tp_exit(
    *,
    direction: str,
    entry_price: float,
    stop_price: float,
    take_profit_price: float,
    bars_after_entry: list[tuple[str, float, float, float]],
) -> tuple[str, float]:
    """Deterministic intrabar exit policy (same semantics as discovery:
    if SL and TP are both touchable within the same bar, SL wins — the
    conservative rule). Returns (exit_time, exit_price) or the last bar's
    close if neither level is touched."""
    for ts, high, low, _close in bars_after_entry:
        if direction == "LONG":
            hit_sl = low <= stop_price
            hit_tp = high >= take_profit_price
        else:
            hit_sl = high >= stop_price
            hit_tp = low <= take_profit_price
        if hit_sl:  # conservative: SL first on ambiguous bars
            return ts, stop_price
        if hit_tp:
            return ts, take_profit_price
    if bars_after_entry:
        return bars_after_entry[-1][0], bars_after_entry[-1][3]
    raise ValueError("no bars after entry to simulate exit")


@dataclass(frozen=True, slots=True)
class ShadowPlane:
    """Non-authoritative evaluation entry point (§10).

    ``evaluate`` accepts ONLY pure inputs: a hypothetical proposal dict,
    market bars, cost assumptions and the risk rejection reason. Passing a
    broker/risk object raises immediately.
    """

    ledger: ShadowLedger = field(default_factory=ShadowLedger)
    sl_tp_policy_ref: str = "poc01-paper-broker-canonical-sl-tp"

    def evaluate_rejected_decision(
        self,
        *,
        source_decision_id: str,
        asset: str,
        direction: str,
        strategy: str,
        entry_time: str,
        entry_price: float,
        stop_price: float,
        take_profit_price: float,
        bars_after_entry: list[tuple[str, float, float, float]],
        cost_assumptions: dict[str, float],
        risk_rejection_reason: str,
        market_data_fingerprint: str,
        evidence_refs: tuple[str, ...] = (),
        pnl_scale: float = 1.0,
    ) -> ShadowTrade:
        """Counterfactual evaluation of one Risk-rejected decision (§12)."""
        assert_no_execution_authority(
            bars_after_entry, cost_assumptions, risk_rejection_reason
        )
        exit_time, exit_price = simulate_sl_tp_exit(
            direction=direction,
            entry_price=entry_price,
            stop_price=stop_price,
            take_profit_price=take_profit_price,
            bars_after_entry=bars_after_entry,
        )
        sign = 1.0 if direction == "LONG" else -1.0
        gross = (exit_price - entry_price) * sign * pnl_scale
        fee_rate = float(cost_assumptions.get("taker_fee_rate", 0.0))
        slip_rate = float(cost_assumptions.get("slippage_rate", 0.0))
        fees = (abs(entry_price) + abs(exit_price)) * fee_rate
        slippage = (abs(entry_price) + abs(exit_price)) * slip_rate
        net = gross - fees - slippage
        trade = ShadowTrade(
            shadow_trade_id=f"shadow-{canonical_hash(source_decision_id)[:16]}",
            source_decision_id=source_decision_id,
            asset=asset,
            direction=direction,
            strategy=strategy,
            hypothetical_entry_time=entry_time,
            hypothetical_entry_price=entry_price,
            sl_tp_policy_ref=self.sl_tp_policy_ref,
            cost_assumptions=cost_assumptions,
            exit_time=exit_time,
            exit_price=exit_price,
            outcome="win" if net > 0 else ("loss" if net < 0 else "flat"),
            gross_pnl=round(gross, 9),
            net_pnl=round(net, 9),
            risk_rejection_reason=risk_rejection_reason,
            market_data_fingerprint=market_data_fingerprint,
            evidence_refs=evidence_refs,
            labels=(
                ShadowLabel.SHADOW_ONLY.value,
                ShadowLabel.COUNTERFACTUAL.value,
                ShadowLabel.EXCLUDED_FROM_POC01_PNL.value,
                ShadowLabel.EXCLUDED_FROM_POC01_FREQUENCY.value,
            ),
        )
        self.ledger.record(trade)
        return trade
