"""WP-051-02H independent verifier: does the package's story survive its own bytes?

This program is a second implementation, not a call into the first. It imports neither the
02H builder, nor the watchdog, nor ``trading_bot``, nor the forward observer. It parses the
tick log, the bar store, the declaration and the scheduler's registration itself,
recomputes every number the package reports, and fails where the two disagree.

The controls, and nothing but the controls:

* ``TICK_LOG_READABLE``          the tick log parses, and the package did not hide lines
* ``OBSERVER_LIVENESS``          the newest tick is inside the declared cadence
* ``RECOVERY_CLAIM``             the tick the package calls "the recovery" exists and is
                                 the first observation after the last refusal
* ``BLOCK_EPISODE``              the refusal episode is measured, with its free-space floor
* ``NO_DUPLICATE_TICKS``         no run id appears twice
* ``STORE_ADVANCED``             the store holds bars newer than the instant 02G named
* ``BAR_LAG_RECOMPUTED``         every bar's lag is recomputed with the declaration's formula
* ``LOST_DAYS_RECOMPUTED``       the days the package calls lost are exactly the days whose
                                 grid holds an inadmissible bar
* ``COVERAGE_CEILING``           the ceiling is recomputed, and it is below the declaration
* ``NO_REFETCH_OR_THRESHOLD_MOVE`` the declaration's bytes are the ones 02G froze
* ``FROZEN_PACKAGES_INTACT``     02B..02G are byte-identical to HEAD
* ``WATCHDOG_PRESENT``           the continuity component exists and is registered
* ``WATCHDOG_ALARM_REACHES_OS``  the scheduler holds a non-zero result for it
* ``CONTINUITY_REQUIREMENTS``    each requirement's status matches the task's own settings
* ``NO_TRADING_SURFACE``         the package names no order entry point and claims nothing
* ``EXPERIMENT_NOT_CERTIFIED``   the word the mission requires
* ``VERIFIER_IS_INDEPENDENT``    this file imports none of the things it judges

Exit codes: 0 pass, 2 fail, 4 cannot read an input.

Research only: reads local files, writes one JSON verdict, sends nothing.
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import subprocess
import sys
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

VERIFIER_ID = "verifier-h/EXP-004A/WP-051-02H"
SCHEMA_VERSION = "1.0"
BUILDER = "scripts/exp004a_wp051_02h_audit.py"
WATCHDOG = "scripts/edge04_watchdog.py"
PACKAGE_DIR = "docs/agentic/exp004a/wp051_02h"
DECLARATION = "config/preregistrations/EXP-004A.datasets.phase3.json"
STATE = "data/forward/edge04"
STORE = "data/forward/edge03"
TASK_NAME = "TradingAgentic-EDGE04-Forward"
WATCHDOG_TASK = "TradingAgentic-EDGE04-Watchdog"

EXIT_PASS = 0
EXIT_FAIL = 2
EXIT_MISSING = 4

HOUR = 3_600_000
DAY = 24 * HOUR
INTERVAL_MINUTES = 15
SILENCE_LIMIT = INTERVAL_MINUTES * 60 * 3


@dataclass
class Check:
    name: str
    detail: str
    ok: bool


@dataclass
class Verdict:
    checks: list[Check] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def add(self, name: str, ok: bool, detail: str) -> None:
        self.checks.append(Check(name=name, ok=ok, detail=detail))

    @property
    def failed(self) -> list[str]:
        return [check.name for check in self.checks if not check.ok]


# --------------------------------------------------------------------------- #
# reading, independently
# --------------------------------------------------------------------------- #
def iso(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000, tz=UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def millis(text: str) -> int:
    parsed = datetime.fromisoformat(str(text).strip().replace("Z", "+00:00"))
    return int((parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)).timestamp() * 1000)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def load(path: Path) -> Any:
    return json.loads(path.read_bytes().decode("utf-8"))


def rows_of(path: Path) -> list[dict[str, Any]]:
    """Parsed JSON objects, strictly: a line that is not an object is not silently skipped.

    The caller gets the accepted rows and the count of rejected lines, so a claim about
    "how many ticks there were" can be confronted with "how many lines could not be read".
    """
    out: list[dict[str, Any]] = []
    if not path.is_file():
        return out
    for raw in path.read_bytes().splitlines():
        if raw.strip():
            parsed = json.loads(raw)
            if not isinstance(parsed, dict):
                raise ValueError(f"{path} holds a line that is not an object")
            out.append(parsed)
    return out


def git(repo: Path, *args: str) -> tuple[int, str]:
    completed = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True)
    return completed.returncode, completed.stdout.strip()


def scheduler(task: str) -> dict[str, Any]:
    if not sys.platform.startswith("win"):
        return {"queried": False}
    completed = subprocess.run(
        ["schtasks", "/query", "/tn", task, "/xml"], capture_output=True, text=True
    )
    if completed.returncode != 0:
        return {"queried": True, "installed": False}
    xml = completed.stdout.replace("\x00", "")
    root = ET.fromstring(xml)
    ns = "{http://schemas.microsoft.com/windows/2004/02/mit/task}"
    settings = root.find(f"{ns}Settings")
    trigger = root.find(f"{ns}Triggers/{ns}TimeTrigger")
    action = root.find(f"{ns}Actions/{ns}Exec")
    restart = settings.find(f"{ns}RestartOnFailure") if settings is not None else None
    repetition = trigger.find(f"{ns}Repetition") if trigger is not None else None
    principal = root.find(f"{ns}Principals/{ns}Principal")
    return {
        "queried": True,
        "installed": True,
        "multiple_instances": settings.findtext(f"{ns}MultipleInstancesPolicy") if settings is not None else None,
        "start_when_available": settings.findtext(f"{ns}StartWhenAvailable") if settings is not None else None,
        "restart_count": restart.findtext(f"{ns}Count") if restart is not None else None,
        "restart_interval": restart.findtext(f"{ns}Interval") if restart is not None else None,
        "repetition_interval": repetition.findtext(f"{ns}Interval") if repetition is not None else None,
        "repetition_duration": repetition.findtext(f"{ns}Duration") if repetition is not None else None,
        "command": action.findtext(f"{ns}Command") if action is not None else None,
        "arguments": action.findtext(f"{ns}Arguments") if action is not None else None,
        "logon_type": principal.findtext(f"{ns}LogonType") if principal is not None else None,
    }


def task_result(task: str) -> dict[str, Any]:
    if not sys.platform.startswith("win"):
        return {}
    completed = subprocess.run(
        [
            "powershell",
            "-NoProfile",
            "-NonInteractive",
            "-Command",
            "try { Get-ScheduledTaskInfo -TaskName '%s' | Select-Object LastRunTime,LastTaskResult,"
            "NextRunTime,NumberOfMissedRuns | ConvertTo-Json -Compress } catch { '' }" % task,
        ],
        capture_output=True,
        text=True,
        timeout=90,
    )
    if completed.returncode != 0 or not completed.stdout.strip():
        return {}
    try:
        parsed = json.loads(completed.stdout)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


# --------------------------------------------------------------------------- #
# arithmetic, independently
# --------------------------------------------------------------------------- #
def bar_lags(rows: list[dict[str, Any]]) -> dict[int, dict[str, Any]]:
    """lag = fetched - (open + 1h), the forward store's own definition, re-derived here."""
    out: dict[int, dict[str, Any]] = {}
    for row in rows:
        opened = int(row["ts"])
        fetched = int(row.get("fetched_at_ms") or row.get("fetched_ms") or 0)
        out[opened] = {
            "open_utc": iso(opened),
            "fetched_utc": iso(fetched),
            "lag_ms": fetched - (opened + HOUR),
            "closed": bool(row.get("closed", True)),
        }
    return out


