"""A declared path may not leave the checkout — proven with a real link, not a simulated one.

The previous mission left this branch of ``safely_under_repo`` **unverified** because
``Path.symlink_to`` needs a privilege this Windows host does not grant. A directory *junction*
(``mklink /J``) is a reparse point that can be created without elevation and is resolved by
``Path.resolve`` exactly like a symlink, so the escape can be tested here for real.

Two assertions, in this order, because the second is what stops the first from being vacuous:

1. a path that traverses a link out of the repository returns ``None``;
2. a path that stays inside returns the file — the check still accepts honest input.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from trading_bot.research import prereg_gate as gate


def _link_directory(link: Path, target: Path) -> bool:
    """Create a directory link; ``False`` when the platform refuses, so the test can skip."""
    if sys.platform == "win32":
        completed = subprocess.run(
            ["cmd", "/c", "mklink", "/J", str(link), str(target)],
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
        return completed.returncode == 0 and link.exists()
    try:
        link.symlink_to(target, target_is_directory=True)
    except (OSError, NotImplementedError):  # pragma: no cover - exotic POSIX
        return False
    return True


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    (root / "config").mkdir(parents=True)
    (root / "config" / "inside.json").write_text('{"ok": true}\n', encoding="utf-8")
    return root


def test_a_linked_directory_cannot_smuggle_a_file_into_the_checkout(
    repo: Path, tmp_path: Path
) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.json").write_text('{"experiment_id": "EXP-STOLEN"}\n', encoding="utf-8")
    link = repo / "config" / "escape"
    if not _link_directory(link, outside):
        pytest.skip("this environment cannot create a directory link")

    # The link really does reach the file, so the refusal below is about the boundary and not
    # about a missing target.
    assert (link / "secret.json").is_file()
    assert gate.safely_under_repo(repo, "config/escape/secret.json") is None


def test_the_same_check_still_accepts_a_file_inside(repo: Path) -> None:
    inside = gate.safely_under_repo(repo, "config/inside.json")
    assert inside is not None
    assert inside.is_file()


def test_parent_traversal_is_refused(repo: Path) -> None:
    assert gate.safely_under_repo(repo, "../outside/secret.json") is None
    assert gate.safely_under_repo(repo, "config/../../outside/secret.json") is None


def test_an_absolute_path_is_refused(repo: Path) -> None:
    absolute = (repo / "config" / "inside.json").resolve()
    assert gate.safely_under_repo(repo, str(absolute)) is None
