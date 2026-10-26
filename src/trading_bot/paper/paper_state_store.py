"""Persistent state for the paper runtime (startup reconciliation / crash recovery).

GAP-R1 hardening: before this module the paper runtime had ZERO persistence
(broker, idempotency guard and archive were all in-memory), so a process
restart silently lost equity, positions and the intent ledger — and Risk
would assume zero exposure over pre-existing positions.

WHAT is persisted, WHERE, WHEN and WITH WHICH IDENTIFIER:

- ``broker_state``   — equity/initial_equity/fill counters (PaperBroker).
- ``risk_state``     — daily/weekly pnl, trade count, consecutive losses,
                       peak equity, kill-switch flag (RiskManager).
- ``open_positions`` — each open paper position with its full parameters.
- ``closed_trades``  — realized trades (true-net PnL records).
- ``sent_intents``   — the exact ``cloid`` ledger backing exactly-once
                       execution across restarts (stable intent ids from
                       ``paper_cycle.intent_cloid``).
- ``updated_at_ms``  — wall-clock stamp of the last durable write.
- ``run_id``         — the session run that last wrote this state.

Consistency guarantee: a single JSON document written ATOMICALLY
(temp file + fsync + rename). A reader either sees the last fully written
state or a ``CorruptStateFile`` error (fail closed — never silently start
empty over existing exposure). No WAL, no partial state.

This module is deterministic storage only: no market data, no indicators,
no strategy logic, no execution.
"""

from __future__ import annotations

import contextlib
import json
import os
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import structlog

__all__ = [
    "CorruptStateFile",
    "PaperStateStore",
    "SessionPaperState",
    "empty_state",
]


class CorruptStateFile(Exception):
    """Raised when the persisted state exists but cannot be parsed.

    Fail-closed policy: a corrupt file means we cannot know whether
    exposure exists; callers must NOT proceed as if the book were empty.
    """


@dataclass(frozen=True, slots=True)
class SessionPaperState:
    """Durable snapshot of the paper runtime's economic state."""

    schema_version: int
    run_id: str
    updated_at_ms: int
    broker_state: dict[str, Any]
    risk_state: dict[str, Any]
    open_positions: list[dict[str, Any]]
    closed_trades: list[dict[str, Any]]
    sent_intents: list[str] = field(default_factory=list)


def empty_state(*, run_id: str = "") -> SessionPaperState:
    """A pristine state: zero exposure, no intents, no history."""
    return SessionPaperState(
        schema_version=1,
        run_id=run_id,
        updated_at_ms=0,
        broker_state={},
        risk_state={},
        open_positions=[],
        closed_trades=[],
        sent_intents=[],
    )


class PaperStateStore:
    """Atomic JSON-file store for :class:`SessionPaperState`."""

    def __init__(self, path: Path | str) -> None:
        self._path = Path(path)
        self._log = structlog.get_logger("paper_state_store")

    @property
    def path(self) -> Path:
        return self._path

    def exists(self) -> bool:
        return self._path.exists()

    def load_or_recover(self) -> SessionPaperState:
        """Load the durable state.

        - Missing file  → empty state (fresh book, legitimate first run).
        - Corrupt file  → ``CorruptStateFile`` (fail closed). The raw bytes
          are preserved as ``<path>.corrupt`` for post-mortem; nothing is
          overwritten or silently reset.
        """
        if not self._path.exists():
            return empty_state()
        raw = self._path.read_bytes()
        try:
            doc = json.loads(raw.decode("utf-8"))
            state = SessionPaperState(
                schema_version=int(doc["schema_version"]),
                run_id=str(doc.get("run_id", "")),
                updated_at_ms=int(doc.get("updated_at_ms", 0)),
                broker_state=dict(doc.get("broker_state", {})),
                risk_state=dict(doc.get("risk_state", {})),
                open_positions=[dict(p) for p in doc.get("open_positions", [])],
                closed_trades=[dict(t) for t in doc.get("closed_trades", [])],
                sent_intents=[str(c) for c in doc.get("sent_intents", [])],
            )
        except Exception as exc:
            backup = self._path.with_suffix(self._path.suffix + ".corrupt")
            with contextlib.suppress(OSError):
                backup.write_bytes(raw)
            self._log.error("paper_state.corrupt", path=str(self._path), error=str(exc))
            raise CorruptStateFile(
                f"paper state file {self._path} is corrupt: {exc}. "
                "Refusing to start with an unknown book (fail closed)."
            ) from exc
        return state

    def save(self, state: SessionPaperState) -> None:
        """Atomically persist ``state`` (tmp file + fsync + rename)."""
        doc = asdict(state)
        doc["updated_at_ms"] = int(time.time() * 1000)
        payload = json.dumps(doc, sort_keys=True, separators=(",", ":")).encode("utf-8")
        self._path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = self._path.with_suffix(self._path.suffix + ".tmp")
        with open(tmp_path, "wb") as fh:
            fh.write(payload)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp_path, self._path)
        self._log.info(
            "paper_state.saved",
            path=str(self._path),
            open_positions=len(state.open_positions),
            sent_intents=len(state.sent_intents),
        )
