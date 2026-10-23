"""Guard: a mandatory audit contract cannot go missing, ignored or untracked.

The failure this file exists for is not hypothetical. The multi-agent audit
backlog lived in ``reports/multiagent-audit/17_ATOMIC_BACKLOG.yaml``, which
``.gitignore:55`` excludes (``reports/*``). It was never committed, so when the
worktree was reset the whole corpus — including MT-0004's acceptance criteria —
was gone, and the task had to be blocked with ``BLOCKED_SPEC``.

Contracts are now versioned under ``docs/audit/``. This guard makes that
structural rather than customary: it fails when a contract declared in the
backlog is missing, empty, gitignored or untracked, and when the backlog itself
stops parsing or loses a required key.

Fail-closed by design: if git is unavailable or the tests run outside a work
tree, the check cannot prove the property and fails with a clear message
instead of skipping. A guard that silently disables itself is the same class of
false success as a stub that returns 0.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
AUDIT_DIR = REPO_ROOT / "docs" / "audit"
BACKLOG = AUDIT_DIR / "AUDIT_BACKLOG.yaml"

REQUIRED_SECTIONS = {"schema", "generated_at_utc", "tasks", "contracts"}
REQUIRED_TASK_KEYS = {"id", "status", "provenance"}
KNOWN_STATUSES = {
    "todo",
    "ready",
    "in_progress",
    "in_review",
    "done",
    "blocked",
    "spec_reissue_required",
}
KNOWN_PROVENANCE = {"recovered", "reissued", "lost"}


def _git(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(REPO_ROOT), *args],
        capture_output=True,
        text=True,
        timeout=180,
    )


def _require_git_worktree() -> None:
    completed = _git("rev-parse", "--is-inside-work-tree")
    if completed.returncode != 0 or completed.stdout.strip() != "true":
        pytest.fail(
            "this guard needs a git work tree to prove a contract is tracked; "
            f"git said: {completed.stderr.strip() or completed.stdout.strip()!r}"
        )


def _relative(path: Path) -> str:
    return path.resolve().relative_to(REPO_ROOT.resolve()).as_posix()


@pytest.fixture(scope="module")
def backlog() -> dict[str, Any]:
    assert BACKLOG.exists(), f"the audit backlog is missing: {BACKLOG}"
    payload = yaml.safe_load(BACKLOG.read_text(encoding="utf-8"))
    assert isinstance(payload, dict), "the audit backlog must be a YAML mapping"
    return payload


# --- the backlog itself ------------------------------------------------------


def test_the_backlog_declares_the_required_sections(backlog: dict[str, Any]) -> None:
    missing = REQUIRED_SECTIONS - set(backlog)
    assert missing == set(), f"the backlog lost required sections: {sorted(missing)}"
    assert backlog["tasks"], "a backlog with no tasks cannot declare anything"


def test_every_task_is_well_formed(backlog: dict[str, Any]) -> None:
    ids: list[str] = []
    for task in backlog["tasks"]:
        assert isinstance(task, dict), f"task entry is not a mapping: {task!r}"
        missing = REQUIRED_TASK_KEYS - set(task)
        assert missing == set(), f"task {task.get('id')!r} lost {sorted(missing)}"
        assert task["status"] in KNOWN_STATUSES, f"unknown status {task['status']!r}"
        assert task["provenance"] in KNOWN_PROVENANCE, (
            f"task {task['id']!r} claims an unknown provenance {task['provenance']!r}"
        )
        ids.append(task["id"])
    assert len(ids) == len(set(ids)), f"duplicate task ids: {ids}"


def test_the_reissue_of_mt_0004_is_recorded_honestly(backlog: dict[str, Any]) -> None:
    """The loss and the reissue must stay distinguishable in the record."""
    by_id = {task["id"]: task for task in backlog["tasks"]}
    assert "MT-0004" in by_id and "MT-0004-R1" in by_id
    original = by_id["MT-0004"]
    assert original["status"] == "spec_reissue_required"
    assert original["provenance"] == "lost"
    assert original["superseded_by"] == "MT-0004-R1"
    reissue = by_id["MT-0004-R1"]
    assert reissue["provenance"] == "reissued"
    assert Path(REPO_ROOT / reissue["contract"]).is_file()


# --- the contracts -----------------------------------------------------------


def _required_contracts(backlog: dict[str, Any]) -> list[str]:
    paths: list[str] = []
    for entry in backlog["contracts"]:
        assert isinstance(entry, dict) and "path" in entry, f"malformed contract entry: {entry!r}"
        if entry.get("required", True):
            paths.append(entry["path"])
    assert paths, "the backlog declares no required contract"
    return paths


def test_every_required_contract_exists_and_has_content(backlog: dict[str, Any]) -> None:
    for rel in _required_contracts(backlog):
        path = REPO_ROOT / rel
        assert path.is_file(), f"declared contract does not exist: {rel}"
        assert path.stat().st_size > 200, f"declared contract is suspiciously empty: {rel}"


def test_no_contract_is_gitignored(backlog: dict[str, Any]) -> None:
    """``check-ignore`` exits 1 when the path is NOT ignored. 0 means ignored."""
    _require_git_worktree()
    for rel in _required_contracts(backlog):
        completed = _git("check-ignore", "--quiet", "--", rel)
        assert completed.returncode == 1, (
            f"{rel} is gitignored ({completed.returncode}); a contract git will not "
            "store is a contract the next reset destroys"
        )


def test_every_contract_is_tracked_by_git(backlog: dict[str, Any]) -> None:
    _require_git_worktree()
    for rel in _required_contracts(backlog):
        completed = _git("ls-files", "--error-unmatch", "--", rel)
        assert completed.returncode == 0, (
            f"{rel} exists but is not tracked by git; commit it "
            f"(git said: {completed.stderr.strip()!r})"
        )


def test_contracts_do_not_live_in_the_ignored_report_directory(backlog: dict[str, Any]) -> None:
    """``reports/*`` is for generated evidence, never for authority."""
    for rel in _required_contracts(backlog):
        assert not rel.startswith("reports/"), (
            f"{rel} is an authority document stored under the ignored reports/ tree"
        )


def test_the_contracts_are_inside_the_repository(backlog: dict[str, Any]) -> None:
    for rel in _required_contracts(backlog):
        resolved = (REPO_ROOT / rel).resolve()
        assert resolved.is_relative_to(REPO_ROOT.resolve())
        assert _relative(resolved) == rel
