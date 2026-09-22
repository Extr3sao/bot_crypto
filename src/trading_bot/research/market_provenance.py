"""Market Data Provenance and Real Exchange Data for V0.2.3 §2-4.

V0.2.3 §2: Data provenance (exchange, source, retrieval method).
V0.2.3 §3: Real public exchange OHLCV (Binance/Bybit public REST).
V0.2.3 §4: Snapshot immutability (SHA-256 checksum).
"""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import structlog

from .evidence import EvidenceClass


@dataclass(frozen=True, slots=True)
class MarketDataProvenance:
    """Verifiable data provenance for a dataset.

    V0.2.3 §2: HISTORICAL_MARKET_REAL requires provenance.
    """

    dataset_id: str
    exchange: str
    market_type: str  # "spot" | "futures"
    symbol: str
    timeframe: str
    source: str  # "binance_public_rest" | "bybit_public_rest" | "ccxt"
    retrieval_method: str  # "public_api" | "websocket" | "file"
    retrieved_at: int  # epoch ms
    start: int  # epoch ms
    end: int  # epoch ms
    bars: int
    checksum: str  # SHA-256 of OHLCV data
    raw_checksum: str = ""  # SHA-256 of raw response
    evidence_class: EvidenceClass = EvidenceClass.HISTORICAL_MARKET_REAL

    def to_dict(self) -> dict[str, Any]:
        return {
            "dataset_id": self.dataset_id,
            "exchange": self.exchange,
            "market_type": self.market_type,
            "symbol": self.symbol,
            "timeframe": self.timeframe,
            "source": self.source,
            "retrieval_method": self.retrieval_method,
            "retrieved_at": self.retrieved_at,
            "start": self.start,
            "end": self.end,
            "bars": self.bars,
            "checksum": self.checksum,
            "raw_checksum": self.raw_checksum,
            "evidence_class": self.evidence_class.value,
        }

    def assert_operational(self) -> None:
        """Raise if provenance doesn't support HISTORICAL_MARKET_REAL."""
        required = [
            self.exchange,
            self.market_type,
            self.symbol,
            self.timeframe,
            self.source,
            self.retrieval_method,
            self.checksum,
        ]
        missing = [f for f in required if not f]
        if missing:
            raise ValueError(
                f"Provenance incomplete for HISTORICAL_MARKET_REAL: missing fields: {missing}"
            )
        if self.bars <= 0:
            raise ValueError(f"Provenance bars must be > 0, got {self.bars}")


