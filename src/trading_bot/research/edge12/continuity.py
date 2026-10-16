"""WP-EDGE-12D — continuity proved on the runtime, not asserted about the design.

RFC-EDGE-012 asks for resumption after a restart, resumption after an absent session,
idempotency, no concurrent corruption, timeout handling, missed-trigger detection,
recovery of an incomplete state, ledger reconciliation and alerts that follow real
failures. Nine properties, and the failure mode of a work package answering them is
to describe the code: this repository is full of correct mechanisms and the useful
question is not whether they were written but whether they were ever exercised.

So this module drives the **real observer**, with the real ingest and the real store
layout, over a *copy* of the store, under an isolated state root. Six things are then
measurable rather than arguable:

* a second trigger inside an observed slot makes **no market request**;
* a trigger that arrives while another tick holds the lease changes **nothing**;
* a lease a hard-killed process left behind is reclaimed **by age**, because this
  platform cannot always prove a pid is dead;
* bars that closed while the observer was down are **recovered by the next tick**,
  over the network, and counted;
* a log line interrupted mid-write is **counted and survived**, not repaired away;
* a duplicated slot seal is **dropped**, and the ledger goes back to behaving like a
  set.

The copy matters and is not a shortcut: the live store is this campaign's evidence,
and a rehearsal that wrote into it would be producing the evidence it is measuring.
The isolated root is what lets the rehearsal be wrong without damaging anything.

Read-only with respect to the live state root, the live store and the live task.

Research only: public market data, no credentials, no orders, no capital.
"""

from __future__ import annotations

import json
import shutil
import sys
import time
from datetime import UTC, datetime
from itertools import pairwise
from pathlib import Path
from typing import Any

__all__ = [
    "CONTINUITY_SCHEMA_VERSION",
    "PROPERTIES",
    "live_continuity",
    "matrix",
    "rehearsal",
    "rehearsal_summary",
]

CONTINUITY_SCHEMA_VERSION = "EDGE12_CONTINUITY_REHEARSAL_V1"

#: The nine properties RFC-EDGE-012 names, as ids, so a matrix row can never be added
#: without one of them or dropped without the omission being visible.
PROPERTIES: tuple[tuple[str, str], ...] = (
    (
        "IDEMPOTENT_SLOT",
        "an observed slot is not observed twice and makes no second market request",
    ),
    ("SINGLE_INSTANCE", "two triggers at once cannot both write: the second changes nothing"),
    (
        "STALE_LEASE_RECLAIM",
        "a lease left by a crashed process is reclaimed by age, not wedged forever",
    ),
    (
        "RESUME_AFTER_RESTART",
        "bars that closed while the observer was down are recovered by the next tick",
    ),
    (
        "RESUME_AFTER_ABSENT_SESSION",
        "a tick missed because nobody was signed in is not lost by construction",
    ),
    (
        "INCOMPLETE_WRITE_SURVIVAL",
        "a log line interrupted mid-write is counted and the lane keeps running",
    ),
    (
        "LEDGER_RECONCILIATION",
        "a duplicated slot seal is dropped and the day reconciles with the ledger",
    ),
    (
        "TIMEOUT_HANDLING",
        "a tick cannot outlive its own interval, and the lease bound is shorter than one tick",
    ),
    (
        "MISSED_TRIGGER_DETECTION",
        "a silence longer than the declared bound is detected and alerted, not averaged away",
    ),
)


def _now_ms() -> int:
    import time

    return int(time.time() * 1000)


