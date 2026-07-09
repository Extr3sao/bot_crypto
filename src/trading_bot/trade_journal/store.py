"""SQLite store for TSK-860 trade intelligence cases."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import asdict
from pathlib import Path
from typing import Any

from trading_bot.trade_journal.types import (
    ChartSnapshot,
    EntryThesis,
    TechnicalZone,
    TradeCase,
    TradeOutcome,
)

CURRENT_SCHEMA_VERSION = 1
_SQLITE_PREFIX = "sqlite:///"
_SECRET_KEYS = ("api_key", "apiSecret", "api_secret", "secret", "token", "cookie", "password")

_SCHEMA_V1_DDL: tuple[str, ...] = (
    """
    CREATE TABLE trade_cases (
        trade_case_id TEXT PRIMARY KEY,
        signal_id TEXT NOT NULL,
        symbol TEXT NOT NULL,
        direction TEXT NOT NULL,
        status TEXT NOT NULL,
        order_id TEXT,
        position_id TEXT,
        created_at INTEGER NOT NULL,
        updated_at INTEGER NOT NULL
    )
    """,
    """
    CREATE TABLE entry_theses (
        trade_case_id TEXT PRIMARY KEY,
        payload_json TEXT NOT NULL,
        created_at INTEGER NOT NULL,
        FOREIGN KEY (trade_case_id) REFERENCES trade_cases(trade_case_id)
    )
    """,
    """
    CREATE TABLE technical_zones (
        zone_id TEXT PRIMARY KEY,
        trade_case_id TEXT NOT NULL,
        payload_json TEXT NOT NULL,
        FOREIGN KEY (trade_case_id) REFERENCES trade_cases(trade_case_id)
    )
    """,
    """
    CREATE TABLE chart_snapshots (
        snapshot_id TEXT PRIMARY KEY,
        trade_case_id TEXT NOT NULL,
        payload_json TEXT NOT NULL,
        FOREIGN KEY (trade_case_id) REFERENCES trade_cases(trade_case_id)
    )
    """,
    """
    CREATE TABLE trade_outcomes (
        trade_case_id TEXT PRIMARY KEY,
        position_id TEXT NOT NULL,
        payload_json TEXT NOT NULL,
        closed_at INTEGER NOT NULL,
        FOREIGN KEY (trade_case_id) REFERENCES trade_cases(trade_case_id)
    )
    """,
    "CREATE INDEX idx_trade_cases_symbol_created ON trade_cases (symbol, created_at DESC)",
    "CREATE INDEX idx_trade_cases_status ON trade_cases (status)",
)


class TradeJournalStore:
    """Durable local journal for trade cases."""

    def __init__(self, database_url: str) -> None:
        db_path = _parse_sqlite_url(database_url)
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._db_path = db_path
        self._conn = sqlite3.connect(str(db_path), isolation_level=None)
        self._conn.row_factory = sqlite3.Row
        try:
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA foreign_keys=ON")
            self._run_migrations()
        except Exception:
            self._conn.close()
            raise

    @property
    def db_path(self) -> Path:
        return self._db_path

    def create_case(self, case: TradeCase) -> None:
        self._conn.execute(
            """
            INSERT INTO trade_cases (
                trade_case_id, signal_id, symbol, direction, status,
                order_id, position_id, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                case.trade_case_id,
                case.signal_id,
                case.symbol,
                case.direction,
                case.status,
                case.order_id,
                case.position_id,
                case.created_at,
                case.created_at,
            ),
        )
        if case.entry_thesis is not None:
            self.save_entry_thesis(case.entry_thesis)
        if case.chart_snapshot is not None:
            self.save_chart_snapshot(case.chart_snapshot)
        if case.outcome is not None:
            self.save_outcome(case.outcome)

    def update_case_status(
        self,
        trade_case_id: str,
        *,
        status: str,
        updated_at: int,
        order_id: str | None = None,
        position_id: str | None = None,
    ) -> None:
        self._conn.execute(
            """
            UPDATE trade_cases
            SET status = ?,
                order_id = COALESCE(?, order_id),
                position_id = COALESCE(?, position_id),
                updated_at = ?
            WHERE trade_case_id = ?
            """,
            (status, order_id, position_id, updated_at, trade_case_id),
        )

    def save_entry_thesis(self, thesis: EntryThesis) -> None:
        payload = _safe_payload(asdict(thesis))
        with self._conn:
            self._conn.execute(
                """
                INSERT INTO entry_theses (trade_case_id, payload_json, created_at)
                VALUES (?, ?, ?)
                ON CONFLICT (trade_case_id) DO UPDATE SET
                    payload_json=excluded.payload_json,
                    created_at=excluded.created_at
                """,
                (thesis.trade_case_id, payload, thesis.created_at),
            )
            self._conn.executemany(
                """
                INSERT INTO technical_zones (zone_id, trade_case_id, payload_json)
                VALUES (?, ?, ?)
                ON CONFLICT (zone_id) DO UPDATE SET
                    payload_json=excluded.payload_json
                """,
                [
                    (zone.zone_id, thesis.trade_case_id, _safe_payload(asdict(zone)))
                    for zone in thesis.zones
                ],
            )

    def save_chart_snapshot(self, snapshot: ChartSnapshot) -> None:
        self._conn.execute(
            """
            INSERT INTO chart_snapshots (snapshot_id, trade_case_id, payload_json)
            VALUES (?, ?, ?)
            ON CONFLICT (snapshot_id) DO UPDATE SET
                payload_json=excluded.payload_json
            """,
            (snapshot.snapshot_id, snapshot.trade_case_id, _safe_payload(asdict(snapshot))),
        )

    def save_outcome(self, outcome: TradeOutcome) -> None:
        self._conn.execute(
            """
            INSERT INTO trade_outcomes (
                trade_case_id, position_id, payload_json, closed_at
            )
            VALUES (?, ?, ?, ?)
            ON CONFLICT (trade_case_id) DO UPDATE SET
                position_id=excluded.position_id,
                payload_json=excluded.payload_json,
                closed_at=excluded.closed_at
            """,
            (
                outcome.trade_case_id,
                outcome.position_id,
                _safe_payload(asdict(outcome)),
                outcome.closed_at,
            ),
        )
        self.update_case_status(
            outcome.trade_case_id,
            status="closed",
            updated_at=outcome.closed_at,
            position_id=outcome.position_id,
        )

    def get_case(self, trade_case_id: str) -> TradeCase | None:
        row = self._conn.execute(
            "SELECT * FROM trade_cases WHERE trade_case_id = ?",
            (trade_case_id,),
        ).fetchone()
        if row is None:
            return None
        return self._hydrate_case(row)

    def list_cases(
        self,
        *,
        symbol: str | None = None,
        status: str | None = None,
        limit: int = 100,
    ) -> list[TradeCase]:
        clauses: list[str] = []
        params: list[object] = []
        if symbol is not None:
            clauses.append("symbol = ?")
            params.append(symbol)
        if status is not None:
            clauses.append("status = ?")
            params.append(status)
        where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
        rows = self._conn.execute(
            f"SELECT * FROM trade_cases{where} ORDER BY created_at DESC LIMIT ?",
            (*params, limit),
        ).fetchall()
        return [self._hydrate_case(row) for row in rows]

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> TradeJournalStore:
        return self

    def __exit__(self, exc_type: object, exc_val: object, exc_tb: object) -> None:
        self.close()

    def _run_migrations(self) -> None:
        row = self._conn.execute("PRAGMA user_version").fetchone()
        version = int(row[0]) if row else 0
        if version < 1:
            for ddl in _SCHEMA_V1_DDL:
                self._conn.execute(ddl)
            self._conn.execute(f"PRAGMA user_version = {CURRENT_SCHEMA_VERSION}")

    def _hydrate_case(self, row: sqlite3.Row) -> TradeCase:
        trade_case_id = str(row["trade_case_id"])
        thesis = self._load_entry_thesis(trade_case_id)
        snapshot = self._load_chart_snapshot(trade_case_id)
        outcome = self._load_outcome(trade_case_id)
        return TradeCase(
            trade_case_id=trade_case_id,
            signal_id=str(row["signal_id"]),
            symbol=str(row["symbol"]),
            direction=str(row["direction"]),  # type: ignore[arg-type]
            status=str(row["status"]),  # type: ignore[arg-type]
            created_at=int(row["created_at"]),
            order_id=row["order_id"],
            position_id=row["position_id"],
            entry_thesis=thesis,
            chart_snapshot=snapshot,
            outcome=outcome,
        )

    def _load_entry_thesis(self, trade_case_id: str) -> EntryThesis | None:
        row = self._conn.execute(
            "SELECT payload_json FROM entry_theses WHERE trade_case_id = ?",
            (trade_case_id,),
        ).fetchone()
        if row is None:
            return None
        payload = json.loads(str(row["payload_json"]))
        zones = tuple(_zone_from_payload(zone) for zone in payload.pop("zones", []))
        payload["criteria_met"] = tuple(payload["criteria_met"])
        payload["criteria_failed"] = tuple(payload["criteria_failed"])
        return EntryThesis(zones=zones, **payload)

    def _load_chart_snapshot(self, trade_case_id: str) -> ChartSnapshot | None:
        row = self._conn.execute(
            "SELECT payload_json FROM chart_snapshots WHERE trade_case_id = ?",
            (trade_case_id,),
        ).fetchone()
        if row is None:
            return None
        return ChartSnapshot(**json.loads(str(row["payload_json"])))

    def _load_outcome(self, trade_case_id: str) -> TradeOutcome | None:
        row = self._conn.execute(
            "SELECT payload_json FROM trade_outcomes WHERE trade_case_id = ?",
            (trade_case_id,),
        ).fetchone()
        if row is None:
            return None
        payload = json.loads(str(row["payload_json"]))
        payload["post_trade_diagnosis"] = tuple(payload["post_trade_diagnosis"])
        return TradeOutcome(**payload)


def _zone_from_payload(payload: dict[str, Any]) -> TechnicalZone:
    return TechnicalZone(**payload)


def _safe_payload(payload: dict[str, Any]) -> str:
    _reject_secret_keys(payload)
    return json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":"))


def _reject_secret_keys(payload: object, path: str = "") -> None:
    if isinstance(payload, dict):
        for key, value in payload.items():
            key_text = str(key)
            key_path = f"{path}.{key_text}" if path else key_text
            if any(secret in key_text.lower() for secret in _SECRET_KEYS):
                raise ValueError(f"trade journal payload contains secret-like key: {key_path}")
            _reject_secret_keys(value, key_path)
    elif isinstance(payload, (list, tuple)):
        for idx, item in enumerate(payload):
            _reject_secret_keys(item, f"{path}[{idx}]")


def _parse_sqlite_url(database_url: str) -> Path:
    if not database_url.startswith(_SQLITE_PREFIX):
        raise NotImplementedError("TradeJournalStore solo soporta sqlite:///<path>.")
    return Path(database_url[len(_SQLITE_PREFIX):])


__all__ = ["CURRENT_SCHEMA_VERSION", "TradeJournalStore"]
