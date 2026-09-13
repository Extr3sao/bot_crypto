"""H6 V4 — the runtime entry point must resolve its data root explicitly, or fail loudly.

Defect this file pins: ``prepare_decision_from_data_root(data_root=...)`` passed its
argument straight to the causal reader, which returns NO rows for any directory that does
not itself contain ``<SYMBOL>/<SYMBOL>-oi-5m-*.jsonl``.  Passing the authority-documented
data root (``<repo>/data``, the value of ``TRADING_AGENTIC_DATA_ROOT``) therefore produced
a well-formed, plausible NO_TRADE decision computed from zero observations -- a silent
wrong-target result instead of an error.

No economics: these tests only exercise path resolution and the fail-closed boundary.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from trading_bot.research.h6.contracts import SignalDirection
from trading_bot.research.h6.feature_engine import CompletedHourPrice
from trading_bot.research.h6.preparation import prepare_decision_from_data_root
from trading_bot.research.oi_dataset_v2 import resolve_oi_v2_data_dir_from

SYMBOL = "BTCUSDT"
T0 = datetime(2024, 1, 1, 0, 0, tzinfo=timezone.utc)


def _write_store(repo_root: Path, hours: int = 1) -> Path:
    """Create a minimal store at ``<repo_root>/data/processed/oi_full_history_v2``."""
    store = repo_root / "data" / "processed" / "oi_full_history_v2" / SYMBOL
    store.mkdir(parents=True, exist_ok=True)
    rows = []
    for h in range(hours):
        for k in range(12):
            ts = int((T0 + timedelta(hours=h)).timestamp() * 1000) + k * 300_000
            rows.append(
                {
                    "timestamp_ms": ts,
                    "sum_open_interest": 1000.0 + h * 12.0 + k,
                    "sum_open_interest_value": (1000.0 + h * 12.0 + k) * 10.0,
                    "source_file": "synthetic",
                    "source_sha256": "0" * 64,
                    "unit_semantics": "synthetic",
                }
            )
    shard = store / f"{SYMBOL}-oi-5m-2024-01-01.jsonl"
    shard.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
    return store


def _price(at: datetime) -> CompletedHourPrice:
    return CompletedHourPrice(bucket_close_time=at, open=100.0, close=101.0)


def test_resolves_the_documented_data_root(tmp_path: Path) -> None:
    store = _write_store(tmp_path)
    assert resolve_oi_v2_data_dir_from(tmp_path / "data").resolve() == store.parent.resolve()


def test_resolves_the_store_directory_itself(tmp_path: Path) -> None:
    store = _write_store(tmp_path)
    assert resolve_oi_v2_data_dir_from(store.parent).resolve() == store.parent.resolve()


def test_resolves_a_repo_root(tmp_path: Path) -> None:
    store = _write_store(tmp_path)
    assert resolve_oi_v2_data_dir_from(tmp_path).resolve() == store.parent.resolve()


def test_unresolvable_root_raises_instead_of_returning_nothing(tmp_path: Path) -> None:
    bogus = tmp_path / "not-a-data-root"
    bogus.mkdir()
    with pytest.raises(FileNotFoundError):
        resolve_oi_v2_data_dir_from(bogus)


def test_entry_point_with_unresolvable_root_fails_loudly(tmp_path: Path) -> None:
    bogus = tmp_path / "not-a-data-root"
    bogus.mkdir()
    with pytest.raises(FileNotFoundError):
        prepare_decision_from_data_root(
            data_root=bogus, symbol=SYMBOL, decision_time=T0, price=_price(T0)
        )


def test_entry_point_rejects_a_store_without_shards_for_the_symbol(tmp_path: Path) -> None:
    _write_store(tmp_path)
    at = T0 + timedelta(hours=1)
    with pytest.raises(FileNotFoundError):
        prepare_decision_from_data_root(
            data_root=tmp_path, symbol="NOSUCHCOIN", decision_time=at, price=_price(at)
        )


def test_entry_point_accepts_both_root_shapes_identically(tmp_path: Path) -> None:
    store = _write_store(tmp_path, hours=12)
    at = T0 + timedelta(hours=1)
    from_data_root = prepare_decision_from_data_root(
        data_root=tmp_path / "data", symbol=SYMBOL, decision_time=at, price=_price(at)
    )
    from_store_dir = prepare_decision_from_data_root(
        data_root=store.parent, symbol=SYMBOL, decision_time=at, price=_price(at)
    )
    # 12 snapshots in hour 0 plus the boundary snapshot stamped exactly at `at`, which the
    # causal filter admits but the half-open completed-hour window excludes.
    assert from_data_root.observations_admitted == 13
    assert from_data_root.current_hour_oi.snapshot_count == 12
    assert from_data_root.feature_state.to_dict() == from_store_dir.feature_state.to_dict()
    assert from_data_root.signal.to_dict() == from_store_dir.signal.to_dict()
    # 12 observations cannot satisfy the frozen 336-observation minimum: ineligible, but
    # a real decision from real rows rather than a silent empty-store answer.
    assert from_data_root.feature_state.decision_eligible is False
    assert from_data_root.signal.direction == SignalDirection.NO_TRADE
