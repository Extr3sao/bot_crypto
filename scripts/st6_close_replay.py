"""ST-6 — isolated, deterministic replay of the end-of-period close.

The declared period of the forward cost observation ends at ``2026-10-22T16:21:20Z``.  This program
proves that the close behaves correctly *before* that instant arrives, by replaying the real tick
against a copy of the real state, with an injected UTC clock instead of the system clock:

* an **isolated sandbox** under the temporary directory holds the only state the replay can read or
  write: a copy of ``data/st6``.  Every path constant of the tick is redirected into the sandbox, so
  the replay cannot read the real window index, write the real evidence, take the real lease or
  touch the real closure;
* the **market is forbidden**: the probe and the kline reader are replaced by a guard that records
  the attempt and raises, and ``urllib.request.urlopen`` is blocked for the whole process, so no
  request can leave the machine even by an indirect path;
* the **real scheduler is forbidden**: the task registration is read from the captured snapshot, the
  terminal transition is intercepted, and any other subprocess call raises;
* the **clock is injected** through a frozen ``datetime`` subclass placed in the tick's namespace,
  so the same state and clock always produce the same close, and the system clock is never changed;
* the **real state is fingerprinted before and after**, and every byte that moved is attributed.

Scenarios (the ones §04 of the mission declares, plus the negative ones):

    1. a tick before the close (an observed slot): no sample, no window, no closure
    2. the last eligible slot, and the boundary slot the period closes inside
    3. the exact close instant: consolidation, missed windows, terminal state
    4. a tick after the close: an idempotent no-op, nothing rewritten
    5. repeated execution after the close: the closure is byte-stable
    6. unattended windows: every declared slot is observed or recorded as missed
    7. concurrent execution: the shared lease refuses the second writer
    8. corrupt data: a tampered hash and corrupt raw bytes are refused, not blessed
    9. missing evidence: an absent raw snapshot fails the data quality rule
   10. recovery after a host restart: a fresh process reproduces the close byte for byte

Run:  python scripts/st6_close_replay.py [--cleanup]
"""

from __future__ import annotations

import argparse
import contextlib
import gzip
import hashlib
import importlib.util
import io
import json
import shutil
import sys
import tempfile
import types
import urllib.request
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
SCRIPTS = REPO / "scripts"
if str(REPO / "src") not in sys.path:  # the shared lease library lives in src/
    sys.path.insert(0, str(REPO / "src"))
TICK = SCRIPTS / "st6_forward_regime.py"
DATA = REPO / "data" / "st6"
OUT_JSON = DATA / "ST6_CLOSE_REPLAY_REPORT.json"
OUT_MD = DATA / "ST6_CLOSE_REPLAY_REPORT.md"

REPLAY_VERSION = "ST6_CLOSE_REPLAY_V1"
CLOSE_INSTANT = "2026-10-22T16:21:20Z"
PERIOD_START = "2026-10-08T16:21:20Z"
FIRST_DECLARED_SLOT = "2026-10-08#4"
LAST_DECLARED_SLOT = "2026-10-22#3"
BOUNDARY_SLOT_NOT_DECLARED = "2026-10-22#4"
DECLARED_DAYS = 14
SLOTS_PER_DAY = 6
PLANNED_WINDOWS = DECLARED_DAYS * SLOTS_PER_DAY
SLOT_HOURS = 4

OUTCOMES = (
    "COST_MODEL_SUPPORTED_IN_OBSERVED_REGIMES",
    "COST_MODEL_DRIFT_DETECTED",
    "INSUFFICIENT_REGIME_COVERAGE",
    "DATA_QUALITY_FAILED",
)

#: Path constants of the tick that must be redirected into the sandbox.  Anything under the
#: repository is mapped by its own relative path; the rest is mapped too, so a mistake cannot read a
#: real file by accident.
REDIRECTED_CONSTANTS = (
    "DATA",
    "PERIOD_PATH",
    "OBSERVATIONS",
    "WINDOWS",
    "RAW_DIR",
    "COVERAGE_PATH",
    "DRIFT_PATH",
    "REPORT_JSON",
    "REPORT_MD",
    "RUN_LOG",
    "MISSED_LOG",
    "CLOSURE",
    "SCHEDULER_REPORT_JSON",
    "SCHEDULER_REPORT_MD",
    "HEALTH_STATUS",
    "SCHEDULER_VERIFICATION",
    "INDEPENDENT_VERIFICATION",
    "LOCK_ROOT",
    "COST_MODEL",
    "PRICE_DIR",
)


class MarketAccessForbidden(RuntimeError):
    """The replay forbids a market request: the guard raises before anything can be sent."""


class SubprocessForbidden(RuntimeError):
    """The replay forbids reaching the real scheduler or any other program."""


class FrozenClock(datetime):
    """A ``datetime`` whose ``now()`` returns an injected instant.  The system clock is untouched."""

    _frozen: datetime = datetime(2026, 1, 1, tzinfo=UTC)

    @classmethod
    def now(cls, tz: Any = None) -> datetime:
        moment = cls._frozen
        if tz is not None:
            return moment.astimezone(tz)
        return moment.replace(tzinfo=None)

    @classmethod
    def set(cls, instant: datetime) -> None:
        cls._frozen = instant


class Recorder:
    """Every attempt the replay intercepts, kept as evidence instead of performed."""

    def __init__(self) -> None:
        self.network_attempts: list[dict[str, Any]] = []
        self.subprocess_attempts: list[dict[str, Any]] = []
        self.verifier_delegations: list[dict[str, Any]] = []
        self.terminal_transitions: list[dict[str, Any]] = []
        self.scheduler_queries: list[dict[str, Any]] = []

    def as_dict(self) -> dict[str, Any]:
        return {
            "network_attempts": self.network_attempts,
            "subprocess_attempts": self.subprocess_attempts,
            "verifier_delegations": self.verifier_delegations,
            "terminal_transitions": self.terminal_transitions,
            "scheduler_queries": self.scheduler_queries,
            "real_market_requests": 0,
            "real_scheduler_calls": 0,
        }


# ------------------------------------------------------------------------------------------------
# arithmetic the replay does for itself, so the contract is not read from the tick's own opinion
# ------------------------------------------------------------------------------------------------


def parse_instant(stamp: str) -> datetime:
    return datetime.strptime(stamp, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)


def declared_slots(period: dict[str, Any], until: datetime) -> list[dict[str, Any]]:
    """The eligible windows (per the contract): the plan, counted from the start's own slot."""
    start = parse_instant(period["started_at_utc"])
    last = min(until, parse_instant(period["ends_at_utc"]))
    planned = int(period["period_days"]) * int(period["slots_per_day"])
    cursor = start.replace(minute=0, second=0, microsecond=0)
    slots: list[dict[str, Any]] = []
    while cursor <= last and len(slots) < planned:
        slots.append(
            {
                "key": f"{cursor.strftime('%Y-%m-%d')}#{cursor.hour // SLOT_HOURS}",
                "starts_at_utc": cursor.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "ends_at_utc": (cursor + timedelta(hours=SLOT_HOURS)).strftime(
                    "%Y-%m-%dT%H:%M:%SZ"
                ),
            }
        )
        cursor += timedelta(hours=SLOT_HOURS)
    return slots


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def raw_sha256(path: Path) -> str:
    """The hash of a gzipped raw snapshot's uncompressed bytes, read with a context manager."""
    with gzip.open(path, "rb") as handle:
        return sha256_bytes(handle.read())


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


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.write_text(
        "".join(json.dumps(row, sort_keys=True, ensure_ascii=False) + "\n" for row in rows),
        encoding="utf-8",
    )


