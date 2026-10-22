"""ledger — the evidence trail from pixels to PnL.

Every decision writes one line, and every line carries the hash of the one before it.
That turns the ledger from a log into a chain: editing a past decision to make an
experiment look better breaks every subsequent hash, and ``verify_chain`` says exactly
where.

A line is one of:

``RUN``       the parameters of a lane run (dataset, costs, capital, limits, prompt and
              chart spec versions), written once before the first decision;
``DECISION``  image hash, prompt hash, provider metadata, raw answer, parsed decision,
              coherence outcome and the risk verdict;
``FILL``      what the broker did with an approved decision, including the net cost;
``CLOSE``     a closed trade with its net PnL, so the economic result is in the chain
              and not only in a report;
``PROVIDER_FAILURE``  a call that produced no decision, with the reason code.

The writer is single-writer: an exclusive lock file is created next to the ledger and
removed on exit. Two processes writing the same chain would interleave ``prev_sha256``
and the chain would (correctly) fail to verify, so the second writer is refused rather
than allowed to corrupt it.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from trading_bot.vision import failpoints
from trading_bot.vision.durable import pid_alive


def _utc_now() -> str:
    return datetime.now(tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _canonical(payload: dict[str, Any]) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


@dataclass(frozen=True, slots=True)
class LedgerLine:
    seq: int
    prev_sha256: str
    entry: dict[str, Any]
    sha256: str

    def to_json(self) -> str:
        return _canonical(
            {
                "seq": self.seq,
                "prev_sha256": self.prev_sha256,
                "entry": self.entry,
                "sha256": self.sha256,
            }
        )


def line_hash(seq: int, prev_sha256: str, entry: dict[str, Any]) -> str:
    return hashlib.sha256(
        _canonical({"seq": seq, "prev_sha256": prev_sha256, "entry": entry}).encode()
    ).hexdigest()


GENESIS = "0" * 64


class LedgerLockedError(RuntimeError):
    """Another writer holds the ledger. Refused, never merged."""


class OperationConflict(RuntimeError):
    """One ``operation_id`` was re-executed with a different economic result.

    A retry may repeat a committed operation (the crash window between the row and the
    book makes that the normal case) and must then produce the same row, byte for byte
    apart from the clock. Two different results under one identity is not a retry: it is a
    non-deterministic effect, and publishing either of them would make the ledger claim a
    history the book cannot reproduce.
    """


def _economics(entry: dict[str, Any]) -> dict[str, Any]:
    """The row without the wall clock: what two executions of one operation must share."""
    return {key: value for key, value in entry.items() if key != "recorded_at_utc"}


class DecisionLedger:
    """Append-only, hash-chained, single-writer JSONL."""

    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)
        self._lock_path = self.path.with_suffix(self.path.suffix + ".lock")
        #: Where a torn tail was recorded before it was dropped. The ledger is evidence:
        #: a line that was removed has to leave a mark, or the repair is indistinguishable
        #: from an edit.
        self._torn_path = self.path.with_suffix(self.path.suffix + ".torn.json")
        self._lock_fd: int | None = None
        self._seq = 0
        self._last_sha = GENESIS
        #: ``operation_id`` -> the line already on disk, so a re-execution after a crash
        #: appends nothing and returns the committed row instead.
        self._operations: dict[str, LedgerLine] = {}
        self.duplicates_suppressed = 0
        self.tail_repair: dict[str, Any] | None = None

    # -- lifecycle -----------------------------------------------------------

    def open(self) -> DecisionLedger:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        try:
            self._lock_fd = os.open(self._lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError as exc:
            holder = self._lock_owner()
            alive = pid_alive(holder) if holder else None
            if alive is not False:
                raise LedgerLockedError(
                    f"{self._lock_path} exists: another writer owns this ledger "
                    f"(pid={holder}, alive={alive}). If no writer is running, remove the "
                    "stale lock deliberately."
                ) from exc
            #: Un proceso terminado a la fuerza no ejecuta su ``finally``: su cerrojo queda
            #: en disco apuntando a un pid que ya no existe. Sin este relevo, una caída real
            #: no se puede reanudar — y el libro durable estaría protegiendo una cadena que
            #: nadie puede volver a abrir.
            self._lock_path.unlink(missing_ok=True)
            self._lock_fd = os.open(self._lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        os.write(self._lock_fd, str(os.getpid()).encode())
        if self.path.exists():
            self._seq, self._last_sha = self._scan()
        return self

    def close(self) -> None:
        if self._lock_fd is not None:
            os.close(self._lock_fd)
            self._lock_fd = None
            with contextlib.suppress(FileNotFoundError):
                self._lock_path.unlink()

    def __enter__(self) -> DecisionLedger:
        return self.open()

    def __exit__(self, *exc: object) -> None:
        self.close()

    def _lock_owner(self) -> int | None:
        """El pid que dejó escrito el cerrojo, o ``None`` si no se puede leer."""
        try:
            return int(self._lock_path.read_text(encoding="utf-8").strip() or 0)
        except (OSError, ValueError):
            return None

    def _scan(self) -> tuple[int, str]:
        """Read the chain, truncate a torn tail, and index the committed operations.

        A process that dies mid-``write`` leaves bytes that are not a line. That tail was
        never committed — its hash link does not exist and nothing can be derived from it —
        so it is dropped, and the drop is written to ``<ledger>.torn.json`` before it
        happens. A bad line with a good line *after* it is not a torn tail: it is an edit,
        and it is left in place for :func:`verify_chain` to refuse.
        """
        raw = self.path.read_bytes()
        if not raw:
            return 0, GENESIS
        cut = raw.rfind(b"\n") + 1
        complete, tail = raw[:cut], raw[cut:]
        if tail.strip():
            self._truncate(cut, tail, "TORN_TAIL")
        #: Segmentos crudos, no líneas filtradas: el recorte se hace por *offset de byte*, y
        #: calcularlo sumando longitudes de líneas ya filtradas se desvía en cuanto hay una
        #: línea vacía o un CR. Un byte de menos corta una fila buena.
        segments = complete.split(b"\n")[:-1]
        last: dict[str, Any] | None = None
        position = 0
        for index, segment in enumerate(segments):
            if not segment.strip():
                position += len(segment) + 1
                continue
            try:
                row = json.loads(segment.decode("utf-8"))
            except (ValueError, UnicodeDecodeError):
                if any(item.strip() for item in segments[index + 1 :]):
                    raise  # una edición en medio: el fichero no se toca
                #: Basura al final que sí termina en salto de línea: mismo veredicto que
                #: una cola rota, y misma evidencia.
                self._truncate(position, segment, "BAD_TAIL")
                break
            last = row
            operation_id = str(row["entry"].get("operation_id") or "")
            if operation_id and operation_id not in self._operations:
                self._operations[operation_id] = LedgerLine(
                    seq=int(row["seq"]),
                    prev_sha256=str(row["prev_sha256"]),
                    entry=dict(row["entry"]),
                    sha256=str(row["sha256"]),
                )
            position += len(segment) + 1
        if last is None:
            return 0, GENESIS
        return int(last["seq"]), str(last["sha256"])

    def _truncate(self, offset: int, dropped: bytes, reason: str) -> None:
        record = {
            "reason": reason,
            "offset": int(offset),
            "dropped_bytes": len(dropped),
            "dropped_preview": dropped[:120].decode("utf-8", "replace"),
        }
        with self._torn_path.open("w", encoding="utf-8", newline="\n") as handle:
            handle.write(json.dumps(record, sort_keys=True) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        with self.path.open("r+b") as handle:
            handle.truncate(offset)
            handle.flush()
            os.fsync(handle.fileno())
        self.tail_repair = record

    # -- writing -------------------------------------------------------------

    def append(
        self,
        kind: str,
        payload: dict[str, Any],
        *,
        clock: str | None = None,
        operation_id: str | None = None,
    ) -> LedgerLine:
        """Append one line, or return the committed one when the operation repeats.

        ``operation_id`` is the economic identity of the row (``<book>|CLOSE|<position>``).
        A resume after a crash re-executes the bar whose book never landed, so the same
        close is computed a second time; without this the ledger would carry two CLOSE
        rows for one economic event and the *evidence* would be wrong even though the book
        was right. Suppression is only allowed when the repeated row is economically
        identical: a different result under one identity raises
        :class:`OperationConflict` instead of being silently deduplicated.
        """
        if self._lock_fd is None:
            raise LedgerLockedError("ledger.append() before open(): refusing an unlocked write")
        entry = {
            "kind": kind,
            "recorded_at_utc": clock or _utc_now(),
            **({"operation_id": operation_id} if operation_id else {}),
            **payload,
        }
        if operation_id:
            existing = self._operations.get(operation_id)
            if existing is not None:
                if _economics(existing.entry) != _economics(entry):
                    changed = sorted(
                        key
                        for key in set(existing.entry) | set(entry)
                        if existing.entry.get(key) != entry.get(key)
                    )
                    raise OperationConflict(
                        f"{operation_id} was already committed with a different result "
                        f"({', '.join(changed)}); a retry may not change an effect"
                    )
                self.duplicates_suppressed += 1
                return existing
        seq = self._seq + 1
        digest = line_hash(seq, self._last_sha, entry)
        line = LedgerLine(seq=seq, prev_sha256=self._last_sha, entry=entry, sha256=digest)
        if operation_id:
            failpoints.trigger("ledger.before_write", path=self.path, operation_id=operation_id)
        with self.path.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(line.to_json() + "\n")
            if operation_id:
                failpoints.trigger("ledger.after_write", path=self.path, operation_id=operation_id)
            handle.flush()
            os.fsync(handle.fileno())
        if operation_id:
            failpoints.trigger("ledger.after_fsync", path=self.path, operation_id=operation_id)
        self._seq = seq
        self._last_sha = digest
        if operation_id:
            self._operations[operation_id] = line
        return line


def verify_chain(path: Path | str) -> dict[str, Any]:
    """Recompute the chain. Returns counts and the first inconsistency, if any."""
    target = Path(path)
    if not target.exists():
        return {"ok": False, "reason": "MISSING", "lines": 0}
    prev = GENESIS
    count = 0
    kinds: dict[str, int] = {}
    with target.open("r", encoding="utf-8") as handle:
        for raw in handle:
            if not raw.strip():
                continue
            count += 1
            try:
                row = json.loads(raw)
            except json.JSONDecodeError as exc:
                return {"ok": False, "reason": f"BAD_JSON_AT_{count}: {exc}", "lines": count}
            expected = line_hash(int(row["seq"]), str(row["prev_sha256"]), row["entry"])
            if int(row["seq"]) != count:
                return {"ok": False, "reason": f"SEQ_GAP_AT_{count}", "lines": count}
            if str(row["prev_sha256"]) != prev:
                return {"ok": False, "reason": f"BROKEN_LINK_AT_{count}", "lines": count}
            if expected != str(row["sha256"]):
                return {"ok": False, "reason": f"TAMPERED_LINE_{count}", "lines": count}
            prev = str(row["sha256"])
            kind = str(row["entry"].get("kind", "?"))
            kinds[kind] = kinds.get(kind, 0) + 1
    return {"ok": True, "reason": "INTACT", "lines": count, "kinds": kinds, "head_sha256": prev}


def read_entries(path: Path | str) -> list[dict[str, Any]]:
    target = Path(path)
    if not target.exists():
        return []
    out: list[dict[str, Any]] = []
    with target.open("r", encoding="utf-8") as handle:
        for raw in handle:
            if raw.strip():
                out.append(json.loads(raw))
    return out


def summarize(path: Path | str) -> dict[str, Any]:
    """Countable facts for the report: decisions by action and by rejection code."""
    entries = [row["entry"] for row in read_entries(path)]
    actions: dict[str, int] = {}
    rejections: dict[str, int] = {}
    provider_failures: dict[str, int] = {}
    closed: list[float] = []
    for entry in entries:
        kind = entry.get("kind")
        if kind == "DECISION":
            action = str((entry.get("decision") or {}).get("action", "PARSE_FAILED"))
            actions[action] = actions.get(action, 0) + 1
            reason = entry.get("coherence_reason")
            if reason and reason not in ("MODEL_NO_TRADE", "MODEL_LONG", "MODEL_SHORT", "MODEL_CLOSE"):
                rejections[str(reason)] = rejections.get(str(reason), 0) + 1
            blocked = entry.get("risk_blocked_by")
            if blocked:
                rejections[str(blocked)] = rejections.get(str(blocked), 0) + 1
            if entry.get("parse_error"):
                rejections[str(entry["parse_error"])] = rejections.get(str(entry["parse_error"]), 0) + 1
        elif kind == "PROVIDER_FAILURE":
            code = str(entry.get("code", "UNKNOWN"))
            provider_failures[code] = provider_failures.get(code, 0) + 1
        elif kind == "CLOSE":
            closed.append(float(entry.get("pnl_net_usdt", 0.0)))
    return {
        "entries": len(entries),
        "actions": actions,
        "rejections": rejections,
        "provider_failures": provider_failures,
        "closed_trades": len(closed),
        "net_realised_usdt": round(sum(closed), 6) if closed else 0.0,
    }
