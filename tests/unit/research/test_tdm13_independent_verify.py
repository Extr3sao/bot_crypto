"""Contract tests for the RFC-TDM-013 independent verifier (WP-13C).

These hold the verifier to the behaviour the RFC demands: a check that did not
run can never become a PASS, an altered claim is caught by name, and the verdict
ladder degrades in the documented order. The scripts are imported as modules, so
the tests exercise the same functions that produced the published artefacts.

The last two tests read the committed evidence to check the manifest contract and
the negative-control verdict rule; everything else is hermetic and synthetic.
"""

from __future__ import annotations

import importlib.util
import json
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
    return load_script("tdm13_independent_verify")


@pytest.fixture(scope="module")
def replay_module() -> Any:
    return load_script("tdm13_replay")


@pytest.fixture(scope="module")
def controls_module() -> Any:
    return load_script("tdm13_negative_controls")


def build_package(root: Path, *, net_mean: float, eligible: list[str] | None = None) -> Path:
    """A miniature, internally consistent TDM-12 package inside ``root``."""
    tdm12 = root / "evidence" / "tdm" / "wp-tdm-12"
    tdm11 = root / "evidence" / "tdm" / "wp-tdm-11"
    tdm12.mkdir(parents=True, exist_ok=True)
    tdm11.mkdir(parents=True, exist_ok=True)

    (tdm11 / "RETROSPECTIVE_LEDGER.csv").write_text(
        "asset,gross_bps\nBTC,10.0\nBTC,-20.0\nETH,5.0\n", encoding="utf-8"
    )
    registry = {
        "rows": [{"candidate_id": "a"}, {"candidate_id": "b"}],
        "metrics_by_cell": {
            "a": {"dev": {"trades": 10, "net_mean": -3.0}, "hold": {"trades": 5, "net_mean": -5.0}},
            "b": {"dev": {"trades": 8, "net_mean": -4.0}, "hold": {"trades": 4, "net_mean": -6.0}},
        },
    }
    (tdm12 / "CANDIDATE_REGISTRY.json").write_text(json.dumps(registry), encoding="utf-8")
    (tdm12 / "DECISION_REGISTER.json").write_text(
        json.dumps({"decision": "NO_ELIGIBLE_CANDIDATE", "eligible_candidates": eligible or []}),
        encoding="utf-8",
    )
    (tdm12 / "TDM11_CLOSURE_DECISION.json").write_text(
        json.dumps({"alpha_status": "REJECTED_ALPHA"}), encoding="utf-8"
    )
    report = {
        "metrics": {
            "tdm11_review": {"trades": 3, "net_mean": net_mean},
            "triage": {"hold_net_positive": [], "dev_net_positive": [], "eligible": []},
        },
        "paper_orders": 0,
        "live_orders": 0,
        "result": "NO_ELIGIBLE_CANDIDATE",
        "independence_status": "INDEPENDENCE_NOT_DEMONSTRATED",
    }
    (tdm12 / "RUN_REPORT.json").write_text(json.dumps(report), encoding="utf-8")
    return root


CONSISTENT_REPORTED = {
    "deliverables": 14,
    "digests_ok": "16/16",
    "required_fields": "17/17",
    "strategies_measured": 2,
    "registry_rows": 2,
    "ledger_trades": 3,
    "net_mean_bps": -25.4573,
    "eligible": [],
    "paper_orders": 0,
    "live_orders": 0,
    "verdict": "NO_ELIGIBLE_CANDIDATE",
    "tdm11_alpha_status": "REJECTED_ALPHA",
}


# ---------------------------------------------------------------------------
# verdict ladder
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("git_integrity", "claims", "replay", "controls", "inputs", "expected"),
    [
        ("PASS", "PASS", "PASS", "PASS", "AVAILABLE", "VERIFIED_REPRODUCIBLE"),
        ("PASS", "PASS", "NOT_RUN", "PASS", "AVAILABLE", "INTEGRITY_ONLY"),
        ("PASS", "PASS", "PASS", "INCOMPLETE", "AVAILABLE", "INTEGRITY_ONLY"),
        ("PASS", "PASS", "PASS", "PASS", "UNAVAILABLE", "INTEGRITY_ONLY"),
        ("PASS", "PASS", "FAIL", "PASS", "AVAILABLE", "NOT_REPRODUCIBLE"),
        ("FAIL", "PASS", "PASS", "PASS", "AVAILABLE", "FAILED_INTEGRITY"),
        ("PASS", "FAIL", "PASS", "PASS", "AVAILABLE", "FAILED_INTEGRITY"),
        ("INCOMPLETE", "INCOMPLETE", "NOT_RUN", "INCOMPLETE", "UNKNOWN", "INCOMPLETE"),
    ],
)
def test_verdict_never_promotes_a_check_that_did_not_run(
    verifier: Any,
    git_integrity: str,
    claims: str,
    replay: str,
    controls: str,
    inputs: str,
    expected: str,
) -> None:
    result, reasons = verifier.decide(
        git_integrity=git_integrity,
        claims_consistency=claims,
        replay=replay,
        negative_controls=controls,
        input_state=inputs,
    )
    assert result == expected
    if result != "VERIFIED_REPRODUCIBLE":
        assert reasons, "a downgraded verdict must say why"


