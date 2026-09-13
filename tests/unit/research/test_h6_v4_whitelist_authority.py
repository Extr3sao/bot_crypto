"""H6 V4 — feature-authority contract tests.

Covers checkpoint sections 10-14:

* forbidden values STORED == 0
* forbidden values RECOVERABLE == 0
* whitelist bypass paths == 0
* repr / str / logs / serialization safety (sentinel)
* the whitelist is reachable on the ACTUAL runtime data path
* a forbidden/unadmitted field injected into the real preparation path fails
  closed BEFORE any feature or signal exists

No economics.
"""

from __future__ import annotations

import copy
import json
import pickle
from datetime import datetime, timezone

import pytest

from trading_bot.research.h6.feature_authority import (
    AdmittedOIObservation,
    H6AuthorityBoundaryError,
    admitted_observation,
)
from trading_bot.research.h6.feature_engine import CompletedHourPrice
from trading_bot.research.h6.preparation import prepare_decision
from trading_bot.research.h6.runtime_authority import REPO_ROOT
from trading_bot.research.h6.whitelist import (
    FEATURE_INPUT_FIELDS,
    FORBIDDEN_H6_FIELDS,
    H6FieldAccess,
    H6ForbiddenFeatureAccess,
    H6ForbiddenRowRejected,
    H6UnadmittedField,
)

SENTINEL = "UNADMITTED_SENTINEL_123"
DECISION = datetime(2024, 6, 5, 12, 0, tzinfo=timezone.utc)


def dirty_row() -> dict:
    return {
        "sum_open_interest": 100.0,
        "sum_open_interest_value": 5000.0,
        "timestamp_ms": 1717588800000,
        "unit_semantics": "BASE_ASSET_UNITS",
        "source_file": "synthetic",
        "source_sha256": "0" * 64,
        "unadmitted_metric": 7,
        "some_future_provider_field": SENTINEL,
        "count_toptrader_long_short_ratio": 1.5,
        "sum_taker_long_short_vol_ratio": 2.5,
    }


# --------------------------------------------------------------------------- 11


@pytest.mark.parametrize(
    "probe",
    [
        lambda a: a["count_long_short_ratio"],
        lambda a: a.get("count_long_short_ratio"),
        lambda a: getattr(a, "count_long_short_ratio"),
        lambda a: "count_long_short_ratio" in a,
    ],
)
def test_forbidden_access_paths_raise(probe) -> None:
    acc = H6FieldAccess(dirty_row())
    with pytest.raises(H6ForbiddenFeatureAccess):
        probe(acc)


def test_no_forbidden_value_is_stored() -> None:
    """FORBIDDEN_VALUES_STORED == 0 — sanitized immutable state, not hiding."""
    acc = H6FieldAccess(dirty_row())
    stored = {
        k: v
        for k, v in dict(acc.to_dict()).items()
    }
    assert not (set(stored) & FORBIDDEN_H6_FIELDS)
    assert "unadmitted_metric" not in stored
    # The one and only internal attribute holds admitted keys only.
    internal = object.__getattribute__(acc, "_admitted")
    assert not (set(internal) & FORBIDDEN_H6_FIELDS)
    assert all(k in FEATURE_INPUT_FIELDS | {"timestamp_ms", "unit_semantics", "source_file", "source_sha256"}
               for k in internal)


@pytest.mark.parametrize(
    "attack",
    [
        lambda a: a.__dict__,
        lambda a: vars(a),
        lambda a: getattr(a, "data", "MISSING"),
        lambda a: getattr(a, "_data", "MISSING"),
        lambda a: object.__getattribute__(a, "data"),
        lambda a: dict(a),
        lambda a: json.dumps(a.to_dict()),
        lambda a: repr(a),
        lambda a: str(a),
        lambda a: repr(copy.copy(a)),
        lambda a: repr(copy.deepcopy(a)),
        lambda a: repr(pickle.loads(pickle.dumps(a))),
        lambda a: list(a.keys()),
        lambda a: [v for v in a.values()],
        lambda a: [i for i in a.items()],
    ],
)
def test_forbidden_values_are_not_recoverable(attack) -> None:
    """FORBIDDEN_VALUES_RECOVERABLE == 0 across every listed attack surface."""
    acc = H6FieldAccess(dirty_row())
    try:
        result = attack(acc)
    except (H6ForbiddenFeatureAccess, AttributeError, TypeError):
        # Refusing to answer at all is a fail-closed outcome.
        return
    rendered = repr(result)
    assert SENTINEL not in rendered
    assert "count_toptrader_long_short_ratio" not in rendered
    assert "sum_taker_long_short_vol_ratio" not in rendered
    assert "unadmitted_metric" not in rendered


def test_repr_and_str_never_render_values() -> None:
    """Section 12 — logs/traces are evidence surfaces, so repr is keys-only."""
    acc = H6FieldAccess(dirty_row())
    for text in (repr(acc), str(acc), repr(copy.copy(acc)), repr(pickle.loads(pickle.dumps(acc)))):
        assert SENTINEL not in text
        assert "100.0" not in text  # even admitted values are not rendered
        assert "sum_open_interest" in text  # key names only


