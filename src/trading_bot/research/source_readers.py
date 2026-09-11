"""Official-source readers for admitted data families (checksum + schema guards).

ALPHA-DATA-ADMISSION-01 Tracks D3/E2. Provider-original files are read-only;
every read verifies the official sha256 CHECKSUM sidecar and the official
column schema before parsing. Any drift is a hard error (provider-failure /
schema-change safety), never a silent parse.
"""

from __future__ import annotations

import csv
import hashlib
import io
import zipfile
from datetime import datetime, timezone
from pathlib import Path

from trading_bot.research.data_contracts import (
    OpenInterestRecord,
    TradeFlowRecord,
    taker_side_from_buyer_is_maker,
)

EXPECTED_AGG_TRADES_COLUMNS = [
    "agg_trade_id",
    "price",
    "quantity",
    "first_trade_id",
    "last_trade_id",
    "transact_time",
    "is_buyer_maker",
]

EXPECTED_METRICS_COLUMNS = [
    "create_time",
    "symbol",
    "sum_open_interest",
    "sum_open_interest_value",
    "count_toptrader_long_short_ratio",
    "sum_toptrader_long_short_ratio",
    "count_long_short_ratio",
    "sum_taker_long_short_vol_ratio",
]

_TRUE = {"true", "1", "True", "TRUE"}


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verify_official_checksum(zip_path: Path) -> None:
    """Verify the zip against its official .CHECKSUM sidecar (sha256).

    Raises FileNotFoundError (missing sidecar/file) or ValueError (mismatch).
    """
    if not zip_path.exists():
        raise FileNotFoundError(f"raw file missing: {zip_path}")
    sidecar = zip_path.with_name(zip_path.name + ".CHECKSUM")
    if not sidecar.exists():
        raise FileNotFoundError(f"missing official CHECKSUM sidecar: {sidecar}")
    expected = sidecar.read_text().strip().split()[0]
    actual = sha256_file(zip_path)
    if actual != expected:
        raise ValueError(f"CHECKSUM MISMATCH for {zip_path.name}: {actual} != {expected}")


def _open_single_csv(zip_path: Path) -> tuple[csv.DictReader, zipfile.ZipFile]:
    zf = zipfile.ZipFile(zip_path)
    names = zf.namelist()
    if len(names) != 1 or not names[0].endswith(".csv"):
        raise ValueError(f"unexpected archive layout in {zip_path.name}: {names}")
    fh = zf.open(names[0])
    text = io.TextIOWrapper(fh, encoding="utf-8")
    return csv.DictReader(text), zf


def read_agg_trades_zip(zip_path: Path, symbol: str) -> list[TradeFlowRecord]:
    """Parse one official daily aggTrades zip; schema drift is a hard error."""
    verify_official_checksum(zip_path)
    digest = sha256_file(zip_path)
    records: list[TradeFlowRecord] = []
    reader, zf = _open_single_csv(zip_path)
    try:
        if reader.fieldnames != EXPECTED_AGG_TRADES_COLUMNS:
            raise ValueError(
                f"schema drift in {zip_path.name}: {reader.fieldnames} != {EXPECTED_AGG_TRADES_COLUMNS}"
            )
        for row in reader:
            buyer_is_maker = row["is_buyer_maker"] in _TRUE
            records.append(
                TradeFlowRecord(
                    exchange="binance",
                    market="usdm_futures",
                    symbol=symbol,
                    agg_trade_id=int(row["agg_trade_id"]),
                    price=float(row["price"]),
                    quantity=float(row["quantity"]),
                    first_trade_id=int(row["first_trade_id"]),
                    last_trade_id=int(row["last_trade_id"]),
                    trade_time_ms=int(row["transact_time"]),
                    buyer_is_maker=buyer_is_maker,
                    taker_side=taker_side_from_buyer_is_maker(buyer_is_maker),
                    source_file=f"data/raw/binance_um/aggTrades/{symbol}/{zip_path.name}",
                    source_sha256=digest,
                )
            )
    finally:
        zf.close()
    return records


def read_metrics_zip(zip_path: Path, symbol: str) -> list[OpenInterestRecord]:
    """Parse one official daily futures-metrics zip; schema drift is a hard error."""
    verify_official_checksum(zip_path)
    digest = sha256_file(zip_path)
    records: list[OpenInterestRecord] = []
    reader, zf = _open_single_csv(zip_path)
    try:
        if reader.fieldnames != EXPECTED_METRICS_COLUMNS:
            raise ValueError(
                f"schema drift in {zip_path.name}: {reader.fieldnames} != {EXPECTED_METRICS_COLUMNS}"
            )
        for row in reader:
            ts = (
                datetime.strptime(row["create_time"], "%Y-%m-%d %H:%M:%S")
                .replace(tzinfo=timezone.utc)
                .timestamp()
            )
            records.append(
                OpenInterestRecord(
                    exchange="binance",
                    market="usdm_futures",
                    symbol=symbol,
                    timestamp_ms=int(ts * 1000),
                    open_interest_contracts=float(row["sum_open_interest"]),
                    open_interest_value=float(row["sum_open_interest_value"]),                        period="5m",
                    source="binance_public_data_futures_metrics",
                    source_file=f"data/raw/binance_um/metrics/{symbol}/{zip_path.name}",
                    source_sha256=digest,
                )
            )
    finally:
        zf.close()
    return records
