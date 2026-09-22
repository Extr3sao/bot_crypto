"""Trade data validation — detect impossible trades.

Fase 9: Validates that trades are physically possible:
- price > 0
- entry price reasonable vs market
- quantity > 0
- notional ≈ quantity * entry_price
- PnL sign matches direction + price movement

Invalid trades are QUARANTINED, not deleted silently.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import structlog

from trading_bot.paper.broker import ClosedTrade

# Maximum reasonable deviation of entry price from a reference price
# (e.g., the signal price). If entry deviates more than this fraction,
# the trade is suspicious.
MAX_ENTRY_DEVIATION_PCT = 5.0  # 5%


@dataclass(frozen=True, slots=True)
class ValidationResult:
    """Result of validating a single trade."""

    trade_id: str
    valid: bool
    issues: list[str] = field(default_factory=list)
    severity: str = "ok"  # ok / warning / invalid


@dataclass
class TradeValidator:
    """Validates trade data for physical possibility.

    Maintains a quarantine list of invalid trades.
    """

    def __init__(self, reference_prices: dict[str, float] | None = None) -> None:
        self._log = structlog.get_logger("trade_validator")
        self._reference_prices: dict[str, float] = reference_prices or {}
        self._quarantined: list[dict[str, Any]] = []

    def set_reference_price(self, symbol: str, price: float) -> None:
        """Update the reference market price for a symbol."""
        self._reference_prices[symbol] = price

    def validate_trade(
        self,
        trade: ClosedTrade,
        trade_id: str = "",
    ) -> ValidationResult:
        """Validate a single closed trade.

        Returns ValidationResult with issues if any.
        Invalid trades are added to quarantine.
        """
        issues: list[str] = []

        # 1. Prices must be positive
        if trade.entry_price <= 0:
            issues.append(f"entry_price={trade.entry_price} <= 0")
        if trade.exit_price <= 0:
            issues.append(f"exit_price={trade.exit_price} <= 0")

        # 2. Quantity must be positive
        if trade.quantity <= 0:
            issues.append(f"quantity={trade.quantity} <= 0")

        # 3. Entry price sanity check vs reference
        ref_price = self._reference_prices.get(trade.symbol)
        if ref_price is not None and ref_price > 0 and trade.entry_price > 0:
            deviation_pct = abs(trade.entry_price - ref_price) / ref_price * 100
            if deviation_pct > MAX_ENTRY_DEVIATION_PCT:
                issues.append(
                    f"entry_price={trade.entry_price:.4f} deviates "
                    f"{deviation_pct:.1f}% from reference={ref_price:.4f}"
                )

        # 4. Notional consistency: notional ≈ quantity * entry_price
        # (We don't have notional in ClosedTrade, but we can check PnL sign)

        # 5. PnL sign must match direction + price movement
        if trade.side == "buy":
            if trade.exit_price > trade.entry_price:
                # Exit higher than entry -> should be profitable (gross)
                # Net may be slightly negative due to fees, but not hugely
                if trade.pnl < -abs(trade.entry_price * trade.quantity * 0.1):
                    issues.append(
                        f"BUY but pnl={trade.pnl:.4f} is very negative "
                        f"despite exit > entry ({trade.exit_price:.4f} > {trade.entry_price:.4f})"
                    )
            elif trade.exit_price < trade.entry_price and trade.pnl > abs(
                trade.entry_price * trade.quantity * 0.1
            ):
                # Exit lower than entry -> should be a loss
                issues.append(
                    f"BUY but pnl={trade.pnl:.4f} is very positive "
                    f"despite exit < entry ({trade.exit_price:.4f} < {trade.entry_price:.4f})"
                )
        elif trade.side == "sell":
            if trade.exit_price < trade.entry_price:
                # Exit lower than entry -> should be profitable for short
                if trade.pnl < -abs(trade.entry_price * trade.quantity * 0.1):
                    issues.append(
                        f"SELL but pnl={trade.pnl:.4f} is very negative "
                        f"despite exit < entry ({trade.exit_price:.4f} < {trade.entry_price:.4f})"
                    )
            elif trade.exit_price > trade.entry_price and trade.pnl > abs(
                trade.entry_price * trade.quantity * 0.1
            ):
                # Exit higher than entry -> should be a loss for short
                issues.append(
                    f"SELL but pnl={trade.pnl:.4f} is very positive "
                    f"despite exit > entry ({trade.exit_price:.4f} > {trade.entry_price:.4f})"
                )

        # Determine severity
        severity = "ok"
        valid = True
        if issues:
            # Check if any issue is critical (price/quantity <= 0)
            critical = any("<= 0" in issue or "deviates" in issue for issue in issues)
            if critical:
                severity = "invalid"
                valid = False
            else:
                severity = "warning"

        result = ValidationResult(
            trade_id=trade_id,
            valid=valid,
            issues=issues,
            severity=severity,
        )

        # Quarantine invalid trades
        if not valid:
            self._quarantined.append(
                {
                    "trade_id": trade_id,
                    "symbol": trade.symbol,
                    "side": trade.side,
                    "entry_price": trade.entry_price,
                    "exit_price": trade.exit_price,
                    "pnl": trade.pnl,
                    "issues": issues,
                }
            )
            self._log.warning(
                "trade.quarantined",
                trade_id=trade_id,
                symbol=trade.symbol,
                issues=issues,
            )

        return result

    def validate_batch(
        self,
        trades: list[tuple[str, ClosedTrade]],
    ) -> list[ValidationResult]:
        """Validate a batch of trades.

        Args:
            trades: List of (trade_id, ClosedTrade) tuples.

        Returns:
            List of ValidationResult for each trade.
        """
        results: list[ValidationResult] = []
        for trade_id, trade in trades:
            result = self.validate_trade(trade, trade_id)
            results.append(result)
        return results

    @property
    def quarantined(self) -> list[dict[str, Any]]:
        """List of quarantined invalid trades."""
        return list(self._quarantined)

    def stats(self) -> dict[str, Any]:
        """Summary statistics of validation."""
        total = len(self._quarantined)
        return {
            "quarantined_count": total,
            "quarantined_trades": [q["trade_id"] for q in self._quarantined],
        }
