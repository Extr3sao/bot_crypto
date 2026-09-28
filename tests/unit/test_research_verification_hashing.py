"""Regression test for DEF-V2-1: artifact comparison must ignore line endings.

Found by running the V2 verifier in a fresh worktree: this repository has
``core.autocrlf=true``, so a fresh checkout materialises the generated artifacts
with CRLF while the generators write LF. A raw byte comparison then reports a
"divergence" whose content is in fact identical, which would either block a
release or — worse — train the reader to ignore the check.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]


def _load_verifier() -> Any:
    spec = importlib.util.spec_from_file_location(
        "research_verification", ROOT / "scripts" / "research_verification.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_normalized_hash_ignores_crlf(tmp_path: Path) -> None:
    verifier = _load_verifier()
    lf = tmp_path / "lf.json"
    crlf = tmp_path / "crlf.json"
    lf.write_bytes(b'{\n  "a": 1\n}\n')
    crlf.write_bytes(b'{\r\n  "a": 1\r\n}\r\n')

    assert verifier.sha256_file(lf) != verifier.sha256_file(crlf)
    assert verifier.sha256_normalized(lf) == verifier.sha256_normalized(crlf)


def test_normalized_hash_still_detects_real_content_change(tmp_path: Path) -> None:
    verifier = _load_verifier()
    original = tmp_path / "original.json"
    changed = tmp_path / "changed.json"
    original.write_bytes(b'{\n  "value": 1\n}\n')
    # same bytes except a real numerical change
    changed.write_bytes(b'{\n  "value": 2\n}\n')
    assert verifier.sha256_normalized(original) != verifier.sha256_normalized(changed)


def test_committed_v2_artifact_survives_a_crlf_checkout(tmp_path: Path) -> None:
    """A CRLF-materialised copy of a real artifact must hash as the same content."""
    verifier = _load_verifier()
    artifact = ROOT / "docs" / "EXECUTION_COST_MODEL_V4.json"
    assert artifact.exists(), "the V2 cost artifact must be committed"
    original_bytes = artifact.read_bytes()
    as_json = json.loads(original_bytes.decode("utf-8"))
    assert "assets" in as_json and "maker_gate" in as_json

    crlf_copy = tmp_path / artifact.name
    crlf_copy.write_bytes(original_bytes.replace(b"\n", b"\r\n"))
    assert verifier.sha256_file(crlf_copy) != verifier.sha256_file(artifact)
    assert verifier.sha256_normalized(crlf_copy) == verifier.sha256_normalized(artifact)


def test_v2_artifact_list_is_checked_by_content() -> None:
    """The V2 reproduction check must use the normalised hash for every artifact."""
    source = (ROOT / "scripts" / "research_verification.py").read_text(encoding="utf-8")
    verifier = _load_verifier()
    assert verifier.V2_ARTIFACTS, "the V2 artifact list must not be empty"
    for artifact in verifier.V2_ARTIFACTS:
        assert (ROOT / artifact).exists(), f"{artifact} is missing from the repository"
    assert "norm_before == norm_after" in source
