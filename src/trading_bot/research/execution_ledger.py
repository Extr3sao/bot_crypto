"""ResearchExecutionLedger — durable, append-only research execution governance.

Born from the H3 execution-attempt reconciliation (checkpoint
H3-GOVERNANCE-RECONCILIATION-AND-H5-SELECTION-01, DEF-H3-EXEC-001):

the legacy pattern (marker written AFTER simulation, before result write)
cannot distinguish "never ran" from "ran and crashed before persisting".
This ledger makes every attempt VISIBLE and durable BEFORE any economic
work (data evaluation, signal generation, trade simulation, metric
computation, performance classification). An attempt that dies after
STARTED leaves an immutable trace; a retry is a NEW attempt row with
RECOVERY_OF_ATTEMPT_ID set — attempts are never overwritten or deleted.

Core invariants (unit-tested):

- **STARTED-before-evaluation (EXEC-04):** ``started_experiment`` must be
  persisted and fsync'd (durable confirmation) before any economic work.
- **Atomic authority (EXEC-06):** only ONE process can hold economic
  execution authority for an experiment; a second acquirer receives
  ALREADY_RUNNING / ALREADY_CONSUMED.
- **Crash durability (EXEC-05):** every crash state leaves the attempt
  visible; FALSE_SUCCESS stays 0 (``finished`` requires either a result
  or an explicit failure record).
- **Recovery (B2):** a crashed attempt remains FAILED forever; a retry
  shares the experiment_id with a fresh attempt_id and a recovery link.
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path

STATES = ("STARTED", "COMPLETED", "FAILED", "ABORTED")

LEDGER_FILE = "research_execution_ledger.jsonl"
LOCK_SUFFIX = ".lock"


def _utcnow_iso() -> str:
    import datetime

    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def _sha256_file(path: Path) -> str:
    import hashlib

    return hashlib.sha256(path.read_bytes()).hexdigest()


@dataclass(frozen=True, slots=True)
class LedgerRecord:
    """One execution attempt. Append-only: fields are fixed at creation."""

    experiment_id: str
    attempt_id: str
    attempt_index: int  # 1-based within the experiment
    state: str  # STARTED | COMPLETED | FAILED | ABORTED
    started_at: str
    prereg_commit: str
    spec_sha256: str
    protocol_sha256: str
    dataset_sha256: str
    code_commit: str
    recovery_of_attempt_id: str | None  # B2 link for retries
    finished_at: str | None = None
    result_sha256: str | None = None
    failure_reason: str | None = None
    extra: str = ""  # JSON blob for optional forensics fields


class ResearchExecutionLedger:
    """Append-only JSONL ledger + atomic lock for economic execution authority."""

    def __init__(self, ledger_dir: Path, experiment_id: str, *, concurrent: bool = False) -> None:
        self.dir = Path(ledger_dir)
        self.dir.mkdir(parents=True, exist_ok=True)
        self.experiment_id = experiment_id
        self.ledger_path = self.dir / LEDGER_FILE
        self.lock_path = self.dir / f"{experiment_id}{LOCK_SUFFIX}"
        self.concurrent = concurrent  # test seam: skip real fs locking
        self._lock_held = False

    # ------------------------------------------------------------------
    # Atomic authority (B3)
    # ------------------------------------------------------------------

    def acquire(self) -> str:
        """Acquire economic execution authority.

        Returns 'ACQUIRED', 'ALREADY_RUNNING' (another live process holds the
        lock) or 'ALREADY_CONSUMED' (experiment already COMPLETED).
        """
        records = self._read_all()
        if any(r["experiment_id"] == self.experiment_id and r["state"] == "COMPLETED" for r in records):
            return "ALREADY_CONSUMED"
        if self.concurrent:
            if self._lock_held:
                return "ALREADY_RUNNING"
            self._lock_held = True
            return "ACQUIRED"
        # Cross-platform advisory lock: msvcrt byte-range lock on Windows,
        # fcntl flock on POSIX. The lock is held for the process lifetime.
        # The WHOLE acquire body is failure-atomic: ANY OSError while taking
        # or writing the lock (including Windows same-process write denial)
        # means authority is held elsewhere -> ALREADY_RUNNING.
        fh = open(self.lock_path, "a+")
        try:
            try:
                fh.seek(0)
                try:
                    import msvcrt

                    msvcrt.locking(fh.fileno(), msvcrt.LK_NBLCK, 1)
                except ImportError:
                    import fcntl

                    fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                fh.seek(0)
                fh.truncate()
                fh.write(_utcnow_iso())
                fh.flush()
            except OSError:
                try:
                    fh.close()
                except Exception:  # noqa: BLE001 - best-effort close
                    pass
                return "ALREADY_RUNNING"
        except Exception:  # noqa: BLE001 - never grant authority on unknown errors
            try:
                fh.close()
            except Exception:  # noqa: BLE001
                pass
            return "ALREADY_RUNNING"
        self._fh = fh
        self._lock_held = True
        return "ACQUIRED"

    def release(self) -> None:
        fh = getattr(self, "_fh", None)
        if fh is not None:
            try:
                fh.seek(0)
                try:
                    import msvcrt

                    msvcrt.locking(fh.fileno(), msvcrt.LK_UNLCK, 1)
                except ImportError:
                    import fcntl

                    fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
            except OSError:
                pass
            fh.close()
            self._fh = None
        self._lock_held = False

    # ------------------------------------------------------------------
    # Append-only records
    # ------------------------------------------------------------------

    def _append(self, record: dict[str, object]) -> None:
        with self.ledger_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, sort_keys=True) + "\n")
            fh.flush()
            os.fsync(fh.fileno())  # durable confirmation

    def _read_all(self) -> list[dict[str, object]]:
        if not self.ledger_path.exists():
            return []
        return [
            json.loads(line)
            for line in self.ledger_path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]

    def start_attempt(
        self,
        *,
        spec_sha256: str,
        dataset_sha256: str,
        prereg_commit: str,
        protocol_sha256: str = "",
        code_commit: str = "",
        recovery_of_attempt_id: str | None = None,
    ) -> LedgerRecord:
        """Persist a STARTED record and fsync it. MUST precede all economic work."""
        records = self._read_all()
        distinct_attempts = {r["attempt_id"] for r in records if r["experiment_id"] == self.experiment_id}
        attempt_index = len(distinct_attempts) + 1
        rec = LedgerRecord(
            experiment_id=self.experiment_id,
            attempt_id=f"{self.experiment_id}#a{attempt_index}",
            attempt_index=attempt_index,
            state="STARTED",
            started_at=_utcnow_iso(),
            prereg_commit=prereg_commit,
            spec_sha256=spec_sha256,
            protocol_sha256=protocol_sha256,
            dataset_sha256=dataset_sha256,
            code_commit=code_commit,
            recovery_of_attempt_id=recovery_of_attempt_id,
        )
        self._append(asdict(rec))
        return rec

    def finish_completed(self, attempt_id: str, result_path: Path) -> None:
        result_sha = _sha256_file(result_path)
        prev = self._get(attempt_id)
        self._append(
            {
                **prev,
                "state": "COMPLETED",
                "finished_at": _utcnow_iso(),
                "result_sha256": result_sha,
            }
        )

    def finish_failed(self, attempt_id: str, failure_reason: str) -> None:
        prev = self._get(attempt_id)
        self._append(
            {
                **{k: v for k, v in prev.items()},
                "state": "FAILED",
                "finished_at": _utcnow_iso(),
                "failure_reason": failure_reason,
            }
        )

    def finish_aborted(self, attempt_id: str, failure_reason: str) -> None:
        prev = self._get(attempt_id)
        self._append(
            {
                **{k: v for k, v in prev.items()},
                "state": "ABORTED",
                "finished_at": _utcnow_iso(),
                "failure_reason": failure_reason,
            }
        )

    def _get(self, attempt_id: str) -> dict[str, object]:
        matches = [r for r in self._read_all() if r.get("attempt_id") == attempt_id]
        if not matches:
            raise KeyError(f"attempt {attempt_id} not found")
        return matches[-1]

    # ------------------------------------------------------------------
    # Queries (forensics)
    # ------------------------------------------------------------------

    def experiment_summary(self) -> dict[str, object]:
        """Forensic summary: one entry per attempt (latest event = its state)."""
        records = [r for r in self._read_all() if r["experiment_id"] == self.experiment_id]
        latest_by_attempt: dict[str, dict[str, object]] = {}
        for r in records:  # file order == append order
            latest_by_attempt[str(r["attempt_id"])] = r
        attempts = sorted(latest_by_attempt.values(), key=lambda r: int(r["attempt_index"]))  # type: ignore[arg-type]
        return {
            "experiment_id": self.experiment_id,
            "execution_attempts": len(attempts),
            "completed_executions": sum(1 for r in attempts if r["state"] == "COMPLETED"),
            "failed_attempts": sum(1 for r in attempts if r["state"] == "FAILED"),
            "aborted_attempts": sum(1 for r in attempts if r["state"] == "ABORTED"),
            "open_attempts": sum(1 for r in attempts if r["state"] == "STARTED"),
            "economic_experiments": 1 if attempts else 0,
            "attempts": attempts,
        }


# Convenience wrapper used by exactly-once runners --------------------------


class RunnerLedger:
    """Thin wrapper: acquire -> STARTED -> (economic work) -> COMPLETED/FAILED."""

    def __init__(self, ledger_dir: Path, experiment_id: str) -> None:
        self.ledger = ResearchExecutionLedger(ledger_dir, experiment_id)
        self.attempt_id: str | None = None

    def begin(
        self,
        *,
        spec_sha256: str,
        dataset_sha256: str,
        prereg_commit: str,
        protocol_sha256: str = "",
        code_commit: str = "",
        recovery_of_attempt_id: str | None = None,
    ) -> str:
        verdict = self.ledger.acquire()
        if verdict != "ACQUIRED":
            raise RuntimeError(f"execution authority refused: {verdict}")
        rec = self.ledger.start_attempt(
            spec_sha256=spec_sha256,
            dataset_sha256=dataset_sha256,
            prereg_commit=prereg_commit,
            protocol_sha256=protocol_sha256,
            code_commit=code_commit,
            recovery_of_attempt_id=recovery_of_attempt_id,
        )
        self.attempt_id = rec.attempt_id
        return rec.attempt_id

    def complete(self, result_path: Path) -> None:
        assert self.attempt_id
        self.ledger.finish_completed(self.attempt_id, result_path)
        self.ledger.release()

    def fail(self, reason: str) -> None:
        assert self.attempt_id
        self.ledger.finish_failed(self.attempt_id, reason)
        self.ledger.release()
