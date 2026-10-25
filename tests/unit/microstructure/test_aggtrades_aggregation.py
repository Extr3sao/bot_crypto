"""Tests for the aggTrades tick->minute aggregation (§PHASE 5).

These pin the two things that silently corrupt a microstructure backtest:
  * the SOURCE TIMESTAMP UNIT (Binance bulk aggTrades is in microseconds),
  * the PIT availability of a derived bar.
"""

from __future__ import annotations

import importlib.util
import io
import zipfile
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "scripts" / "fetch_aggtrades_microstructure.py"


def _load_module() -> Any:
    spec = importlib.util.spec_from_file_location("agg_fetch_under_test", SCRIPT)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


fetch = _load_module()


# --- timestamp units -------------------------------------------------------


def test_microseconds_are_detected_and_converted() -> None:
    # 2026-07-12T00:00:00Z in microseconds
    assert fetch._to_ms(1_783_814_400_000_000) == (1_783_814_400_000, "microseconds")


def test_milliseconds_are_left_alone() -> None:
    assert fetch._to_ms(1_783_814_400_000) == (1_783_814_400_000, "milliseconds")


def test_wrong_unit_would_fragment_buckets() -> None:
    """Regression guard for the 62k-rows-per-day bug."""
    us = 1_783_814_400_000_000
    ms, _ = fetch._to_ms(us)
    naive = (us // fetch.MINUTE_MS) * fetch.MINUTE_MS  # the buggy computation
    correct = (ms // fetch.MINUTE_MS) * fetch.MINUTE_MS
    assert naive != correct
    assert correct % fetch.MINUTE_MS == 0


# --- aggregation -----------------------------------------------------------


def _zip_with_csv(text: str) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("SYM-aggTrades-2026-07-12.csv", text)
    return buf.getvalue()


def test_bucketing_and_aggressor_signing() -> None:
    base_us = 1_783_814_400_000_000  # 2026-07-12T00:00:00Z in microseconds
    rows = [
        # aggId, price, qty, firstId, lastId, ts(us), isBuyerMaker, isBestMatch
        f"1,100.0,1.0,1,1,{base_us},false,true",  # buyer aggressor -> buy
        f"2,100.0,2.0,2,2,{base_us + 1_000},true,true",  # seller aggressor -> sell
        f"3,100.0,0.5,3,3,{base_us + 70_000_000},false,true",  # 70 s later -> next minute
    ]
    buckets, unit = fetch.aggregate_day(_zip_with_csv("\n".join(rows) + "\n"))
    assert unit == "microseconds"
    m0 = (base_us // 1000 // fetch.MINUTE_MS) * fetch.MINUTE_MS
    assert sorted(buckets) == [m0, m0 + fetch.MINUTE_MS]
    first = buckets[m0]
    assert first["n_trades"] == 2
    assert first["buy_vol"] == pytest.approx(1.0)
    assert first["sell_vol"] == pytest.approx(2.0)
    assert first["buy_count"] == 1 and first["sell_count"] == 1
    assert first["min_interarrival_ms"] == 1
    assert buckets[m0 + fetch.MINUTE_MS]["n_trades"] == 1


def test_large_trade_threshold_is_notional_based() -> None:
    base_us = 1_783_814_400_000_000
    rows = [
        f"1,100000.0,1.0,1,1,{base_us},false,true",  # 100k notional -> large
        f"2,100.0,1.0,2,2,{base_us + 1},true,true",  # small
    ]
    buckets, _ = fetch.aggregate_day(_zip_with_csv("\n".join(rows) + "\n"))
    b = next(iter(buckets.values()))
    assert b["large_buy_vol"] == pytest.approx(1.0)
    assert b["large_sell_vol"] == pytest.approx(0.0)


def test_header_row_is_skipped() -> None:
    text = (
        "aggTradeId,price,qty,firstTradeId,lastTradeId,timestamp,isBuyerMaker,isBestMatch\n"
        "1,100.0,1.0,1,1,1783814400000000,false,true\n"
    )
    buckets, _ = fetch.aggregate_day(_zip_with_csv(text))
    assert sum(b["n_trades"] for b in buckets.values()) == 1


def test_mixed_timestamp_units_fail_closed() -> None:
    text = (
        "1,100.0,1.0,1,1,1783814400000000,false,true\n"
        "2,100.0,1.0,2,2,1783814400000,false,true\n"
    )
    with pytest.raises(ValueError, match="mixed timestamp units"):
        fetch.aggregate_day(_zip_with_csv(text))


# --- PIT availability ------------------------------------------------------


def test_serialised_row_is_only_available_after_its_minute_closes() -> None:
    b = fetch._empty_bucket()
    b["n_trades"] = 1
    b["buy_vol"] = 1.0
    b["first_price"] = b["last_price"] = 100.0
    b["high"] = b["low"] = 100.0
    minute = 1_783_814_400_000
    row = fetch._serialise(minute, b)
    assert row["available_at"] == minute + fetch.MINUTE_MS + 1
    # a decision taken AT the minute open must not see this row
    assert row["available_at"] > minute


def test_bars_are_aligned_and_end_before_the_decision_clock() -> None:
    rows = []
    start = 1_783_814_400_000
    for k in range(10):
        b = fetch._empty_bucket()
        b["n_trades"] = 1
        b["buy_vol"] = 1.0
        b["buy_count"] = 1
        b["first_price"] = b["last_price"] = 100.0 + k
        b["high"] = b["low"] = 100.0 + k
        rows.append(fetch._serialise(start + k * fetch.MINUTE_MS, b))
    mod = _load_experiments()
    bars = mod._bars_from_minutes(rows, "2026-07-12")
    assert len(bars) == 2
    assert bars[0]["open_time"] == start
    assert bars[0]["last_price"] == pytest.approx(104.0)
    assert bars[1]["open_time"] == start + 5 * fetch.MINUTE_MS
    for bar in bars:
        assert bar["available_at"] > bar["open_time"]
        assert bar["available_at"] - bar["open_time"] == 5 * fetch.MINUTE_MS + 1


def _load_experiments() -> Any:
    spec = importlib.util.spec_from_file_location(
        "agg_experiments_under_test", ROOT / "scripts" / "aggtrades_experiments.py"
    )
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod
