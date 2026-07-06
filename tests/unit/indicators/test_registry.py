"""Tests for IndicatorRegistry (TSK-200, F3 / TSK-200.3.1..3.3).

Per docs/specs/TSK-200-indicators-interface/05-tasks.md F3 rows
TSK-200.3.1, TSK-200.3.2, TSK-200.3.3.

Covers:
- TSK-200.3.1: register new, register duplicate raises, all() order,
  __len__.
- TSK-200.3.2: freeze() blocks register, freeze() idempotent,
  is_frozen property.
- TSK-200.3.3: get() returns indicator, get() raises KeyError.
- Defensive: TypeError on non-Protocol candidates, TypeError on
  candidates missing the ``name: str`` data attribute (per
  think-with-files Q1 hybrid validation).

Exercises the full pre-freeze + post-freeze lifecycle including
read-only operations remaining valid after freeze per CL-7.
"""

from __future__ import annotations

import pytest

from trading_bot.indicators.exceptions import RegistryFrozenError
from trading_bot.indicators.registry import IndicatorRegistry
from trading_bot.indicators.types import IndicatorOutput, IndicatorParams
from trading_bot.market_data.types import OHLCV

# ---------------------------------------------------------------------
# Helpers — fake Indicator Protocol implementations
# ---------------------------------------------------------------------


class _FakeIndicator:
    """Minimal valid Indicator: callable ``compute`` + ``name: str``
    attribute.  The ``compute`` signature matches the
    ``Indicator`` Protocol exactly (list[OHLCV] + IndicatorParams +
    -> IndicatorOutput) so mypy --strict accepts the assignment to
    ``register(name, indicator: Indicator)`` without requiring a
    ``# type: ignore[arg-type]`` comment."""

    def __init__(self, name: str = "fake") -> None:
        self.name = name

    def compute(self, ohlcv: list[OHLCV], params: IndicatorParams) -> IndicatorOutput:
        # Body is a no-op for registry tests; the return type just
        # satisfies the Protocol contract.
        return IndicatorOutput(values={"fake": 0.0})


class _NonProtocolIndicator:
    """Deliberately missing ``compute`` method; PEP 544
    ``runtime_checkable`` rejects this candidate at ``isinstance``
    time.  ``name`` is present (a string literal) to ensure mypy's
    static check rejects ONLY on the missing ``compute`` axis."""

    name = "broken"


class _MissingNameIndicator:
    """Has a Protocol-compliant ``compute`` method but ``name`` is
    ``None`` (NOT a string).  PEP 544 ``runtime_checkable`` accepts
    this (it only checks callable ``compute``, not data attributes),
    so the candidate passes the first isinstance gate.  The registry's
    defensive ``isinstance(getattr(obj, 'name', None), str)`` check
    is what must reject this candidate — this is precisely the
    branch the test docstring claims to verify."""

    name = None  # explicitly NOT a str; defensive check rejects this

    def compute(self, ohlcv: list[OHLCV], params: IndicatorParams) -> IndicatorOutput:
        return IndicatorOutput(values={"x": 0.0})


# ---------------------------------------------------------------------
# TSK-200.3.1 — register / duplicates / order / len
# ---------------------------------------------------------------------


def test_register_new_indicator() -> None:
    """Fresh registry accepts a valid Indicator under a unique name."""
    reg = IndicatorRegistry()
    fake = _FakeIndicator(name="rsi")
    reg.register("rsi", fake)
    assert "rsi" in reg
    assert len(reg) == 1


def test_register_duplicate_name_raises_value_error() -> None:
    """Second register() with the same name raises ValueError (not RegistryFrozenError)."""
    reg = IndicatorRegistry()
    reg.register("ema", _FakeIndicator(name="ema"))
    with pytest.raises(ValueError, match="already registered"):
        reg.register("ema", _FakeIndicator(name="ema"))


def test_all_returns_insertion_order() -> None:
    """all() preserves the OrderedDict insertion order."""
    reg = IndicatorRegistry()
    a = _FakeIndicator(name="a")
    b = _FakeIndicator(name="b")
    c = _FakeIndicator(name="c")
    reg.register("a", a)
    reg.register("b", b)
    reg.register("c", c)
    assert reg.all() == [a, b, c]