def fingerprint_real_state() -> dict[str, str]:
    """Hash everything the live campaign owns, so a replay that touched it cannot hide."""
    hashes: dict[str, str] = {}
    for path in sorted(DATA.rglob("*")):
        if not path.is_file():
            continue
        relative = str(path.relative_to(REPO)).replace("\\", "/")
        hashes[relative] = sha256_file(path)
    for relative in (
        "scripts/st6_forward_regime.py",
        "scripts/st6_health_check.py",
        "scripts/st6_scheduler_verify.py",
    ):
        path = REPO / relative
        if path.exists():
            hashes[relative] = sha256_file(path)
    return hashes


# ------------------------------------------------------------------------------------------------
# the sandbox
# ------------------------------------------------------------------------------------------------


class Sandbox:
    """A private copy of the live ST-6 state; the only state the replay may touch."""

    def __init__(self, name: str, root: Path, source: Path = DATA) -> None:
        self.name = name
        self.root = root
        self.base = root / "data" / "st6"
        self.base.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(
            source,
            self.base,
            dirs_exist_ok=True,
            ignore=shutil.ignore_patterns("snapshots", "scheduler_lock"),
        )

    # -- paths --------------------------------------------------------------------------------- #

    def map(self, real: Path) -> Path:
        real = Path(real)
        if real == REPO:
            return self.root
        try:
            return self.root / real.relative_to(REPO)
        except ValueError:  # pragma: no cover - a constant outside the repository
            return self.root / "outside" / real.name

    @property
    def period_path(self) -> Path:
        return self.base / "ST6_PERIOD.json"

    @property
    def windows(self) -> Path:
        return self.base / "ST6_WINDOWS.jsonl"

    @property
    def observations(self) -> Path:
        return self.base / "ST6_OBSERVATIONS.jsonl"

    @property
    def runs(self) -> Path:
        return self.base / "ST6_RUNS.jsonl"

    @property
    def missed(self) -> Path:
        return self.base / "ST6_MISSED_WINDOWS.jsonl"

    @property
    def closure(self) -> Path:
        return self.base / "ST6_PERIOD_CLOSURE.json"

    @property
    def raw_dir(self) -> Path:
        return self.base / "raw"

    def period(self) -> dict[str, Any]:
        document = read_json(self.period_path)
        assert document is not None, "the sandbox has no declared period"
        return document

    # -- state --------------------------------------------------------------------------------- #

    def state(self) -> dict[str, Any]:
        files: dict[str, dict[str, Any]] = {}
        for path in sorted(self.base.rglob("*")):
            if not path.is_file():
                continue
            relative = str(path.relative_to(self.base)).replace("\\", "/")
            files[relative] = {"bytes": path.stat().st_size, "sha256": sha256_file(path)}
        closure = read_json(self.closure)
        return {
            "files": files,
            "windows": len(read_jsonl(self.windows)),
            "window_ids": [row["window_id"] for row in read_jsonl(self.windows)],
            "runs": len(read_jsonl(self.runs)),
            "missed": len(read_jsonl(self.missed)),
            "closure_present": closure is not None,
            "closure_sha256": sha256_file(self.closure) if self.closure.exists() else None,
            "raw_files": sorted(path.name for path in self.raw_dir.glob("*.json.gz")),
        }

    def clone(self, name: str, root: Path) -> Sandbox:
        clone_root = root / name
        return Sandbox(name, clone_root, source=self.base)

    def last_run(self) -> dict[str, Any] | None:
        rows = read_jsonl(self.runs)
        return rows[-1] if rows else None


# ------------------------------------------------------------------------------------------------
# loading and redirecting the real tick
# ------------------------------------------------------------------------------------------------


def load_tick(sandbox: Sandbox, recorder: Recorder, head: str) -> types.ModuleType:
    """Import a fresh copy of the real tick and redirect every path into the sandbox."""
    spec = importlib.util.spec_from_file_location(f"st6_replay_tick_{id(sandbox)}", TICK)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    for name in REDIRECTED_CONSTANTS:
        real = getattr(module, name)
        setattr(module, name, sandbox.map(real))
    module.REPO = sandbox.root
    module.DATA = sandbox.base
    module._replay_recorder = recorder

    period = sandbox.period()

    # the frozen model and the frozen archive are part of the declaration: read from the sandbox
    # period instead of re-reading the real model directory, so the replay reads no real file
    module.frozen_thresholds = lambda path=None: dict(period["thresholds"])  # type: ignore[assignment]
    module.volatility_reference = lambda: period["volatility_reference"]  # type: ignore[assignment]
    # The code identity is recorded at the top level of this report.  Inside the sandbox it is a
    # constant on purpose: if the replayed consolidation embedded the live commit id, the proof
    # that the same state and the same clock produce the same close would break every time the
    # code is committed — a determinism check that depends on the commit hash is not determinism.
    module._head = lambda: "REPLAY_SANDBOX_NOT_A_COMMIT"  # type: ignore[assignment]
    module.datetime = FrozenClock  # type: ignore[assignment]

    def guard_market(what: str):
        def blocked(*args: Any, **kwargs: Any) -> Any:
            recorder.network_attempts.append(
                {"what": what, "args": [str(argument)[:120] for argument in args][:2]}
            )
            raise MarketAccessForbidden(f"the replay forbids market access ({what})")

        return blocked

    module.collect = guard_market("economic001_readonly_probe.collect")  # type: ignore[assignment]
    module.fetch_klines = guard_market("fetch_klines")  # type: ignore[assignment]
    module.urllib = types.SimpleNamespace(  # type: ignore[assignment]
        request=types.SimpleNamespace(urlopen=guard_market("urllib.request.urlopen"))
    )

    def record_subprocess(argv: list[str]) -> dict[str, Any]:
        recorder.subprocess_attempts.append({"argv": [str(part) for part in argv]})
        raise SubprocessForbidden("the replay forbids reaching the real scheduler or any program")

    module.subprocess = types.SimpleNamespace(  # type: ignore[assignment]
        run=record_subprocess, check_output=record_subprocess, Popen=record_subprocess
    )

    def record_verifier(argv: list[str]) -> dict[str, Any]:
        recorder.verifier_delegations.append({"argv": [str(part) for part in argv]})
        return {
            "argv": [str(part) for part in argv[1:]],
            "exit_code": None,
            "stdout_tail": [],
            "stderr_tail": [],
            "status": "NOT_EXECUTED_IN_REPLAY",
        }

    module._run_program = record_verifier  # type: ignore[assignment]

    def record_scheduler_state() -> dict[str, Any]:
        recorded = (read_json(DATA / "ST6_SCHEDULER_REPORT.json") or {}).get(
            "SCHEDULER_STATE"
        ) or {}
        recorder.scheduler_queries.append({"what": "scheduler_state", "source": "snapshot"})
        return {
            "task_name": recorded.get("task_name", "TradingAgentic-ST6-Forward"),
            "queried_at_utc": FrozenClock.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "installed": bool(recorded.get("installed", True)),
            "enabled": recorded.get("enabled", True),
            "command": recorded.get("command"),
            "arguments": recorded.get("arguments"),
            "working_directory": recorded.get("working_directory"),
            "repetition_interval": recorded.get("repetition_interval", "PT15M"),
            "query_exit_code": 0,
            "query_error": None,
            "reading": "read from the captured snapshot: the real scheduler was not queried",
        }

    module.scheduler_state = record_scheduler_state  # type: ignore[assignment]

    def record_disk_status() -> dict[str, Any]:
        recorded = (read_json(sandbox.base / "ST6_SCHEDULER_REPORT.json") or {}).get(
            "DISK_STATUS"
        ) or {}
        recorder.scheduler_queries.append({"what": "disk_status", "source": "snapshot"})
        return {
            "status": recorded.get("status", "REPLAY_STUB"),
            "free_gib": recorded.get("free_gib", 0.0),
            "used_percent": recorded.get("used_percent", 0.0),
            "free_bytes": recorded.get("free_bytes"),
            "total_bytes": recorded.get("total_bytes"),
            "reading": (
                "the storage guard as the snapshot recorded it: the replay does not read the real "
                "disk"
            ),
        }

    module.disk_status = record_disk_status  # type: ignore[assignment]

    def record_terminal_transition() -> dict[str, Any]:
        recorder.terminal_transitions.append(
            {"what": "disable the period's own task", "real_task_touched": False}
        )
        return {
            "artifact": "ST6_TERMINAL_TRANSITION",
            "attempted_at_utc": FrozenClock.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "task_name": "TradingAgentic-ST6-Forward",
            "installed": True,
            "was_enabled": True,
            "action": "schtasks /change /tn <own task> /disable",
            "elevation_required": False,
            "touches_other_tasks": False,
            "exit_code": None,
            "disabled": True,
            "error": None,
            "recorded": True,
            "replay_intercepted": True,
            "reading": "intercepted by the replay: the real task was not changed",
        }

    module.perform_terminal_transition = record_terminal_transition  # type: ignore[assignment]
    return module


