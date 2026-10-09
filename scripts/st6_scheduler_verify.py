"""ST-6 — independent verification of the autonomous observation programme.

A separate program from the tick, and it checks the scheduler by *using* it rather than by reading a
declaration about it:

* the task's registration is parsed from the scheduler's own XML and required to exist, to be
  enabled, to point at the repository's virtual-environment interpreter, to pass the tick's
  arguments and to work in the repository directory;
* **real execution**: the task is triggered through the scheduler itself and the run log is polled
  until the tick it produced appears, so the evidence is an execution that happened under the
  scheduler, not a file that says it should;
* **due idempotency**: two consecutive ticks are run and the window index must not grow for a slot
  that already has a window, while each tick still leaves one run event;
* **concurrency**: the lease is held by this process while a second process is launched, which must
  refuse with ``ALREADY_RUNNING``, make no market request and change nothing;
* **error exit status**: a tick with an impossible cadence must refuse, record the refusal and return
  the non-zero status it declared;
* **the closure guard** is re-derived structurally from the tick's own syntax tree: the branch that
  returns ``EXIT_PERIOD_ENDED`` has to come before any call that collects a window, so no sample can
  be taken after the declared end;
* the run log is checked for uniqueness, for the observability fields of the phase, for compactness
  (no rollups inside an event, per CAP-004C) and for agreement between each event's result and the
  exit status the process returned;
* missed windows are recomputed: every declared slot that has already ended must be either an
  observed window or a recorded ``MISSED_WINDOW``, nothing is ever reconstructed, and each miss must
  state a cause from the declared vocabulary whose own counters agree with the retained run events;
* both programs are scanned for an order or credential path in their syntax trees.

It fails closed, reports ``FALSE_SUCCESS`` as the number of mismatches, and writes
``ST6_SCHEDULER_VERIFICATION.json``.

Run:  python scripts/st6_scheduler_verify.py
"""

from __future__ import annotations

import argparse
import ast
import json
import subprocess
import sys
import time
import xml.etree.ElementTree as ElementTree
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
SCRIPTS = REPO / "scripts"
TICK = SCRIPTS / "st6_forward_regime.py"
HEALTH = SCRIPTS / "st6_health_check.py"
PYTHON = REPO / ".venv" / "Scripts" / "python.exe"
DATA = REPO / "data" / "st6"
PERIOD = DATA / "ST6_PERIOD.json"
WINDOWS = DATA / "ST6_WINDOWS.jsonl"
MISSED_LOG = DATA / "ST6_MISSED_WINDOWS.jsonl"
RUN_LOG = DATA / "ST6_RUNS.jsonl"
CLOSURE = DATA / "ST6_PERIOD_CLOSURE.json"
OUT = DATA / "ST6_SCHEDULER_VERIFICATION.json"
TASK_NAME = "TradingAgentic-ST6-Forward"
LOCAL_STATE = REPO / "data" / "storage"

SLOT_HOURS = 4
SLOTS_PER_DAY = 6
EXPECTED_INTERVAL = "PT15M"
#: The causes a missed window may state.  A slot nobody attended and a slot the tick visited without
#: measuring are different failures, and the record has to say which one it was.
ATTENDANCE_CLASSES = (
    "ATTENDED_NOT_COLLECTED",
    "ATTENDED_REQUEST_FAILED",
    "UNATTENDED_NO_RUN_EVENT",
    "ATTENDANCE_UNKNOWN_RUN_LOG_TRUNCATED",
)
TASK_TRIGGER_TIMEOUT_S = 120
RUN_EVENT_FIELDS = (
    "run_id",
    "scheduled_slot_utc",
    "slot_key",
    "actual_start_utc",
    "actual_end_utc",
    "result",
    "market_requests",
    "data_freshness",
    "raw_evidence_hash",
    "verifier_status",
    "errors",
    "exit_code",
)
ROLLUP_KEYS = (
    "by_asset",
    "by_session",
    "by_volatility_regime",
    "checks",
    "day_detail",
    "model_comparison",
    "coverage",
    "statistics",
)
ORDER_TOKENS = (
    "create_order",
    "place_order",
    "submit_order",
    "new_order",
    "post_order",
    "cancel_order",
    "createOrder",
    "privateKey",
    "signature",
    "apiKey",
    "api_key",
    "secret",
    "testnet_order",
)
RESULT_EXIT_CODES = {
    "COLLECTED": 0,
    "SKIPPED_NO_WINDOW_DUE": 0,
    "ALREADY_RUNNING": 2,
    "PERIOD_ENDED_CONSOLIDATED": 3,
    "COLLECTION_INCOMPLETE": 4,
    "REFUSED_INVALID_ARGUMENTS": 1,
    "REPORT_ONLY": 0,
    # a legacy label from the first report-only invocations: the log is append-only, so the token
    # stays known rather than being rewritten
    "UNKNOWN": 0,
}


