"""Track N tests for ALPHA-DATA-ADMISSION-01: contracts, quality, PIT, fingerprints.

Covers: data-contract semantics, normalization, PIT cutoff, future-mutation
safety, fingerprint stability/sensitivity, corrupt-file, missing-file,
duplicate-record, schema-change and provider-failure handling.
"""

from __future__ import annotations

import zipfile
from pathlib import Path

import pytest

from trading_bot.research.data_contracts import (
    OPEN_INTEREST_EXPECTED_INTERVAL_MS,
    OPEN_INTEREST_NATIVE_PERIOD,
    OPEN_INTEREST_ROWS_PER_COMPLETE_UTC_DAY,
    SCHEMA_VERSION,
    OpenInterestRecord,
    TakerSide,
    TradeFlowRecord,
    taker_side_from_buyer_is_maker,
)
from trading_bot.research.data_quality import (
    NORMALIZER_VERSION,
    dataset_fingerprint,
    enforce_pit_cutoff,
    fingerprint_open_interest,
    fingerprint_trade_flow,
    normalize_open_interest,
    normalize_trade_flow,
)
from trading_bot.research.source_readers import (
    read_agg_trades_zip,
    read_metrics_zip,
    verify_official_checksum,
)


def _tf(agg_id: int, t_ms: int, *, price: float = 100.0, qty: float = 1.0, buyer_maker: bool = False) -> TradeFlowRecord:
    return TradeFlowRecord(
        exchange="binance",
        market="usdm_futures",
        symbol="BTCUSDT",
        agg_trade_id=agg_id,
        price=price,
        quantity=qty,
        first_trade_id=agg_id,
        last_trade_id=agg_id,
        trade_time_ms=t_ms,
        buyer_is_maker=buyer_maker,
        taker_side=taker_side_from_buyer_is_maker(buyer_maker),
        source_file="test",
        source_sha256="0" * 64,
    )


def _oi(t_ms: int, *, contracts: float = 1000.0, value: float = 10_000_000.0) -> OpenInterestRecord:
    return OpenInterestRecord(
        exchange="binance",
        market="usdm_futures",
        symbol="BTCUSDT",
        timestamp_ms=t_ms,
        open_interest_contracts=contracts,
        open_interest_value=value,
        period=OPEN_INTEREST_NATIVE_PERIOD,
        source="test",
        source_file="test",
        source_sha256="0" * 64,
    )


# ---------------------------------------------------------------------------
# Track D2/E1 — contracts and direction semantics
# ---------------------------------------------------------------------------


def test_taker_side_semantics_official_schema() -> None:
    """buyer_is_maker=true -> taker is SELL; false -> taker is BUY (official)."""
    assert taker_side_from_buyer_is_maker(True) is TakerSide.TAKER_SELL
    assert taker_side_from_buyer_is_maker(False) is TakerSide.TAKER_BUY


def test_trade_flow_record_invalid_values_flagged() -> None:
    bad = TradeFlowRecord(
        exchange="binance",
        market="usdm_futures",
        symbol="X",
        agg_trade_id=1,
        price=-1.0,
        quantity=0.0,
        first_trade_id=5,
        last_trade_id=3,
        trade_time_ms=-2,
        buyer_is_maker=False,
        taker_side=TakerSide.TAKER_BUY,
        source_file="t",
        source_sha256="0" * 64,
    )
    errors = bad.__class__ and __import__(
        "trading_bot.research.data_contracts", fromlist=["validate_trade_flow_record"]
    ).validate_trade_flow_record(bad)
    assert set(errors) == {"price_not_positive", "quantity_not_positive", "first_trade_id_gt_last_trade_id", "negative_trade_time"}


# ---------------------------------------------------------------------------
# Normalization + ordering + duplicates
# ---------------------------------------------------------------------------


def test_normalize_trade_flow_sorts_and_flags_duplicates() -> None:
    recs = [_tf(2, 1000), _tf(1, 1000), _tf(3, 500)]
    stats = normalize_trade_flow(recs, decision_time_ms=2000)
    assert stats["rows_within_pit"] == 3
    assert stats["errors"] == {}  # sorting fixes presentation order; times non-decreasing after sort


def test_normalize_trade_flow_duplicate_ids_detected() -> None:
    recs = [_tf(7, 1000), _tf(7, 2000)]
    stats = normalize_trade_flow(recs, decision_time_ms=3000)
    assert stats["errors"]["DUPLICATE_AGG_TRADE_IDS"] == [7]


def test_oi_native_cadence_constants() -> None:
    """DEF-DATA-OI-001: native cadence is 5m (288 rows/complete UTC day)."""
    assert OPEN_INTEREST_NATIVE_PERIOD == "5m"
    assert OPEN_INTEREST_EXPECTED_INTERVAL_MS == 300_000
    assert OPEN_INTEREST_ROWS_PER_COMPLETE_UTC_DAY == 288


