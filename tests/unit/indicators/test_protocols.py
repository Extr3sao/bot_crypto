"""Tests for the ``Indicator`` Protocol contract (TSK-200.2.1 + TSK-200.2.2).

Per docs/specs/TSK-200-indicators-interface/05-tasks.md F2 rows:

- TSK-200.2.1 DoD: ``isinstance(fake, Indicator)`` -> ``True`` when
  the candidate exposes a callable ``compute`` method; ``mypy
  --strict`` detects the static structural contracts (``name: str`` +
  signature match for ``compute``).  ``@runtime_checkable`` allows
  the runtime isinstance check; data-attribute coverage (``name``)
  remains a mypy-strict responsibility per PEP 544.

- TSK-200.2.2 DoD: ``name: str`` is part of the Protocol contract
  and must be accessible via class-level introspection WITHOUT
  instantiation; pins the runtime side of the ``name`` contract
  (the half runtime ``isinstance`` cannot verify per PEP 544).

The spec-mapped tests verify both halves of the contract: the
runtime isinstance semantics AND the runtime surface of ``name``.
``FakeIndicator`` below mirrors the Protocol shape so mypy
accepts both tests without a suppression.  ``from __future__ import
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

    Note: this fake intentionally does NOT enforce the
    ``Indicator.compute`` contract that real implementations must
    follow — e.g. real indicators (see ``EmaIndicator`` in
    TSK-200.4.x) raise ``InsufficientHistoryError`` when ohlcv is
    too short, but the Protocol itself does not require that
    behavior.  The Protocol's runtime_contract is purely structural:
    methods exist with the right signature; semantic guarantees
    (e.g. raising on insufficient data) are policy decisions on top
    of the Protocol, not of the Protocol itself.
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


def test_indicator_protocol_attr_name() -> None:
    """``Indicator.name: str`` is part of the Protocol contract and
    must be accessible via class-level introspection WITHOUT
    instantiation.

    Per PEP 544: a Protocol declares structural members as
    class-level annotations OR methods.  ``Indicator.name: str`` is
    exposed as an annotated class member — concrete implementations
    must surface ``name`` as a class attribute (no ``__init__``
    invocation needed).  The ``sin instanciar mypy`` DoD phrasing
    pins this contract explicitly: no instantiation is required to
    access ``name`` on the candidate or on the Protocol class
    itself.

    Runtime caveat (PEP 544): ``@runtime_checkable`` does NOT
    verify ``name`` via ``isinstance`` — that was pinned in row .1
    (``test_indicator_protocol_runtime_checkable``).  This test
    verifies the EXPECTED runtime surface contract via direct
    class-level attribute lookup, complementing the static
    ``mypy --strict`` check.
    """
    # Class-level access on FakeIndicator (NO instance created).
    # This is what the DoD means by "sin instanciar mypy".
    assert FakeIndicator.name == "fake"
    # Type contract: must be ``str`` matching the Protocol annotation.
    assert isinstance(FakeIndicator.name, str)
    # Defense-in-depth: ``name`` is an ATTRIBUTE, NOT a callable
    # method.  Guards against a future refactor that turns the
    # Protocol attribute into a no-arg method
    # (e.g. ``def name(self) -> str: ...``), which would silently
    # desynchronize the contract from the registry duplicate-name
    # check in F3.
    assert not callable(FakeIndicator.name)
    # The Protocol class itself declares ``name`` in its annotations
    # (visible via ``__annotations__`` lookup, the canonical
    # Python-level mirror of the type-level Protocol declaration).
    # We do NOT need an instance of ``Indicator`` to verify the
    # declaration — the class itself advertises ``name: str``.
    # Direct ``__annotations__`` access is safe on Python 3.11+:
    # a Protocol declaring class-level annotations always has
    # ``__annotations__`` populated (PEP 563 + PEP 649 deferred-
    # evaluation don't break the lookup; values may be strings if
    # ``from __future__ import annotations`` is in effect).
    assert "name" in Indicator.__annotations__
