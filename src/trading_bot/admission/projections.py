"""ADMISSION-FOUNDATION-01 — read-only projections for the frontend contract (§18).

Pure read/serialize functions over the registry, shadow ledger and asset
records. The frontend branch consumes these; no trading authority and no
mutation paths exist in this module.
"""

from __future__ import annotations

import json
import pathlib
from typing import Any

from .states import AdmissionState

#: Next gate per admission state (Strategy Lab "next gate" column).
NEXT_GATE: dict[str, str] = {
    AdmissionState.IDEA.value: "SPEC",
    AdmissionState.CANDIDATE.value: "SPEC",
    AdmissionState.SPECIFIED.value: "IMPLEMENT",
    AdmissionState.IMPLEMENTED.value: "TEST",
    AdmissionState.TESTED.value: "BACKTEST",
    AdmissionState.BACKTEST_PASS.value: "ROBUSTNESS",
    AdmissionState.ROBUSTNESS_PASS.value: "DISCOVERY",
    AdmissionState.DISCOVERY_PASS.value: "CONFIRMATION",
    AdmissionState.CONFIRMATION_BLOCKED.value: "CONFIRMATION (authority repair)",
    AdmissionState.CONFIRMATION_PASS.value: "HOLDOUT",
    AdmissionState.HOLDOUT_PASS.value: "SHADOW",
    AdmissionState.SHADOW_PASS.value: "PAPER_ELIGIBLE",
    AdmissionState.PAPER_ELIGIBLE.value: "PAPER_ACTIVATION",
    AdmissionState.PAPER_ACTIVE.value: "—",
    AdmissionState.LEGACY_PAPER_BASELINE.value: "retro-admission (optional)",
    AdmissionState.REJECTED.value: "—",
    AdmissionState.INSUFFICIENT_SAMPLE.value: "more data",
    AdmissionState.BLOCKED.value: "unblock via evidence",
    AdmissionState.RETIRED.value: "—",
}


def _load(path: pathlib.Path | None) -> Any:
    if path is None or not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def strategy_lab(registry_path: pathlib.Path | None) -> dict[str, Any]:
    """Strategy Lab projection (§18): one row per strategy version."""
    payload = _load(registry_path)
    if not payload:
        return {"available": False, "strategies": []}
    rows = []
    for r in payload.get("records", []):
        rows.append(
            {
                "strategy": r["strategy_id"],
                "version": r["version"],
                "status": r["admission_state"],
                "trades": r.get("trade_count"),
                "expectancy": r.get("net_expectancy"),
                "pf": r.get("net_profit_factor"),
                "dd": r.get("max_drawdown"),
                "next_gate": NEXT_GATE.get(r["admission_state"], "—"),
            }
        )
    return {"available": True, "registry_sha256": payload.get("registry_sha256"), "strategies": rows}


def asset_lab(assets: list[dict[str, Any]]) -> dict[str, Any]:
    """Asset Lab projection (§18)."""
    rows = [
        {
            "asset": a["asset_id"],
            "status": a["admission_state"],
            "liquidity": a["liquidity"],
            "diversification": a["opportunity_overlap"],
            "incremental_opportunity": a["incremental_opportunity"],
            "next_gate": "full AssetAdmission (future checkpoint)",
        }
        for a in assets
    ]
    return {"available": True, "assets": rows}


def shadow(ledger_path: pathlib.Path | None) -> dict[str, Any]:
    """Shadow projection (§18): risk reason + hypothetical result + badges."""
    payload = _load(ledger_path)
    if not payload:
        return {"available": False, "trades": [], "accounting": None}
    return {
        "available": True,
        "accounting": payload.get("accounting"),
        "trades": [
            {
                "risk_reason": t.get("risk_rejection_reason"),
                "outcome": t.get("outcome"),
                "net_pnl": t.get("net_pnl"),
                "excluded_from_paper": True,
            }
            for t in payload.get("trades", [])
        ],
    }
