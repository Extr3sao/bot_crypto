"""Bounded deterministic communication sessions for MA-1."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum

from trading_bot.multi_agent.bus import AgentBus
from trading_bot.multi_agent.communication_errors import (
    SessionMaxRoundsError,
    SessionTerminatedError,
    SessionTimeoutError,
)
from trading_bot.multi_agent.contracts import AgentMessage


class SessionStatus(StrEnum):
    """Terminal and active session states."""

    ACTIVE = "ACTIVE"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    TIMEOUT = "TIMEOUT"
    MAX_ROUNDS = "MAX_ROUNDS"


@dataclass(frozen=True, slots=True)
class CommunicationSessionState:
    """Serializable state projection used by replay and certification."""

    session_id: str
    run_id: str
    participants: tuple[str, ...]
    round: int
    max_rounds: int
    status: SessionStatus
    termination_reason: str | None
    accepted_message_ids: tuple[str, ...]


class CommunicationSession:
    """A bounded session that advances one round per accepted message."""

    def __init__(
        self,
        *,
        session_id: str,
        run_id: str,
        participants: tuple[str, ...],
        max_rounds: int,
        bus: AgentBus,
        started_at: datetime,
        timeout: timedelta | None = None,
    ) -> None:
        if not session_id or not run_id or not participants:
            raise ValueError("session identity and participants are required")
        if len(set(participants)) != len(participants):
            raise ValueError("session participants must be unique")
        if max_rounds < 1:
            raise ValueError("max_rounds must be positive")
        if started_at.tzinfo is None or started_at.utcoffset() is None:
            raise ValueError("started_at must be timezone-aware")
        if timeout is not None and timeout <= timedelta(0):
            raise ValueError("timeout must be positive")
        if run_id != bus.blackboard.run_id:
            raise ValueError("session run does not match bus run")
        self.session_id = session_id
        self.run_id = run_id
        self.participants = tuple(participants)
        self.max_rounds = max_rounds
        self.bus = bus
        self.started_at = started_at
        self.deadline = started_at + timeout if timeout is not None else None
        self._round = 0
        self._status = SessionStatus.ACTIVE
        self._termination_reason: str | None = None
        self._message_ids: list[str] = []

    @property
    def state(self) -> CommunicationSessionState:
        return CommunicationSessionState(
            session_id=self.session_id,
            run_id=self.run_id,
            participants=self.participants,
            round=self._round,
            max_rounds=self.max_rounds,
            status=self._status,
            termination_reason=self._termination_reason,
            accepted_message_ids=tuple(self._message_ids),
        )

    def send(self, message: AgentMessage, *, now: datetime | None = None) -> AgentMessage:
        """Accept one participant message or terminate fail-closed."""
        self._ensure_active(now)
        if not isinstance(message, AgentMessage):
            self.fail("message is not an AgentMessage")
            raise SessionTerminatedError(self._termination_reason or "invalid message")
        if message.sender not in self.participants or message.receiver not in self.participants:
            self.fail("message participant is outside the session")
            raise SessionTerminatedError(self._termination_reason or "invalid participant")
        if message.run_id != self.run_id:
            self.fail("message run does not match session")
            raise SessionTerminatedError(self._termination_reason or "trace mismatch")
        if self._round >= self.max_rounds:
            self._status = SessionStatus.MAX_ROUNDS
            self._termination_reason = "maximum rounds reached"
            raise SessionMaxRoundsError(self._termination_reason)
        try:
            accepted = self.bus.publish(message)
        except Exception as exc:
            self.fail(f"message rejected: {type(exc).__name__}")
            raise
        self._message_ids.append(accepted.message_id)
        self._round += 1
        if self._round >= self.max_rounds:
            self._status = SessionStatus.MAX_ROUNDS
            self._termination_reason = "maximum rounds reached"
        return accepted

    def complete(self, reason: str = "participants completed communication") -> CommunicationSessionState:
        self._ensure_active()
        self._status = SessionStatus.COMPLETED
        self._termination_reason = reason
        return self.state

    def fail(self, reason: str) -> CommunicationSessionState:
        if self._status is SessionStatus.ACTIVE:
            self._status = SessionStatus.FAILED
            self._termination_reason = reason
        return self.state

    def _ensure_active(self, now: datetime | None = None) -> None:
        if self._status is SessionStatus.MAX_ROUNDS:
            raise SessionMaxRoundsError(self._termination_reason or "maximum rounds reached")
        if self._status is not SessionStatus.ACTIVE:
            raise SessionTerminatedError(self._termination_reason or self._status.value)
        current = now or datetime.now(UTC)
        if current.tzinfo is None or current.utcoffset() is None:
            raise ValueError("now must be timezone-aware")
        if self.deadline is not None and current >= self.deadline:
            self._status = SessionStatus.TIMEOUT
            self._termination_reason = "session deadline reached"
            raise SessionTimeoutError(self._termination_reason)


class CommunicationReplay:
    """Reconstruct a session state from its accepted ordered messages."""

    @staticmethod
    def replay(session: CommunicationSession, messages: tuple[AgentMessage, ...]) -> CommunicationSessionState:
        replay_session = CommunicationSession(
            session_id=session.session_id,
            run_id=session.run_id,
            participants=session.participants,
            max_rounds=session.max_rounds,
            bus=session.bus,
            started_at=session.started_at,
            timeout=None,
        )
        for message in messages:
            if replay_session.state.status is not SessionStatus.ACTIVE:
                break
            replay_session.send(message, now=message.created_at)
        if session.state.status is SessionStatus.COMPLETED and replay_session.state.status is SessionStatus.ACTIVE:
            replay_session.complete(session.state.termination_reason or "replayed completion")
        elif session.state.status is SessionStatus.FAILED and replay_session.state.status is SessionStatus.ACTIVE:
            replay_session.fail(session.state.termination_reason or "replayed failure")
        return replay_session.state


__all__ = [
    "CommunicationReplay",
    "CommunicationSession",
    "CommunicationSessionState",
    "SessionStatus",
]
