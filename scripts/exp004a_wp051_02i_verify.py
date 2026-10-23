"""Independent verifier for WP-051-02I: recompute the storage report from bytes.

This program shares no code with the builder. It does not import
``scripts/exp004a_wp051_02i_storage.py``, it does not import the watchdog, and it does not
accept a number the report asserts without measuring that number again. What it cannot
measure it reports as ``UNVERIFIABLE`` -- never as a pass.

Why a second program: the failure this package exists to prevent is a full volume that is
reported as healthy. A builder that grades its own arithmetic would reproduce exactly that
failure one layer up.

Usage::

    python scripts/exp004a_wp051_02i_verify.py --out docs/agentic/exp004a/wp051_02i \\
        --state-root "C:/Users/GVLLFR0035/Downloads/bot freebuff/data/forward/edge04" \\
        --json-out .../INDEPENDENT_VERIFICATION.json

Research only: reads local files, runs the watchdog in ``--no-persist`` mode, writes the
verification JSON it is asked for.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import statistics
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
REPORT_NAME = "STORAGE_CAPACITY_REPORT.json"
SWEEP_NAME = "SWEEP_EVIDENCE.json"
WATCHDOG = REPO_ROOT / "scripts" / "edge04_watchdog.py"
CONTRACT = REPO_ROOT / "config" / "preregistrations" / "EXP-004A.datasets.phase3.json"

CRITICAL_FREE_BYTES = 2 * 1024**3
WARNING_FREE_BYTES = 5 * 1024**3
GIB = 1024**3
EPISODE_GAP_MS = 2 * 15 * 60 * 1000
WHITELIST = ("__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache", ".hypothesis")

SCHEMA_VERSION = "EXP004A_WP051_02I_VERIFICATION_V1"


def now_iso() -> str:
    return datetime.now(tz=UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def read_json(path: Path) -> dict[str, Any] | None:
    try:
        loaded = json.loads(path.read_bytes().decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    return loaded if isinstance(loaded, dict) else None


def digest(path: Path) -> str | None:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return None


def measure(path: Path) -> tuple[int, int]:
    """Bytes and file count under ``path``, walked independently of the builder."""
    total = files = 0
    if not path.exists():
        return 0, 0
    if path.is_file():
        try:
            return path.stat().st_size, 1
        except OSError:
            return 0, 0
    stack = [path]
    while stack:
        current = stack.pop()
        try:
            with os.scandir(current) as entries:
                for entry in entries:
                    try:
                        if entry.is_dir(follow_symlinks=False):
                            stack.append(Path(entry.path))
                        elif entry.is_file(follow_symlinks=False):
                            total += entry.stat(follow_symlinks=False).st_size
                            files += 1
                    except OSError:
                        continue
        except OSError:
            continue
    return total, files


def git(cwd: Path, *args: str) -> str:
    try:
        completed = subprocess.run(
            ["git", *args], cwd=str(cwd), capture_output=True, text=True, timeout=60
        )
    except (OSError, subprocess.TimeoutExpired):
        return ""
    return completed.stdout.strip() if completed.returncode == 0 else ""


def lane_rows(state_root: Path, *, cap: int = 200_000) -> tuple[list[dict[str, Any]], int]:
    """The lane's own tick rows, parsed here rather than through the builder."""
    path = state_root / "runs.jsonl"
    rows: list[dict[str, Any]] = []
    corrupt = 0
    try:
        raw = path.read_bytes()
    except OSError:
        return [], 0
    for line in raw.splitlines()[:cap]:
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            corrupt += 1
            continue
        if isinstance(row, dict):
            rows.append(row)
        else:
            corrupt += 1
    return rows, corrupt


