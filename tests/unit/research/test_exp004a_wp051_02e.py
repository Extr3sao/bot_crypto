"""The phase-2 capture attempt is classified, and a capture that did not happen is refused.

Two things are under test here. The builder's preflight has to name the state of an attempt in a way
that cannot be talked up: ``CAPTURED`` requires bytes on disk inside an open window, and every other
name requires their absence. And the independent verifier has to reject a report that claims more
than the artefacts support — a ``PASS`` without a dataset, a digest that no longer matches, a gate
that was quietly promoted, a limitation whose declared behaviour is not the observed one.

None of these tests touches ``data/exp004a``, the freeze or a sealed artefact: the fixtures live in
``tmp_path`` and the probes run the declared extractor into a throwaway directory.
"""

from __future__ import annotations

import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "scripts"))
sys.path.insert(0, str(REPO / "src"))

import exp004a_wp051_02e_preflight as preflight  # noqa: E402
import exp004a_wp051_02e_verify as verifier  # noqa: E402

WINDOW_START = "2026-10-22T00:00:00Z"
WINDOW_END = "2027-01-20T00:00:00Z"
EFFECTIVE = "2026-10-21T16:00:00Z"


def _ms(iso: str) -> int:
    return int(datetime.fromisoformat(iso.replace("Z", "+00:00")).timestamp() * 1000)


def _by_id(checks: list[Any]) -> dict[str, Any]:
    return {item.check_id: item for item in checks}


def _row(open_utc: str, fetched_utc: str, *, closed: bool = True) -> dict[str, Any]:
    return {
        "ts": _ms(open_utc),
        "interval": "1h",
        "closed": closed,
        "fetched_at_ms": _ms(fetched_utc),
        "open": 100.0,
        "close": 101.0,
    }


def _series(tmp_path: Path, rows: list[dict[str, Any]]) -> Path:
    """Write a series where the store contract puts it: ``<root>/data/forward/edge03/1h/BTC.jsonl``."""
    path = tmp_path / "data" / "forward" / "edge03" / "1h" / "BTC.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes("".join(json.dumps(row) + "\n" for row in rows).encode("utf-8"))
    return path


def _entry() -> dict[str, Any]:
    return {
        "dataset_id": "EXP-004A-1H-BTC",
        "asset": "BTC",
        "timeframe": "1h",
        "generator_parameters": {"interval": "1h", "lag_bound_ms": 7_200_000},
    }


# --------------------------------------------------------------------------- #
# the window, with no grace period
# --------------------------------------------------------------------------- #
def test_the_window_opens_exactly_at_its_declared_instant() -> None:
    start, end = _ms(WINDOW_START), _ms(WINDOW_END)
    assert preflight.window_state(start, end, start - 1) == "BEFORE_WINDOW"
    assert preflight.window_state(start, end, start) == "OPEN"
    assert preflight.window_state(start, end, end - 1) == "OPEN"
    assert preflight.window_state(start, end, end) == "CLOSED"


# --------------------------------------------------------------------------- #
# classification: a name requires the bytes, or the absence of them
# --------------------------------------------------------------------------- #
def test_before_the_window_a_clean_refusal_is_pending_not_failed() -> None:
    state, reason = preflight.classify(
        state="BEFORE_WINDOW",
        exit_codes={"1h:BTC": 3, "1h:ETH": 3, "1h:SOL": 3},
        published=[],
    )
    assert state == "PENDING_WINDOW"
    assert "exit 3" in reason


def test_an_open_window_without_bars_is_not_a_capture() -> None:
    state, _ = preflight.classify(state="OPEN", exit_codes={"1h:BTC": 3}, published=[])
    assert state == "NO_ELIGIBLE_DATA"


def test_data_published_inside_an_open_window_is_the_only_capture() -> None:
    state, _ = preflight.classify(
        state="OPEN",
        exit_codes={"1h:BTC": 0},
        published=["data/exp004a/EXP-004A-1H-BTC.jsonl"],
    )
    assert state == "CAPTURED"


def test_a_dataset_written_before_the_window_is_a_failure_not_a_capture() -> None:
    state, reason = preflight.classify(
        state="BEFORE_WINDOW",
        exit_codes={"1h:BTC": 0},
        published=["data/exp004a/EXP-004A-1H-BTC.jsonl"],
    )
    assert state == "FAIL"
    assert "did not succeed" in reason


