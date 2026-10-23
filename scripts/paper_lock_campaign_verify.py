"""paper_lock_campaign_verify — a second opinion on the repeated-crash campaign.

``BUILDER != VERIFIER``. This script did not produce the campaign, imports none of its
code, and never reads ``CAMPAIGN.json``'s verdict. It reconstructs the sequence of crashes
and recoveries from the artefacts alone:

* the chained ``STREAM.jsonl`` (re-hashed with the published rule, line by line);
* each iteration's ``POST_CRASH.json`` (whose ``rows_at_crash`` boundary is *checked*, not
  trusted: the recomputed head of that prefix must equal the recorded head);
* each iteration's ``RECOVERY.json``, ``LIVE_OWNER.json``, ``STALE_OWNER.json`` and, where
  present, ``CONCURRENCY.json``;
* the cycle directories and their ledgers;
* the fence files and the lock files that remain now.

It is also required to fail. Every negative control is applied to a **copy** of the real
campaign and the targeted check must turn ``False``. A mutation that does not actually
change the scenario is reported ``invalid`` and retried with another witness; it is never
counted as a detection. ``false_success`` counts mutations that *did* change the scenario
and were still judged PASS: it must be zero.

Usage::

    python scripts/paper_lock_campaign_verify.py --campaign reports/.../campaign
"""

from __future__ import annotations

import argparse
import hashlib
import itertools
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
if str(REPO / "src") not in sys.path:
    sys.path.insert(0, str(REPO / "src"))

from trading_bot.ops.session_status import session_status  # noqa: E402
from trading_bot.ops.single_writer import SingleWriter, diagnose_lock  # noqa: E402
from trading_bot.vision.ledger import GENESIS, line_hash, read_entries, verify_chain  # noqa: E402

ABANDONED_REASONS = {"OWNER_PROCESS_DEAD", "PID_REUSED"}
GOOD_FINAL_STATES = {"RECOVERED", "READY"}
MIN_RECOVERIES = 5


# ----------------------------------------------------------------------- helpers


def read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def sha256(path: Path) -> str | None:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return None


def iteration_dirs(campaign: Path) -> list[Path]:
    return sorted(
        item
        for item in (campaign / "iterations").glob("iteration-*")
        if item.is_dir() and item.name.split("-")[-1].isdigit()
    )


def iteration_number(directory: Path) -> int:
    return int(directory.name.split("-")[-1])


def _lock_name(path: Any) -> str:
    return str(path).replace("\\", "/").rsplit("/", 1)[-1]


def stream_rows(path: Path) -> list[dict[str, Any]]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def recompute_prefix(rows: list[dict[str, Any]], count: int) -> dict[str, Any]:
    """Re-derive the chain for the first ``count`` rows, independently of the producer."""

    if count <= 0 or count > len(rows):
        return {"ok": False, "reason": "NO_SUCH_PREFIX"}
    prev = GENESIS
    for index, row in enumerate(rows[:count], start=1):
        if int(row.get("seq", -1)) != index:
            return {"ok": False, "reason": f"SEQ_{index}"}
        if str(row.get("prev_sha256")) != prev:
            return {"ok": False, "reason": f"LINK_{index}"}
        if line_hash(index, prev, row["entry"]) != str(row.get("sha256")):
            return {"ok": False, "reason": f"SHA_{index}"}
        prev = str(row["sha256"])
    return {"ok": True, "head_sha256": prev, "lines": count}


def locks_now(session: Path) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []
    for path in sorted(session.rglob("*.lock")):
        record = SingleWriter(path, purpose="campaign-verifier").read()
        found.append(
            {
                "path": path.relative_to(session).as_posix(),
                "record": record,
                "state": diagnose_lock(record)["state"],
            }
        )
    return found


def fence_files(session: Path) -> dict[str, int | None]:
    out: dict[str, int | None] = {}
    for path in sorted(session.rglob("*.lock.fence")):
        try:
            out[path.relative_to(session).as_posix()] = int(
                path.read_text(encoding="utf-8").strip() or 0
            )
        except (OSError, ValueError):
            out[path.relative_to(session).as_posix()] = None
    return out


