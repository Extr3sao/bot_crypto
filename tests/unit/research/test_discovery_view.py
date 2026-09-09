"""Track G tests — read-only discovery/shadow/coverage projection."""

from __future__ import annotations

from typing import Any

from trading_bot.research.discovery_view import (
    build_coverage_rows,
    build_discovery_lab_view,
    build_legacy_matrix,
)
from trading_bot.shadow.router import ShadowCounters


def _report() -> dict[str, Any]:
    return {
        "batch": "DISCOVERY_BATCH_01",
        "dataset_fingerprint": "abc123",
        "preregistration": {
            "eval_spec_fingerprints": {"session_time": "f" * 64, "carry_funding": "e" * 64}
        },
        "cells": [
            {
                "category": "session_time",
                "asset": "BTC",
                "timeframe": "1h",
                "regime": "TRENDING",
                "status": "INSUFFICIENT_SAMPLE",
                "n_trades": 82,
                "reason": "below minimum",
                "spec_fingerprint": "f" * 64,
                "metrics": {"n": 82, "net_expectancy": -0.002, "profit_factor": 0.6},
            },
            {
                "category": "carry_funding",
                "asset": "BTC",
                "timeframe": "1h",
                "regime": "TRENDING",
                "status": "INSUFFICIENT_SAMPLE",
                "n_trades": 0,
                "reason": "n=0",
                "spec_fingerprint": "e" * 64,
                "metrics": {"n": 0, "cost_model": "x"},
            },
        ],
    }


def test_lab_view_marks_research_surface_and_no_promotion() -> None:
    view = build_discovery_lab_view(_report())
    assert view["surface"] == "RESEARCH"
    cats = {c["category"] for c in view["candidates"]}
    assert cats == {"session_time", "carry_funding"}
    for cand in view["candidates"]:
        assert cand["note"].startswith("RESEARCH ONLY")
        assert cand["totals"]["discovery_pass"] == 0


def test_lab_view_empty_report_is_insufficient_evidence() -> None:
    view = build_discovery_lab_view({"cells": [], "preregistration": {}})
    assert view["surface"] == "RESEARCH"
    assert view["candidates"][0]["status"] == "INSUFFICIENT_EVIDENCE"


def test_legacy_matrix_cells_evidence_backed() -> None:
    results = {
        "protocol_fingerprint": "d2f17f91",
        "cells": [
            {
                "strategy_id": "momentum",
                "asset": "BTC",
                "timeframe": "1h",
                "regime": "TRENDING",
                "status": "FAILED_CELL",
                "n_trades": 22,
                "reason": "failed gates: sharpe,significance",
                "metrics": {"net_expectancy": -0.001, "profit_factor": 0.7},
            }
        ],
    }
    view = build_legacy_matrix(results)
    assert view["surface"] == "RESEARCH"
    row = view["matrix"][0]
    assert row["strategy"] == "momentum"
    cell = row["cells"][0]
    assert cell["status"] == "FAILED_CELL"
    assert cell["profit_factor"] == 0.7


def test_legacy_matrix_empty_is_insufficient() -> None:
    view = build_legacy_matrix({"cells": []})
    assert view["matrix"][0]["status"] == "INSUFFICIENT_EVIDENCE"


def test_coverage_rows_project_paper_surface() -> None:
    rows = build_coverage_rows(
        [
            {
                "date": "2026-09-08",
                "status": "FINALIZED",
                "coverage_ratio": 0.717,
                "scans": 1,
                "proposals": 0,
                "risk_accepts": 0,
                "risk_rejects": 0,
                "paper_opens": 0,
                "trades": 0,
                "realized_pnl": 0.0,
            }
        ]
    )
    assert rows[0]["date"] == "2026-09-08"
    assert rows[0]["status"] == "FINALIZED"
    assert rows[0]["coverage_ratio"] == 0.717


def test_shadow_counters_surface() -> None:
    class _FakeHook:
        pass

    from trading_bot.shadow.integration import ShadowCaptureHook

    hook = ShadowCaptureHook(
        captures_path="unused/captures.jsonl", outcomes_path=None
    )
    counters = ShadowCounters(hook).snapshot()
    assert counters["captures_total"] == 0
    assert counters["paper_contamination"] == 0
