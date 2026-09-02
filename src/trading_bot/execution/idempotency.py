"""Idempotency guard — prevent duplicate executions."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class IdempotencyGuard:
    """Prevents duplicate order submissions.

    Tracks sent cloids and order IDs to ensure exactly-once execution.
    """

    _sent_cloids: set[str] = field(default_factory=set)
    _sent_order_ids: set[str] = field(default_factory=set)
    _ttl_seconds: int = 3600

    def is_duplicate(self, cloid: str) -> bool:
        """Check if a cloid was already sent."""
        return cloid in self._sent_cloids

    def register(self, cloid: str, order_id: str = "") -> None:
        """Register a sent cloid to prevent re-sending."""
        self._sent_cloids.add(cloid)
        if order_id:
            self._sent_order_ids.add(order_id)

    def was_order_sent(self, order_id: str) -> bool:
        """Check if an order ID was already sent."""
        return order_id in self._sent_order_ids

    def clear(self) -> None:
        """Clear all tracked IDs (use with caution)."""
        self._sent_cloids.clear()
        self._sent_order_ids.clear()

    @property
    def active_count(self) -> int:
        """Number of active tracked IDs."""
        return len(self._sent_cloids) + len(self._sent_order_ids)
