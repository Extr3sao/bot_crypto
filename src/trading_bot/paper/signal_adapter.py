"""Signal adapter — converts research-side alpha output to execution `Signal`.

FASE 2/3 contract convergence: `AlphaSignal` (research/types.py, family
output) is not directly consumable by `RiskManager.check_signal` or
`PaperBroker.execute_signal`, which both require `strategies.types.Signal`.
This module is the single, explicit conversion point. No other adaptation
is permitted (D2 in docs/PAPER_OPERATIONAL_CONTRACT_CONVERGENCE.md).
"""

from __future__ import annotations

from typing import Any

from trading_bot.strategies.types import Side, Signal

__all__ = ["AdapterError", "alpha_signal_to_signal"]


class AdapterError(ValueError):
    """Raised when a research-side alpha cannot be safely converted."""


def alpha_signal_to_signal(
    alpha: Any,  # research.types.AlphaSignal (Any avoids a package cycle)
    *,
    stop_loss_pct: float | None = None,
    take_profit_pct: float | None = None,
    notional_usdt: float | None = None,
) -> Signal:
    """Convert an AlphaSignal into the canonical execution Signal.

    - direction: LONG → buy, SHORT → sell (fail closed on anything else).
    - price: AlphaSignal.entry_reference (reference price at signal time).
    - stop_loss_pct: explicit argument wins; otherwise derived from the
      structural stop distance when available; otherwise a conservative 1%.
    - notional_usdt is passed through metadata for the broker (sizing stays
      the RiskManager's job — callers must pass the risk-approved size).
    """
    direction = getattr(alpha, "direction", None)
    direction_upper = str(direction).upper() if direction else ""
    if direction == "LONG" or direction_upper == "LONG":
        side: Side = "buy"
    elif direction == "SHORT" or direction_upper == "SHORT":
        side = "sell"
    else:
        raise AdapterError(f"cannot adapt alpha direction: {direction!r}")

    price = float(getattr(alpha, "entry_reference", 0.0) or 0.0)
    if price <= 0:
        raise AdapterError("alpha entry_reference must be > 0")

    sl_pct = stop_loss_pct
    if sl_pct is None:
        stop = getattr(alpha, "effective_stop", None) or getattr(alpha, "structural_stop", None)
        if stop and 0 < float(stop) < price:
            sl_pct = round(abs(price - float(stop)) / price * 100.0, 4)
        else:
            sl_pct = 1.0  # conservative default

    metadata: dict[str, Any] = dict(getattr(alpha, "metadata", None) or {})
    if notional_usdt is not None:
        metadata["notional_usdt"] = float(notional_usdt)

    return Signal(
        symbol=getattr(alpha, "symbol", ""),
        side=side,
        strategy_name=getattr(alpha, "family", "unknown"),
        timeframe=getattr(alpha, "timeframe", "5m"),
        confidence=float(getattr(alpha, "confidence", 0.0) or 0.0),
        price=price,
        stop_loss_pct=sl_pct,
        take_profit_pct=take_profit_pct,
        metadata=metadata,
    )