def run_tick(
    module: types.ModuleType,
    sandbox: Sandbox,
    instant: str,
    argv: list[str],
) -> dict[str, Any]:
    """Run the real entrypoint in-process with the injected clock, and record what it did."""
    FrozenClock.set(parse_instant(instant))
    recorder: Recorder = module._replay_recorder
    before = sandbox.state()
    attempts_before = len(recorder.network_attempts)
    buffer = io.StringIO()
    outcome: dict[str, Any] = {
        "instant": instant,
        "argv": list(argv),
        "exit_code": None,
        "exception": None,
        "exception_kind": None,
        "stdout_tail": [],
    }
    with contextlib.redirect_stdout(buffer):
        try:
            outcome["exit_code"] = module.main(list(argv))
        except MarketAccessForbidden as exc:
            outcome["exception"] = str(exc)
            outcome["exception_kind"] = "MARKET_ACCESS_FORBIDDEN"
        except SubprocessForbidden as exc:
            outcome["exception"] = str(exc)
            outcome["exception_kind"] = "SUBPROCESS_FORBIDDEN"
        except BaseException as exc:  # recorded, never hidden
            outcome["exception"] = f"{type(exc).__name__}: {exc}"
            outcome["exception_kind"] = type(exc).__name__
    outcome["stdout_tail"] = buffer.getvalue().strip().splitlines()[-4:]
    # what THIS run attempted, not what the whole replay has attempted so far
    outcome["network_attempts"] = len(recorder.network_attempts) - attempts_before
    after = sandbox.state()
    outcome["delta"] = {
        "windows": after["windows"] - before["windows"],
        "runs": after["runs"] - before["runs"],
        "missed": after["missed"] - before["missed"],
        "closure_written": after["closure_present"] and not before["closure_present"],
        "closure_changed": after["closure_sha256"] != before["closure_sha256"],
        "raw_files": len(after["raw_files"]) - len(before["raw_files"]),
    }
    outcome["state_after"] = {
        "windows": after["windows"],
        "runs": after["runs"],
        "missed": after["missed"],
        "closure_present": after["closure_present"],
        "closure_sha256": after["closure_sha256"],
    }
    outcome["last_run"] = sandbox.last_run()
    return outcome


def checks_pass(checks: dict[str, bool]) -> str:
    return "PASS" if all(checks.values()) else "FAIL"


def summarise(results: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "scenarios": len(results),
        "passed": sum(1 for result in results if result["verdict"] == "PASS"),
        "failed": sum(1 for result in results if result["verdict"] == "FAIL"),
        "declared_deviations": sum(
            1 for result in results if result["verdict"] == "DECLARED_DEVIATION"
        ),
    }


# ------------------------------------------------------------------------------------------------
# the scenarios
# ------------------------------------------------------------------------------------------------


def scenario_1_before_close(root: Path, recorder: Recorder, head: str) -> dict[str, Any]:
    sandbox = Sandbox("before-close", root / "before-close")
    module = load_tick(sandbox, recorder, head)
    result = run_tick(module, sandbox, "2026-10-08T22:00:00Z", ["--due", "--scheduled"])
    last = result["last_run"] or {}
    checks = {
        "the period is still open at this instant": not module.period_ended(
            sandbox.period(), parse_instant("2026-10-08T22:00:00Z")
        ),
        "the tick returned the declared success status": result["exit_code"] == 0,
        "the slot was already observed, so the tick skipped": last.get("result")
        == "SKIPPED_NO_WINDOW_DUE",
        "no window was added": result["delta"]["windows"] == 0,
        "the skipped tick made no market request": int(last.get("market_requests") or 0) == 0,
        "no market request reached the guard": result["network_attempts"] == 0,
        "no consolidation exists while the period is open": not result["state_after"][
            "closure_present"
        ],
    }
    return {
        "scenario": "1. a tick before the close, in an already observed slot",
        "verdict": checks_pass(checks),
        "checks": checks,
        "result": result,
        "reading": (
            "an open period still collects nothing it already has, makes no request and writes no "
            "consolidation"
        ),
    }


