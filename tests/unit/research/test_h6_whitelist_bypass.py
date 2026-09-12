"""EXT-FEATURE-WHITELIST-001 — bypass matrix for H6FieldAccess fail-closed."""

from __future__ import annotations

import pytest

from trading_bot.research.h6.whitelist import H6FieldAccess, H6ForbiddenFeatureAccess


def _row_with_extra() -> dict:
    return {
        "sum_open_interest": 100.0,
        "sum_open_interest_value": 5000.0,
        "unadmitted_metric": 7,
        "count_toptrader_long_short_ratio": 1.5,
        "count_long_short_ratio": 0.9,
        "timestamp_ms": 123,
    }


def test_subscript_unadmitted_raises() -> None:
    row = _row_with_extra()
    acc = H6FieldAccess(row)
    with pytest.raises(H6ForbiddenFeatureAccess):
        _ = acc["unadmitted_metric"]


def test_get_unadmitted_raises() -> None:
    acc = H6FieldAccess(_row_with_extra())
    with pytest.raises(H6ForbiddenFeatureAccess):
        acc.get("unadmitted_metric")


def test_get_with_default_unadmitted_still_raises() -> None:
    acc = H6FieldAccess(_row_with_extra())
    with pytest.raises(H6ForbiddenFeatureAccess):
        acc.get("unadmitted_metric", 123)


def test_forbidden_ratio_via_get_raises() -> None:
    acc = H6FieldAccess(_row_with_extra())
    with pytest.raises(H6ForbiddenFeatureAccess):
        acc.get("count_toptrader_long_short_ratio")


def test_forbidden_ratio_via_subscript_raises() -> None:
    acc = H6FieldAccess(_row_with_extra())
    with pytest.raises(H6ForbiddenFeatureAccess):
        _ = acc["count_toptrader_long_short_ratio"]


def test_contains_unadmitted_raises_or_false() -> None:
    acc = H6FieldAccess(_row_with_extra())
    # Our implementation raises FIELD_NOT_ADMITTED for __contains__ on forbidden; that's fail-closed.
    # Accept either raise or False, but must not return True leaking it.
    try:
        result = "unadmitted_metric" in acc
    except H6ForbiddenFeatureAccess:
        return
    assert result is False, "unadmitted field must not appear as contained"


def test_iter_excludes_unadmitted() -> None:
    acc = H6FieldAccess(_row_with_extra())
    keys = list(acc)
    assert "unadmitted_metric" not in keys
    assert "count_toptrader_long_short_ratio" not in keys
    assert "sum_open_interest" in keys


def test_keys_excludes_unadmitted() -> None:
    acc = H6FieldAccess(_row_with_extra())
    assert "unadmitted_metric" not in acc.keys()
    assert "sum_open_interest" in acc.keys()


def test_values_items_exclude_unadmitted() -> None:
    acc = H6FieldAccess(_row_with_extra())
    vals = acc.values()
    items = acc.items()
    # 7 must not appear via values/items
    assert 7 not in vals
    assert ("unadmitted_metric", 7) not in items


def test_attribute_access_unadmitted_raises() -> None:
    acc = H6FieldAccess(_row_with_extra())
    with pytest.raises(H6ForbiddenFeatureAccess):
        _ = acc.unadmitted_metric  # type: ignore[attr-defined]


def test_attribute_forbidden_raises() -> None:
    acc = H6FieldAccess(_row_with_extra())
    with pytest.raises(H6ForbiddenFeatureAccess):
        _ = acc.count_toptrader_long_short_ratio  # type: ignore[attr-defined]


def test_allowed_field_access_succeeds() -> None:
    acc = H6FieldAccess(_row_with_extra())
    assert acc["sum_open_interest"] == 100.0
    assert acc.get("sum_open_interest") == 100.0
    assert acc.get("sum_open_interest_value") == 5000.0


def test_allowed_missing_returns_default_or_raises() -> None:
    # allowed field declared but not present in row: get returns default, [] raises KeyError
    acc = H6FieldAccess({"sum_open_interest": 1.0})
    assert acc.get("sum_open_interest_value", 999) == 999
    assert acc.get("sum_open_interest_value") is None
    with pytest.raises(KeyError):
        _ = acc["sum_open_interest_value"]


def test_len_counts_only_admitted() -> None:
    acc = H6FieldAccess(_row_with_extra())
    # admitted fields in row: sum_open_interest, sum_open_interest_value, timestamp_ms = 3
    assert len(acc) == 3


def test_allowed_keys_returns_frozenset() -> None:
    acc = H6FieldAccess({})
    ks = acc.allowed_keys()
    assert "sum_open_interest" in ks
    assert "unadmitted_metric" not in ks