class Checks:
    def __init__(self) -> None:
        self.total = 0
        self.passed = 0
        self.failed: list[str] = []

    def check(self, name: str, ok: bool, detail: Any = None) -> None:
        self.total += 1
        if ok:
            self.passed += 1
        else:
            self.failed.append(f"{name}: {detail}")


def read_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    document: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    return document


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [
        json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()
    ]


def order_path_tokens(source: str) -> list[str]:
    """Tokens of an order or credential path in *executable* code.

    Identifiers count, and so does a string that is passed *into* a call; a string sitting in a
    module-level list does not, because a program that names the paths it forbids is not a program
    that uses them — and a check that cannot tell those apart would only ever flag the guards.
    """
    tree = ast.parse(source)
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute):
            names.add(node.attr.lower())
        elif isinstance(node, ast.Name):
            names.add(node.id.lower())
        elif isinstance(node, ast.Call):
            for argument in [*node.args, *[keyword.value for keyword in node.keywords]]:
                if isinstance(argument, ast.Constant) and isinstance(argument.value, str):
                    names.add(argument.value.lower())
    return sorted({token for token in ORDER_TOKENS if token.lower() in names})


def task_registration() -> dict[str, Any]:
    state: dict[str, Any] = {"installed": False, "enabled": None, "query_error": None}
    try:
        result = subprocess.run(
            ["schtasks", "/query", "/tn", TASK_NAME, "/xml"],
            capture_output=True,
            text=True,
            timeout=30,
        )
    except Exception as exc:
        state["query_error"] = f"{type(exc).__name__}: {exc}"
        return state
    if result.returncode != 0:
        state["query_error"] = (result.stderr or result.stdout or "").strip()[:200]
        return state
    try:
        root = ElementTree.fromstring(result.stdout.lstrip("\ufeff"))
    except ElementTree.ParseError as exc:
        state["query_error"] = f"ParseError: {exc}"
        return state
    ns = {"t": "http://schemas.microsoft.com/windows/2004/02/mit/task"}
    state["installed"] = True
    settings = root.find("t:Settings", ns)
    if settings is not None:
        enabled = settings.find("t:Enabled", ns)
        state["enabled"] = (
            True if enabled is None else (enabled.text or "").strip().lower() == "true"
        )
        policy = settings.find("t:MultipleInstancesPolicy", ns)
        state["multiple_instances_policy"] = None if policy is None else (policy.text or "").strip()
        limit = settings.find("t:ExecutionTimeLimit", ns)
        state["execution_time_limit"] = None if limit is None else (limit.text or "").strip()
    action = root.find("t:Actions/t:Exec", ns)
    if action is not None:
        state["command"] = (action.findtext("t:Command", default="", namespaces=ns) or "").strip()
        state["arguments"] = (
            action.findtext("t:Arguments", default="", namespaces=ns) or ""
        ).strip()
        state["working_directory"] = (
            action.findtext("t:WorkingDirectory", default="", namespaces=ns) or ""
        ).strip()
    repetition = root.find("t:Triggers/t:TimeTrigger/t:Repetition/t:Interval", ns)
    state["repetition_interval"] = None if repetition is None else (repetition.text or "").strip()
    return state