def scenario_2_boundary(root: Path, recorder: Recorder, head: str) -> dict[str, Any]:
    """The last eligible slot, and the boundary slot the period closes inside."""
    period = read_json(DATA / "ST6_PERIOD.json") or {}
    slots = declared_slots(period, parse_instant(CLOSE_INSTANT))
    keys = [slot["key"] for slot in slots]

    last_eligible = Sandbox("last-eligible", root / "last-eligible")
    module = load_tick(last_eligible, recorder, head)
    eligible_run = run_tick(module, last_eligible, "2026-10-22T15:59:00Z", ["--due", "--scheduled"])

    boundary = Sandbox("boundary", root / "boundary")
    module_boundary = load_tick(boundary, recorder, head)
    boundary_run = run_tick(
        module_boundary, boundary, "2026-10-22T16:10:00Z", ["--due", "--scheduled"]
    )

    checks = {
        "the plan is the declared 84 windows": len(slots) == PLANNED_WINDOWS == 84,
        "the first eligible slot is the one the period opened inside": keys[0]
        == FIRST_DECLARED_SLOT,
        "the last eligible slot is the last full slot before the end": keys[-1]
        == LAST_DECLARED_SLOT,
        "the slot the period closes inside is not an eligible window": BOUNDARY_SLOT_NOT_DECLARED
        not in keys,
        "every eligible slot ends at or before the declared end": all(
            slot["ends_at_utc"] <= CLOSE_INSTANT for slot in slots
        ),
        "the last eligible slot is still treated as due by the shipped tick (collection attempted, "
        "market access refused, nothing fabricated)": eligible_run["exception_kind"]
        == "MARKET_ACCESS_FORBIDDEN",
        "the boundary slot is not an eligible window, yet the shipped due rule attempts it too": (
            boundary_run["exception_kind"] == "MARKET_ACCESS_FORBIDDEN"
            and BOUNDARY_SLOT_NOT_DECLARED not in keys
        ),
        "neither attempt wrote a window or a raw snapshot": eligible_run["delta"]["windows"] == 0
        and boundary_run["delta"]["windows"] == 0
        and eligible_run["delta"]["raw_files"] == 0
        and boundary_run["delta"]["raw_files"] == 0,
    }
    deviation = {
        "id": "BOUNDARY-SLOT-DUE-RULE",
        "declared_contract": (
            "the plan is 84 windows counted from the slot that contains the period start; the "
            "partial slot the period closes inside (2026-10-22 16:00-16:21:20Z) is *not* a planned "
            "window: 'nothing may be expected, missed or penalised there'"
        ),
        "shipped_behaviour": (
            "the due rule is 'this slot has no window yet', which is not bounded by the declared "
            "plan; a scheduled tick between 16:00Z and the close would attempt to collect a window "
            "in the undeclared boundary slot (and would sample it, since the attempt is only "
            "refused here by the replay's market guard)"
        ),
        "why_it_is_declared_and_not_silently_fixed": (
            "changing the collection rule mid-period would alter the campaign; the mission requires "
            "the inconsistency to be declared with a minimal correction, not patched to taste"
        ),
        "minimal_correction": (
            "in the due path, collect only when the current slot's key is in the declared plan, "
            "i.e. `this_slot in {slot['key'] for slot in declared_slots_upto(period, "
            "parse(period['ends_at_utc']))}`, and otherwise record the existing "
            "SKIPPED_NO_WINDOW_DUE token with no market request"
        ),
        "effect_on_collected_evidence": "none: no window, no observation and no hash changes",
    }
    return {
        "scenario": "2. the last eligible slot, and the boundary slot the period closes inside",
        "verdict": checks_pass(checks),
        "checks": checks,
        "eligible_run": eligible_run,
        "boundary_run": boundary_run,
        "declared_deviation": deviation,
        "reading": (
            "the plan arithmetic is the declared 84 windows and the boundary slot is not one of "
            "them; the shipped due rule is not bounded by the plan, and that is declared here"
        ),
    }


def scenario_3_to_6_close_sequence(
    root: Path, recorder: Recorder, head: str
) -> list[dict[str, Any]]:
    sandbox = Sandbox("close-sequence", root / "close-sequence")
    # one module instance closes; a second one (fresh import) proves the no-op after the close
    module = load_tick(sandbox, recorder, head)
    closed = run_tick(module, sandbox, CLOSE_INSTANT, ["--due", "--scheduled"])
    closure = read_json(sandbox.closure) or {}
    period = sandbox.period()
    slots = declared_slots(period, parse_instant(CLOSE_INSTANT))
    missed_rows = read_jsonl(sandbox.missed)
    declared_keys = {slot["key"] for slot in slots}
    observed_keys = {f"{row['day']}#{row['slot_index']}" for row in read_jsonl(sandbox.windows)}
    missed_keys = [row["slot_key"] for row in missed_rows]

    last_event = closed["last_run"] or {}
    close_checks = {
        "the close returned the declared terminal status": closed["exit_code"] == 3,
        "no market request was made": closed["network_attempts"] == 0,
        "no window and no raw snapshot were added": closed["delta"]["windows"] == 0
        and closed["delta"]["raw_files"] == 0,
        "the consolidation was written": closed["delta"]["closure_written"],
        "the consolidation is the declared artefact of this period": closure.get("artifact")
        == "ST6_PERIOD_CLOSURE"
        and (closure.get("period") or {}).get("started_at_utc") == PERIOD_START
        and (closure.get("period") or {}).get("ends_at_utc") == CLOSE_INSTANT,
        "the period was never extended": closure.get("auto_extended") is False,
        "the terminal state is declared": closure.get("terminal_state")
        == "PERIOD_CLOSED_NO_FURTHER_COLLECTION",
        "the transition of the schedule itself is recorded": (
            closure.get("terminal_transition") or {}
        ).get("recorded")
        is True,
        "the post-close contract is written into the consolidation": (
            closure.get("post_close_contract") or {}
        ).get("new_market_requests")
        == 0,
        "the outcome is one of the four declared classifications": closure.get("outcome")
        in OUTCOMES,
        "the run event says the period ended": last_event.get("result")
        == "PERIOD_ENDED_CONSOLIDATED"
        and last_event.get("exit_code") == 3
        and int(last_event.get("market_requests") or 0) == 0,
        "the delegated verifiers were invoked through their own programs": len(
            recorder.verifier_delegations
        )
        >= 1,
        "no program other than those delegations was spawned": not recorder.subprocess_attempts,
    }
    after_close_checks = {
        "exactly one consolidation": closed["delta"]["closure_written"],
    }

    # 4 and 5: a tick after the close, and repeated execution after the close
    module_after = load_tick(sandbox, recorder, head)
    closure_hash = sha256_file(sandbox.closure)
    runs_before = sandbox.state()["runs"]
    after_close = run_tick(module_after, sandbox, "2026-10-22T18:00:00Z", ["--due", "--scheduled"])
    repeats = [
        run_tick(module_after, sandbox, instant, ["--due", "--scheduled"])
        for instant in ("2026-10-22T19:00:00Z", "2026-10-30T00:00:00Z", "2026-11-05T12:00:00Z")
    ]
    idempotency_checks = {
        "a tick after the close returns the terminal status": after_close["exit_code"] == 3,
        "it appends no run event": sandbox.state()["runs"] == runs_before
        and after_close["delta"]["runs"] == 0,
        "it rewrites no artefact": sha256_file(sandbox.closure) == closure_hash,
        "it takes no sample": after_close["delta"]["windows"] == 0,
        "repeated execution is equally inert": all(
            repeat["exit_code"] == 3
            and repeat["delta"]["runs"] == 0
            and repeat["delta"]["windows"] == 0
            for repeat in repeats
        ),
        "the consolidation stayed byte-identical across every repetition": sha256_file(
            sandbox.closure
        )
        == closure_hash,
        "no market request in any repetition": after_close["network_attempts"] == 0
        and all(repeat["network_attempts"] == 0 for repeat in repeats),
    }

    # 6: unattended windows
    expected_missed = PLANNED_WINDOWS - len(observed_keys)
    missed_checks = {
        "every declared slot that ended without a window is recorded as missed": sorted(missed_keys)
        == sorted(declared_keys - observed_keys),
        "the number of missed windows is the plan minus what was observed": len(missed_keys)
        == expected_missed,
        "nothing was reconstructed": all(row.get("reconstructed") is False for row in missed_rows),
        "every missed window states a reason": all(row.get("reason") for row in missed_rows),
        "no missed window duplicates another": len(set(missed_keys)) == len(missed_keys),
        "the boundary slot the period closes inside is neither observed nor missed": (
            BOUNDARY_SLOT_NOT_DECLARED not in missed_keys
            and BOUNDARY_SLOT_NOT_DECLARED not in observed_keys
        ),
        "the observed windows are inside the declared plan": observed_keys <= declared_keys,
        "the coverage denominator is still the declared 84": (
            (closure.get("coverage_total") or {}).get("planned_windows") == PLANNED_WINDOWS
        ),
    }
    period_arithmetic_checks = {
        "the plan counted from the start's own slot is 84 windows": len(slots) == 84,
        "the observed windows still reproduce their raw evidence": all(
            raw_sha256(sandbox.raw_dir / f"{row['window_id']}.json.gz")
            == row["raw"]["uncompressed_sha256"]
            for row in read_jsonl(sandbox.windows)
        ),
    }

    return [
        {
            "scenario": "3. the exact close instant",
            "verdict": checks_pass(close_checks | after_close_checks),
            "checks": close_checks | after_close_checks,
            "result": closed,
            "closure_outcome": closure.get("outcome"),
            "closure_sha256": sha256_file(sandbox.closure),
            "reading": (
                "the consolidation is written once, the missed windows are named, the terminal "
                "state is declared and the tick that produced it sampled nothing"
            ),
            "sandbox": str(sandbox.root),
        },
        {
            "scenario": "4. and 5. a tick after the close, and repeated execution after the close",
            "verdict": checks_pass(idempotency_checks),
            "checks": idempotency_checks,
            "result": after_close,
            "repeats": repeats,
            "reading": (
                "the terminal transition is idempotent: later ticks sample nothing, rewrite "
                "nothing and append no run event"
            ),
        },
        {
            "scenario": "6. unattended windows",
            "verdict": checks_pass(missed_checks | period_arithmetic_checks),
            "checks": missed_checks | period_arithmetic_checks,
            "missed_windows": len(missed_keys),
            "observed_windows": len(observed_keys),
            "declared_windows": len(declared_keys),
            "reading": (
                "a slot that passed without a measurement is written down as a loss with its "
                "reason, never invented, and the denominator stays the declared plan"
            ),
        },
    ]


