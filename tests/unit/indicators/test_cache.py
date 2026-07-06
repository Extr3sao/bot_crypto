"""Tests for IndicatorCache + IndicatorCacheStats (TSK-200, F3 / TSK-200.3.4..3.8).

Per docs/specs/TSK-200-indicators-interface/05-tasks.md F3 rows
TSK-200.3.4 (hit/miss/LRU/lock), TSK-200.3.5 (invalidate_on_new_candle),
TSK-200.3.6 (frozen stats snapshot), TSK-200.3.7 (threading pool
without corruption), TSK-200.3.8 (race-stick post-compute).

Covers the full LRU + threading.Lock contract:

- Hit iff ``(name, params_hash, last_candle_ts)`` matches (RF-5).
- ``invalidate_on_new_candle(ts)`` purges entries with
  ``ts < new_ts`` (RF-6); entries with ``ts >= new_ts`` remain.
- ``max_entries`` (default 256 per RNF-3) bounds LRU; oldest entry
  evicted on overflow.
- ``threading.Lock`` per-instance protects read/write (RNF-4);
  compute runs OUTSIDE the lock so concurrent readers do not block
  on slow indicators (CL-8).
- Race-stick path: if another thread inserted the same key while we
  were unlocked, we discard our computed result and stick to the
  existing entry (CL-8 + spec section 5).
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from dataclasses import FrozenInstanceError

import pytest

from trading_bot.indicators.cache import (
    IndicatorCache,
    IndicatorCacheStats,
    compute_params_hash,
)
from trading_bot.indicators.types import IndicatorOutput

# ---------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------


def _val(v: float) -> IndicatorOutput:
    """Build a minimal valid IndicatorOutput (frozen+slots, finite floats).

    Note: per the actual ``IndicatorOutput`` dataclass
    (``src/trading_bot/indicators/types.py``), the only public field
    is ``values: dict[str, float]``; spec section 2 aspirationally
    documented a ``meta: dict[str, str]`` field that has not been
    added to the implementation yet (would require an ADR per CL-5).
    Tests use only factory functions on existing field shape.
    """
    return IndicatorOutput(values={"ema": v})


def _make_compute(value: float, counter: list[int] | None = None) -> Callable[[], IndicatorOutput]:
    """Return a zero-arg callable that produces an IndicatorOutput and
    optionally records call counts in ``counter`` for assertion.

    The callable closes over ``counter`` so multiple threads appending
    to the same list is safe (Python list append is atomic at the
    bytecode level — GIL-protected)."""

    def _compute() -> IndicatorOutput:
        if counter is not None:
            counter.append(1)
        return _val(value)

    return _compute


# ---------------------------------------------------------------------
# TSK-200.3.4 — get_or_compute hit/miss/LRU/lock + max_entries default
# ---------------------------------------------------------------------


def test_cache_hit_returns_memoized_without_calling_compute() -> None:
    """Hit path: compute_fn is NOT called on the 2nd get_or_compute; the
    cached value is returned verbatim."""
    cache = IndicatorCache(max_entries=4)
    compute_calls: list[int] = []

    out1 = cache.get_or_compute("rsi", {"period": 9}, 1000, _make_compute(0.5, compute_calls))
    assert out1.values["ema"] == 0.5
    assert compute_calls == [1]

    # Same key — cache hit, compute_fn must NOT be called.
    out2 = cache.get_or_compute("rsi", {"period": 9}, 1000, _make_compute(0.99, compute_calls))
    assert out2 is out1  # identity check: same IndicatorOutput instance
    assert compute_calls == [1]  # counter unchanged

    stats = cache.stats()
    assert stats.hits == 1
    assert stats.misses == 1


def test_cache_miss_computes_once_for_same_key() -> None:
    """A MISS returns the freshly-computed value; cache is sized to 1
    entry after the first miss."""
    cache = IndicatorCache(max_entries=4)
    compute_calls: list[int] = []

    out = cache.get_or_compute("rsi", {"period": 9}, 1000, _make_compute(0.42, compute_calls))
    assert out.values["ema"] == 0.42
    assert compute_calls == [1]
    assert len(cache) == 1


@pytest.mark.parametrize(
    "max_entries",
    [1, 2, 4, 256],
)
def test_cache_lru_eviction_drops_oldest_entry_on_overflow(max_entries: int) -> None:
    """When insert count > max_entries, the least-recently-used entry is
    evicted (FIFO-ish by insertion + move_to_end semantics).  Final
    stats show ``evictions == total inserts - max_entries`` for fills
    that exceed capacity."""
    cache = IndicatorCache(max_entries=max_entries)
    compute_calls: list[int] = []

    # Fill cache with max_entries distinct keys (varying ``last_candle_ts``
    # so each one creates its own cache row).
    for i in range(max_entries):
        cache.get_or_compute(
            "rsi",
            {"period": i + 1},  # distinct params -> distinct params_hash
            1000 + i,  # distinct ts
            _make_compute(0.1 * i, compute_calls),
        )
    assert len(cache) == max_entries
    assert cache.stats().evictions == 0

    overflow_ts = max_entries + 999  # distinct from all prior ts
    cache.get_or_compute(
        "rsi",
        {"period": overflow_ts},  # new params -> new hash
        overflow_ts,
        _make_compute(99.9, compute_calls),
    )

    assert len(cache) == max_entries
    assert cache.stats().evictions == 1

    # The FIRST entry (period=1, ts=1000) is now evicted.
    # Re-issuing that key must miss.
    compute_calls.clear()
    cache.get_or_compute(
        "rsi",
        {"period": 1},
        1000,
        _make_compute(0.1, compute_calls),
    )
    assert compute_calls == [1]  # re-computed; was evicted


def test_cache_max_entries_default_256() -> None:
    """``IndicatorCache()`` with no args uses max_entries=256 per RNF-3."""
    cache = IndicatorCache()
    assert cache.max_entries == 256


def test_cache_max_entries_zero_or_negative_raises() -> None:
    """Defensive: zero or negative max_entries is a programmer error."""
    with pytest.raises(ValueError, match="max_entries"):
        IndicatorCache(max_entries=0)
    with pytest.raises(ValueError, match="max_entries"):
        IndicatorCache(max_entries=-1)


# ---------------------------------------------------------------------
# TSK-200.3.5 — invalidate_on_new_candle purges ``ts < new_ts``
# ---------------------------------------------------------------------


def test_invalidate_on_new_candle_purges_entries_with_older_ts() -> None:
    """Entries whose ``last_candle_ts`` is strictly less than ``new_ts``
    are purged; the entry at ``new_ts`` itself remains (RF-6 strict-<)."""
    cache = IndicatorCache(max_entries=8)
    cache.get_or_compute("ema", {"period": 9}, 1000, _make_compute(0.1))
    cache.get_or_compute("ema", {"period": 9}, 2000, _make_compute(0.2))
    cache.get_or_compute("ema", {"period": 9}, 3000, _make_compute(0.3))
    assert len(cache) == 3

    purged = cache.invalidate_on_new_candle(2500)
    assert purged == 2
    assert len(cache) == 1

    # The surviving entry is the one at ts=3000 (>= 2500).
    surviving_key = next(iter(cache._cache.keys()))
    assert surviving_key[2] == 3000


def test_invalidate_returns_count_purged() -> None:
    """Return value is the number of purged entries; the count equals
    len(before) - len(after).  Zero when no entry has ``ts < new_ts``."""
    cache = IndicatorCache(max_entries=4)
    cache.get_or_compute("ema", {"period": 9}, 5000, _make_compute(0.5))
    assert cache.invalidate_on_new_candle(1000) == 0
    assert cache.invalidate_on_new_candle(5000) == 0  # strict-< boundary
    assert cache.invalidate_on_new_candle(6000) == 1
    assert len(cache) == 0


# ---------------------------------------------------------------------
# TSK-200.3.6 — stats() returns a frozen IndicatorCacheStats snapshot
# ---------------------------------------------------------------------


def test_stats_returns_frozen_snapshot() -> None:
    """``stats()`` returns a frozen dataclass instance; mutation raises
    FrozenInstanceError (RNF-6 + IndicatorOutput mirror contract)."""
    cache = IndicatorCache(max_entries=4)
    cache.get_or_compute("ema", {"period": 9}, 1000, _make_compute(0.5))
    snapshot = cache.stats()

    assert isinstance(snapshot, IndicatorCacheStats)
    assert snapshot.hits == 0
    assert snapshot.misses == 1
    assert snapshot.evictions == 0
    assert snapshot.size == 1  # ``FrozenInstanceError`` is a strict subclass of ``AttributeError``,
    # but matching by exception class (not by message regex) is version-
    # stable across CPython releases.  CPython 3.10+ emits
    # ``cannot assign to field "X"``; earlier versions emit
    # ``can't set attribute`` — exception-class matching sidesteps both
    # message-format skews.  Pin to ``FrozenInstanceError`` (not just
    # ``AttributeError``) so an unrelated ``AttributeError`` from inside
    # ``cache.stats()`` would fail the assertion.
    with pytest.raises(FrozenInstanceError):
        snapshot.hits = 999  # type: ignore[misc]


def test_stats_size_matches_actual_cache_size() -> None:
    """stats().size equals len(cache) at snapshot time."""
    cache = IndicatorCache(max_entries=4)
    for i in range(3):
        cache.get_or_compute("ema", {"period": i + 1}, 1000 + i, _make_compute(0.1 * i))
    assert cache.stats().size == len(cache) == 3


def test_stats_evictions_increments_only_on_overflow_insert() -> None:
    """Each LRU overflow (insert past max_entries) increments evictions
    by 1.  Race-stick paths do NOT increment evictions (cache size
    didn't grow)."""
    cache = IndicatorCache(max_entries=2)
    cache.get_or_compute("ema", {"period": 1}, 1000, _make_compute(0.1))
    cache.get_or_compute("ema", {"period": 2}, 2000, _make_compute(0.2))
    assert cache.stats().evictions == 0
    cache.get_or_compute("ema", {"period": 3}, 3000, _make_compute(0.3))
    assert cache.stats().evictions == 1
    cache.get_or_compute("ema", {"period": 4}, 4000, _make_compute(0.4))
    assert cache.stats().evictions == 2


# ---------------------------------------------------------------------
# TSK-200.3.7 — Threading pool without corruption (race-aware assertions)
# ---------------------------------------------------------------------


def test_cache_thread_safe_no_corruption_with_pool_of_readers() -> None:
    """8 concurrent threads hitting the SAME key produce a consistent
    cache state.  Per think-with-files Q1/Q2: under CPython's GIL,
    the lock acquisition prevents all 8 threads from observing an empty
    cache in the first miss-check; typically the first thread that
    acquires the lock completes its full cycle (miss + compute + insert)
    before the GIL switches and the second thread enters the lock.
    So the stable outcome is ``misses >= 1`` and ``misses + hits ==
    n_threads``.  Validates that the cache remains consistent across
    any thread interleaving — no lost entries, no spurious hits/misses,
    no exceptions."""
    cache = IndicatorCache(max_entries=4)
    compute_calls: list[int] = []

    n_threads = 8
    barrier = threading.Barrier(n_threads)  # simultaneously released
    errors: list[Exception] = []

    def worker() -> None:
        try:
            barrier.wait(timeout=5)
            cache.get_or_compute(
                "rsi",
                {"period": 9},
                1000,
                _make_compute(0.42, compute_calls),
            )
        except Exception as exc:
            errors.append(exc)

    threads = [threading.Thread(target=worker) for _ in range(n_threads)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=10)

    assert errors == []  # no thread raised
    assert len(cache) == 1

    stats = cache.stats()
    # At least one thread took the initial-miss path (the first to win
    # the lock race); all other threads either hit the freshly-inserted
    # entry or stuck to it via the race-stick path.
    assert stats.misses >= 1
    # Every ``get_or_compute`` call was accounted for as either a hit or
    # a miss; no thread "disappeared" without being charged.
    assert stats.misses + stats.hits == n_threads
    assert stats.size == 1
    # compute_fn count equals misses (each miss computes exactly once).
    assert len(compute_calls) == stats.misses
    # No spurious evictions: cache never grew past max_entries.
    assert stats.evictions == 0


def test_cache_thread_safe_concurrent_distinct_keys() -> None:
    """8 concurrent threads with DISTINCT keys (different params +
    timestamps) hammer the cache.  Each thread independently misses
    its own key, so all 8 must miss+compute and the cache must hold
    all 8 entries.  Validates that concurrent distinct inserts
    don't lose entries due to lock mis-ordering.

    Per think-with-files Q3/Q4 (option (b)): aims at the
    insert-then-move_to_end path which is exercised concurrently
    WITHOUT the race-stick short-circuit (every key is unique)."""
    cache = IndicatorCache(max_entries=16)  # bigger than n_threads
    compute_calls: list[int] = []

    n_threads = 8
    barrier = threading.Barrier(n_threads)
    errors: list[Exception] = []

    def worker(thread_id: int) -> None:
        try:
            barrier.wait(timeout=5)
            cache.get_or_compute(
                f"rsi_{thread_id}",
                {"period": 9 + thread_id},
                1000 + thread_id,
                _make_compute(thread_id * 0.1, compute_calls),
            )
        except Exception as exc:
            errors.append(exc)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(n_threads)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=10)

    assert errors == []
    assert len(cache) == n_threads

    stats = cache.stats()
    # Each thread misses its distinct key exactly once.
    assert stats.misses == n_threads
    assert stats.hits == 0  # no shared keys -> no overlap hits
    assert stats.size == n_threads
    # Every thread's compute_fn ran (no wasted compute).
    assert len(compute_calls) == n_threads


