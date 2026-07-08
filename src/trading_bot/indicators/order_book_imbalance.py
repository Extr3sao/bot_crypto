"""OrderBookImbalance - concrete indicator implementation (TSK-203).

Computes the bid/ask volume imbalance as::

    imbalance = (bid_volume - ask_volume) / (bid_volume + ask_volume)

clamped to ``[-1.0, +1.0]``. A positive value indicates bid-dominance
(buying pressure); a negative value indicates ask-dominance (selling
pressure); zero is balanced.

Per sprint-003 spec for TSK-203, the indicator is feature-flag gated via
the ``enabled`` constructor argument (default: ``False``). The runtime
config flag ``runtime.features.enable_order_book_imbalance`` is wired by
the dispatch layer (post-TSK-200 IndicatorRegistry) to control this.

Edge cases:
- ``bid_volume + ask_volume == 0``: raises ``InsufficientHistoryError``.
- Negative ``bid_volume`` or ``ask_volume``: raises
  ``InvalidOrderBookSnapshotError``.
- ``enabled=False``: raises ``IndicatorDisabledError`` when ``compute()``
  is called.

The compute is deterministic: same input ``OrderBookSummary`` yields
the same output, within float-precision.

Cross-layer note: this module is self-contained for now (no dependency
on TSK-200's ``Indicator`` Protocol / ``IndicatorRegistry`` / ``IndicatorCache``).
The dispatch integration is decoupled: when TSK-200 lands, an
``IndicatorRegistry.register("order_book_imbalance", ...)`` line will
plug this concrete class into the catalog dispatch.
"""

from __future__ import annotations

from dataclasses import dataclass


class OrderBookImbalanceError(Exception):
    """Base exception for OrderBookImbalance."""


class IndicatorDisabledError(OrderBookImbalanceError):
    """Raised when ``compute()`` is called on a disabled instance."""


class InsufficientHistoryError(OrderBookImbalanceError):
    """Raised when the order book snapshot has zero total volume."""


class InvalidOrderBookSnapshotError(OrderBookImbalanceError):
    """Raised when bid_volume or ask_volume is negative."""


@dataclass(frozen=True, slots=True)
class OrderBookSummary:
    """Snapshot of top-of-book + depth for imbalance computation.

    Attributes:
        bid_volume: Total volume at the bid side, summed across the depth
            levels represented in this snapshot. Must be >= 0.
        ask_volume: Total volume at the ask side, summed across the depth
            levels represented in this snapshot. Must be >= 0.
        depth_levels: Number of depth levels the snapshot covers. Default
            is 10 (per ``config/indicators.yaml`` registry entry). Used
            for traceability; not consumed by the compute.
    """

    bid_volume: float
    ask_volume: float
    depth_levels: int = 10


class OrderBookImbalance:
    """Concrete Indicator implementation for bid/ask volume imbalance.

    Per sprint-003 spec, the indicator is feature-flag gated. Set
    ``enabled=True`` to activate (typically wired from
    ``config.runtime.features.enable_order_book_imbalance``). The
    default is ``False``: an instance constructed with no arguments
    refuses to compute and raises ``IndicatorDisabledError``.

    The compute is deterministic: same input ``OrderBookSummary`` yields
    the same output ``float`` (within float-precision).
    """

    def __init__(self, *, enabled: bool = False) -> None:
        """Construct an OrderBookImbalance indicator.

        Args:
            enabled: Whether the indicator is active. Default ``False``
                (feature-flag off).
        """
        self.enabled = enabled

    def compute(self, summary: OrderBookSummary) -> float:
        """Compute the imbalance ``(bid - ask) / (bid + ask)``.

        Returns:
            A ``float`` in ``[-1.0, +1.0]``. Positive => bid dominance;
            negative => ask dominance; zero => balanced.

        Raises:
            IndicatorDisabledError: When ``self.enabled`` is ``False``.
            InvalidOrderBookSnapshotError: When either volume is negative.
            InsufficientHistoryError: When total volume is exactly zero.
        """
        if not self.enabled:
            raise IndicatorDisabledError(
                "OrderBookImbalance is feature-flag gated (TSK-203). "
                "Construct with enabled=True or wire "
                "runtime.features.enable_order_book_imbalance to the dispatch layer."
            )
        if summary.bid_volume < 0.0 or summary.ask_volume < 0.0:
            raise InvalidOrderBookSnapshotError(
                f"OrderBookSummary has negative volume: "
                f"bid={summary.bid_volume}, ask={summary.ask_volume}"
            )
        total = summary.bid_volume + summary.ask_volume
        if total == 0.0:
            raise InsufficientHistoryError(
                "OrderBookSummary has zero total volume (bid+ask==0); imbalance is undefined."
            )
        imbalance = (summary.bid_volume - summary.ask_volume) / total
        # Clamp to [-1.0, +1.0] to handle floating-point imprecision
        # at the boundary (e.g., bid=100.0, ask=1e-15 may yield ~1.00001).
        return max(-1.0, min(1.0, imbalance))


__all__ = [
    "IndicatorDisabledError",
    "InsufficientHistoryError",
    "InvalidOrderBookSnapshotError",
    "OrderBookImbalance",
    "OrderBookImbalanceError",
    "OrderBookSummary",
]
