"""The inventory publisher may not be turned into an exfiltration or overwrite tool.

``exp004a_evidence_inventory.py`` is the builder-side half of the RFC-051 handoff: it exposes
hashes, sizes and timestamps so a separate verifier can recompute them. Because it is the half
that touches evidence paths, its two failure modes are the ones worth testing here — reading
outside the checkout, and writing the output into the evidence it is describing.

A directory junction is used rather than ``Path.symlink_to`` because a junction needs no
privilege on Windows and is resolved by ``Path.resolve`` exactly like a symlink. Each refusal is
paired with a positive control, so a passing test means "the boundary was reached", not "the
path happened to be missing".
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
if str(REPO / "scripts") not in sys.path:
    sys.path.insert(0, str(REPO / "scripts"))

import exp004a_evidence_inventory as inventory  # noqa: E402


def _link_directory(link: Path, target: Path) -> bool:
    """Create a directory link; ``False`` when the platform refuses, so the test can skip."""
    if sys.platform == "win32":
        import subprocess

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
    (root / "data" / "exp004a").mkdir(parents=True)
    (root / "data" / "exp004a" / "admission_1h.jsonl").write_text("{}\n", encoding="utf-8")
    (root / "docs" / "agentic" / "exp004a" / "handoff").mkdir(parents=True)
    return root


def test_a_linked_directory_cannot_smuggle_an_outside_file(repo: Path, tmp_path: Path) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.json").write_text('{"key": "not-yours"}\n', encoding="utf-8")
    link = repo / "data" / "exp004a" / "escape"
    if not _link_directory(link, outside):
        pytest.skip("this environment cannot create a directory link")

    # The link genuinely reaches the file: the refusal below is about the boundary.
    assert (link / "secret.json").is_file()
    with pytest.raises(inventory.InventoryError):
        inventory.resolve_declared(repo, "data/exp004a/escape/secret.json")


def test_an_honest_store_file_is_accepted(repo: Path) -> None:
    resolved = inventory.resolve_declared(repo, "data/exp004a/admission_1h.jsonl")
    assert resolved.is_file()


@pytest.mark.parametrize(
    "declared",
    [
        "../outside/secret.json",
        "data/../../outside/secret.json",
        "config/../data/exp004a/admission_1h.jsonl",
    ],
)
def test_traversal_out_of_the_checkout_is_refused(repo: Path, declared: str) -> None:
    with pytest.raises(inventory.InventoryError):
        inventory.resolve_declared(repo, declared)


def test_a_root_that_is_not_allowlisted_is_refused(repo: Path) -> None:
    (repo / "secrets").mkdir()
    (repo / "secrets" / "api.json").write_text('{"key": "value"}\n', encoding="utf-8")
    with pytest.raises(inventory.InventoryError):
        inventory.resolve_declared(repo, "secrets/api.json")


def test_the_absolute_path_outside_the_repository_is_refused(repo: Path, tmp_path: Path) -> None:
    absolute = (tmp_path / "elsewhere.json").resolve()
    absolute.write_text("{}\n", encoding="utf-8")
    with pytest.raises(inventory.InventoryError):
        inventory.resolve_declared(repo, str(absolute))


def test_a_missing_declared_reference_is_an_error_not_a_silent_skip(repo: Path) -> None:
    with pytest.raises(inventory.InventoryError):
        inventory.describe(repo, "docs/agentic/exp004a/handoff/absent.json")


@pytest.mark.parametrize(
    "target",
    [
        "data/exp004a/EVIDENCE_INVENTORY.json",
        "data/forward/edge03/1h/EVIDENCE_INVENTORY.json",
        "reports/ai-bots/EXP-004A-001/EVIDENCE_INVENTORY.json",
        "evidence/real_decisions/EVIDENCE_INVENTORY.json",
    ],
)
def test_the_inventory_cannot_be_written_into_evidence(repo: Path, target: str) -> None:
    with pytest.raises(inventory.InventoryError):
        inventory.check_output_target(repo, repo / target)


def test_an_honest_output_target_is_accepted(repo: Path) -> None:
    target = repo / "docs" / "agentic" / "exp004a" / "handoff" / "EVIDENCE_INVENTORY.json"
    assert inventory.check_output_target(repo, target) == target.resolve()