def test_mapping_unpack_cannot_leak() -> None:
    acc = H6FieldAccess(dirty_row())
    assert dict(**acc.to_dict()) == acc.to_dict()
    assert set(acc.to_dict()) <= (
        FEATURE_INPUT_FIELDS | {"timestamp_ms", "unit_semantics", "source_file", "source_sha256"}
    )


def test_accessor_is_immutable() -> None:
    acc = H6FieldAccess(dirty_row())
    with pytest.raises(AttributeError):
        acc._admitted = {}  # type: ignore[misc]
    with pytest.raises(AttributeError):
        del acc._admitted  # type: ignore[misc]


# --------------------------------------------------------------------------- 13


def test_runtime_whitelist_is_reachable_on_the_real_path() -> None:
    """RUNTIME_WHITELIST_REACHABLE — the engine's boundary module is imported by the path."""
    import trading_bot.research.h6.preparation as prep

    assert prep.admitted_observation.__module__ == "trading_bot.research.h6.feature_authority"
    src = (REPO_ROOT / "src/trading_bot/research/h6/preparation.py").read_text(encoding="utf-8")
    assert "admitted_observation(" in src
    assert "admitted_causal_observations(" in src


def test_clean_row_prepares_a_decision() -> None:
    """Positive control: the boundary does not simply reject everything."""
    rows = [
        {
            "timestamp_ms": int((DECISION.timestamp() - (i * 300)) * 1000),
            "sum_open_interest": 1000.0 + i,
            "sum_open_interest_value": 50000.0 + i,
        }
        for i in range(1, 60)
    ]
    price = CompletedHourPrice(bucket_close_time=DECISION, open=100.0, close=101.0)
    prepared = prepare_decision(rows, symbol="BTCUSDT", decision_time=DECISION, price=price)
    assert prepared.observations_admitted == len(rows)
    assert prepared.current_hour_oi.snapshot_count <= 12
    assert prepared.authority_boundary.endswith("admitted_observation")


# --------------------------------------------------------------------------- 14


@pytest.mark.parametrize(
    "injected",
    [
        {"unadmitted_metric": 7},
        {"count_toptrader_long_short_ratio": 1.5},
        {"some_future_provider_field": SENTINEL},
        {"sum_taker_long_short_vol_ratio": 2.5},
    ],
)
def test_forbidden_injection_fails_closed_before_feature_or_signal(injected) -> None:
    """ACTUAL_FORBIDDEN_INJECTION = FAIL_CLOSED on the real preparation path."""
    rows = [
        {"timestamp_ms": int((DECISION.timestamp() - (i * 300)) * 1000), "sum_open_interest": 1000.0 + i}
        for i in range(1, 60)
    ]
    rows.append(
        {
            "timestamp_ms": int((DECISION.timestamp() - 300) * 1000),
            "sum_open_interest": 2000.0,
            **injected,
        }
    )
    price = CompletedHourPrice(bucket_close_time=DECISION, open=100.0, close=101.0)
    with pytest.raises(H6ForbiddenFeatureAccess):
        prepare_decision(rows, symbol="BTCUSDT", decision_time=DECISION, price=price)


def test_boundary_rejects_forbidden_and_unadmitted_separately() -> None:
    base = {"timestamp_ms": 1717588800000, "sum_open_interest": 1.0}
    with pytest.raises(H6ForbiddenRowRejected):
        admitted_observation({**base, "count_long_short_ratio": 9.9})
    with pytest.raises(H6UnadmittedField):
        admitted_observation({**base, "unadmitted_metric": 7})
    with pytest.raises(H6AuthorityBoundaryError):
        admitted_observation({"sum_open_interest": 1.0})  # missing timestamp_ms


def test_boundary_returns_typed_observation_not_a_dict() -> None:
    obs = admitted_observation(
        {"timestamp_ms": 1717588800000, "sum_open_interest": "12.5", "unit_semantics": "BASE_ASSET_UNITS"}
    )
    assert isinstance(obs, AdmittedOIObservation)
    assert isinstance(obs.sum_open_interest, float)
    assert obs.unit_semantics == "BASE_ASSET_UNITS"


def test_boundary_rejects_non_numeric_and_bool_payloads() -> None:
    base = {"timestamp_ms": 1717588800000}
    with pytest.raises(H6AuthorityBoundaryError):
        admitted_observation({**base, "sum_open_interest": "not-a-number"})
    with pytest.raises(H6AuthorityBoundaryError):
        admitted_observation({**base, "sum_open_interest": True})


def test_declared_whitelist_matches_enforced_sets() -> None:
    from trading_bot.research.h6.whitelist import H6_FEATURE_AUTHORITY_WHITELIST

    assert H6_FEATURE_AUTHORITY_WHITELIST["enforcement"]["bypass_paths_allowed"] == 0
    assert set(H6_FEATURE_AUTHORITY_WHITELIST["FORBIDDEN_FIELDS"]) == set(FORBIDDEN_H6_FIELDS)
