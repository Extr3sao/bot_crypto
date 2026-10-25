"""RFC-DEF-RUN-019 / WP-04F — a report may not say ``PASS`` over a suite that failed.

The first version of the closer read the test logs, printed them in the ``TESTS`` block and
then computed ``VERDICT = PASS`` from something else, with ``FALSE_SUCCESS`` typed as ``0``.
It shipped exactly that: ``PASS`` beside ``1 failed, 348 passed``. These cases pin the rule
that replaced it — the verdict is the conjunction of the gates, a suite that failed (or a
log that cannot prove it passed) removes the verdict, and the emitted payload is read back
and checked for the contradiction.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[3]


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


closer = load_module("def_run_019_close", REPO / "scripts" / "def_run_019_close.py")


def write_suite(tmp_path: Path, text: str, exit_code: str | None) -> tuple[Path, Path]:
    log = tmp_path / "suite.log"
    log.write_text(text, encoding="utf-8", newline="\n")
    status = tmp_path / "suite.exit"
    if exit_code is not None:
        status.write_text(exit_code + "\n", encoding="utf-8", newline="\n")
    return log, status


def clean_gates() -> dict[str, dict[str, Any]]:
    return closer.build_gates(
        implementation="PASS",
        vision={"state": "PASS", "line": "349 passed in 718.36s"},
        reports={"state": "PASS", "line": "264 passed in 167.24s"},
        ab={"all_match": True, "compared_rows": 20, "differences": []},
        controls={"all_detected": True, "controls": [{"control": "x"}]},
        verifier={"overall": "PASS", "verifier": "scripts/def_run_019_verify.py"},
    )


def payload(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "VERDICT": "PASS",
        "GATES": clean_gates(),
        "IMPLEMENTATION": {"state": "PASS", "runtime_digest": "a" * 64},
        "TESTS": {
            "vision": {
                "state": "PASS",
                "line": "349 passed in 718.36s",
                "passed": 349,
                "failed": 0,
                "errors": 0,
                "exit_code": 0,
            },
            "reports": {
                "state": "PASS",
                "line": "264 passed in 167.24s",
                "passed": 264,
                "failed": 0,
                "errors": 0,
                "exit_code": 0,
            },
        },
    }
    base.update(overrides)
    return base


def test_a_failing_suite_is_never_green(tmp_path: Path) -> None:
    log, status = write_suite(tmp_path, "1 failed, 348 passed in 1298.34s\n", "1")
    summary = closer.pytest_summary(log, status)
    assert summary["state"] == "NOT_EVIDENCED"
    assert summary["failed"] == 1
    assert "SUITE_FAILURES" in summary["reasons"]
    assert "NON_ZERO_EXIT" in summary["reasons"]


def test_a_green_log_without_a_recorded_exit_code_is_not_evidenced(tmp_path: Path) -> None:
    """"passed" in a file is a claim; the exit status is the runner's own answer."""
    log, status = write_suite(tmp_path, "349 passed in 718.36s\n", None)
    summary = closer.pytest_summary(log, status)
    assert summary["state"] == "NOT_EVIDENCED"
    assert summary["reasons"] == ["NO_RECORDED_EXIT_CODE"]


def test_a_truncated_log_does_not_look_cleaner_than_a_failed_one(tmp_path: Path) -> None:
    log, status = write_suite(tmp_path, "." * 72 + "\n....F..\n", "1")
    summary = closer.pytest_summary(log, status)
    assert summary["state"] == "NOT_EVIDENCED"
    assert "NO_SUMMARY_LINE" in summary["reasons"]


def test_only_a_conclusive_green_run_earns_the_gate(tmp_path: Path) -> None:
    log, status = write_suite(tmp_path, "349 passed in 718.36s\n", "0")
    summary = closer.pytest_summary(log, status)
    assert summary["state"] == "PASS"
    assert summary["conclusive"] is True
    assert summary["passed"] == 349


def test_a_missing_log_is_not_evidenced_instead_of_empty(tmp_path: Path) -> None:
    summary = closer.pytest_summary(tmp_path / "nope.log", tmp_path / "nope.exit")
    assert summary["present"] is False
    assert summary["state"] == "NOT_EVIDENCED"


def test_one_failed_suite_removes_the_verdict() -> None:
    gates = clean_gates()
    gates["tests_vision"] = {"state": "NOT_EVIDENCED", "detail": "1 failed, 348 passed"}
    assert closer.verdict_from(gates) == "NOT_EVIDENCED"


def test_every_gate_has_to_hold() -> None:
    assert closer.verdict_from(clean_gates()) == "PASS"
    for name in clean_gates():
        gates = clean_gates()
        gates[name] = {"state": "NOT_EVIDENCED", "detail": "roto"}
        assert closer.verdict_from(gates) == "NOT_EVIDENCED", name


def test_the_self_check_catches_the_pass_shipped_over_a_failure() -> None:
    broken = payload()
    broken["TESTS"]["vision"] = {
        "state": "PASS",
        "line": "1 failed, 348 passed in 1298.34s",
        "passed": 348,
        "failed": 1,
        "errors": 0,
        "exit_code": 0,
    }
    problems = closer.self_check(broken)
    assert any("TESTS.vision" in problem for problem in problems)


def test_the_self_check_catches_a_pass_over_a_closed_gate() -> None:
    broken = payload(VERDICT="PASS")
    broken["GATES"]["economic_integrity"] = {"state": "NOT_EVIDENCED", "detail": "1 diferencia"}
    problems = closer.self_check(broken)
    assert any("economic_integrity" in problem for problem in problems)


def test_the_self_check_catches_an_implementation_pass_without_a_digest() -> None:
    broken = payload()
    broken["IMPLEMENTATION"] = {"state": "PASS", "runtime_digest": None}
    assert closer.self_check(broken)


def test_a_consistent_payload_passes_the_self_check() -> None:
    assert closer.self_check(payload()) == []


def test_the_collected_counts_come_from_a_real_collection(tmp_path: Path) -> None:
    listing = tmp_path / "collect.txt"
    listing.write_text(
        "tests/unit/vision/test_session_provenance.py::test_a\n"
        "tests/unit/vision/test_session_provenance.py::test_b\n"
        "tests/unit/reports/test_def_run_019_verifier.py::test_c\n"
        "55 tests collected in 1.85s\n",
        encoding="utf-8",
        newline="\n",
    )
    counts = closer.collected(listing)
    assert counts == {
        "tests/unit/vision/test_session_provenance.py": 2,
        "tests/unit/reports/test_def_run_019_verifier.py": 1,
    }
