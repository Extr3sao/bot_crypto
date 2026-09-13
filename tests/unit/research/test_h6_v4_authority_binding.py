"""H6 V4 — runtime authority binding tests (sections 17-24).

* STALE_V1_ACTIVE_BINDINGS == 0
* SINGLE_V4_AUTHORITY_BINDING — exactly one module holds authoritative literals
* fail-closed while unbound
* deterministic, CWD-independent external-report path
* synthetic external-report authority matrix (no real verification report exists)

No economics. No report is created by this audit.
"""

from __future__ import annotations

import ast
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from trading_bot.research.h6 import runtime_authority as RA
from trading_bot.research.h6 import execution_harness as EH

H6_PKG = Path(RA.__file__).resolve().parent
REPO = RA.REPO_ROOT
V4_DIR = REPO / "docs" / "external-audit-01" / "h6-v4-repair"

V1_LITERALS = (
    "e683e04",
    "f514fecf",
    "345334c3",
    "256bd5ec",
    "oi-full-history-01/H6_SPEC.json",
    "oi-full-history-01/H6_MANIFEST.json",
    "oi-full-history-01/H6_EXTERNAL_VERIFIER_REPORT.json",
)


def _code_string_constants(path: Path) -> list[tuple[int, str]]:
    """String constants that are NOT docstrings — i.e. live code bindings."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    docstrings = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            body = getattr(node, "body", [])
            if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
                docstrings.add(id(body[0].value))
    out: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in docstrings:
            out.append((getattr(node, "lineno", 0), node.value))
    return out


def test_no_stale_v1_active_binding_in_h6_package() -> None:
    """STALE_V1_ACTIVE_BINDINGS == 0 — docstrings may explain history, code may not pin it."""
    offenders: list[str] = []
    for path in sorted(H6_PKG.glob("*.py")):
        for lineno, value in _code_string_constants(path):
            for literal in V1_LITERALS:
                if literal in value:
                    offenders.append(f"{path.name}:{lineno} -> {literal}")
    assert offenders == [], f"stale V1 active bindings: {offenders}"


def test_only_the_binding_module_holds_authority_literals() -> None:
    """SINGLE_V4_AUTHORITY_BINDING — no other module duplicates hash/commit literals."""
    import re

    hex64 = re.compile(r"^[0-9a-f]{64}$")
    holders: dict[str, list[str]] = {}
    for path in sorted(H6_PKG.glob("*.py")):
        for _, value in _code_string_constants(path):
            if hex64.match(value):
                holders.setdefault(path.name, []).append(value)
    assert set(holders) <= {"runtime_authority.py"}, holders


def test_pre_freeze_runtime_is_unbound_and_fail_closed() -> None:
    """PRE-FREEZE: no binding file, so the runtime must refuse to run."""
    binding_exists = RA.BINDING_PATH.exists()
    status = RA.binding_status()
    assert status["binding_exists"] == binding_exists
    if not binding_exists:
        assert status["state"] == RA.UNBOUND
        assert RA.load_binding() is None
        with pytest.raises(RA.H6RuntimeAuthorityUnavailable):
            RA.current_binding()
        assert EH.can_execute_h6() is False
        assert EH.gate_status()["reason"] in {"RUNTIME_AUTHORITY_UNBOUND", "REPORT_MISSING_OR_MALFORMED"}


def test_report_path_is_absolute_and_cwd_independent(tmp_path: Path) -> None:
    """V4-AUTH-001: the V1 report path was relative, so the gate depended on the CWD."""
    resolved_here = RA.expected_external_verifier_report_path()
    assert resolved_here.is_absolute()
    assert "h6-external-verification-v4" in str(resolved_here).replace("\\", "/")

    code = "import trading_bot.research.h6.runtime_authority as r; print(r.expected_external_verifier_report_path())"
    env = dict(os.environ)
    env["PYTHONPATH"] = str(REPO / "src")
    out = subprocess.run(
        [sys.executable, "-c", code], cwd=str(tmp_path), capture_output=True, text=True, env=env, timeout=120
    )
    assert out.returncode == 0, out.stderr
    assert Path(out.stdout.strip()).resolve() == resolved_here.resolve()


# ------------------------------------------------------------------ synthetic


def _real_artifact_hashes() -> dict[str, str]:
    return {
        "spec": hashlib.sha256((V4_DIR / "H6_SPEC_V4.json").read_bytes()).hexdigest(),
        "manifest": hashlib.sha256((V4_DIR / "H6_MANIFEST_V4.json").read_bytes()).hexdigest(),
        "whitelist": hashlib.sha256((V4_DIR / "H6_FEATURE_AUTHORITY_WHITELIST_V4.json").read_bytes()).hexdigest(),
        "data_authority": hashlib.sha256((V4_DIR / "H6_DATA_AUTHORITY_V4.json").read_bytes()).hexdigest(),
    }


@pytest.fixture()
def bound(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Install a TEMP binding that points at the real V4 artifacts (no economics)."""
    h = _real_artifact_hashes()
    rel = "docs/external-audit-01/h6-v4-repair"
    binding = {
        "schema_version": RA.BINDING_SCHEMA_VERSION,
        "generation": "H6-V4",
        "prereg_commit": "a" * 40,
        "spec_path": f"{rel}/H6_SPEC_V4.json",
        "spec_sha256": h["spec"],
        "manifest_path": f"{rel}/H6_MANIFEST_V4.json",
        "manifest_sha256": h["manifest"],
        "whitelist_path": f"{rel}/H6_FEATURE_AUTHORITY_WHITELIST_V4.json",
        "whitelist_sha256": h["whitelist"],
        "data_authority_path": f"{rel}/H6_DATA_AUTHORITY_V4.json",
        "data_authority_sha256": h["data_authority"],
        "expected_external_verifier_report_path": (
            "docs/external-audit-01/h6-external-verification-v4/H6_EXTERNAL_VERIFICATION_V4_REPORT.json"
        ),
        "dataset_sha256": json.loads((V4_DIR / "H6_DATA_AUTHORITY_V4.json").read_text())["dataset_sha256"],
    }
    p = tmp_path / "H6_RUNTIME_AUTHORITY_BINDING_V4.json"
    p.write_text(json.dumps(binding), encoding="utf-8")
    monkeypatch.setattr(RA, "BINDING_PATH", p)
    RA._cache.clear()
    yield binding, h
    RA._cache.clear()


