"""RFC-DEF-RUN-019 / WP-04D — the verifier has to know how to say no.

These cases do not check that the verifier says ``PASS``. They check that it **stops**
saying it when a byte, a digest, an ordering or a parent changes, and that it says
``NOT_EVIDENCED`` — not ``PASS``, not ``FAIL`` — when a session predates the block.

The tampering is done the hard way: the whole hash chain is rebuilt after each mutation,
so what the verifier catches is the content of the claim and not a broken link it could
have noticed for free.
"""

from __future__ import annotations

import ast
import hashlib
import importlib.util
import json
import subprocess
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

import pytest

from trading_bot.vision import provenance
from trading_bot.vision.ledger import DecisionLedger, read_entries

REPO = Path(__file__).resolve().parents[3]


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


verifier = load_module("def_run_019_verify", REPO / "scripts" / "def_run_019_verify.py")

CONFIG: dict[str, Any] = {
    "symbols": ["BTCUSDT"],
    "timeframe": "5m",
    "window_bars": 20,
    "equity": 10_000.0,
    "signal_source": "legacy_parity",
}
PROVIDER: dict[str, Any] = {
    "signal": {"source": "legacy_parity", "provider": "paper-script"},
    "data": {"kind": "default", "name": "binance_rest", "base_url": "https://example"},
}
STARTED_MS = 1_700_000_100_000


def git(root: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", "-C", str(root), *args], capture_output=True, text=True, check=True
    )
    return completed.stdout.strip()


def make_repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    for relative in provenance.SESSION_PATHS:
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(f"# {relative}\n", encoding="utf-8", newline="\n")
    git(root, "init", "-q")
    git(root, "add", "-A")
    git(
        root,
        "-c",
        "user.email=agent@example.invalid",
        "-c",
        "user.name=agent",
        "commit",
        "-q",
        "-m",
        "runtime",
    )
    #: Materialise the files through Git's own checkout filters, exactly as a real
    #: checkout would: otherwise a test on a machine with ``autocrlf`` would compare LF
    #: bytes against the CRLF bytes Git would produce and call every file modified.
    for target in [item for item in root.rglob("*") if item.is_file()]:
        if ".git" not in target.parts:
            target.unlink()
    git(root, "checkout", "--", ".")
    return root


def block_for(root: Path) -> dict[str, Any]:
    block = provenance.capture_session(
        root,
        config=CONFIG,
        provider=PROVIDER,
        started_at_ms=STARTED_MS,
        mode="PAPER",
    )
    assert block["unavailable_reasons"] == []
    return block


def cycle_row(out: Path, block: dict[str, Any], cycle: int) -> dict[str, Any]:
    directory = out / "cycles" / f"cycle-{cycle:04d}"
    directory.mkdir(parents=True, exist_ok=True)
    ledger = directory / "ledger.jsonl"
    ledger.write_text(
        f'{{"kind": "RUN", "cycle": {cycle}}}\n', encoding="utf-8", newline="\n"
    )
    return {
        "cycle": cycle,
        "status": "EXECUTED",
        "mode": "PAPER",
        "provenance": {
            "run_id": block["run_id"],
            "session_id": block["session_id"],
            "pinned_identity": block["pinned_identity"],
            "runtime_digest": block["runtime"]["digest"],
        },
        "ledger": {
            "path": ledger.relative_to(out).as_posix(),
            "sha256": hashlib.sha256(ledger.read_bytes()).hexdigest(),
        },
    }


def write_rows(out: Path, rows: Sequence[tuple[str, dict[str, Any]]]) -> None:
    stream = out / "STREAM.jsonl"
    lock = stream.with_suffix(stream.suffix + ".lock")
    for path in (stream, lock):
        if path.exists():
            path.unlink()
    handle = DecisionLedger(stream).open()
    try:
        for kind, payload in rows:
            handle.append(kind, payload)
    finally:
        handle.close()


