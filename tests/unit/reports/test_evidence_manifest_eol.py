"""A manifest that digests working-tree bytes must survive a checkout.

``git checkout`` rewrites line endings according to ``core.autocrlf``.  The RFC's manifest
hashes the files on disk, so a checkout that turned LF into CRLF made 13 of its 44 digests
name bytes the verifier could not obtain: the gates passed in the tree that produced the
manifest and failed in a fresh clone of the same commit.  The fix is a ``-text`` pin per
covered path; this test fails if a new digest is added without one.

The check reads ``git check-attr``, not the files, so it is independent of the line
endings of the machine running it.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
MANIFEST = REPO / "reports/ai-bots/RFC-TAP-PAPER-ADMISSION-REPRO-001/evidence_manifest.json"


def text_attr(paths: list[str]) -> dict[str, str]:
    """``git check-attr text`` for every path, parsed from its NUL-separated form."""

    completed = subprocess.run(
        ["git", "check-attr", "-z", "text", "--", *paths],
        cwd=REPO,
        capture_output=True,
        check=True,
    )
    fields = completed.stdout.decode("utf-8").split("\0")
    return {fields[i]: fields[i + 2] for i in range(0, len(fields) - 2, 3)}


def digested_paths() -> list[str]:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    paths = [entry["path"] for entry in manifest.get("preserved", {}).values()]
    paths += [entry["path"] for entry in manifest.get("code_changes", [])]
    paths += list(manifest.get("evidence", {}))
    return sorted(set(paths))


def test_manifest_is_not_empty() -> None:
    # A green pass over zero paths would prove nothing.
    assert len(digested_paths()) >= 40


def test_every_digested_path_is_pinned_against_eol_rewriting() -> None:
    pinned = text_attr(digested_paths())
    unpinned = sorted(path for path, value in pinned.items() if value != "unset")
    assert not unpinned, (
        "these paths are digested by evidence_manifest.json but still subject to Git's "
        f"end-of-line conversion, so a fresh clone cannot reproduce their bytes: {unpinned}"
    )


def test_the_probe_can_see_an_unpinned_path() -> None:
    # Negative control: if `check-attr` quietly returned "unset" for everything, the
    # assertion above would pass without any pin existing.
    assert text_attr(["src/trading_bot/vision/lane.py"])["src/trading_bot/vision/lane.py"] != "unset"


@pytest.mark.parametrize("path", digested_paths())
def test_digested_path_is_tracked(path: str) -> None:
    # An ignored or untracked file would make the manifest unverifiable from a clone.
    completed = subprocess.run(
        ["git", "ls-files", "--error-unmatch", path],
        cwd=REPO,
        capture_output=True,
        check=False,
    )
    assert completed.returncode == 0, f"{path} is digested but Git does not track it"