def scenario_7_concurrency(root: Path, recorder: Recorder, head: str) -> dict[str, Any]:
    sandbox = Sandbox("concurrency", root / "concurrency")
    module = load_tick(sandbox, recorder, head)
    FrozenClock.set(parse_instant("2026-10-08T22:00:00Z"))
    lease = module.run_lease()
    acquired = lease.acquire(now=int(FrozenClock.now(UTC).timestamp()))
    try:
        result = run_tick(module, sandbox, "2026-10-08T22:00:00Z", ["--due", "--scheduled"])
        last = result["last_run"] or {}
        release = lease.release()
    finally:
        if lease.path.exists():
            lease.release()
    checks = {
        "the first writer holds the lease": acquired["acquired"] is True,
        "the second writer refuses with the declared status": result["exit_code"] == 2,
        "the refusal is recorded in the run log": last.get("result") == "ALREADY_RUNNING",
        "the refusal makes no market request": int(last.get("market_requests") or 0) == 0,
        "the refusal collects nothing": result["delta"]["windows"] == 0,
        "the refusal reaches no market either": result["network_attempts"] == 0,
        "the lease is released afterwards": release.get("released") is True,
    }
    return {
        "scenario": "7. concurrent execution",
        "verdict": checks_pass(checks),
        "checks": checks,
        "result": result,
        "reading": (
            "a second writer is refused by the shared lease, records the refusal and touches "
            "nothing"
        ),
    }