def test_normalize_open_interest_gap_detection() -> None:
    # 5m cadence; a 15m hole between the 2nd and 3rd record
    recs = [_oi(0), _oi(300_000), _oi(900_000), _oi(1_200_000)]
    stats = normalize_open_interest(recs, decision_time_ms=10**12)
    assert stats["errors"]["MISSING_INTERVALS"] == [900_000]
    assert stats["expected_interval_ms"] == 300_000


def test_normalize_open_interest_zero_value_flagged() -> None:
    recs = [_oi(0), _oi(300_000, contracts=-5.0, value=-1.0)]
    stats = normalize_open_interest(recs, decision_time_ms=10**12)
    assert len(stats["errors"]["INVALID_RECORDS"]) == 2  # type: ignore[index]


def test_normalize_open_interest_handles_unsorted_provider_rows() -> None:
    """Provider files are not guaranteed row-sorted; canonical state must be."""
    recs = [_oi(600_000), _oi(0), _oi(300_000)]
    stats = normalize_open_interest(recs, decision_time_ms=10**12)
    assert stats["errors"] == {}  # no ORDER_VIOLATIONS after canonical sort
    assert stats["time_min_ms"] == 0 and stats["time_max_ms"] == 600_000


# ---------------------------------------------------------------------------
# PIT + future mutation (DATA-08/09)
# ---------------------------------------------------------------------------


def test_pit_cutoff_splits_future_records() -> None:
    recs = [_tf(1, 1000), _tf(2, 5000)]
    allowed, future = enforce_pit_cutoff(recs, lambda r: r.trade_time_ms, 4999)
    assert [r.agg_trade_id for r in allowed] == [1]
    assert [r.agg_trade_id for r in future] == [2]


def test_future_mutation_does_not_change_state_at_or_before_T() -> None:
    """Mutating records AFTER timestamp T must not change state at/before T."""
    recs_a = [_tf(1, 1000), _tf(2, 2000)]
    recs_b = [_tf(1, 1000), _tf(2, 2000), _tf(3, 9000), _tf(4, 9999)]
    T = 5000
    sa = normalize_trade_flow(recs_a, decision_time_ms=T)
    sb = normalize_trade_flow(recs_b, decision_time_ms=T)
    # Drop error bookkeeping (future lists differ by construction); compare data state.
    for k in ("rows_total",):
        sa.pop(k)
        sb.pop(k)
    assert sa["rows_within_pit"] == sb["rows_within_pit"] == 2
    assert sa["time_min_ms"] == sb["time_min_ms"] == 1000
    assert sa["time_max_ms"] == sb["time_max_ms"] == 2000
    assert sb["errors"]["FUTURE_RECORDS"] == [3, 4]  # reported, never merged


def test_future_mutation_oi_state_stable() -> None:
    a = [_oi(0), _oi(300_000)]
    b = a + [_oi(10**9)]
    sa = normalize_open_interest(a, decision_time_ms=10**8)
    sb = normalize_open_interest(b, decision_time_ms=10**8)
    assert sa["rows_within_pit"] == sb["rows_within_pit"] == 2
    assert sa["time_max_ms"] == sb["time_max_ms"] == 300_000


# ---------------------------------------------------------------------------
# Fingerprints (DATA-07)
# ---------------------------------------------------------------------------


def test_fingerprint_stable_regardless_of_input_order() -> None:
    recs_a = [_tf(1, 1000), _tf(2, 2000)]
    recs_b = [_tf(2, 2000), _tf(1, 1000)]
    fa = fingerprint_trade_flow(
        recs_a, asset="BTCUSDT", time_range_ms=(1000, 2000), schema_version=SCHEMA_VERSION,
        normalizer_version=NORMALIZER_VERSION, source_file_hashes=["h"],
    )
    fb = fingerprint_trade_flow(
        recs_b, asset="BTCUSDT", time_range_ms=(1000, 2000), schema_version=SCHEMA_VERSION,
        normalizer_version=NORMALIZER_VERSION, source_file_hashes=["h"],
    )
    assert fa == fb


def test_fingerprint_changes_on_one_byte_source_change() -> None:
    recs_a = [_tf(1, 1000, price=100.0)]
    recs_b = [_tf(1, 1000, price=100.1)]
    fa = fingerprint_trade_flow(
        recs_a, asset="BTCUSDT", time_range_ms=(1000, 1000), schema_version=SCHEMA_VERSION,
        normalizer_version=NORMALIZER_VERSION, source_file_hashes=["h"],
    )
    fb = fingerprint_trade_flow(
        recs_b, asset="BTCUSDT", time_range_ms=(1000, 1000), schema_version=SCHEMA_VERSION,
        normalizer_version=NORMALIZER_VERSION, source_file_hashes=["h"],
    )
    assert fa != fb


def test_dataset_fingerprint_canonical_and_stable() -> None:
    p1 = {"a": 1, "b": [1, 2, 3], "c": "x"}
    p2 = {"c": "x", "b": [3, 2, 1]}
    assert dataset_fingerprint(p1) != dataset_fingerprint(p2)  # content order matters
    assert dataset_fingerprint(p1) == dataset_fingerprint({"b": [1, 2, 3], "a": 1, "c": "x"})


