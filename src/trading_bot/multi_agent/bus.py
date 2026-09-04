"""In-process deterministic typed AgentBus for MA-1."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from typing import Final

from trading_bot.multi_agent.blackboard import Blackboard
from trading_bot.multi_agent.communication_errors import (
    DuplicateMessageConflictError,
    EvidenceMissingError,
    ExpiredMessageError,
    InvalidMessageError,
    ReplyCorrelationError,
    TraceMismatchError,
    UnauthorizedTopicError,
    UnknownReceiverError,
    UnknownSenderError,
)
from trading_bot.multi_agent.contracts import (
    AgentCapability,
    AgentEvidence,
    AgentLifecycleState,
    AgentMessage,
    AgentMessageType,
    TraceContext,
)
from trading_bot.multi_agent.registry import AgentRegistry, CapabilityRegistry

MessageHandler = Callable[[AgentMessage], None]

TOPIC_BY_MESSAGE_TYPE: Final[dict[AgentMessageType, str]] = {
    AgentMessageType.OBSERVATION: "market_state",
    AgentMessageType.PROPOSAL: "proposals",
    AgentMessageType.CRITIQUE: "criticisms",
    AgentMessageType.COUNTERPROPOSAL: "strategy_candidates",
    AgentMessageType.RISK_WARNING: "risk_flags",
    AgentMessageType.VETO: "risk_flags",
    AgentMessageType.AGREEMENT: "decision_state",
    AgentMessageType.DECISION: "decision_state",
    AgentMessageType.HANDOFF: "asset_context",
    AgentMessageType.STATUS: "decision_state",
    AgentMessageType.EVIDENCE_REQUEST: "evidence",
    AgentMessageType.EVIDENCE_RESPONSE: "evidence",
}


class AgentBus:
    """Synchronous FIFO bus; accepted messages are delivered exactly once."""

    def __init__(
        self,
        *,
        agent_registry: AgentRegistry,
        capability_registry: CapabilityRegistry,
        blackboard: Blackboard,
        clock: Callable[[], datetime],
    ) -> None:
        """Create a bus bound to one explicit temporal authority.

        The run clock is a required constructor dependency: temporal
        validation must never fall back to host wall-clock time, otherwise
        deterministic replay against historical fixtures silently fails
        (DEF-MA2-001).
        """
        self.agent_registry = agent_registry
        self.capability_registry = capability_registry
        self.blackboard = blackboard
        self._clock = clock
        self._handlers: dict[str, MessageHandler] = {}
        self._subscriptions: dict[str, list[tuple[str, MessageHandler]]] = {}
        self._accepted: list[AgentMessage] = []
        self._accepted_by_id: dict[str, AgentMessage] = {}
        self._pending_requests: dict[str, str] = {}
        self._evidence: dict[str, AgentEvidence] = {}

    def now(self) -> datetime:
        """Return the current decision time from the injected run clock.

        Single temporal authority for every bus-side temporal comparison
        (message expiry, future-dated rejection, evidence availability).
        """
        return self._clock()

    @property
    def accepted_messages(self) -> tuple[AgentMessage, ...]:
        return tuple(self._accepted)

    @property
    def evidence(self) -> tuple[AgentEvidence, ...]:
        return tuple(self._evidence.values())

    def register_handler(self, agent_id: str, handler: MessageHandler) -> None:
        """Attach a deterministic endpoint to an already enabled identity."""
        self._require_enabled(agent_id, receiver=True)
        self._handlers[agent_id] = handler

    def register_evidence(self, evidence: AgentEvidence) -> None:
        """Register immutable evidence before it is referenced by a message."""
        self._require_enabled(evidence.producer_agent_id)
        producer_version = self.agent_registry.get(evidence.producer_agent_id).agent_version
        if not self.capability_registry.is_allowed(
            evidence.producer_agent_id, producer_version, AgentCapability.WRITE
        ):
            raise UnauthorizedTopicError(
                f"evidence producer lacks WRITE capability: {evidence.producer_agent_id}"
            )
        if evidence.run_id != self.blackboard.run_id:
            raise TraceMismatchError("evidence run does not match bus run")
        if evidence.trace is not None and evidence.trace.trace_id != self.blackboard.trace_id:
            raise TraceMismatchError("evidence trace does not match bus trace")
        existing = self._evidence.get(evidence.evidence_id)
        if existing is not None and existing != evidence:
            raise DuplicateMessageConflictError(
                f"evidence ID already exists with different content: {evidence.evidence_id}"
            )
        self._evidence[evidence.evidence_id] = evidence

    def subscribe(self, subscriber: str, topic: str, handler: MessageHandler) -> None:
        self._require_enabled(subscriber, receiver=True)
        if topic not in self.blackboard_topics:
            raise UnauthorizedTopicError(f"unsupported topic: {topic}")
        if not self.capability_registry.is_allowed(
            subscriber, self.agent_registry.get(subscriber).agent_version, AgentCapability.READ
        ):
            raise UnauthorizedTopicError(f"subscriber lacks READ capability: {subscriber}")
        self._subscriptions.setdefault(topic, []).append((subscriber, handler))

    @property
    def blackboard_topics(self) -> frozenset[str]:
        from trading_bot.multi_agent.blackboard import BLACKBOARD_TOPICS

        return BLACKBOARD_TOPICS

    def publish(self, message: AgentMessage, *, topic: str | None = None) -> AgentMessage:
        """Validate, append, broadcast to subscriptions, and route a message."""
        self._validate(message)
        expected_topic = TOPIC_BY_MESSAGE_TYPE.get(message.message_type)
        if expected_topic is None or (topic is not None and topic != expected_topic):
            raise UnauthorizedTopicError(
                f"topic is not authorized for message type {message.message_type}: {topic}"
            )
        if isinstance(message, AgentMessage):
            existing = self._accepted_by_id.get(message.message_id)
            if existing is not None:
                if existing != message:
                    raise DuplicateMessageConflictError(
                        f"message ID already exists with different content: {message.message_id}"
                    )
                return existing
        topic = expected_topic
        if topic is None:
            raise UnauthorizedTopicError(f"no topic for message type: {message.message_type}")
        self._accepted.append(message)
        self._accepted_by_id[message.message_id] = message
        if message.requires_response:
            self._pending_requests[message.message_id] = message.sender
        self._publish_artifact(message, topic)
        for _, handler in self._subscriptions.get(topic, ()):
            handler(message)
        if message.receiver in self._handlers:
            self._handlers[message.receiver](message)
        return message

    def direct_route(self, message: AgentMessage) -> AgentMessage:
        """Publish a message whose declared receiver is the endpoint."""
        return self.publish(message)

    def broadcast(self, message: AgentMessage) -> tuple[AgentMessage, ...]:
        """Deliver one immutable message to every eligible enabled receiver."""
        self._validate(message, allow_broadcast=True)
        receivers = tuple(
            agent_id for agent_id in sorted(self._handlers) if agent_id != message.sender
        )
        delivered: list[AgentMessage] = []
        for receiver in receivers:
            clone = message.model_copy(
                update={
                    "message_id": f"{message.message_id}:{receiver}",
                    "receiver": receiver,
                }
            )
            delivered.append(self.publish(clone))
        return tuple(delivered)

    def request(self, message: AgentMessage) -> AgentMessage:
        if not message.requires_response:
            raise InvalidMessageError("request message must set requires_response=True")
        return self.publish(message)

    def reply(self, message: AgentMessage, *, request_id: str) -> AgentMessage:
        requester = self._pending_requests.get(request_id)
        if requester is None:
            raise ReplyCorrelationError(f"unknown request: {request_id}")
        if message.causation_id != request_id:
            raise ReplyCorrelationError("reply causation_id must equal request_id")
        if message.receiver != requester:
            raise ReplyCorrelationError("reply receiver must equal original requester")
        return self.publish(message)

    def _require_enabled(self, agent_id: str, *, receiver: bool = False) -> None:
        try:
            manifest = self.agent_registry.get(agent_id)
        except ValueError as exc:
            error = UnknownReceiverError if receiver else UnknownSenderError
            raise error(f"unknown agent: {agent_id}") from exc
        if manifest.lifecycle_state is not AgentLifecycleState.ENABLED:
            error = UnknownReceiverError if receiver else UnknownSenderError
            raise error(f"agent is not enabled: {agent_id}")

    def _validate(self, message: AgentMessage, *, allow_broadcast: bool = False) -> None:
        if not isinstance(message, AgentMessage):
            raise InvalidMessageError("bus accepts only AgentMessage instances")
        if message.trace is None:
            raise InvalidMessageError("accepted messages must carry TraceContext")
        if message.trace.run_id != message.run_id or message.trace.trace_id != message.trace_id:
            raise TraceMismatchError("message trace identifiers do not match message identifiers")
        self._require_enabled(message.sender)
        if not allow_broadcast:
            self._require_enabled(message.receiver, receiver=True)
            receiver_version = self.agent_registry.get(message.receiver).agent_version
            if not self.capability_registry.is_allowed(
                message.receiver, receiver_version, AgentCapability.READ
            ):
                raise UnauthorizedTopicError(f"receiver lacks READ capability: {message.receiver}")
        if message.run_id != self.blackboard.run_id or message.trace_id != self.blackboard.trace_id:
            raise TraceMismatchError("message trace does not match bus trace")
        now = self.now()
        if message.expires_at is not None and now >= message.expires_at:
            raise ExpiredMessageError(f"message expired: {message.message_id}")
        if message.created_at > now:
            raise ExpiredMessageError(f"message is future-dated: {message.message_id}")
        version = self.agent_registry.get(message.sender).agent_version
        if not self.capability_registry.is_allowed(message.sender, version, AgentCapability.WRITE):
            raise UnauthorizedTopicError(f"sender lacks WRITE capability: {message.sender}")
        if message.evidence_refs:
            for evidence_id in message.evidence_refs:
                evidence = self._evidence.get(evidence_id)
                if evidence is None:
                    raise EvidenceMissingError(f"unknown evidence: {evidence_id}")
                if not evidence.is_valid_at(message.created_at):
                    raise ExpiredMessageError(
                        f"evidence unavailable at message time: {evidence_id}"
                    )
        elif message.message_type in {
            AgentMessageType.PROPOSAL,
            AgentMessageType.CRITIQUE,
            AgentMessageType.EVIDENCE_RESPONSE,
        }:
            raise EvidenceMissingError(f"message type requires evidence: {message.message_type}")

    def _publish_artifact(self, message: AgentMessage, topic: str) -> None:
        self.blackboard.publish(
            artifact_id=f"message:{message.message_id}",
            topic=topic,
            producer=message.sender,
            timestamp=message.created_at,
            trace=message.trace
            or TraceContext(
                run_id=message.run_id,
                trace_id=message.trace_id,
                correlation_id=message.correlation_id or message.message_id,
                causation_id=message.causation_id or message.message_id,
            ),
            value=message,
            evidence=tuple(self._evidence[item] for item in message.evidence_refs),
        )


__all__ = ["TOPIC_BY_MESSAGE_TYPE", "AgentBus", "MessageHandler"]