def scenario_8_corrupt_data(root: Path, recorder: Recorder, head: str) -> dict[str, Any]:
    """Two independent corruptions: a tampered hash, and corrupt raw bytes."""
    results: list[dict[str, Any]] = []

    tampered = Sandbox("corrupt-hash", root / "corrupt-hash")
    rows = read_jsonl(tampered.windows)
    rows[0]["raw"]["uncompressed_sha256"] = "0" * 64
    write_jsonl(tampered.windows, rows)
    module = load_tick(tampered, recorder, head)
    run = run_tick(module, tampered, CLOSE_INSTANT, ["--due", "--scheduled"])
    closure = read_json(tampered.closure) or {}
    reported = (
        (read_json(tampered.base / "ST6_FORWARD_REGIME_REPORT.json") or {})
        .get("errors", {})
        .get("evidence_failures", [])
    )
    checks = {
        "the close still happened": run["exit_code"] == 3 and run["delta"]["closure_written"],
        "a tampered window hash is classified as a data quality failure": closure.get("outcome")
        == "DATA_QUALITY_FAILED",
        "the tampered artefact is named in the terminal consolidation": bool(
            [
                failure
                for failure in (closure.get("evidence_failures") or [])
                if "sha256 mismatch" in failure
            ]
        ),
        "the report of the same run names it too": bool(
            [failure for failure in reported if "sha256 mismatch" in failure]
        ),
    }
    results.append(
        {
            "case": "a window index row whose recorded hash no longer matches its bytes",
            "verdict": checks_pass(checks),
            "checks": checks,
            "closure_outcome": closure.get("outcome"),
            "result": run,
        }
    )

    corrupted = Sandbox("corrupt-bytes", root / "corrupt-bytes")
    target = sorted(corrupted.raw_dir.glob("*.json.gz"))[0]
    target.write_bytes(b"this is not gzip evidence")
    module_corrupt = load_tick(corrupted, recorder, head)
    run_corrupt = run_tick(module_corrupt, corrupted, CLOSE_INSTANT, ["--due", "--scheduled"])
    closure_corrupt = read_json(corrupted.closure) or {}
    reported_corrupt = (
        (read_json(corrupted.base / "ST6_FORWARD_REGIME_REPORT.json") or {})
        .get("errors", {})
        .get("evidence_failures", [])
    )
    checks_corrupt = {
        "corrupt raw bytes never close as supported": closure_corrupt.get("outcome")
        != "COST_MODEL_SUPPORTED_IN_OBSERVED_REGIMES",
        "the corruption is either classified or the close refuses loudly": (
            closure_corrupt.get("outcome") == "DATA_QUALITY_FAILED"
            and run_corrupt["exception_kind"] is None
        )
        or run_corrupt["exception_kind"] is not None,
        "the corrupt artefact is named when the close classified it": (
            run_corrupt["exception_kind"] is not None
            or bool(closure_corrupt.get("evidence_failures"))
            or bool(reported_corrupt)
        ),
        "no window is invented from the corrupt bytes": run_corrupt["delta"]["windows"] == 0,
    }
    results.append(
        {
            "case": "raw bytes that are not the evidence they claim to be",
            "verdict": checks_pass(checks_corrupt),
            "checks": checks_corrupt,
            "closure_outcome": closure_corrupt.get("outcome"),
            "exception_kind": run_corrupt["exception_kind"],
            "result": run_corrupt,
            "note": (
                "when the raw bytes are not gzip at all the close raises instead of classifying; "
                "the independent verifier's negative test requires the corruption to be detected, "
                "which it is, either as DATA_QUALITY_FAILED or as a refused run"
            ),
        }
    )

    duplicated = Sandbox("duplicate", root / "duplicate")
    window_rows = read_jsonl(duplicated.windows)
    write_jsonl(duplicated.windows, [*window_rows, window_rows[0]])
    run_rows = read_jsonl(duplicated.runs)
    if run_rows:
        write_jsonl(duplicated.runs, [*run_rows, run_rows[-1]])
    module_duplicate = load_tick(duplicated, recorder, head)
    run_duplicate = run_tick(module_duplicate, duplicated, CLOSE_INSTANT, ["--due", "--scheduled"])
    results.append(
        {
            "case": "a duplicated window index row",
            "verdict": "PASS",
            "tick_detects_duplicates_in_the_close": False,
            "checks": {
                "the tick consolidates what the index says instead of silently deduplicating": (
                    run_duplicate["exit_code"] == 3
                ),
                "no window is added by the close itself": run_duplicate["delta"]["windows"] == 0,
            },
            "tick_detects_duplicates": False,
            "note": (
                "duplicate detection is the independent verifier's check, not the tick's: the "
                "verifier's negative test proves it fires on a duplicated index row"
            ),
            "result": run_duplicate,
        }
    )

    all_checks = {
        f"{entry['case']}: {name}": ok for entry in results for name, ok in entry["checks"].items()
    }
    all_checks["none of the corrupted states reached the market"] = all(
        entry["result"]["network_attempts"] == 0 for entry in results
    )
    return {
        "scenario": "8. corrupt data and duplication",
        "verdict": checks_pass(all_checks),
        "checks": all_checks,
        "cases": results,
        "reading": (
            "corruption is refused rather than blessed; a duplicate is left to the verifier, which "
            "is proven to fail on it in the negative tests"
        ),
    }


def scenario_9_missing_evidence(root: Path, recorder: Recorder, head: str) -> dict[str, Any]:
    sandbox = Sandbox("missing-evidence", root / "missing-evidence")
    target = sorted(sandbox.raw_dir.glob("*.json.gz"))[0]
    target.unlink()
    module = load_tick(sandbox, recorder, head)
    run = run_tick(module, sandbox, CLOSE_INSTANT, ["--due", "--scheduled"])
    closure = read_json(sandbox.closure) or {}
    failures = list(closure.get("evidence_failures") or [])
    if not failures:
        failures = list(
            (read_json(sandbox.base / "ST6_FORWARD_REGIME_REPORT.json") or {})
            .get("errors", {})
            .get("evidence_failures", [])
        )
    checks = {
        "the missing evidence is classified as a data quality failure": closure.get("outcome")
        == "DATA_QUALITY_FAILED",
        "the absent artefact is named": any(target.name in failure for failure in failures),
        "the consolidation is still written with its drift and coverage": closure.get(
            "drift_preserved"
        )
        is not None
        and closure.get("coverage_total") is not None
        and bool(closure.get("st6_verdict"))
        and bool(closure.get("drift_preserved", {}).get("policy")),
        "no market request was made to refill the missing evidence": run["network_attempts"] == 0,
        "no window is invented for the missing snapshot": run["delta"]["windows"] == 0,
    }
    return {
        "scenario": "9. missing evidence",
        "verdict": checks_pass(checks),
        "checks": checks,
        "closure_outcome": closure.get("outcome"),
        "evidence_failures": failures,
        "result": run,
        "reading": (
            "an absent raw snapshot fails the data quality rule and is named; nothing is "
            "reconstructed and no request is made to replace it"
        ),
    }


def scenario_11_extension_flag(root: Path, recorder: Recorder, head: str) -> dict[str, Any]:
    """The declared extension policy against the shipped flag: measured, not read off the help."""
    during = Sandbox("extension-during", root / "extension-during")
    module_during = load_tick(during, recorder, head)
    run_during = run_tick(
        module_during,
        during,
        "2026-10-09T02:00:00Z",
        ["--collect", "--authorize-extension"],
    )
    during_event = run_during["last_run"] or {}

    after = Sandbox("extension-after", root / "extension-after")
    module_after = load_tick(after, recorder, head)
    run_after = run_tick(
        module_after,
        after,
        CLOSE_INSTANT,
        ["--due", "--scheduled", "--authorize-extension"],
    )
    after_event = run_after["last_run"] or {}

    checks = {
        "during the open period the flag does not enable a sample either": run_during[
            "network_attempts"
        ]
        == 0
        and run_during["delta"]["windows"] == 0,
        "during the open period the flagged tick records itself as report-only": during_event.get(
            "result"
        )
        == "REPORT_ONLY",
        "after the declared end the flag does not extend the period": run_after["exit_code"] == 3
        and run_after["delta"]["windows"] == 0
        and run_after["network_attempts"] == 0,
        "after the declared end the flagged tick still closes and records the terminal status": (
            after_event.get("result") == "PERIOD_ENDED_CONSOLIDATED"
            and after_event.get("exit_code") == 3
        ),
        "the consolidation of the flagged close refuses extension": (
            (read_json(after.closure) or {}).get("auto_extended") is False
        ),
    }
    deviation = {
        "id": "EXTENSION-FLAG-INERT",
        "declared_contract": (
            "the period file declares: 'after ends_at_utc collection stops unless a human passes "
            "--authorize-extension, and that flag never turns an incomplete period into a PASS'"
        ),
        "shipped_behaviour": (
            "the ended branch returns before the collection branch, so the flag cannot extend "
            "anything; and the collection branch is itself guarded by `not "
            "args.authorize_extension`, so passing the flag during the open period suppresses "
            "collection and turns the tick into a report-only run"
        ),
        "measured_here": {
            "during_open_period": {
                "argv": run_during["argv"],
                "exit_code": run_during["exit_code"],
                "windows_added": run_during["delta"]["windows"],
                "market_attempts": run_during["network_attempts"],
                "event": during_event.get("result"),
            },
            "after_the_end": {
                "argv": run_after["argv"],
                "exit_code": run_after["exit_code"],
                "windows_added": run_after["delta"]["windows"],
                "market_attempts": run_after["network_attempts"],
                "event": after_event.get("result"),
            },
        },
        "why_it_is_declared_and_not_silently_fixed": (
            "the flag is a governance escape hatch: giving it effect is a policy decision about the "
            "closed period, not a repair, and the mission requires the inconsistency to be "
            "declared"
        ),
        "minimal_correction": (
            "either honour the flag in a guarded branch (`if ended and not args.authorize_extension:` "
            "consolidate; else collect), keeping the 'never turns an incomplete period into a PASS' "
            "rule, or amend the declared text to state that the period never extends"
        ),
        "effect_on_collected_evidence": "none: no window, no observation and no hash changes",
    }
    return {
        "scenario": "11. the declared extension policy against the shipped flag",
        "verdict": checks_pass(checks),
        "checks": checks,
        "during_open_period": run_during,
        "after_the_end": run_after,
        "declared_deviation": deviation,
        "reading": (
            "the flag is inert in both directions: it cannot extend the period, and during the "
            "period it suppresses collection"
        ),
    }


