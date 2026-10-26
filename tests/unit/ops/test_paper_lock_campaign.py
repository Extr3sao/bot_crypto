"""CODEX — the campaign verifier and its probes must work on *real* mechanisms.

The verifier is only worth something if it fails when the evidence is wrong, so this file
builds a complete synthetic campaign (six crashes, five recoveries after a persisted cycle,
one before it, chained stream, cycle ledgers, fences, probes) and then requires that:

* the honest campaign is judged PASS on every check;
* every negative control changes the scenario, is detected, and none is ``invalid`` —
  including one where the hash chain stays perfectly valid and only the cycle numbering
  betrays the duplication. That is the mutation a chain-only verifier would pass.

The probe tests use the real lock and a real second interpreter, not mocks: a live owner
must be refused and left untouched, an old owner must get ``LOCK_LOST`` and must not be able
to release the new owner's lock, and two racers must produce exactly one reclaimer.
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from trading_bot.ops.single_writer import SingleWriter, diagnose_lock
from trading_bot.vision.ledger import GENESIS, line_hash

REPO = Path(__file__).resolve().parents[3]


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, REPO / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


campaign = _load("paper_lock_campaign")
verifier = _load("paper_lock_campaign_verify")


def _dead_pid() -> int:
    process = subprocess.Popen([sys.executable, "-c", "pass"])
    process.wait()
    return process.pid


def _write_stream(path: Path, entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    path.parent.mkdir(parents=True, exist_ok=True)
    prev = GENESIS
    rows = []
    for index, entry in enumerate(entries, start=1):
        digest = line_hash(index, prev, entry)
        rows.append({"seq": index, "prev_sha256": prev, "entry": entry, "sha256": digest})
        prev = digest
    path.write_text(
        "\n".join(json.dumps(row, sort_keys=True) for row in rows) + "\n", encoding="utf-8"
    )
    return rows


def _owner(pid: int, token: str) -> dict[str, Any]:
    import socket

    return {
        "schema_version": "TAP_SINGLE_WRITER_LOCK_V1",
        "purpose": "fixture",
        "host": socket.gethostname(),
        "pid": pid,
        "process_start_ms": None,
        "token": token,
        "fence": 1,
    }


def build_campaign(root: Path) -> Path:
    """A campaign shaped exactly like the producer's output, with proved-dead owners."""

    out = root / "campaign"
    session = out / "session"
    session.mkdir(parents=True)
    pids = [_dead_pid() for _ in range(6)]
    for pid in pids:
        assert diagnose_lock(_owner(pid, "x"))["state"] == "ABANDONED"

    entries: list[dict[str, Any]] = []
    boundaries: dict[int, int] = {}

    def add(kind: str, **payload: Any) -> None:
        entries.append(
            {
                "kind": kind,
                "recorded_at_utc": "2026-10-23T00:00:00Z",
                "live_orders": 0,
                **payload,
            }
        )

    def provenance(resumed: bool, index: int) -> dict[str, Any]:
        return {
            "run_id": "run-1",
            "session_id": f"sess-{index}",
            "pinned_identity": "pin-1",
            "runtime_digest": "digest-1",
            "resumed": resumed,
        }

    def reclaim(pid: int, token: str) -> None:
        add(
            "LOCK_RECLAIMED",
            scope="session",
            locks=[
                {
                    "lock": "STREAM.jsonl.lock",
                    "pid": pid,
                    "reason": "OWNER_PROCESS_DEAD",
                    "fence": 2,
                    "process_start_ms": None,
                },
                {
                    "lock": "market-1m/BTCUSDT.jsonl.lock",
                    "pid": pid,
                    "reason": "OWNER_PROCESS_DEAD",
                    "fence": 2,
                    "process_start_ms": None,
                },
            ],
        )

    #: One iteration is the process that is killed, followed by the process that recovers it
    #: and runs to completion — the harness launches both, so the fixture must too, or the
    #: verifier would be tuned to a stream the runtime never writes.
    cycle = 0
    for index in range(1, 7):
        add(
            "SESSION_START",
            started_at_utc="2026-10-23T00:00:00Z",
            runtime_sha256={"src/a.py": "a"},
            provenance=provenance(index > 1, index),
        )
        add("DELAY_MEASURED", data_delay_ms=30_000)
        if index != 3:  # iteration 3 is the crash *before* any cycle is persisted
            cycle += 1
            add("CYCLE", cycle=cycle, status="EXECUTED")
        boundaries[index] = len(entries)

        add(
            "SESSION_START",
            started_at_utc="2026-10-23T00:00:00Z",
            runtime_sha256={"src/a.py": "a"},
            provenance=provenance(True, 100 + index),
        )
        reclaim(pids[index - 1], f"tok-{index}")
        add("DELAY_MEASURED", data_delay_ms=30_000)
        for _ in range(2):
            cycle += 1
            add("CYCLE", cycle=cycle, status="EXECUTED")
        add("SESSION_END", ended_at_utc="2026-10-23T00:10:00Z")

    rows = _write_stream(session / "STREAM.jsonl", entries)

    for number in range(1, cycle + 1):
        directory = session / "cycles" / f"cycle-{number:04d}"
        directory.mkdir(parents=True)
        ledger = [
            {"kind": "RUN", "recorded_at_utc": "2026-10-23T00:00:00Z", "run": number},
            {"kind": "DECISION", "recorded_at_utc": "2026-10-23T00:00:30Z", "cycle": number},
        ]
        prev = GENESIS
        lines = []
        for seq, entry in enumerate(ledger, start=1):
            digest = line_hash(seq, prev, entry)
            lines.append(
                json.dumps(
                    {"seq": seq, "prev_sha256": prev, "entry": entry, "sha256": digest},
                    sort_keys=True,
                )
            )
            prev = digest
        (directory / "ledger.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")
        (directory / "summary.json").write_text("{}", encoding="utf-8")

    for index in range(1, 7):
        directory = out / "iterations" / f"iteration-{index:02d}"
        directory.mkdir(parents=True)
        pid, token = pids[index - 1], f"tok-{index}"
        leftovers = [
            {
                "path": name,
                "state": "ABANDONED",
                "reason": "OWNER_PROCESS_DEAD",
                "record": _owner(pid, token) | {"path": name},
            }
            for name in ("STREAM.jsonl.lock", "market-1m/BTCUSDT.jsonl.lock")
        ]
        (directory / "POST_CRASH.json").write_text(
            json.dumps(
                {
                    "iteration": index,
                    "crash_site": "BEFORE_CYCLE" if index == 3 else "AFTER_CYCLE",
                    "rows_at_crash": boundaries[index],
                    "chain_at_crash": {
                        "ok": True,
                        "head_sha256": rows[boundaries[index] - 1]["sha256"],
                    },
                    "leftovers": leftovers,
                },
                sort_keys=True,
            ),
            encoding="utf-8",
        )
        (directory / "RECOVERY.json").write_text(
            json.dumps(
                {
                    "iteration": index,
                    "exit_code": 0,
                    "locks_after": [],
                    "chain_after": {"ok": True},
                },
                sort_keys=True,
            ),
            encoding="utf-8",
        )
        (directory / "LIVE_OWNER.json").write_text(
            json.dumps(
                {
                    "stream": {"outcome": "REFUSED", "code": "LOCK_HELD", "unchanged": True},
                    "cycles": [{"outcome": "REFUSED", "code": "LOCK_HELD", "unchanged": True}],
                },
                sort_keys=True,
            ),
            encoding="utf-8",
        )
        (directory / "STALE_OWNER.json").write_text(
            json.dumps(
                {
                    "old_token": token,
                    "old_fence": 1,
                    "lock_lost": {"raised": True, "code": "LOCK_LOST"},
                    "release_refused": True,
                    "lock_still_present": True,
                    "current": {"token": f"new-{index}", "fence": 2},
                },
                sort_keys=True,
            ),
            encoding="utf-8",
        )
        if index == 2:
            (directory / "CONCURRENCY.json").write_text(
                json.dumps(
                    {
                        "path": str(session / "STREAM.jsonl.lock"),
                        "racers": 2,
                        "outcomes": [
                            {
                                "outcome": "RECLAIMED",
                                "pid": 1111,
                                "fence": 3,
                                "previous_owner": {"fence": 1},
                                "released": True,
                            },
                            {"outcome": "REFUSED", "code": "LOCK_HELD", "pid": 2222},
                        ],
                    },
                    sort_keys=True,
                ),
                encoding="utf-8",
            )

    (session / "STREAM.jsonl.lock.fence").write_text("3\n", encoding="utf-8")
    (session / "RUN_META.json").write_text(
        json.dumps({"mode": "PAPER", "live_enabled": False, "live_orders": 0}), encoding="utf-8"
    )
    (session / "RUN_RESULT.json").write_text(json.dumps({"exit_code": 0}), encoding="utf-8")
    return out


