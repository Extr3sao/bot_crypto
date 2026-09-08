from __future__ import annotations

from trading_bot.execution import (
    AckQueryResult,
    TradeIntent,
)
from trading_bot.execution.conformance import run_conformance


class CompliantFakeAdapter:
    """Reference implementation satisfying the full conformance contract."""

    def __init__(self) -> None:
        self._orders: dict[str, str] = {}
        self._cancelled: set[str] = set()
        self._reconnects = 0

    def adapter_id(self) -> str:
        return "fake-reference"

    def instrument_metadata(self, symbol: str) -> dict[str, object]:
        return {"symbol": symbol, "precision": 6, "min_size": 0.001, "fees_bps": 10}

    def account_snapshot(self) -> dict[str, float]:
        return {"equity": 10_000.0, "available": 9_000.0}

    def positions(self) -> dict[str, float]:
        return {"BTC/USDT": 0.0}

    def open_orders(self) -> list[str]:
        return [c for c in self._orders if c not in self._cancelled]

    def fills(self) -> list[dict[str, object]]:
        return []

    def submit(self, intent: TradeIntent, client_order_id: str) -> str:
        if client_order_id in self._orders:
            return self._orders[client_order_id]  # idempotent echo
        ref = f"VO-{len(self._orders) + 1}"
        self._orders[client_order_id] = ref
        return ref

    def query(self, client_order_id: str) -> AckQueryResult:
        if client_order_id in self._orders:
            return AckQueryResult.FOUND
        return AckQueryResult.ABSENT

    def venue_order_id_of(self, client_order_id: str) -> str | None:
        return self._orders.get(client_order_id)

    def cancel(self, client_order_id: str) -> str:
        self._cancelled.add(client_order_id)
        return "CANCELLED"

    def reconnect(self) -> None:
        self._reconnects += 1

    def staleness(self) -> float:
        return 0.0


class NonCompliantAdapter(CompliantFakeAdapter):
    """Violates idempotency: mints a new venue order on duplicate submit."""

    def submit(self, intent: TradeIntent, client_order_id: str) -> str:
        ref = f"VO-{len(self._orders) + 1}"
        self._orders[client_order_id] = ref
        return ref


def test_compliant_adapter_passes_full_suite() -> None:
    passed, checks = run_conformance(CompliantFakeAdapter())
    assert passed, [f"{c.name}: {c.detail}" for c in checks if not c.passed]
    names = {c.name for c in checks}
    assert {
        "identity_stable",
        "metadata_available",
        "account_snapshot",
        "positions_queryable",
        "open_orders_queryable",
        "fills_queryable",
        "submit_returns_venue_ref",
        "query_found_by_cloid",
        "venue_order_id_correlated",
        "duplicate_submit_single_economic_order",
        "cancel_confirmed",
        "query_after_cancel_definitive",
        "reconnect_preserves_state",
        "startup_reconciliation_inputs",
        "staleness_exposed",
        "gateway_round_trip_idempotent",
    } <= names


def test_non_compliant_adapter_fails_idempotency_check() -> None:
    passed, checks = run_conformance(NonCompliantAdapter())
    failed = [c.name for c in checks if not c.passed]
    assert not passed
    assert "gateway_round_trip_idempotent" in failed


def test_suite_is_deterministic() -> None:
    first = run_conformance(CompliantFakeAdapter())
    second = run_conformance(CompliantFakeAdapter())
    assert [c.name for c in first[1]] == [c.name for c in second[1]]
    assert first[0] == second[0]
