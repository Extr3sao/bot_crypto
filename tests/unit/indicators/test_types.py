"""Tests for ``IndicatorOutput`` contract and the indicators-engine
exception hierarchy (TSK-200.1.2 + 1.3 + 1.4).

Per docs/specs/TSK-200-indicators-interface/05-tasks.md:

- TSK-200.1.2 DoD: ``FrozenInstanceError`` on mutation; ``slots=True``
  verified.
- TSK-200.1.3 DoD: NaN, ±inf, non-float raise explicitly; valid
  floats pass.
- TSK-200.1.4 DoD: ``RegistryFrozenError``,
  ``InsufficientHistoryError``, ``ParamsHashError`` importable from
  ``trading_bot.indicators.exceptions``; ``InsufficientHistoryError``
  exposes ``.required`` and ``.got``.

Seven tests cover those exact invariants; ``IndicatorParams`` is shipped
alongside but its serialization invariants land in TSK-200.2 alongside
``compute_params_hash``.
"""

import dataclasses
import math

import pytest

from trading_bot.indicators.exceptions import (
    IndicatorError,
    InsufficientHistoryError,
    ParamsHashError,
    RegistryFrozenError,
)
from trading_bot.indicators.types import IndicatorOutput


def test_indicator_output_frozen() -> None:
    """``IndicatorOutput`` instances raise ``FrozenInstanceError`` on
    attribute mutation (dataclass ``frozen=True``)."""
    output = IndicatorOutput(values={"ema": 1.0})
    with pytest.raises(dataclasses.FrozenInstanceError):
        output.values = {"ema": 2.0}  # type: ignore[misc]


def test_indicator_output_frozen_slots() -> None:
    """``IndicatorOutput`` is a slots-based dataclass: no ``__dict__``
    is allocated on the instance, and assigning an unknown attribute
    raises ``AttributeError`` (not silently stored).

    Both behaviors are direct evidence of ``slots=True``;
    silent attribute storage would imply a classic ``__dict__``-backed
    dataclass.
    """
    output = IndicatorOutput(values={"ema": 1.0})
    assert not hasattr(output, "__dict__")
    with pytest.raises(AttributeError):
        output.nonexistent = 1.0  # type: ignore[attr-defined]


def test_indicator_output_post_init_rejects_nan() -> None:
    """NaN entries in ``values`` raise ``ValueError`` at construction."""
    with pytest.raises(ValueError, match="finite"):
        IndicatorOutput(values={"ema": float("nan")})


def test_indicator_output_post_init_rejects_inf() -> None:
    """``+inf`` and ``-inf`` entries raise ``ValueError`` at construction."""
    with pytest.raises(ValueError, match="finite"):
        IndicatorOutput(values={"pos": math.inf})
    with pytest.raises(ValueError, match="finite"):
        IndicatorOutput(values={"neg": -math.inf})


def test_indicator_output_post_init_rejects_non_float() -> None:
    """Non-float entries (``str``, ``int``) raise ``TypeError`` at
    construction.

    Only the ``str`` case carries a ``# type: ignore[dict-item]``
    suppression: mypy rejects ``dict[str, str]`` against ``dict[str,
    float]``.  The ``int`` case does NOT — mypy treats ``dict[str,
    int]`` as compatible (int promotes to float implicitly under PEP
    484 in argument positions); a suppression there would be
    ``[unused-ignore]`` dead code.  ``__post_init__`` still rejects
    the runtime int via ``isinstance(value, float)``, so the test path
    is intact.
    """
    with pytest.raises(TypeError, match="must be float"):
        IndicatorOutput(values={"x": "1.0"})  # type: ignore[dict-item]
    with pytest.raises(TypeError, match="must be float"):
        IndicatorOutput(values={"x": 1})


def test_exceptions_inherit_indicator_error() -> None:
    """Every concrete indicator exception inherits from
    ``IndicatorError``.

    This is the contract that lets callers write one
    ``except IndicatorError`` catch-all and still distinguish
    subclasses programmatically (e.g. observability counters per
    error class).  ``IndicatorError`` itself extends :class:`Exception`
    (not :class:`BaseException`) so ``KeyboardInterrupt`` /
    ``SystemExit`` are NOT silently absorbed by an
    ``except IndicatorError`` block.
    """
    assert issubclass(RegistryFrozenError, IndicatorError)
    assert issubclass(InsufficientHistoryError, IndicatorError)
    assert issubclass(ParamsHashError, IndicatorError)
    assert issubclass(IndicatorError, Exception)


def test_insufficient_history_error_attributes_required_got() -> None:
    """``InsufficientHistoryError`` exposes ``.required`` and ``.got``
    attributes (int), and the exception message includes both
    numbers.

    The orchestrator consumes these attributes directly to emit the
    ``indicator.insufficient_history`` structured log line (see
    ``03-specify.md`` sec. 9).  Stringifying the args into the message
    keeps the error readable in tracebacks without losing
    programmatic access.  Construction args are exactly
    ``(required, got)`` in that order — no keyword-only quirks.
    """
    err = InsufficientHistoryError(required=100, got=42)
    assert err.required == 100
    assert err.got == 42
    # The args tuple reflects the message format used in __init__.
    assert "100" in err.args[0]
    assert "42" in err.args[0]
    # Defense-in-depth: still an IndicatorError subclass; can be raised
    # inside an ``except InsufficientHistoryError`` block.
    assert isinstance(err, IndicatorError)
    with pytest.raises(InsufficientHistoryError):
        raise InsufficientHistoryError(required=10, got=3)