def test_len_tracks_registered_indicators() -> None:
    """__len__ matches the number of registered indicators."""
    reg = IndicatorRegistry()
    assert len(reg) == 0
    reg.register("a", _FakeIndicator(name="a"))
    assert len(reg) == 1
    reg.register("b", _FakeIndicator(name="b"))
    assert len(reg) == 2


# ---------------------------------------------------------------------
# TSK-200.3.2 — freeze() blocks register / idempotent / is_frozen
# ---------------------------------------------------------------------


def test_freeze_blocks_register_with_registry_frozen_error() -> None:
    """Post-freeze register() raises RegistryFrozenError (NOT ValueError);
    the freeze-related error class is distinct from duplicate-name to
    make CLI / runtime diagnostics unambiguous."""
    reg = IndicatorRegistry()
    reg.register("a", _FakeIndicator(name="a"))
    reg.freeze()
    with pytest.raises(RegistryFrozenError, match="frozen"):
        reg.register("b", _FakeIndicator(name="b"))


def test_freeze_idempotent_second_call_is_noop() -> None:
    """Second freeze() is silently OK per CL-7; is_frozen remains True (still True)."""
    reg = IndicatorRegistry()
    reg.freeze()
    assert reg.is_frozen is True
    # Second freeze() must not raise.
    reg.freeze()
    assert reg.is_frozen is True


def test_is_frozen_property_transitions_false_to_true() -> None:
    """is_frozen property reflects freeze() state; pre-freeze False, post-freeze True."""
    reg = IndicatorRegistry()
    assert reg.is_frozen is False
    reg.freeze()
    assert reg.is_frozen is True


# ---------------------------------------------------------------------
# TSK-200.3.3 — get() / __contains__ post-freeze
# ---------------------------------------------------------------------


def test_get_returns_registered_indicator() -> None:
    """get(name) returns the exact Indicator instance registered."""
    reg = IndicatorRegistry()
    fake = _FakeIndicator(name="rsi")
    reg.register("rsi", fake)
    assert reg.get("rsi") is fake


def test_get_missing_raises_key_error() -> None:
    """get(unknown) raises KeyError (registry miss, NOT IndicatorError;
    the distinction is intentional — registry lookup failures are
    separate from indicator engine failures)."""
    reg = IndicatorRegistry()
    with pytest.raises(KeyError, match="not registered"):
        reg.get("missing")


def test_read_only_ops_continue_post_freeze() -> None:
    """get / __contains__ / __len__ / all work normally after freeze()
    — only mutators raise. CL-7 keeps the registry usable for queries."""
    reg = IndicatorRegistry()
    fake_a = _FakeIndicator(name="a")
    reg.register("a", fake_a)
    reg.freeze()
    assert reg.get("a") is fake_a
    assert "a" in reg
    assert "missing" not in reg
    assert len(reg) == 1
    assert reg.all() == [fake_a]


# ---------------------------------------------------------------------
# Defensive — Protocol validation per Q1 hybrid check
# ---------------------------------------------------------------------


def test_register_non_protocol_candidate_raises_type_error() -> None:
    """Candidate lacking callable ``compute`` fails PEP 544 isinstance;
    registry raises TypeError with the ``Indicator Protocol`` message
    so the failure mode is unambiguous (``name`` defensive check is
    not what fires here)."""
    reg = IndicatorRegistry()
    with pytest.raises(TypeError, match="Indicator Protocol"):
        reg.register("broken", _NonProtocolIndicator())  # type: ignore[arg-type]


def test_register_missing_name_attribute_raises_type_error() -> None:
    """Candidate with a callable ``compute`` but ``name: None`` (NOT a
    str) PASSES the PEP 544 isinstance check (runtime_checkable
    only checks methods, NOT data attributes), then fails the
    registry's defensive ``isinstance(getattr(obj, 'name', None),
    str)`` check.  The error message contains ``name`` so we can
    pin the SPECIFIC defensive branch that fired."""
    reg = IndicatorRegistry()
    with pytest.raises(TypeError, match="name"):
        reg.register("bad", _MissingNameIndicator())  # type: ignore[arg-type]
