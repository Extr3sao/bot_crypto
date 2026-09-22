"""Experiment Registry (FASE 4, P8, P9, P11).

SQLite-backed experiment tracking:
- Preregistration with code/config/data hashes (P9)
- Consumed-periods ledger (P11)
- Status lifecycle: PREREGISTERED → RUNNING → REJECTED/CANDIDATE/CONFIRMED
- Reproducibility: any experiment can be reconstructed from its record

Design:
- One SQLite database (consistent with OHLCVStore and TradeJournal).
- Deterministic: same experiment_id always resolves to same record.
- Fail-closed: corrupted/missing hash → INVALIDATED_HASH_CHANGED.
"""

from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path
from typing import Any

import structlog

from .types import (
    ExperimentRecord,
    ExperimentStatus,
    PerformanceMetrics,
)


class ExperimentRegistry:
    """SQLite-backed experiment registry.

    P8 contract:
    - Each experiment has a unique ID.
    - Code, config, and data are hashed for reproducibility.
    - Status lifecycle is explicit.
    - A consumed period cannot be re-labeled FRESH.
    """

    def __init__(self, db_path: Path | str = ":memory:") -> None:
        self._db_path = str(db_path)
        self._conn = sqlite3.connect(self._db_path)
        self._conn.row_factory = sqlite3.Row
        self._log = structlog.get_logger("experiment_registry")
        self._create_tables()

    def _create_tables(self) -> None:
        self._conn.executescript("""
            CREATE TABLE IF NOT EXISTS experiments (
                experiment_id TEXT PRIMARY KEY,
                strategy_version TEXT NOT NULL,
                hypothesis TEXT NOT NULL,
                rules_json TEXT NOT NULL,
                parameters_json TEXT NOT NULL,
                dataset_start INTEGER NOT NULL,
                dataset_end INTEGER NOT NULL,
                created_at INTEGER NOT NULL,
                code_hash TEXT NOT NULL,
                config_hash TEXT NOT NULL,
                data_hash TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'PREREGISTERED',
                executed_at INTEGER,
                results_json TEXT,
                decision TEXT DEFAULT '',
                parent_experiment TEXT
            );

            CREATE TABLE IF NOT EXISTS consumed_periods (
                period_id INTEGER PRIMARY KEY AUTOINCREMENT,
                experiment_id TEXT NOT NULL,
                symbol TEXT NOT NULL,
                timeframe TEXT NOT NULL,
                start_ts INTEGER NOT NULL,
                end_ts INTEGER NOT NULL,
                consumed_at INTEGER NOT NULL,
                FOREIGN KEY (experiment_id) REFERENCES experiments(experiment_id)
            );

            CREATE INDEX IF NOT EXISTS idx_experiments_status
                ON experiments(status);
            CREATE INDEX IF NOT EXISTS idx_experiments_family
                ON experiments(strategy_version);
            CREATE INDEX IF NOT EXISTS idx_consumed_experiment
                ON consumed_periods(experiment_id);
        """)
        self._conn.commit()

    # ------------------------------------------------------------------
    # Preregistration (P9)
    # ------------------------------------------------------------------

    def preregister(
        self,
        experiment_id: str,
        strategy_version: str,
        hypothesis: str,
        rules: dict[str, Any],
        parameters: dict[str, Any],
        dataset_start: int,
        dataset_end: int,
        code_hash: str,
        config_hash: str,
        data_hash: str,
        parent_experiment: str | None = None,
    ) -> ExperimentRecord:
        """Preregister an experiment (P9: freeze code+config+data).

        Raises ValueError if experiment_id already exists.
        """
        if not experiment_id:
            raise ValueError("experiment_id cannot be empty")
        if not code_hash:
            raise ValueError("code_hash cannot be empty (P9)")

        # Check for existing
        existing = self.get(experiment_id)
        if existing is not None:
            raise ValueError(f"Experiment {experiment_id} already exists")

        now = int(time.time() * 1000)
        self._conn.execute(
            """INSERT INTO experiments
               (experiment_id, strategy_version, hypothesis, rules_json,
                parameters_json, dataset_start, dataset_end, created_at,
                code_hash, config_hash, data_hash, status, parent_experiment)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'PREREGISTERED', ?)""",
            (
                experiment_id,
                strategy_version,
                hypothesis,
                json.dumps(rules),
                json.dumps(parameters),
                dataset_start,
                dataset_end,
                now,
                code_hash,
                config_hash,
                data_hash,
                parent_experiment,
            ),
        )
        self._conn.commit()
        self._log.info("registry.preregistered", experiment_id=experiment_id)
        return self.get(experiment_id)  # type: ignore[return-value]

    def get(self, experiment_id: str) -> ExperimentRecord | None:
        """Get an experiment by ID."""
        row = self._conn.execute(
            "SELECT * FROM experiments WHERE experiment_id = ?",
            (experiment_id,),
        ).fetchone()
        if row is None:
            return None
        return self._row_to_record(row)

    def update_status(
        self,
        experiment_id: str,
        status: ExperimentStatus,
        *,
        results: PerformanceMetrics | None = None,
        decision: str = "",
        executed_at: int | None = None,
    ) -> ExperimentRecord:
        """Update experiment status.

        P9 invariant: PREREGISTERED → RUNNING → REJECTED/CANDIDATE/CONFIRMED.
        INVALIDATED at any time if hash changes.
        """
        record = self.get(experiment_id)
        if record is None:
            raise ValueError(f"Experiment {experiment_id} not found")

        now = int(time.time() * 1000)
        results_json = json.dumps(_metrics_to_dict(results)) if results else None

        self._conn.execute(
            """UPDATE experiments SET
               status = ?, results_json = ?, decision = ?,
               executed_at = COALESCE(?, executed_at)
               WHERE experiment_id = ?""",
            (status, results_json, decision, executed_at or now, experiment_id),
        )
        self._conn.commit()
        self._log.info("registry.status_updated", experiment_id=experiment_id, status=status)
        return self.get(experiment_id)  # type: ignore[return-value]

    def verify_hash(
        self,
        experiment_id: str,
        code_hash: str,
        config_hash: str,
        data_hash: str,
    ) -> bool:
        """Verify that stored hashes match provided hashes (P9).

        If mismatch → status becomes INVALIDATED.
        """
        record = self.get(experiment_id)
        if record is None:
            return False

        if (
            record.code_hash != code_hash
            or record.config_hash != config_hash
            or record.data_hash != data_hash
        ):
            self.update_status(experiment_id, "INVALIDATED", decision="INVALIDATED_HASH_CHANGED")
            self._log.warning("registry.hash_mismatch", experiment_id=experiment_id)
            return False
        return True

    def execute_and_verify(
        self,
        experiment_id: str,
        code_hash: str,
        config_hash: str,
        data_hash: str,
        results: PerformanceMetrics,
        decision: str = "",
    ) -> ExperimentRecord:
        """Execute experiment with automatic hash verification (P9).

        P9 contract: before accepting results, verify that code/config/data
        hashes still match the preregistered values. If mismatch → INVALIDATED.

        This is the recommended way to complete an experiment execution.
        """
        # Verify hashes first (P9: fail-closed)
        if not self.verify_hash(experiment_id, code_hash, config_hash, data_hash):
            self._log.warning(
                "registry.execute_and_verify.hash_mismatch",
                experiment_id=experiment_id,
            )
            # Already INVALIDATED by verify_hash
            return self.get(experiment_id)  # type: ignore[return-value]

        # Hashes match — accept results
        return self.update_status(
            experiment_id,
            "RUNNING",
            results=results,
            decision=decision or "executed_with_verified_hashes",
        )

    # ------------------------------------------------------------------
    # Consumed periods (P11)
    # ------------------------------------------------------------------

    def record_consumed_period(
        self,
        experiment_id: str,
        symbol: str,
        timeframe: str,
        start_ts: int,
        end_ts: int,
    ) -> None:
        """Record that a data period has been consumed (P11)."""
        now = int(time.time() * 1000)
        self._conn.execute(
            """INSERT INTO consumed_periods
               (experiment_id, symbol, timeframe, start_ts, end_ts, consumed_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (experiment_id, symbol, timeframe, start_ts, end_ts, now),
        )
        self._conn.commit()

    def is_consumed(
        self,
        symbol: str,
        timeframe: str,
        start_ts: int,
        end_ts: int,
    ) -> bool:
        """Check if any part of a window overlaps with consumed periods (P11)."""
        row = self._conn.execute(
            """SELECT COUNT(*) as cnt FROM consumed_periods
               WHERE symbol = ? AND timeframe = ?
               AND start_ts < ? AND end_ts > ?""",
            (symbol, timeframe, end_ts, start_ts),
        ).fetchone()
        return (row["cnt"] if row else 0) > 0

    def get_consumed_periods(self, experiment_id: str) -> list[dict[str, Any]]:
        """Get all consumed periods for an experiment."""
        rows = self._conn.execute(
            "SELECT * FROM consumed_periods WHERE experiment_id = ? ORDER BY start_ts",
            (experiment_id,),
        ).fetchall()
        return [dict(r) for r in rows]

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------

    def list_experiments(
        self,
        status: ExperimentStatus | None = None,
    ) -> list[ExperimentRecord]:
        """List experiments, optionally filtered by status."""
        if status:
            rows = self._conn.execute(
                "SELECT * FROM experiments WHERE status = ? ORDER BY created_at DESC",
                (status,),
            ).fetchall()
        else:
            rows = self._conn.execute(
                "SELECT * FROM experiments ORDER BY created_at DESC"
            ).fetchall()
        return [self._row_to_record(r) for r in rows]

    def count_by_status(self) -> dict[str, int]:
        """Count experiments by status."""
        rows = self._conn.execute(
            "SELECT status, COUNT(*) as cnt FROM experiments GROUP BY status"
        ).fetchall()
        return {r["status"]: r["cnt"] for r in rows}

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> ExperimentRegistry:
        return self

    def __exit__(self, *args: Any) -> None:
        self.close()

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _row_to_record(self, row: sqlite3.Row) -> ExperimentRecord:
        """Convert a database row to an ExperimentRecord."""
        return ExperimentRecord(
            experiment_id=row["experiment_id"],
            strategy_version=row["strategy_version"],
            hypothesis=row["hypothesis"],
            rules=json.loads(row["rules_json"]),
            parameters=json.loads(row["parameters_json"]),
            dataset_start=row["dataset_start"],
            dataset_end=row["dataset_end"],
            created_at=row["created_at"],
            code_hash=row["code_hash"],
            config_hash=row["config_hash"],
            data_hash=row["data_hash"],
            status=row["status"],
            executed_at=row["executed_at"],
            results=_dict_to_metrics(json.loads(row["results_json"]))
            if row["results_json"]
            else None,
            decision=row["decision"] or "",
            parent_experiment=row["parent_experiment"],
        )


def _metrics_to_dict(m: PerformanceMetrics) -> dict[str, Any]:
    """Serialize PerformanceMetrics to dict."""
    import dataclasses

    return {f.name: getattr(m, f.name) for f in dataclasses.fields(m)}


def _dict_to_metrics(d: dict[str, Any]) -> PerformanceMetrics:
    """Deserialize dict to PerformanceMetrics."""
    return PerformanceMetrics(**d)


__all__ = ["ExperimentRegistry"]
