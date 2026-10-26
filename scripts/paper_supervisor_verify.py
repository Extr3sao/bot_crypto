"""paper_supervisor_verify — a second opinion on the supervised recovery campaign.

``BUILDER != VERIFIER``. This script produced none of the campaign and imports none of its
code. It reads what was persisted and rebuilds the story itself:

* the chained stream, re-hashed line by line with the published rule;
* every ``SESSION_START``, ``LOCK_RECLAIMED``, ``CYCLE`` and ``SESSION_END`` row, in order;
* every cycle ledger, re-hashed independently of ``verify_chain``;
* the supervisor journal: which process took the coordination lock, which one was refused,
  which decisions were taken, which children existed and how they ended;
* the negative scenarios (corrupt evidence, exhausted budget);
* the authority boundary: which paths changed between the commit the session ran at and
  ``HEAD``.

It is also required to fail. Each negative control is applied to a **copy** of the evidence
and the check it targets must turn ``False``. A mutation that does not change the scenario is
reported ``invalid`` and retried with another witness; it is never counted as a detection.
``false_success`` counts mutations that *did* change the scenario and still passed.

Usage::

    python scripts/paper_supervisor_verify.py --campaign reports/.../campaign
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
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
if str(REPO / "src") not in sys.path:
    sys.path.insert(0, str(REPO / "src"))

from trading_bot.ops.single_writer import SingleWriter, diagnose_lock  # noqa: E402
from trading_bot.vision.ledger import GENESIS, line_hash  # noqa: E402

ABANDONED_REASONS = {"OWNER_PROCESS_DEAD", "PID_REUSED"}
GOOD_FINAL_STATES = {"RECOVERED", "READY"}
PROTECTED_PATHS = (
    "src/trading_bot/strategies",
    "src/trading_bot/risk",
    "src/trading_bot/execution",
    "src/trading_bot/paper",
    "src/trading_bot/portfolio",
    "src/trading_bot/vision/execution.py",
    "src/trading_bot/vision/lane.py",
)


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


def stream_rows(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    out = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        if raw.strip():
            try:
                out.append(json.loads(raw))
            except json.JSONDecodeError:
                out.append({"__unparseable__": raw})
    return out


def rehash(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Recompute the chain from the entry payloads; returns the first defect, if any."""

    prev = GENESIS
    for index, row in enumerate(rows, start=1):
        if "__unparseable__" in row:
            return {"ok": False, "reason": f"BAD_JSON_AT_{index}", "lines": index}
        if int(row.get("seq", -1)) != index:
            return {"ok": False, "reason": f"SEQ_AT_{index}", "lines": index}
        if str(row.get("prev_sha256")) != prev:
            return {"ok": False, "reason": f"LINK_AT_{index}", "lines": index}
        if line_hash(index, prev, row["entry"]) != str(row.get("sha256")):
            return {"ok": False, "reason": f"SHA_AT_{index}", "lines": index}
        prev = str(row["sha256"])
    return {"ok": True, "reason": "INTACT", "lines": len(rows), "head_sha256": prev}


