"""WP-016C — the admission decision, derived from the WP-016A/B artifacts.

The decision is not written by hand: it is computed from the audit and the
cycle evidence, so it can only say what those two files support.

* If the audit admits at least one strategy, the decision is
  ``ECONOMIC_CANDIDATE`` and the PAPER run with real market data is the next
  step. That branch is unreachable today, and the script says so instead of
  pretending to have tried it.
* If it admits none, the decision is ``ECONOMIC_BLOCKED`` and the script also
  derives the **single number that can change it**: the execution-cost budget
  of the best cell.

That budget is the useful part. The cheapest *assumed* maker line on the venue
family the runtime trades is 9.25 bps RT, of which 4.00 bps are **known**
exchange fees (2 + 2) and 5.25 bps are **assumed** execution costs (adverse
selection, missed fills, fill-probability inflation). Against a gross of
8.912 bps, a measured execution cost below **4.912 bps** would make the cell
net positive; anything at or above it closes the lane. One number, one
experiment, no criterion relaxed.

Usage:
    uv run python scripts/tdm16_decision.py \
        --out evidence/tdm/wp-tdm-16-paper-admission/ECONOMIC_DECISION.json
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
AUDIT = Path("evidence/tdm/wp-tdm-16-paper-admission/ADMISSION_AUDIT.json")
CYCLE = Path("evidence/tdm/wp-tdm-16-paper-admission/PAPER_CYCLE_EVIDENCE.json")
EXPLORER = Path("data/recovery/COST_BARRIER_EXPLORER.json")
LEDGER = Path("config/strategy_admission.json")
DECISION_SCHEMA_VERSION = "wp-tdm-16-economic-decision-v1"


def _load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _known_maker_fees_bps(explorer: dict[str, Any]) -> tuple[float, list[dict[str, Any]]]:
    """Known (published-fee) components of the futures-maker line, 200 USD deep."""
    for row in explorer.get("venue_grid") or []:
        if (
            str(row.get("scenario_id", "")) == "BINANCE_USDM_PERP_MAKER"
            and str(row.get("order_mode")) == "maker"
            and float(row.get("size_usd") or 0.0) == 200.0
            and str(row.get("liquidity_regime")) == "deep"
        ):
            components = list(row.get("components") or [])
            known = round(
                sum(
                    float(c.get("value_bps") or 0.0)
                    for c in components
                    if str(c.get("knowledge")) == "KNOWN"
                ),
                6,
            )
            return known, components
    return 0.0, []


def build_decision(repo_root: Path = REPO_ROOT) -> dict[str, Any]:
    audit = _load(repo_root / AUDIT)
    cycle = _load(repo_root / CYCLE)
    explorer = _load(repo_root / EXPLORER)
    ledger = _load(repo_root / LEDGER)

    admitted = list(audit["verdict"]["admitted_ids"])
    frontier = audit["frontier"]
    known_fees, components = _known_maker_fees_bps(explorer)
    assumed_cost = round(
        sum(
            float(c.get("value_bps") or 0.0)
            for c in components
            if str(c.get("knowledge")) != "KNOWN"
        ),
        6,
    )
    best_gross = float(frontier["max_gross_bps"])
    budget = round(best_gross - known_fees, 6)

    ledger_strategies = {
        k for k in (ledger.get("strategies") or {}) if not k.startswith("_")
    }

    decision: dict[str, Any] = {
        "artifact": "WP-TDM-016-C · PAPER admission decision",
        "schema_version": DECISION_SCHEMA_VERSION,
        "generated_by": "scripts/tdm16_decision.py",
        "decision": "ECONOMIC_CANDIDATE" if admitted else "ECONOMIC_BLOCKED",
        "admission": {
            "strategies_audited": len(ledger_strategies),
            "admitted": len(admitted),
            "admitted_ids": admitted,
            "pipeline_invoked": False,
            "pipeline_note": (
                "scripts/build_strategy_admission.py is the only authorised admission path; "
                "it recognises a paper candidate only when the pre-registered matrix lists the "
                "family AND its gross is positive. With paper_candidates empty there is nothing "
                "to admit, and editing the ledger by hand is refused at load time by design."
            ),
        },
        "paper_run_with_real_market_data": {
            "attempted": False,
            "orders": 0,
            "live_orders": 0,
            "reason": (
                "the PAPER_ORDER layer is BLOCKED by the empty admission ledger. Placing a "
                "PAPER order anyway would be forcing a trade through a control that exists to "
                "stop exactly that, so no order is placed and the layer keeps reporting BLOCKED."
            ),
            "what_still_runs": (
                "INGEST, SIGNALS and SHADOW: read-only market data, the decision projection and "
                "observations. They were exercised in WP-TDM-015-OPS and are independent of "
                "admission."
            ),
        },
        "mechanical_readiness": {
            "cycle_label": cycle.get("label"),
            "tests": len(cycle.get("tests") or []),
            "tests_failed": [t["name"] for t in (cycle.get("tests") or []) if t["outcome"] != "passed"],
            "checks_passed": (cycle.get("checks_total") or 0) - (cycle.get("checks_failed") or 0),
            "checks_total": cycle.get("checks_total"),
            "net_bps_of_the_fixture_cycle": (cycle.get("traces") or {}).get("cycle", {}).get("net_bps"),
            "conclusion": (
                "the order/fill/PnL/reconciliation cycle is mechanically ready (TEST_ONLY "
                "evidence). It is not the blocker: the economics are."
            ),
        },
        "economics": {
            "best_cell": frontier["max_gross_cell"],
            "best_gross_bps": best_gross,
            "cheapest_measured_rt_bps": frontier["cheapest_measured_rt_bps"],
            "assumed_futures_maker_rt_bps": frontier["assumed_futures_maker_rt_bps"],
            "known_fees_bps": known_fees,
            "assumed_execution_cost_bps": assumed_cost,
            "breakeven_execution_cost_bps": budget,
            "distance_to_measured_bps": frontier["distance_to_measured_bps"],
            "distance_to_assumed_futures_maker_bps": frontier[
                "distance_to_assumed_futures_maker_bps"
            ],
            "reading": (
                f"{frontier['max_gross_cell']} earns {best_gross:.3f} bps gross. Fees are "
                f"{known_fees:.3f} bps RT (known). The maker line therefore breaks even only if "
                f"measured execution cost stays below {budget:.3f} bps; the model currently "
                f"assumes {assumed_cost:.3f} bps for it, which is why the line reads "
                f"{frontier['assumed_futures_maker_rt_bps']:.3f} bps and kills the cell."
            ),
        },
        "next_experiment": {
            "id": "EXP-MAKER-LINE-001",
            "document": "evidence/tdm/wp-tdm-16-paper-admission/NEXT_EXPERIMENT.md",
            "question": (
                "is the measured maker execution cost (adverse selection + missed fills) below "
                f"{budget:.3f} bps for {frontier['max_gross_cell']} at 200 USD on deep USD-M "
                "perpetuals?"
            ),
            "threshold_bps": budget,
            "kill_switch": (
                "measured execution cost >= the threshold closes the intraday OHLCV lane for "
                "good; no further indicator search is funded on 5m/15m/30m/1h"
            ),
            "why_this_one": (
                "it is the only unmeasured component between the best cell and admission: the "
                "gross is measured, the fees are known, and the 5.25 bps of execution cost is "
                "assumed. Measuring it is the difference between an opinion and a number."
            ),
        },
        "not_claimed": [
            "profitability: no strategy has demonstrated a positive net edge",
            "that a PAPER order was placed with real market data: the gate is closed",
            "that the fixture cycle in WP-016B is evidence of returns (its label is TEST_ONLY)",
            "LIVE readiness: no live path is enabled and none was tested",
        ],
        "sources": {
            "admission_audit": {"path": AUDIT.as_posix(), "sha256": _sha256(repo_root / AUDIT)},
            "paper_cycle_evidence": {
                "path": CYCLE.as_posix(),
                "sha256": _sha256(repo_root / CYCLE),
            },
        },
    }
    return decision


def _sha256(path: Path) -> str:
    import hashlib

    return hashlib.sha256(path.read_bytes()).hexdigest()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--out",
        default="evidence/tdm/wp-tdm-16-paper-admission/ECONOMIC_DECISION.json",
    )
    args = parser.parse_args(argv)
    decision = build_decision()
    out = REPO_ROOT / args.out
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps(decision, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    print(
        f"wrote {args.out}: decision={decision['decision']} "
        f"admitted={decision['admission']['admitted']} "
        f"threshold={decision['economics']['breakeven_execution_cost_bps']:.3f} bps"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
