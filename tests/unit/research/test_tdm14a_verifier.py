"""Contract tests for the RFC-TDM-014A verifier's custody rules.

Two properties are load-bearing and neither is visible from the published
artefacts, so they are pinned here:

* a ``git status --porcelain`` line must be parsed so that a real uncommitted
  change can never escape the ACC-12 clean-tree test. The helper that produced
  this RFC's own evidence trimmed the whole stdout, which ate the leading space
  of the first line only and turned ``evidence/...`` into ``vidence/...``;
* the verdict ladder must never promote a check that did not pass.

The verifier is imported as a module, so these tests exercise the same functions
that wrote ``verification_result.json``.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[3]


def load_script(name: str) -> Any:
    path = ROOT / "scripts" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def verifier() -> Any:
    return load_script("tdm14a_verify")


def test_porcelain_path_reads_a_line_with_its_leading_space(verifier: Any) -> None:
    assert verifier.porcelain_path(" M evidence/tdm/wp-tdm-14a/run_lf.json") == (
        "evidence/tdm/wp-tdm-14a/run_lf.json"
    )
    assert verifier.porcelain_path("?? evidence/tdm/wp-tdm-14a/NEW.json") == (
        "evidence/tdm/wp-tdm-14a/NEW.json"
    )
    assert verifier.porcelain_path("A  scripts/tdm14a_verify.py") == "scripts/tdm14a_verify.py"


def test_porcelain_path_survives_the_first_line_losing_its_space(verifier: Any) -> None:
    """The defect: ``git()`` strips the whole stdout, so line 0 arrives shifted.

    Slicing at column 3 assumed the space was present and returned ``vidence/...``
    for exactly the first dirty file, which is the one most likely to be a stale
    artefact.
    """
    shifted = "M evidence/tdm/wp-tdm-14a/verification_result.json"
    assert verifier.porcelain_path(shifted) == "evidence/tdm/wp-tdm-14a/verification_result.json"


def test_a_self_output_stays_excluded_after_the_shift(verifier: Any) -> None:
    """ACC-12 compares parsed paths against the explicit exclusion list."""
    self_outputs = set(verifier.SELF_OUTPUTS)
    shifted = "M evidence/tdm/wp-tdm-14a/EOL_COMPARISON.json"
    assert verifier.porcelain_path(shifted) in self_outputs


def test_a_foreign_dirty_file_is_never_excluded(verifier: Any) -> None:
    self_outputs = set(verifier.SELF_OUTPUTS)
    assert verifier.porcelain_path(" M evidence/tdm/wp-tdm-14a/run_lf.json") not in self_outputs


def test_rename_lines_resolve_to_the_target_path(verifier: Any) -> None:
    assert verifier.porcelain_path("R  old/name.json -> evidence/tdm/wp-tdm-14a/run_crlf.json") == (
        "evidence/tdm/wp-tdm-14a/run_crlf.json"
    )


def test_verdict_promotes_only_when_every_check_passes(verifier: Any) -> None:
    passing = [{"id": "ACC-01", "status": "PASS"}, {"id": "ACC-02", "status": "PASS"}]
    assert verifier.verdict(passing) == "VERIFIED_PORTABLE_FULL_REPLAY"

    failing = [{"id": "ACC-01", "status": "PASS"}, {"id": "ACC-02", "status": "FAIL"}]
    assert verifier.verdict(failing) == "FAILED"

    blocked = [{"id": "ACC-01", "status": "PASS"}, {"id": "ACC-02", "status": "BLOCKED"}]
    assert verifier.verdict(blocked) == "BLOCKED"


def test_verdict_does_not_promote_an_empty_check_list(verifier: Any) -> None:
    """Zero checks is not a clean sweep; it is no evidence."""
    assert verifier.verdict([]) == "BLOCKED"