# ---------------------------------------------------------------------------
# claim re-derivation
# ---------------------------------------------------------------------------
def test_claims_pass_on_a_consistent_package(tmp_path: Path, verifier: Any) -> None:
    root = build_package(tmp_path, net_mean=CONSISTENT_REPORTED["net_mean_bps"])
    audit = verifier.audit_claims(from_dir=root, reported=CONSISTENT_REPORTED)
    assert audit["status"] == "PASS", audit["failures"]
    assert audit["checked"] == audit["matched"]
    assert {c["claim"] for c in audit["claims"]} >= {"ledger_trades", "net_mean_bps", "eligible"}


def test_altered_net_mean_is_caught_by_name(tmp_path: Path, verifier: Any) -> None:
    root = build_package(tmp_path, net_mean=CONSISTENT_REPORTED["net_mean_bps"] + 2.5)
    audit = verifier.audit_claims(from_dir=root, reported=CONSISTENT_REPORTED)
    assert audit["status"] == "FAIL"
    failed = {c["claim"] for c in audit["failures"]}
    assert failed == {"net_mean_matches_manifest"}
    assert all(c["reported"] != c["derived"] for c in audit["failures"])


def test_eligibility_is_recomputed_not_taken_from_the_verdict(
    tmp_path: Path, verifier: Any
) -> None:
    root = build_package(tmp_path, net_mean=CONSISTENT_REPORTED["net_mean_bps"])
    registry = json.loads(
        (root / "evidence/tdm/wp-tdm-12/CANDIDATE_REGISTRY.json").read_text(encoding="utf-8")
    )
    registry["metrics_by_cell"]["a"]["hold"]["net_mean"] = 4.0
    registry["metrics_by_cell"]["a"]["dev"]["net_mean"] = 3.0
    registry["metrics_by_cell"]["a"]["hold"]["power_sufficient"] = True
    (root / "evidence/tdm/wp-tdm-12/CANDIDATE_REGISTRY.json").write_text(
        json.dumps(registry), encoding="utf-8"
    )
    audit = verifier.audit_claims(from_dir=root, reported=CONSISTENT_REPORTED)
    assert audit["status"] == "FAIL"
    eligible = next(c for c in audit["claims"] if c["claim"] == "eligible")
    assert eligible["derived"] == ["a"]
    assert eligible["match"] is False


def test_missing_ledger_is_a_failure_not_a_pass(tmp_path: Path, verifier: Any) -> None:
    root = build_package(tmp_path, net_mean=CONSISTENT_REPORTED["net_mean_bps"])
    (root / "evidence/tdm/wp-tdm-11/RETROSPECTIVE_LEDGER.csv").unlink()
    audit = verifier.audit_claims(from_dir=root, reported=CONSISTENT_REPORTED)
    assert audit["status"] == "FAIL"


# ---------------------------------------------------------------------------
# replay comparison helpers
# ---------------------------------------------------------------------------
def test_strip_ephemeral_removes_only_the_enumerated_keys(replay_module: Any) -> None:
    document = {
        "generated_at_ms": 1,
        "elapsed_s": 2.5,
        "run_id": "x",
        "metrics": {"net_mean": -36.3676},
        "rows": [{"generated_at_ms": 3, "edge_net_bps": -21.851}],
    }
    stripped = replay_module.strip_ephemeral(document)
    assert "generated_at_ms" not in stripped
    assert "elapsed_s" not in stripped
    assert stripped["metrics"] == {"net_mean": -36.3676}
    assert stripped["rows"] == [{"edge_net_bps": -21.851}]


def test_deep_diff_names_the_leaf_that_changed(replay_module: Any) -> None:
    left = {"a": {"b": 1}, "c": [1, 2]}
    right = {"a": {"b": 2}, "c": [1, 3]}
    diff = replay_module.deep_diff(left, right)
    paths = {d["path"] for d in diff}
    assert paths == {"a.b", "c[1]"}
    assert replay_module.deep_diff(left, left) == []


# ---------------------------------------------------------------------------
# artefact contracts
# ---------------------------------------------------------------------------
def test_published_dataset_manifest_satisfies_the_contract() -> None:
    manifest = json.loads(
        (ROOT / "evidence/tdm/wp-tdm-13/DATASET_MANIFEST.json").read_text(encoding="utf-8")
    )
    for key in (
        "schema_version",
        "source_commit",
        "datasets",
        "storage_mode",
        "retrieval_instructions",
        "restriction_reason",
        "verified_at",
        "verifier_id",
        "input_state",
    ):
        assert key in manifest, key
    assert manifest["datasets"], "a bundle with no datasets proves nothing"
    for entry in manifest["datasets"]:
        for field in ("dataset_id", "path", "sha256", "state", "source", "license"):
            assert field in entry, field
        assert entry["state"] in {"SEALED_IN_BUNDLE", "MISSING"}
        assert len(entry["sha256"]) == 64


def test_control_needs_a_non_zero_exit_and_the_expected_cause(controls_module: Any) -> None:
    ok = controls_module._control(
        "NC-XX",
        "synthetic",
        "none",
        {"command": "x", "exit_code": 1, "stdout": ["FAIL wanted"], "stderr": []},
        "FAIL",
    )
    assert ok["status"] == "PROVEN"

    silent = controls_module._control(
        "NC-XX",
        "synthetic",
        "none",
        {"command": "x", "exit_code": 1, "stdout": ["something unrelated"], "stderr": []},
        "FAIL",
    )
    assert silent["status"] == "NOT_PROVEN"

    clean = controls_module._control(
        "NC-XX",
        "synthetic",
        "none",
        {"command": "x", "exit_code": 0, "stdout": ["FAIL"], "stderr": []},
        "FAIL",
    )
    assert clean["status"] == "NOT_PROVEN"