def scenario_10_restart_recovery(root: Path, recorder: Recorder, head: str) -> dict[str, Any]:
    """A host restart is a fresh process reading the same state: the close must reproduce."""
    first = Sandbox("restart-first", root / "restart-first")
    module_first = load_tick(first, recorder, head)
    run_first = run_tick(module_first, first, CLOSE_INSTANT, ["--due", "--scheduled"])
    first_hash = sha256_file(first.closure) if first.closure.exists() else None

    second = first.clone("restart-second", root)
    module_second = load_tick(second, recorder, head)
    run_second = run_tick(module_second, second, CLOSE_INSTANT, ["--due", "--scheduled"])
    second_hash = sha256_file(second.closure) if second.closure.exists() else None

    # and a fresh process after the close reads the terminal state and does nothing
    after = run_tick(module_second, second, "2026-10-23T06:00:00Z", ["--due", "--scheduled"])
    checks = {
        "a fresh process closes the state the same way": run_first["exit_code"] == 3
        and run_second["exit_code"] == 3,
        "the consolidation is byte-identical across a simulated restart": first_hash is not None
        and first_hash == second_hash,
        "the second process rewrote nothing it did not need to": run_second["delta"]["windows"]
        == 0,
        "a fresh process after the close is inert": after["exit_code"] == 3
        and after["delta"]["runs"] == 0
        and sha256_file(second.closure) == second_hash,
        "no market request at any point": run_first["network_attempts"] == 0
        and run_second["network_attempts"] == 0
        and after["network_attempts"] == 0,
    }
    return {
        "scenario": "10. recovery after a host restart",
        "verdict": checks_pass(checks),
        "checks": checks,
        "closure_sha256_first": first_hash,
        "closure_sha256_second": second_hash,
        "first_run": run_first,
        "second_run": run_second,
        "after_restart_run": after,
        "reading": (
            "the close depends only on the state on disk and the injected clock: a fresh process "
            "reproduces it byte for byte, and a later process reads the terminal state and stops"
        ),
    }


# ------------------------------------------------------------------------------------------------
# report
# ------------------------------------------------------------------------------------------------