def _stamp(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000, tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _series_digests(store_root: Path) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for timeframe in ("1h", "15m"):
        directory = store_root / timeframe
        if not directory.is_dir():
            continue
        for path in sorted(directory.glob("*.jsonl")):
            data = path.read_bytes()
            import hashlib

            out[f"{timeframe}:{path.stem}"] = {
                "rows": sum(1 for line in data.splitlines() if line.strip()),
                "bytes": len(data),
                "sha256": hashlib.sha256(data).hexdigest(),
            }
    return out


def _truncate_store(store_root: Path, *, drop_last: int) -> dict[str, Any]:
    """Remove the newest ``drop_last`` bars from every series, simulating a downtime.

    This is the only way to measure recovery: a tick that has nothing to recover proves
    nothing about recovery, and waiting for a real outage is not a plan. The bars that
    were removed leave with their own timestamps, because the check that follows is not
    "a bar came back" but "every bar that had closed by the declared instant came back".
    """
    dropped: dict[str, int] = {}
    removed: dict[str, list[int]] = {}
    for timeframe in ("1h", "15m"):
        directory = store_root / timeframe
        if not directory.is_dir():
            continue
        for path in sorted(directory.glob("*.jsonl")):
            lines = [line for line in path.read_bytes().splitlines() if line.strip()]
            keep = max(0, len(lines) - drop_last)
            gone = lines[keep:]
            key = f"{timeframe}:{path.stem}"
            dropped[key] = len(gone)
            removed[key] = [int(json.loads(line)["ts"]) for line in gone]
            path.write_bytes(b"".join(line + b"\n" for line in lines[:keep]))
    return {
        "dropped_per_series": dropped,
        "dropped_total": sum(dropped.values()),
        "removed_timestamps": removed,
    }


#: The span of each timeframe's bar, so the rehearsal can say which removed bars had
#: already closed by the declared instant. Restated from the store's own grid rather than
#: imported: a check that imported the number it checks would agree with itself.
_SPAN_MS: dict[str, int] = {"1h": 3_600_000, "15m": 900_000}


def _closed_by(*, removed: dict[str, list[int]], market_instant_ms: int) -> dict[str, int]:
    """How many of the removed bars had already closed at the declared market instant."""
    out: dict[str, int] = {}
    for key, timestamps in removed.items():
        timeframe = key.split(":")[0]
        span = _SPAN_MS.get(timeframe, 0)
        out[key] = sum(1 for ts in timestamps if ts + span <= market_instant_ms)
    return out


class _Rehearsal:
    """One rehearsal, with its receipts, over an isolated store and state root."""

    def __init__(self, *, repo_root: Path, work_root: Path, store_source: Path) -> None:
        self.repo_root = Path(repo_root)
        self.work_root = Path(work_root)
        self.store_source = Path(store_source)
        self.store_root = self.work_root / "store"
        self.state_root = self.work_root / "state"
        self.scratch = self.work_root / "scratch"
        self.steps: list[dict[str, Any]] = []

    def _observer(self, **kwargs: Any) -> Any:
        sys.path.insert(0, str(self.repo_root / "src"))
        from trading_bot.research.edge03.autonomous import ForwardObserver

        return ForwardObserver(
            repo_root=self.repo_root,
            state_root=self.state_root,
            store_root=self.store_root,
            **kwargs,
        )

    def tick(self, observer: Any, **kwargs: Any) -> tuple[dict[str, Any], float]:
        """Run one tick and time it with a stopwatch.

        The tick's own ``duration_seconds`` is not a timing source under an injected clock, and
        this is worth stating exactly rather than assuming: a tick takes ``started_ms`` from the
        injected ``now_ms`` and closes with the wall clock, so its duration is
        *wall clock minus the clock the rehearsal pinned*. While the pin sits behind the wall
        clock that reads as an offset (the first tick here reported 900.797 s for a call that
        took a few seconds), and once the rehearsal advances the pin past the wall clock it reads
        as a negative number. The rehearsal therefore times the call itself, keeps the reported
        value beside it as a cross-check, and never judges a property from it.
        """
        started = time.perf_counter()
        result = observer.tick(**kwargs)
        return result, round(time.perf_counter() - started, 3)

    def record(
        self,
        *,
        step_id: str,
        property_id: str,
        expected: str,
        observed: dict[str, Any],
        verdict: str,
        artifacts: dict[str, Any] | None = None,
    ) -> None:
        self.steps.append(
            {
                "step_id": step_id,
                "property": property_id,
                "expected": expected,
                "observed": observed,
                "verdict": verdict,
                "artifacts": artifacts or {},
            }
        )

    def _reset_roots(self) -> None:
        """An isolated home for this rehearsal, emptied of the previous run's results.

        The store is copied rather than shared because it is this campaign's evidence. The state
        root is wiped rather than inherited for a reason the second run of this rehearsal made
        plain: it found its own first slot already sealed by the previous run, returned
        `ALREADY_OBSERVED` where the rehearsal expected a slot-consuming tick, and failed three
        properties on a ledger that was behaving exactly as designed. A rehearsal that inherits
        another rehearsal's ledger measures the ledger, not the observer.
        """
        self.work_root.mkdir(parents=True, exist_ok=True)
        self.scratch.mkdir(parents=True, exist_ok=True)
        if self.state_root.exists():
            shutil.rmtree(self.state_root)
        if self.store_root.exists():
            shutil.rmtree(self.store_root)
        shutil.copytree(self.store_source, self.store_root)

    def run(self, *, drop_last: int = 2, market_instant_ms: int | None = None) -> dict[str, Any]:
        from trading_bot.research.edge03 import autonomous as AUTO

        self._reset_roots()
        baseline = _series_digests(self.store_root)
        self.record(
            step_id="copy_the_store",
            property_id="BASELINE",
            expected="an isolated copy of the live store, byte for byte, over an empty state root",
            observed={
                "series": baseline,
                "source": str(self.store_source),
                "state_root_emptied": True,
            },
            verdict="PASS",
        )

        observer = self._observer()
        instant = int(market_instant_ms or _now_ms())
        # The clock and the market instant are set independently, and deliberately:
        #
        # * the *clock* decides which slot a launch belongs to, and the rehearsal needs each
        #   step in a slot of its own, so the clock is pinned to a fixed offset inside
        #   successive slot boundaries rather than to the wall clock a test happens to run at;
        # * the *market instant* decides which bars have closed, and it stays the same for every
        #   step. The recovery step is the reason: with the market instant re-declared, what a
        #   tick recovers is the deficit the downtime created, not whatever closed while the
        #   rehearsal was running.
        #
        # `--due` is what the scheduler passes, so the first tick is what a scheduled launch
        # does, and the slot it seals is the one the clock names.
        clock_base = (instant // AUTO.SLOT_MS) * AUTO.SLOT_MS
        first, first_seconds = self.tick(
            observer,
            observed_at_ms=instant,
            due_only=True,
            mode=AUTO.MODE_SCHEDULED,
            now_ms=clock_base + 30_000,
        )
        after_first = _series_digests(self.store_root)
        self.record(
            step_id="first_tick",
            property_id="BASELINE",
            expected="a tick that runs the whole pipeline and seals its slot",
            observed={
                "outcome": first.get("outcome"),
                "new_bars": first.get("new_bars"),
                "market_requests": first.get("market_requests"),
                "wall_seconds": first_seconds,
                "duration_seconds_the_tick_reports": first.get("duration_seconds"),
                "slot_key": first.get("slot_key"),
                "slot_sealed": first.get("slot_sealed"),
                "store_after": after_first,
            },
            verdict="PASS" if first.get("outcome") in AUTO.SLOT_CONSUMING_OUTCOMES else "FAIL",
        )

        # --- idempotency: the same slot, a second trigger ---------------------------------
        # 210 s later, which is inside the same 15-minute slot with seven minutes of margin:
        # a second trigger in the slot the first one sealed, not a trigger in the next one.
        second, second_seconds = self.tick(
            observer,
            observed_at_ms=instant,
            due_only=True,
            mode=AUTO.MODE_SCHEDULED,
            now_ms=clock_base + 240_000,
        )
        after_second = _series_digests(self.store_root)
        self.record(
            step_id="repeat_inside_the_same_slot",
            property_id="IDEMPOTENT_SLOT",
            expected="ALREADY_OBSERVED with zero market requests and an unchanged store",
            observed={
                "outcome": second.get("outcome"),
                "wall_seconds": second_seconds,
                "market_requests": second.get("market_requests"),
                "store_unchanged": after_second == after_first,
                "slot_seals": len(
                    (self.state_root / "slots.jsonl").read_text(encoding="utf-8").splitlines()
                ),
            },
            verdict=(
                "PASS"
                if second.get("outcome") == AUTO.ALREADY_OBSERVED
                and int(second.get("market_requests") or 0) == 0
                and after_second == after_first
                else "FAIL"
            ),
        )

        # --- concurrency: another holder, then a stale lease ------------------------------
        # The clock and the market instant are set independently, and deliberately. The lease
        # steps need a slot the schedule has not already sealed, which is a property of the
        # clock; they return before ingesting anything, so the market instant is irrelevant to
        # them. The lock's own fields are epoch SECONDS -- the lease compares `now - renewed_at`
        # against its bound, and a record written in milliseconds is a lease that is never old
        # enough to reclaim, which is exactly how a first attempt at this rehearsal reported
        # two properties as failures that the code had implemented correctly.
        clock_now = (clock_base + AUTO.SLOT_MS) // 1000
        lock_dir = self.state_root / "lock"
        lock_dir.mkdir(parents=True, exist_ok=True)
        lock_path = lock_dir / "CAMPAIGN_LOCK.json"
        held = {
            "lease_version": "CAMPAIGN_LEASE_V1",
            "campaign_id": "EDGE04_FORWARD_OBSERVER",
            "pid": __import__("os").getpid(),
            "host": "rehearsal",
            "acquired_at": clock_now,
            "renewed_at": clock_now,
            "stale_after_seconds": AUTO.LEASE_STALE_AFTER_SECONDS,
        }
        lock_path.write_text(json.dumps(held) + "\n", encoding="utf-8")
        third, third_seconds = self.tick(
            observer,
            observed_at_ms=instant,
            due_only=True,
            mode=AUTO.MODE_SCHEDULED,
            now_ms=clock_base + AUTO.SLOT_MS + 30_000,
        )
        after_third = _series_digests(self.store_root)
        self.record(
            step_id="trigger_while_another_tick_holds_the_lease",
            property_id="SINGLE_INSTANCE",
            expected="ALREADY_RUNNING, no market request, the store untouched",
            observed={
                "outcome": third.get("outcome"),
                "wall_seconds": third_seconds,
                "market_requests": third.get("market_requests"),
                "store_unchanged": after_third == after_first,
                "lease": third.get("lease"),
                "holder": third.get("lease", {}).get("holder") if third.get("lease") else None,
            },
            verdict=(
                "PASS"
                if third.get("outcome") == AUTO.ALREADY_RUNNING
                and int(third.get("market_requests") or 0) == 0
                and after_third == after_first
                else "FAIL"
            ),
        )

        stale = {
            **held,
            "pid": 999_999,
            "renewed_at": clock_now - AUTO.LEASE_STALE_AFTER_SECONDS - 60,
        }
        lock_path.write_text(json.dumps(stale) + "\n", encoding="utf-8")
        fourth, fourth_seconds = self.tick(
            observer,
            observed_at_ms=instant,
            due_only=True,
            mode=AUTO.MODE_SCHEDULED,
            now_ms=clock_base + 2 * AUTO.SLOT_MS + 30_000,
        )
        self.record(
            step_id="lease_left_by_a_crashed_process",
            property_id="STALE_LEASE_RECLAIM",
            expected="the lease is reclaimed by age and the tick proceeds",
            observed={
                "outcome": fourth.get("outcome"),
                "wall_seconds": fourth_seconds,
                # The tick's own lease record, kept whole, with the status beside it because a
                # reader should not have to know the record's shape to see the verdict. The
                # independent verifier checks the record and the matrix reads the status, and a
                # rehearsal that published only the derived string would leave that reader
                # checking a summary of the evidence instead of the evidence.
                "lease": fourth.get("lease"),
                "lease_status": (fourth.get("lease") or {}).get("status"),
                "lease_age_seconds": AUTO.LEASE_STALE_AFTER_SECONDS + 60,
                "previous_holder_pid": (
                    (fourth.get("lease") or {}).get("previous_holder") or {}
                ).get("pid"),
            },
            verdict=(
                "PASS"
                if str((fourth.get("lease") or {}).get("status")) == "STALE_LEASE_RECLAIMED"
                else "FAIL"
            ),
        )

        # --- recovery of bars that closed during a downtime -------------------------------
        before_drop = _series_digests(self.store_root)
        dropped = _truncate_store(self.store_root, drop_last=drop_last)
        after_drop = _series_digests(self.store_root)
        expected_recovery = _closed_by(
            removed=dropped["removed_timestamps"], market_instant_ms=instant
        )
        fifth, fifth_seconds = self.tick(
            observer,
            observed_at_ms=instant,
            due_only=True,
            mode=AUTO.MODE_SCHEDULED,
            now_ms=clock_base + 3 * AUTO.SLOT_MS + 30_000,
        )
        recovered = _series_digests(self.store_root)
        rows_restored = {
            key: recovered[key]["rows"]
            - (before_drop[key]["rows"] - dropped["dropped_per_series"].get(key, 0))
            for key in before_drop
        }
        self.record(
            step_id="bars_that_closed_while_the_observer_was_down",
            property_id="RESUME_AFTER_RESTART",
            expected=(
                "the next tick recovers every removed bar that had closed by the declared market "
                "instant, and only those"
            ),
            observed={
                "dropped": {
                    "dropped_per_series": dropped["dropped_per_series"],
                    "dropped_total": dropped["dropped_total"],
                },
                "expected_recovery_per_series": expected_recovery,
                "rows_restored_per_series": rows_restored,
                "rows_before_drop": {key: row["rows"] for key, row in before_drop.items()},
                "rows_after_drop": {key: row["rows"] for key, row in after_drop.items()},
                "rows_after_recovery": {key: row["rows"] for key, row in recovered.items()},
                "outcome": fifth.get("outcome"),
                "wall_seconds": fifth_seconds,
                "new_bars_reported": fifth.get("new_bars"),
                "market_instant_utc": fifth.get("market_instant_utc"),
                "clock_instant_utc": fifth.get("started_at_utc"),
                "note": (
                    "the market instant is the first tick's, re-declared: the recovery is measured "
                    "as the deficit being filled, not as whatever closed while the rehearsal ran"
                ),
            },
            verdict=(
                "PASS"
                if fifth.get("outcome") == AUTO.OBSERVED
                and rows_restored == expected_recovery
                and sum(expected_recovery.values()) > 0
                else "FAIL"
            ),
        )

        # --- an interrupted write ----------------------------------------------------------
        runs_path = self.state_root / "runs.jsonl"
        original = runs_path.read_bytes()
        runs_path.write_bytes(original + b'{"schema_version": "EDGE04_TICK_V1", "run_id": "trunc')
        sixth, sixth_seconds = self.tick(
            observer,
            observed_at_ms=instant,
            due_only=True,
            mode=AUTO.MODE_SCHEDULED,
            now_ms=clock_base + 4 * AUTO.SLOT_MS + 30_000,
        )
        rows_after = [line for line in runs_path.read_bytes().splitlines() if line.strip()]
        partial_present = any(b"trunc" in line for line in rows_after)
        self.record(
            step_id="a_log_line_interrupted_mid_write",
            property_id="INCOMPLETE_WRITE_SURVIVAL",
            expected="the truncated line is counted and the lane still records its own row",
            observed={
                "outcome": sixth.get("outcome"),
                "wall_seconds": sixth_seconds,
                "corrupt_log_lines": sixth.get("corrupt_log_lines"),
                "partial_line_still_present": partial_present,
                "rows_after": len(rows_after),
                "rows_before": len([line for line in original.splitlines() if line.strip()]),
            },
            verdict=(
                "PASS"
                if int(sixth.get("corrupt_log_lines") or 0) >= 1 and partial_present
                else "FAIL"
            ),
        )

        # --- a duplicated seal and the reconciliation -------------------------------------
        slots_path = self.state_root / "slots.jsonl"
        slot_lines = [line for line in slots_path.read_bytes().splitlines() if line.strip()]
        duplicated = [*slot_lines, slot_lines[0]]
        slots_path.write_bytes(b"".join(line + b"\n" for line in duplicated))
        repair = observer.dedupe_slots()
        unique_keys = {
            json.loads(line).get("slot_key")
            for line in slots_path.read_bytes().splitlines()
            if line.strip()
        }
        daily_files = sorted(self.state_root.glob("daily/*.json"))
        daily_summary = {}
        for path in daily_files:
            payload = json.loads(path.read_text(encoding="utf-8"))
            daily_summary[path.name] = {
                "ticks": payload.get("ticks"),
                "new_bars": payload.get("new_bars"),
                "slots": len(payload.get("slots") or {}),
                "hypothetical": payload.get("hypothetical"),
                "order_sent": payload.get("order_sent"),
            }
        self.record(
            step_id="a_duplicated_slot_seal",
            property_id="LEDGER_RECONCILIATION",
            expected="the duplicate is dropped and the slot ledger behaves like a set",
            observed={
                "duplicates_dropped": len(repair.get("dropped") or []),
                "unique_slot_keys": len(unique_keys),
                "rows_after_repair": len(
                    [line for line in slots_path.read_bytes().splitlines() if line.strip()]
                ),
                "daily": daily_summary,
            },
            verdict="PASS" if len(repair.get("dropped") or []) == 1 else "FAIL",
        )

        wall = [
            first_seconds,
            second_seconds,
            third_seconds,
            fourth_seconds,
            fifth_seconds,
            sixth_seconds,
        ]
        reported = [
            float(row.get("duration_seconds") or 0)
            for row in (first, second, third, fourth, fifth, sixth)
        ]
        self.record(
            step_id="a_tick_against_its_own_interval",
            property_id="TIMEOUT_HANDLING",
            expected="every rehearsal tick fits inside the interval with room for its successor",
            observed={
                "wall_seconds": wall,
                "maximum_seconds": max(wall) if wall else None,
                "reported_durations_seconds": reported,
                "interval_seconds": AUTO.SCHEDULE_INTERVAL_SECONDS,
                "lease_stale_after_seconds": AUTO.LEASE_STALE_AFTER_SECONDS,
                "lease_shorter_than_the_interval": AUTO.LEASE_STALE_AFTER_SECONDS
                < AUTO.SCHEDULE_INTERVAL_SECONDS,
                "note": (
                    "the wall figures come from a stopwatch around the call; the reported ones "
                    "are wall_clock minus the pinned clock and are kept only as a cross-check, "
                    "because a tick that takes its start from an injected clock cannot time itself"
                ),
            },
            verdict=(
                "PASS"
                if wall
                and max(wall) < AUTO.SCHEDULE_INTERVAL_SECONDS
                and bool(AUTO.LEASE_STALE_AFTER_SECONDS < AUTO.SCHEDULE_INTERVAL_SECONDS)
                else "FAIL"
            ),
        )
        return {
            "schema_version": CONTINUITY_SCHEMA_VERSION,
            "generated_at_utc": _stamp(_now_ms()),
            "work_root": str(self.work_root),
            "store_source": str(self.store_source),
            "steps": self.steps,
            "failures": [row["step_id"] for row in self.steps if row["verdict"] != "PASS"],
            "verdict": "REHEARSAL_PASS"
            if all(row["verdict"] == "PASS" for row in self.steps)
            else "REHEARSAL_FAILED",
            "hypothetical": True,
            "order_sent": False,
            "promotion": "NONE",
        }


def rehearsal(
    *,
    repo_root: Path,
    work_root: Path,
    store_source: Path,
    drop_last: int = 2,
    market_instant_ms: int | None = None,
    network: bool = True,
) -> dict[str, Any]:
    """Run the rehearsal, or record honestly that it could not run."""
    if not network:
        return {
            "schema_version": CONTINUITY_SCHEMA_VERSION,
            "generated_at_utc": _stamp(_now_ms()),
            "steps": [],
            "verdict": "REHEARSAL_NOT_RUN",
            "reason": "the caller declared that the network is unavailable",
            "hypothetical": True,
            "order_sent": False,
        }
    if not store_source.is_dir():
        return {
            "schema_version": CONTINUITY_SCHEMA_VERSION,
            "generated_at_utc": _stamp(_now_ms()),
            "steps": [],
            "verdict": "REHEARSAL_NOT_RUN",
            "reason": f"no store to copy at {store_source}",
            "hypothetical": True,
            "order_sent": False,
        }
    return _Rehearsal(repo_root=repo_root, work_root=work_root, store_source=store_source).run(
        drop_last=drop_last, market_instant_ms=market_instant_ms
    )


def rehearsal_summary(rehearsal_row: dict[str, Any]) -> dict[str, Any]:
    """One line per step, for a report reader who does not want the receipts."""
    return {
        "verdict": rehearsal_row.get("verdict"),
        "steps": [
            {
                "step_id": row["step_id"],
                "property": row["property"],
                "verdict": row["verdict"],
            }
            for row in rehearsal_row.get("steps") or []
        ],
        "failures": rehearsal_row.get("failures") or [],
    }


def live_continuity(
    *,
    runs_path: Path,
    alerts_path: Path,
    slots_path: Path,
    state_root: Path,
    interval_seconds: int = 900,
    gap_warning_seconds: int = 2_100,
) -> dict[str, Any]:
    """What the live lane's own logs say about the same properties, without a rehearsal.

    Two of the nine properties cannot be rehearsed without ending the session this work
    runs in — a real sign-in absence and a real missed trigger — so they are read from
    the live evidence instead, and the reading says which of the two it is.
    """
    rows: list[dict[str, Any]] = []
    corrupt_runs = 0
    if runs_path.is_file():
        for line in runs_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                corrupt_runs += 1
    rows.sort(key=lambda row: int(row.get("started_at_ms") or 0))
    gaps: list[dict[str, Any]] = []
    for previous, following in pairwise(rows):
        delta = (
            int(following.get("started_at_ms") or 0) - int(previous.get("started_at_ms") or 0)
        ) / 1000.0
        if delta > gap_warning_seconds:
            gaps.append(
                {
                    "from_utc": previous.get("started_at_utc"),
                    "to_utc": following.get("started_at_utc"),
                    "seconds": round(delta, 1),
                    "missed_intervals": int(delta // interval_seconds) - 1,
                }
            )
    alerts: list[dict[str, Any]] = []
    if alerts_path.is_file():
        for line in alerts_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                loaded = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(loaded, dict):
                alerts.append(loaded)
    kinds: dict[str, int] = {}
    for alert in alerts:
        kind = str(alert.get("kind") or alert.get("alert") or "UNKNOWN")
        kinds[kind] = kinds.get(kind, 0) + 1
    slot_rows = 0
    slot_keys: set[str] = set()
    if slots_path.is_file():
        for line in slots_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            slot_rows += 1
            try:
                slot_keys.add(str(json.loads(line).get("slot_key")))
            except json.JSONDecodeError:
                continue
    durations = [float(row.get("duration_seconds") or 0) for row in rows]
    derived_path = state_root / "derived_refresh.jsonl"
    derived_rows = 0
    derived_failures = 0
    if derived_path.is_file():
        for line in derived_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                loaded = json.loads(line)
            except json.JSONDecodeError:
                continue
            derived_rows += 1
            if not loaded.get("ran"):
                derived_failures += 1
    return {
        "runs": len(rows),
        "corrupt_run_lines": corrupt_runs,
        "first_tick_utc": rows[0].get("started_at_utc") if rows else None,
        "last_tick_utc": rows[-1].get("finished_at_utc") if rows else None,
        "gaps_over_the_declared_bound": gaps,
        "worst_gap_seconds": max((gap["seconds"] for gap in gaps), default=None),
        "slots_sealed_rows": slot_rows,
        "slots_unique_keys": len(slot_keys),
        "slot_ledger_is_a_set": slot_rows == len(slot_keys),
        "maximum_tick_seconds": max(durations, default=None),
        "median_tick_seconds": _median(durations),
        "ticks_over_the_interval": sum(1 for value in durations if value >= interval_seconds),
        "alerts": {"total": len(alerts), "kinds": dict(sorted(kinds.items()))},
        "derived_refresh": {
            "rows": derived_rows,
            "failures": derived_failures,
            "reading": (
                "one row per scheduled tick that consumed its slot: the lane re-reads its own "
                "reconciliation from the cadence rather than from a person running a command"
            ),
        },
        "corrupt_evidence_is_counted_not_hidden": corrupt_runs,
    }


def _median(values: list[float]) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return round(ordered[middle], 3)
    return round((ordered[middle - 1] + ordered[middle]) / 2, 3)


def _mechanisms_by_name(session_evidence: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """The probe verdicts, whether they arrive as a list or as a mapping.

    Two producers write this record: the session probe numbers its results into an array,
    and this campaign keys them by mechanism. Accepting only one of the two makes the
    matrix silently treat the other as "no probe was run", which is the difference between
    a property that was exercised and one that merely looks like it was not.
    """
    probes = session_evidence.get("probes")
    if isinstance(probes, dict):
        return {str(name): dict(row) for name, row in probes.items() if isinstance(row, dict)}
    if isinstance(probes, list):
        return {str(row.get("mechanism")): row for row in probes if isinstance(row, dict)}
    return {}


def matrix(
    *,
    rehearsal_row: dict[str, Any],
    live: dict[str, Any],
    session_evidence: dict[str, Any],
) -> dict[str, Any]:
    """The nine properties, each with where it was exercised and what the answer was.

    A property that could not be exercised is `NOT_EXERCISED` and says why. There is no
    row in this table whose verdict is `PASS` because the design intends it: either a
    rehearsal step or a live reading is named as the evidence, or the row says it has none.
    """
    steps = {row["step_id"]: row for row in rehearsal_row.get("steps") or []}
    session_mechanisms = _mechanisms_by_name(session_evidence)
    rows: list[dict[str, Any]] = []

    def add(
        property_id: str,
        evidence_kind: str,
        evidence_ref: str,
        verdict: str,
        detail: str,
    ) -> None:
        rows.append(
            {
                "property": property_id,
                "evidence_kind": evidence_kind,
                "evidence": evidence_ref,
                "verdict": verdict,
                "detail": detail,
            }
        )

    idempotent = steps.get("repeat_inside_the_same_slot")
    add(
        "IDEMPOTENT_SLOT",
        "REHEARSED_ON_THE_RUNTIME",
        "repeat_inside_the_same_slot",
        idempotent["verdict"] if idempotent else "NOT_EXERCISED",
        f"outcome {idempotent['observed']['outcome']} with {idempotent['observed']['market_requests']} "
        f"market request(s), store unchanged "
        f"{idempotent['observed']['store_unchanged']}"
        if idempotent
        else "the rehearsal did not reach this step",
    )
    single = steps.get("trigger_while_another_tick_holds_the_lease")
    add(
        "SINGLE_INSTANCE",
        "REHEARSED_ON_THE_RUNTIME",
        "trigger_while_another_tick_holds_the_lease",
        single["verdict"] if single else "NOT_EXERCISED",
        f"outcome {single['observed']['outcome']} while another holder's lease was live, store unchanged "
        f"{single['observed']['store_unchanged']}"
        if single
        else "the rehearsal did not reach this step",
    )
    stale = steps.get("lease_left_by_a_crashed_process")
    add(
        "STALE_LEASE_RECLAIM",
        "REHEARSED_ON_THE_RUNTIME",
        "lease_left_by_a_crashed_process",
        stale["verdict"] if stale else "NOT_EXERCISED",
        f"lease status "
        f"{stale['observed'].get('lease_status') or (stale['observed'].get('lease') or {}).get('status')} "
        f"after an {stale['observed'].get('lease_age_seconds')} s old lease"
        if stale
        else "the rehearsal did not reach this step",
    )
    resume = steps.get("bars_that_closed_while_the_observer_was_down")
    add(
        "RESUME_AFTER_RESTART",
        "REHEARSED_ON_THE_RUNTIME",
        "bars_that_closed_while_the_observer_was_down",
        resume["verdict"] if resume else "NOT_EXERCISED",
        f"{resume['observed']['dropped']['dropped_total']} bar(s) removed, next tick reported "
        f"new_bars={resume['observed']['new_bars_reported']} outcome={resume['observed']['outcome']}"
        if resume
        else "the rehearsal did not reach this step",
    )
    logon = session_mechanisms.get("SESSION_LOGON_TRIGGER") or {}
    add(
        "RESUME_AFTER_ABSENT_SESSION",
        "OBSERVED_LIVE_AND_BOUNDED",
        "WP-EDGE-04R SESSION_INDEPENDENCE.json + the logon-trigger probe in this pass",
        "BOUNDED_NOT_REMOVED",
        (
            "the absence itself cannot be removed without a privilege or a credential this package "
            f"does not have; the logon trigger is {logon.get('verdict', 'UNKNOWN')} on this host and "
            f"the worst live gap was {live.get('worst_gap_seconds')} s"
        ),
    )
    write = steps.get("a_log_line_interrupted_mid_write")
    add(
        "INCOMPLETE_WRITE_SURVIVAL",
        "REHEARSED_ON_THE_RUNTIME",
        "a_log_line_interrupted_mid_write",
        write["verdict"] if write else "NOT_EXERCISED",
        f"corrupt_log_lines={write['observed']['corrupt_log_lines']}, partial line preserved "
        f"{write['observed']['partial_line_still_present']}"
        if write
        else "the rehearsal did not reach this step",
    )
    ledger = steps.get("a_duplicated_slot_seal")
    add(
        "LEDGER_RECONCILIATION",
        "REHEARSED_ON_THE_RUNTIME_AND_READ_LIVE",
        "a_duplicated_slot_seal + the live slot ledger",
        ledger["verdict"] if ledger else "NOT_EXERCISED",
        f"{ledger['observed']['duplicates_dropped']} duplicate(s) dropped; the live ledger holds "
        f"{live['slots_sealed_rows']} row(s) and {live['slots_unique_keys']} unique key(s)"
        if ledger
        else "the rehearsal did not reach this step",
    )
    timeout = steps.get("a_tick_against_its_own_interval")
    add(
        "TIMEOUT_HANDLING",
        "REHEARSED_ON_THE_RUNTIME_AND_READ_LIVE",
        "a_tick_against_its_own_interval + the live run log",
        timeout["verdict"] if timeout else "NOT_EXERCISED",
        f"rehearsal maximum {timeout['observed']['maximum_seconds']} s of wall clock against a "
        f"{timeout['observed']['interval_seconds']} s interval; live maximum "
        f"{live.get('maximum_tick_seconds')} s with {live.get('ticks_over_the_interval')} tick(s) over it"
        if timeout
        else "the rehearsal did not reach this step",
    )
    gaps = live.get("gaps_over_the_declared_bound") or []
    alert_kinds = (live.get("alerts") or {}).get("kinds") or {}
    add(
        "MISSED_TRIGGER_DETECTION",
        "READ_LIVE",
        "the live run log and alerts.jsonl",
        "DETECTED" if gaps else "NO_SILENCE_IN_THE_WINDOW",
        f"{len(gaps)} silence(s) over the declared bound, worst {live.get('worst_gap_seconds')} s; "
        f"alerts recorded: {alert_kinds or 'none'}",
    )

    covered = {row["property"] for row in rows}
    missing = [name for name, _ in PROPERTIES if name not in covered]
    passed = [row["property"] for row in rows if row["verdict"] == "PASS"]
    return {
        "schema_version": "EDGE12_CONTINUITY_MATRIX_V1",
        "generated_at_utc": _stamp(_now_ms()),
        "properties_required": [name for name, _ in PROPERTIES],
        "properties_missing": missing,
        "rows": rows,
        "passed": passed,
        "not_passed": [row["property"] for row in rows if row["verdict"] != "PASS"],
        "verdict": "CONTINUITY_MATRIX_COMPLETE" if not missing else "CONTINUITY_MATRIX_INCOMPLETE",
        "reading": (
            "no row passes because the design intends it: each one names either a rehearsal step "
            "or a live reading, and the rows that could not be exercised say so"
        ),
        "hypothetical": True,
        "order_sent": False,
    }
