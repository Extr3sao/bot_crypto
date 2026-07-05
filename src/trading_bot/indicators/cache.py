"""Cache foundations for the indicators engine (TSK-200, F2 prelude to F3).

Per docs/specs/TSK-200-indicators-interface/03-specify.md section 5 and
05-tasks.md F2 row TSK-200.2.3.

The full ``IndicatorCache`` class lands under TSK-200.3.4 (F3).  This
F2 commit ships only ``compute_params_hash`` — the deterministic
keying function that the cache's LRU buckets will hash against — so
the cache contract can be regressed independently from the registry
class in F3 and the EMA implementation in F4.

Why ``compute_params_hash`` lives in ``cache.py`` and NOT in a
standalone ``params_hash`` module:

- Spec section 5 puts the function next to ``IndicatorCache``; the
  test file is the standalone ``test_params_hash.py`` per F2 DoD.
- Forward-compatibility: F3 will extend this file with
  ``IndicatorCache`` (LRU 256 + ``threading.Lock`` per RNF-3 / RNF-4)
  and re-use ``compute_params_hash`` for keying without an added
  import chain.

The companion test file lives at
``tests/unit/indicators/test_params_hash.py``.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

from trading_bot.indicators.exceptions import ParamsHashError

__all__ = ["compute_params_hash"]


def compute_params_hash(params: Mapping[str, Any]) -> int:
    """Deterministic hash of indicator ``params`` (RNF-5).

    Uses ``json.dumps(dict(params), sort_keys=True, default=str)`` to
    obtain a canonical string representation that is invariant to
    the original key order, then feeds it through Python's built-in
    :func:`hash`.  The integer result serves as the second component
    of the cache key ``(name, params_hash, last_candle_ts)`` in the
    F3 ``IndicatorCache``.

    Args:
        params: ``Mapping[str, Any]`` of indicator-specific parameters
            (e.g. ``{"period": 9}`` for an EMA).  Accepts ``dict``,
            ``MappingProxyType``, or any read-only view that satisfies
            the structural ``Mapping`` contract.

    Returns:
        An integer hash of the canonical JSON string.  Deterministic
        within a single Python process (PYTHONHASHSEED is stable for
        the lifetime of the interpreter).  NOT portable across
        processes because CPython's built-in :func:`hash` is seeded
        with ``PYTHONHASHSEED``; if a future cache migration needs
        cross-process key persistence, this call site must move to
        ``hashlib.sha256`` (track in ADR-0013-Fase2).

    Raises:
        ParamsHashError: If ``params`` cannot be coerced to JSON.
            Two distinct failure modes, both wrapped and chained via
            ``__cause__`` so the original subclass is preserved:

            - ``ValueError`` — raised when ``dict(params)`` chokes on
              a wrongly-shaped iterable (e.g. ``dict("abc")`` raises
              ``ValueError: dictionary update sequence element #0
              has length 1; 2 is required``). Covers non-Mapping
              inputs whose iteration yields 1-tuples instead of
              2-tuples.
            - ``TypeError`` — raised when ``json.dumps(..., default=str)``
              cannot find a stringifiable representation for a value
              (e.g. an object whose ``__str__`` actively raises). The
              ``default=str`` callback falls through to ``str(value)``
              for values json doesn't natively serialize; if that
              raises, the engine-class wrap catches it.
    """
    try:
        canonical = json.dumps(dict(params), sort_keys=True, default=str)
    except (TypeError, ValueError) as exc:
        # Engine-class wrap: per ``trading_bot.indicators.exceptions``
        # contract, ``ParamsHashError`` inherits from ``IndicatorError``
        # so a single ``except IndicatorError`` on the engine side
        # picks this up.  ``from exc`` preserves the stdlib cause in
        # ``__cause__`` so the original ``TypeError`` is not lost.
        raise ParamsHashError(f"compute_params_hash: params not JSON-serializable: {exc}") from exc
    return hash(canonical)
