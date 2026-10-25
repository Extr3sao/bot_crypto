"""DEF-RUN-019 / WP-04D — the controls that must fail, run against the real evidence.

A verifier that has only ever seen a good session has not been tested. Each control here
copies the *real* session directory produced by the live run, breaks exactly one claim,
rebuilds the hash chain so the break cannot be caught for free, and asks the verifier for
a verdict. The chain is rebuilt by this script with its own hashing: it does not import
the producer and it does not import the verifier.

Usage::

    python scripts/def_run_019_negative_controls.py \
        --session reports/.../evidence/live-session-2 \
        --repo ../rfc019-wp04 --out reports/.../evidence/NEGATIVE_CONTROLS.json
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))
GENESIS = "0" * 64
BLOCK_KIND = "SESSION_PROVENANCE"


def canonical(payload: Any) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def chain(entries: list[dict[str, Any]], path: Path) -> None:
    previous = GENESIS
    lines: list[str] = []
    for seq, entry in enumerate(entries, start=1):
        digest = hashlib.sha256(
            canonical({"seq": seq, "prev_sha256": previous, "entry": entry}).encode("utf-8")
        ).hexdigest()
        lines.append(canonical({"seq": seq, "prev_sha256": previous, "entry": entry, "sha256": digest}))
        previous = digest
    path.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")


def read_stream(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    return [json.loads(line)["entry"] for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def write_block_files(session: Path, block: dict[str, Any]) -> None:
    serialised = json.dumps(block, indent=2, sort_keys=True) + "\n"
    (session / "SESSION_PROVENANCE.json").write_text(serialised, encoding="utf-8", newline="\n")
    records = session / "provenance"
    records.mkdir(exist_ok=True)
    for path in records.glob("session-*.json"):
        path.unlink()
    (records / f"session-{block['session_id']}.json").write_text(
        serialised, encoding="utf-8", newline="\n"
    )


@dataclass
class Control:
    name: str
    expectation: str
    apply: Callable[[Path], None]
    code: str


def block_payload(entry: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in entry.items() if key not in ("kind", "recorded_at_utc")}


def controls() -> list[Control]:
    def forged_commit(session: Path) -> None:
        entries = read_stream(session / "STREAM.jsonl")
        for entry in entries:
            if entry.get("kind") == BLOCK_KIND:
                entry["code"]["commit"] = "f" * 40
                entry["code"]["head_at_capture"] = "f" * 40
                write_block_files(session, block_payload(entry))
                break
        chain(entries, session / "STREAM.jsonl")

    def edited_byte(session: Path) -> None:
        entries = read_stream(session / "STREAM.jsonl")
        for entry in entries:
            if entry.get("kind") == BLOCK_KIND:
                files = entry["code"]["files"]
                #: One file's recorded hash replaced by another's: the blob still resolves,
                #: so only a byte-level check can notice.
                files["src/trading_bot/vision/lane.py"]["sha256"] = files[
                    "src/trading_bot/vision/ledger.py"
                ]["sha256"]
                write_block_files(session, block_payload(entry))
                break
        chain(entries, session / "STREAM.jsonl")

    def trimmed_manifest(session: Path) -> None:
        entries = read_stream(session / "STREAM.jsonl")
        victim = "src/trading_bot/vision/prospective.py"
        for entry in entries:
            if entry.get("kind") == BLOCK_KIND:
                entry["code"]["files"].pop(victim, None)
                entry["code"]["runtime_paths"] = [
                    name for name in entry["code"].get("runtime_paths", []) if name != victim
                ]
                entry["runtime"]["paths"] = [
                    name for name in entry.get("runtime", {}).get("paths", []) if name != victim
                ]
                entry.get("runtime", {}).get("sha256", {}).pop(victim, None)
                write_block_files(session, block_payload(entry))
                break
        chain(entries, session / "STREAM.jsonl")

    def removed_block(session: Path) -> None:
        entries = [entry for entry in read_stream(session / "STREAM.jsonl") if entry.get("kind") != BLOCK_KIND]
        chain(entries, session / "STREAM.jsonl")
        (session / "SESSION_PROVENANCE.json").unlink(missing_ok=True)
        shutil.rmtree(session / "provenance", ignore_errors=True)

    def late_block(session: Path) -> None:
        entries = read_stream(session / "STREAM.jsonl")
        index = next(i for i, entry in enumerate(entries) if entry.get("kind") == BLOCK_KIND)
        block = entries.pop(index)
        first_cycle = next(i for i, entry in enumerate(entries) if entry.get("kind") == "CYCLE")
        entries.insert(first_cycle + 1, block)
        chain(entries, session / "STREAM.jsonl")

    def dirty_runtime(session: Path) -> None:
        entries = read_stream(session / "STREAM.jsonl")
        for entry in entries:
            if entry.get("kind") == BLOCK_KIND:
                entry["code"]["worktree"]["runtime_dirty"] = [
                    "src/trading_bot/research/economic_recovery/alpha15.py"
                ]
                write_block_files(session, block_payload(entry))
                break
        chain(entries, session / "STREAM.jsonl")

    return [
        Control("forged_commit", "FAIL", forged_commit, "code:COMMIT_RESOLVES"),
        Control("edited_byte_intact_blob", "FAIL", edited_byte, "code:BYTES_AT_COMMIT"),
        Control("trimmed_manifest", "FAIL", trimmed_manifest, "code:RUNTIME_PATHS_COVERED"),
        Control("block_removed", "NOT_EVIDENCED", removed_block, "identity:PROVENANCE_ROW_PRESENT"),
        Control("block_after_first_decision", "FAIL", late_block, "evidence:PROVENANCE_PRECEDES_ITS_CYCLES"),
        Control("dirty_runtime_declared", "FAIL", dirty_runtime, "code:WORKTREE_RUNTIME_CLEAN"),
    ]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Negative controls over a real session")
    parser.add_argument("--session", required=True)
    parser.add_argument("--repo", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--workdir", default=None)
    args = parser.parse_args(argv)

    session = Path(args.session).resolve()
    repo = Path(args.repo).resolve()
    out = Path(args.out)
    workdir = Path(args.workdir) if args.workdir else out.parent / "negative"
    workdir.mkdir(parents=True, exist_ok=True)

    results: list[dict[str, Any]] = []
    for control in controls():
        target = workdir / control.name
        if target.exists():
            shutil.rmtree(target)
        shutil.copytree(session, target)
        control.apply(target)
        verdict_path = target / "VERDICT.json"
        completed = subprocess.run(
            [
                sys.executable,
                str(REPO / "scripts" / "def_run_019_verify.py"),
                "--session",
                str(target),
                "--repo",
                str(repo),
                "--out",
                str(verdict_path),
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        verdict = json.loads(verdict_path.read_text(encoding="utf-8")) if verdict_path.is_file() else {}
        record = (verdict.get("sessions") or [{}])[0]
        hits = control.code in (record.get("reasons") or [])
        results.append(
            {
                "control": control.name,
                "expected": control.expectation,
                "observed": record.get("overall"),
                "verifier_exit": completed.returncode,
                "expected_check_present": hits,
                "expected_check": control.code,
                "reasons": record.get("reasons"),
                "detected": record.get("overall") == control.expectation and hits,
            }
        )
        print(
            f"{control.name:32s} expected={control.expectation:14s} "
            f"observed={record.get('overall')!s:14s} check={hits}",
            flush=True,
        )

    payload = {
        "schema_version": "DEF_RUN_019_NEGATIVE_CONTROLS_V1",
        "session": str(session),
        "repo": str(repo),
        "controls": results,
        "all_detected": all(row["detected"] for row in results),
        "false_success": 0 if all(row["detected"] for row in results) else 1,
    }
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n"
    )
    print(f"all_detected={payload['all_detected']}")
    return 0 if payload["all_detected"] else 1


if __name__ == "__main__":
    sys.exit(main())