def test_the_honest_campaign_passes_every_check(tmp_path: Path) -> None:
    campaign_dir = build_campaign(tmp_path)
    verdict = verifier.judge(campaign_dir)
    failed = sorted(key for key, value in verdict["checks"].items() if value is False)
    assert failed == [], f"unexpected failures: {failed}"
    assert verdict["verdict"] == "PASS"
    assert verdict["counts"]["iterations"] == 6
    assert verdict["counts"]["reclaim_rows"] == 6
    assert verdict["cycles"]["numbers"] == list(range(1, 18))


def test_every_mutation_is_effective_and_detected(tmp_path: Path) -> None:
    campaign_dir = build_campaign(tmp_path)
    results = verifier.mutations(campaign_dir)
    assert len(results) == 9
    invalid = [item["mutation"] for item in results if item["invalid"]]
    undetected = [item["mutation"] for item in results if not item["detected"]]
    assert invalid == [], f"mutations that changed nothing: {invalid}"
    assert undetected == [], f"mutations that slipped through: {undetected}"

    duplicate = next(
        item for item in results if item["mutation"] == "duplicated_cycle_with_valid_chain"
    )
    assert "stream_chain_intact" not in duplicate["false_checks"], (
        "the duplicate must be caught by numbering, not by a broken chain"
    )


