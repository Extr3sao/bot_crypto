"""ExecutionService — runtime-mounted execution authority.

PORTFOLIO-AND-RUNTIME-INTEGRATION-01, Track C (EXECUTION-RUNTIME-WIRING-01).
Makes the 814f0e4 / hardening-01 primitives runtime-reachable through one
mounted path:

    TradeIntent -> stable intent_id -> stable client_order_id
      -> ExecutionJournal (durable JSONL, reloaded on restart)
      -> ExecutionGateway (idempotent submit gate, ACK recovery, fills)
      -> VenuePort adapter (fake / simulated / paper today; LIVE disabled)

Runtime invariants carried over from the certified primitives:

- ECONOMIC_ORDERS_PER_INTENT <= 1 under retries, restarts and ambiguity.
- Wall clock is metadata only; economic identity is canonical.
- Every transition is journaled append-only; restarts reload the journal and
  never resubmit a non-terminal intent.
- Startup reconciliation is fail-closed: EXECUTION_READY only after
  instrument metadata, account, positions, open orders and recent fills have
  been reconciled.

No live trading is enabled: the venue port is injected by the caller.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from trading_bot.execution.feed_guard import FeedGuardVerdict
from trading_bot.execution.gateway import ExecutionGateway, GatewayReceipt, VenuePort
from trading_bot.execution.intent import (
    AckQueryResult,
    ExecutionReliabilityError,
    FillApplication,
    TradeIntent,
)
from trading_bot.execution.journal import ExecutionJournal, ExecutionState

__all__ = [
    "AmbiguousSubmit",
    "ExecutionService",
    "FeedBlockedError",
    "StartupReconciliationReport",
]


class FeedBlockedError(ExecutionReliabilityError):
    """A feed dead-man BLOCK verdict forbade this entry; nothing was sent.

    The intent is intentionally NOT journaled as REJECTED: staleness is
    transient and the same economic intent may legitimately execute once the
    feed recovers. Evidence is carried on the exception.
    """

    def __init__(self, verdict: FeedGuardVerdict) -> None:
        super().__init__(f"feed BLOCK active ({verdict.action.value}); entry forbidden")
        self.verdict = verdict


class AmbiguousSubmit(ExecutionReliabilityError):
    """Submit raised after arming: outcome unknown, resolve via ``resolve_ack``."""


@dataclass
class StartupReconciliationReport:
    """Result of replaying a durable journal and reconciling with the venue."""

    intents_replayed: int
    adopted: tuple[str, ...]
    closed: tuple[str, ...]
    unresolvable: tuple[str, ...]
    ready: bool
    missing: tuple[str, ...]

    @property
    def clean(self) -> bool:
        return not self.unresolvable


# States from which a re-execute MUST NOT submit again (restart residue or
# already-live intent). CREATED is deliberately absent: it means registered
# but no venue call ever armed, so submission may proceed under the gate.
_STICKY_STATES: frozenset[ExecutionState] = frozenset(
    {
        ExecutionState.SUBMITTING,
        ExecutionState.ACK_UNKNOWN,
        ExecutionState.ACCEPTED,
        ExecutionState.PARTIALLY_FILLED,
        ExecutionState.FILLED,
        ExecutionState.CANCEL_PENDING,
        ExecutionState.CANCELLED,
        ExecutionState.REJECTED,
        ExecutionState.ORPHANED,
        ExecutionState.RECONCILING,
    }
)


@dataclass
class ExecutionService:
    """Single mounted authority path from economic intents to a venue.

    The service owns ONE journal shared with its gateway, so every actor
    (submit, recovery, fills, reconciliation) observes the same durable
    state machine. Mount durably with :meth:`from_path` to survive restarts.
    """

    journal: ExecutionJournal = field(default_factory=ExecutionJournal)
    gateway: ExecutionGateway = field(default_factory=ExecutionGateway)
    _intents: dict[str, TradeIntent] = field(default_factory=dict)

    def __post_init__(self) -> None:
        # One authority journal: the gateway must observe the same FSM state.
        self.gateway.journal = self.journal

    @classmethod
    def from_path(cls, path: Path | str) -> ExecutionService:
        """Mount durably: append transitions to ``path`` and replay any
        transitions already persisted there (restart recovery)."""
        journal = ExecutionJournal(path=Path(path))
        journal.load_replay()
        return cls(journal=journal, gateway=ExecutionGateway(journal=journal))

    # -- identity -----------------------------------------------------------
    def intent_id(self, intent: TradeIntent) -> str:
        return self.gateway.intent_id(intent)

    def client_order_id(self, intent: TradeIntent) -> str:
        return self.gateway.client_order_id(intent)

    # -- submit path ----------------------------------------------------------
    def execute(
        self,
        intent: TradeIntent,
        venue: VenuePort,
        *,
        reason: str = "execution service submit",
        evidence: dict[str, Any] | None = None,
    ) -> GatewayReceipt:
        """Submit an intent through the full authority path.

        - Feed BLOCK verdict (in ``evidence["feed_verdict"]``): nothing is
          sent or journaled; :class:`FeedBlockedError` carries the verdict.
        - Restart residue (non-terminal journal state): the known venue
          reference is returned without a venue call; resolve ambiguity via
          :meth:`resolve_ack` / :meth:`reconcile_intent`.
        - Fresh intent: CREATED -> SUBMITTING -> (ACCEPTED | ACK_UNKNOWN).
        """
        verdict = (evidence or {}).get("feed_verdict")
        if verdict is not None and not self.gateway.feed_guard.allow_new_entries(verdict):
            raise FeedBlockedError(verdict)

        intent_id = self.intent_id(intent)
        self._intents[intent_id] = intent
        current = self.journal.current_state(intent_id)
        if current is not None and current in _STICKY_STATES:
            return GatewayReceipt(
                intent_id=intent_id,
                client_order_id=self.client_order_id(intent),
                venue_order_id=self.gateway._venue_refs.get(intent_id),
                journal_state=current,
                submitted_now=False,
                detail=(
                    f"intent already {current.value}; no economic order placed "
                    "(restart-safe sticky identity)"
                ),
            )
        try:
            return self.gateway.submit(intent, venue, reason=reason, evidence=evidence)
        except ExecutionReliabilityError:
            # FSM/journal programming errors propagate unchanged.
            raise
        except Exception as exc:
            # The gateway has already recorded ACK_UNKNOWN for this intent:
            # surface a uniform service-level ambiguous-submit error chained
            # to the transport failure. Resolve via ``resolve_ack``.
            raise AmbiguousSubmit(
                f"submit outcome unknown for intent {intent_id}; "
                "resolve via resolve_ack (never resubmit blindly)"
            ) from exc

    # -- ambiguous ack --------------------------------------------------------
    def resolve_ack(
        self,
        intent: TradeIntent,
        venue: VenuePort,
        *,
        query_result: AckQueryResult | None = None,
    ) -> GatewayReceipt:
        """Resolve ACK_UNKNOWN: ADOPT / CONTROLLED_RETRY (same identity) / BLOCK."""
        self._intents[self.intent_id(intent)] = intent
        return self.gateway.resolve_ack_unknown(intent, venue, query_result=query_result)

    # -- fills ----------------------------------------------------------------
    def apply_fill(
        self,
        intent: TradeIntent,
        *,
        venue_fill_id: str,
        quantity: float,
        price: float,
        fee: float = 0.0,
        timestamp: float | None = None,
    ) -> FillApplication:
        """Apply a venue fill exactly once (duplicates are no-ops)."""
        return self.gateway.apply_fill(
            intent,
            venue_fill_id=venue_fill_id,
            quantity=quantity,
            price=price,
            fee=fee,
            timestamp=timestamp,
        )

    # -- cancel ---------------------------------------------------------------
    def request_cancel(self, intent: TradeIntent, venue: VenuePort) -> GatewayReceipt:
        """CANCEL_PENDING; CANCELLED only after venue confirmation."""
        return self.gateway.request_cancel(intent, venue)

    def confirm_cancel(self, intent: TradeIntent) -> GatewayReceipt:
        """Record venue-confirmed cancellation (terminal)."""
        return self.gateway.confirm_cancel(intent)

    # -- reconciliation ---------------------------------------------------------
    def reconcile_intent(
        self,
        intent: TradeIntent,
        *,
        venue_holds_order: bool,
        venue_order_id: str | None = None,
    ) -> GatewayReceipt:
        """Adopt or close one intent after authoritative venue comparison."""
        self._intents[self.intent_id(intent)] = intent
        return self.gateway.reconcile(
            intent,
            venue_holds_order=venue_holds_order,
            venue_order_id=venue_order_id,
        )

    # -- startup reconciliation -------------------------------------------------
    def startup_reconcile(
        self,
        intents: tuple[TradeIntent, ...] | list[TradeIntent],
        *,
        venue_open_client_order_ids: frozenset[str] | set[str],
        venue_order_ids: dict[str, str] | None = None,
        prerequisites: dict[str, bool] | None = None,
    ) -> StartupReconciliationReport:
        """Replay + reconcile at startup; fail-closed EXECUTION_READY gate.

        Compare every journaled intent against the venue's authoritative open
        orders: held orders are adopted (never resubmitted); absent orders are
        closed. Prerequisites default to satisfied only when the caller
        explicitly passes them — anything missing keeps execution NOT ready.
        """
        venue_order_ids = venue_order_ids or {}
        adopted: list[str] = []
        closed: list[str] = []
        unresolvable: list[str] = []
        for intent in intents:
            intent_id = self.intent_id(intent)
            state = self.journal.current_state(intent_id)
            if state is None or state in (
                ExecutionState.CANCELLED,
                ExecutionState.REJECTED,
                ExecutionState.FILLED,
            ):
                continue  # terminal or never submitted: nothing to reconcile
            cloid = self.client_order_id(intent)
            if cloid in venue_open_client_order_ids:
                self.reconcile_intent(
                    intent,
                    venue_holds_order=True,
                    venue_order_id=venue_order_ids.get(cloid),
                )
                adopted.append(intent_id)
            else:
                self.reconcile_intent(intent, venue_holds_order=False)
                closed.append(intent_id)

        prereq = prerequisites or {}
        ready, missing = self.gateway.execution_ready(
            instrument_metadata_loaded=bool(prereq.get("instrument_metadata", False)),
            account_loaded=bool(prereq.get("account", False)),
            positions_loaded=bool(prereq.get("positions", False)),
            open_orders_loaded=bool(prereq.get("open_orders", False)),
            recent_fills_loaded=bool(prereq.get("recent_fills", False)),
        )
        return StartupReconciliationReport(
            intents_replayed=len(self.journal.intents()),
            adopted=tuple(adopted),
            closed=tuple(closed),
            unresolvable=tuple(unresolvable),
            ready=ready,
            missing=missing,
        )

    def execution_ready(self, prerequisites: dict[str, bool]) -> tuple[bool, tuple[str, ...]]:
        """Fail-closed readiness over the five reconciliation prerequisites."""
        return self.gateway.execution_ready(
            instrument_metadata_loaded=bool(prerequisites.get("instrument_metadata", False)),
            account_loaded=bool(prerequisites.get("account", False)),
            positions_loaded=bool(prerequisites.get("positions", False)),
            open_orders_loaded=bool(prerequisites.get("open_orders", False)),
            recent_fills_loaded=bool(prerequisites.get("recent_fills", False)),
        )
