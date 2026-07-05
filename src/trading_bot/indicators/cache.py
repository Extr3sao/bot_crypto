"""Cache foundations for the indicators engine (TSK-200, F2 prelude + F3).

Per docs/specs/TSK-200-indicators-interface/03-specify.md section 5 and
05-tasks.md F2 row TSK-200.2.3 + F3 rows TSK-200.3.4..3.8.

The module ships two pieces:

- ``compute_params_hash`` (F2 / TSK-200.2.3) — the deterministic
  keying function used by the cache to bucket params.  See the
  round-2 commit message for the rationale on this function living
  here (spec section 5 places it next to ``IndicatorCache``; the
  test file is the standalone ``test_params_hash.py`` per F2 DoD).

- ``IndicatorCacheStats`` + ``IndicatorCache`` (F3 / TSK-200.3.4..3.8)
  — the LRU + threading-safe keyed-by-``(name, params_hash, ts)``
  cache.

The companion test files are
``tests/unit/indicators/test_params_hash.py`` (F2, 3 tests) and
``tests/unit/indicators/test_cache.py`` (F3, 8 tests).
"""

from __future__ import annotations

import json
import threading
from collections import OrderedDict
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from trading_bot.indicators.exceptions import ParamsHashError
from trading_bot.indicators.types import IndicatorOutput, IndicatorParams

__all__ = ["IndicatorCache", "IndicatorCacheStats", "compute_params_hash"]


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


# ---------------------------------------------------------------------------
# F3 IndicatorCache
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class IndicatorCacheStats:
    """Immutable snapshot of cache counters (F3 / TSK-200.3.6).

    Returned by ``IndicatorCache.stats()`` so observability callers
    read a consistent tuple of integers taken under the cache lock
    at invocation time.  ``__slots__`` are declared manually in the
    class body (not via ``slots=True``) to sidestep the bpo-46268
    synthetic-slots-base-class issue with ``frozen=True`` on
    CPython 3.10-3.11 — see ``IndicatorOutput`` in ``types.py`` for
    the same pattern.
    """

    __slots__ = ("evictions", "hits", "misses", "size")

    hits: int
    misses: int
    evictions: int
    size: int


class IndicatorCache:
    """LRU cache for ``compute()`` results, keyed by
    ``(name, params_hash, last_candle_ts)``.

    - Hit iff the 3 key components match (RF-5).
    - ``invalidate_on_new_candle(ts)`` purges entries with
      ``ts < new_ts`` (RF-6).
    - ``max_entries`` (default 256 per RNF-3) bounds the LRU; the
      least-recently-used entry is evicted when overflow occurs.
    - ``threading.Lock`` per-instance protects read/write (RNF-4);
      compute runs OUTSIDE the lock so concurrent readers do not
      block on slow indicators (CL-8).

    Per-instance only — no global mutable state (RNF-1 determinism).
    The orchestrator (Fase 4) holds 1 shared instance via DI.
    """

    def __init__(self, max_entries: int = 256) -> None:
        if max_entries <= 0:
            raise ValueError(f"max_entries must be > 0; got {max_entries}")
        self._cache: OrderedDict[tuple[str, int, int], IndicatorOutput] = OrderedDict()
        self._max = max_entries
        self._lock = threading.Lock()

        # Mutable counters protected by lock; observed via stats().
        self._hits = 0
        self._misses = 0
        self._evictions = 0

    @property
    def max_entries(self) -> int:
        """Maximum entries before LRU eviction kicks in."""
        return self._max

    def __len__(self) -> int:
        """Number of cached entries.  Snapshot — call ``stats()`` for
        a thread-safe counter view."""
        return len(self._cache)

    def get_or_compute(
        self,
        name: str,
        params: IndicatorParams,
        last_candle_ts: int,
        compute_fn: Callable[[], IndicatorOutput],
    ) -> IndicatorOutput:
        """Return cached value or compute + memoize.

        Args:
            name: indicator name (typically the registry ``.name``).
            params: indicator parameters — hashed via
                ``compute_params_hash(params)`` for cache keying.
            last_candle_ts: most-recent candle timestamp (int ms
                epoch).  Third cache key component; advances as new
                candles arrive and invalidates stale entries
                implicitly.
            compute_fn: zero-arg callable that produces the
                ``IndicatorOutput`` on miss.  Called OUTSIDE the
                cache lock to avoid blocking concurrent reads
                (CL-8).

        Returns:
            Cached or freshly-computed ``IndicatorOutput``.

        Locking discipline:
        - ``compute_fn()`` runs OUTSIDE the cache lock — concurrent
          readers do not wait while a slow indicator computes.
        - A **race-stick path** (spec section 5 + CL-8) handles the
          case where another thread inserted the same key while we
          were unlocked: ``move_to_end`` refreshes LRU order on
          the existing entry rather than overwriting it.  The
          second-winner's compute result is wasted but the cache
          never corrupts.
        - ``_evictions`` increments ONLY on actual ``popitem`` from
          a fresh insert (i.e. cache grew past ``_max``).  Race-stick
          paths do NOT increment ``_evictions`` because the cache
          size didn't grow.
        - ``_misses`` increments on every initial-miss path; the
          race-loser also counts as a miss because work was
          performed even if the result was later discarded (per
          Q2 think-with-files decision).
        """
        params_hash_value = compute_params_hash(params)
        key = (name, params_hash_value, last_candle_ts)

        with self._lock:
            if key in self._cache:
                self._hits += 1
                self._cache.move_to_end(key)  # LRU: most-recent first
                return self._cache[key]
            self._misses += 1

        # Compute OUTSIDE the lock (CL-8: don't serialize slow work).
        result = compute_fn()

        with self._lock:
            if key in self._cache:
                # Race-stick: another thread won while we were
                # unlocked.  Refresh LRU order on the existing entry
                # and return its result; do NOT overwrite.  The
                # ``result`` we just computed is discarded (wasted
                # compute, no corruption).
                self._cache.move_to_end(key)
                return self._cache[key]

            self._cache[key] = result
            if len(self._cache) > self._max:
                # FIFO pops the first (least-recently-used) entry.
                self._cache.popitem(last=False)
                self._evictions += 1
            return result

    def invalidate_on_new_candle(self, new_ts: int) -> int:
        """Purge entries whose ``last_candle_ts`` is strictly less
        than ``new_ts`` (RF-6).

        Returns the number of entries purged.  Purged entries'
        counter charge is implicit (the entry is gone); the
        cumulative hit/miss/eviction counters are NOT reset.
        """
        purged = 0
        with self._lock:
            keys_to_purge = [k for k in list(self._cache.keys()) if k[2] < new_ts]
            for k in keys_to_purge:
                del self._cache[k]
                purged += 1
        return purged

    def stats(self) -> IndicatorCacheStats:
        """Return a frozen snapshot of current counter state.

        Snapshot is consistent (all 4 fields taken under the same
        lock acquisition) so observability callers reading a tuple
        ``(hits, misses, evictions, size)`` see a single point-in-time
        view.
        """
        with self._lock:
            return IndicatorCacheStats(
                hits=self._hits,
                misses=self._misses,
                evictions=self._evictions,
                size=len(self._cache),
            )

    def clear(self) -> None:
        """Drop all entries.  Cumulative counters (hits, misses,
        evictions) are NOT reset — they reflect lifetime activity
        independent of current cache occupancy."""
        with self._lock:
            self._cache.clear()
