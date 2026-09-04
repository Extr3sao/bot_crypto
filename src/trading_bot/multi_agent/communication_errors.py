"""Fail-closed errors for the deterministic MA-1 communication runtime."""

from __future__ import annotations


class CommunicationError(ValueError):
    """Base error for rejected communication operations."""


class InvalidMessageError(CommunicationError):
    """Raised when a message cannot be accepted by the bus."""


class UnknownSenderError(CommunicationError):
    """Raised when a message sender is not registered and active."""


class UnknownReceiverError(CommunicationError):
    """Raised when a direct message receiver is not registered and active."""


class UnauthorizedTopicError(CommunicationError):
    """Raised when a topic is unsupported or not permitted."""


class ExpiredMessageError(CommunicationError):
    """Raised when a message is expired or future-dated."""


class EvidenceMissingError(CommunicationError):
    """Raised when an accepted message or artifact lacks valid evidence."""


class TraceMismatchError(CommunicationError):
    """Raised when a message or evidence escapes its communication trace."""


class DuplicateMessageConflictError(CommunicationError):
    """Raised when an existing message ID is reused for different content."""


class ReplyCorrelationError(CommunicationError):
    """Raised when a reply does not match a pending request."""


class SessionTerminatedError(CommunicationError):
    """Raised when a session operation is attempted after termination."""


class SessionTimeoutError(SessionTerminatedError):
    """Raised when a communication session reaches its timeout."""


class SessionMaxRoundsError(SessionTerminatedError):
    """Raised when a communication session reaches its round limit."""


__all__ = [
    "CommunicationError",
    "DuplicateMessageConflictError",
    "EvidenceMissingError",
    "ExpiredMessageError",
    "InvalidMessageError",
    "ReplyCorrelationError",
    "SessionMaxRoundsError",
    "SessionTerminatedError",
    "SessionTimeoutError",
    "TraceMismatchError",
    "UnauthorizedTopicError",
    "UnknownReceiverError",
    "UnknownSenderError",
]