def make_session(tmp_path: Path, root: Path, *, cycles: int = 2) -> Path:
    out = tmp_path / "session"
    out.mkdir(exist_ok=True)
    block = block_for(root)
    rows: list[tuple[str, dict[str, Any]]] = [
        ("SESSION_START", {"schema_version": "PROSPECTIVE_PAPER_SESSION_V1", "mode": "PAPER"}),
        ("SESSION_PROVENANCE", block),
    ]
    for cycle in range(1, cycles + 1):
        rows.append(("CYCLE", cycle_row(out, block, cycle)))
    rows.append(
        (
            "SESSION_END",
            {
                "schema_version": "PROSPECTIVE_PAPER_SUMMARY_V1",
                "runtime_stable": True,
                "provenance": {
                    "run_id": block["run_id"],
                    "session_id": block["session_id"],
                    "pinned_identity": block["pinned_identity"],
                    "runtime_digest": block["runtime"]["digest"],
                    "resumed": False,
                    "chain": [],
                },
            },
        )
    )
    write_rows(out, rows)
    (out / "SESSION_PROVENANCE.json").write_text(
        json.dumps(block, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n"
    )
    record = out / "provenance" / f"session-{block['session_id']}.json"
    record.parent.mkdir(parents=True, exist_ok=True)
    record.write_text(
        json.dumps(block, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n"
    )
    return out


def entries_of(session: Path) -> list[dict[str, Any]]:
    return [row["entry"] for row in read_entries(session / "STREAM.jsonl")]


def mutate_block(session: Path, change: Callable[[dict[str, Any]], None]) -> None:
    """Change the block and rebuild chain and file, so only the claim is wrong."""

    rows = [
        (entry["kind"], {k: v for k, v in entry.items() if k != "kind"})
        for entry in entries_of(session)
    ]
    block = next(payload for kind, payload in rows if kind == "SESSION_PROVENANCE")
    change(block)
    write_rows(session, rows)
    #: The chain adds ``recorded_at_utc``; the block file never carries it, so the two
    #: stay comparable instead of looking like a disagreement for the wrong reason.
    written = {key: value for key, value in block.items() if key != "recorded_at_utc"}
    serialised = json.dumps(written, indent=2, sort_keys=True) + "\n"
    (session / "SESSION_PROVENANCE.json").write_text(
        serialised, encoding="utf-8", newline="\n"
    )
    record = session / "provenance" / f"session-{written['session_id']}.json"
    record.write_text(serialised, encoding="utf-8", newline="\n")


def state(verdict: dict[str, Any], domain: str) -> str:
    return verdict["domains"][domain]["state"]


# --------------------------------------------------------------------------- positives


def test_a_clean_session_passes_and_declares_its_limits(tmp_path: Path) -> None:
    root = make_repo(tmp_path)
    session = make_session(tmp_path, root)

    verdict = verifier.judge_session(session, root)

    assert verdict["overall"] == "PASS"
    for domain in ("chain", "code", "identity", "evidence", "stability"):
        assert state(verdict, domain) == "PASS", (domain, verdict["domains"][domain])
    #: Nothing resumed here, so the verifier says so instead of inventing a pass.
    assert state(verdict, "resume") == "NOT_EVIDENCED"
    assert verdict["reasons"] == ["resume:NO_RESUME_TO_JUDGE"]
    assert verdict["session_id"] == json.loads(
        (session / "SESSION_PROVENANCE.json").read_text(encoding="utf-8")
    )["session_id"]


def test_the_cli_writes_a_verdict_and_reports_no_false_success(tmp_path: Path) -> None:
    root = make_repo(tmp_path)
    session = make_session(tmp_path, root)
    out = tmp_path / "VERDICT.json"

    exit_code = verifier.main(["--session", str(session), "--repo", str(root), "--out", str(out)])

    assert exit_code == 0
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload["independent"] is True
    assert payload["imports_producer"] is False
    assert payload["overall"] == "PASS"
    assert payload["false_success"] == 0


# --------------------------------------------------------------------------- negatives


def test_a_commit_that_does_not_exist_fails(tmp_path: Path) -> None:
    root = make_repo(tmp_path)
    session = make_session(tmp_path, root)
    mutate_block(session, lambda block: block["code"].update({"commit": "f" * 40}))

    verdict = verifier.judge_session(session, root)

    assert verdict["overall"] == "FAIL"
    assert "code:COMMIT_RESOLVES" in verdict["reasons"]


def test_an_edited_byte_with_an_intact_blob_fails(tmp_path: Path) -> None:
    root = make_repo(tmp_path)
    session = make_session(tmp_path, root)

    def change(block: dict[str, Any]) -> None:
        files = block["code"]["files"]
        files["src/trading_bot/vision/lane.py"]["sha256"] = files[
            "src/trading_bot/vision/ledger.py"
        ]["sha256"]

    mutate_block(session, change)
    verdict = verifier.judge_session(session, root)

    assert verdict["overall"] == "FAIL"
    assert "code:BYTES_AT_COMMIT" in verdict["reasons"]
    assert "code:BLOBS_AT_COMMIT" not in verdict["reasons"]


def test_a_trimmed_manifest_fails_even_though_it_agrees_with_itself(tmp_path: Path) -> None:
    root = make_repo(tmp_path)
    session = make_session(tmp_path, root)
    trimmed = "src/trading_bot/vision/prospective.py"

    def change(block: dict[str, Any]) -> None:
        block["code"]["files"].pop(trimmed)
        block["code"]["runtime_paths"] = [
            name for name in block["code"]["runtime_paths"] if name != trimmed
        ]
        block["runtime"]["paths"] = [name for name in block["runtime"]["paths"] if name != trimmed]
        block["runtime"]["sha256"].pop(trimmed)

    mutate_block(session, change)
    verdict = verifier.judge_session(session, root)

    assert verdict["overall"] == "FAIL"
    assert "code:RUNTIME_PATHS_COVERED" in verdict["reasons"]


def test_a_dirty_runtime_declared_by_the_block_fails(tmp_path: Path) -> None:
    root = make_repo(tmp_path)
    session = make_session(tmp_path, root)

    def change(block: dict[str, Any]) -> None:
        block["code"]["worktree"]["runtime_dirty"] = ["src/trading_bot/risk/manager.py"]

    mutate_block(session, change)
    verdict = verifier.judge_session(session, root)

    assert verdict["overall"] == "FAIL"
    assert "code:WORKTREE_RUNTIME_CLEAN" in verdict["reasons"]


def test_a_session_without_a_block_is_not_evidenced(tmp_path: Path) -> None:
    root = make_repo(tmp_path)
    session = make_session(tmp_path, root)
    rows = [
        (kind, payload)
        for kind, payload in (
            (entry["kind"], {k: v for k, v in entry.items() if k != "kind"})
            for entry in entries_of(session)
        )
        if kind != "SESSION_PROVENANCE"
    ]
    write_rows(session, rows)
    (session / "SESSION_PROVENANCE.json").unlink()

    verdict = verifier.judge_session(session, root)

    assert verdict["overall"] == "NOT_EVIDENCED"
    assert "identity:PROVENANCE_ROW_PRESENT" in verdict["reasons"]


def test_a_block_written_after_the_first_decision_fails(tmp_path: Path) -> None:
    root = make_repo(tmp_path)
    session = make_session(tmp_path, root)
    rows = [
        (entry["kind"], {k: v for k, v in entry.items() if k != "kind"})
        for entry in entries_of(session)
    ]
    block_index = next(index for index, (kind, _) in enumerate(rows) if kind == "SESSION_PROVENANCE")
    moved = rows.pop(block_index)
    cycle_index = next(index for index, (kind, _) in enumerate(rows) if kind == "CYCLE")
    rows.insert(cycle_index + 1, moved)
    write_rows(session, rows)

    verdict = verifier.judge_session(session, root)

    assert verdict["overall"] == "FAIL"
    assert "evidence:PROVENANCE_PRECEDES_ITS_CYCLES" in verdict["reasons"]


def test_a_cycle_without_the_pinned_identity_fails(tmp_path: Path) -> None:
    root = make_repo(tmp_path)
    session = make_session(tmp_path, root)
    rows = [
        (entry["kind"], {k: v for k, v in entry.items() if k != "kind"})
        for entry in entries_of(session)
    ]
    for kind, payload in rows:
        if kind == "CYCLE":
            payload["provenance"]["pinned_identity"] = "0" * 64
            break
    write_rows(session, rows)

    verdict = verifier.judge_session(session, root)

    assert verdict["overall"] == "FAIL"
    assert "evidence:EVERY_CYCLE_CARRIES_THE_PIN" in verdict["reasons"]


def test_a_runtime_drift_that_stops_the_session_is_detected(tmp_path: Path) -> None:
    root = make_repo(tmp_path)
    session = make_session(tmp_path, root, cycles=1)
    rows = [
        (entry["kind"], {k: v for k, v in entry.items() if k != "kind"})
        for entry in entries_of(session)
    ]
    rows.insert(
        -1,
        (
            "BLOCKED",
            {
                "cycle": 2,
                "reason": "RUNTIME_DRIFT",
                "detail": {"changed_paths": ["src/trading_bot/vision/lane.py"]},
            },
        ),
    )
    write_rows(session, rows)

    verdict = verifier.judge_session(session, root)

    assert verdict["overall"] == "FAIL"
    assert "stability:NO_DRIFT_OBSERVED" in verdict["reasons"]
    assert "stability:DRIFT_CONTAINED" not in verdict["reasons"]


def test_a_decision_taken_after_the_drift_fails_the_containment_check(tmp_path: Path) -> None:
    root = make_repo(tmp_path)
    session = make_session(tmp_path, root, cycles=2)
    rows = [
        (entry["kind"], {k: v for k, v in entry.items() if k != "kind"})
        for entry in entries_of(session)
    ]
    rows.insert(
        2,
        (
            "BLOCKED",
            {
                "cycle": 2,
                "reason": "RUNTIME_DRIFT",
                "detail": {"changed_paths": ["src/trading_bot/vision/lane.py"]},
            },
        ),
    )
    write_rows(session, rows)

    verdict = verifier.judge_session(session, root)

    assert "stability:DRIFT_CONTAINED" in verdict["reasons"]


def test_a_resumed_session_whose_parent_pin_moved_fails(tmp_path: Path) -> None:
    root = make_repo(tmp_path)
    parent = block_for(root)
    child = provenance.capture_session(
        root,
        config=CONFIG,
        provider=PROVIDER,
        started_at_ms=STARTED_MS + 900_000,
        mode="PAPER",
        resume_parent={**parent, "chain": []},
    )
    assert child["resume"]["resumed"] is True

    out = tmp_path / "child"
    out.mkdir()
    rows: list[tuple[str, dict[str, Any]]] = [
        ("SESSION_START", {"schema_version": "PROSPECTIVE_PAPER_SESSION_V1"}),
        ("SESSION_PROVENANCE", child),
        ("CYCLE", cycle_row(out, child, 1)),
        (
            "SESSION_END",
            {
                "runtime_stable": True,
                "provenance": {
                    "pinned_identity": child["pinned_identity"],
                    "runtime_digest": child["runtime"]["digest"],
                    "resumed": True,
                    "chain": child["resume"]["chain"],
                },
            },
        ),
    ]
    write_rows(out, rows)
    (out / "SESSION_PROVENANCE.json").write_text(
        json.dumps(child, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n"
    )
    records = out / "provenance"
    records.mkdir()
    (records / f"session-{child['session_id']}.json").write_text(
        json.dumps(child, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n"
    )
    forged = {**parent, "pinned_identity": "1" * 64}
    (records / f"session-{parent['session_id']}.json").write_text(
        json.dumps(forged, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n"
    )

    verdict = verifier.judge_session(out, root)

    assert verdict["overall"] == "FAIL"
    #: Only the continuation lives here, so the parent is judged through its own record.
    assert "resume:PINNED_IDENTITY_PRESERVED[0]" in verdict["reasons"]


def test_a_resumed_session_whose_stream_parent_moved_fails(tmp_path: Path) -> None:
    root = make_repo(tmp_path)
    parent = block_for(root)
    child = provenance.capture_session(
        root,
        config=CONFIG,
        provider=PROVIDER,
        started_at_ms=STARTED_MS + 900_000,
        mode="PAPER",
        resume_parent={**parent, "chain": []},
    )
    out = tmp_path / "both"
    out.mkdir()
    rows: list[tuple[str, dict[str, Any]]] = [
        ("SESSION_START", {"schema_version": "PROSPECTIVE_PAPER_SESSION_V1"}),
        ("SESSION_PROVENANCE", parent),
        ("CYCLE", cycle_row(out, parent, 1)),
        ("SESSION_END", {"runtime_stable": True, "provenance": {"pinned_identity": parent["pinned_identity"]}}),
        ("SESSION_START", {"schema_version": "PROSPECTIVE_PAPER_SESSION_V1"}),
        ("SESSION_PROVENANCE", child),
        ("CYCLE", cycle_row(out, child, 2)),
        ("SESSION_END", {"runtime_stable": True, "provenance": {"pinned_identity": child["pinned_identity"]}}),
    ]
    write_rows(out, rows)
    (out / "SESSION_PROVENANCE.json").write_text(
        json.dumps(child, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n"
    )
    records = out / "provenance"
    records.mkdir()
    for block in (parent, child):
        (records / f"session-{block['session_id']}.json").write_text(
            json.dumps(block, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n"
        )
    #: An intact pair, then the same pair with the parent's pin moved.
    assert verifier.judge_session(out, root)["overall"] == "PASS"
    rebuilt = [
        (entry["kind"], {k: v for k, v in entry.items() if k != "kind"})
        for entry in entries_of(out)
    ]
    for kind, payload in rebuilt:
        if kind == "SESSION_PROVENANCE" and payload.get("pinned_identity") == parent["pinned_identity"]:
            payload["pinned_identity"] = "1" * 64
            break
    write_rows(out, rebuilt)
    verdict = verifier.judge_session(out, root)
    assert verdict["overall"] == "FAIL"
    assert "resume:PINNED_IDENTITY_PRESERVED[1]" in verdict["reasons"]


def test_a_rewritten_stream_breaks_its_own_chain(tmp_path: Path) -> None:
    root = make_repo(tmp_path)
    session = make_session(tmp_path, root)
    stream = session / "STREAM.jsonl"
    rows = stream.read_text(encoding="utf-8").splitlines()
    row = json.loads(rows[2])
    row["entry"]["cycle"] = 99
    rows[2] = json.dumps(row, sort_keys=True, separators=(",", ":"))
    stream.write_text("\n".join(rows) + "\n", encoding="utf-8", newline="\n")

    verdict = verifier.judge_session(session, root)

    assert verdict["overall"] == "FAIL"
    assert "chain:CHAIN_INTACT" in verdict["reasons"]


def test_a_session_recorded_before_the_block_is_not_evidenced(tmp_path: Path) -> None:
    old = tmp_path / "old-session"
    old.mkdir()
    write_rows(old, [("SESSION_START", {"schema_version": "PROSPECTIVE_PAPER_SESSION_V1"})])

    verdict = verifier.judge_history(old)

    assert verdict["overall"] == "NOT_EVIDENCED"
    assert verdict["reason"] == "PRE_CONTROL_SESSION"
    assert verdict["has_provenance"] is False


def test_the_verifier_does_not_import_the_producer() -> None:
    source = (REPO / "scripts" / "def_run_019_verify.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imported.add(node.module or "")
    assert not [name for name in imported if name.startswith("trading_bot")]
    #: The verifier must not even reach for the producer's helpers by name.
    assert "capture_session" not in source
    assert "sys.path" not in source


def test_an_unrelated_failure_cannot_be_reported_as_a_pass(tmp_path: Path) -> None:
    """A PASS in one domain never lifts a global FAIL, whatever order the checks run in."""

    root = make_repo(tmp_path)
    session = make_session(tmp_path, root)
    mutate_block(
        session,
        lambda block: block["code"]["worktree"].update(
            {"runtime_dirty": ["src/trading_bot/risk/manager.py"]}
        ),
    )
    verdict = verifier.judge_session(session, root)

    assert state(verdict, "identity") == "PASS"
    assert state(verdict, "evidence") == "PASS"
    assert state(verdict, "code") == "FAIL"
    assert verdict["overall"] == "FAIL"


@pytest.mark.parametrize(
    ("field", "value", "reason"),
    [
        ("run_id", "run-00000000000000000000", "identity:RUN_ID_DERIVED"),
        ("session_id", "sess-00000000000000000000", "identity:SESSION_ID_DERIVED"),
        ("mode", "LIVE", "identity:MODE_IS_PAPER"),
        ("environment_digest", "0" * 64, "identity:ENVIRONMENT_DIGEST_RECOMPUTED"),
        ("pinned_identity", "2" * 64, "identity:PINNED_IDENTITY_RECOMPUTED"),
    ],
)
def test_each_identity_claim_is_recomputed(
    tmp_path: Path, field: str, value: str, reason: str
) -> None:
    root = make_repo(tmp_path)
    session = make_session(tmp_path, root, cycles=1)
    mutate_block(session, lambda block: block.update({field: value}))

    verdict = verifier.judge_session(session, root)

    assert verdict["overall"] == "FAIL"
    assert reason in verdict["reasons"]
