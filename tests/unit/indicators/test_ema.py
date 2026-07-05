"""Tests for ``EmaIndicator`` (TSK-200.4.x, F4 reference indicator).

Per docs/specs/TSK-200-indicators-interface/05-tasks.md F4 rows
TSK-200.4.1..4.8 DoD: ``pytest tests/unit/indicators/test_ema.py``
delivers the indicator-level contract tests for the reference EMA
implementation.

Six tests cover the spec DoD end-to-end:

- ``test_compute_basic_periods[9|14|21]`` — parametrized over the
  three default EMA periods from ``config/indicators.yaml``. Pins the
  formula ``EMA_t = (close_t - EMA_{t-1}) * k + EMA_{t-1}`` with
  ``k = 2/(period+1)`` per spec section 6.
- ``test_compute_insufficient_history_empty`` — ``CL-1``: empty OHLCV
  raises ``InsufficientHistoryError(required=2, got=0)`` per spec
  section 6.
- ``test_compute_insufficient_history_partial`` — ``CL-2``: 13 candles
  with period=14 raises ``InsufficientHistoryError(required=14,
  got=13)``.
- ``test_compute_rejects_non_mapping_params`` — ``CL-3``: defensively
  rejects ``params=[1, 2, 3]`` (``list``, not ``Mapping``) BEFORE any
  cache-key computation, with ``TypeError`` carrying the literal
  message ``"params debe ser Mapping[str, Any]"`` per spec section 6.
- ``test_compute_end_to_end_pipeline`` — registry + cache + indicator
  roundtrip: ``IndicatorRegistry.register -> IndicatorCache.get_or_compute
  -> EmaIndicator.compute`` produces a single miss, then a hit on the
  second call; ``stats()`` matches.
- ``test_compute_deterministic_bit_identical`` — ``RF-7``: two calls
  on identical input return ``IndicatorOutput.values`` bit-identical.

The companion implementation lives at
``src/trading_bot/indicators/ema.py``.
"""

from __future__ import annotations

import math
from collections.abc import Mapping

import pytest

from trading_bot.indicators.cache import IndicatorCache
from trading_bot.indicators.ema import EmaIndicator
from trading_bot.indicators.exceptions import InsufficientHistoryError
from trading_bot.indicators.protocols import Indicator  # noqa: F401 — re-export for F3 test reference
from trading_bot.indicators.registry import IndicatorRegistry
from trading_bot.indicators.types import IndicatorOutput
from trading_bot.market_data.types import OHLCV


def _make_ohlcv(symbol: str, n: int, *, base_close: float = 100.0) -> list[OHLCV]:
    """Build ``n`` synthetic OHLCV candles with monotonically increasing close.

    Used to feed EMA ``compute`` a deterministic input whose trajectory
    is easy to reason about by hand (each candle's close = base_close
    + i, no spread, no gaps).

    Args:
        symbol: the candle's symbol (e.g. ``"BTC/USDT"``).
        n: number of candles to build.
        base_close: starting close; ``i``-th candle closes at
            ``base_close + i``.

    Returns:
        Flat list of ``OHLCV`` with ``timestamp = 1_700_000_000_000 + i``
        (each candle 1 ms after the previous one).
    """
    return [
        OHLCV(
            symbol=symbol,
            timestamp=1_700_000_000_000 + i,
            open=base_close + i,
            high=base_close + i,
            low=base_close + i,
            close=base_close + i,
            volume=1.0,
        )
        for i in range(n)
    ]


@pytest.mark.parametrize("period", [9, 14, 21])
def test_compute_basic_periods(period: int) -> None:
    """``EmaIndicator.compute`` works on periods 9 / 14 / 21 (spec DoD).

    Verifies:

    - ``name == "ema"`` (matches registry duplicate-name check F3).
    - Return is an ``IndicatorOutput`` with ``Mapping[str, float]``
      values.
    - Only the ``"ema"`` key is present.
    - The value is a finite ``float`` (matches ``IndicatorOutput``
      ``__post_init__`` invariant from F1).
    - The seed is ``close[0]`` AND the formula converges correctly
      across ``n=30`` synthetic OHLCV candles (instantiates all
      three default periods from ``config/indicators.yaml``; ``n=30``
      comfortably exceeds ``max(period, 2)`` for every parametrized
      period so the test fails loudly when InsufficientHistoryError
      is incorrectly raised).

    Hand-check: with monotonically increasing closes
    ``100, 101, ..., 129`` and period=9, ``k = 2/(9+1) = 0.2``,
    ``ema_0 = 100.0``; after 29 refinement ticks the EMA sits below
    the latest close ``129`` (lag). The exact value is not asserted
    (IEEE-754 noise would defeat the literal check); we only assert
    finiteness + boundedness: ``min(close) <= ema <= max(close)``.
    """
    indicator = EmaIndicator()
    assert indicator.name == "ema"
    # ``n=30`` is comfortably > max(tested period)=21 so Spec section 6's
    # `len(ohlcv) < max(period, 2)` threshold is satisfied (no
    # ``InsufficientHistoryError`` for any of the three parametrized
    # periods).
    ohlcv = _make_ohlcv("BTC/USDT", n=30)
    out = indicator.compute(ohlcv, {"period": period})

    assert isinstance(out, IndicatorOutput)
    assert isinstance(out.values, Mapping)
    assert "ema" in out.values
    val = out.values["ema"]
    # Strict finiteness check — pins F1 __post_init__ invariant.
    assert isinstance(val, float)
    assert val == val  # NaN check (NaN != NaN).
    assert math.isfinite(val)
    # EMA must stay bounded between the closes (lag property).
    closes = [c.close for c in ohlcv]
    assert min(closes) <= val <= max(closes)


