"""Read-only discovery/shadow/coverage projection (Track G).

ALPHA-DISCOVERY-AND-SHADOW-V2-01. Frontend-ready, STRICTLY READ-ONLY view
models that separate the three observational surfaces:

- RESEARCH: Discovery Batch 01 lab view + legacy validation matrix cells;
- SHADOW: capture/resolve counters (no paper surface);
- PAPER: POC01 daily coverage rows (observation layer only).

Every status comes from evidence; empty evidence renders as
``INSUFFICIENT_EVIDENCE`` / ``NOT_OBSERVED`` — never inferred from names.
No trading controls exist on this module.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from trading_bot.shadow.router import ShadowCounters

__all__ = [
    "DiscoveryCellView",
    "LegacyMatrixCell",
    "build_coverage_rows",
    "build_discovery_lab_view",
    "build_legacy_matrix",
]


def _no_evidence(reason: str) -> dict[str, Any]:
    return {"status": "INSUFFICIENT_EVIDENCE", "reason": reason}


class DiscoveryCellView:
    """One lab candidate summary row (RESEARCH surface)."""

    def __init__(self, category: str, cells: Iterable[Mapping[str, Any]]) -> None:
        self.category = category
        self._cells: list[dict[str, Any]] = [dict(c) for c in cells]

    def to_dict(self) -> dict[str, Any]:
        n_total = sum(int(c.get("n_trades", 0) or 0) for c in self._cells)
        passes = sum(1 for c in self._cells if c.get("status") == "DISCOVERY_PASS")
        fails = sum(1 for c in self._cells if c.get("status") == "DISCOVERY_FAIL")
        insufficient = sum(1 for c in self._cells if c.get("status") == "INSUFFICIENT_SAMPLE")
        not_applicable = sum(1 for c in self._cells if c.get("status") == "NOT_APPLICABLE")
        best_pf: float | None = None
        for c in self._cells:
            m = c.get("metrics") or {}
            pf = m.get("profit_factor")
            if isinstance(pf, (int, float)) and (best_pf is None or pf > best_pf):
                best_pf = float(pf)
        return {
            "category": self.category,
            "surface": "RESEARCH",
            "cells": self._cells,
            "totals": {
                "n_trades": n_total,
                "discovery_pass": passes,
                "discovery_fail": fails,
                "insufficient_sample": insufficient,
                "not_applicable": not_applicable,
                "best_observed_pf": best_pf,
            },
            "status": (
                "DISCOVERY_PASS" if passes else (
                    "EVIDENCE_NEGATIVE" if fails and not insufficient and not not_applicable else (
                        "INSUFFICIENT_SAMPLE" if insufficient or not_applicable else "INSUFFICIENT_EVIDENCE"
                    )
                )
            ),
            "note": "RESEARCH ONLY - no candidate may enter PAPER from this view",
        }


def build_discovery_lab_view(
    report: Mapping[str, Any],
) -> dict[str, Any]:
    """Compose the lab view from a DiscoveryReport ``to_dict`` payload."""
    by_category: dict[str, list[dict[str, Any]]] = {}
    for cell in report.get("cells", []):
        by_category.setdefault(str(cell.get("category")), []).append(dict(cell))
    categories = sorted(
        set(by_category) | set(report.get("preregistration", {}).get("eval_spec_fingerprints", {}))
    )
    if not categories:
        return {
            "surface": "RESEARCH",
            "candidates": [_no_evidence("no discovery cells recorded")],
            "preregistration": report.get("preregistration", {}),
        }
    return {
        "surface": "RESEARCH",
        "preregistration": report.get("preregistration", {}),
        "dataset_fingerprint": report.get("dataset_fingerprint"),
        "candidates": [
            DiscoveryCellView(cat, by_category.get(cat, [])).to_dict()
            for cat in categories
        ],
    }


class LegacyMatrixCell:
    """Evidence-backed legacy matrix cell (RESEARCH surface)."""

    def __init__(self, strategy: str, cell: Mapping[str, Any] | None, *, reason: str | None = None) -> None:
        self.strategy = strategy
        self._cell = dict(cell) if cell else None
        self._reason = reason

    def to_dict(self) -> dict[str, Any]:
        if self._cell is None:
            return {
                "strategy": self.strategy,
                "status": "INSUFFICIENT_EVIDENCE",
                "reason": self._reason or "no cell evidence recorded",
            }
        m = self._cell.get("metrics") or {}
        return {
            "strategy": self.strategy,
            "asset": self._cell.get("asset"),
            "timeframe": self._cell.get("timeframe"),
            "regime": self._cell.get("regime"),
            "status": self._cell.get("status"),
            "n_trades": self._cell.get("n_trades"),
            "net_expectancy": m.get("net_expectancy"),
            "profit_factor": m.get("profit_factor"),
            "reason": self._cell.get("reason"),
        }


def build_legacy_matrix(
    results: Mapping[str, Any],
) -> dict[str, Any]:
    """Matrix rows from ``LEGACY_RETRO_EXECUTION_RESULTS.json``-shaped data."""
    cells = results.get("cells") or []
    if not cells:
        return {
            "surface": "RESEARCH",
            "matrix": [_no_evidence("no legacy retro cells recorded")],
        }
    rows: dict[str, list[dict[str, Any]]] = {}
    for cell in cells:
        rows.setdefault(str(cell.get("strategy_id")), []).append(
            LegacyMatrixCell(str(cell.get("strategy_id")), cell).to_dict()
        )
    return {
        "surface": "RESEARCH",
        "protocol_fingerprint": results.get("protocol_fingerprint"),
        "matrix": [
            {"strategy": s, "cells": cs}
            for s, cs in sorted(rows.items())
        ],
    }


def build_coverage_rows(
    daily_table: Iterable[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """POC01 coverage rows (PAPER surface, observation layer only)."""
    out: list[dict[str, Any]] = []
    for row in daily_table:
        out.append(
            {
                "date": row.get("date"),
                "status": row.get("status"),
                "coverage_ratio": row.get("coverage_ratio"),
                "scans": row.get("scans"),
                "proposals": row.get("proposals"),
                "risk_accepts": row.get("risk_accepts"),
                "risk_rejects": row.get("risk_rejects"),
                "paper_opens": row.get("paper_opens"),
                "trades": row.get("trades"),
                "realized_pnl": row.get("realized_pnl"),
            }
        )
    return out


def shadow_counters_payload(hook_counters: ShadowCounters) -> dict[str, Any]:
    """SHADOW surface: counters only, no candidate detail, no controls."""
    snap = hook_counters.snapshot()
    return {
        "surface": "SHADOW",
        **snap,
        "note": "observational counters only; shadow never mutates PAPER",
    }
