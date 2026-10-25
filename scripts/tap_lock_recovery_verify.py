"""tap_lock_recovery_verify — a second opinion on the lock-recovery evidence.

``BUILDER != VERIFIER``: this script did not produce the rehearsal it judges. It reads the
raw artefacts (the chained stream, the cycle ledgers, the lock files, the entrypoint's own
result files) and re-derives every claim, instead of trusting ``REHEARSAL.json``.

It also refuses to be a rubber stamp. A verifier that only ever says PASS is worthless, so
it is run against deliberately broken copies of the same evidence and must reject each one:

* one byte changed in the stream → the chain must stop verifying;
* the ``LOCK_RECLAIMED`` row removed → the recovery claim must be unsupported;
* a lock left behind with a live owner → the "no lock remains" check must fail;
* a resume that never happened (single ``SESSION_START``) → continuity must be unsupported.

``false_success`` counts mutations that slipped through. It must be zero.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import socket
import sys
import tempfile
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
if str(REPO / "src") not in sys.path:
    sys.path.insert(0, str(REPO / "src"))

from trading_bot.ops.single_writer import SingleWriter, diagnose_lock  # noqa: E402
from trading_bot.vision.ledger import read_entries, verify_chain  # noqa: E402

ABANDONED_REASONS = {"OWNER_PROCESS_DEAD", "PID_REUSED"}


def _entries(session: Path) -> list[dict[str, Any]]:
    return read_entries(session / "STREAM.jsonl")


def _locks(session: Path) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []
    for path in sorted(session.rglob("*.lock")):
        verdict = diagnose_lock(SingleWriter(path).read())
        found.append({"path": path.relative_to(session).as_posix(), "state": verdict["state"]})
    return found


def judge(session: Path, rows: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """Every claim, re-derived from the artefacts. ``rows`` lets a mutation be judged."""

    rows = _entries(session) if rows is None else rows
    entries = [row["entry"] for row in rows]
    starts = [entry for entry in entries if entry.get("kind") == "SESSION_START"]
    reclaimed = [entry for entry in entries if entry.get("kind") == "LOCK_RECLAIMED"]
    cycles = [entry for entry in entries if entry.get("kind") == "CYCLE"]
    seqs = [int(row["seq"]) for row in rows]
    chain = verify_chain(session / "STREAM.jsonl")
    result_path = session / "RUN_RESULT.json"
    result = json.loads(result_path.read_text(encoding="utf-8")) if result_path.is_file() else {}
    ledgers = sorted((session / "cycles").glob("*/ledger.jsonl"))
    leftovers = _locks(session)

    check = {
        "stream_chain_intact": bool(chain.get("ok")),
        "seq_continuous": seqs == list(range(1, len(seqs) + 1)) and bool(seqs),
        "a_crash_then_a_continuation": bool(starts)
        and any((entry.get("provenance") or {}).get("resumed") is False for entry in starts)
        and any((entry.get("provenance") or {}).get("resumed") is True for entry in starts),
        "reclaim_is_recorded_with_a_proved_reason": bool(reclaimed)
        and all(
            lock.get("reason") in ABANDONED_REASONS
            and isinstance(lock.get("pid"), int)
            and isinstance(lock.get("fence"), int)
            for entry in reclaimed
            for lock in (entry.get("locks") or [])
        )
        and all(bool(entry.get("locks")) for entry in reclaimed),
        "no_lock_left_after_resume": not leftovers,
        "cycle_ledgers_intact": bool(ledgers)
        and all(bool(verify_chain(path).get("ok")) for path in ledgers),
        "at_least_two_cycles": len(cycles) >= 2,
        "resume_reported_success": int(result.get("exit_code", -1)) == 0,
        "no_refusal_on_the_record": not (session / "REFUSED.json").is_file()
        and not (session / "ABORTED.json").is_file(),
        "same_runtime_before_and_after": len({str(entry.get("runtime_sha256")) for entry in starts})
        == 1
        and len({str((entry.get("provenance") or {}).get("runtime_digest")) for entry in starts})
        == 1,
        "no_live_orders": all(int(entry.get("live_orders", 0) or 0) == 0 for entry in entries),
    }
    return {
        "checks": check,
        "verdict": "PASS" if all(check.values()) else "FAIL",
        "counts": {
            "rows": len(rows),
            "cycles": len(cycles),
            "session_starts": len(starts),
            "lock_reclaimed_rows": len(reclaimed),
            "cycle_ledgers": len(ledgers),
        },
        "chain": chain,
    }


# ------------------------------------------------------------------ fault injection


def _copy_evidence(source: Path) -> Path:
    target = Path(tempfile.mkdtemp(prefix="tap-lock-verify-")) / "session"
    shutil.copytree(source, target)
    return target


def adversarials(source: Path) -> list[dict[str, Any]]:
    """Mutations of the real evidence that the judge must reject."""

    results: list[dict[str, Any]] = []

    def record(name: str, detected: bool, detail: str) -> None:
        results.append({"mutation": name, "detected": bool(detected), "detail": detail})

    # 1. one field changed in the middle of the chain, stored hash left as it was.
    tampered = _copy_evidence(source)
    stream = tampered / "STREAM.jsonl"
    rows = [
        json.loads(line) for line in stream.read_text(encoding="utf-8").splitlines() if line.strip()
    ]
    index = max(0, len(rows) // 2)
    original = str(rows[index]["entry"].get("recorded_at_utc"))
    rows[index]["entry"]["recorded_at_utc"] = original[:-1] + (
        "Z" if not original.endswith("Z") else "X"
    )
    stream.write_text(
        "\n".join(json.dumps(row, sort_keys=True) for row in rows) + "\n", encoding="utf-8"
    )
    verdict = judge(tampered)
    record(
        "one byte changed in the stream",
        not verdict["checks"]["stream_chain_intact"],
        verdict["chain"].get("reason", ""),
    )
    shutil.rmtree(tampered.parent)

    # 2. the recovery claim removed (everything else intact).
    rows = [row for row in _entries(source) if row["entry"].get("kind") != "LOCK_RECLAIMED"]
    verdict = judge(source, rows)
    record(
        "LOCK_RECLAIMED row removed",
        not verdict["checks"]["reclaim_is_recorded_with_a_proved_reason"],
        "a resume without the reclaim row is not evidence of a reclaim",
    )

    # 3. a lock left behind, held by this very process.
    littered = _copy_evidence(source)
    lock = littered / "STREAM.jsonl.lock"
    lock.write_text(
        json.dumps(
            {
                "host": socket.gethostname(),
                "pid": os.getpid(),
                "process_start_ms": None,
                "token": "verifier" * 4,
                "fence": 99,
            }
        ),
        encoding="utf-8",
    )
    verdict = judge(littered)
    record(
        "a live lock left behind",
        not verdict["checks"]["no_lock_left_after_resume"],
        "a leftover lock must fail the run, however healthy the stream looks",
    )
    shutil.rmtree(littered.parent)

    # 4. the resumed session's SESSION_START removed: one start cannot prove a continuation.
    rows = [
        row
        for row in _entries(source)
        if not (
            row["entry"].get("kind") == "SESSION_START"
            and (row["entry"].get("provenance") or {}).get("resumed") is True
        )
    ]
    verdict = judge(source, rows)
    record(
        "the resumed SESSION_START removed",
        not verdict["checks"]["a_crash_then_a_continuation"],
        "one start cannot prove a continuation",
    )
    return results


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Independent verification of lock recovery")
    parser.add_argument(
        "--evidence",
        default=str(REPO / "reports" / "ai-bots" / "CODEX-PAPER-UNBLOCK-001" / "lock-recovery"),
    )
    parser.add_argument("--out", default=None)
    args = parser.parse_args(argv)

    evidence = Path(args.evidence)
    session = evidence / "session"
    verdict = judge(session)
    mutations = adversarials(session)
    false_success = [item for item in mutations if not item["detected"]]
    payload = {
        "schema_version": "TAP_LOCK_RECOVERY_VERIFICATION_V1",
        "evidence": str(evidence),
        "builder": "scripts/tap_lock_recovery_rehearsal.py",
        "verifier": "scripts/tap_lock_recovery_verify.py",
        "judgement": verdict,
        "adversarial": mutations,
        "false_success": len(false_success),
        "verdict": "PASS" if verdict["verdict"] == "PASS" and not false_success else "FAIL",
    }
    out = Path(args.out) if args.out else evidence / "VERIFICATION.json"
    out.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"verdict": payload["verdict"], "checks": verdict["checks"]}, indent=2))
    print(json.dumps({"adversarial": mutations, "false_success": len(false_success)}, indent=2))
    return 0 if payload["verdict"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
