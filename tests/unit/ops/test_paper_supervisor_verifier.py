"""CODEX-SUPERVISOR — the verifier must pass honest evidence and fail every fake.

A verifier that only reads the producer's verdict proves nothing, so this file builds a
complete supervised campaign by hand — two recoveries, one supervisor race, both negative
scenarios — and then requires two contradictory things:

* the honest copy passes every check;
* each of the twelve negative controls changes the scenario, is detected, and none is
  ``invalid``. Several keep the hash chain perfectly valid, so a chain-only judge would
  pass them; the numbering, the fences and the journal are what catch them.
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
from pathlib import Path
from typing import Any

from trading_bot.vision.ledger import GENESIS, line_hash

REPO = Path(__file__).resolve().parents[3]


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, REPO / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


verifier = _load("paper_supervisor_verify")


def _chain(path: Path, entries: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    prev = GENESIS
    lines = []
    for index, entry in enumerate(entries, start=1):
        digest = line_hash(index, prev, entry)
        lines.append(
            json.dumps(
                {"seq": index, "prev_sha256": prev, "entry": entry, "sha256": digest},
                sort_keys=True,
            )
        )
        prev = digest
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _start(resumed: bool, index: int) -> dict[str, Any]:
    return {
        "kind": "SESSION_START",
        "recorded_at_utc": "2026-10-23T00:00:00Z",
        "started_at_utc": "2026-10-23T00:00:00Z",
        "live_orders": 0,
        "runtime_sha256": {"src/a.py": "a"},
        "provenance": {
            "run_id": "run-1",
            "session_id": f"sess-{index}",
            "pinned_identity": "pin-1",
            "runtime_digest": "digest-1",
            "resumed": resumed,
        },
    }


def _reclaim(fence: int) -> dict[str, Any]:
    return {
        "kind": "LOCK_RECLAIMED",
        "recorded_at_utc": "2026-10-23T00:00:00Z",
        "live_orders": 0,
        "scope": "session",
        "locks": [
            {
                "lock": "STREAM.jsonl.lock",
                "pid": 4000 + fence,
                "reason": "OWNER_PROCESS_DEAD",
                "fence": fence,
            }
        ],
    }


def _cycle(number: int) -> dict[str, Any]:
    return {
        "kind": "CYCLE",
        "recorded_at_utc": "2026-10-23T00:01:00Z",
        "cycle": number,
        "live_orders": 0,
    }


def build_campaign(root: Path) -> Path:
    out = root / "campaign"
    session = out / "session"
    session.mkdir(parents=True)
    entries = [
        _start(False, 1),
        {"kind": "SESSION_PROVENANCE", "recorded_at_utc": "2026-10-23T00:00:00Z"},
        {
            "kind": "DELAY_MEASURED",
            "recorded_at_utc": "2026-10-23T00:00:10Z",
            "data_delay_ms": 7000,
        },
        _cycle(1),
        _start(True, 2),
        {"kind": "SESSION_PROVENANCE", "recorded_at_utc": "2026-10-23T00:05:00Z"},
        _reclaim(2),
        {
            "kind": "DELAY_MEASURED",
            "recorded_at_utc": "2026-10-23T00:05:10Z",
            "data_delay_ms": 7000,
        },
        _cycle(2),
        _start(True, 3),
        {"kind": "SESSION_PROVENANCE", "recorded_at_utc": "2026-10-23T00:10:00Z"},
        _reclaim(3),
        {
            "kind": "DELAY_MEASURED",
            "recorded_at_utc": "2026-10-23T00:10:10Z",
            "data_delay_ms": 7000,
        },
        _cycle(3),
        {"kind": "SESSION_END", "recorded_at_utc": "2026-10-23T00:15:00Z", "live_orders": 0},
    ]
    _chain(session / "STREAM.jsonl", entries)
    for number in (1, 2, 3):
        _chain(
            session / "cycles" / f"cycle-{number:04d}" / "ledger.jsonl",
            [
                {"kind": "RUN", "recorded_at_utc": "2026-10-23T00:00:00Z", "run": number},
                {"kind": "DECISION", "recorded_at_utc": "2026-10-23T00:00:30Z", "cycle": number},
            ],
        )
    commit = subprocess.run(
        ["git", "-C", str(REPO), "rev-parse", "HEAD"], capture_output=True, text=True, check=False
    ).stdout.strip()
    (session / "RUN_META.json").write_text(
        json.dumps({"mode": "PAPER", "live_enabled": False, "live_orders": 0, "commit": commit}),
        encoding="utf-8",
    )
    (session / "RUN_RESULT.json").write_text('{"exit_code": 0}', encoding="utf-8")

    def decision(action: str, rows: int, awaiting: list[dict[str, Any]]) -> dict[str, Any]:
        return {
            "event": "DECISION",
            "action": action,
            "state": {
                "state": "RECOVERING" if action == "RESUME" else "ABSENT",
                "rows": rows,
                "awaiting": awaiting,
            },
        }

    def spawn(pid: int, resume: bool) -> dict[str, Any]:
        return {"event": "SPAWNED", "pid": pid, "resume": resume, "supervisor_pid": 100}

    def exit_row(
        pid: int, code: int, before: int, after: int, start_seq: int, action: str
    ) -> dict[str, Any]:
        return {
            "event": "CHILD_EXIT",
            "pid": pid,
            "action": action,
            "exit_code": code,
            "before": {"rows": before},
            "after": {"rows": after},
            "verified": {
                "progress": after > before,
                "continued": True,
                "start_seq": start_seq,
                "exit_code": code,
                "clean": code == 0,
            },
        }

    abandoned = [
        {"path": "STREAM.jsonl.lock", "state": "ABANDONED", "reason": "OWNER_PROCESS_DEAD"}
    ]
    events = [
        {
            "event": "ACQUIRED",
            "supervisor_pid": 100,
            "policy": {"max_restarts": 5, "poll_s": 2.0},
        },
        {"event": "REFUSED", "supervisor_pid": 200, "code": "LOCK_HELD"},
        decision("START", 0, []),
        spawn(111, False),
        exit_row(111, 1, 0, 4, 1, "START"),
        decision("RESUME", 4, abandoned),
        {"event": "BACKOFF", "seconds": 1.0},
        spawn(222, True),
        exit_row(222, 1, 4, 9, 5, "RESUME"),
        decision("RESUME", 9, abandoned),
        spawn(333, True),
        exit_row(333, 0, 9, 15, 10, "RESUME"),
        {"event": "STOP", "action": "STOP_COMPLETED"},
    ]
    (out / "supervisor").mkdir(parents=True)
    (out / "supervisor" / "SUPERVISOR.jsonl").write_text(
        "\n".join(json.dumps(row, sort_keys=True) for row in events) + "\n", encoding="utf-8"
    )
    (out / "supervisor" / "SUPERVISOR_RESULT.json").write_text(
        json.dumps(
            {
                "action": "STOP_COMPLETED",
                "reason": "CLEAN_END",
                "restarts": 2,
                "final_state": "RECOVERED",
                "locks": [],
                "exit_code": 0,
            }
        ),
        encoding="utf-8",
    )
    scenarios = {
        "scenarios": {
            "corrupt": {
                "rows_before": 15,
                "rows_after": None,
                "state": "FAILED",
                "exit_code": 3,
                "spawned": [],
                "result": {"action": "STOP_FAILED", "reason": "STATE_FAILED"},
            },
            "budget": {
                "attempts": [{"attempt": 1}, {"attempt": 2}],
                "exit_code": 3,
                "result": {
                    "action": "STOP_BUDGET",
                    "reason": "RETRY_BUDGET_EXHAUSTED",
                    "restarts": 1,
                },
            },
        }
    }
    (out / "scenarios").mkdir(parents=True)
    (out / "scenarios" / "SCENARIOS.json").write_text(
        json.dumps(scenarios, sort_keys=True), encoding="utf-8"
    )
    return out


def test_the_honest_campaign_passes_every_check(tmp_path: Path) -> None:
    verdict = verifier.judge(build_campaign(tmp_path))
    failed = sorted(key for key, value in verdict["checks"].items() if value is False)
    assert failed == [], f"unexpected failures: {failed}"
    assert verdict["verdict"] == "PASS"
    assert verdict["counts"]["resumed_starts"] == 2
    assert verdict["cycles"]["numbers"] == [1, 2, 3]


def test_every_mutation_changes_the_scenario_and_is_detected(tmp_path: Path) -> None:
    results = verifier.mutations(build_campaign(tmp_path))
    assert len(results) == 12
    invalid = [item["mutation"] for item in results if item["invalid"]]
    undetected = [item["mutation"] for item in results if not item["detected"]]
    assert invalid == [], f"mutations that changed nothing: {invalid}"
    assert undetected == [], f"mutations that slipped through: {undetected}"
    duplicate = next(
        item for item in results if item["mutation"] == "duplicated_cycle_with_a_valid_chain"
    )
    assert "stream_chain_intact" not in duplicate["false_checks"]


def test_a_tampered_stream_is_not_certified(tmp_path: Path) -> None:
    campaign = build_campaign(tmp_path)
    path = campaign / "session" / "STREAM.jsonl"
    rows = path.read_text(encoding="utf-8").splitlines()
    payload = json.loads(rows[3])
    payload["entry"]["cycle"] = 9
    rows[3] = json.dumps(payload, sort_keys=True)
    path.write_text("\n".join(rows) + "\n", encoding="utf-8")

    verdict = verifier.judge(campaign)
    assert verdict["checks"]["stream_chain_intact"] is False
    assert verdict["verdict"] == "FAIL"


def test_a_tampered_cycle_ledger_is_not_certified(tmp_path: Path) -> None:
    campaign = build_campaign(tmp_path)
    path = campaign / "session" / "cycles" / "cycle-0002" / "ledger.jsonl"
    rows = path.read_text(encoding="utf-8").splitlines()
    payload = json.loads(rows[0])
    payload["entry"]["run"] = 99
    rows[0] = json.dumps(payload, sort_keys=True)
    path.write_text("\n".join(rows) + "\n", encoding="utf-8")

    verdict = verifier.judge(campaign)
    assert verdict["checks"]["cycle_ledgers_intact"] is False