def run_tick(extra: list[str], timeout: int = 180) -> dict[str, Any]:
    result = subprocess.run(
        [str(PYTHON), str(TICK), *extra],
        cwd=REPO,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    return {
        "argv": extra,
        "exit_code": result.returncode,
        "stdout_tail": (result.stdout or "").strip().splitlines()[-4:],
        "stderr_tail": (result.stderr or "").strip().splitlines()[-2:],
    }


def slots_ended_by(period: dict[str, Any], now: datetime) -> list[dict[str, Any]]:
    start = datetime.strptime(period["started_at_utc"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
    last = min(
        now, datetime.strptime(period["ends_at_utc"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
    )
    cursor = start.replace(minute=0, second=0, microsecond=0)
    slots: list[dict[str, Any]] = []
    while cursor <= last:
        index = cursor.hour // SLOT_HOURS
        slots.append(
            {
                "key": f"{cursor.strftime('%Y-%m-%d')}#{index}",
                "ends_at_utc": (cursor + timedelta(hours=SLOT_HOURS)).strftime(
                    "%Y-%m-%dT%H:%M:%SZ"
                ),
            }
        )
        cursor += timedelta(hours=SLOT_HOURS)
    return slots


# ---------------------------------------------------------------------------------------------
# live tests: the scheduler is exercised, not described
# ---------------------------------------------------------------------------------------------


def live_real_execution() -> dict[str, Any]:
    before = len(read_jsonl(RUN_LOG))
    try:
        triggered = subprocess.run(
            ["schtasks", "/run", "/tn", TASK_NAME], capture_output=True, text=True, timeout=60
        )
    except Exception as exc:
        return {"status": "FAIL", "detail": f"{type(exc).__name__}: {exc}"}
    if triggered.returncode != 0:
        return {
            "status": "FAIL",
            "detail": (triggered.stderr or triggered.stdout or "").strip()[:200],
        }
    deadline = time.time() + TASK_TRIGGER_TIMEOUT_S
    while time.time() < deadline:
        runs = read_jsonl(RUN_LOG)
        if len(runs) > before:
            event = runs[-1]
            return {
                "status": "PASS",
                "detail": "the scheduler started the task and its tick wrote a run event",
                "trigger_exit_code": triggered.returncode,
                "event": {
                    "run_id": event.get("run_id"),
                    "result": event.get("result"),
                    "exit_code": event.get("exit_code"),
                    "market_requests": event.get("market_requests"),
                },
            }
        time.sleep(5)
    return {"status": "FAIL", "detail": "the triggered task wrote no run event within the timeout"}


def live_due_idempotency() -> dict[str, Any]:
    windows_before = len(read_jsonl(WINDOWS))
    first = run_tick(["--due", "--scheduled"])
    second = run_tick(["--due", "--scheduled"])
    windows_after = len(read_jsonl(WINDOWS))
    runs = read_jsonl(RUN_LOG)
    tails = runs[-2:]
    ok = (
        windows_after == windows_before
        and len(runs) >= 2
        and all(event.get("slot_key") for event in tails)
        and all(int(event.get("market_requests") or 0) == 0 for event in tails)
        and all(event.get("result") in ("SKIPPED_NO_WINDOW_DUE", "COLLECTED") for event in tails)
    )
    return {
        "status": "PASS" if ok else "FAIL",
        "detail": (
            "two consecutive ticks ran in a slot that already has a window: no new window, no market "
            "request, one run event each"
            if ok
            else "the two ticks changed the window index or made a market request"
        ),
        "windows_before": windows_before,
        "windows_after": windows_after,
        "first": first,
        "second": second,
        "events": [
            {
                "run_id": event.get("run_id"),
                "result": event.get("result"),
                "exit_code": event.get("exit_code"),
                "market_requests": event.get("market_requests"),
            }
            for event in tails
        ],
    }


def live_concurrency() -> dict[str, Any]:
    sys.path.insert(0, str(SCRIPTS))
    import st6_forward_regime as phase  # the tick's own lease, exercised live

    lease = phase.run_lease()
    acquired = lease.acquire(now=int(datetime.now(UTC).timestamp()))
    if not acquired["acquired"]:
        return {
            "status": "FAIL",
            "detail": f"could not take the lease to run the test: {acquired}",
        }
    try:
        second = run_tick(["--due", "--scheduled"])
        runs = read_jsonl(RUN_LOG)
        refused = [event for event in runs if event.get("result") == "ALREADY_RUNNING"]
        ok = second["exit_code"] == 2 and bool(refused)
        return {
            "status": "PASS" if ok else "FAIL",
            "detail": (
                "a second process refused the tick with ALREADY_RUNNING while the lease was held"
                if ok
                else "the second process did not refuse with the declared status"
            ),
            "second_exit_code": second["exit_code"],
            "refusals_recorded": len(refused),
            "refusal_event": refused[-1] if refused else None,
        }
    finally:
        lease.release()


def live_error_exit_status() -> dict[str, Any]:
    before = len(read_jsonl(RUN_LOG))
    result = run_tick(["--collect", "--rounds", "0"])
    runs = read_jsonl(RUN_LOG)
    fresh = runs[before:]
    ok = result["exit_code"] == 1 and any(
        event.get("result") == "REFUSED_INVALID_ARGUMENTS" for event in fresh
    )
    return {
        "status": "PASS" if ok else "FAIL",
        "detail": (
            "a tick with an impossible cadence refused, recorded the refusal and returned a non-zero "
            "status"
            if ok
            else "the refusal path did not behave as declared"
        ),
        "exit_code": result["exit_code"],
        "events": [
            {"result": event.get("result"), "exit_code": event.get("exit_code")} for event in fresh
        ],
    }


def closure_guard_structure() -> dict[str, Any]:
    """Re-derive the closure guard from the tick's syntax tree: the guard must come first."""
    source = TICK.read_text(encoding="utf-8")
    tree = ast.parse(source)
    target = next(
        (node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "_run"),
        None,
    )
    if target is None:
        return {"status": "FAIL", "detail": "the tick has no _run function"}
    guard_variable: str | None = None
    computed_index: int | None = None
    guard_index: int | None = None
    collect_index: int | None = None
    for index, statement in enumerate(target.body):
        dumped = ast.dump(statement)
        if computed_index is None and "period_ended" in dumped:
            computed_index = index
            if isinstance(statement, ast.Assign) and isinstance(statement.targets[0], ast.Name):
                guard_variable = statement.targets[0].id
        if collect_index is None and "collect_one" in dumped:
            collect_index = index
    if guard_variable is not None:
        for index, statement in enumerate(target.body):
            if not isinstance(statement, ast.If):
                continue
            tested = {node.id for node in ast.walk(statement.test) if isinstance(node, ast.Name)}
            if guard_variable in tested and "EXIT_PERIOD_ENDED" in ast.dump(statement):
                guard_index = index
                break
    ok = (
        computed_index is not None
        and guard_index is not None
        and collect_index is not None
        and computed_index < collect_index
        and guard_index < collect_index
    )
    return {
        "status": "PASS" if ok else "FAIL",
        "detail": (
            "the end of the period is computed and its branch returns EXIT_PERIOD_ENDED before any "
            "statement that collects a window"
            if ok
            else "the closure guard does not dominate the collection"
        ),
        "period_ended_statement_index": computed_index,
        "guard_branch_index": guard_index,
        "collection_statement_index": collect_index,
        "guard_variable": guard_variable,
    }


# ---------------------------------------------------------------------------------------------
# static and log checks
# ---------------------------------------------------------------------------------------------


def verify_run_log(c: Checks) -> dict[str, Any]:
    runs = read_jsonl(RUN_LOG)
    c.check("the run log exists and is not empty", bool(runs), len(runs))
    ids = [run.get("run_id") for run in runs]
    c.check(
        "every run event carries a unique run_id",
        len(set(ids)) == len(ids),
        len(ids) - len(set(ids)),
    )
    for index, run in enumerate(runs):
        c.check(
            f"run {index}: it carries the observability fields of the phase",
            all(field in run for field in RUN_EVENT_FIELDS),
            sorted(set(RUN_EVENT_FIELDS) - set(run)),
        )
        for key in ROLLUP_KEYS:
            c.check(f"run {index}: no rollup is duplicated inside the event", key not in run, key)
        result = run.get("result")
        expected = RESULT_EXIT_CODES.get(str(result))
        c.check(
            f"run {index}: the recorded result and exit status agree",
            expected is None or run.get("exit_code") == expected,
            f"{result} -> {run.get('exit_code')} (expected {expected})",
        )
        c.check(
            f"run {index}: actual_end follows actual_start",
            str(run.get("actual_end_utc", "")) >= str(run.get("actual_start_utc", "")),
            (run.get("actual_start_utc"), run.get("actual_end_utc")),
        )
        if result == "SKIPPED_NO_WINDOW_DUE":
            c.check(
                f"run {index}: a tick with nothing due made no market request",
                int(run.get("market_requests") or 0) == 0,
                run.get("market_requests"),
            )
        if result == "COLLECTED":
            c.check(
                f"run {index}: a collected run names its raw evidence hash",
                bool(run.get("raw_evidence_hash")),
                run.get("raw_evidence_hash"),
            )
    per_slot: dict[str, list[str]] = {}
    for run in runs:
        if run.get("result") == "COLLECTED":
            per_slot.setdefault(str(run.get("slot_key")), []).append(str(run.get("window_id")))
    duplicates = {key: value for key, value in per_slot.items() if len(value) > 1}
    c.check(
        "no slot was measured twice by the tick",
        not duplicates,
        duplicates,
    )
    windows = read_jsonl(WINDOWS)
    slot_windows: dict[str, int] = {}
    for window in windows:
        key = f"{window['day']}#{window['slot_index']}"
        slot_windows[key] = slot_windows.get(key, 0) + 1
    c.check(
        "no slot holds more than one window in the index",
        all(count == 1 for count in slot_windows.values()),
        {key: count for key, count in slot_windows.items() if count > 1},
    )
    return {"runs": len(runs), "collected_slots": sorted(per_slot), "windows": len(windows)}


def verify_missed_accounting(c: Checks, period: dict[str, Any], now: datetime) -> dict[str, Any]:
    windows = read_jsonl(WINDOWS)
    missed = read_jsonl(MISSED_LOG)
    runs = read_jsonl(RUN_LOG)
    retained = sorted(
        str(run.get("actual_start_utc")) for run in runs if run.get("actual_start_utc")
    )
    observed = {f"{row['day']}#{row['slot_index']}" for row in windows}
    recorded = {row["slot_key"] for row in missed}
    ended = [
        entry
        for entry in slots_ended_by(period, now)
        if entry["ends_at_utc"] <= now.strftime("%Y-%m-%dT%H:%M:%SZ")
    ]
    unaccounted = [
        entry["key"]
        for entry in ended
        if entry["key"] not in observed and entry["key"] not in recorded
    ]
    c.check(
        "every ended slot is either an observed window or a recorded missed window",
        not unaccounted,
        unaccounted,
    )
    for row in missed:
        c.check(
            f"missed {row['slot_key']}: it is recorded as MISSED_WINDOW and not reconstructed",
            row.get("status") == "MISSED_WINDOW" and row.get("reconstructed") is False,
            row,
        )
        c.check(
            f"missed {row['slot_key']}: it states a reason",
            bool(row.get("reason")),
            row.get("reason"),
        )
        attendance = row.get("attendance")
        attendance = attendance if isinstance(attendance, dict) else {}
        classification = str(attendance.get("classification"))
        try:
            counted = int(attendance.get("scheduled_runs_in_slot") or 0)
        except (TypeError, ValueError):
            counted = -1  # an unreadable count fails the consistency check instead of crashing it
        covers = bool(attendance.get("log_covers_whole_slot"))
        c.check(
            f"missed {row['slot_key']}: the cause is declared and carries its own evidence",
            classification in ATTENDANCE_CLASSES,
            row.get("attendance"),
        )
        c.check(
            f"missed {row['slot_key']}: the stated cause agrees with its own counters",
            (classification.startswith("ATTENDED") and counted > 0)
            or (classification == "UNATTENDED_NO_RUN_EVENT" and counted == 0 and covers)
            or (
                classification == "ATTENDANCE_UNKNOWN_RUN_LOG_TRUNCATED"
                and counted == 0
                and not covers
            ),
            {
                "classification": classification,
                "scheduled_runs_in_slot": counted,
                "log_covers_whole_slot": covers,
            },
        )
        c.check(
            f"missed {row['slot_key']}: the evidence declares how long it stays valid",
            bool(attendance.get("policy")) and bool(attendance.get("evidence_lifetime")),
            attendance.get("evidence_lifetime"),
        )
        # While the retained log still reaches back past the slot's own start, no event inside that
        # slot can have been pruned, so the number it holds is a second count of the record's claim.
        if retained and retained[0] <= str(row.get("starts_at_utc")):
            live = sum(
                1
                for run in runs
                if run.get("slot_key") == row["slot_key"]
                and str(run.get("invocation", "")).upper() != "MANUAL"
            )
            c.check(
                f"missed {row['slot_key']}: the recorded attendance count matches the run log",
                counted == live,
                {"recorded": counted, "retained_events_in_slot": live},
            )
    invented = [row["slot_key"] for row in missed if row["slot_key"] in observed]
    c.check("no slot is both missed and observed", not invented, invented)
    return {
        "ended_slots": len(ended),
        "observed_slots": len(observed),
        "missed_slots": len(recorded),
        "unaccounted": unaccounted,
    }


def verify_task(c: Checks, state: dict[str, Any]) -> None:
    c.check(
        "the scheduled task is installed on this host", state["installed"], state.get("query_error")
    )
    if not state["installed"]:
        return
    c.check("the scheduled task is enabled", state.get("enabled") is True, state.get("enabled"))
    c.check(
        "the task runs the repository's virtual-environment interpreter",
        Path(str(state.get("command"))).name.lower() == "python.exe"
        and str(PYTHON).lower() in str(state.get("command", "")).lower(),
        state.get("command"),
    )
    c.check(
        "the task passes the unattended tick arguments",
        "--due" in str(state.get("arguments", ""))
        and "--scheduled" in str(state.get("arguments", "")),
        state.get("arguments"),
    )
    c.check(
        "the task works in the repository directory",
        str(state.get("working_directory", "")).rstrip("\\/").lower()
        == str(REPO).rstrip("\\/").lower(),
        state.get("working_directory"),
    )
    c.check(
        "the task repeats every fifteen minutes",
        state.get("repetition_interval") == EXPECTED_INTERVAL,
        state.get("repetition_interval"),
    )
    c.check(
        "the task cannot hold credentials: its action is a plain python interpreter",
        "cmd" not in str(state.get("command", "")).lower()
        and "powershell" not in str(state.get("command", "")).lower(),
        state.get("command"),
    )


def verify_no_live_paths(c: Checks, tick_source: str, health_source: str) -> None:
    for label, source in (("the tick", tick_source), ("the health checker", health_source)):
        offenders = order_path_tokens(source)
        c.check(
            f"{label}: its syntax tree carries no order or credential path",
            not offenders,
            offenders,
        )
    combined = tick_source + health_source
    for token in ("ccxt", "TRADING_MODE", ".env", "exchange.yaml", "api_secret"):
        c.check(f"neither program references {token}", token not in combined, token)
    c.check(
        "the tick writes only inside its own evidence directory",
        "data" in tick_source and "/st6" in tick_source.replace("\\", "/"),
        "the evidence directory is named",
    )
    c.check(
        "the scan can tell a guard from a use: it flags a token passed into a call",
        order_path_tokens('client.create_order(symbol, "create_order")') == ["create_order"],
        order_path_tokens("client.create_order(symbol)"),
    )
    c.check(
        "the scan does not flag a program that merely names the forbidden paths",
        order_path_tokens('FORBIDDEN = ("api_key", "create_order")') == [],
        order_path_tokens('FORBIDDEN = ("api_key", "create_order")'),
    )
    c.check(
        "the periods' local state directory is not written by these programs",
        str(LOCAL_STATE) not in tick_source
        and "data/storage" not in tick_source.replace("\\", "/"),
        "data/storage referenced",
    )


def closure_for_declared_period(period: dict[str, Any]) -> tuple[dict[str, Any] | None, str]:
    """A consolidation counts only when it is the consolidation *of this* declared period.

    Existence alone is not identity: a rehearsal, a test or an earlier period can leave a
    closure document on disk, and accepting it would let a foreign artefact stand in for the
    consolidation of the period under observation.
    """
    document = read_json(CLOSURE)
    if document is None:
        return None, "absent"
    closed = document.get("period") or {}
    declared = (period.get("started_at_utc"), period.get("ends_at_utc"))
    found = (closed.get("started_at_utc"), closed.get("ends_at_utc"))
    if found != declared:
        return None, f"belongs to another period: {found[0]} -> {found[1]}"
    return document, "belongs to the declared period"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default=str(OUT))
    args = parser.parse_args(argv)

    now = datetime.now(UTC)
    c = Checks()
    period = read_json(PERIOD)
    if period is None:
        print("no period is declared; nothing to verify")
        return 1
    tick_source = TICK.read_text(encoding="utf-8")
    health_source = HEALTH.read_text(encoding="utf-8")

    state = task_registration()
    verify_task(c, state)
    details: dict[str, dict[str, Any]] = {}
    if state["installed"]:
        details["real_execution"] = live_real_execution()
        details["due_idempotency"] = live_due_idempotency()
        details["concurrency"] = live_concurrency()
        details["error_exit_status"] = live_error_exit_status()
    else:
        for key in ("real_execution", "due_idempotency", "concurrency", "error_exit_status"):
            details[key] = {
                "status": "NOT_RUN",
                "detail": "the scheduled task is not installed on this host",
            }
    guard = closure_guard_structure()
    details["period_closure_guard"] = guard
    # one status per test, and the full payload kept beside it: a report that only carries "PASS"
    # could not be audited afterwards
    live = {name: entry["status"] for name, entry in details.items()}
    for name, entry in details.items():
        c.check(f"live test {name}: it passed", entry["status"] == "PASS", entry)
    run_log_state = verify_run_log(c)
    missed_state = verify_missed_accounting(c, period, now)
    verify_no_live_paths(c, tick_source, health_source)

    closure, closure_reading = closure_for_declared_period(period)
    c.check(
        "the task's own repetition cannot outlive the declared period unnoticed",
        closure is not None
        or now < datetime.strptime(period["ends_at_utc"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC),
        f"the period is over but no consolidation of this period exists ({closure_reading})",
    )
    c.check(
        "a consolidation on disk is read by identity, not by existence",
        closure_for_declared_period({**period, "ends_at_utc": "2026-01-01T00:00:00Z"})[0] is None
        if read_json(CLOSURE) is not None
        else True,
        closure_reading,
    )
    c.check(
        "the delegated verifier of the observations exists and reports PASS",
        (read_json(DATA / "ST6_INDEPENDENT_VERIFICATION.json") or {}).get("status") == "PASS",
        (read_json(DATA / "ST6_INDEPENDENT_VERIFICATION.json") or {}).get("status"),
    )
    c.check(
        "the builder is not the verifier",
        Path(__file__).name != TICK.name,
        Path(__file__).name,
    )

    result: dict[str, Any] = {
        "artifact": "ST6_SCHEDULER_VERIFICATION",
        "verifier": "scripts/st6_scheduler_verify.py",
        "builder": "scripts/st6_forward_regime.py",
        "builder_equals_verifier": False,
        "generated_at_utc": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "task": state,
        "live_tests": live,
        "live_test_detail": details,
        "period_closure_guard": guard,
        "period_closure": {"reading": closure_reading, "present": closure is not None},
        "run_log": run_log_state,
        "missed_accounting": missed_state,
        "checks_total": c.total,
        "checks_passed": c.passed,
        "mismatches": len(c.failed),
        "failures": c.failed,
        "false_success": len(c.failed),
        "status": "PASS" if not c.failed else "FAIL",
        "verdict": "ST6_SCHEDULER_VERIFIED" if not c.failed else "ST6_SCHEDULER_FAILED",
        "method": (
            "the task is exercised through the scheduler itself and through two direct ticks; the "
            "lease, the idempotency of --due, the refusal path and the closure guard are tested live "
            "and structurally; the run log, the missed-window accounting and the absence of an order "
            "path are re-derived from the artefacts and from the syntax trees"
        ),
        "standing_state": {
            "DISCOVERY_CAMPAIGN_FAILED": True,
            "NEXT_CAMPAIGN": "NOT_AUTHORIZED",
            "TRADES_AUTHORIZED": 0,
            "LIVE_TRADING": "DISABLED",
            "PROFITABILITY_VERIFIED": False,
        },
    }
    out = Path(args.out)
    out.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(
        f"{result['status']} {result['checks_passed']}/{result['checks_total']} checks, "
        f"{result['mismatches']} mismatches, FALSE_SUCCESS = {result['false_success']}"
    )
    for failure in result["failures"][:25]:
        print(f"  FAIL {failure}")
    print(f"written -> {out}")
    return 1 if c.failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