# ------------------------------------------------------------------------- judge


def judge(campaign: Path) -> dict[str, Any]:
    """Re-derive every claim of the campaign from its artefacts."""

    session = campaign / "session"
    stream = session / "STREAM.jsonl"
    rows = read_entries(stream)
    chain = verify_chain(stream)
    seqs = [int(row["seq"]) for row in rows]

    starts = [
        {"seq": int(row["seq"]), "entry": row["entry"]}
        for row in rows
        if row["entry"].get("kind") == "SESSION_START"
    ]
    reclaims = [
        {"seq": int(row["seq"]), "entry": row["entry"]}
        for row in rows
        if row["entry"].get("kind") == "LOCK_RECLAIMED"
    ]
    cycles = [
        {"seq": int(row["seq"]), "entry": row["entry"]}
        for row in rows
        if row["entry"].get("kind") == "CYCLE"
    ]
    cycle_numbers = [
        int(item["entry"]["cycle"]) for item in cycles if item["entry"].get("cycle") is not None
    ]
    directories = sorted(
        int(item.name.split("-")[-1])
        for item in (session / "cycles").glob("cycle-*")
        if item.name.split("-")[-1].isdigit()
    )

    #: Each iteration's recovery window ends at the next crash boundary, which the next
    #: iteration's POST_CRASH records. The boundary itself is verified per iteration.
    boundaries = {
        iteration_number(directory): int(
            (read_json(directory / "POST_CRASH.json") or {}).get("rows_at_crash") or 0
        )
        for directory in iteration_dirs(campaign)
    }

    iterations: list[dict[str, Any]] = []
    facts: dict[str, Any] = {
        "iterations": [],
        "rows": len(rows),
        "starts": len(starts),
        "locks_now": sorted(left["path"] for left in locks_now(session)),
    }
    for directory in iteration_dirs(campaign):
        index = iteration_number(directory)
        post = read_json(directory / "POST_CRASH.json")
        recovery = read_json(directory / "RECOVERY.json")
        live = read_json(directory / "LIVE_OWNER.json")
        stale = read_json(directory / "STALE_OWNER.json")
        race = read_json(directory / "CONCURRENCY.json")

        crash_rows = int(post.get("rows_at_crash") or 0)
        prefix = recompute_prefix(rows, crash_rows)
        recorded_head = (post.get("chain_at_crash") or {}).get("head_sha256")
        #: The window is inclusive of the next crash row: that row is the last cycle the
        #: resume of *this* iteration produced, and the first thing the next crash is
        #: anchored on. Excluding it would misattribute every recovery's progress.
        end = boundaries.get(index + 1) or len(rows)

        recomputed: list[dict[str, Any]] = []
        for item in post.get("leftovers") or []:
            record = item.get("record")
            verdict = diagnose_lock(record)
            recomputed.append(
                {
                    "path": str(item.get("path")),
                    "state": verdict["state"],
                    "reason": verdict["reason"],
                    "pid": (record or {}).get("pid"),
                    "process_start_ms": (record or {}).get("process_start_ms"),
                    "token": (record or {}).get("token"),
                    "fence": (record or {}).get("fence"),
                    "recorded_state": item.get("state"),
                    "recorded_reason": item.get("reason"),
                }
            )

        own_reclaims = [item for item in reclaims if crash_rows < item["seq"] <= end]
        own_cycles = [item for item in cycles if crash_rows < item["seq"] <= end]
        start = next((item for item in starts if item["seq"] > crash_rows), None)

        #: A lock whose abandoned owner was taken over by the concurrency probe is already
        #: free when the session resumes, so the session correctly records nothing about it.
        #: The probe's own takeover is the evidence for that path, and it is held to the same
        #: standard: exactly one winner, a higher fence, and it must have released.
        race_paths: list[str] = []
        race_recovered = False
        if race:
            winners = [
                item for item in (race.get("outcomes") or []) if item.get("outcome") == "RECLAIMED"
            ]
            if len(winners) == 1 and winners[0].get("released") is True:
                previous = winners[0].get("previous_owner") or {}
                if int(winners[0].get("fence") or 0) > int(previous.get("fence") or 0):
                    race_recovered = True
                    race_paths = [str(race.get("path") or "").replace("\\", "/").split("/")[-1]]

        ownership = {"ok": True, "reasons_proved": True, "fences_advance": True}
        covered: set[str] = set()
        for item in own_reclaims:
            for lock in item["entry"].get("locks") or []:
                name = str(lock.get("lock"))
                covered.add(name)
                if lock.get("reason") not in ABANDONED_REASONS:
                    ownership["reasons_proved"] = False
                match = next(
                    (left for left in recomputed if left["path"].endswith(name)),
                    None,
                )
                if match is None or match["pid"] != lock.get("pid"):
                    ownership["ok"] = False
                    continue
                if (
                    isinstance(lock.get("fence"), int)
                    and isinstance(match["fence"], int)
                    and int(lock["fence"]) <= int(match["fence"])
                ):
                    ownership["fences_advance"] = False

        iterations.append(
            {
                "iteration": index,
                "crash_site": post.get("crash_site"),
                "crash_rows": crash_rows,
                "prefix_ok": bool(prefix.get("ok")),
                "prefix_head_matches": str(prefix.get("head_sha256")) == str(recorded_head),
                "leftovers": recomputed,
                "leftover_paths": sorted({left["path"] for left in recomputed}),
                "reclaimed_paths": sorted(covered),
                "race_recovered_paths": race_paths,
                "race_recovered": race_recovered,
                "resume_start_seq": start["seq"] if start else None,
                "resume_resumed_flag": (
                    (start["entry"].get("provenance") or {}).get("resumed") if start else None
                ),
                "resume_exit_code": recovery.get("exit_code"),
                "new_cycles_after_resume": len(own_cycles),
                "locks_after_recorded": len(recovery.get("locks_after") or []),
                "live_owner_outcome": (live.get("stream") or {}).get("outcome"),
                "live_owner_unchanged": (live.get("stream") or {}).get("unchanged"),
                "harness_locks_refused": bool(live.get("cycles"))
                and all(
                    item.get("outcome") == "REFUSED" and item.get("unchanged") is True
                    for item in (live.get("cycles") or [])
                    if item.get("outcome") != "NOT_HELD"
                )
                and any(
                    item.get("outcome") == "REFUSED" for item in (live.get("cycles") or [])
                ),
                "ownership": ownership,
                "stale_owner": stale or None,
                "race": race or None,
            }
        )
        facts["iterations"].append(
            {
                "iteration": index,
                "crash_site": post.get("crash_site"),
                "crash_rows": crash_rows,
                "prefix_head": str(prefix.get("head_sha256")),
                "leftover_owners": sorted(
                    f"{left['path']}:{left['pid']}:{left['token']}" for left in recomputed
                ),
                "reclaimed_paths": sorted(covered),
                "reclaim_fences": sorted(
                    f"{lock.get('lock')}:{lock.get('fence')}"
                    for item in own_reclaims
                    for lock in item["entry"].get("locks") or []
                ),
                "reclaim_owners": sorted(
                    f"{lock.get('lock')}:{lock.get('pid')}"
                    for item in own_reclaims
                    for lock in item["entry"].get("locks") or []
                ),
                "exit": recovery.get("exit_code"),
                "new_cycles": len(own_cycles),
            }
        )

    interrupted = [number for number in directories if number not in cycle_numbers]
    gaps_ok = True
    for left, right in itertools.pairwise(cycle_numbers):
        if right == left + 1:
            continue
        if right == left + 2 and (left + 1) in interrupted:
            continue
        gaps_ok = False
    persisted_ledgers = {
        number: verify_chain(session / "cycles" / f"cycle-{number:04d}" / "ledger.jsonl")
        for number in cycle_numbers
    }
    remaining = locks_now(session)
    final = session_status(session)
    run_meta = read_json(session / "RUN_META.json")
    raced = [item for item in iterations if item["race"]]
    stale_items = [item for item in iterations if item["stale_owner"]]

    checks = {
        "stream_chain_intact": bool(chain.get("ok")),
        "seq_continuous": bool(seqs) and seqs == list(range(1, len(seqs) + 1)),
        "iterations_contiguous": [item["iteration"] for item in iterations]
        == list(range(1, len(iterations) + 1)),
        "at_least_five_recoveries": len(
            [item for item in iterations if item["resume_exit_code"] == 0]
        )
        >= MIN_RECOVERIES,
        "both_crash_sites_covered": bool(
            [item for item in iterations if item["crash_site"] == "BEFORE_CYCLE"]
        )
        and len([item for item in iterations if item["crash_site"] == "AFTER_CYCLE"]) >= 4,
        "crash_boundaries_match_recorded_chains": all(
            item["prefix_ok"] and item["prefix_head_matches"] for item in iterations
        ),
        "every_crash_left_locks": all(item["leftovers"] for item in iterations),
        "all_leftovers_proved_abandoned": all(
            left["state"] == "ABANDONED" and left["reason"] in ABANDONED_REASONS
            for item in iterations
            for left in item["leftovers"]
        ),
        "leftover_state_matches_recomputed_verdict": all(
            left["state"] == left["recorded_state"] for item in iterations for left in item["leftovers"]
        ),
        "one_owner_per_path_per_crash": all(
            len({left["path"] for left in item["leftovers"]}) == len(item["leftovers"])
            for item in iterations
        ),
        #: The lock record names the lock (``BTCUSDT.jsonl.lock``); the audit walks the
        #: directory (``market-1m/BTCUSDT.jsonl.lock``). Compare the identity, not the walk.
        "every_recovery_is_reclaimed": all(
            {_lock_name(path) for path in item["leftover_paths"]}
            <= {_lock_name(path) for path in item["reclaimed_paths"]}
            | {_lock_name(path) for path in item["race_recovered_paths"]}
            for item in iterations
        ),
        "reclaim_reason_is_a_proof": all(item["ownership"]["reasons_proved"] for item in iterations),
        "reclaim_takes_over_the_crashed_owner": all(item["ownership"]["ok"] for item in iterations),
        "reclaim_fence_advances": all(item["ownership"]["fences_advance"] for item in iterations),
        #: The resumed session's SESSION_START is the *next* row written after the crash:
        #: nothing else can be appended while no writer holds the lock. That anchor is what
        #: makes "a resume happened" checkable instead of merely present somewhere later.
        "every_resume_continued_the_session": all(
            item["resume_start_seq"] == item["crash_rows"] + 1
            and item["resume_resumed_flag"] is True
            for item in iterations
        ),
        "every_resume_made_progress": all(
            item["new_cycles_after_resume"] >= 1 for item in iterations
        ),
        "resume_exited_zero": all(item["resume_exit_code"] == 0 for item in iterations),
        "cycle_numbers_unique": len(cycle_numbers) == len(set(cycle_numbers)),
        "cycle_numbers_ordered": cycle_numbers == sorted(cycle_numbers),
        "cycle_gaps_are_interrupted_cycles": gaps_ok,
        "persisted_cycle_ledgers_intact": bool(persisted_ledgers)
        and all(bool(item.get("ok")) for item in persisted_ledgers.values()),
        #: One process holds every lock of an epoch; the *token* is per lock instance, which
        #: is exactly why identity is (pid, process start) and not the token.
        "one_owner_per_iteration": all(
            len({(left["pid"], left["process_start_ms"]) for left in item["leftovers"]}) == 1
            and len(item["leftovers"]) > 0
            for item in iterations
        ),
        "owner_identity_never_repeats": len(
            {
                (left["pid"], left["process_start_ms"])
                for item in iterations
                for left in item["leftovers"]
            }
        )
        == len(iterations),
        "live_owner_was_refused": all(
            item["live_owner_outcome"] == "REFUSED"
            and item["live_owner_unchanged"] is True
            and item["harness_locks_refused"]
            for item in iterations
        ),
        "stale_owner_was_refused": bool(stale_items)
        and all(
            bool((item["stale_owner"].get("lock_lost") or {}).get("raised"))
            and item["stale_owner"].get("release_refused") is True
            and item["stale_owner"].get("lock_still_present") is True
            and str(item["stale_owner"].get("old_token"))
            != str((item["stale_owner"].get("current") or {}).get("token"))
            and int(item["stale_owner"].get("old_fence") or 0)
            < int((item["stale_owner"].get("current") or {}).get("fence") or 0)
            for item in stale_items
        ),
        "concurrent_reclaim_has_one_winner": bool(raced)
        and all(
            item["race_recovered"] is True
            and len(item["race"].get("outcomes") or []) == int(item["race"].get("racers") or 0)
            and sum(
                1
                for outcome in item["race"].get("outcomes") or []
                if outcome.get("outcome") == "RECLAIMED"
            )
            == 1
            and all(
                outcome.get("outcome") == "REFUSED"
                for outcome in item["race"].get("outcomes") or []
                if outcome.get("outcome") != "RECLAIMED"
            )
            for item in raced
        ),
        "no_lock_remaining_now": not remaining,
        "no_lock_after_any_resume": all(item["locks_after_recorded"] == 0 for item in iterations),
        "final_state_not_failed": final["state"] in GOOD_FINAL_STATES,
        "no_live_orders": all(int(row["entry"].get("live_orders", 0) or 0) == 0 for row in rows)
        and run_meta.get("live_enabled") is False
        and str(run_meta.get("mode")) == "PAPER",
        "runtime_identity_stable": len(
            {str((item["entry"].get("provenance") or {}).get("pinned_identity")) for item in starts}
        )
        == 1
        and len({str(item["entry"].get("runtime_sha256")) for item in starts}) == 1,
        "resume_flags_are_false_then_true": bool(starts)
        and (starts[0]["entry"].get("provenance") or {}).get("resumed") is False
        and all(
            (item["entry"].get("provenance") or {}).get("resumed") is True for item in starts[1:]
        ),
    }

    return {
        "checks": checks,
        "iterations": iterations,
        "facts": facts,
        "chain": chain,
        "cycles": {
            "numbers": cycle_numbers,
            "directories": directories,
            "interrupted": interrupted,
            "fences": fence_files(session),
            "ledgers": {f"cycle-{number:04d}": value for number, value in persisted_ledgers.items()},
        },
        "final_status": final,
        "counts": {
            "rows": len(rows),
            "starts": len(starts),
            "cycles": len(cycles),
            "reclaim_rows": len(reclaims),
            "iterations": len(iterations),
        },
        "verdict": "PASS" if all(checks.values()) else "FAIL",
    }