def test_a_forged_crash_boundary_is_refused(tmp_path: Path) -> None:
    campaign_dir = build_campaign(tmp_path)
    path = campaign_dir / "iterations" / "iteration-02" / "POST_CRASH.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["rows_at_crash"] = int(payload["rows_at_crash"]) + 1
    path.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
    verdict = verifier.judge(campaign_dir)
    assert verdict["checks"]["crash_boundaries_match_recorded_chains"] is False
    assert verdict["verdict"] == "FAIL"


def test_the_live_owner_probe_is_refused_without_touching_the_record(tmp_path: Path) -> None:
    path = tmp_path / "STREAM.jsonl.lock"
    holder = SingleWriter(path, purpose="test-holder")
    holder.acquire()
    try:
        before = path.read_bytes()
        payload = campaign.probe_live(path)
        after = path.read_bytes()
    finally:
        holder.release()
    assert payload["outcome"] == "REFUSED"
    assert payload["code"] == "LOCK_HELD"
    assert payload["unchanged"] is True
    assert before == after


def test_an_old_owner_gets_lock_lost_and_cannot_release_the_new_lock(tmp_path: Path) -> None:
    path = tmp_path / "STREAM.jsonl.lock"
    holder = SingleWriter(path, purpose="test-holder")
    holder.acquire()
    try:
        old = _owner(holder.record["pid"], "old-token") | {"fence": 0}
        payload = campaign.probe_stale(path, old)
        current = SingleWriter(path, purpose="test-holder").read()
    finally:
        holder.release()
    assert payload["lock_lost"]["raised"] is True
    assert payload["lock_lost"]["code"] == "LOCK_LOST"
    assert payload["release_refused"] is True
    assert payload["lock_still_present"] is True
    assert current is not None and current["token"] == holder.token


def test_a_blocked_feed_cannot_exit_zero(tmp_path: Path, monkeypatch) -> None:
    """CI ran the gate without a live feed: the session reported BLOCKED after one cycle-less
    launch, the campaign broke on NO_SESSION_START and still returned 0 because the final
    session state was READY. READY is what an empty directory reports too, so the exit code
    has to be driven by the iterations, not by that state."""

    class _FakeProcess:
        pid = 4242

    def _fake_start(*args: Any, **kwargs: Any) -> _FakeProcess:
        # The real entrypoint opens the stream before it discovers the feed is blocked, and
        # that empty-but-present stream is exactly why the session reports READY afterwards.
        session = Path(args[0])
        session.mkdir(parents=True, exist_ok=True)
        (session / "STREAM.jsonl").touch()
        log = kwargs.get("log")
        if log is not None:
            Path(log).write_text("[wp04] BLOCKED — no cycle\n", encoding="utf-8")
        return _FakeProcess()

    monkeypatch.setattr(campaign, "start_session", _fake_start)
    monkeypatch.setattr(campaign, "wait_for", lambda *a, **k: False)

    args = SimpleNamespace(
        out=str(tmp_path / "campaign"),
        symbols=["BTCUSDT"],
        modes=[
            "after_cycle",
            "after_cycle",
            "before_cycle",
            "after_cycle",
            "after_cycle",
            "after_cycle",
        ],
        race_iterations=[2, 5],
        wait_cycle_timeout_s=1.0,
        wait_abandoned_timeout_s=1.0,
        before_cycle_wait_s=0.0,
    )
    code = campaign.run_campaign(args)
    payload = json.loads((tmp_path / "campaign" / "CAMPAIGN.json").read_text(encoding="utf-8"))
    assert code == 1
    assert payload["failures"] == ["iteration-01:NO_SESSION_START", "incomplete:1/6 crash sites"]
    assert payload["final_status"]["state"] == "READY"


def test_two_racers_produce_exactly_one_reclaimer(tmp_path: Path) -> None:
    path = tmp_path / "STREAM.jsonl.lock"
    path.write_text(json.dumps(_owner(_dead_pid(), "dead")), encoding="utf-8")
    payload = campaign.race_reclaim(path, racers=2, hold_s=4.0, out=tmp_path)
    outcomes = payload["outcomes"]
    assert len(outcomes) == 2, outcomes
    winners = [item for item in outcomes if item.get("outcome") == "RECLAIMED"]
    assert len(winners) == 1, outcomes
    assert all(
        item.get("outcome") == "REFUSED" for item in outcomes if item.get("outcome") != "RECLAIMED"
    ), outcomes
    assert winners[0]["previous_owner"]["pid"] is not None
    assert not path.exists()