def test_an_eligibility_refusal_keeps_its_own_name() -> None:
    assert preflight.classify(state="OPEN", exit_codes={"1h:BTC": 5}, published=[])[0] == (
        "NOT_ELIGIBLE"
    )


def test_a_contract_error_blocks_rather_than_pending() -> None:
    assert preflight.classify(state="BEFORE_WINDOW", exit_codes={"1h:BTC": 2}, published=[])[0] == (
        "BLOCKED"
    )


def test_a_closed_window_without_a_dataset_fails() -> None:
    state, reason = preflight.classify(state="CLOSED", exit_codes={"1h:BTC": 3}, published=[])
    assert state == "FAIL"
    assert "closed" in reason


# --------------------------------------------------------------------------- #
# the store, counted against the declaration
# --------------------------------------------------------------------------- #
def test_the_store_snapshot_counts_what_the_declaration_cares_about(tmp_path: Path) -> None:
    _series(
        tmp_path,
        [
            _row("2026-10-21T05:00:00Z", "2026-10-21T09:00:00Z"),  # before the declaration
            _row("2026-10-22T00:00:00Z", "2026-10-21T17:00:00Z"),  # inside the window, negative lag
            _row("2026-10-22T01:00:00Z", "2027-01-01T00:00:00Z", closed=False),
        ],
    )
    snapshot = preflight.store_snapshot(
        tmp_path,
        _entry(),
        start_ms=_ms(WINDOW_START),
        end_ms=_ms(WINDOW_END),
        effective_ms=_ms(EFFECTIVE),
        at_ms=_ms("2026-10-21T18:00:00Z"),
    )
    assert snapshot["readable"] is True
    assert snapshot["bars"] == 3
    assert snapshot["bars_opening_in_window"] == 2
    assert snapshot["bars_fetched_before_effective"] == 1
    assert snapshot["unclosed_bars"] == 1
    assert snapshot["negative_lag_bars"] == 1
    assert snapshot["bars_fetched_after_now"] == 1, "a future ingest is counted, not believed"


def test_a_missing_series_is_reported_unreadable_rather_than_empty(tmp_path: Path) -> None:
    snapshot = preflight.store_snapshot(
        tmp_path,
        _entry(),
        start_ms=_ms(WINDOW_START),
        end_ms=_ms(WINDOW_END),
        effective_ms=_ms(EFFECTIVE),
        at_ms=_ms("2026-10-21T18:00:00Z"),
    )
    assert snapshot["present"] is False
    assert snapshot["readable"] is False
    assert "does not exist" in snapshot["error"]


# --------------------------------------------------------------------------- #
# the verifier rejects a claim the artefacts do not support
# --------------------------------------------------------------------------- #
def _run_dir(tmp_path: Path, capture: dict[str, Any], report: dict[str, Any]) -> Path:
    run_dir = tmp_path / "wp051_02e"
    (run_dir / "evidence").mkdir(parents=True)
    (run_dir / "WP_051_02E_PREFLIGHT.json").write_text(
        json.dumps({"role": "builder", "economic_executions": 0}), encoding="utf-8"
    )
    (run_dir / "WP_051_02E_CAPTURE_REPORT.json").write_text(json.dumps(capture), encoding="utf-8")
    (run_dir / "RUN_REPORT.json").write_text(json.dumps(report), encoding="utf-8")
    return run_dir


def _capture(status: str, *, published: list[str] | None = None) -> dict[str, Any]:
    return {
        "status": status,
        "datasets_published": published or [],
        "window_state_at_capture": "BEFORE_WINDOW",
        "started_at_utc": "2026-10-21T19:00:00Z",
        "capture_window": {"effective_from_utc": EFFECTIVE},
        "temporal": {"external_timestamp": "UNAVAILABLE", "time_proof": "TIME_PROOF_WEAK"},
        "economic_executions": 0,
    }