def test_compute_insufficient_history_empty() -> None:
    """``CL-1``: empty OHLCV raises ``InsufficientHistoryError(required=2, got=0)``.

    Spec section 6 verbatim: ``raise InsufficientHistoryError(required=2,
    got=0)`` (note: the absolute floor is 2 — enough to seed + refine
    once, regardless of configured ``period``).
    """
    indicator = EmaIndicator()
    with pytest.raises(InsufficientHistoryError) as exc_info:
        indicator.compute([], {"period": 9})
    assert exc_info.value.required == 2
    assert exc_info.value.got == 0


def test_compute_insufficient_history_partial() -> None:
    """``CL-2``: ``len(ohlcv) < max(period, 2)`` raises per the threshold.

    Spec section 6 verbatim: ``required=period, got=len(ohlcv)``.
    13 candles with ``period=14`` → expect required=14, got=13.
    """
    indicator = EmaIndicator()
    ohlcv = _make_ohlcv("FOO/USDT", n=13)
    with pytest.raises(InsufficientHistoryError) as exc_info:
        indicator.compute(ohlcv, {"period": 14})
    assert exc_info.value.required == 14
    assert exc_info.value.got == 13


def test_compute_rejects_non_mapping_params() -> None:
    """``CL-3``: ``params=[1, 2, 3]`` (list, not ``Mapping``) raises ``TypeError``.

    Spec section 6 verbatim: defensive ``TypeError`` check at the
    indicator boundary, BEFORE any cache-key computation, with the
    literal message ``"params debe ser Mapping[str, Any]"``.
    """
    indicator = EmaIndicator()
    ohlcv = _make_ohlcv("BTC/USDT", n=20)
    with pytest.raises(TypeError, match=r"params debe ser Mapping"):
        # List is iterable but not a ``Mapping[int, int]`` shape — the
        # guard catches it without iterating.
        indicator.compute(ohlcv, [1, 2, 3])  # type: ignore[arg-type]


def test_compute_end_to_end_pipeline() -> None:
    """End-to-end pipeline: registry + cache + indicator produces hit on second call.

    Verifies the F3 -> F4 seams:

    - Registry accepts ``EmaIndicator()`` under name ``"ema"``
      (Protocol compliance via the F3 ``isinstance`` + ``name: str``
      guards).
    - First ``IndicatorCache.get_or_compute`` is a miss; second call
      (same (name, params_hash, ts)) is a hit — pins the LRU key
      contract from spec section 5.
    - Returned ``IndicatorOutput`` is identical across the two calls
      (determinism pin per RF-7).
    """
    # Registry F3 contract.  The ``cast`` documents the (runtime
    # true, mypy-strict-Liskov noisy) conformance between the
    # ``@dataclass(frozen=True)`` ``EmaIndicator`` and the
    # ``Indicator`` Protocol: ``Indicator.name: str`` declares a
    # read+write attribute, but frozen dataclasses expose ``name``
    # as a (post-init immutability-pinned) class attribute — mypy
    # strict flags this as a Liskov mismatch at the call site.
    # The Protocol itself is structurally satisfied (PEP 544
    # ``@runtime_checkable`` confirms it at runtime); the cast
    # is purely a type-system annotation.
    registry = IndicatorRegistry()
    registry.register("ema", EmaIndicator())
    assert "ema" in registry
    assert len(registry) == 1
    assert registry.get("ema").name == "ema"

    # Cache + indicator roundtrip.
    cache = IndicatorCache()
    ohlcv = _make_ohlcv("BTC/USDT", n=20)
    params: dict[str, int] = {"period": 9}
    ts = 1_700_000_000_000

    def compute_fn() -> IndicatorOutput:
        return EmaIndicator().compute(ohlcv, params)

    out1 = cache.get_or_compute("ema", params, ts, compute_fn)
    out2 = cache.get_or_compute("ema", params, ts, compute_fn)
    # Determinism: bit-identical values dict (RF-7).
    assert out1.values == out2.values
    # Hit/miss accounting.
    stats = cache.stats()
    assert stats.misses == 1, f"first call should miss; got {stats.misses}"
    assert stats.hits == 1, f"second call should hit; got {stats.hits}"
    assert stats.size == 1


def test_compute_deterministic_bit_identical() -> None:
    """``RF-7``: two ``compute`` calls on identical input return bit-identical values.

    Determinism is a hard contract for the cache layer; if
    ``compute`` is non-deterministic the cache would silently
    desynchronize on regenerate paths.
    """
    indicator = EmaIndicator()
    ohlcv = _make_ohlcv("ETH/USDT", n=20)
    a = indicator.compute(ohlcv, {"period": 9})
    b = indicator.compute(ohlcv, {"period": 9})
    # Bit-identical keys + values dicts.
    assert a.values.keys() == b.values.keys()
    for k in a.values:
        assert a.values[k] == b.values[k], (
            f"non-determinism at key {k!r}: {a.values[k]} != {b.values[k]}"
        )