def render_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# ST-6 — isolated close replay",
        "",
        f"Generated {report['generated_at_utc']} at `{report['current_head']}`.",
        "",
        f"Inside the sandbox the tick records the code identity as `{report['sandbox_code_identity']}`:",
        "a constant on purpose, so the determinism proof does not depend on the commit hash.",
        "",
        f"Replay of `{report['tick']}` against an isolated copy of the live state, with an injected",
        f"UTC clock. Period `{report['period']['started_at_utc']}` → "
        f"`{report['period']['ends_at_utc']}`; close instant `{report['period']['close_instant']}`.",
        "",
        f"**Close mechanics: {report['close_mechanics_verdict']}** — "
        f"{report['summary']['passed']}/{report['summary']['scenarios']} scenarios PASS, "
        f"{report['summary']['failed']} FAIL, "
        f"{report['summary']['declared_deviations']} declared deviation(s).",
        "",
        "## Scenarios",
        "",
        "| # | scenario | verdict |",
        "| --- | --- | --- |",
    ]
    for entry in report["scenarios"]:
        lines.append(f"| | {entry['scenario']} | **{entry['verdict']}** |")
    lines += [
        "",
        "## Isolation and non-interference",
        "",
        f"Sandboxes: `{report['isolation']['sandbox_root']}` (a temporary directory outside the",
        f"repository). Real state unmoved by the replay: "
        f"**{report['isolation']['real_state_unchanged_by_the_replay']}** (identical bytes before "
        f"and after: {report['isolation']['real_state_unchanged']})"
        + (
            f" (live scheduler activity observed during the replay: "
            f"{', '.join(report['isolation']['live_activity_attributed']) or 'none'})"
            if report["isolation"]["live_activity_attributed"]
            else ""
        ),
        "",
        f"Real market requests: {report['isolation']['real_market_requests']}. "
        f"Real scheduler calls: {report['isolation']['real_scheduler_calls']}. "
        f"Market attempts refused by the guard: "
        f"{len(report['isolation']['network_attempts'])}. "
        f"Terminal transitions intercepted: "
        f"{len(report['isolation']['terminal_transitions'])}.",
        "",
        "## Declared boundary deviations",
        "",
    ]
    deviations = report.get("boundary_deviations") or []
    if not deviations:
        lines.append("None.")
    for deviation in deviations:
        lines += [
            f"### {deviation['id']}",
            "",
            f"- contract: {deviation['declared_contract']}",
            f"- shipped behaviour: {deviation['shipped_behaviour']}",
            f"- minimal correction: {deviation['minimal_correction']}",
            f"- effect on collected evidence: {deviation['effect_on_collected_evidence']}",
            "",
        ]
    lines += [
        "## What the replay does not claim",
        "",
        "- it does not sample the market: a slot that is due is recorded as *refused by the guard*,",
        "  never filled with invented evidence;",
        "- it does not run the delegated verifiers inside the sandbox: the delegation is intercepted",
        "  and recorded (`NOT_EXECUTED_IN_REPLAY`), so a sandbox run event never claims a",
        "  verification that did not run;",
        "- it is not evidence about the real period: the real period closes on its own date, and the",
        "  consolidation of the real period is produced by the tick, then verified independently.",
        "",
        "Research only: no orders, no credentials, no capital.",
        "",
    ]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out-json", default=str(OUT_JSON))
    parser.add_argument("--out-md", default=str(OUT_MD))
    parser.add_argument("--sandbox-root", default=None)
    parser.add_argument("--cleanup", action="store_true", help="remove the sandboxes on exit")
    args = parser.parse_args(argv)

    live_head = (
        __import__("subprocess")
        .run(["git", "rev-parse", "HEAD"], cwd=REPO, capture_output=True, text=True, check=True)
        .stdout.strip()
    )
    # what the sandbox records as the code identity: a constant, so the determinism proof does not
    # depend on the commit hash (the real head is recorded at the top level of this report)
    head = "REPLAY_SANDBOX_NOT_A_COMMIT"
    root = (
        Path(args.sandbox_root)
        if args.sandbox_root
        else Path(tempfile.mkdtemp(prefix="st6-close-replay-"))
    )
    root.mkdir(parents=True, exist_ok=True)
    recorder = Recorder()
    real_before = fingerprint_real_state()

    real_urlopen = urllib.request.urlopen

    def blocked_urlopen(*call_args: Any, **call_kwargs: Any) -> Any:
        recorder.network_attempts.append(
            {"what": "urllib.request.urlopen", "args": [str(a)[:120] for a in call_args][:2]}
        )
        raise MarketAccessForbidden("the replay forbids any outbound request")

    urllib.request.urlopen = blocked_urlopen  # type: ignore[assignment]
    try:
        scenarios: list[dict[str, Any]] = []
        scenarios.append(scenario_1_before_close(root, recorder, head))
        scenarios.append(scenario_2_boundary(root, recorder, head))
        scenarios.extend(scenario_3_to_6_close_sequence(root, recorder, head))
        scenarios.append(scenario_7_concurrency(root, recorder, head))
        scenarios.append(scenario_8_corrupt_data(root, recorder, head))
        scenarios.append(scenario_9_missing_evidence(root, recorder, head))
        scenarios.append(scenario_10_restart_recovery(root, recorder, head))
        scenarios.append(scenario_11_extension_flag(root, recorder, head))
    finally:
        urllib.request.urlopen = real_urlopen  # type: ignore[assignment]

    real_after = fingerprint_real_state()
    moved = sorted(
        relative
        for relative in set(real_before) | set(real_after)
        if real_before.get(relative) != real_after.get(relative)
    )
    # a live tick keeps working while this runs: its own artefacts are attributed, not excused
    live_files = {
        "data/st6/ST6_RUNS.jsonl",
        "data/st6/ST6_HEALTH.jsonl",
        "data/st6/ST6_HEALTH_STATUS.json",
        "data/st6/ST6_SCHEDULER_REPORT.json",
        "data/st6/ST6_SCHEDULER_REPORT.md",
        "data/st6/ST6_WINDOWS.jsonl",
        "data/st6/ST6_OBSERVATIONS.jsonl",
        "data/st6/ST6_REGIME_COVERAGE.json",
        "data/st6/ST6_MODEL_DRIFT.json",
        "data/st6/ST6_FORWARD_REGIME_REPORT.json",
        "data/st6/ST6_FORWARD_REGIME_REPORT.md",
        "data/st6/ST6_MISSED_WINDOWS.jsonl",
        "data/st6/scheduler_lock/CAMPAIGN_LOCK.json",
    }
    unexplained = [relative for relative in moved if relative not in live_files]

    close_scenarios = [
        entry
        for entry in scenarios
        if entry["scenario"][0] in "3456789"
        or entry["scenario"].startswith("10")
        or entry["scenario"].startswith("11")
    ]
    close_failures = [entry for entry in close_scenarios if entry["verdict"] == "FAIL"]
    boundary = scenarios[1]
    extension = scenarios[-1]
    report: dict[str, Any] = {
        "artifact": REPLAY_VERSION,
        "generated_at_utc": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "current_head": live_head,
        "sandbox_code_identity": head,
        "tick": "scripts/st6_forward_regime.py",
        "tick_sha256": sha256_file(TICK),
        "period": {
            "started_at_utc": PERIOD_START,
            "ends_at_utc": CLOSE_INSTANT,
            "close_instant": CLOSE_INSTANT,
            "declared_days": DECLARED_DAYS,
            "slots_per_day": SLOTS_PER_DAY,
            "planned_windows": PLANNED_WINDOWS,
        },
        "method": (
            "the real tick is imported and its every path is redirected into a private copy of the "
            "live state; the clock is a frozen datetime placed in the tick's own namespace; the "
            "probe, the kline reader and urllib are blocked; the task registration and the terminal "
            "transition are intercepted; the real state is fingerprinted before and after"
        ),
        "clock_injection": {
            "mechanism": "FrozenClock, a datetime subclass placed in the tick's namespace",
            "system_clock_changed": False,
            "instants_used": sorted(
                {
                    entry["result"]["instant"]
                    for entry in scenarios
                    if isinstance(entry.get("result"), dict) and entry["result"].get("instant")
                }
            ),
        },
        "summary": summarise(scenarios),
        "close_mechanics_verdict": "PASS" if not close_failures else "FAIL",
        "scenarios": scenarios,
        "boundary_deviations": [boundary["declared_deviation"], extension["declared_deviation"]],
        "isolation": {
            "sandbox_root": str(root),
            "sandbox_outside_repository": not str(root).startswith(str(REPO)),
            "redirected_constants": list(REDIRECTED_CONSTANTS),
            "real_state_unchanged": not moved,
            "real_state_unchanged_by_the_replay": not unexplained,
            "real_files_that_moved": moved,
            "live_activity_attributed": [f for f in moved if f in live_files],
            "unexplained_changes": unexplained,
            "real_market_requests": 0,
            "real_scheduler_calls": 0,
            "network_attempts": recorder.network_attempts,
            "subprocess_attempts": recorder.subprocess_attempts,
            "verifier_delegations": recorder.verifier_delegations,
            "terminal_transitions": recorder.terminal_transitions,
            "scheduler_queries": recorder.scheduler_queries,
        },
        "false_success": 0 if not close_failures else len(close_failures),
        "does_not_prove": [
            "that the real period will close on its own date: it proves how the close behaves",
            "that the market data of a slot the guard refused is anything: nothing was sampled",
            "that the delegated verifiers pass: they are intercepted inside the replay",
        ],
    }
    out_json = Path(args.out_json)
    out_json.parent.mkdir(parents=True, exist_ok=True)
    out_json.write_text(
        json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
        # the bytes of an artefact whose hashes are recorded must not depend on the platform's
        # line separator: without this, Windows writes CRLF and the recorded digest describes a
        # file that no other host, and no reader of the committed bytes, can reproduce
        newline="\n",
    )
    out_md = Path(args.out_md)
    out_md.write_text(render_markdown(report), encoding="utf-8", newline="\n")
    print(
        f"{report['close_mechanics_verdict']}: close mechanics {report['summary']['passed']}/"
        f"{report['summary']['scenarios']} scenarios PASS, {report['summary']['failed']} FAIL; "
        f"real state unchanged: {report['isolation']['real_state_unchanged']}; "
        f"market requests: 0"
    )
    for entry in scenarios:
        if entry["verdict"] == "FAIL":
            print(f"  FAIL {entry['scenario']}")
            for name, ok in entry["checks"].items():
                if not ok:
                    print(f"       {name}")
    print(f"written -> {out_json}, {out_md}")
    if args.cleanup:
        shutil.rmtree(root, ignore_errors=True)
    return 0 if not close_failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
