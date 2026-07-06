"""EMA reference implementation (TSK-200, F4 / TSK-200.4.x).

Per docs/specs/TSK-200-indicators-interface/03-specify.md section 6 and
05-tasks.md F4 rows TSK-200.4.1..4.4.

``EmaIndicator`` is the reference indicator shipped with TSK-200; the
remaining indicators (RSI / MACD / ATR / BB / VWAP / vol-relative /
spread / volatility / OB imbalance) enter the project as part of
TSK-201..TSK-203.  EMA is intentionally the simplest non-trivial
moving average so the contract surface (Protocol, frozen dataclass,
exception hierarchy, registry, cache) can be exercised end-to-end
without prematurely exposing RSI/MACD/etc. design tensions.

Spec-vs-impl note (F3 round-2 carry-over)
-----------------------------------------

``03-specify.md`` section 6 lists the EMA ``compute()`` return as
``IndicatorOutput(values={"ema": ema}, meta={"period": str(period)})``
with a ``Mapping[str, str]`` ``meta`` field.  However, the actual
``IndicatorOutput`` implementation in ``types.py`` (locked-in by
F1 + F1 round-2 review) has ONLY the ``values`` field; the aspirational
``meta`` field has not been added to the dataclass and would require
a separate ADR per CL-5 to introduce.  This module therefore returns
``IndicatorOutput(values={"ema": ema})`` (no meta) — the docstring of
the type itself (``src/trading_bot/indicators/types.py``) documents
the same drift per F3 round-2 reviewer feedback.  Any future ADR that
adds ``meta`` to ``IndicatorOutput`` will pick this implementation up
without further changes here.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from trading_bot.indicators.exceptions import InsufficientHistoryError
from trading_bot.indicators.types import IndicatorOutput, IndicatorParams
from trading_bot.market_data.types import OHLCV

__all__ = ["EmaIndicator"]


@dataclass(frozen=True)
class EmaIndicator:
    """EMA reference indicator (TSK-200 / TSK-201..203 slots).

    Why ``@dataclass(frozen=True)`` (no ``__slots__``): the RNF-6
    immutability contract per spec section 11 is enforced by
    ``frozen=True`` (the dataclass-installed ``__setattr__`` raises
    ``FrozenInstanceError`` on assignments).  Per F4 close-out
    thinker decision, manual ``__slots__`` is NOT used here because:

    1. ``@dataclass(slots=True)`` triggers bpo-46268 on CPython 3.10/3.11
       (the synthetic slots-base class is not a valid supertype).
    2. With ``__slots__`` declared MANUALLY in the class body,
       Python refuses combinations where a ``__slots__`` name is
       ALSO a class-level attribute with a default value (e.g.
       ``name: str = "ema"``) because ``__slots__`` creates a
       class-level descriptor that conflicts with the dataclass
       field default (``ValueError: 'name' in __slots__ conflicts
       with class variable``).
    3. ``EmaIndicator`` is a singleton-style class instantiated
       exactly ONCE per process (the orchestrator registers it at
       startup).  Slot-based ``__dict__`` avoidance is moot — we
       cannot amortize over millions of calls.

    Compare with ``IndicatorOutput`` (types.py) and
    ``IndicatorCacheStats`` (cache.py): both use manual __slots__
    because their fields are REQUIRED (no defaults), avoiding the
    class-attribute conflict and giving the LRU-key statistics
    dataclass slot semantics on a hot path.

    Attributes:
        name: stable identifier ``"ema"`` (matches string contract
            of the ``Indicator`` Protocol per F2 / spec section 3).
            Pinned hard-coded rather than via ``field(default=...)``
            because dataclasses' default-factory machinery on a
            ``str`` field adds runtime overhead for a pure-literal
            default with no behavioral difference.
    """

    name: str = "ema"

    def compute(
        self,
        ohlcv: list[OHLCV],
        params: IndicatorParams,
    ) -> IndicatorOutput:
        """Run one EMA pass over ``ohlcv`` with ``params``.

        Args:
            ohlcv: ordered list of OHLCV candles.  The seed
                (``EMA_0``) is ``float(ohlcv[0].close)`` per spec
                section 6; subsequent ticks apply
                ``EMA_t = (close_t - EMA_{t-1}) * k + EMA_{t-1}``
                with ``k = 2 / (period + 1)``.
            params: ``Mapping[str, Any]``; only the ``period`` key
                is consumed (default 9 per spec section 6 + the
                ``FAST``/``SLOW`` defaults in ``config/indicators.yaml``).

        Returns:
            ``IndicatorOutput`` with ``values={"ema": float}`` —
            finiteness guard lands in ``IndicatorOutput.__post_init__``
            (F1 round-1) so NaN/±inf from upstream data fail at
            construction time rather than at the registry/cache
            boundary.

        Raises:
            TypeError: if ``params`` is not a ``Mapping`` (CL-3
                defensive check at the indicator boundary, BEFORE
                any cache-key computation).
            InsufficientHistoryError:
                - ``required=2, got=0`` if ``ohlcv`` is empty
                  (per spec section 6 verbatim — minimum to seed
                  AND refine at least once).
                - ``required=period, got=len(ohlcv)`` if
                  ``len(ohlcv) < max(period, 2)`` for non-empty
                  but too-short input (CL-2 contract pinned in
                  BDD scenario ``Funcion con N velas <
                  param.min_period raise InsufficientHistoryError``).

        Formula derivation (kept brief; full version in spec section 6):

            k = 2.0 / (period + 1)
            ema_0 = float(ohlcv[0].close)        # seed
            ema_t = (close_t - ema_{t-1}) * k + ema_{t-1}    for t >= 1

        The choice of ``close[0]`` (rather than the SMA of the first
        ``period`` candles) is mandated verbatim by spec section 6:
        ``El indicador arranca con close[0] (semilla) y suaviza el
        resto``.
        """
        if not isinstance(params, Mapping):
            raise TypeError(f"params debe ser Mapping[str, Any]; got {type(params).__name__}")
        period = int(params.get("period", 9))
        if not ohlcv:
            # Spec verbatim: required=2 (the absolute floor to seed
            # + refine at least once), got=0.  Distinct from the
            # non-empty short case below (which uses the configured
            # ``period`` as the requirement).
            raise InsufficientHistoryError(required=2, got=0)
        if len(ohlcv) < max(period, 2):
            # Spec verbatim: required=period, got=len(ohlcv).
            raise InsufficientHistoryError(required=period, got=len(ohlcv))

        k = 2.0 / (period + 1)
        ema = float(ohlcv[0].close)  # seed per spec §6
        for candle in ohlcv[1:]:
            ema = (float(candle.close) - ema) * k + ema
        return IndicatorOutput(values={"ema": ema})