def _report(**overrides: Any) -> dict[str, Any]:
    document: dict[str, Any] = {
        "status": {
            "WP_051_02E": "PENDING_WINDOW",
            "C_004": "PASS",
            "C_013": "TIME_PROOF_WEAK",
            "C_016": "UNREACHABLE_UNDER_DECLARED_COST_MODEL",
            "PAPER_VALIDATION": "NOT_PASS",
            "CERTIFICATION": "BLOCKED",
            "PROMOTION": "NO_PROMOTION",
        },
        "limitations": [{"id": "L-01", "observed_exit_code": 0}],
        "artefacts": [],
        "admission_ledgers": {},
        "economic_executions": 0,
    }
    document.update(overrides)
    return document


def test_a_capture_claim_that_names_the_wrong_window_state_fails(tmp_path: Path) -> None:
    report = _report()
    capture = _capture("PENDING_WINDOW")
    capture["window_state_at_capture"] = "OPEN"
    checks = _by_id(verifier.temporal_checks(capture, report))
    assert checks["V-TEMP-01"].status == "FAIL"


def test_a_pass_without_a_dataset_is_refused(tmp_path: Path) -> None:
    report = _report()
    report["status"]["WP_051_02E"] = "PASS"
    capture = _capture("PENDING_WINDOW")
    checks = _by_id(verifier.policy_checks(tmp_path, capture, report))
    assert checks["V-POL-04"].status == "FAIL"
    assert "PENDING_WINDOW" in checks["V-POL-04"].detail


def test_a_promoted_gate_is_refused(tmp_path: Path) -> None:
    report = _report()
    report["status"]["CERTIFICATION"] = "PASS"
    checks = _by_id(verifier.policy_checks(tmp_path, _capture("PENDING_WINDOW"), report))
    assert checks["V-POL-03"].status == "FAIL"


def test_a_borrowed_external_timestamp_is_refused(tmp_path: Path) -> None:
    capture = _capture("PENDING_WINDOW")
    capture["temporal"]["external_timestamp"] = "2026-10-21T19:00:00Z"
    checks = _by_id(verifier.temporal_checks(capture, _report()))
    assert checks["V-TEMP-03"].status == "FAIL"


def test_an_artefact_whose_digest_moved_fails(tmp_path: Path) -> None:
    report = _report(
        artefacts=[{"path": "AGENTS.md", "sha256": "0" * 64}],
    )
    run_dir = _run_dir(tmp_path, _capture("PENDING_WINDOW"), report)
    checks = _by_id(verifier.artifact_checks(run_dir, _capture("PENDING_WINDOW"), report))
    assert checks["V-ART-02"].status == "FAIL"
    assert checks["V-ART-02"].evidence["mismatched"][0]["path"] == "AGENTS.md"


def test_an_artefact_digest_that_matches_passes(tmp_path: Path) -> None:
    import hashlib

    digest = hashlib.sha256((REPO / "AGENTS.md").read_bytes()).hexdigest()
    report = _report(artefacts=[{"path": "AGENTS.md", "sha256": digest}])
    run_dir = _run_dir(tmp_path, _capture("PENDING_WINDOW"), report)
    checks = _by_id(verifier.artifact_checks(run_dir, _capture("PENDING_WINDOW"), report))
    assert checks["V-ART-02"].status == "PASS"


def test_a_limitation_whose_declared_behaviour_is_not_the_observed_one_fails(
    tmp_path: Path,
) -> None:
    report = _report(limitations=[{"id": "L-01", "observed_exit_code": 5}])
    checks = _by_id(verifier.policy_checks(tmp_path, _capture("PENDING_WINDOW"), report))
    assert checks["V-POL-05"].status == "FAIL"


def test_the_declared_limitation_is_the_frozen_extractors_real_behaviour(tmp_path: Path) -> None:
    """``L-01`` is a fact about the frozen generator, not a claim about what it ought to do."""
    report = _report(limitations=[{"id": "L-01", "observed_exit_code": 0}])
    checks = _by_id(verifier.policy_checks(tmp_path, _capture("PENDING_WINDOW"), report))
    assert checks["V-POL-05"].status == "PASS"


def test_the_verifier_will_not_run_its_own_verdict_as_evidence(tmp_path: Path) -> None:
    """No capture report and no run report: the verdict is BLOCKED, never PASS."""
    checks, status = verifier.verify(tmp_path / "nowhere")
    assert status == "BLOCKED"
    assert any(item.status == "BLOCKED" for item in checks)


