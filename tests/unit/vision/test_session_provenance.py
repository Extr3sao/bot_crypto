"""UNIT — the session block: which bytes are about to decide, and does it say so.

The block is a set of facts, not a verdict. These tests pin what it must record, when it
refuses to record anything usable, and what a resume is allowed to accept.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

import pytest

from trading_bot.vision import provenance
from trading_bot.vision.provenance import (
    SESSION_PATHS,
    SESSION_SCHEMA,
    RuntimeNotProvable,
    assert_provable,
    blocking_reasons,
    capture_session,
    config_fingerprint,
    drifted,
    environment,
    environment_digest,
    file_hashes,
    resume_reasons,
    runtime_digest,
)


def git(root: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", "-C", str(root), *args], capture_output=True, text=True, check=True
    )
    return completed.stdout.strip()


def build_repo(root: Path) -> Path:
    """A real repository containing every runtime path, so capture has something to bind."""

    for relative in SESSION_PATHS:
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"# {relative}\n", encoding="utf-8", newline="\n")
    (root / "README.md").write_text("a repository\n", encoding="utf-8", newline="\n")
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
    return root


CONFIG: dict[str, Any] = {
    "symbols": ["BTCUSDT"],
    "timeframe": "5m",
    "window_bars": 20,
    "signal_source": "legacy_parity",
}
PROVIDER: dict[str, Any] = {
    "signal": {"source": "legacy_parity", "provider": "paper-script"},
    "data": {"kind": "default", "name": "binance_rest", "base_url": "https://example"},
}


def build_block(root: Path, **overrides: Any) -> dict[str, Any]:
    kwargs: dict[str, Any] = {
        "config": CONFIG,
        "provider": PROVIDER,
        "started_at_ms": 1_700_000_000_000,
        "mode": "PAPER",
    }
    kwargs.update(overrides)
    return capture_session(root, **kwargs)


def test_a_clean_repository_produces_a_usable_block(tmp_path: Path) -> None:
    root = build_repo(tmp_path / "repo")
    block = build_block(root)

    assert block["schema"] == SESSION_SCHEMA
    assert block["unavailable_reasons"] == []
    assert blocking_reasons(block) == []
    assert block["code"]["commit"] == git(root, "rev-parse", "HEAD")
    assert sorted(block["runtime"]["sha256"]) == sorted(SESSION_PATHS)
    assert block["runtime"]["digest"] == runtime_digest(block["runtime"]["sha256"])
    assert block["pinned_identity"] == provenance.identity_digest(
        commit=block["code"]["commit"],
        runtime=block["runtime"]["sha256"],
        config_fingerprint_value=block["config"]["fingerprint"],
    )
    assert assert_provable(block)["run_id"] == block["run_id"]


def test_the_identifiers_are_derived_and_not_random(tmp_path: Path) -> None:
    root = build_repo(tmp_path / "repo")

    first = build_block(root)
    again = build_block(root)
    later = build_block(root, started_at_ms=1_700_000_060_000)

    assert first["run_id"] == again["run_id"] == later["run_id"]
    assert first["session_id"] == again["session_id"]
    assert first["session_id"] != later["session_id"]
    assert first["run_id"] == "run-" + first["pinned_identity"][:20]


def test_a_dirty_runtime_path_refuses_and_names_itself(tmp_path: Path) -> None:
    root = build_repo(tmp_path / "repo")
    target = root / "src/trading_bot/vision/lane.py"
    target.write_text("# edited while the market was open\n", encoding="utf-8", newline="\n")

    block = build_block(root)

    assert "RUNTIME_PATHS_DIRTY" in block["unavailable_reasons"]
    assert block["code"]["worktree"]["runtime_dirty"] == ["src/trading_bot/vision/lane.py"]
    with pytest.raises(RuntimeNotProvable) as excinfo:
        assert_provable(block)
    assert excinfo.value.reasons == ["RUNTIME_PATHS_DIRTY"]
    assert excinfo.value.block["run_id"] == block["run_id"]


def test_edits_outside_the_runtime_are_allowed_and_disclosed(tmp_path: Path) -> None:
    root = build_repo(tmp_path / "repo")
    (root / "README.md").write_text("another agent was here\n", encoding="utf-8", newline="\n")
    (root / "reports").mkdir()
    (root / "reports" / "x.json").write_text("{}\n", encoding="utf-8", newline="\n")

    block = build_block(root)

    assert block["unavailable_reasons"] == []
    worktree = block["code"]["worktree"]
    assert worktree["runtime_dirty"] == []
    assert worktree["fully_clean"] is False
    assert worktree["dirty_outside_runtime_total"] == 2
    assert "README.md" in worktree["dirty_outside_runtime"]
    assert assert_provable(block)


def test_a_root_without_git_is_refused(tmp_path: Path) -> None:
    root = tmp_path / "loose"
    for relative in SESSION_PATHS:
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("x\n", encoding="utf-8", newline="\n")

    block = build_block(root)

    assert "NOT_A_REPOSITORY" in block["unavailable_reasons"]
    assert block["code"]["commit"] is None
    with pytest.raises(RuntimeNotProvable):
        assert_provable(block)


def test_a_missing_runtime_file_is_refused(tmp_path: Path) -> None:
    root = build_repo(tmp_path / "repo")
    (root / "src/trading_bot/vision/quotes.py").unlink()

    block = build_block(root)

    assert "RUNTIME_PATH_MISSING" in block["unavailable_reasons"]
    assert block["runtime"]["sha256"]["src/trading_bot/vision/quotes.py"] == "MISSING"
    with pytest.raises(RuntimeNotProvable):
        assert_provable(block)


def test_the_configuration_fingerprint_covers_every_declared_field() -> None:
    base = config_fingerprint(CONFIG)
    assert config_fingerprint(dict(reversed(list(CONFIG.items())))) == base
    for field, value in (
        ("window_bars", 21),
        ("timeframe", "1m"),
        ("signal_source", "strategy_experimental"),
        ("max_cycles", 3),
        ("stale_after_ms", 150_001),
    ):
        changed = dict(CONFIG)
        changed[field] = value
        assert config_fingerprint(changed) != base, field


def test_the_runtime_digest_changes_only_when_a_byte_does(tmp_path: Path) -> None:
    root = build_repo(tmp_path / "repo")
    before = file_hashes(root)
    assert runtime_digest(before) == runtime_digest(file_hashes(root))

    (root / "src/trading_bot/risk/manager.py").write_text(
        "# one byte more\n", encoding="utf-8", newline="\n"
    )
    after = file_hashes(root)
    assert runtime_digest(after) != runtime_digest(before)
    assert drifted(after, before) == ["src/trading_bot/risk/manager.py"]


def test_the_environment_block_is_recorded_and_digestible() -> None:
    block = environment()
    assert block["python_version"]
    assert block["distributions"]["PyYAML"]
    assert environment_digest(block) == environment_digest(dict(block))
    #: The executable path is disclosed but must not be what a resume compares against.
    moved = dict(block)
    moved["executable"] = "C:/elsewhere/python.exe"
    assert environment_digest(moved) == environment_digest(block)


def test_a_resume_accepts_the_same_facts_and_names_everything_else(tmp_path: Path) -> None:
    root = build_repo(tmp_path / "repo")
    first = build_block(root)
    assert resume_reasons(first, build_block(root)) == []

    #: Same commit, different bytes on disk: the pin cannot hold.
    (root / "src/trading_bot/vision/lane.py").write_text(
        "# changed\n", encoding="utf-8", newline="\n"
    )
    changed_runtime = build_block(root)
    assert "RUNTIME_DRIFT" in resume_reasons(first, changed_runtime)

    (root / "src/trading_bot/vision/lane.py").write_text(
        "# src/trading_bot/vision/lane.py\n", encoding="utf-8", newline="\n"
    )
    other_config = build_block(root, config={**CONFIG, "window_bars": 24})
    assert resume_reasons(first, other_config) == ["CONFIG_CHANGED"]

    other_environment = build_block(
        root, environment_block={**environment(), "python_version": "0.0.0"}
    )
    assert resume_reasons(first, other_environment) == ["ENVIRONMENT_DRIFT"]

    moved_commit = build_block(root, started_at_ms=1)
    other_code = dict(moved_commit)
    other_code["code"] = {**moved_commit["code"], "commit": "1" * 40}
    assert "COMMIT_CHANGED" in resume_reasons(first, other_code)


def test_a_resumed_block_carries_its_parent_chain(tmp_path: Path) -> None:
    root = build_repo(tmp_path / "repo")
    first = build_block(root)
    #: The parent is the block the session actually wrote. Injecting a top-level ``chain``
    #: here is what hid a defect: the chain is nested under ``resume``, so the reader must
    #: find it there, and a test that supplies it at the top level proves nothing.
    second = build_block(root, started_at_ms=1_700_000_900_000, resume_parent=first)

    assert second["resume"]["resumed"] is True
    assert second["resume"]["parent_session_id"] == first["session_id"]
    assert [item["session_id"] for item in second["resume"]["chain"]] == [first["session_id"]]
    assert second["run_id"] == first["run_id"]
    assert second["session_id"] != first["session_id"]
    assert resume_reasons(first, second) == []


def test_a_second_resume_keeps_the_origin_of_the_first_session(tmp_path: Path) -> None:
    """Resuming twice must not move the origin the lane replays from.

    ``origin`` is ``chain[0].started_at_ms``: the first session of the lineage, not the
    immediate parent. When the chain was read from the wrong key it held one entry, so the
    third session started replaying at the second session's start and the prefix comparison
    failed on decisions that had not changed. This test pins the shape that makes the
    replay stable across an arbitrary number of recoveries.
    """

    root = build_repo(tmp_path / "repo")
    first = build_block(root, started_at_ms=1_700_000_000_000)
    second = build_block(root, started_at_ms=1_700_000_900_000, resume_parent=first)
    third = build_block(root, started_at_ms=1_700_001_800_000, resume_parent=second)

    assert [item["session_id"] for item in second["resume"]["chain"]] == [first["session_id"]]
    assert [item["session_id"] for item in third["resume"]["chain"]] == [
        first["session_id"],
        second["session_id"],
    ]
    assert third["resume"]["chain"][0]["started_at_ms"] == 1_700_000_000_000
    assert second["resume"]["chain"][0]["started_at_ms"] == 1_700_000_000_000
    assert third["run_id"] == first["run_id"]
    assert third["session_id"] not in {first["session_id"], second["session_id"]}


def test_the_block_never_claims_a_verdict(tmp_path: Path) -> None:
    block = build_block(build_repo(tmp_path / "repo"))
    assert "complete" not in block
    assert "verdict" not in block
    assert "ok" not in block