# --------------------------------------------------------------------- mutations


def rechain(stream: Path) -> None:
    """Rewrite seq/sha so the mutated stream is *validly* chained.

    The point of every mutation is to leave the hash chain intact and break the claim
    instead: a verifier that only re-hashes would pass every one of these.
    """

    rows = stream_rows(stream)
    prev = GENESIS
    out = []
    for index, row in enumerate(rows, start=1):
        digest = line_hash(index, prev, row["entry"])
        out.append(
            json.dumps(
                {"seq": index, "prev_sha256": prev, "entry": row["entry"], "sha256": digest},
                sort_keys=True,
            )
        )
        prev = digest
    stream.write_text("\n".join(out) + "\n", encoding="utf-8")


def copy_campaign(source: Path) -> Path:
    target = Path(tempfile.mkdtemp(prefix="paper-lock-campaign-")) / "campaign"
    shutil.copytree(source, target)
    return target


def mutations(source: Path) -> list[dict[str, Any]]:
    """Each mutation names the check it must turn ``False`` and a list of witnesses."""

    base_facts = judge(source)["facts"]
    results: list[dict[str, Any]] = []

    def apply(name: str, target: str, builder, witnesses: list[Any], description: str) -> None:
        attempts: list[str] = []
        for witness in witnesses:
            work = copy_campaign(source)
            try:
                detail = builder(work, witness)
                if not detail:
                    attempts.append(f"witness {witness!r} does not exist in this evidence")
                    continue
                verdict = judge(work)
                changed = verdict["facts"] != base_facts
                detected = verdict["checks"].get(target) is False
                results.append(
                    {
                        "mutation": name,
                        "description": description,
                        "target_check": target,
                        "witness": witness,
                        "detail": detail,
                        "changed_the_scenario": changed,
                        "detected": detected,
                        "invalid": not changed,
                        "false_checks": sorted(
                            key for key, value in verdict["checks"].items() if value is False
                        ),
                    }
                )
                if changed:
                    return
                attempts.append(f"witness {witness!r} left the scenario unchanged")
            finally:
                shutil.rmtree(work.parent, ignore_errors=True)
        results.append(
            {
                "mutation": name,
                "description": description,
                "target_check": target,
                "witness": None,
                "detail": "; ".join(attempts) or "no witness",
                "changed_the_scenario": False,
                "detected": False,
                "invalid": True,
                "false_checks": [],
            }
        )

    stream = source / "session" / "STREAM.jsonl"
    rows = stream_rows(stream)
    cycle_positions = [
        index for index, row in enumerate(rows) if row["entry"].get("kind") == "CYCLE"
    ]
    reclaim_positions = [
        index for index, row in enumerate(rows) if row["entry"].get("kind") == "LOCK_RECLAIMED"
    ]
    start_positions = [
        index
        for index, row in enumerate(rows)
        if row["entry"].get("kind") == "SESSION_START"
        and (row["entry"].get("provenance") or {}).get("resumed") is True
    ]

    def duplicate_cycle(work: Path, witness: int) -> str:
        target = work / "session" / "STREAM.jsonl"
        mutated = stream_rows(target)
        mutated.insert(witness + 1, json.loads(json.dumps(mutated[witness])))
        target.write_text(
            "\n".join(json.dumps(row, sort_keys=True) for row in mutated) + "\n", encoding="utf-8"
        )
        rechain(target)
        return f"duplicated stream row {witness + 1} (a CYCLE) and re-chained the file"

    apply(
        "duplicated_cycle_with_valid_chain",
        "cycle_numbers_unique",
        duplicate_cycle,
        cycle_positions[:3],
        "the same cycle appears twice and every hash is recomputed: only numbering can catch it",
    )

    def drop_reclaim(work: Path, witness: int) -> str:
        target = work / "session" / "STREAM.jsonl"
        mutated = stream_rows(target)
        del mutated[witness]
        target.write_text(
            "\n".join(json.dumps(row, sort_keys=True) for row in mutated) + "\n", encoding="utf-8"
        )
        rechain(target)
        return f"removed LOCK_RECLAIMED at row {witness + 1} and re-chained the rest"

    apply(
        "reclaim_row_removed",
        "every_recovery_is_reclaimed",
        drop_reclaim,
        reclaim_positions[:2],
        "a resume whose reclaim is not on the record proves nothing about the abandoned lock",
    )

    def lower_fence(work: Path, witness: tuple[int, int]) -> str:
        target = work / "session" / "STREAM.jsonl"
        mutated = stream_rows(target)
        locks = mutated[witness[0]]["entry"].get("locks") or []
        if witness[1] >= len(locks):
            return ""
        locks[witness[1]]["fence"] = max(0, int(locks[witness[1]].get("fence") or 0) - 1)
        target.write_text(
            "\n".join(json.dumps(row, sort_keys=True) for row in mutated) + "\n", encoding="utf-8"
        )
        rechain(target)
        return f"lowered the fence of reclaim row {witness[0] + 1}, lock {witness[1]}"

    fence_witnesses = [
        (index, lock_index)
        for index in reclaim_positions
        for lock_index, _ in enumerate(rows[index]["entry"].get("locks") or [])
    ]
    apply(
        "reclaim_fence_does_not_advance",
        "reclaim_fence_advances",
        lower_fence,
        fence_witnesses[:3],
        "a takeover whose fence did not advance past the old record did not dispossess it",
    )

    def drop_resume_start(work: Path, witness: int) -> str:
        target = work / "session" / "STREAM.jsonl"
        mutated = stream_rows(target)
        del mutated[witness]
        target.write_text(
            "\n".join(json.dumps(row, sort_keys=True) for row in mutated) + "\n", encoding="utf-8"
        )
        rechain(target)
        return f"removed the resumed SESSION_START at row {witness + 1}"

    apply(
        "resume_start_removed",
        "every_resume_continued_the_session",
        drop_resume_start,
        start_positions[:2],
        "without the resumed SESSION_START there is no evidence the crash was continued",
    )

    def leave_a_lock(work: Path, witness: str) -> str:
        lock = work / "session" / "STREAM.jsonl.lock"
        lock.write_text(
            json.dumps(
                {
                    "schema_version": "TAP_SINGLE_WRITER_LOCK_V1",
                    "purpose": "verifier",
                    "host": socket.gethostname(),
                    "pid": os.getpid(),
                    "process_start_ms": None,
                    "token": "verifier" * 4,
                    "fence": 9999,
                }
            ),
            encoding="utf-8",
        )
        return "planted a residual lock whose owner is this live process"

    apply(
        "residual_lock_presented_as_recovered",
        "no_lock_remaining_now",
        leave_a_lock,
        ["plant"],
        "a leftover lock must fail the campaign however healthy the stream looks",
    )

    def make_leftover_live(work: Path, witness: tuple[int, int]) -> str:
        directory = iteration_dirs(work)[witness[0]]
        path = directory / "POST_CRASH.json"
        payload = read_json(path)
        leftovers = payload.get("leftovers") or []
        if witness[1] >= len(leftovers):
            return ""
        leftovers[witness[1]]["record"]["pid"] = os.getpid()
        leftovers[witness[1]]["record"]["host"] = socket.gethostname()
        leftovers[witness[1]]["record"]["process_start_ms"] = None
        path.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
        return f"iteration {witness[0] + 1} leftover {witness[1]} now names this live pid"

    leftover_witnesses = [
        (index, position)
        for index, directory in enumerate(iteration_dirs(source))
        for position, _ in enumerate(read_json(directory / "POST_CRASH.json").get("leftovers") or [])
    ]
    apply(
        "leftover_owner_is_alive",
        "all_leftovers_proved_abandoned",
        make_leftover_live,
        leftover_witnesses[:3],
        "a lock whose owner is alive must never be counted as abandoned",
    )

    def fail_resume(work: Path, witness: int) -> str:
        path = iteration_dirs(work)[witness] / "RECOVERY.json"
        payload = read_json(path)
        if not payload:
            return ""
        payload["exit_code"] = 124
        path.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
        return f"iteration {witness + 1} resume exit set to 124"

    apply(
        "resume_did_not_exit_cleanly",
        "resume_exited_zero",
        fail_resume,
        list(range(len(iteration_dirs(source))))[:2],
        "a timed-out resume is not a recovery",
    )

    def two_owners(work: Path, witness: int) -> str:
        path = iteration_dirs(work)[witness] / "POST_CRASH.json"
        payload = read_json(path)
        leftovers = payload.get("leftovers") or []
        if not leftovers:
            return ""
        clone = json.loads(json.dumps(leftovers[0]))
        clone["record"]["pid"] = int(clone["record"].get("pid") or 0) + 4
        clone["record"]["token"] = "other-owner" * 4
        leftovers.append(clone)
        path.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
        return f"iteration {witness + 1} now names two owners for {clone['path']}"

    apply(
        "two_writers_claim_one_lock",
        "one_owner_per_path_per_crash",
        two_owners,
        list(range(len(iteration_dirs(source))))[:2],
        "two owners for one path is the state a single writer exists to forbid",
    )

    def wrong_owner(work: Path, witness: int) -> str:
        target = work / "session" / "STREAM.jsonl"
        mutated = stream_rows(target)
        locks = mutated[witness]["entry"].get("locks") or []
        if not locks:
            return ""
        locks[0]["pid"] = int(locks[0].get("pid") or 0) + 4
        target.write_text(
            "\n".join(json.dumps(row, sort_keys=True) for row in mutated) + "\n", encoding="utf-8"
        )
        rechain(target)
        return f"reclaim row {witness + 1} names a pid that owned nothing"

    apply(
        "reclaim_names_the_wrong_owner",
        "reclaim_takes_over_the_crashed_owner",
        wrong_owner,
        reclaim_positions[:2],
        "a reclaim of a different process would leave the real owner unreclaimed",
    )

    return results


