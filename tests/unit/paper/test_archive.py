from __future__ import annotations

from pathlib import Path

from trading_bot.paper.archive import PaperSnapshotArchive
from trading_bot.scanner.types import MarketSnapshot


def _snapshot(symbol: str, timestamp: int, *, active: bool, score: float) -> MarketSnapshot:
    return MarketSnapshot(
        symbol=symbol,
        last_price=100.0,
        volume_24h_usdt=10_000_000.0,
        spread_bps=5.0,
        atr_pct=1.0,
        volatility_pct=1.0,
        active=active,
        rejection_reason=None if active else "spread_above_threshold",
        timestamp=timestamp,
        rank_score=score,
    )


def test_archive_round_trips_session_snapshots(tmp_path: Path) -> None:
    with PaperSnapshotArchive(f"sqlite:///{tmp_path}/paper.db") as archive:
        archive.archive_session(
            "session-1",
            1_700_000_000_000,
            [
                _snapshot("BTC/USDT", 1_700_000_000_000, active=True, score=0.8),
                _snapshot("ETH/USDT", 1_700_000_060_000, active=False, score=0.0),
            ],
        )
        rows = archive.list_session("session-1")
        assert [row.symbol for row in rows] == ["BTC/USDT", "ETH/USDT"]
        assert rows[0].active is True
        assert rows[1].active is False


def test_archive_purge_older_than_removes_old_sessions(tmp_path: Path) -> None:
    with PaperSnapshotArchive(f"sqlite:///{tmp_path}/paper.db") as archive:
        archive.archive_session(
            "old",
            1_700_000_000_000,
            [_snapshot("BTC/USDT", 1_700_000_000_000, active=True, score=0.8)],
        )
        archive.archive_session(
            "new",
            1_800_000_000_000,
            [_snapshot("ETH/USDT", 1_800_000_000_000, active=True, score=0.9)],
        )
        removed = archive.purge_older_than(1_750_000_000_000)
        assert removed == 1
        assert archive.list_session("old") == []
        assert len(archive.list_session("new")) == 1
