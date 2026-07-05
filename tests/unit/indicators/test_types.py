"""Tests for ``IndicatorOutput`` contract (TSK-200.1.2).

Per docs/specs/TSK-200-indicators-interface/05-tasks.md row .2:

- DoD: ``FrozenInstanceError`` on mutation; ``slots=True`` verified.

Two tests cover those exact invariants; ``IndicatorParams`` is shipped
alongside but its invariants land in TSK-200.1.3, alongside the
``__post_init__`` finiteness checks.
"""

import dataclasses

import pytest

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
