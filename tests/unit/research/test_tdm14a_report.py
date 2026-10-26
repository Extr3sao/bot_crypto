"""Contract tests for the RFC-TDM-014A closing report renderer.

`FINAL_REPORT.md` is generated from the verdict, not written by hand, so it can
only be as honest as its inputs. These tests pin the two properties that make it
worth reading:

* every acceptance criterion the verifier produced appears, with the verifier's
  own status — the report cannot quietly drop the one that failed;
* the limits section is mandatory. A closing document that lists only the green
  checks is the exact failure mode this RFC was written about.
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
def report_module() -> Any:
    return load_script("tdm14a_report")


def synthetic_inputs(
    status: str = "FAIL",
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    checks = [{"id": f"ACC-{i:02d}", "status": "PASS"} for i in range(1, 12)]
    checks.append({"id": "ACC-12", "status": status})
    verification = {"verdict": "FAILED" if status != "PASS" else "VERIFIED_PORTABLE_FULL_REPLAY",
                    "checks": checks}
    report = {
        "verdict": verification["verdict"],
        "baseline_commit": "04fb8bc8",
        "head": "deadbeef",
        "branch": "fix/tdm14a",
        "commits": ["abc123 first"],
        "runs": [
            {
                "run_id": "run-lf",
                "core_autocrlf": "false",
                "status": "PASS",
                "duration_seconds": 419.7,
                "outputs_proven": "8/8",
            }
        ],
        "negative_controls": {"proven": 10, "total": 10},
        "v1_compatibility": {"status": "PASS", "differences": 0, "csv_identical": True},
        "tests": {
            "directory_run": {"failed": 79},
            "passed": 42,
            "failed": 0,
            "exit_code": 0,
            "suites": "targeted",
            "duration_seconds": 9.0,
        },
        "defects": [{"id": "D-01", "state": "FIXED", "detail": "fingerprint by blob"}],
        "paper_orders": 0,
        "live_orders": 0,
        "false_success": 0,
        "decision": "NO_ELIGIBLE_CANDIDATE / REJECTED_ALPHA",
        "files_changed": ["scripts/tdm14a_verify.py"],
    }
    replay = {"status": "PASS", "contracts_passing": 10, "contracts_compared": 10}
    return report, replay, verification


def test_every_acceptance_criterion_reaches_the_report(report_module: Any) -> None:
    report, replay, verification = synthetic_inputs()
    text = report_module.final_markdown(report, replay, verification, None)
    for check in verification["checks"]:
        assert f"| {check['id']} | {check['status']} |" in text


def test_a_failed_criterion_is_not_hidden_by_the_verdict(report_module: Any) -> None:
    report, replay, verification = synthetic_inputs(status="FAIL")
    text = report_module.final_markdown(report, replay, verification, None)
    assert "`FAILED`" in text
    assert "| ACC-12 | FAIL |" in text


def test_the_limits_section_is_present_and_names_independence(report_module: Any) -> None:
    report, replay, verification = synthetic_inputs()
    text = report_module.final_markdown(report, replay, verification, None)
    assert "## Qué NO se afirma" in text
    assert "INDEPENDENCE_NOT_DEMONSTRATED" in text
    assert "NO_ELIGIBLE_CANDIDATE / REJECTED_ALPHA" in text


def test_a_missing_closure_is_reported_as_not_run(report_module: Any) -> None:
    report, replay, verification = synthetic_inputs()
    text = report_module.final_markdown(report, replay, verification, None)
    assert "NOT_RUN" in text
    closure = {"head": "cafebabe", "files_checked": 25, "files_matching_head": 25, "status": "PASS",
               "self_excluded": ["evidence/tdm/wp-tdm-14a/POST_COMMIT_CLOSURE.json"]}
    text = report_module.final_markdown(report, replay, verification, closure)
    assert "cafebabe" in text and "25" in text
