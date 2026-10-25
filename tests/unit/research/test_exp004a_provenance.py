"""The successor declaration is refused unless it identifies code, bytes and an ordering.

Every test here is about a way of *looking* authorised: a plausible declaration that cites a commit
that does not contain the generator, a generator edited after the declaration, a declaration written
into the window it governs, a timestamp on a document that no repository vouches for. Each one must
end in a named defect, because the alternative is a capture that is technically perfect and
provenance-free.

The fixtures are a throwaway Git repository, not this checkout: a positive case has to build a commit,
and a test may not commit to the repository it is testing.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

import pytest

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "src"))

from trading_bot.research.prospective import provenance  # noqa: E402
from trading_bot.research.prospective.provenance import (  # noqa: E402
    DeclarationError,
    authorize,
    eligibility_defects,
    load,
    validate,
)

START = "2026-10-22T00:00:00Z"
END = "2026-10-23T00:00:00Z"
EFFECTIVE = "2026-10-21T12:00:00Z"
ISSUED = "2026-10-21T10:00:00Z"
GENERATOR = "scripts/exp004a_capture.py"
ORIGINAL = "config/preregistrations/EXP-004A.datasets.json"
SUCCESSOR = "config/preregistrations/EXP-004A.datasets.phase2.json"

_URL = "https://api.binance.com/api/v3/klines"


def _git(repo: Path, *args: str, date: str | None = None) -> str:
    env = os.environ.copy()
    env.pop("GIT_DIR", None)
    if date is not None:
        env["GIT_AUTHOR_DATE"] = date
        env["GIT_COMMITTER_DATE"] = date
    completed = subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
        check=True,
        env=env,
        timeout=120,
    )
    return completed.stdout.strip()


def _entry(dataset_id: str, asset: str, interval: str, commit: str) -> dict[str, Any]:
    return {
        "dataset_id": dataset_id,
        "asset": asset,
        "venue": "Binance",
        "instrument_type": "spot",
        "timeframe": interval,
        "provider": "Binance public REST",
        "source_url": _URL,
        "period_start_utc": START,
        "period_end_utc": END,
        "raw_file": f"data/exp004a/{dataset_id}.raw.jsonl",
        "raw_sha256": None,
        "normalized_file": f"data/exp004a/{dataset_id}.jsonl",
        "normalized_sha256": None,
        "generator_command": f"python scripts/exp004a_capture.py --slice {interval}:{asset}",
        "generator_parameters": {"interval": interval, "lag_bound_ms": 7_200_000},
        "generator_code_commit": commit,
        "row_count": 24,
        "reproduction_status": "PENDING_CAPTURE",
        "digest_deferred_by": "TWO_PHASE_PHASE_1",
    }


def _original(commit: str = "0" * 40) -> dict[str, Any]:
    return {
        "experiment_id": "EXP-004A",
        "schema_version": "2.0",
        "phase": 1,
        "entries": [
            _entry("EXP-004A-1H-BTC", "BTC", "1h", commit),
            _entry("EXP-004A-ST6-TAPE", "BTC", "4h slot, 3 rounds of 15s", commit),
        ],
    }


def _successor(commit: str, *, sha: str, blob: str, generator_sha: str) -> dict[str, Any]:
    document = _original(commit)
    return {
        "declaration_id": "EXP-004A.datasets.phase2/v1",
        "experiment_id": "EXP-004A",
        "phase": 2,
        "schema_version": "3.0",
        "supersedes": {
            "path": ORIGINAL,
            "sha256": sha,
            "git_blob": blob,
            "declared_generator_code_commit": "0" * 40,
            "reason": "phase 1 deferred the generator commit to a phase-2 document",
        },
        "generator": {
            "path": GENERATOR,
            "commit": commit,
            "blob_sha256": generator_sha,
            "contract": "trading_bot.research.prospective.store.index_series",
        },
        "capture_window": {"start_utc": START, "end_utc": END},
        "effective_from_utc": EFFECTIVE,
        "issued_at_utc": ISSUED,
        "governance_status": "AUTHORIZED_FOR_CAPTURE",
        "entries": document["entries"],
    }


class Scaffold:
    """A committed original declaration, a committed generator, and room to write a successor."""

    def __init__(self, repo: Path) -> None:
        self.repo = repo
        self.declaration = repo / SUCCESSOR
        self.generator = repo / GENERATOR
        self.original = repo / ORIGINAL
        #: the commit the last document() call declared as the generator's home
        self.declared_commit = ""

    @property
    def original_sha256(self) -> str:
        return provenance.sha256_file(self.original)

    @property
    def original_blob(self) -> str:
        return provenance._git_blob_id(self.original.read_bytes())

    def generator_commit(self) -> str:
        return _git(self.repo, "rev-parse", "HEAD")

    def write(self, document: dict[str, Any], *, commit: bool = True, date: str | None = None) -> None:
        self.declaration.parent.mkdir(parents=True, exist_ok=True)
        self.declaration.write_text(
            json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        if commit:
            _git(self.repo, "add", "-A")
            _git(self.repo, "commit", "-m", "successor declaration", date=date)

    def rewrite_generator(self, text: str = "# edited after the declaration\n") -> None:
        self.generator.write_text(text, encoding="utf-8")

    def document(self, **overrides: Any) -> dict[str, Any]:
        self.declared_commit = self.generator_commit()
        document = _successor(
            self.declared_commit,
            sha=self.original_sha256,
            blob=self.original_blob,
            generator_sha=provenance.sha256_file(self.generator),
        )
        for key, value in overrides.items():
            if key == "generator" and isinstance(value, dict):
                document["generator"].update(value)
            elif key == "entry" and isinstance(value, dict):
                dataset_id, field, replacement = value["dataset_id"], value["field"], value["value"]
                for entry in document["entries"]:
                    if entry["dataset_id"] == dataset_id:
                        entry[field] = replacement
            elif key == "entry_commit":
                for entry in document["entries"]:
                    entry["generator_code_commit"] = value
            else:
                document[key] = value
        return document


@pytest.fixture()
def scaffold(tmp_path: Path) -> Scaffold:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "builder@example.invalid")
    _git(repo, "config", "user.name", "builder")
    _git(repo, "config", "core.autocrlf", "false")
    generator = repo / GENERATOR
    generator.parent.mkdir(parents=True, exist_ok=True)
    generator.write_text(
        '"""declared generator"""\n\n\ndef main() -> int:\n    return 0\n', encoding="utf-8"
    )
    original = repo / ORIGINAL
    original.parent.mkdir(parents=True, exist_ok=True)
    original.write_text(json.dumps(_original(), indent=2) + "\n", encoding="utf-8")
    (repo / ".gitignore").write_text("", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", "phase 1", date="2026-10-20T09:00:00 +0000")
    return Scaffold(repo)


def _codes(defects: list[provenance.Defect]) -> set[str]:
    return {defect.code for defect in defects}


# --------------------------------------------------------------------------- #
# positive control
# --------------------------------------------------------------------------- #
def test_a_committed_successor_naming_its_generator_commit_is_accepted(scaffold: Scaffold) -> None:
    scaffold.write(scaffold.document())
    declaration = load(scaffold.declaration)
    assert validate(declaration, repo=scaffold.repo) == []

    record = authorize(scaffold.declaration, repo=scaffold.repo)
    assert record.generator_commit == scaffold.declared_commit
    assert len(record.generator_commit) == 40
    assert record.declaration_commit is not None
    assert record.declaration_sha256 == provenance.sha256_file(scaffold.declaration)
    assert record.external_timestamp == "UNAVAILABLE"


def test_the_record_says_what_its_clock_is_worth(scaffold: Scaffold) -> None:
    """No external timestamp is available here, and the record must not imply one."""
    scaffold.write(scaffold.document())
    record = authorize(scaffold.declaration, repo=scaffold.repo).as_dict()
    assert record["temporal"]["basis"] == "GIT_ANCESTRY_PLUS_INGEST_CLOCK"
    assert record["temporal"]["external_timestamp"] == "UNAVAILABLE"
    assert record["generator"]["commit"] == scaffold.declared_commit


# --------------------------------------------------------------------------- #
# ACC-01 - the original is not rewritten
# --------------------------------------------------------------------------- #
def test_a_successor_that_cites_the_wrong_original_digest_is_refused(scaffold: Scaffold) -> None:
    document = scaffold.document()
    document["supersedes"]["sha256"] = "1" * 64
    scaffold.write(document)
    defects = validate(load(scaffold.declaration), repo=scaffold.repo)
    assert "ORIGINAL_DECLARATION_SHA256_MISMATCH" in _codes(defects)


def test_the_original_is_never_opened_for_writing(scaffold: Scaffold) -> None:
    before = scaffold.original.read_bytes()
    scaffold.write(scaffold.document())
    authorize(scaffold.declaration, repo=scaffold.repo)
    assert scaffold.original.read_bytes() == before
    assert _git(scaffold.repo, "status", "--porcelain", "--", ORIGINAL) == ""


# --------------------------------------------------------------------------- #
# ACC-03/ACC-04 - the code that ran
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("commit", ["daa7bde", "0000000000000000000000000000000000000000"])
def test_an_abbreviated_or_zero_commit_is_not_an_identifier(scaffold: Scaffold, commit: str) -> None:
    document = scaffold.document(generator={"commit": commit})
    scaffold.write(document, commit=False)
    codes = _codes(validate(load(scaffold.declaration), repo=scaffold.repo))
    assert codes & {"GENERATOR_COMMIT_NOT_FULL_SHA", "GENERATOR_COMMIT_ZERO"}


def test_a_commit_that_does_not_exist_in_the_repository_is_refused(scaffold: Scaffold) -> None:
    scaffold.write(scaffold.document(generator={"commit": "f" * 40}), commit=False)
    defects = validate(load(scaffold.declaration), repo=scaffold.repo)
    assert "GENERATOR_COMMIT_UNKNOWN" in _codes(defects)


def test_a_generator_edited_after_the_declaration_is_refused(scaffold: Scaffold) -> None:
    """The declared commit is real; the file on disk is not the file that commit holds."""
    scaffold.write(scaffold.document())
    scaffold.rewrite_generator()
    codes = _codes(validate(load(scaffold.declaration), repo=scaffold.repo))
    assert "GENERATOR_FILE_DIFFERS_FROM_DECLARED" in codes
    assert "GENERATOR_WORKTREE_DIRTY" in codes


def test_a_commit_that_holds_different_generator_bytes_is_refused(scaffold: Scaffold) -> None:
    scaffold.write(scaffold.document())
    document = json.loads(scaffold.declaration.read_text(encoding="utf-8"))
    document["generator"]["blob_sha256"] = "2" * 64
    scaffold.declaration.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")
    codes = _codes(validate(load(scaffold.declaration), repo=scaffold.repo))
    assert "GENERATOR_BLOB_MISMATCH" in codes


# --------------------------------------------------------------------------- #
# ACC-05/ACC-06 - the ordering
# --------------------------------------------------------------------------- #
def test_a_declaration_effective_after_the_window_opens_cannot_authorise_it(
    scaffold: Scaffold,
) -> None:
    scaffold.write(scaffold.document(effective_from_utc="2026-10-22T06:00:00Z"))
    codes = _codes(validate(load(scaffold.declaration), repo=scaffold.repo))
    assert "TEMPORAL_EFFECTIVE_AFTER_WINDOW_START" in codes


def test_issue_date_may_not_follow_the_effective_date(scaffold: Scaffold) -> None:
    scaffold.write(scaffold.document(issued_at_utc="2026-10-21T13:00:00Z"))
    defects = validate(load(scaffold.declaration), repo=scaffold.repo)
    assert "TEMPORAL_ISSUED_AFTER_EFFECTIVE" in _codes(defects)


def test_a_declaration_committed_inside_the_window_is_refused(scaffold: Scaffold) -> None:
    """A document that looks prospective and was written after the window opened is not one."""
    scaffold.write(scaffold.document(), date="2026-10-22T01:00:00 +0000")
    codes = _codes(validate(load(scaffold.declaration), repo=scaffold.repo))
    assert "DECLARATION_COMMITTED_AFTER_WINDOW_START" in codes


def test_an_uncommitted_declaration_has_no_temporal_authority(scaffold: Scaffold) -> None:
    scaffold.write(scaffold.document(), commit=False)
    codes = _codes(validate(load(scaffold.declaration), repo=scaffold.repo))
    assert "DECLARATION_NOT_COMMITTED" in codes


def test_an_edited_but_committed_declaration_is_reported_as_dirty(scaffold: Scaffold) -> None:
    scaffold.write(scaffold.document())
    document = json.loads(scaffold.declaration.read_text(encoding="utf-8"))
    document["issued_at_utc"] = "2026-10-21T11:00:00Z"
    scaffold.declaration.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")
    codes = _codes(validate(load(scaffold.declaration), repo=scaffold.repo))
    assert "DECLARATION_WORKTREE_DIRTY" in codes


# --------------------------------------------------------------------------- #
# nothing but the commit may move
# --------------------------------------------------------------------------- #
def test_entry_drift_is_named_field_by_field(scaffold: Scaffold) -> None:
    scaffold.write(
        scaffold.document(
            entry={"dataset_id": "EXP-004A-1H-BTC", "field": "row_count", "value": 2160}
        )
    )
    defects = validate(load(scaffold.declaration), repo=scaffold.repo)
    assert "ENTRY_DRIFT" in _codes(defects)
    assert any("row_count" in defect.detail for defect in defects)


def test_an_entry_naming_a_different_commit_than_the_declaration_is_refused(
    scaffold: Scaffold,
) -> None:
    scaffold.write(scaffold.document(entry_commit="0" * 40))
    codes = _codes(validate(load(scaffold.declaration), repo=scaffold.repo))
    assert "ENTRY_GENERATOR_COMMIT_MISMATCH" in codes


def test_a_successor_may_not_invent_the_tape_slice_contract(scaffold: Scaffold) -> None:
    scaffold.write(
        scaffold.document(
            entry={"dataset_id": "EXP-004A-ST6-TAPE", "field": "slice_contract", "value": "rounds"}
        )
    )
    codes = _codes(validate(load(scaffold.declaration), repo=scaffold.repo))
    assert "ENTRY_INVENTS_SLICE_CONTRACT" in codes


# --------------------------------------------------------------------------- #
# eligibility is decided by the bar's own ingest clock
# --------------------------------------------------------------------------- #
def _ms(iso: str) -> int:
    return int(datetime.fromisoformat(iso.replace("Z", "+00:00")).timestamp() * 1000)


def _record(scaffold: Scaffold) -> provenance.ProvenanceRecord:
    scaffold.write(scaffold.document())
    return authorize(scaffold.declaration, repo=scaffold.repo)


def test_bars_fetched_after_effect_are_eligible(scaffold: Scaffold) -> None:
    record = _record(scaffold)
    bars = [(_ms("2026-10-22T00:00:00Z"), _ms("2026-10-22T01:01:00Z"))]
    assert eligibility_defects(record, bars) == []


def test_a_bar_fetched_before_the_declaration_existed_is_not_eligible(scaffold: Scaffold) -> None:
    record = _record(scaffold)
    bars = [
        (_ms("2026-10-22T00:00:00Z"), _ms("2026-10-21T09:00:00Z")),
        (_ms("2026-10-22T01:00:00Z"), _ms("2026-10-22T02:01:00Z")),
    ]
    defects = eligibility_defects(record, bars)
    assert _codes(defects) == {"CAPTURE_BEFORE_EFFECTIVE"}
    assert "earliest fetch" in defects[0].detail


def test_a_bar_outside_the_declared_window_is_not_eligible(scaffold: Scaffold) -> None:
    record = _record(scaffold)
    bars = [(_ms("2026-10-25T00:00:00Z"), _ms("2026-10-25T01:01:00Z"))]
    assert _codes(eligibility_defects(record, bars)) == {"CAPTURE_OUTSIDE_DECLARED_WINDOW"}


def test_authorize_raises_with_every_defect_when_the_declaration_is_absent(
    tmp_path: Path,
) -> None:
    with pytest.raises(DeclarationError) as error:
        authorize(tmp_path / "absent.json", repo=tmp_path)
    assert error.value.codes == ("DECLARATION_MISSING",)


def test_authorize_carries_more_than_the_first_defect(scaffold: Scaffold) -> None:
    scaffold.write(
        scaffold.document(generator={"commit": "daa7bde"}, effective_from_utc="2026-11-01T00:00:00Z")
    )
    with pytest.raises(DeclarationError) as error:
        authorize(scaffold.declaration, repo=scaffold.repo)
    assert len(error.value.defects) >= 2