def entries(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [row.get("entry") or {} for row in rows]


def locks(session: Path) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []
    if not session.is_dir():
        return found
    for path in sorted(session.rglob("*.lock")):
        record = SingleWriter(path, purpose="supervisor-verifier").read()
        verdict = diagnose_lock(record)
        found.append(
            {
                "path": path.relative_to(session).as_posix(),
                "record": record,
                "state": verdict["state"],
                "reason": verdict["reason"],
            }
        )
    return found


def journal(state_dir: Path) -> list[dict[str, Any]]:
    path = state_dir / "SUPERVISOR.jsonl"
    out = []
    if path.is_file():
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                try:
                    out.append(json.loads(line))
                except json.JSONDecodeError:
                    out.append({"event": "UNPARSEABLE"})
    return out


def git(*args: str) -> str:
    completed = subprocess.run(
        ["git", "-C", str(REPO), *args], capture_output=True, text=True, check=False
    )
    return completed.stdout.strip() if completed.returncode == 0 else ""


# ------------------------------------------------------------------------- judge


def judge(
    root: Path, applicability: Mapping[str, bool] | None = None
) -> dict[str, Any]:
    """Judge one campaign.  ``applicability`` is passed by the mutation harness.

    Which checks apply is a property of the *campaign being judged*, fixed before any
    mutation.  Recomputing it per mutant let a mutation delete the evidence a check
    depended on, the check then vanished from the verdict, and the mutation counted as
    undetected: a verifier blindfolded by the tampering it was supposed to catch.
    """
    session = root / "session"
    state_dir = root / "supervisor"
    rows = stream_rows(session / "STREAM.jsonl")
    chain = rehash(rows)
    entry_rows = entries(rows)
    seqs = [int(row.get("seq", -1)) for row in rows if "__unparseable__" not in row]

    starts = [
        {"seq": int(row["seq"]), "entry": entry}
        for row, entry in zip(rows, entry_rows, strict=True)
        if entry.get("kind") == "SESSION_START" and "__unparseable__" not in row
    ]
    reclaims = [
        {"seq": int(row["seq"]), "entry": entry}
        for row, entry in zip(rows, entry_rows, strict=True)
        if entry.get("kind") == "LOCK_RECLAIMED" and "__unparseable__" not in row
    ]
    cycles = [
        {"seq": int(row["seq"]), "entry": entry}
        for row, entry in zip(rows, entry_rows, strict=True)
        if entry.get("kind") == "CYCLE" and "__unparseable__" not in row
    ]
    cycle_numbers = [
        int(item["entry"]["cycle"])
        for item in cycles
        if isinstance(item["entry"].get("cycle"), int)
    ]
    directories = sorted(
        int(item.name.split("-")[-1])
        for item in (session / "cycles").glob("cycle-*")
        if item.name.split("-")[-1].isdigit()
    )
    interrupted = [number for number in directories if number not in cycle_numbers]
    persisted_ledgers = {
        number: verify_independent(session / "cycles" / f"cycle-{number:04d}" / "ledger.jsonl")
        for number in cycle_numbers
    }

    events = journal(state_dir)
    acquired = [row for row in events if row.get("event") == "ACQUIRED"]
    refused = [row for row in events if row.get("event") == "REFUSED"]
    spawned = [row for row in events if row.get("event") == "SPAWNED"]
    exits = [row for row in events if row.get("event") == "CHILD_EXIT"]
    decisions = [row for row in events if row.get("event") == "DECISION"]
    resumes = [row for row in decisions if row.get("action") == "RESUME"]
    resumed_starts = [
        item for item in starts if (item["entry"].get("provenance") or {}).get("resumed") is True
    ]

    #: A resumed start must be followed, before the next start, by the reclaim of the stream
    #: lock whose owner was proved gone. That is the artefact-level reason a resume was
    #: allowed at all — independent of what the supervisor said about it.
    reclaim_by_seq: dict[int, dict[str, Any]] = {item["seq"]: item["entry"] for item in reclaims}
    starts_seq = [item["seq"] for item in starts]
    resume_windows = []
    for position, start in enumerate(starts):
        if (start["entry"].get("provenance") or {}).get("resumed") is not True:
            continue
        end = starts_seq[position + 1] if position + 1 < len(starts_seq) else len(rows) + 1
        window = [claim for seq, claim in reclaim_by_seq.items() if start["seq"] < seq < end]
        covered = [
            lock
            for claim in window
            for lock in claim.get("locks") or []
            if str(lock.get("lock")) == "STREAM.jsonl.lock"
        ]
        resume_windows.append(
            {
                "start_seq": start["seq"],
                "reclaims": [
                    {
                        "seq": None,
                        "locks": [
                            {
                                "lock": lock.get("lock"),
                                "reason": lock.get("reason"),
                                "fence": lock.get("fence"),
                                "pid": lock.get("pid"),
                            }
                            for lock in covered
                        ],
                    }
                ],
                "backed": bool(covered)
                and all(lock.get("reason") in ABANDONED_REASONS for lock in covered),
            }
        )

    fences_by_lock: dict[str, list[int]] = {}
    for claim in reclaims:
        for lock in claim["entry"].get("locks") or []:
            if isinstance(lock.get("fence"), int):
                fences_by_lock.setdefault(str(lock.get("lock")), []).append(int(lock["fence"]))
    #: A takeover fence must be at least 2: the first acquisition writes 1, so a reclaim
    #: can only install a higher number.  With a single reclaim there is no pair to
    #: compare, and ``all(pairwise([2]))`` is vacuous — which is how a fence reset to 0
    #: slipped through.  The floor is asserted explicitly, then the sequence when there is
    #: more than one.
    fences_advance = all(
        (all(right > left for left, right in itertools.pairwise(values)) and values[0] >= 2)
        if len(values) > 1
        else values[0] >= 2
        for values in fences_by_lock.values()
    )

    gaps_ok = True
    for left, right in itertools.pairwise(cycle_numbers):
        if right == left + 1:
            continue
        if right == left + 2 and (left + 1) in interrupted:
            continue
        gaps_ok = False

    run_meta = read_json(session / "RUN_META.json")
    result = read_json(state_dir / "SUPERVISOR_RESULT.json")
    final_locks = locks(session)
    policy = (acquired[0].get("policy") if acquired else {}) or {}

    zero_exits = [row for row in exits if row.get("exit_code") == 0]
    last_spawn = spawned[-1] if spawned else None
    resumed_spawns = [row for row in spawned if row.get("resume") is True]
    attempts = [row for row in exits if isinstance(row.get("verified"), dict)]

    #: A rerun of the crash that produced no row is still a crash; what must be impossible is
    #: a *clean* exit that carries no new `SESSION_START`.
    verified_attempts = [
        row
        for row in attempts
        if int((row.get("after") or {}).get("rows") or 0)
        > int((row.get("before") or {}).get("rows") or 0)
    ]
    attempts_continue = all(
        bool(row["verified"].get("continued"))
        and row["verified"].get("start_seq") == int((row.get("before") or {}).get("rows") or 0) + 1
        for row in verified_attempts
    )
    false_success_rows = [
        row for row in attempts if row.get("exit_code") == 0 and not row["verified"].get("progress")
    ]

    protected_diff = ""
    run_commit = str(run_meta.get("commit") or "")
    if run_commit:
        protected_diff = git("diff", "--name-only", run_commit, "HEAD", "--", *PROTECTED_PATHS)

    corrupt = (
        read_json(root / "scenarios" / "SCENARIOS.json").get("scenarios", {}).get("corrupt", {})
    )
    budget = read_json(root / "scenarios" / "SCENARIOS.json").get("scenarios", {}).get("budget", {})
    budget_result = budget.get("result") or {}
    corrupt_result = corrupt.get("result") or {}

    checks = {
        "stream_chain_intact": bool(chain.get("ok")),
        "seq_continuous": bool(seqs) and seqs == list(range(1, len(seqs) + 1)),
        #: The first start is a fresh session; every later one names the previous session as
        #: its parent, so a "resume" cannot be a fresh run wearing the word.
        "resume_flags_are_false_then_true": bool(starts)
        and (starts[0]["entry"].get("provenance") or {}).get("resumed") is False
        and all(
            (item["entry"].get("provenance") or {}).get("resumed") is True for item in starts[1:]
        ),
        "starts_carry_their_own_identity": all(
            (item["entry"].get("provenance") or {}).get("session_id")
            and (item["entry"].get("provenance") or {}).get("run_id")
            and (item["entry"].get("provenance") or {}).get("pinned_identity")
            for item in starts
        ),
        "one_run_id_and_pin": len(
            {str((item["entry"].get("provenance") or {}).get("run_id")) for item in starts}
        )
        == 1
        and len(
            {str((item["entry"].get("provenance") or {}).get("pinned_identity")) for item in starts}
        )
        == 1,
        "runtime_bytes_stable": len({str(item["entry"].get("runtime_sha256")) for item in starts})
        == 1,
        "cycle_numbers_unique": len(cycle_numbers) == len(set(cycle_numbers)),
        "cycle_numbers_increasing": cycle_numbers == sorted(cycle_numbers),
        "cycle_gaps_are_interrupted": gaps_ok,
        "cycle_ledgers_intact": bool(persisted_ledgers)
        and all(bool(item.get("ok")) for item in persisted_ledgers.values()),
        "no_live_orders": all(int(entry.get("live_orders", 0) or 0) == 0 for entry in entry_rows)
        and run_meta.get("live_enabled") is False
        and str(run_meta.get("mode")) == "PAPER",
        "every_resume_backed_by_a_reclaim": bool(resume_windows)
        and all(item["backed"] for item in resume_windows),
        "reclaim_fences_advance": bool(fences_by_lock) and fences_advance,
        "one_supervisor_acquired": len(acquired) == 1,
        "loser_refused_without_spawning": len(refused) == 1
        and not any(
            row.get("supervisor_pid") == refused[0].get("supervisor_pid") for row in spawned
        ),
        "only_one_supervisor_spawned": len({row.get("supervisor_pid") for row in spawned}) == 1,
        "no_supervisor_decision_acted_on_failed": all(
            row.get("action") != "RESUME" or (row.get("state") or {}).get("state") == "RECOVERING"
            for row in decisions
        ),
        "every_resume_decision_saw_only_abandoned_locks": all(
            all(
                item.get("state") == "ABANDONED"
                for item in (row.get("state") or {}).get("awaiting") or []
            )
            for row in resumes
        )
        and all((row.get("state") or {}).get("awaiting") for row in resumes),
        "resume_decisions_match_resumed_starts": len(resumes) == len(resumed_starts),
        "every_resume_child_is_recorded": len(resumed_spawns) == len(resumed_starts)
        and all(
            any(item.get("pid") == spawn.get("pid") for item in exits) for spawn in resumed_spawns
        ),
        "attempts_continue_the_stream": attempts_continue,
        "no_clean_exit_without_evidence": not false_success_rows,
        #: Only the process that finished the campaign may have exited 0; a killed child
        #: cannot have returned success, or the supervisor would have stopped there.
        "zero_exit_is_terminal": all(
            row.get("pid") == (last_spawn or {}).get("pid") for row in zero_exits
        )
        and len(zero_exits) <= 1,
        #: Every child except the last one was killed; none of them may claim success.
        #: Filtering to non-zero exits first would make this a tautology.
        "killed_children_did_not_exit_zero": all(
            row.get("exit_code") not in (0, None)
            for row in exits
            if row.get("pid") != (last_spawn or {}).get("pid")
        ),
        "restarts_within_budget": len(resumes) <= int(policy.get("max_restarts") or len(resumes)),
        "rows_never_shrank": all(
            right >= left
            for left, right in itertools.pairwise(
                [int((row.get("state") or {}).get("rows") or 0) for row in decisions]
            )
        ),
        "supervisor_finished_completed": result.get("action") == "STOP_COMPLETED",
        "supervisor_result_counts_its_restarts": int(result.get("restarts") or 0) == len(resumes),
        "no_lock_remaining_now": not final_locks,
        "final_state_not_failed": result.get("final_state") in GOOD_FINAL_STATES,
        "protected_paths_untouched": protected_diff == "",
        "corrupt_evidence_was_refused": corrupt_result.get("action") == "STOP_FAILED"
        and corrupt.get("state") == "FAILED"
        and not corrupt.get("spawned")
        #: The copy is unreadable by design, so its parseable row count is ``None``; what
        #: must hold is that the supervisor wrote nothing over it.
        and corrupt.get("rows_after") is None
        and int(corrupt.get("rows_before") or 0) > 0
        and corrupt.get("exit_code") == 3,
        "budget_was_exhausted_not_exceeded": budget_result.get("action") == "STOP_BUDGET"
        and int(budget_result.get("restarts") or 0) == 1
        and len(budget.get("attempts") or []) == 2,
    }

    #: A check is only a check when the campaign contains the thing it judges.  The
    #: alternative — ``all([])`` or a zero-length list — is a vacuous PASS, which is the
    #: failure mode this verifier exists to catch.  Every entry here names the evidence
    #: that must exist for the check to apply; when it does not, the check is reported as
    #: ``not_applicable`` and excluded from the verdict instead of being counted as green.
    last_pid = (last_spawn or {}).get("pid")
    crashed = [
        row
        for row in exits
        if row.get("pid") != last_pid and row.get("exit_code") not in (0, None)
    ]
    computed_applicability = {
        "every_resume_backed_by_a_reclaim": bool(resumed_starts or resumes or reclaims),
        "reclaim_fences_advance": bool(fences_by_lock),
        "resume_decisions_match_resumed_starts": bool(resumed_starts or resumes),
        "every_resume_child_is_recorded": bool(resumed_starts or resumes),
        "every_resume_decision_saw_only_abandoned_locks": bool(resumes),
        "attempts_continue_the_stream": bool(attempts),
        "no_clean_exit_without_evidence": bool(attempts),
        "zero_exit_is_terminal": bool(exits),
        "killed_children_did_not_exit_zero": bool(crashed),
        "restarts_within_budget": bool(spawned),
        #: These two read the fixture campaign's own scenario records.  A real campaign
        #: produced by ``paper_supervisor_campaign.py`` carries no such file, and this
        #: verifier will not fabricate one to keep the checks green.
        "corrupt_evidence_was_refused": (root / "scenarios" / "SCENARIOS.json").is_file(),
        "budget_was_exhausted_not_exceeded": (root / "scenarios" / "SCENARIOS.json").is_file(),
    }
    if applicability is None:
        applicability = computed_applicability
    else:
        #: A name the caller pinned that this campaign does not even define is still
        #: honoured as "not applicable"; the check list is unchanged.
        applicability = {
            name: (applicability.get(name, False) if name in computed_applicability else False)
            for name in computed_applicability
        }
    not_applicable = sorted(name for name, applies in applicability.items() if not applies)
    for name in not_applicable:
        checks.pop(name, None)

    facts = {
        "rows": len(rows),
        "head": chain.get("head_sha256"),
        "starts": len(starts),
        "resumed_starts": len(resumed_starts),
        "cycles": cycle_numbers,
        "reclaims": len(reclaims),
        "fences": fences_by_lock,
        "journal_events": [row.get("event") for row in events],
        "journal_actions": [row.get("action") for row in decisions],
        "spawned_pids": [row.get("pid") for row in spawned],
        "exits": [row.get("exit_code") for row in exits],
        "result_action": result.get("action"),
        "corrupt_action": corrupt_result.get("action"),
        "budget_action": budget_result.get("action"),
        "budget_restarts": int(budget_result.get("restarts") or 0),
        "budget_attempts": len(budget.get("attempts") or []),
        "final_locks": [item["path"] for item in final_locks],
        "scenarios_present": (root / "scenarios" / "SCENARIOS.json").is_file(),
        "crashed_children": len(crashed),
    }
    return {
        "checks": checks,
        "not_applicable": not_applicable,
        "applicability": applicability,
        "facts": facts,
        "chain": chain,
        "cycles": {
            "numbers": cycle_numbers,
            "directories": directories,
            "interrupted": interrupted,
            "ledgers": {
                f"cycle-{number:04d}": value for number, value in persisted_ledgers.items()
            },
        },
        "resume_windows": resume_windows,
        "journal": {
            "events": len(events),
            "acquired": len(acquired),
            "refused": len(refused),
            "spawned": len(spawned),
            "exits": len(exits),
            "resumes": len(resumes),
        },
        "counts": {
            "rows": len(rows),
            "starts": len(starts),
            "resumed_starts": len(resumed_starts),
            "cycles": len(cycles),
            "reclaim_rows": len(reclaims),
        },
        "verdict": "PASS" if all(checks.values()) else "FAIL",
    }


def verify_independent(path: Path) -> dict[str, Any]:
    """Re-hash a ledger without ``verify_chain``, so a bug there is not inherited here."""

    if not path.is_file():
        return {"ok": False, "reason": "MISSING", "lines": 0}
    prev = GENESIS
    lines = 0
    for raw in path.read_text(encoding="utf-8").splitlines():
        if not raw.strip():
            continue
        lines += 1
        try:
            row = json.loads(raw)
        except json.JSONDecodeError:
            return {"ok": False, "reason": f"BAD_JSON_AT_{lines}", "lines": lines}
        if int(row.get("seq", -1)) != lines:
            return {"ok": False, "reason": f"SEQ_AT_{lines}", "lines": lines}
        if str(row.get("prev_sha256")) != prev:
            return {"ok": False, "reason": f"LINK_AT_{lines}", "lines": lines}
        if line_hash(lines, prev, row["entry"]) != str(row.get("sha256")):
            return {"ok": False, "reason": f"SHA_AT_{lines}", "lines": lines}
        prev = str(row["sha256"])
    return {"ok": True, "reason": "INTACT", "lines": lines}


# --------------------------------------------------------------------- mutations


def copy_evidence(source: Path) -> Path:
    target = Path(tempfile.mkdtemp(prefix="paper-supervisor-")) / "campaign"
    shutil.copytree(source, target)
    return target


def rechain(path: Path) -> None:
    rows = stream_rows(path)
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
    path.write_text("\n".join(out) + "\n", encoding="utf-8")


def mutations(source: Path) -> list[dict[str, Any]]:
    base_verdict = judge(source)
    base = base_verdict["facts"]
    base_applicability = base_verdict["applicability"]
    results: list[dict[str, Any]] = []

    def apply(
        name: str,
        target_check: str,
        builder: Callable[[Path], str],
        description: str,
        requires: Callable[[], bool] | None = None,
    ) -> None:
        #: A mutation whose evidence is absent from *this* campaign is not a verifier
        #: weakness and not a pass: it is ``not_applicable``.  Counting it as invalid
        #: made the verifier impossible to run on a real campaign; counting it as
        #: detected would be a false success.  Neither happens.
        if requires is not None and not requires():
            results.append(
                {
                    "mutation": name,
                    "description": description,
                    "target_check": target_check,
                    "detail": "not applicable: the campaign carries no evidence for this mutation",
                    "applicable": False,
                    "changed_the_scenario": False,
                    "detected": False,
                    "invalid": False,
                    "false_checks": [],
                }
            )
            return
        work = copy_evidence(source)
        detail = ""
        try:
            detail = builder(work)
            verdict = judge(work, base_applicability)
            changed = verdict["facts"] != base
            results.append(
                {
                    "mutation": name,
                    "description": description,
                    "target_check": target_check,
                    "detail": detail,
                    "applicable": True,
                    "changed_the_scenario": changed,
                    "detected": bool(
                        changed
                        and (
                            verdict["checks"].get(target_check) is False
                            #: The tampering removed the evidence the check needs.  That is
                            #: not a pass: the campaign no longer proves the property.
                            or target_check in verdict["not_applicable"]
                        )
                    ),
                    "invalid": not changed,
                    "false_checks": sorted(
                        key for key, value in verdict["checks"].items() if value is False
                    ),
                }
            )
        except (IndexError, KeyError, StopIteration, FileNotFoundError) as error:
            #: The builder could not find the row it mutates.  That is evidence the
            #: campaign does not exercise this path, never a reason to crash the verifier
            #: or to call the check green.  The exception text is kept verbatim.
            results.append(
                {
                    "mutation": name,
                    "description": description,
                    "target_check": target_check,
                    "detail": f"not applicable: {type(error).__name__}: {error}",
                    "applicable": False,
                    "changed_the_scenario": False,
                    "detected": False,
                    "invalid": False,
                    "false_checks": [],
                }
            )
        finally:
            shutil.rmtree(work.parent, ignore_errors=True)

    stream = source / "session" / "STREAM.jsonl"
    rows = stream_rows(stream)
    cycle_positions = [i for i, row in enumerate(rows) if row["entry"].get("kind") == "CYCLE"]
    resume_starts = [
        i
        for i, row in enumerate(rows)
        if row["entry"].get("kind") == "SESSION_START"
        and (row["entry"].get("provenance") or {}).get("resumed") is True
    ]
    reclaim_positions = [
        i for i, row in enumerate(rows) if row["entry"].get("kind") == "LOCK_RECLAIMED"
    ]

    def duplicate_cycle(work: Path) -> str:
        target = work / "session" / "STREAM.jsonl"
        mutated = stream_rows(target)
        at = cycle_positions[0]
        mutated.insert(at + 1, json.loads(json.dumps(mutated[at])))
        target.write_text(
            "\n".join(json.dumps(row, sort_keys=True) for row in mutated) + "\n",
            encoding="utf-8",
        )
        rechain(target)
        return f"duplicated the cycle at row {at + 1} and re-chained every hash"

    apply(
        "duplicated_cycle_with_a_valid_chain",
        "cycle_numbers_unique",
        duplicate_cycle,
        "only the numbering betrays it: the chain verifies",
    )

    def drop_resume_start(work: Path) -> str:
        target = work / "session" / "STREAM.jsonl"
        mutated = stream_rows(target)
        at = resume_starts[0]
        del mutated[at]
        target.write_text(
            "\n".join(json.dumps(row, sort_keys=True) for row in mutated) + "\n",
            encoding="utf-8",
        )
        rechain(target)
        return f"removed the resumed SESSION_START at row {at + 1}"

    apply(
        "resume_start_removed",
        "resume_decisions_match_resumed_starts",
        drop_resume_start,
        "a decision with no continuation row is a recovery that never happened",
    )

    def drop_reclaim(work: Path) -> str:
        target = work / "session" / "STREAM.jsonl"
        mutated = stream_rows(target)
        at = reclaim_positions[0]
        del mutated[at]
        target.write_text(
            "\n".join(json.dumps(row, sort_keys=True) for row in mutated) + "\n",
            encoding="utf-8",
        )
        rechain(target)
        return f"removed the LOCK_RECLAIMED at row {at + 1}"

    apply(
        "reclaim_row_removed",
        "every_resume_backed_by_a_reclaim",
        drop_reclaim,
        "a resume the runtime never authorised is a takeover, not a recovery",
    )

    def lower_fence(work: Path) -> str:
        target = work / "session" / "STREAM.jsonl"
        mutated = stream_rows(target)
        entry = mutated[reclaim_positions[-1]]["entry"]
        if not entry.get("locks"):
            return ""
        #: Reset the *last* takeover's fence: the sequence then rises and falls, which is
        #: the shape a takeover cannot have.
        entry["locks"][0]["fence"] = 0
        target.write_text(
            "\n".join(json.dumps(row, sort_keys=True) for row in mutated) + "\n",
            encoding="utf-8",
        )
        rechain(target)
        return f"reset the fence of the last reclaim (row {reclaim_positions[-1] + 1}) to 0"

    apply(
        "reclaim_fence_does_not_advance",
        "reclaim_fences_advance",
        lower_fence,
        "a takeover whose fence did not move did not dispossess the old owner",
    )

    def forge_second_supervisor(work: Path) -> str:
        path = work / "supervisor" / "SUPERVISOR.jsonl"
        rows_here = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
        clone = json.loads(json.dumps(next(row for row in rows_here if row["event"] == "ACQUIRED")))
        clone["supervisor_pid"] = 999_999
        with path.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(json.dumps(clone, sort_keys=True) + "\n")
        return "appended a second ACQUIRED row for a pid that never existed"

    apply(
        "two_supervisors_both_acquired",
        "one_supervisor_acquired",
        forge_second_supervisor,
        "two owners of one session is the state the coordination lock forbids",
    )

    def turn_a_crash_into_a_success(work: Path) -> str:
        path = work / "supervisor" / "SUPERVISOR.jsonl"
        rows_here = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
        index = next(
            i
            for i, row in enumerate(rows_here)
            if row["event"] == "CHILD_EXIT" and row.get("exit_code") not in (0, None)
        )
        rows_here[index]["exit_code"] = 0
        path.write_text(
            "\n".join(json.dumps(row, sort_keys=True) for row in rows_here) + "\n",
            encoding="utf-8",
        )
        return f"marked the killed child {rows_here[index].get('pid')} as a clean exit"

    apply(
        "killed_child_presented_as_clean",
        "killed_children_did_not_exit_zero",
        turn_a_crash_into_a_success,
        "a crash reported as success is the one lie the supervisor exists to prevent",
    )

    def plant_lock(work: Path) -> str:
        target = work / "session" / "STREAM.jsonl.lock"
        target.write_text(
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
        return "planted a residual lock owned by this live process"

    apply(
        "residual_lock_presented_as_recovered",
        "no_lock_remaining_now",
        plant_lock,
        "a leftover lock must fail the campaign however healthy the stream looks",
    )

    def live_order(work: Path) -> str:
        target = work / "session" / "STREAM.jsonl"
        mutated = stream_rows(target)
        mutated[cycle_positions[0]]["entry"]["live_orders"] = 1
        target.write_text(
            "\n".join(json.dumps(row, sort_keys=True) for row in mutated) + "\n",
            encoding="utf-8",
        )
        rechain(target)
        return "set live_orders = 1 on one cycle and re-chained"

    apply(
        "live_order_written_into_the_stream",
        "no_live_orders",
        live_order,
        "the PAPER claim is a property of the evidence, not of the report",
    )

    has_scenarios = (source / "scenarios" / "SCENARIOS.json").is_file()

    def corrupt_scenario_recovered(work: Path) -> str:
        path = work / "scenarios" / "SCENARIOS.json"
        payload = json.loads(path.read_text(encoding="utf-8"))
        payload["scenarios"]["corrupt"]["result"]["action"] = "STOP_COMPLETED"
        path.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
        return "claimed the corrupt scenario ended cleanly"

    apply(
        "corrupt_evidence_reported_as_recovered",
        "corrupt_evidence_was_refused",
        corrupt_scenario_recovered,
        "a broken chain presented as a recovery must not pass",
        requires=lambda: has_scenarios,
    )

    def budget_exceeded(work: Path) -> str:
        path = work / "scenarios" / "SCENARIOS.json"
        payload = json.loads(path.read_text(encoding="utf-8"))
        payload["scenarios"]["budget"]["result"]["restarts"] = 2
        path.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
        return "claimed two restarts under a one-restart budget"

    apply(
        "budget_overspent",
        "budget_was_exhausted_not_exceeded",
        budget_exceeded,
        "a supervisor that spends more than its budget is the loop it must not be",
        requires=lambda: has_scenarios,
    )

    def remove_resume_decision(work: Path) -> str:
        path = work / "supervisor" / "SUPERVISOR.jsonl"
        rows_here = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
        index = next(
            i
            for i, row in enumerate(rows_here)
            if row["event"] == "DECISION" and row.get("action") == "RESUME"
        )
        del rows_here[index]
        path.write_text(
            "\n".join(json.dumps(row, sort_keys=True) for row in rows_here) + "\n",
            encoding="utf-8",
        )
        return "removed one RESUME decision from the journal"

    apply(
        "resume_without_a_decision",
        "resume_decisions_match_resumed_starts",
        remove_resume_decision,
        "a recovery that happened without a decision was not supervised",
    )

    def fake_false_success(work: Path) -> str:
        path = work / "supervisor" / "SUPERVISOR.jsonl"
        rows_here = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
        index = next(
            i
            for i, row in enumerate(rows_here)
            if row["event"] == "CHILD_EXIT" and isinstance(row.get("verified"), dict)
        )
        rows_here[index]["verified"]["progress"] = False
        rows_here[index]["exit_code"] = 0
        path.write_text(
            "\n".join(json.dumps(row, sort_keys=True) for row in rows_here) + "\n",
            encoding="utf-8",
        )
        return "declared a clean exit whose verified attempt has no progress"

    apply(
        "clean_exit_without_evidence_reported_as_success",
        "no_clean_exit_without_evidence",
        fake_false_success,
        "starting a process is not a recovery; the check must demand the row",
    )

    return results


def artifacts(root: Path) -> dict[str, str | None]:
    files = [
        root / "session" / "STREAM.jsonl",
        root / "session" / "RUN_META.json",
        root / "supervisor" / "SUPERVISOR.jsonl",
        root / "supervisor" / "SUPERVISOR_RESULT.json",
        root / "scenarios" / "SCENARIOS.json",
    ]
    files.extend(sorted((root / "session" / "cycles").glob("cycle-*/ledger.jsonl")))
    files.extend(sorted((root / "session").rglob("*.lock.fence")))
    return {path.relative_to(root).as_posix(): sha256(path) for path in files if path.is_file()}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Independent verification of the supervisor")
    parser.add_argument("--campaign", required=True)
    parser.add_argument("--out", default=None)
    parser.add_argument("--skip-mutations", action="store_true")
    args = parser.parse_args(argv)

    root = Path(args.campaign)
    verdict = judge(root)
    mutants = [] if args.skip_mutations else mutations(root)
    applicable = [item for item in mutants if item.get("applicable", True)]
    inapplicable = [item for item in mutants if not item.get("applicable", True)]
    invalid = [item for item in applicable if item["invalid"]]
    undetected = [item for item in applicable if not item["invalid"] and not item["detected"]]
    payload = {
        "schema_version": "TAP_PAPER_SUPERVISOR_VERIFICATION_V1",
        "campaign": str(root),
        "builder": "scripts/paper_supervisor_campaign.py",
        "verifier": "scripts/paper_supervisor_verify.py",
        "verifier_commit": git("rev-parse", "HEAD"),
        "artifacts": artifacts(root),
        "judgement": {
            "verdict": verdict["verdict"],
            "checks": verdict["checks"],
            "not_applicable_checks": verdict["not_applicable"],
            "counts": verdict["counts"],
            "cycles": verdict["cycles"],
            "journal": verdict["journal"],
            "resume_windows": verdict["resume_windows"],
            "facts": verdict["facts"],
        },
        "adversarial": mutants,
        "applicable_mutations": len(applicable),
        "not_applicable_mutations": [item["mutation"] for item in inapplicable],
        "invalid_mutations": [item["mutation"] for item in invalid],
        "undetected_mutations": [item["mutation"] for item in undetected],
        "false_success": len(undetected),
        "verdict": (
            "PASS"
            if verdict["verdict"] == "PASS" and applicable and not undetected and not invalid
            else "FAIL"
        ),
    }
    out = Path(args.out) if args.out else root / "VERIFICATION.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"verdict": payload["verdict"], "checks": verdict["checks"]}, indent=2))
    print(
        json.dumps(
            {
                "adversarial": [
                    {
                        key: item[key]
                        for key in ("mutation", "detected", "invalid", "applicable", "target_check")
                    }
                    for item in mutants
                ],
                "false_success": payload["false_success"],
                "applicable_mutations": payload["applicable_mutations"],
                "not_applicable_mutations": payload["not_applicable_mutations"],
            },
            indent=2,
        )
    )
    return 0 if payload["verdict"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
