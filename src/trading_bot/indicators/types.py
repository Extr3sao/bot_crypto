"""Data types of the indicators engine (TSK-200, Fase 2).

Per docs/specs/TSK-200-indicators-interface/03-specify.md and
05-tasks.md F1 steps 1.2 - 1.3.

This module hosts the public types of the indicators package:

- ``IndicatorOutput``: the immutable result of an
  ``Indicator.compute(ohlcv, params)`` call.
- ``IndicatorParams``: the canonical type alias for ``compute``'s
  second argument.

The ``Indicator`` Protocol lives in
``src/trading_bot/indicators/protocols.py`` (TSK-200.2).
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

__all__ = ["IndicatorOutput", "IndicatorParams"]

# Public type alias for ``compute``'s second argument.  ``Mapping`` keeps
# callers free to pass plain ``dict``, ``MappingProxyType``, or any
# readonly view that satisfies the structural contract.
IndicatorParams = Mapping[str, Any]


@dataclass(frozen=True)
class IndicatorOutput:
    """Immutable output of one ``Indicator.compute(ohlcv, params)`` call.

    A single output is identified by its ``values`` mapping (e.g.,
    MACD returns ``{"fast": 1.2, "slow": 1.1}``; EMA returns
    ``{"ema": 50.0}``).  Keeping the payload as a free-form ``dict``
    accommodates multi-value indicators without changing the dataclass
    signature; finiteness and value-type validation land in TSK-200.1.3
    via ``__post_init__``.

    Note: ``__slots__`` is declared manually in the class body rather
    than via ``@dataclass(slots=True)``.  CPython 3.10-3.11 ships a
    known interaction between ``slots=True`` and ``frozen=True``
    (bpo-46268): the synthetic ``__slots__``-base class that
    ``slots=True`` inserts is not a proper supertype for the dataclass
    instance, so the frozen ``__setattr__`` override raises
    ``TypeError: super(type, obj)`` when triggered.  Declaring
    ``__slots__ = ("values",)`` in the class body sidesteps the bug
    while preserving both slot semantics (no ``__dict__`` on
    instances) and frozen immutability.
    """

    __slots__ = ("values",)

    values: dict[str, float]

    def __post_init__(self) -> None:
        """Validate the ``values`` payload at construction time.

        Rejects:
        - non-``float`` entries (``TypeError``): ``str``, ``int``,
          ``bool``, ``complex``, ``None``, etc.  ``isinstance(True,
          float)`` is ``False``, so booleans are correctly rejected
          even though ``True == 1``.
        - non-finite floats (``ValueError``): NaN, ``+inf``,
          ``-inf``.  ``math.isfinite`` covers all three in one check.

        Compose: int literals like ``1`` already fail the static
        ``dict[str, float]`` annotation under mypy strict; this
        ``__post_init__`` is the runtime defense-in-depth.
        """
        for key, value in self.values.items():
            if not isinstance(value, float):
                # Reject bool/int/str/complex/None/Decimal/etc.
                # isinstance(True, float) is False, so bools are caught.
                raise TypeError(
                    f"IndicatorOutput.values[{key!r}] must be float, got {type(value).__name__}"
                )
            if not math.isfinite(value):
                # math.isfinite is False for NaN, +inf, -inf in one check.
                raise ValueError(f"IndicatorOutput.values[{key!r}] must be finite, got {value}")
