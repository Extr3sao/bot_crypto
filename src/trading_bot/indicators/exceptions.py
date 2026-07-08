"""Exceptions for the indicator engine (TSK-200)."""

from __future__ import annotations


class IndicatorError(Exception):
    """Base class for indicator-engine errors."""


class UnknownIndicatorTypeError(IndicatorError):
    """Raised when config references an unregistered indicator type."""


__all__ = ["IndicatorError", "UnknownIndicatorTypeError"]
