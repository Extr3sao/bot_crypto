"""Public Protocol contract for the indicators engine (TSK-200, Fase 2).

Per docs/specs/TSK-200-indicators-interface/03-specify.md section 3.
Hosts the structural ``Indicator`` Protocol — duck-typing contract
that every indicator implementation must satisfy without inheriting
from a shared base class.  ADR-0013-Fase2 documents the
structural-typing choice.  See the :class:`Indicator` docstring for
the PEP 544 ``@runtime_checkable`` attribute-checking caveat.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from trading_bot.indicators.types import IndicatorOutput, IndicatorParams
from trading_bot.market_data.types import OHLCV


@runtime_checkable
class Indicator(Protocol):
    """Structural contract for any technical indicator implementation.

    Why Protocol (structural) vs ABC (nominal):
    - Implementations live in their own modules (``ema.py`` for F4,
      future TSK-201..203 for RSI/MACD/etc.) and we want zero coupling
      between them and the registry/cache.
    - A class is treated as an ``Indicator`` iff it exposes ``.name``
      and a ``.compute(...)`` method with matching signatures, no
      explicit ``is-a`` relation required.

    Why ``@runtime_checkable``:
    - Lets tests (``tests/unit/indicators/test_protocols.py``) and
      the F3 ``IndicatorRegistry`` do cheap ``isinstance(obj,
      Indicator)`` checks WITHOUT importing concrete indicator
      classes — useful for plugin-style loading from
      ``IndicatorsConfig.indicators`` at app boot.

    PEP 544 caveat: ``@runtime_checkable`` does **NOT** verify data
    attributes such as ``name: str`` at runtime — it only checks
    callable method presence.  ``isinstance(obj, Indicator)`` returns
    ``True`` for any object exposing a callable ``compute``,
    regardless of whether it declares ``name``.  The ``name: str``
    contract is enforced statically by ``mypy --strict`` (and at
    runtime by the F3 registry's duplicate-name check).

    Implementations MUST:
    - Expose ``.name: str`` (unique within the F3
      ``IndicatorRegistry``).
    - Expose ``.compute(ohlcv, params) -> IndicatorOutput`` as a
      callable method.  Verified by the ``@runtime_checkable``
      isinstance check (F2 step 2.1 DoD).
    """

    name: str

    def compute(
        self,
        ohlcv: list[OHLCV],
        params: IndicatorParams,
    ) -> IndicatorOutput:
        """Run one ``compute`` pass over ``ohlcv`` with ``params``.

        Args:
            ohlcv: ordered list of OHLCV candles.  Implementations
                must raise ``InsufficientHistoryError`` (from
                ``trading_bot.indicators.exceptions``) when
                ``len(ohlcv)`` is below the indicator's minimum
                requirement rather than returning a partial value.
            params: ``Mapping[str, Any]`` of indicator-specific
                parameters (e.g. ``{"period": 9}`` for an EMA).

        Returns:
            ``IndicatorOutput`` with finite float ``values`` —
            NaN/±inf and non-float are rejected at construction
            (``IndicatorOutput.__post_init__``, see ``types.py``).
        """
        ...


__all__ = ["Indicator"]
