"""SQLite snapshot archive for paper-trading sessions (TSK-105)."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import cast

from trading_bot.scanner import MarketSnapshot, RejectionReason
from trading_bot.storage.ohlcv_store import _parse_sqlite_url


class PaperSnapshotArchive:
    """Persists paper-session snapshots with TTL-style cleanup."""

    def __init__(self, database_url: str) -> None:
        db_path = _parse_sqlite_url(database_url)
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._db_path = db_path
        self._conn = sqlite3.connect(str(db_path), isolation_level=None)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS paper_snapshots (
                session_id TEXT NOT NULL,
                archived_at_ms INTEGER NOT NULL,
                symbol TEXT NOT NULL,
                last_price REAL NOT NULL,
                volume_24h_usdt REAL NOT NULL,
                spread_bps REAL NOT NULL,
                atr_pct REAL,
                volatility_pct REAL,
                active INTEGER NOT NULL,
                rejection_reason TEXT,
                timestamp INTEGER NOT NULL,
                rank_score REAL NOT NULL,
                PRIMARY KEY (session_id, symbol, timestamp)
            )
            """
        )
        self._conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_paper_snapshots_archived_at
            ON paper_snapshots (archived_at_ms)
            """
        )

    @property
    def db_path(self) -> Path:
        return self._db_path

    def archive_session(
        self,
        session_id: str,
        archived_at_ms: int,
        snapshots: list[MarketSnapshot],
    ) -> int:
        rows = [
            (
                session_id,
                archived_at_ms,
                snap.symbol,
                snap.last_price,
                snap.volume_24h_usdt,
                snap.spread_bps,
                snap.atr_pct,
                snap.volatility_pct,
                1 if snap.active else 0,
                snap.rejection_reason,
                snap.timestamp,
                snap.rank_score,
            )
            for snap in snapshots
        ]
        if not rows:
            return 0
        cur = self._conn.executemany(
            """
            INSERT INTO paper_snapshots (
                session_id, archived_at_ms, symbol, last_price, volume_24h_usdt,
                spread_bps, atr_pct, volatility_pct, active, rejection_reason,
                timestamp, rank_score
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT (session_id, symbol, timestamp) DO UPDATE SET
                last_price=excluded.last_price,
                volume_24h_usdt=excluded.volume_24h_usdt,
                spread_bps=excluded.spread_bps,
                atr_pct=excluded.atr_pct,
                volatility_pct=excluded.volatility_pct,
                active=excluded.active,
                rejection_reason=excluded.rejection_reason,
                rank_score=excluded.rank_score
            """,
            rows,
        )
        return cur.rowcount

    def list_session(self, session_id: str) -> list[MarketSnapshot]:
        cur = self._conn.execute(
            """
            SELECT symbol, last_price, volume_24h_usdt, spread_bps, atr_pct,
                   volatility_pct, active, rejection_reason, timestamp, rank_score
            FROM paper_snapshots
            WHERE session_id = ?
            ORDER BY timestamp ASC, symbol ASC
            """,
            (session_id,),
        )
        return [
            MarketSnapshot(
                symbol=str(row[0]),
                last_price=float(row[1]),
                volume_24h_usdt=float(row[2]),
                spread_bps=float(row[3]),
                atr_pct=float(row[4]) if row[4] is not None else None,
                volatility_pct=float(row[5]) if row[5] is not None else None,
                active=bool(row[6]),
                rejection_reason=(
                    cast(RejectionReason, row[7]) if row[7] is not None else None
                ),
                timestamp=int(row[8]),
                rank_score=float(row[9]),
            )
            for row in cur.fetchall()
        ]

    def purge_older_than(self, cutoff_ms: int) -> int:
        cur = self._conn.execute(
            "DELETE FROM paper_snapshots WHERE archived_at_ms < ?",
            (cutoff_ms,),
        )
        return cur.rowcount

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> PaperSnapshotArchive:
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        self.close()


__all__ = ["PaperSnapshotArchive"]
