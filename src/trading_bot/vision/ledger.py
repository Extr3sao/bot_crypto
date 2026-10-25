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

CODEX: the lock is ``ops.single_writer.SingleWriter``, not a bare ``O_EXCL`` file. A lock
left behind by a killed process used to wedge the ledger forever (the only way out was
deleting a file by hand), and a recycled pid made it look held by a stranger. Ownership is
now proved — dead pid, or a live pid that started at a different instant — before it is
taken, and it is fenced, so a writer that lost it fails closed on its next ``append``.
"""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from trading_bot.ops.single_writer import LockLost, LockRefused, SingleWriter


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


class DecisionLedger:
    """Append-only, hash-chained, single-writer JSONL."""

    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)
        self._lock_path = self.path.with_suffix(self.path.suffix + ".lock")
        self._lock = SingleWriter(self._lock_path, purpose=f"ledger:{self.path.name}")
        self._seq = 0
        self._last_sha = GENESIS

    # -- lifecycle -----------------------------------------------------------

    def open(self) -> DecisionLedger:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        #: A validated ledger holds the lock. An abandoned one (crash) is reclaimed with the
        #: evidence attached to the error/record, never blindly; a live owner is refused.
        try:
            self._lock.acquire()
        except LockRefused as exc:
            raise LedgerLockedError(
                f"{self._lock_path}: {exc}. If no writer is running, the lock can be reclaimed "
                "only when its owner is proved gone (ops.single_writer)."
            ) from exc
        if self.path.exists():
            self._seq, self._last_sha = self._tail()
        return self

    @property
    def lock_record(self) -> dict[str, Any]:
        return dict(self._lock.record or {})

    def close(self) -> None:
        if self._lock.record is not None:
            self._lock.release()

    def __enter__(self) -> DecisionLedger:
        return self.open()

    def __exit__(self, *exc: object) -> None:
        self.close()

    def _tail(self) -> tuple[int, str]:
        last: dict[str, Any] | None = None
        with self.path.open("r", encoding="utf-8") as handle:
            for raw in handle:
                if raw.strip():
                    last = json.loads(raw)
        if last is None:
            return 0, GENESIS
        return int(last["seq"]), str(last["sha256"])

    # -- writing -------------------------------------------------------------

    def append(self, kind: str, payload: dict[str, Any], *, clock: str | None = None) -> LedgerLine:
        #: Re-read the lock before every line: an owner that lost its lock (a paused process
        #: whose lease was reclaimed) must fail closed rather than fork the chain.
        try:
            self._lock.assert_held()
        except LockLost as exc:
            raise LedgerLockedError(str(exc)) from exc
        entry = {
            "kind": kind,
            "recorded_at_utc": clock or _utc_now(),
            **payload,
        }
        seq = self._seq + 1
        digest = line_hash(seq, self._last_sha, entry)
        line = LedgerLine(seq=seq, prev_sha256=self._last_sha, entry=entry, sha256=digest)
        with self.path.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(line.to_json() + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        self._seq = seq
        self._last_sha = digest
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