def rows_until(report: dict[str, Any], rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The rows the report could have seen.

    The lane writes a tick every fifteen minutes, so a verifier that reads the log later sees
    a longer series than the report described. Comparing the two without cutting the series at
    the report's own last reading would turn the campaign's normal operation into a mismatch.
    """
    stamp = str((report.get("history") or {}).get("last_at_utc") or "")
    if not stamp:
        return rows
    try:
        limit = int(datetime.fromisoformat(stamp.replace("Z", "+00:00")).timestamp() * 1000)
    except ValueError:
        return rows
    return [row for row in rows if int(row.get("started_at_ms") or 0) <= limit]


def episodes_from_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Refusal stretches, recomputed from outcomes (a different reading than free space).

    Walked over every row: a tick that ran and was accepted ends the episode even when the
    next refusal follows within the time tolerance.
    """
    episodes: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    for row in sorted(rows, key=lambda item: item.get("started_at_ms") or 0):
        stamp = row.get("started_at_ms")
        if not isinstance(stamp, int):
            continue
        if str(row.get("outcome")) == "DISK_BUDGET_EXCEEDED":
            if current is not None and stamp - current["last_ms"] <= EPISODE_GAP_MS:
                current["last_ms"] = stamp
                current["ticks"] += 1
            else:
                if current is not None:
                    episodes.append(current)
                current = {"start_ms": stamp, "last_ms": stamp, "ticks": 1}
        elif current is not None:
            episodes.append(current)
            current = None
    if current is not None:
        episodes.append(current)
    return episodes


def free_space_episodes(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Stretches whose own reading was under the floor, recomputed here.

    Walked over the whole series rather than over the under-floor rows alone: a single
    healthy reading between two dips ends the first dip, and filtering first would merge the
    two whenever the dips happen to be close in time.
    """
    episodes: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    for row in sorted(rows, key=lambda item: item.get("started_at_ms") or 0):
        stamp = row.get("started_at_ms")
        if not isinstance(stamp, int):
            continue
        reading = row.get("disk_after") or row.get("disk") or {}
        free = reading.get("free_bytes") if isinstance(reading, dict) else None
        if not isinstance(free, int):
            continue
        if free < CRITICAL_FREE_BYTES:
            if current is not None and stamp - current["last_ms"] <= EPISODE_GAP_MS:
                current["last_ms"] = stamp
                current["ticks"] += 1
            else:
                if current is not None:
                    episodes.append(current)
                current = {"start_ms": stamp, "last_ms": stamp, "ticks": 1}
        elif current is not None:
            episodes.append(current)
            current = None
    if current is not None:
        episodes.append(current)
    return episodes


def _episodes(selected: list[dict[str, Any]]) -> list[dict[str, Any]]:
    selected = sorted(selected, key=lambda row: row.get("started_at_ms") or 0)
    episodes: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    for row in selected:
        stamp = row.get("started_at_ms")
        if not isinstance(stamp, int):
            continue
        if current is not None and stamp - current["last_ms"] <= EPISODE_GAP_MS:
            current["last_ms"] = stamp
            current["ticks"] += 1
        else:
            if current is not None:
                episodes.append(current)
            current = {"start_ms": stamp, "last_ms": stamp, "ticks": 1}
    if current is not None:
        episodes.append(current)
    return episodes


def check(id_: str, ok: bool | None, detail: str, *, evidence: Any = None) -> dict[str, Any]:
    status = "UNVERIFIABLE" if ok is None else ("PASS" if ok else "FAIL")
    payload = {"id": id_, "status": status, "detail": detail}
    if evidence is not None:
        payload["evidence"] = evidence
    return payload


# --------------------------------------------------------------------------- #
# the checks
# --------------------------------------------------------------------------- #
def check_report_present(out: Path) -> list[dict[str, Any]]:
    report = read_json(out / REPORT_NAME)
    if report is None:
        return [check("REPORT_PRESENT", False, f"{out / REPORT_NAME} is missing or unreadable")]
    return [
        check(
            "REPORT_PRESENT",
            True,
            f"{REPORT_NAME} parsed: schema {report.get('schema_version')}, generated "
            f"{report.get('generated_at_utc')}",
        ),
        check(
            "REPORT_HAS_NO_GRADE",
            not any(
                key for key in report if "certif" in key.lower() or "coverage" in key.lower()
            ),
            "the report must not carry a coverage or certification claim: it measures storage",
        ),
    ]


def check_arithmetic(report: dict[str, Any], rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = rows_until(report, rows)
    projection = report.get("projection") or {}
    own = (projection.get("own") or {}).get("adopted_bytes")
    floor = projection.get("floor_bytes")
    drawdown = projection.get("max_daily_drawdown_bytes")
    required = projection.get("required_free_bytes")
    free = projection.get("current_free_bytes")
    verdict = projection.get("verdict")
    refused = sum(1 for row in rows if str(row.get("outcome")) == "DISK_BUDGET_EXCEEDED")

    problems: list[str] = []
    if required is None or own is None or floor is None or drawdown is None:
        return [check("PROJECTION_ARITHMETIC", None, "one of the projection terms is absent")]
    if required != own + floor + max(0, drawdown):
        problems.append(
            f"required {required} != own {own} + floor {floor} + drawdown {max(0, drawdown)}"
        )
    if floor != CRITICAL_FREE_BYTES:
        problems.append(f"floor {floor} is not the 2 GiB the guard enforces")
    expected = "SUFFICIENT" if (free is not None and free >= required and not refused) else "INSUFFICIENT"
    if verdict != expected:
        problems.append(f"verdict {verdict!r} contradicts the recomputed {expected!r}")
    if verdict not in ("SUFFICIENT", "INSUFFICIENT", "UNKNOWN"):
        problems.append(f"verdict {verdict!r} is outside the allowed vocabulary")
    return [
        check(
            "PROJECTION_ARITHMETIC",
            not problems,
            "; ".join(problems) or f"required {required} = own + floor + drawdown, verdict {verdict}",
        )
    ]


def check_refusals(report: dict[str, Any], rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = rows_until(report, rows)
    breaches = report.get("breaches") or {}
    refused = sum(1 for row in rows if str(row.get("outcome")) == "DISK_BUDGET_EXCEEDED")
    checks: list[dict[str, Any]] = []
    checks.append(
        check(
            "REFUSALS_RECOMPUTED",
            refused == breaches.get("refused_ticks"),
            f"the report claims {breaches.get('refused_ticks')} refusal(s); the tick log holds {refused}",
            evidence={"recomputed": refused, "claimed": breaches.get("refused_ticks")},
        )
    )
    recomputed_episodes = episodes_from_rows(rows)
    claimed = int(breaches.get("refusal_episode_count") or 0)
    checks.append(
        check(
            "REFUSAL_EPISODES_RECOMPUTED",
            len(recomputed_episodes) == claimed,
            f"the report claims {claimed} refusal episode(s); the outcomes form "
            f"{len(recomputed_episodes)}",
        )
    )
    under_floor = free_space_episodes(rows)
    claimed_free = int(breaches.get("free_space_episode_count") or 0)
    checks.append(
        check(
            "FREE_SPACE_EPISODES_RECOMPUTED",
            len(under_floor) == claimed_free,
            f"the report claims {claimed_free} stretch(es) under the floor; the readings form "
            f"{len(under_floor)}",
        )
    )
    bad = [
        row.get("run_id")
        for row in rows
        if str(row.get("outcome")) == "DISK_BUDGET_EXCEEDED"
        and (int(row.get("new_bars") or 0) != 0 or int(row.get("exit_code") or 0) != 5)
    ]
    checks.append(
        check(
            "A_REFUSAL_IS_NOT_A_CAPTURE",
            not bad,
            "every refused tick carries 0 new bars and exit 5"
            if not bad
            else f"{len(bad)} refused tick(s) claim data: {bad[:5]}",
        )
    )
    return checks


def check_consumers(report: dict[str, Any]) -> list[dict[str, Any]]:
    """Re-measure each path, with a tolerance the directory's own churn sets.

    A shared temp directory is being written while it is measured. Comparing it against a
    reading taken minutes earlier without allowing for that churn would fail every time, and
    failing every time is how a real mismatch gets ignored. So each path is measured twice a
    second apart; the drift observed is the tolerance, and anything beyond it is a mismatch.
    """
    problems: list[str] = []
    compared = 0
    volatile: list[dict[str, Any]] = []
    protected: list[dict[str, Any]] = []
    for row in report.get("consumers") or []:
        measured = row.get("measured") or {}
        path = Path(str(measured.get("path") or ""))
        if not measured.get("path"):
            problems.append(f"{row.get('id')}: no path recorded")
            continue
        if path.exists() != bool(measured.get("exists")):
            problems.append(
                f"{row.get('id')}: report says exists={measured.get('exists')}, filesystem says "
                f"{path.exists()}"
            )
            continue
        if not path.exists():
            continue
        fresh, _files = measure(path)
        claimed = int(measured.get("bytes") or 0)
        if row.get("volatile"):
            # A shared temp tree is being written by other processes while it is measured. Its
            # size is evidence of *when* it was read, not a quantity that can be re-derived
            # exactly; what can be checked is that it is still there and still growing.
            volatile.append(
                {
                    "id": row.get("id"),
                    "claimed": claimed,
                    "now": fresh,
                    "growth": fresh - claimed,
                }
            )
            continue
        time.sleep(0.2)
        again, _ = measure(path)
        drift = abs(again - fresh)
        compared += 1
        tolerance = max(2 * 1024**2, int(0.01 * max(claimed, fresh)), drift)
        if str(row.get("class") or "").startswith("PROTECTED"):
            # Evidence may GROW between the report and the verification -- the lane is writing.
            # It may not shrink: a smaller store than the one the report measured is exactly the
            # failure this whole package exists to make visible.
            if fresh < claimed - tolerance:
                problems.append(
                    f"{row.get('id')}: the evidence tree shrank from {claimed} to {fresh} bytes"
                )
            else:
                protected.append(
                    {"id": row.get("id"), "claimed": claimed, "now": fresh, "growth": fresh - claimed}
                )
            continue
        if abs(fresh - claimed) > tolerance:
            problems.append(
                f"{row.get('id')}: report {claimed} bytes, now {fresh}, churn {drift} "
                f"(tolerance {tolerance})"
            )
    return [
        check(
            "CONSUMERS_MATCH_THE_FILESYSTEM",
            not problems,
            "; ".join(problems) or f"{compared} stable path(s) agree within tolerance; "
            f"{len(protected)} evidence path(s) did not shrink; "
            f"{len(volatile)} volatile path(s) reported separately",
            evidence={"compared": compared, "volatile": volatile, "protected": protected},
        )
    ]


def check_shards(report: dict[str, Any]) -> list[dict[str, Any]]:
    shards = report.get("shards") or {}
    claimed = shards.get("bytes_per_row")
    rows = shards.get("shards") or []
    if claimed is None:
        return [
            check(
                "SHARD_FORMAT_RECOMPUTED",
                None,
                "the report states the format term is unavailable; nothing to recompute",
            )
        ]
    per_row: list[float] = []
    missing: list[str] = []
    for item in rows:
        path = Path(str(item.get("path") or ""))
        if not path.is_file():
            missing.append(str(path))
            continue
        lines = sum(1 for line in path.read_bytes().splitlines() if line.strip())
        if lines > 0:
            per_row.append(path.stat().st_size / lines)
    if not per_row:
        return [
            check(
                "SHARD_FORMAT_RECOMPUTED",
                False,
                f"no shard named by the report is readable: {missing[:3]}",
            )
        ]
    fresh = statistics.median(per_row)
    ok = abs(fresh - float(claimed)) <= max(1.0, 0.005 * float(claimed))
    return [
        check(
            "SHARD_FORMAT_RECOMPUTED",
            ok,
            f"report {claimed} bytes/row, recomputed {round(fresh, 2)} over {len(per_row)} shard(s)",
            evidence={"missing": missing[:5], "recomputed": round(fresh, 2)},
        )
    ]


def check_sweep(out: Path) -> list[dict[str, Any]]:
    evidence = read_json(out / SWEEP_NAME)
    if evidence is None:
        return [check("SWEEP_EVIDENCE_PRESENT", False, f"{SWEEP_NAME} is missing")]
    problems: list[str] = []
    regenerated: list[str] = []
    # Every run the evidence records, not only the last one: a later run that removes nothing
    # must not shelter an earlier run's paths from being audited.
    removed: list[dict[str, Any]] = list(evidence.get("removed") or [])
    for run in evidence.get("history") or []:
        removed.extend(run.get("removed") or [])
    for item in removed:
        path = Path(str(item.get("path") or ""))
        if path.is_absolute() or ".." in path.parts:
            problems.append(f"{path}: outside the worktree")
        if path.name not in WHITELIST:
            problems.append(f"{path}: not on the whitelist")
        # A cache that exists again is not a contradiction: it is rebuilt by the next import or
        # the next test run. What must hold is that what was deleted was scratch, in scope, and
        # untracked -- not that the path stays empty for ever.
        if (REPO_ROOT / path).exists():
            regenerated.append(str(path))
        if git(REPO_ROOT, "ls-tree", "--name-only", "HEAD", "--", str(path)):
            problems.append(f"{path}: tracked by Git at HEAD")
    return [
        check(
            "SWEEP_STAYED_INSIDE_ITS_SCOPE",
            not problems,
            "; ".join(problems)
            or f"{len({str(item.get('path')) for item in removed})} distinct removed director(ies) "
            "across the recorded history, all whitelisted and untracked; "
            f"{len(regenerated)} of them have been rebuilt since, which is what a cache does",
            evidence={"regenerated": regenerated},
        )
    ]


def run_watchdog(state_root: Path) -> tuple[dict[str, Any] | None, int, str]:
    before = {name: digest(state_root / name) for name in ("runs.jsonl", "health.json")}
    try:
        completed = subprocess.run(
            [sys.executable, str(WATCHDOG), "--state-root", str(state_root), "--json", "--no-persist"],
            capture_output=True,
            text=True,
            timeout=180,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return None, -1, repr(exc)
    payload = None
    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError:
        payload = None
    after = {name: digest(state_root / name) for name in before}
    global _STORE_UNCHANGED  # noqa: PLW0603 - one-shot evidence for the next check
    _STORE_UNCHANGED = before == after
    return payload, completed.returncode, completed.stderr[:400]


_STORE_UNCHANGED: bool | None = None


def check_watchdog(state_root: Path) -> list[dict[str, Any]]:
    payload, code, err = run_watchdog(state_root)
    checks: list[dict[str, Any]] = []
    if payload is None:
        return [
            check("WATCHDOG_RUNS", False, f"the watchdog did not produce JSON: exit {code} {err}")
        ]
    required = ("status", "exit_code", "reasons", "disk", "history", "forecast")
    missing = [key for key in required if key not in payload]
    checks.append(
        check(
            "WATCHDOG_RUNS",
            not missing,
            f"status {payload.get('status')} exit {payload.get('exit_code')} "
            f"(process {code}); missing fields: {missing}",
        )
    )
    free = int((payload.get("disk") or {}).get("free_bytes") or 0)
    usage = shutil.disk_usage(state_root)
    tolerance = 512 * 1024**2
    checks.append(
        check(
            "WATCHDOG_READS_THE_SAME_VOLUME",
            abs(int(usage.free) - free) <= tolerance,
            f"watchdog {round(free / GIB, 3)} GiB, verifier {round(int(usage.free) / GIB, 3)} GiB",
        )
    )
    expected_status = None
    if free < CRITICAL_FREE_BYTES:
        expected_status = "BLOCKED"
    if payload.get("status") in ("BLOCKED", "STALE", "DEGRADED", "OK", "UNREADABLE", "RECOVERED"):
        allowed = True
    else:
        allowed = False
    checks.append(
        check(
            "WATCHDOG_STATE_VOCABULARY",
            allowed,
            f"status {payload.get('status')!r} is one of the five documented states",
        )
    )
    if expected_status:
        checks.append(
            check(
                "WATCHDOG_BLOCKS_UNDER_THE_FLOOR",
                payload.get("status") == "BLOCKED" and int(payload.get("exit_code") or 0) == 8,
                f"free {round(free / GIB, 3)} GiB is under the floor; the watchdog said "
                f"{payload.get('status')} / {payload.get('exit_code')}",
            )
        )
    forecast = payload.get("forecast") or {}
    checks.append(
        check(
            "WATCHDOG_FORECAST_IS_LABELLED",
            forecast.get("label") in ("UNKNOWN", "AT_RISK", "COMFORTABLE"),
            f"forecast label {forecast.get('label')!r} with "
            f"{forecast.get('hours_to_critical')} h to the floor",
        )
    )
    checks.append(
        check(
            "WATCHDOG_DOES_NOT_WRITE_THE_STORE",
            _STORE_UNCHANGED if _STORE_UNCHANGED is not None else None,
            "runs.jsonl and health.json are byte-identical after a --no-persist run"
            if _STORE_UNCHANGED
            else "the watchdog changed the store while reporting only",
        )
    )
    return checks


def check_contract(report: dict[str, Any], state_root: Path) -> list[dict[str, Any]]:
    contract = read_json(CONTRACT)
    if contract is None:
        return [
            check("WINDOW_MATCHES_THE_CONTRACT", None, f"{CONTRACT} is not readable here")
        ]
    window = contract.get("capture_window") or {}
    days = window.get("days")
    start = str(window.get("start_utc") or "")
    end = str(window.get("end_utc") or "")
    projection = report.get("projection") or {}
    today = datetime.now(tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    problems = []
    if projection.get("window_days") != days:
        problems.append(f"report projects {projection.get('window_days')} d, contract {days} d")
    if not (start <= today < end):
        problems.append(f"now {today} is outside the contract window {start} .. {end}")
    return [
        check(
            "WINDOW_MATCHES_THE_CONTRACT",
            not problems,
            "; ".join(problems) or f"window {start} .. {end} ({days} d) holds now and matches",
        )
    ]


def verify(out: Path, state_root: Path) -> dict[str, Any]:
    report = read_json(out / REPORT_NAME) or {}
    rows, corrupt = lane_rows(state_root)
    checks: list[dict[str, Any]] = []
    checks.extend(check_report_present(out))
    checks.extend(check_arithmetic(report, rows))
    checks.extend(check_refusals(report, rows))
    checks.extend(check_consumers(report))
    checks.extend(check_shards(report))
    checks.extend(check_sweep(out))
    checks.extend(check_watchdog(state_root))
    checks.extend(check_contract(report, state_root))
    failures = [item for item in checks if item["status"] == "FAIL"]
    unverifiable = [item for item in checks if item["status"] == "UNVERIFIABLE"]
    return {
        "schema_version": SCHEMA_VERSION,
        "package": "WP-051-02I",
        "generated_at_utc": now_iso(),
        "worktree": str(REPO_ROOT),
        "head": git(REPO_ROOT, "rev-parse", "HEAD"),
        "state_root": str(state_root),
        "report": str(out / REPORT_NAME),
        "checks": checks,
        "check_count": len(checks),
        "passed": sum(1 for item in checks if item["status"] == "PASS"),
        "failed": len(failures),
        "unverifiable": len(unverifiable),
        "corrupt_run_lines": corrupt,
        "verdict": "PASS" if not failures else "FAIL",
        "not_a_certification": (
            "this says the storage report agrees with the bytes on this host. It says nothing "
            "about the experiment's coverage, and it promotes nothing."
        ),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--out", type=Path, default=REPO_ROOT / "docs/agentic/exp004a/wp051_02i")
    parser.add_argument("--state-root", type=Path, default=None)
    parser.add_argument("--json-out", type=Path, default=None)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    out = args.out.resolve()
    from_env = os.environ.get("EDGE04_STATE_ROOT", "").strip()
    state_root = (
        args.state_root
        or (Path(from_env) if from_env else None)
        or Path(r"C:\Users\GVLLFR0035\Downloads\bot freebuff\data\forward\edge04")
    ).resolve()
    result = verify(out, state_root)
    destination = args.json_out or (out / "INDEPENDENT_VERIFICATION.json")
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        for item in result["checks"]:
            print(f"{item['status']:12} {item['id']}: {item['detail']}")
        print(
            f"\n{result['verdict']}  {result['passed']}/{result['check_count']} PASS, "
            f"{result['failed']} FAIL, {result['unverifiable']} UNVERIFIABLE"
        )
    return 0 if result["verdict"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
