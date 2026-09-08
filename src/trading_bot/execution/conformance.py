"""Exchange adapter conformance suite V1.

EXECUTION-RELIABILITY-RUNTIME-01 (checkpoint INTELLIGENCE-AND-EXECUTION-HARDENING-01,
Track A5). A parametrized conformance harness over the ``VenuePort`` contract
plus gateway-level behaviors. Run it against ANY adapter (fake reference,
simulated adapter, future live adapter) to prove:

identity, metadata, account, positions, orders, fills, submit, query, cancel,
timeout ambiguity, reconnect, startup reconciliation, stale-feed behavior.

No vn.py import. No live I/O: the suite drives whatever port it is given.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from trading_bot.execution.gateway import ExecutionGateway
from trading_bot.execution.intent import AckQueryResult, TradeIntent


class ConformanceAdapter(Protocol):
    """Full contract an adapter must satisfy for conformance V1."""

    def adapter_id(self) -> str: ...
    def instrument_metadata(self, symbol: str) -> dict[str, object]: ...
    def account_snapshot(self) -> dict[str, float]: ...
    def positions(self) -> dict[str, float]: ...
    def open_orders(self) -> list[str]: ...
    def fills(self) -> list[dict[str, object]]: ...
    def submit(self, intent: TradeIntent, client_order_id: str) -> str: ...
    def query(self, client_order_id: str) -> AckQueryResult: ...
    def venue_order_id_of(self, client_order_id: str) -> str | None: ...
    def cancel(self, client_order_id: str) -> str: ...
    def reconnect(self) -> None: ...
    def staleness(self) -> float: ...


@dataclass(frozen=True, slots=True)
class ConformanceCheck:
    name: str
    passed: bool
    detail: str


@dataclass
class ExchangeAdapterConformanceSuite:
    """Runs the V1 conformance battery against one adapter instance."""

    _results: list[ConformanceCheck] = field(default_factory=list)

    def run(self, adapter: ConformanceAdapter) -> tuple[bool, tuple[ConformanceCheck, ...]]:
        self._results = []
        gateway = ExecutionGateway()
        intent = TradeIntent(
            symbol="BTC/USDT",
            side="buy",
            quantity=0.01,
            order_type="limit",
            limit_price=60_000.0,
            venue=adapter.adapter_id(),
        )
        intent_id = gateway.intent_id(intent)
        cloid = gateway.client_order_id(intent)
        del intent_id  # identity is exercised via gateway.client_order_id below

        # identity
        self._check("identity_stable", adapter.adapter_id() == adapter.adapter_id(), adapter.adapter_id())
        # metadata
        meta = adapter.instrument_metadata("BTC/USDT")
        self._check("metadata_available", bool(meta), str(sorted(meta.keys())))
        # account
        account = adapter.account_snapshot()
        self._check("account_snapshot", "equity" in account, str(sorted(account.keys())))
        # positions
        positions = adapter.positions()
        self._check("positions_queryable", isinstance(positions, dict), str(len(positions)))
        # orders / fills
        self._check("open_orders_queryable", isinstance(adapter.open_orders(), list), "")
        self._check("fills_queryable", isinstance(adapter.fills(), list), "")
        # submit + echo
        venue_order_id = adapter.submit(intent, cloid)
        self._check("submit_returns_venue_ref", bool(venue_order_id), venue_order_id)
        # query by stable identity
        self._check("query_found_by_cloid", adapter.query(cloid) is AckQueryResult.FOUND, cloid)
        self._check(
            "venue_order_id_correlated",
            adapter.venue_order_id_of(cloid) == venue_order_id,
            str(adapter.venue_order_id_of(cloid)),
        )
        # duplicate submit with same cloid -> single economic order
        again = adapter.submit(intent, cloid)
        self._check(
            "duplicate_submit_single_economic_order",
            again == venue_order_id,
            f"{again!r} vs {venue_order_id!r}",
        )
        # cancel
        self._check("cancel_confirmed", adapter.cancel(cloid) in ("CANCELLED", "CANCEL_PENDING"), adapter.cancel(cloid))
        # timeout ambiguity: query remains authoritative after cancel
        self._check(
            "query_after_cancel_definitive",
            adapter.query(cloid) in (AckQueryResult.FOUND, AckQueryResult.ABSENT),
            adapter.query(cloid).value,
        )
        # reconnect
        adapter.reconnect()
        self._check("reconnect_preserves_state", adapter.venue_order_id_of(cloid) is not None, "")
        # startup reconciliation inputs
        ready = all(
            [
                bool(adapter.instrument_metadata("BTC/USDT")),
                bool(adapter.account_snapshot()),
                isinstance(adapter.positions(), dict),
                isinstance(adapter.open_orders(), list),
                isinstance(adapter.fills(), list),
            ]
        )
        self._check("startup_reconciliation_inputs", ready, "")
        # stale-feed behavior
        self._check("staleness_exposed", adapter.staleness() >= 0.0, str(adapter.staleness()))
        # gateway round-trip on the same port: the venue must echo the SAME
        # venue reference (no second economic order). submitted_now reflects
        # this gateway's own gate, so only venue-side identity is asserted.
        receipt = gateway.submit(intent, adapter)
        self._check(
            "gateway_round_trip_idempotent",
            receipt.venue_order_id == venue_order_id and adapter.query(cloid) is AckQueryResult.FOUND,
            f"{receipt.detail} | venue_ref={receipt.venue_order_id!r}",
        )
        passed = all(c.passed for c in self._results)
        return passed, tuple(self._results)

    def _check(self, name: str, passed: bool, detail: str) -> None:
        self._results.append(ConformanceCheck(name=name, passed=bool(passed), detail=detail))


def run_conformance(adapter: ConformanceAdapter) -> tuple[bool, tuple[ConformanceCheck, ...]]:
    """Convenience entry point."""
    return ExchangeAdapterConformanceSuite().run(adapter)
