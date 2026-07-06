"""Tests for ``compute_params_hash`` (TSK-200.2.3).

Per docs/specs/TSK-200-indicators-interface/05-tasks.md F2 row
TSK-200.2.3.  Three tests cover the deterministic-key invariants the
indicator engine relies on for cache keying in F3:

- ``test_params_hash_invariant_to_key_order`` — bit-identical hash
  for permuted keys (RNF-5 cross-check; ``sort_keys=True`` is the
  implementation handle).
- ``test_params_hash_changes_when_value_changes`` — different values
  yield different hashes (anti-collision pin; covers both value-
  mutation and key-insertion paths).
- ``test_params_hash_rejects_non_serializable`` — unserializable
  values raise ``ParamsHashError`` (engine-class wrap of
  ``TypeError`` / ``ValueError`` per the existing
  ``ParamsHashError`` contract; verifies MRO and ``__cause__``
  chain preservation).

The companion implementation lives at
``src/trading_bot/indicators/cache.py``.
"""

from __future__ import annotations

import pytest

from trading_bot.indicators.cache import compute_params_hash
from trading_bot.indicators.exceptions import IndicatorError, ParamsHashError


def test_params_hash_invariant_to_key_order() -> None:
    """The hash is bit-identical when keys are permuted (RNF-5 DoD).

    Implementation handle: ``json.dumps(..., sort_keys=True)`` sorts
    keys alphabetically before serialization, so two mappings with
    equal key/value sets but different key order produce the same
    canonical string and therefore the same :func:`hash` result.

    Three permuted variants (2-key swap, 3-key rotation) are
    asserted to confirm the property holds beyond the binomial
    case — defense-in-depth against any future code path that
    accidentally copies the dict but skips the sort_keys step
    (e.g. ``canonical = str(dict(params))`` would lose the invariant).
    """
    two_key_a = compute_params_hash({"period": 9, "source": "close"})
    two_key_b = compute_params_hash({"source": "close", "period": 9})
    assert two_key_a == two_key_b
    # Cache-key contract: the return type is int (the second
    # component of the "(name, hash, ts)" LRU key tuple).
    assert isinstance(two_key_a, int)
    # Three-key rotation: still bit-identical.
    base_3 = compute_params_hash({"period": 9, "source": "close", "alpha": True})
    permuted_3 = compute_params_hash({"alpha": True, "period": 9, "source": "close"})
    assert base_3 == permuted_3


def test_params_hash_changes_when_value_changes() -> None:
    """Different values yield different hashes (anti-collision pin).

    Covers both the value-mutation path (Period 9 → Period 14) and
    the key-insertion path (Period 9 → Period 9 + source), so a
    future refactor that swaps the canonical form for an unstable
    one (e.g. drops ``sort_keys``, switches to ``str(repr(...))``
    on MutableMappings, picks an unstable encoder) is caught at
    L1 rather than at integration time in F3's cache test.

    Distinct types in the same slot (e.g. ``period: 9`` int vs
    ``period: 9.0`` float) intentionally yield different hashes
    even when semantically equivalent — JSON preserves the
    textual form, so ``"9"`` and ``"9.0"`` are distinct canonical
    strings.  This pins the literal-vs-coerced distinction so a
    future caller that mixes ints/floats cannot accidentally
    collide on a cache key.
    """
    base = compute_params_hash({"period": 9})
    # Value-mutation path.
    bump_period = compute_params_hash({"period": 14})
    assert base != bump_period
    # Key-insertion path.
    add_source = compute_params_hash({"period": 9, "source": "close"})
    assert base != add_source
    # int vs float in the same slot — different canonical forms.
    int_period = compute_params_hash({"period": 9})
    float_period = compute_params_hash({"period": 9.0})
    assert int_period != float_period


def test_params_hash_rejects_non_serializable() -> None:
    """Unserializable params raise ``ParamsHashError`` (CL-4 contract).

    The exception class lives in
    ``trading_bot.indicators.exceptions`` and inherits from
    ``IndicatorError(Exception)``.  The ``__cause__`` attribute on
    the chained exception preserves the original ``TypeError`` /
    ``ValueError`` raised by ``json.dumps`` / ``dict(params)`` so
    debugging is not lossy.

    Uses a custom class whose ``__str__`` raises ``TypeError`` —
    the only reliable trigger for the re-raise path under
    ``default=str``.  Plain primitives (functions, sets,
    ``Decimal``, ``complex`` numbers, etc.) all stringify cleanly
    via ``default=str``; only objects whose ``__str__`` actively
    raises propagate the failure.  Enumeration is intentionally
    non-exhaustive — the empirical claim is that ``str(value)``
    succeeds for every stdlib primitive, so a custom
    ``__str__`` raise is the practical trigger.
    """

    class Unserializable:
        def __str__(self) -> str:
            raise TypeError("marker: refuse to stringify")

        def __repr__(self) -> str:
            return "<Unserializable marker>"

    with pytest.raises(ParamsHashError) as exc_info:
        compute_params_hash({"bad": Unserializable()})

    # Engine-class contract: ``ParamsHashError`` inherits from
    # ``IndicatorError``, so a single ``except IndicatorError`` on
    # the engine side catches this.  Mirrors the MRO pine in
    # ``test_types.py::test_exceptions_inherit_indicator_error``.
    assert isinstance(exc_info.value, IndicatorError)

    # Root-cause preservation: ``__cause__`` carries the original
    # json.dumps / dict() error — never lost when the engine-class
    # wrap catches the failure.  Allows operators to trace back to
    # the exact failure mode without re-running the call.
    assert isinstance(exc_info.value.__cause__, (TypeError, ValueError))