def test_the_verifier_does_not_import_the_module_it_verifies() -> None:
    import ast

    tree = ast.parse(Path(verifier.__file__).read_text(encoding="utf-8"))
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
    assert not any(name.startswith("trading_bot") for name in imported)
    assert not any(name.startswith("exp004a_") for name in imported)


# --------------------------------------------------------------------------- #
# the seal
# --------------------------------------------------------------------------- #
def test_the_seal_refuses_a_manifest_whose_digest_no_longer_matches(tmp_path: Path) -> None:
    run_dir = tmp_path / "sealed"
    (run_dir / "evidence").mkdir(parents=True)
    for name in verifier.REQUIRED_AT_SEAL:
        (run_dir / name).write_text("{}\n", encoding="utf-8")
    import hashlib

    digest = hashlib.sha256((REPO / "AGENTS.md").read_bytes()).hexdigest()
    (run_dir / "EVIDENCE_MANIFEST.json").write_text(
        json.dumps({"entries": [{"path": "AGENTS.md", "sha256": digest}]}), encoding="utf-8"
    )
    assert verifier.seal(run_dir)["status"] == "PASS"

    (run_dir / "EVIDENCE_MANIFEST.json").write_text(
        json.dumps({"entries": [{"path": "AGENTS.md", "sha256": "0" * 64}]}), encoding="utf-8"
    )
    sealed = verifier.seal(run_dir)
    assert sealed["status"] == "FAIL"
    assert sealed["mismatched"][0]["path"] == "AGENTS.md"


def test_the_seal_reports_a_missing_report_instead_of_ignoring_it(tmp_path: Path) -> None:
    run_dir = tmp_path / "sealed"
    run_dir.mkdir(parents=True)
    (run_dir / "EVIDENCE_MANIFEST.json").write_text(json.dumps({"entries": []}), encoding="utf-8")
    sealed = verifier.seal(run_dir)
    assert sealed["status"] == "FAIL"
    assert "WP_051_02E_FINAL_REPORT.md" in sealed["missing_reports"]


def test_an_empty_manifest_is_never_a_pass(tmp_path: Path) -> None:
    run_dir = tmp_path / "sealed"
    run_dir.mkdir(parents=True)
    assert verifier.seal(run_dir)["status"] == "BLOCKED"


# --------------------------------------------------------------------------- #
# the anchors are stated, not learned from the document they check
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("capture_window.start_utc", "2026-10-25T00:00:00Z"),
        ("generator.commit", "0" * 40),
        ("governance_status", "PROPOSED"),
        ("supersedes.sha256", "1" * 64),
    ],
)
def test_a_doctored_declaration_fails_the_anchor_check(field: str, value: str) -> None:
    document = json.loads(
        (REPO / "config" / "preregistrations" / "EXP-004A.datasets.phase2.json").read_text(
            encoding="utf-8"
        )
    )
    if field == "capture_window.start_utc":
        document["capture_window"]["start_utc"] = value
    elif field == "generator.commit":
        document["generator"]["commit"] = value
    elif field == "supersedes.sha256":
        document["supersedes"]["sha256"] = value
    else:
        document[field] = value
    checks = _by_id(verifier.technical_checks(document))
    assert checks["V-TECH-02"].status == "FAIL"


def test_the_shipped_declaration_satisfies_the_anchors() -> None:
    document = json.loads(
        (REPO / "config" / "preregistrations" / "EXP-004A.datasets.phase2.json").read_text(
            encoding="utf-8"
        )
    )
    checks = _by_id(verifier.technical_checks(document))
    assert checks["V-TECH-02"].status == "PASS"
    assert checks["V-TECH-03"].status == "PASS"
    assert checks["V-TECH-04"].status == "PASS"


def test_the_utc_guard_refuses_a_naive_instant() -> None:
    with pytest.raises(ValueError, match="explicit UTC"):
        verifier.ms("2026-10-22T00:00:00")
    assert verifier.iso(verifier.ms(WINDOW_START)) == "2026-10-22T00:00:00.000Z"


def test_now_is_read_in_utc() -> None:
    moment = datetime.fromtimestamp(verifier.now_ms() / 1000, UTC)
    assert abs((datetime.now(UTC) - moment).total_seconds()) < 60
