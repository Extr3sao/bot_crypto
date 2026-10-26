"""WP-SIGNAL-003 — the verifier must be able to say no.

A checker that only ever passes is decoration. These tests give it a real run,
then damage it in the four ways that matter: a row that points at no decision, a
row whose numbers were edited, a signal labelled REAL for a demo provider, and an
analysis row claiming a signal that does not exist.
"""

from __future__ import annotations

import asyncio
import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

import pytest

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "src"))

from .helpers import make_ledger, make_runtime  # noqa: E402


def _load_verifier() -> Any:
    spec = importlib.util.spec_from_file_location(
        "wp_signal_verify_under_test", REPO / "scripts" / "wp_signal_verify.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["wp_signal_verify_under_test"] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def verifier() -> Any:
    return _load_verifier()


def _run(tmp_path: Path, cycles: int = 2) -> Path:
    run_dir = tmp_path / "autonomous-paper" / "run-verify"
    runtime, _scanner, _broker = make_runtime(
        run_dir=run_dir, ledger=make_ledger(gross_bps=4.0), signal_source="FAKE"
    )
    asyncio.run(runtime.run(cycles=cycles))
    (run_dir / "PAPER_RUN.json").write_text(
        json.dumps({"run_id": run_dir.name, "provider": "fake", "timeframe": "5m"}),
        encoding="utf-8",
    )
    return run_dir


def _verify(verifier: Any, tmp_path: Path, run_dir: Path) -> tuple[int, dict[str, Any]]:
    out = tmp_path / "verify.json"
    code = verifier.main(
        [
            "--run-root",
            str(tmp_path / "autonomous-paper"),
            "--run-id",
            run_dir.name,
            "--out",
            str(out),
        ]
    )
    return code, json.loads(out.read_text(encoding="utf-8"))


def _rewrite(path: Path, mutate: Any) -> None:
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    rows = mutate(rows)
    path.write_text(
        "".join(json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n" for row in rows),
        encoding="utf-8",
    )


def test_a_real_run_passes_every_check(tmp_path: Path, verifier: Any) -> None:
    run_dir = _run(tmp_path)
    code, report = _verify(verifier, tmp_path, run_dir)
    assert code == verifier.EXIT_PASS, report["failed"]
    assert report["ok"] is True
    assert report["verifier_imports_producer"] is False
    assert report["counts"]["signal_rows"] == 2
    assert report["counts"]["trace_linked"] == 2
    names = {check["name"] for check in report["checks"]}
    assert "signals.trace_hash_recomputes" in names
    assert "signals.source_matches_the_provider" in names


def test_out_may_be_a_directory(tmp_path: Path, verifier: Any) -> None:
    """``--out`` names where the report goes, so a directory receives it inside.

    Passing a directory used to raise PermissionError from deep inside pathlib,
    which reads like a broken verifier rather than an answer about usage.
    """
    run_dir = _run(tmp_path)
    out_dir = tmp_path / "verify-out"
    out_dir.mkdir()
    code = verifier.main(
        [
            "--run-root",
            str(tmp_path / "autonomous-paper"),
            "--run-id",
            run_dir.name,
            "--out",
            str(out_dir),
        ]
    )
    report = json.loads((out_dir / "SIGNAL_VERIFY.json").read_text(encoding="utf-8"))
    assert code == verifier.EXIT_PASS, report["failed"]
    assert report["ok"] is True


def test_out_creates_its_missing_parents(tmp_path: Path, verifier: Any) -> None:
    run_dir = _run(tmp_path)
    out = tmp_path / "deep" / "nested" / "verify.json"
    code = verifier.main(
        [
            "--run-root",
            str(tmp_path / "autonomous-paper"),
            "--run-id",
            run_dir.name,
            "--out",
            str(out),
        ]
    )
    assert code == verifier.EXIT_PASS
    assert out.exists()


def test_an_orphan_signal_fails(tmp_path: Path, verifier: Any) -> None:
    run_dir = _run(tmp_path)
    _rewrite(run_dir / "signals.jsonl", lambda rows: [*rows, {**rows[0], "decision_id": "no-such"}])
    code, report = _verify(verifier, tmp_path, run_dir)
    assert code == verifier.EXIT_FAIL
    assert "signals.every_row_maps_to_a_trace" in report["failed"]


def test_an_edited_edge_fails_the_hash_pin(tmp_path: Path, verifier: Any) -> None:
    run_dir = _run(tmp_path)

    def mutate(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        rows[0]["gross_edge_bps"] = 999.0
        return rows

    _rewrite(run_dir / "signals.jsonl", mutate)
    code, report = _verify(verifier, tmp_path, run_dir)
    assert code == verifier.EXIT_FAIL
    # The hash pin covers the trace; the numbers are checked against the proposal
    # the trace carries, so an edited edge is caught by the value comparison.
    assert "signals.numbers_match_the_trace" in report["failed"]


def test_a_demo_row_labelled_real_fails(tmp_path: Path, verifier: Any) -> None:
    run_dir = _run(tmp_path)

    def mutate(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        rows[0]["source"] = "REAL"
        return rows

    _rewrite(run_dir / "signals.jsonl", mutate)
    code, report = _verify(verifier, tmp_path, run_dir)
    assert code == verifier.EXIT_FAIL
    assert "signals.source_matches_the_provider" in report["failed"]


def test_analysis_for_an_unknown_signal_fails(tmp_path: Path, verifier: Any) -> None:
    run_dir = _run(tmp_path)
    (run_dir / "analysis.jsonl").write_text(
        json.dumps(
            {
                "analysis_id": "a" * 32,
                "signal_id": "does-not-exist",
                "run_id": run_dir.name,
                "decision_id": "nope",
                "status": "ANALYZED",
                "model": "m",
                "prompt_version": "v",
                "analysis_time_ms": 1,
                "claim": "invented",
                "_sequence": 1,
            }
        )
        + "\n",
        encoding="utf-8",
    )
    code, report = _verify(verifier, tmp_path, run_dir)
    assert code == verifier.EXIT_FAIL
    assert "analysis.references_existing_signals" in report["failed"]


def test_not_configured_analysis_passes_but_is_reported(tmp_path: Path, verifier: Any) -> None:
    run_dir = _run(tmp_path)
    sidecar = _load_sidecar()
    args = sidecar.parse_args(["--run-root", str(tmp_path / "autonomous-paper"), "--run-id", run_dir.name])
    sidecar.run_pass(args, run_dir, None)
    code, report = _verify(verifier, tmp_path, run_dir)
    assert code == verifier.EXIT_PASS, report["failed"]
    assert report["counts"]["analysis_by_status"] == {"NOT_CONFIGURED": 2}


def test_the_dashboard_is_checked_over_http(tmp_path: Path, verifier: Any) -> None:
    """The HTTP surface is verified against the files, not against itself."""
    import http.client
    import importlib.util as ilu
    import threading

    run_dir = _run(tmp_path)
    spec = ilu.spec_from_file_location(
        "dashboard_for_verify", REPO / "scripts" / "paper_lab_dashboard.py"
    )
    assert spec and spec.loader
    dashboard = ilu.module_from_spec(spec)
    spec.loader.exec_module(dashboard)
    args = dashboard.parse_args(
        [
            "--lab-root",
            str(tmp_path / "lab"),
            "--paper-root",
            str(tmp_path / "autonomous-paper"),
            "--run-id",
            run_dir.name,
        ]
    )
    server = dashboard.ThreadingHTTPServer(("127.0.0.1", 0), dashboard.make_handler(args))
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        url = f"http://127.0.0.1:{port}"
        out = tmp_path / "verify-http.json"
        code = verifier.main(
            [
                "--run-root",
                str(tmp_path / "autonomous-paper"),
                "--run-id",
                run_dir.name,
                "--dashboard-url",
                url,
                "--out",
                str(out),
            ]
        )
        report = json.loads(out.read_text(encoding="utf-8"))
        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
        conn.request("POST", "/api/analysis", body=b"{}")
        assert conn.getresponse().status == 405
        conn.close()
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
    assert code == verifier.EXIT_PASS, report["failed"]
    names = {check["name"] for check in report["checks"]}
    assert "dashboard/api/signals" in names
    assert "dashboard.signals_match_the_file" in names
    assert "dashboard.newest_signal_matches" in names
    assert "dashboard.refuses_mutation" in names


def test_missing_run_exits_2(tmp_path: Path, verifier: Any) -> None:
    code = verifier.main(["--run-root", str(tmp_path / "nothing-here")])
    assert code == verifier.EXIT_NO_RUN


def _load_sidecar() -> Any:
    spec = importlib.util.spec_from_file_location(
        "ai_signal_analyst_for_verify", REPO / "scripts" / "ai_signal_analyst.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["ai_signal_analyst_for_verify"] = module
    spec.loader.exec_module(module)
    return module
