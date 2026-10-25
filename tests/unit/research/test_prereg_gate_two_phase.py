"""The two-phase freeze: protocol first, digests second, and no data in between.

The gap this closes was stated as a limitation by the previous mission: ``prereg_gate`` requires a
sha256 for every dataset, so a preregistration frozen *before* its data exists cannot pass — and
lowering the requirement for everybody is exactly how a holdout stops being a holdout.

Three properties are pinned:

* **phase 1 is never authorisable.** A protocol frozen before the capture exists can be inspected
  and must still exit non-zero on ``authorize``. If this test ever fails, a preregistration with no
  digests has become permission to run.
* **phase 2 cannot be reached early.** The digest commit must be *after* the capture closed and the
  protocol commit must be *before* the capture started, both read from git commit times rather than
  from anything a manifest asserts about itself.
* **data outside the declared window is refused.** A dataset that predates the capture is not a
  prospective observation, and one that ends after the close was read after the answer existed.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

import test_prereg_gate as base

from trading_bot.research import prereg_gate as gate

EXPERIMENT = "EXP-900A"


def _commit_at(repo: Path, when: str, message: str) -> str:
    """Commit the working tree with an explicit author/committer date."""
    base._git(repo, "add", "-A")
    env = {
        **os.environ,
        "GIT_AUTHOR_DATE": when,
        "GIT_COMMITTER_DATE": when,
        "GIT_AUTHOR_NAME": "fixture",
        "GIT_AUTHOR_EMAIL": "fixture@example.invalid",
        "GIT_COMMITTER_NAME": "fixture",
        "GIT_COMMITTER_EMAIL": "fixture@example.invalid",
    }
    subprocess.run(
        ["git", "-C", str(repo), "commit", "-q", "-m", message],
        check=True,
        capture_output=True,
        env=env,
        timeout=120,
    )
    return subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
        timeout=60,
    ).stdout.strip()


class Phase:
    """A fixture repository with a two-phase block, and a commit clock under test control."""

    def __init__(self, repo: base.Fixture) -> None:
        self.fx = repo

    @property
    def manifest(self) -> dict[str, Any]:
        return self.fx.manifest

    @property
    def registry(self) -> dict[str, Any]:
        return self.fx.registry

    def phase_one(self, *, start: str = "2026-12-01T00:00:00Z", end: str = "2027-03-01T00:00:00Z") -> None:
        self.manifest["status"] = "PROTOCOL_FROZEN"
        self.manifest["two_phase"] = {
            "phase": 1,
            "digests_deferred": True,
            "capture": {
                "start_utc": start,
                "end_utc": end,
                "target_days": 90,
                "closed": False,
            },
        }
        entry = self.fx.registry["entries"][0]
        # A dataset that has not been captured yet: no file, no digest, and an explicit deferral.
        entry["raw_file"] = "data/fixture/NOT_CAPTURED.jsonl.gz"
        entry["normalized_file"] = "data/fixture/NOT_CAPTURED.jsonl.gz"
        entry["raw_sha256"] = None
        entry["normalized_sha256"] = None
        entry["digest_deferred_by"] = "TWO_PHASE_PHASE_1"
        entry["period_start_utc"] = "2026-12-01T00:00:00Z"
        entry["period_end_utc"] = "2027-02-28T23:00:00Z"

    def phase_two(self, *, phase_one_commit: str) -> None:
        self.manifest["status"] = "REGISTRY_FROZEN"
        self.manifest["two_phase"]["phase"] = 2
        self.manifest["two_phase"]["phase1_commit"] = phase_one_commit
        self.manifest["two_phase"]["capture"]["closed"] = True
        entry = self.fx.registry["entries"][0]
        dataset = "data/fixture/NOASSET.1m.jsonl.gz"
        digest = base._sha(self.fx.root / dataset)
        entry["raw_file"] = dataset
        entry["normalized_file"] = dataset
        entry["raw_sha256"] = digest
        entry["normalized_sha256"] = digest
        entry.pop("digest_deferred_by", None)

    def freeze_at(self, when: str, message: str) -> str:
        """Write the manifest and commit it with an explicit timestamp."""
        self.fx.write()
        return _commit_at(self.fx.root, when, message)

    def evaluate(self, **kwargs: Any) -> dict[str, Any]:
        return self.fx.evaluate(**kwargs)


@pytest.fixture
def phase(tmp_path: Path) -> Phase:
    return Phase(base.Fixture(tmp_path / "repo"))


# --------------------------------------------------------------------------- #
# phase 1
# --------------------------------------------------------------------------- #
def test_phase_one_can_be_inspected_but_never_authorised(phase: Phase) -> None:
    phase.phase_one()
    phase.freeze_at("2026-10-21T10:00:00Z", "fixture: protocol frozen before capture")

    inspected = phase.evaluate(mode="inspect")
    assert inspected["decision"] == gate.INSPECTION_ONLY
    assert inspected["exit_code"] == 3
    assert any(
        check.endswith("DIGEST_DEFERRED_TO_PHASE_2") for check in inspected["checks"]
    )
    assert "PROTOCOL_FROZEN_BEFORE_CAPTURE_START" in inspected["checks"]

    authorised = phase.evaluate(mode="authorize")
    assert authorised["decision"] == gate.BLOCKED
    assert authorised["exit_code"] == 2
    assert "TWO_PHASE_PHASE_1_IS_NOT_AUTHORISABLE" in authorised["errors"]


def test_phase_one_that_starts_after_the_data_arrived_is_refused(phase: Phase) -> None:
    """A protocol written after the capture began cannot claim to have predicted it."""
    phase.phase_one(start="2020-01-01T00:00:00Z", end="2026-12-31T00:00:00Z")
    phase.freeze_at("2026-10-21T10:00:00Z", "fixture: too late")
    result = phase.evaluate(mode="inspect")
    assert "PROTOCOL_FROZEN_AFTER_CAPTURE_STARTED" in result["errors"]


def test_phase_one_refuses_a_dataset_that_already_exists(phase: Phase) -> None:
    phase.phase_one()
    entry = phase.fx.registry["entries"][0]
    entry["raw_file"] = "data/fixture/NOASSET.1m.jsonl.gz"
    entry["normalized_file"] = "data/fixture/NOASSET.1m.jsonl.gz"
    phase.fx.freeze("fixture: data present in phase 1")
    result = phase.evaluate(mode="inspect")
    assert any(
        error.startswith("DATASET_PRESENT_BEFORE_FREEZE") for error in result["errors"]
    )


def test_deferral_without_the_flag_is_not_tolerated(phase: Phase) -> None:
    phase.phase_one()
    phase.manifest["two_phase"]["digests_deferred"] = False
    phase.fx.freeze("fixture: silent deferral")
    result = phase.evaluate(mode="inspect")
    assert any("SHA256_MISSING_OR_INVALID" in error for error in result["errors"])


def test_deferral_is_refused_in_phase_two(phase: Phase) -> None:
    phase.phase_one()
    commit = phase.freeze_at("2026-10-21T10:00:00Z", "fixture: phase one")
    phase.phase_two(phase_one_commit=commit)
    phase.manifest["two_phase"]["phase"] = 2
    phase.manifest["two_phase"]["digests_deferred"] = True
    phase.registry["entries"][0]["raw_sha256"] = None
    phase.fx.freeze("fixture: phase two without digests")
    result = phase.evaluate(mode="authorize")
    assert any(
        error.startswith("TWO_PHASE_PHASE_2_REQUIRES_DIGESTS") for error in result["errors"]
    )


# --------------------------------------------------------------------------- #
# phase 2
# --------------------------------------------------------------------------- #
def test_a_correctly_ordered_phase_two_is_authorisable(phase: Phase) -> None:
    phase.phase_one(start="2026-10-22T00:00:00Z", end="2026-10-31T00:00:00Z")
    commit = phase.freeze_at("2026-10-21T12:00:00Z", "fixture: protocol frozen")
    phase.phase_two(phase_one_commit=commit)
    phase.registry["entries"][0]["period_start_utc"] = "2026-10-22T00:00:00Z"
    phase.registry["entries"][0]["period_end_utc"] = "2026-10-31T00:00:00Z"
    phase.freeze_at("2026-11-01T00:00:00Z", "fixture: digests frozen after close")

    result = phase.evaluate(mode="authorize")
    assert result["errors"] == []
    assert result["decision"] == gate.AUTHORIZED
    assert result["exit_code"] == 0
    assert "PROTOCOL_FROZEN_BEFORE_CAPTURE_START" in result["checks"]
    assert "DIGESTS_FROZEN_AFTER_CAPTURE_CLOSED" in result["checks"]


def test_digests_frozen_before_the_capture_closed_are_refused(phase: Phase) -> None:
    phase.phase_one(start="2026-10-22T00:00:00Z", end="2026-10-31T00:00:00Z")
    commit = phase.freeze_at("2026-10-21T12:00:00Z", "fixture: protocol frozen")
    phase.phase_two(phase_one_commit=commit)
    phase.registry["entries"][0]["period_start_utc"] = "2026-10-22T00:00:00Z"
    phase.registry["entries"][0]["period_end_utc"] = "2026-10-31T00:00:00Z"
    phase.freeze_at("2026-10-25T00:00:00Z", "fixture: digests frozen too early")

    result = phase.evaluate(mode="authorize")
    assert "DIGESTS_FROZEN_BEFORE_CAPTURE_CLOSED" in result["errors"]
    assert result["decision"] == gate.BLOCKED


def test_a_dataset_that_predates_the_capture_is_refused(phase: Phase) -> None:
    phase.phase_one(start="2026-10-22T00:00:00Z", end="2026-10-31T00:00:00Z")
    commit = phase.freeze_at("2026-10-21T12:00:00Z", "fixture: protocol frozen")
    phase.phase_two(phase_one_commit=commit)
    phase.registry["entries"][0]["period_start_utc"] = "2026-01-01T00:00:00Z"
    phase.registry["entries"][0]["period_end_utc"] = "2026-10-31T00:00:00Z"
    phase.freeze_at("2026-11-01T00:00:00Z", "fixture: digests frozen")

    result = phase.evaluate(mode="authorize")
    assert any(error.endswith("_PREDATES_CAPTURE") for error in result["errors"])


def test_a_dataset_that_ends_after_the_close_is_refused(phase: Phase) -> None:
    phase.phase_one(start="2026-10-22T00:00:00Z", end="2026-10-31T00:00:00Z")
    commit = phase.freeze_at("2026-10-21T12:00:00Z", "fixture: protocol frozen")
    phase.phase_two(phase_one_commit=commit)
    phase.registry["entries"][0]["period_start_utc"] = "2026-10-22T00:00:00Z"
    phase.registry["entries"][0]["period_end_utc"] = "2026-11-30T00:00:00Z"
    phase.freeze_at("2026-12-01T00:00:00Z", "fixture: digests frozen")

    result = phase.evaluate(mode="authorize")
    assert any(error.endswith("_AFTER_CAPTURE_CLOSE") for error in result["errors"])


def test_a_phase_one_commit_that_does_not_exist_is_refused(phase: Phase) -> None:
    phase.phase_one(start="2026-10-22T00:00:00Z", end="2026-10-31T00:00:00Z")
    phase.freeze_at("2026-10-21T12:00:00Z", "fixture: protocol frozen")
    phase.phase_two(phase_one_commit="f" * 40)
    phase.registry["entries"][0]["period_start_utc"] = "2026-10-22T00:00:00Z"
    phase.registry["entries"][0]["period_end_utc"] = "2026-10-31T00:00:00Z"
    phase.freeze_at("2026-11-01T00:00:00Z", "fixture: digests frozen")
    result = phase.evaluate(mode="authorize")
    assert "TWO_PHASE_PHASE_1_COMMIT_NOT_ANCESTOR" in result["errors"]


def test_an_unclosed_capture_is_refused(phase: Phase) -> None:
    phase.phase_one(start="2026-10-22T00:00:00Z", end="2026-10-31T00:00:00Z")
    commit = phase.freeze_at("2026-10-21T12:00:00Z", "fixture: protocol frozen")
    phase.phase_two(phase_one_commit=commit)
    phase.manifest["two_phase"]["capture"]["closed"] = False
    phase.registry["entries"][0]["period_start_utc"] = "2026-10-22T00:00:00Z"
    phase.registry["entries"][0]["period_end_utc"] = "2026-10-31T00:00:00Z"
    phase.freeze_at("2026-11-01T00:00:00Z", "fixture: digests frozen")
    result = phase.evaluate(mode="authorize")
    assert "TWO_PHASE_CAPTURE_NOT_CLOSED" in result["errors"]


def test_a_status_that_disagrees_with_its_phase_is_refused(phase: Phase) -> None:
    phase.phase_one()
    phase.manifest["status"] = "REGISTRY_FROZEN"
    phase.fx.freeze("fixture: phase and status disagree")
    result = phase.evaluate(mode="inspect")
    assert "TWO_PHASE_STATUS_PHASE_MISMATCH" in result["errors"]


def test_an_invalid_capture_window_is_refused(phase: Phase) -> None:
    phase.phase_one(start="2027-03-01T00:00:00Z", end="2026-12-01T00:00:00Z")
    phase.fx.freeze("fixture: empty window")
    result = phase.evaluate(mode="inspect")
    assert "TWO_PHASE_CAPTURE_WINDOW_INVALID" in result["errors"]


def test_capture_timestamps_must_be_utc(phase: Phase) -> None:
    phase.phase_one(start="2026-12-01T00:00:00+02:00")
    phase.fx.freeze("fixture: offset timestamp")
    result = phase.evaluate(mode="inspect")
    assert "TWO_PHASE_CAPTURE_WINDOW_INVALID" in result["errors"]