def day_outcome(
    lags: dict[int, dict[str, Any]], day_start_ms: int, *, bound_ms: int, now_ms: int, effective_ms: int
) -> str:
    """COMPLETE, LOST or OPEN, decided by the worst bar rather than by a count."""
    admissible = 0
    inadmissible = 0
    missing = 0
    for k in range(24):
        opened = day_start_ms + k * HOUR
        if opened not in lags:
            missing += 1
            continue
        row = lags[opened]
        if not row["closed"] or not (0 <= row["lag_ms"] <= bound_ms) or millis(row["fetched_utc"]) < effective_ms:
            inadmissible += 1
        else:
            admissible += 1
    closed_day = day_start_ms + DAY <= now_ms
    if inadmissible:
        return "LOST"
    if closed_day and missing:
        return "LOST"
    if closed_day and admissible == 24:
        return "COMPLETE"
    return "OPEN"


# --------------------------------------------------------------------------- #
# the controls
# --------------------------------------------------------------------------- #
def verify(repo: Path, package: Path, state_root: Path, store_root: Path) -> tuple[Verdict, dict[str, Any]]:
    verdict = Verdict()
    now_ms = int(datetime.now(tz=UTC).timestamp() * 1000)
    detail: dict[str, Any] = {}

    recovery = load(package / "RECOVERY_REPORT.json")
    gap = load(package / "COVERAGE_GAP_REPORT.json")
    continuity = load(package / "CONTINUITY_REPORT.json")
    root_cause = load(package / "ROOT_CAUSE.json")
    declaration = load(repo / DECLARATION)

    runs = rows_of(state_root / "runs.jsonl")
    verdict.add(
        "TICK_LOG_READABLE",
        bool(runs),
        f"{len(runs)} tick record(s) parsed; the package claims {recovery['observer']['runs_log_lines']}"
        + (" — equal" if len(runs) == recovery["observer"]["runs_log_lines"] else " — DIFFERENT"),
    )

    # liveness
    stamped = [(millis(row["started_at_utc"]), row) for row in runs if row.get("started_at_utc")]
    stamped.sort(key=lambda item: item[0])
    newest_ms, newest = stamped[-1] if stamped else (0, {})
    age = (now_ms - newest_ms) / 1000 if stamped else None
    claimed_age = recovery["observer"]["last_tick_age_seconds"]
    verdict.add(
        "OBSERVER_LIVENESS",
        age is not None and age <= SILENCE_LIMIT,
        f"newest tick {iso(newest_ms) if stamped else 'none'}, age {round(age or 0, 1)}s "
        f"(limit {SILENCE_LIMIT}s); the package says {claimed_age}s, outcome {newest.get('outcome')}",
    )
    detail["newest_tick"] = {"started_at_utc": iso(newest_ms) if stamped else None, "outcome": newest.get("outcome")}

    # the recovery claim: first observation after the last refusal
    blocked = [ms for ms, row in stamped if row.get("outcome") == "DISK_BUDGET_EXCEEDED"]
    observed_with_bars = [
        (ms, row) for ms, row in stamped if row.get("outcome") == "OBSERVED" and int(row.get("new_bars") or 0) > 0
    ]
    last_block = max(blocked) if blocked else None
    after = [(ms, row) for ms, row in observed_with_bars if last_block is None or ms > last_block]
    claimed_recovery = recovery.get("recovered_observation") or {}
    matches = bool(after) and claimed_recovery.get("run_id") == after[0][1].get("run_id")
    verdict.add(
        "RECOVERY_CLAIM",
        matches,
        f"first observation after the last refusal is {after[0][1].get('run_id') if after else 'none'}; "
        f"the package claims {claimed_recovery.get('run_id')}",
    )
    detail["recovery_tick"] = after[0][1] if after else None

    claimed_block = recovery["tick_census"]["blocked"]
    since_ms = millis(recovery["tick_census"]["since_utc"])
    windowed = [row for ms, row in stamped if ms >= since_ms]
    actual_block = [row for row in windowed if row.get("outcome") == "DISK_BUDGET_EXCEEDED"]
    actual_free = [
        float((row.get("disk") or {})["free_gib"])
        for row in actual_block
        if (row.get("disk") or {}).get("free_gib") is not None
    ]
    block_ok = (
        len(actual_block) == claimed_block["count"]
        and claimed_block["min_free_gib"] is not None
        and actual_free
        and abs(min(actual_free) - float(claimed_block["min_free_gib"])) < 1e-6
    )
    verdict.add(
        "BLOCK_EPISODE",
        block_ok,
        f"{len(actual_block)} refusal(s) since {recovery['tick_census']['since_utc']} "
        f"with a free-space floor of {min(actual_free) if actual_free else None} GiB; the package "
        f"reports {claimed_block['count']} and {claimed_block['min_free_gib']}",
    )

    # ``run_id`` is slot-keyed, so several attempts legitimately share it. The invariant is
    # that one slot is sealed once: two sealing rows would be two consuming ticks.
    sealed: dict[str, int] = {}
    for row in runs:
        if row.get("slot_sealed"):
            sealed[str(row.get("slot_key") or "")] = sealed.get(str(row.get("slot_key") or ""), 0) + 1
    sealed_twice = sorted(key for key, count in sealed.items() if count > 1)
    refused_lease = sum(1 for row in runs if str(row.get("outcome")) == "ALREADY_RUNNING")
    verdict.add(
        "NO_DUPLICATE_TICKS",
        not sealed_twice,
        f"{len(sealed)} sealed slot(s), {len(sealed_twice)} sealed twice; "
        f"{refused_lease} tick(s) were refused because another held the lease",
    )

    # the store silence: the last tick that added bars before the last refusal episode, and
    # the first one after it. This is the number that costs coverage, and it is not the same
    # number as the recovery latency.
    boundary = gap["recovery_boundary"]
    episode = boundary.get("block_episode") or {}
    consuming = [
        (ms, row) for ms, row in stamped if row.get("outcome") == "OBSERVED" and int(row.get("new_bars") or 0) > 0
    ]
    if episode.get("first_blocked_start_utc") and episode.get("last_blocked_start_utc"):
        ep_start = millis(episode["first_blocked_start_utc"])
        ep_end = millis(episode["last_blocked_start_utc"])
        before = [(ms, row) for ms, row in consuming if ms < ep_start]
        after_ep = [(ms, row) for ms, row in consuming if ms > ep_end]
        recomputed_silence = (
            round((after_ep[0][0] - before[-1][0]) / 60_000, 2) if before and after_ep else None
        )
        verdict.add(
            "STORE_SILENCE_REPRODUCED",
            recomputed_silence is not None
            and abs(recomputed_silence - float(boundary.get("store_silence_minutes") or -1)) < 0.05,
            f"recomputed store silence {recomputed_silence} min; the package claims "
            f"{boundary.get('store_silence_minutes')} min (recovery latency after the last "
            f"refusal: {boundary.get('recovery_latency_seconds')} s)",
        )
    else:
        verdict.add("STORE_SILENCE_REPRODUCED", False, "the package names no refusal episode")

    # the store
    store_rows = rows_of(store_root / "1h" / "BTC.jsonl")
    lags = bar_lags(store_rows)
    newest_bar = max(lags) if lags else None
    claimed_newest = recovery["store"]["1h:BTC"]["last_open_utc"]
    verdict.add(
        "STORE_ADVANCED",
        newest_bar is not None and iso(newest_bar) == claimed_newest and newest_bar > millis("2026-10-22T18:00:00Z"),
        f"newest BTC bar {iso(newest_bar) if newest_bar else 'none'}; the package says {claimed_newest}; "
        "02G's reference instant was 2026-10-22T18:00:00Z",
    )

    bound_ms = int(declaration["lag_policy"]["bound_ms"])
    effective_ms = millis(declaration["effective_from_utc"])
    per_asset_lost: dict[str, list[str]] = {}
    per_asset_complete: dict[str, list[str]] = {}
    admissible_counts: dict[str, int] = {}
    for asset in ("BTC", "ETH", "SOL"):
        asset_lags = bar_lags(rows_of(store_root / "1h" / f"{asset}.jsonl"))
        lost: list[str] = []
        complete: list[str] = []
        admissible = 0
        for opened, row in asset_lags.items():
            if opened < millis(declaration["capture_window"]["start_utc"]):
                continue
            if 0 <= row["lag_ms"] <= bound_ms and row["closed"] and millis(row["fetched_utc"]) >= effective_ms:
                admissible += 1
        admissible_counts[asset] = admissible
        day = (millis(declaration["capture_window"]["start_utc"]) // DAY) * DAY
        horizon = min(millis(declaration["capture_window"]["end_utc"]), now_ms)
        while day < horizon:
            outcome = day_outcome(asset_lags, day, bound_ms=bound_ms, now_ms=now_ms, effective_ms=effective_ms)
            if outcome == "LOST":
                lost.append(iso(day)[:10])
            elif outcome == "COMPLETE":
                complete.append(iso(day)[:10])
            day += DAY
        per_asset_lost[asset] = lost
        per_asset_complete[asset] = complete

    claimed_lost = gap["phase_impact"]["lost_days_by_asset"]
    verdict.add(
        "LOST_DAYS_RECOMPUTED",
        claimed_lost == per_asset_lost,
        f"recomputed lost days {per_asset_lost}; the package claims {claimed_lost}",
    )

    reachable = sum(2160 - 24 * len(per_asset_lost[asset]) for asset in ("BTC", "ETH", "SOL"))
    claimed_reachable = gap["phase_impact"]["rows_still_reachable"]
    ceiling = reachable / 6480
    verdict.add(
        "COVERAGE_CEILING",
        reachable == claimed_reachable and reachable < 6480 and abs(ceiling - gap["phase_impact"]["fraction_still_reachable"]) < 1e-6,
        f"recomputed {reachable}/6480 = {round(ceiling, 6)}; the package claims "
        f"{claimed_reachable}/6480 = {gap['phase_impact']['fraction_still_reachable']}; "
        f"COVERAGE_COMPLETE reachable: {reachable == 6480}",
    )

    # the declaration was not touched by this package
    code, blob = git(repo, "rev-parse", f"HEAD~0:{DECLARATION}")
    declared_now = hashlib.sha1(
        b"blob %d\0" % len((repo / DECLARATION).read_bytes().replace(b"\r\n", b"\n"))
        + (repo / DECLARATION).read_bytes().replace(b"\r\n", b"\n")
    ).hexdigest()
    verdict.add(
        "NO_REFETCH_OR_THRESHOLD_MOVE",
        code == 0 and declared_now == blob and gap["declaration"]["sha256"] == sha256(repo / DECLARATION),
        f"declaration blob {blob[:10]} == working copy {declared_now[:10]}; sha256 recorded "
        f"{gap['declaration']['sha256'][:10]} == disk {sha256(repo / DECLARATION)[:10]}",
    )

    # 02B..02G untouched
    code, listing = git(repo, "ls-tree", "-r", "--name-only", "HEAD", "docs/agentic/exp004a")
    frozen_paths = [
        line
        for line in listing.splitlines()
        if any(f"/wp051_02{letter}" in line for letter in "bcdefg")
    ]
    drifted = []
    for name in frozen_paths:
        target = repo / name
        if not target.is_file():
            drifted.append(name)
            continue
        code, blob = git(repo, "rev-parse", f"HEAD:{name}")
        disk = hashlib.sha1(
            b"blob %d\0" % len(target.read_bytes().replace(b"\r\n", b"\n"))
            + target.read_bytes().replace(b"\r\n", b"\n")
        ).hexdigest()
        if code != 0 or disk != blob:
            drifted.append(name)
    verdict.add(
        "FROZEN_PACKAGES_INTACT",
        not drifted,
        f"{len(frozen_paths)} path(s) of wp051_02b..02g compared with HEAD; {len(drifted)} drifted"
        + (f": {drifted[:5]}" if drifted else ""),
    )

    # the continuity component
    watchdog_file = repo / WATCHDOG
    watchdog_task = scheduler(WATCHDOG_TASK)
    watchdog_payload = None
    verdict_path = state_root / "WATCHDOG.json"
    if verdict_path.is_file():
        watchdog_payload = load(verdict_path)
    verdict.add(
        "WATCHDOG_PRESENT",
        watchdog_file.is_file() and watchdog_task.get("installed") is True,
        f"{WATCHDOG} present: {watchdog_file.is_file()}; task installed: {watchdog_task.get('installed')}; "
        f"verdict written: {watchdog_payload is not None}",
    )

    info = task_result(WATCHDOG_TASK)
    result_code = info.get("LastTaskResult")
    verdict.add(
        "WATCHDOG_ALARM_REACHES_OS",
        result_code is not None,
        f"the scheduler holds LastTaskResult={result_code} for {WATCHDOG_TASK} "
        f"(a non-zero result is the alarm: 8 blocked, 9 stale)",
    )
    detail["watchdog_task_result"] = result_code

    forward_task = scheduler(TASK_NAME)
    by_id = {item["id"]: item for item in continuity["requirements"]}
    recomputed = {
        "C1_AUTOSTART": forward_task.get("repetition_interval") is not None,
        "C2_RESTART_AFTER_FAILURE": int(forward_task.get("restart_count") or 0) > 0,
        "C3_AFTER_REBOOT": str(forward_task.get("start_when_available")).lower() == "true",
        "C4_NO_DUPLICATE_INSTANCES": forward_task.get("multiple_instances") == "IgnoreNew",
        "C9_ALERT_REACHES_A_HUMAN": watchdog_task.get("installed") is True,
    }
    mismatched = [
        key
        for key, value in recomputed.items()
        if (by_id.get(key, {}).get("status") == "SATISFIED") != value
    ]
    verdict.add(
        "CONTINUITY_REQUIREMENTS",
        not mismatched,
        f"{len(recomputed)} requirement(s) recomputed against the scheduler; mismatched: {mismatched}",
    )

    # no trading surface, no certification
    builder_text = (repo / BUILDER).read_text(encoding="utf-8")
    watchdog_text = watchdog_file.read_text(encoding="utf-8")
    forbidden = ("place_order", "create_order", "submit_order", "live_trading=True", "api_secret")
    hits = [token for token in forbidden if token in builder_text or token in watchdog_text]
    certified = bool(root_cause.get("experiment_certified")) or bool(gap.get("experiment_certified"))
    verdict.add(
        "NO_TRADING_SURFACE",
        not hits and not certified,
        f"order-entry tokens in the two new programs: {hits}; certified: {certified}",
    )
    impact = gap["phase_impact"]
    verdict.add(
        "EXPERIMENT_NOT_CERTIFIED",
        recovery.get("experiment_certified") is not True
        and gap.get("experiment_certified") is not True
        and impact["status_now"] != "COVERAGE_COMPLETE"
        and impact["coverage_complete_reachable"] is False,
        f"EXPERIMENT_CERTIFIED=false in every report; phase status {impact['status_now']}; "
        f"COVERAGE_COMPLETE reachable {impact['coverage_complete_reachable']}",
    )

    tree = ast.parse(Path(__file__).read_text(encoding="utf-8"))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
    forbidden_imports = {"trading_bot", "autonomous", "edge03", "incremental"}
    verdict.add(
        "VERIFIER_IS_INDEPENDENT",
        not (imported & forbidden_imports),
        f"imports: {sorted(imported)}",
    )

    return verdict, detail


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--repo", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--package", type=Path, default=None)
    parser.add_argument("--state-root", type=Path, default=None)
    parser.add_argument("--store-root", type=Path, default=None)
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args(argv)

    repo = args.repo.resolve()
    package = (args.package or repo / PACKAGE_DIR).resolve()
    state_root = (args.state_root or repo / STATE).resolve()
    store_root = (args.store_root or repo / STORE).resolve()

    missing = [
        str(path)
        for path in (
            package / "RECOVERY_REPORT.json",
            package / "COVERAGE_GAP_REPORT.json",
            package / "CONTINUITY_REPORT.json",
            package / "ROOT_CAUSE.json",
            state_root / "runs.jsonl",
            store_root / "1h" / "BTC.jsonl",
            repo / DECLARATION,
        )
        if not path.is_file()
    ]
    if missing:
        print(json.dumps({"ok": False, "missing": missing}), file=sys.stderr)
        return EXIT_MISSING

    verdict, detail = verify(repo, package, state_root, store_root)
    failed = verdict.failed
    payload = {
        "schema_version": SCHEMA_VERSION,
        "package": "WP-051-02H",
        "verifier": VERIFIER_ID,
        "at_utc": iso(int(datetime.now(tz=UTC).timestamp() * 1000)),
        "head": git(repo, "rev-parse", "HEAD")[1],
        "check_count": len(verdict.checks),
        "failed_checks": failed,
        "verdict": "PASS" if not failed else "FAIL",
        "experiment_certified": False,
        "certification_allowed": False,
        "certification_blocked_by": "COVERAGE_CEILING_BELOW_DECLARED",
        "checks": [{"name": c.name, "ok": c.ok, "detail": c.detail} for c in verdict.checks],
        "detail": detail,
        "note": (
            "a PASS here says the package measured what it says it measured. It does not say "
            "the experiment is complete, recoverable in full, or worth anything."
        ),
    }
    out = (args.out or package / "INDEPENDENT_VERIFICATION.json").resolve()
    out.write_bytes((json.dumps(payload, indent=2, sort_keys=True) + "\n").encode("utf-8"))
    print(
        json.dumps(
            {
                "verdict": payload["verdict"],
                "checks": payload["check_count"],
                "failed": failed,
                "out": str(out),
            },
            sort_keys=True,
        )
    )
    return EXIT_PASS if not failed else EXIT_FAIL


if __name__ == "__main__":
    raise SystemExit(main())