def test_oi_fingerprint_changes_on_source_hash_change() -> None:
    recs = [_oi(0), _oi(300_000)]
    common = dict(asset="BTCUSDT", time_range_ms=(0, 300_000), schema_version=SCHEMA_VERSION, normalizer_version=NORMALIZER_VERSION)
    f1 = fingerprint_open_interest(recs, source_file_hashes=["old"], **common)
    f2 = fingerprint_open_interest(recs, source_file_hashes=["new"], **common)
    assert f1 != f2


# ---------------------------------------------------------------------------
# Corrupt / missing / schema-change / provider-failure (raw readers)
# ---------------------------------------------------------------------------


def _write_fake_agg_zip(path: Path, header: str, line: str) -> None:
    csv_name = "BTCUSDT-aggTrades-2026-01-01.csv"
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr(csv_name, header + "\n" + line + "\n")


def test_missing_sidecar_raises(tmp_path: Path) -> None:
    z = tmp_path / "BTCUSDT-aggTrades-2026-01-01.zip"
    _write_fake_agg_zip(
        z,
        "agg_trade_id,price,quantity,first_trade_id,last_trade_id,transact_time,is_buyer_maker",
        "1,100.0,1.0,1,1,1704067200000,false",
    )
    with pytest.raises(FileNotFoundError):
        verify_official_checksum(z)


def test_corrupt_zip_raises(tmp_path: Path) -> None:
    z = tmp_path / "BTCUSDT-aggTrades-2026-01-01.zip"
    z.write_bytes(b"not a zip at all")
    sidecar = z.with_suffix(".zip.CHECKSUM")
    import hashlib

    sidecar.write_text(f"{hashlib.sha256(z.read_bytes()).hexdigest()}  {z.name}\n")
    with pytest.raises(Exception):  # noqa: B017 - zipfile.BadZipFile expected
        read_agg_trades_zip(z, "BTCUSDT")


def test_checksum_mismatch_raises(tmp_path: Path) -> None:
    z = tmp_path / "BTCUSDT-aggTrades-2026-01-01.zip"
    _write_fake_agg_zip(
        z,
        "agg_trade_id,price,quantity,first_trade_id,last_trade_id,transact_time,is_buyer_maker",
        "1,100.0,1.0,1,1,1704067200000,false",
    )
    sidecar = z.with_name(z.name + ".CHECKSUM")
    sidecar.write_text(f"{'0' * 64}  {z.name}\n")  # wrong hash
    with pytest.raises(ValueError, match="CHECKSUM MISMATCH"):
        verify_official_checksum(z)


def test_missing_file_raises(tmp_path: Path) -> None:
    z = tmp_path / "does-not-exist.zip"
    with pytest.raises(FileNotFoundError):
        verify_official_checksum(z)


def test_schema_change_raises(tmp_path: Path) -> None:
    z = tmp_path / "BTCUSDT-aggTrades-2026-01-01.zip"
    _write_fake_agg_zip(
        z,
        "agg_trade_id,price,quantity,first_trade_id,last_trade_id,transact_time,buyer_is_maker",  # renamed column
        "1,100.0,1.0,1,1,1704067200000,false",
    )
    import hashlib

    sidecar = z.with_name(z.name + ".CHECKSUM")
    sidecar.write_text(f"{hashlib.sha256(z.read_bytes()).hexdigest()}  {z.name}\n")
    with pytest.raises(ValueError, match="schema drift"):
        read_agg_trades_zip(z, "BTCUSDT")


def test_metrics_schema_change_raises(tmp_path: Path) -> None:
    z = tmp_path / "BTCUSDT-metrics-2026-01-01.zip"
    with zipfile.ZipFile(z, "w") as zf:
        zf.writestr(
            "BTCUSDT-metrics-2026-01-01.csv",
            "create_time,symbol,sum_open_interest\n2026-01-01 00:00:00,BTCUSDT,1.0\n",
        )
    import hashlib

    sidecar = z.with_name(z.name + ".CHECKSUM")
    sidecar.write_text(f"{hashlib.sha256(z.read_bytes()).hexdigest()}  {z.name}\n")
    with pytest.raises(ValueError, match="schema drift"):
        read_metrics_zip(z, "BTCUSDT")


def test_real_ingested_sample_quality_and_pit(tmp_path: Path) -> None:
    """If the bounded real sample exists, assert PIT and zero quality errors."""
    from scripts.ingest_data_families import NORMALIZED

    manifest = NORMALIZED / "trade_flow" / "DATASET_MANIFEST.json"
    if not manifest.exists():
        pytest.skip("ingestion not run in this environment")
    import json

    files = json.loads(manifest.read_text())["files"]
    assert all(f["official_checksum_verified"] for f in files)
    assert all(f["quality_errors"] == {} for f in files)
    assert all(f["rows_within_pit"] == f["rows_total"] for f in files)
