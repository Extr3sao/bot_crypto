"""Tests for the ``Indicator`` Protocol contract (TSK-200.2.1).

Per docs/specs/TSK-200-indicators-interface/05-tasks.md row .1:
- TSK-200.2.1 DoD: ``isinstance(fake, Indicator)`` -> ``True`` when
  the candidate exposes a callable ``compute`` method; ``mypy
  --strict`` detects the static structural contracts (``name: str`` +
  signature match for ``compute``).  ``@runtime_checkable`` allows
  the runtime isinstance check; data-attribute coverage (``name``)
  remains a mypy-strict responsibility per PEP 544.

The single spec-mapped test verifies the runtime isinstance
semantics.  ``FakeIndicator`` below mirrors the Protocol shape so
mypy accepts it without a suppression.  ``from __future__ import
annotations`` makes ``list[OHLCV]`` a lazy annotation on Python
3.11 (PEP 563) so the test module imports cleanly without
``OHLCV`` bound at runtime; the type checker still resolves it via
the ``TYPE_CHECKING`` guard.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from trading_bot.indicators.protocols import Indicator
from trading_bot.indicators.types import IndicatorOutput, IndicatorParams

if TYPE_CHECKING:
    from trading_bot.market_data.types import OHLCV


class FakeIndicator:
    """Minimal concrete indicator for runtime_checkable isinstance check.

    Mirrors the structural contract of ``Indicator``:
    - ``name: str`` class attribute (enforced statically by
      ``mypy --strict``).
    - ``compute(ohlcv, params) -> IndicatorOutput`` callable.
    """

    name: str = "fake"

    def compute(
        self,
        ohlcv: list[OHLCV],
        params: IndicatorParams,
    ) -> IndicatorOutput:
        """Trivial compute that ignores inputs and returns a constant."""
        return IndicatorOutput(values={"fake": 0.0})


def test_indicator_protocol_runtime_checkable() -> None:
    """``Indicator`` is ``@runtime_checkable``: ``isinstance(fake,
    Indicator)`` returns ``True`` when the candidate exposes a
    callable ``compute`` method matching the Protocol signature.

    PEP 544 caveat (cross-referenced from
    ``trading_bot.indicators.protocols.Indicator`` docstring):
    ``@runtime_checkable`` does NOT verify the ``name: str`` data
    attribute at runtime — only callable methods.  A candidate with
    NO ``compute`` method would correctly return ``False``; a
    candidate with a ``compute`` but no ``name`` would INCORRECTLY
    return ``True`` at runtime.  mypy ``--strict`` catches the
    missing ``name`` statically.

    The ``FakeIndicator`` above declares both ``name`` and
    ``compute`` so mypy accepts it AND the runtime isinstance
    returns ``True`` — closing the spec DoD end-to-end.
    """
    fake = FakeIndicator()
    # Spec DoD line: must hold for any candidate that wires up
    # ``compute`` correctly.
    assert isinstance(fake, Indicator) is True
    # Defense-in-depth: assert the structural pieces are actually
    # wired so a future refactor cannot silently bypass the
    # ``@runtime_checkable`` semantics (e.g. someone moving
    # ``compute`` to a private name).
    assert callable(fake.compute)
    assert isinstance(fake.name, str)
    # End-to-end runtime sanity: compute() executes and returns a
    # valid ``IndicatorOutput`` (defense-in-depth against future
    # ``IndicatorOutput`` signature changes).
    result = fake.compute(ohlcv=[], params={})
    assert isinstance(result, IndicatorOutput)