def artifacts(campaign: Path) -> dict[str, str | None]:
    files: list[Path] = [campaign / "session" / "STREAM.jsonl", campaign / "CAMPAIGN.json"]
    files.extend(sorted((campaign / "iterations").glob("iteration-*/*.json")))
    files.extend(sorted((campaign / "session").rglob("*.lock.fence")))
    return {path.relative_to(campaign).as_posix(): sha256(path) for path in files if path.is_file()}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Independent verification of the lock campaign")
    parser.add_argument("--campaign", required=True)
    parser.add_argument("--out", default=None)
    parser.add_argument("--skip-mutations", action="store_true")
    args = parser.parse_args(argv)

    campaign = Path(args.campaign)
    verdict = judge(campaign)
    mutants = [] if args.skip_mutations else mutations(campaign)
    invalid = [item for item in mutants if item["invalid"]]
    undetected = [item for item in mutants if not item["invalid"] and not item["detected"]]
    payload = {
        "schema_version": "TAP_PAPER_LOCK_CAMPAIGN_VERIFICATION_V1",
        "campaign": str(campaign),
        "builder": "scripts/paper_lock_campaign.py",
        "verifier": "scripts/paper_lock_campaign_verify.py",
        "verifier_commit": subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=REPO, capture_output=True, text=True, check=False
        ).stdout.strip(),
        "artifacts": artifacts(campaign),
        "judgement": {
            "verdict": verdict["verdict"],
            "checks": verdict["checks"],
            "counts": verdict["counts"],
            "cycles": verdict["cycles"],
            "final_state": verdict["final_status"]["state"],
            "iterations": [
                {
                    key: item[key]
                    for key in (
                        "iteration",
                        "crash_site",
                        "crash_rows",
                        "prefix_ok",
                        "prefix_head_matches",
                        "resume_exit_code",
                        "new_cycles_after_resume",
                        "live_owner_outcome",
                        "live_owner_unchanged",
                        "harness_locks_refused",
                        "reclaimed_paths",
                        "leftover_paths",
                        "ownership",
                    )
                }
                for item in verdict["iterations"]
            ],
        },
        "adversarial": mutants,
        "invalid_mutations": [item["mutation"] for item in invalid],
        "undetected_mutations": [item["mutation"] for item in undetected],
        "false_success": len(undetected),
        "verdict": (
            "PASS"
            if verdict["verdict"] == "PASS" and mutants and not undetected and not invalid
            else "FAIL"
        ),
    }
    out = Path(args.out) if args.out else campaign / "VERIFICATION.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"verdict": payload["verdict"], "checks": verdict["checks"]}, indent=2))
    print(
        json.dumps(
            {
                "adversarial": [
                    {key: item[key] for key in ("mutation", "detected", "invalid", "target_check")}
                    for item in mutants
                ],
                "false_success": payload["false_success"],
            },
            indent=2,
        )
    )
    return 0 if payload["verdict"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
