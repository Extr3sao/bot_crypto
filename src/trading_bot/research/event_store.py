"""Blocked Event Store (P4).

SQLite-backed persistence for blocked signals.
P4 contract: every BLOCKED signal must save its reason.

Provides:
- Persist blocked events with full metadata
- Query by family, symbol, reason, time range
- Aggregate counts by reason
- Export to CSV for analysis
"""

from __future__ import annotations

import sqlite3
import time
from pathlib import Path
from typing import Any

import structlog

from .types import BlockedEvent, BlockedReason


class BlockedEventStore:
    """SQLite-backed blocked event persistence (P4).

    Every BLOCKED signal is recorded with:
    - family, symbol, direction, reason, details
    - timestamp for temporal queries
    - run_id for cross-run correlation
    """

    def __init__(self, db_path: Path | str = ":memory:") -> None:
        self._db_path = str(db_path)
        self._conn = sqlite3.connect(self._db_path)
        self._conn.row_factory = sqlite3.Row
        self._log = structlog.get_logger("blocked_event_store")
        self._create_tables()

    def _create_tables(self) -> None:
        self._conn.executescript("""
            CREATE TABLE IF NOT EXISTS blocked_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                signal_family TEXT NOT NULL,
                symbol TEXT NOT NULL,
                timestamp INTEGER NOT NULL,
                direction TEXT NOT NULL,
                reason TEXT NOT NULL,
                details TEXT DEFAULT '',
                run_id TEXT,
                recorded_at INTEGER NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_blocked_family
                ON blocked_events(signal_family);
            CREATE INDEX IF NOT EXISTS idx_blocked_symbol
                ON blocked_events(symbol);
            CREATE INDEX IF NOT EXISTS idx_blocked_reason
                ON blocked_events(reason);
            CREATE INDEX IF NOT EXISTS idx_blocked_timestamp
                ON blocked_events(timestamp);
            CREATE INDEX IF NOT EXISTS idx_blocked_run
                ON blocked_events(run_id);
        """)
        self._conn.commit()

    def record(
        self,
        event: BlockedEvent,
        run_id: str | None = None,
    ) -> int:
        """Record a blocked event. Returns the row ID."""
        now = int(time.time() * 1000)
        cursor = self._conn.execute(
            """INSERT INTO blocked_events
               (signal_family, symbol, timestamp, direction, reason, details, run_id, recorded_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                event.signal_family,
                event.symbol,
                event.timestamp,
                event.direction,
                event.reason,
                event.details,
                run_id,
                now,
            ),
        )
        self._conn.commit()
        row_id = cursor.lastrowid
        self._log.info(
            "blocked_event.recorded",
            family=event.signal_family,
            symbol=event.symbol,
            reason=event.reason,
        )
        return row_id or 0

    def record_batch(
        self,
        events: list[BlockedEvent],
        run_id: str | None = None,
    ) -> int:
        """Record multiple blocked events. Returns count recorded."""
        now = int(time.time() * 1000)
        rows = [
            (
                e.signal_family,
                e.symbol,
                e.timestamp,
                e.direction,
                e.reason,
                e.details,
                run_id,
                now,
            )
            for e in events
        ]
        self._conn.executemany(
            """INSERT INTO blocked_events
               (signal_family, symbol, timestamp, direction, reason, details, run_id, recorded_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            rows,
        )
        self._conn.commit()
        self._log.info("blocked_event.batch_recorded", count=len(rows))
        return len(rows)

    def query(
        self,
        *,
        family: str | None = None,
        symbol: str | None = None,
        reason: BlockedReason | None = None,
        start_ts: int | None = None,
        end_ts: int | None = None,
        run_id: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """Query blocked events with filters."""
        conditions: list[str] = []
        params: list[Any] = []

        if family:
            conditions.append("signal_family = ?")
            params.append(family)
        if symbol:
            conditions.append("symbol = ?")
            params.append(symbol)
        if reason:
            conditions.append("reason = ?")
            params.append(reason)
        if start_ts is not None:
            conditions.append("timestamp >= ?")
            params.append(start_ts)
        if end_ts is not None:
            conditions.append("timestamp <= ?")
            params.append(end_ts)
        if run_id:
            conditions.append("run_id = ?")
            params.append(run_id)

        where = " AND ".join(conditions) if conditions else "1=1"
        params.append(limit)

        rows = self._conn.execute(
            f"SELECT * FROM blocked_events WHERE {where} ORDER BY timestamp DESC LIMIT ?",
            params,
        ).fetchall()

        return [dict(r) for r in rows]

    def count_by_reason(
        self,
        *,
        family: str | None = None,
        start_ts: int | None = None,
        end_ts: int | None = None,
    ) -> dict[str, int]:
        """Count blocked events grouped by reason."""
        conditions: list[str] = []
        params: list[Any] = []

        if family:
            conditions.append("signal_family = ?")
            params.append(family)
        if start_ts is not None:
            conditions.append("timestamp >= ?")
            params.append(start_ts)
        if end_ts is not None:
            conditions.append("timestamp <= ?")
            params.append(end_ts)

        where = " AND ".join(conditions) if conditions else "1=1"

        rows = self._conn.execute(
            f"SELECT reason, COUNT(*) as cnt FROM blocked_events WHERE {where} GROUP BY reason",
            params,
        ).fetchall()

        return {r["reason"]: r["cnt"] for r in rows}

    def total_count(self, *, run_id: str | None = None) -> int:
        """Count total blocked events, optionally by run."""
        if run_id:
            row = self._conn.execute(
                "SELECT COUNT(*) as cnt FROM blocked_events WHERE run_id = ?",
                (run_id,),
            ).fetchone()
        else:
            row = self._conn.execute("SELECT COUNT(*) as cnt FROM blocked_events").fetchone()
        return row["cnt"] if row else 0

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> BlockedEventStore:
        return self

    def __exit__(self, *args: Any) -> None:
        self.close()


__all__ = ["BlockedEventStore"]