class BinancePublicOHLCV:
    """Download OHLCV from Binance public REST API.

    V0.2.3 §3: Real public exchange data, no credentials needed.
    """

    BASE_URL = "https://api.binance.com"

    def __init__(self) -> None:
        self._log = structlog.get_logger("binance_public_ohlcv")

    def fetch_klines(
        self,
        symbol: str,
        interval: str,
        start_ms: int,
        end_ms: int,
        limit: int = 1000,
    ) -> list[dict[str, Any]]:
        """Fetch klines from Binance public API.

        No credentials required.
        """
        try:
            import urllib.parse
            import urllib.request

            all_bars: list[dict[str, Any]] = []
            current_start = start_ms

            while current_start < end_ms:
                params = urllib.parse.urlencode(
                    {
                        "symbol": symbol.replace("/", ""),
                        "interval": interval,
                        "startTime": current_start,
                        "endTime": end_ms,
                        "limit": limit,
                    }
                )
                url = f"{self.BASE_URL}/api/v3/klines?{params}"

                req = urllib.request.Request(url)
                with urllib.request.urlopen(req, timeout=30) as resp:
                    data = json.loads(resp.read().decode("utf-8"))

                if not data:
                    break

                for kline in data:
                    bar = {
                        "timestamp": int(kline[0]),
                        "open": float(kline[1]),
                        "high": float(kline[2]),
                        "low": float(kline[3]),
                        "close": float(kline[4]),
                        "volume": float(kline[5]),
                    }
                    all_bars.append(bar)

                # Move to next batch
                current_start = data[-1][0] + 1
                if len(data) < limit:
                    break

            self._log.info(
                "binance.fetched",
                symbol=symbol,
                interval=interval,
                bars=len(all_bars),
            )
            return all_bars

        except Exception as e:
            self._log.error("binance.fetch_failed", error=str(e))
            raise

    def fetch_and_snapshot(
        self,
        symbol: str,
        interval: str,
        start_ms: int,
        end_ms: int,
        dataset_id: str,
        output_dir: Path,
    ) -> tuple[list[dict[str, Any]], MarketDataProvenance]:
        """Fetch OHLCV and create immutable snapshot.

        V0.2.3 §4: Save raw + compute checksum.
        """
        bars = self.fetch_klines(symbol, interval, start_ms, end_ms)

        # Compute checksum
        checksum = self._compute_checksum(bars)

        # Create provenance
        provenance = MarketDataProvenance(
            dataset_id=dataset_id,
            exchange="binance",
            market_type="spot",
            symbol=symbol,
            timeframe=interval,
            source="binance_public_rest",
            retrieval_method="public_api",
            retrieved_at=int(time.time() * 1000),
            start=bars[0]["timestamp"] if bars else start_ms,
            end=bars[-1]["timestamp"] if bars else end_ms,
            bars=len(bars),
            checksum=checksum,
            evidence_class=EvidenceClass.HISTORICAL_MARKET_REAL,
        )

        # Save snapshot
        output_dir.mkdir(parents=True, exist_ok=True)
        ohlcv_path = output_dir / "ohlcv.json"
        ohlcv_path.write_text(json.dumps(bars, separators=(",", ":")), encoding="utf-8")

        meta_path = output_dir / "metadata.json"
        meta_path.write_text(json.dumps(provenance.to_dict(), indent=2), encoding="utf-8")

        checksum_path = output_dir / "checksum.sha256"
        checksum_path.write_text(checksum, encoding="utf-8")

        self._log.info(
            "binance.snapshot_saved",
            dataset_id=dataset_id,
            bars=len(bars),
            checksum=checksum[:16],
        )

        return bars, provenance

    def _compute_checksum(self, bars: list[dict[str, Any]]) -> str:
        """SHA-256 of OHLCV data."""
        hasher = hashlib.sha256()
        for bar in sorted(bars, key=lambda b: b.get("timestamp", 0)):
            key = f"{bar.get('timestamp', '')}:{bar.get('open', '')}:{bar.get('high', '')}:{bar.get('low', '')}:{bar.get('close', '')}:{bar.get('volume', '')}"
            hasher.update(key.encode("utf-8"))
        return hasher.hexdigest()


class BybitPublicOHLCV:
    """Download OHLCV from Bybit public REST API.

    V0.2.3 §3: Alternative public exchange.
    """

    BASE_URL = "https://api.bybit.com"
    _log = structlog.get_logger("bybit_public_ohlcv")

    def fetch_klines(
        self,
        symbol: str,
        interval: str,
        start_ms: int,
        end_ms: int,
        limit: int = 200,
    ) -> list[dict[str, Any]]:
        """Fetch klines from Bybit public API."""
        try:
            import urllib.parse
            import urllib.request

            # Map interval to Bybit format
            interval_map = {"1m": "1", "5m": "5", "15m": "15", "1h": "60", "4h": "240", "1d": "D"}
            bybit_interval = interval_map.get(interval, interval)

            all_bars: list[dict[str, Any]] = []
            current_start = start_ms

            while current_start < end_ms:
                params = urllib.parse.urlencode(
                    {
                        "category": "spot",
                        "symbol": symbol.replace("/", ""),
                        "interval": bybit_interval,
                        "start": current_start,
                        "end": end_ms,
                        "limit": limit,
                    }
                )
                url = f"{self.BASE_URL}/v5/market/kline?{params}"

                req = urllib.request.Request(url)
                with urllib.request.urlopen(req, timeout=30) as resp:
                    data = json.loads(resp.read().decode("utf-8"))

                result_list = data.get("result", {}).get("list", [])
                if not result_list:
                    break

                for kline in result_list:
                    bar = {
                        "timestamp": int(kline[0]),
                        "open": float(kline[1]),
                        "high": float(kline[2]),
                        "low": float(kline[3]),
                        "close": float(kline[4]),
                        "volume": float(kline[5]),
                    }
                    all_bars.append(bar)

                current_start = int(result_list[-1][0]) + 1
                if len(result_list) < limit:
                    break

            self._log.info(
                "bybit.fetched",
                symbol=symbol,
                bars=len(all_bars),
            )
            return all_bars

        except Exception as e:
            self._log.error("bybit.fetch_failed", error=str(e))
            raise


__all__ = [
    "BinancePublicOHLCV",
    "BybitPublicOHLCV",
    "MarketDataProvenance",
]