# ---------------------------------------------------------------------
# TSK-200.3.8 — Race-stick post-compute sticks to existing entry
# ---------------------------------------------------------------------


def test_cache_post_compute_race_sticks_to_existing_entry() -> None:
    """When thread A enters get_or_compute and computes, but thread B
    inserts the same key first (race window between A's miss-check and
    A's insert), thread A's race-stick path returns B's value (sticking
    to the existing entry) — NOT overwriting with A's computed result.

    Coordination:
    1. Thread A enters ``get_or_compute``; its ``compute_fn_a`` sets
       ``a_in_compute`` event then blocks on ``b_done``.
    2. Main thread waits for ``a_in_compute``; then runs thread B's
       ``get_or_compute`` synchronously (B inserts and returns).
    3. Main thread sets ``b_done``; thread A's compute_fn_a returns.
    4. Thread A re-acquires lock, sees the race-stick, returns B's value.

    The assertion verifies A gets B's value (stick behaviour) and the
    cached entry is B's instance, not A's.
    """
    cache = IndicatorCache(max_entries=4)

    a_in_compute = threading.Event()
    b_done = threading.Event()

    # Two distinct IndicatorOutput instances so identity check is meaningful.
    result_a = _val(0.1)
    result_b = _val(0.9)

    def compute_fn_a() -> IndicatorOutput:
        a_in_compute.set()  # signal: thread A is now computing
        b_done.wait(timeout=5)
        return result_a

    def compute_fn_b() -> IndicatorOutput:
        return result_b

    a_outcome: list[IndicatorOutput] = []

    def run_a() -> None:
        a_outcome.append(cache.get_or_compute("rsi", {"period": 9}, 1000, compute_fn_a))

    thread_a = threading.Thread(target=run_a)
    thread_a.start()

    # Wait until thread A is inside compute_fn_a (waiting for b_done).
    assert a_in_compute.wait(timeout=5)

    # Run thread B's path synchronously: it acquires miss, releases lock,
    # calls compute_fn_b (returns immediately), re-acquires lock, inserts result_b.
    out_b = cache.get_or_compute("rsi", {"period": 9}, 1000, compute_fn_b)
    assert out_b is result_b

    # Release thread A so it can re-acquire the lock and race-stick.
    b_done.set()
    thread_a.join(timeout=10)

    assert len(a_outcome) == 1
    assert a_outcome[0] is result_b  # A stuck to B's value, didn't overwrite

    # And the cache entry is B's value (NOT A's).
    assert len(cache) == 1
    cached_value = next(iter(cache._cache.values()))
    assert cached_value is result_b

    stats = cache.stats()
    # Both threads entered the initial-miss path (initial check).
    assert stats.misses == 2
    # No eviction: cache did not grow past max_entries.
    assert stats.evictions == 0


# ---------------------------------------------------------------------
# Sanity: compute_params_hash is exposed at module level (F2 prelude)
# ---------------------------------------------------------------------


def test_compute_params_hash_is_module_public() -> None:
    """``compute_params_hash`` is the cache-key builder — re-exported from
    ``indicators.cache``; the F3 cache depends on it.  Smoke test: hashing
    the same params twice returns the same int."""
    h1 = compute_params_hash({"period": 9})
    h2 = compute_params_hash({"period": 9})
    assert h1 == h2
    assert isinstance(h1, int)