def _report(binding: dict, h: dict, **overrides) -> dict:
    r = {
        "FINAL_VERDICT": "PASS",
        "generation": binding["generation"],
        "prereg_commit": binding["prereg_commit"],
        "spec_sha256": h["spec"],
        "manifest_sha256": h["manifest"],
        "dataset_sha256": binding["dataset_sha256"],
    }
    r.update(overrides)
    return r


def test_correct_v4_report_is_structurally_accepted(bound) -> None:
    binding, h = bound
    ok, reason = EH.evaluate_report(_report(binding, h))
    assert ok is True, reason
    assert reason == "AUTHORIZED"


@pytest.mark.parametrize("generation", ["H6-V1", "H6-V2", "H6-V3"])
def test_older_generation_reports_are_rejected(bound, generation: str) -> None:
    """A genuine V1/V2/V3 PASS must NOT satisfy the V4 gate."""
    binding, h = bound
    ok, reason = EH.evaluate_report(_report(binding, h, generation=generation))
    assert ok is False
    assert reason.startswith("GENERATION_MISMATCH")


@pytest.mark.parametrize(
    "key", ["spec_sha256", "manifest_sha256", "dataset_sha256", "prereg_commit"]
)
def test_wrong_authority_hash_is_rejected(bound, key: str) -> None:
    binding, h = bound
    ok, reason = EH.evaluate_report(_report(binding, h, **{key: "b" * 64}))
    assert ok is False
    assert key.upper() in reason


@pytest.mark.parametrize("verdict", ["FAIL", "BLOCKED", "", None, "PENDING"])
def test_non_pass_verdict_is_rejected(bound, verdict) -> None:
    binding, h = bound
    ok, _ = EH.evaluate_report(_report(binding, h, FINAL_VERDICT=verdict))
    assert ok is False


def test_missing_report_fails_closed(bound) -> None:
    ok, reason = EH.evaluate_report(None)
    assert ok is False
    assert reason == "REPORT_MISSING_OR_MALFORMED"


@pytest.mark.parametrize("bad", ["a string", 42, [], object()])
def test_malformed_report_fails_closed(bound, bad) -> None:
    ok, _ = EH.evaluate_report(bad)  # type: ignore[arg-type]
    assert ok is False


def test_report_missing_required_keys_is_rejected(bound) -> None:
    binding, h = bound
    r = _report(binding, h)
    del r["spec_sha256"]
    ok, reason = EH.evaluate_report(r)
    assert ok is False
    assert "REPORT_MISSING_KEYS" in reason


def test_synthetic_binding_verifies_real_artifacts(bound) -> None:
    """The binding's hash recomputation must succeed against the real V4 artifacts."""
    RA._cache.clear()
    b = RA.current_binding()
    rec = b.verify_artifacts_present_and_matching()
    assert all(v["match"] for v in rec.values()), rec


def test_binding_rejects_non_v4_report_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """V3's stale V1 report path must not be loadable as a V4 binding."""
    p = tmp_path / "H6_RUNTIME_AUTHORITY_BINDING_V4.json"
    p.write_text(
        json.dumps(
            {
                "schema_version": RA.BINDING_SCHEMA_VERSION,
                "generation": "H6-V4",
                "prereg_commit": "a" * 40,
                "spec_path": "x", "spec_sha256": "0" * 64,
                "manifest_path": "x", "manifest_sha256": "0" * 64,
                "whitelist_path": "x", "whitelist_sha256": "0" * 64,
                "data_authority_path": "x", "data_authority_sha256": "0" * 64,
                "expected_external_verifier_report_path": (
                    "docs/external-audit-01/oi-full-history-01/H6_EXTERNAL_VERIFIER_REPORT.json"
                ),
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(RA, "BINDING_PATH", p)
    RA._cache.clear()
    assert RA.load_binding() is None
    with pytest.raises(RA.H6RuntimeAuthorityUnavailable):
        RA.current_binding()
    RA._cache.clear()


def test_binding_rejects_malformed_hashes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    p = tmp_path / "b.json"
    p.write_text(
        json.dumps(
            {
                "schema_version": RA.BINDING_SCHEMA_VERSION,
                "generation": "H6-V4",
                "prereg_commit": "a" * 40,
                "spec_path": "x", "spec_sha256": "NOT_HEX",
                "manifest_path": "x", "manifest_sha256": "0" * 64,
                "whitelist_path": "x", "whitelist_sha256": "0" * 64,
                "data_authority_path": "x", "data_authority_sha256": "0" * 64,
                "expected_external_verifier_report_path": (
                    "docs/external-audit-01/h6-external-verification-v4/R.json"
                ),
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(RA, "BINDING_PATH", p)
    RA._cache.clear()
    assert RA.load_binding() is None
    RA._cache.clear()
