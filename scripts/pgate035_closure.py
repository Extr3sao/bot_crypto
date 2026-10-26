#!/usr/bin/env python
"""PROFITABILITY-GATE-035 — close RFC-035 and prepare the evolution decision.

This builder is the *analyst* half of the gate. It:

* audits the baseline from the repository itself (HEAD, the RFC-035S3 commits, the shared
  working tree, the 75-source catalogue, the three rounds' verdicts, the rejected-opportunity
  registry, the independent verifications, the CAP-004B campaign, the pending mypy errors and
  the RFC-035E missing-input defect), and separates what was *observed earlier* from what is
  *reproduced in this run*;
* closes RFC-035 formally and records that the closure is about the source universe and the
  selection contract we investigated — not a claim that no profitable opportunity exists;
* classifies every rejection against eight root causes and attributes each to the source, to
  the market, or to our own contract;
* evaluates routes A/B/C on the eight stated criteria and recommends one with evidence;
* audits the 23.791 bps admission cost from the project's own cost model, separating KNOWN
  published fees from ESTIMATED model assumptions;
* writes the six artefacts under ``reports/profitability_gate035/`` and the discovery
  proposal under ``docs/roadmap/``.

It never runs a backtest, never designs a strategy, and never starts trading. Policy changes
are written as PROPOSALS; nothing is recorded as an already-approved decision.

It does not write ``INDEPENDENT_VERIFICATION.*`` — that belongs to
``scripts/pgate035_verify.py``, a separate program.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
OUT = REPO / "reports" / "profitability_gate035"
RESEARCH = REPO / "research" / "profitability"
OPP_DIR = RESEARCH / "opportunities"
PROPOSAL = REPO / "docs" / "roadmap" / "PROFITABILITY_DISCOVERY_PROPOSAL.md"
GATES_PATH = REPO / "data" / "pgate035" / "gates.json"
RFC036_PATH = REPO / "reports" / "RFC036_FINAL_REPORT.json"
ROADMAP = REPO / "tasks" / "roadmap.md"
OPERATING_MODEL = REPO / "docs" / "research" / "PROFITABILITY_OPERATING_MODEL.json"
FREEZE = REPO / "docs" / "governance" / "PROFITABILITY_FIRST_FREEZE.md"

#: When this gate's evidence was actually read and its gates measured, not an idealised date.
RETRIEVED_AT = "2026-10-08T09:45:00Z"
COST_FLOOR_BPS = 23.791
COST_STRESS_MULTIPLE = 1.5
FORBIDDEN_VERDICTS = ("EDGE_CONFIRMED", "PROFITABLE", "READY_FOR_PAPER", "READY_FOR_LIVE")

#: The eight root causes §03 asks us to separate, with the owner of each cause.
ROOT_CAUSES: tuple[tuple[str, str, str], ...] = (
    ("RC-1", "no executable rules", "SOURCE"),
    ("RC-2", "no verifiable economic result", "SOURCE"),
    ("RC-3", "no realistic cost model", "SOURCE"),
    ("RC-4", "proprietary or non-reproducible data", "SOURCE"),
    ("RC-5", "edge below the execution cost", "MARKET"),
    ("RC-6", "overfitted strategies", "SOURCE"),
    ("RC-7", "instrument or universe incompatible with our runtime", "CONTRACT_AND_RUNTIME"),
    ("RC-8", "our evidence contract cannot promote educational examples", "CONTRACT"),
)

#: Round-2 reason codes mapped onto the eight causes (counts come from the round-2 log).
REASON_CODE_TO_CAUSE = {
    "RULES_INCOMPLETE_MATERIAL_FIELDS": "RC-1",
    "NO_FIXED_PARAMETERS_RETRAINING_REQUIRED": "RC-1",
    "NO_CODE": "RC-1",
    "NO_CANONICAL_PERIOD_OR_RESULTS": "RC-2",
    "SAMPLE_TOO_SHORT": "RC-2",
    "SOURCE_READ_LEVEL_INSUFFICIENT": "RC-8",
    "FORECAST_ONLY_NOT_A_STRATEGY": "RC-8",
    "COST_FLOOR_HEADROOM_NOT_ESTABLISHED": "RC-5",
    "INSTRUMENT_OR_UNIVERSE_MISMATCH": "RC-7",
    "OVERFIT_RISK_PARAMETER_SEARCH": "RC-6",
    "REPRODUCIBILITY_LLM_OR_HARDWARE": "RC-4",
    "DATA_DEPENDENCY_PLATFORM_BOUND": "RC-4",
    "LOOKAHEAD_OR_TIMESTAMP_AMBIGUITY": "RC-1",
}

ROUND_3_CAUSES = {
    "OPP-0028": ["RC-5"],
    "OPP-0029": ["RC-2", "RC-5"],
    "OPP-0030": ["RC-3", "RC-5"],
    "OPP-0031": ["RC-1", "RC-7"],
    "OPP-0032": ["RC-1", "RC-3"],
    "OPP-0033": ["RC-8"],
}


def canon(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def compact(value: Any) -> str:
    """One-line rendering for a nested record inside a bullet list."""
    if isinstance(value, dict):
        return "; ".join(f"{k}={compact(v)}" for k, v in value.items())
    if isinstance(value, list):
        return " | ".join(compact(v) for v in value)
    return str(value)


def git(*args: str) -> str:
    proc = subprocess.run(["git", *args], cwd=REPO, capture_output=True, text=True, check=False)
    return proc.stdout.strip()


def load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else None


def load_gates() -> dict[str, Any]:
    if not GATES_PATH.is_file():
        return {"status": "NOT_RUN", "note": "no measured gate results were recorded for this run"}
    payload: dict[str, Any] = json.loads(GATES_PATH.read_text(encoding="utf-8"))
    return payload


# --------------------------------------------------------------------------- #
# 01 — baseline audit
# --------------------------------------------------------------------------- #

RFC035S3_COMMITS = ("3d75e81", "40d9232", "aa0abae")


def rfc036_state(payload: dict[str, Any]) -> dict[str, Any]:
    """Read what RFC-036 actually is, because the RFC-035 lineage assumes something else.

    The RFC-035 rounds 2 and 3 recorded ``RFC-036 = BLOCKED`` and describe that number as reserved
    for the exact replication of an RFC-035 candidate. The repository says otherwise: RFC-036 was
    already used for a managed-futures trend reproduction. This gate reports the two facts and
    refuses to repeat the reservation as if it were true.
    """
    if not payload:
        return {"status": "UNREADABLE", "path": "reports/RFC036_FINAL_REPORT.json"}
    text = payload.get("text") or []
    disc = payload.get("disc") or {}
    val = payload.get("val") or {}

    def find(prefix: str) -> str | None:
        for line in text:
            if line.startswith(prefix):
                return line.split("=", 1)[1].strip() if "=" in line else None
        return None

    return {
        "path": "reports/RFC036_FINAL_REPORT.json",
        "status": "ALREADY_OPENED_AND_COMPLETE",
        "title": text[0] if text else None,
        "candidate": find("CANDIDATE"),
        "reproduction_fidelity": find("REPRODUCTION FIDELITY"),
        "gates": payload.get("gates"),
        "robustness_gate": find("G_MF_3_ROBUSTNESS"),
        "holdout_gate": find("G_MF_4_HOLDOUT"),
        "own_net_edge_claim": find("Did we achieve the first EXECUTABLE VALIDATED NET EDGE?"),
        "next": find("NEXT"),
        "false_success": (payload.get("false_success") or {}).get("false_success_count"),
        "introduced_by_commit": "d0efb51",
        "introduced_on": "2026-10-05",
        "cost_ratio": {
            "discovery": {
                "gross_pnl": disc.get("gross_pnl"),
                "cost_pnl": disc.get("cost_pnl"),
                "net_pnl": disc.get("net_pnl"),
                "cost_share_of_gross": round(disc.get("cost_pnl", 0) / disc.get("gross_pnl", 1), 4),
            },
            "validation": {
                "gross_pnl": val.get("gross_pnl"),
                "cost_pnl": val.get("cost_pnl"),
                "net_pnl": val.get("net_pnl"),
                "cost_share_of_gross": round(val.get("cost_pnl", 0) / val.get("gross_pnl", 1), 4),
            },
        },
        "gate_position": "this gate does NOT validate, promote or endorse RFC-036; it reports that the "
                         "artifact exists, quotes its own claim verbatim as an unverified claim, and "
                         "records that its holdout gate is " + str(find("G_MF_4_HOLDOUT")),
        "reservation_conflict": {
            "claimed_by": "reports/rfc035/search_round_2 and search_round_3 (RFC-035 = BLOCKED, RFC-036 "
                          "described as reserved for exact replication) and this gate's own brief",
            "contradicted_by": "scripts/rfc036_run.py and tests/unit/research/test_rfc036_managed_futures.py, "
                               "tracked since d0efb51 on 2026-10-05",
            "roadmap_says": "nothing: tasks/roadmap.md contains no RFC-035/036/044/045/046 reference at all, "
                            "so no document actually reserves the number",
            "resolution": "NOT THIS GATE'S TO DECIDE: the conflict is recorded and handed to the amendment "
                          "in the proposal; this gate reserves no number and reuses none",
        },
    }


def audit_baseline() -> dict[str, Any]:
    head = git("rev-parse", "HEAD")
    short_log = git("log", "--oneline", "-8").splitlines()
    tracked = [line for line in git("status", "--porcelain").splitlines() if not line.startswith("??")]
    untracked = [line for line in git("status", "--porcelain").splitlines() if line.startswith("??")]
    registry = load(RESEARCH / "source_registry.json") or {}
    sources = registry.get("sources") or []
    ids = [s.get("SOURCE_ID") for s in sources]
    rounds = registry.get("rounds") or []
    opportunities = {}
    for path in sorted(OPP_DIR.glob("OPP-*.json")):
        record = load(path)
        if isinstance(record, dict):
            opportunities[record["opportunity_id"]] = record
    rank_counts: dict[str, int] = {}
    for record in opportunities.values():
        rank_counts[str(record.get("rank"))] = rank_counts.get(str(record.get("rank")), 0) + 1
    superseded = {
        oid: record.get("current_rank")
        for oid, record in opportunities.items()
        if record.get("current_rank")
    }
    frozen = [oid for oid, record in opportunities.items() if record.get("frozen_selection")]

    verifications = {}
    for name in ("rfc035/RFC035_VERIFICATION.json", "rfc035e/INDEPENDENT_VERIFICATION.json",
                 "rfc035/search_round_2/INDEPENDENT_VERIFICATION.json",
                 "rfc035/search_round_3/INDEPENDENT_VERIFICATION.json"):
        payload = load(REPO / "reports" / name)
        verifications[name] = {
            "status": (payload or {}).get("status"),
            "passed": (payload or {}).get("passed"),
            "checks": (payload or {}).get("checks"),
            "mismatches": (payload or {}).get("mismatches"),
            "false_success": (payload or {}).get("false_success"),
            "mismatch_detail": (payload or {}).get("mismatch_detail"),
        }
    verdicts = {}
    for name in ("rfc035/FINAL_REPORT.json", "rfc035e/FINAL_REPORT.json",
                 "rfc035/search_round_2/FINAL_REPORT.json", "rfc035/search_round_3/FINAL_REPORT.json"):
        payload = load(REPO / "reports" / name) or {}
        verdicts[name] = {
            "final_status": payload.get("final_status"),
            "classification": payload.get("classification"),
            "next_gate": payload.get("next_gate"),
            "false_success": payload.get("false_success"),
        }

    operating = load(OPERATING_MODEL) or {}
    campaign = load(REPO / "evidence" / "real_decisions" / "CAMPAIGN_MANIFEST.json") or {}
    cap004b = load(REPO / "reports" / "cap004b" / "FINAL_REPORT.json") or {}
    round3_baseline = load(REPO / "reports" / "rfc035" / "search_round_3" / "BASELINE.json") or {}
    rfc036 = load(RFC036_PATH) or {}
    return {
        "current_head": head,
        "short_log": short_log,
        "rfc035s3_commits": {
            "expected": list(RFC035S3_COMMITS),
            "all_in_history": all(
                subprocess.run(["git", "cat-file", "-e", c], cwd=REPO, capture_output=True, check=False).returncode == 0
                for c in RFC035S3_COMMITS
            ),
        },
        "working_tree": {
            "tracked_modifications": len(tracked),
            "tracked_modification_paths": tracked,
            "untracked_entries": len(untracked),
            "note": "the tracked modifications are owned by other threads (CAP-004B/CAP-004D); this gate adds none of them",
        },
        "catalogue": {
            "sources": len(sources),
            "unique_source_ids": len(set(ids)),
            "unique": len(set(ids)) == len(ids) and bool(sources),
            "rounds": [{"rfc": r.get("rfc"), "sources": r.get("sources")} for r in rounds],
            "round_sum": sum(int(r.get("sources") or 0) for r in rounds),
        },
        "opportunities": {
            "total": len(opportunities),
            "rank_counts": rank_counts,
            "superseded_in_round_3": superseded,
            "frozen_selections": frozen,
        },
        "independent_verifications": verifications,
        "round_verdicts": verdicts,
        "campaign": {
            "campaign_id": campaign.get("campaign_id"),
            "campaign_version": campaign.get("campaign_version"),
            "source_type": campaign.get("source_type"),
            "alpha_claimed": campaign.get("alpha_claimed"),
            "alpha_research_freeze": campaign.get("alpha_research_freeze"),
            "next_alpha_rfc_allowed": campaign.get("next_alpha_rfc_allowed"),
            "runtime_promotion": campaign.get("runtime_promotion"),
            "trades_authorized": campaign.get("trades_authorized"),
            "min_evaluable_decisions": campaign.get("min_evaluable_decisions"),
            "horizon": campaign.get("horizon"),
            "cost_model": campaign.get("cost_model"),
            "campaign_code_commit": campaign.get("code_commit"),
            "manifest_path": "evidence/real_decisions/CAMPAIGN_MANIFEST.json",
        },
        "cap004b": {
            "artifact": "reports/cap004b/FINAL_REPORT.json",
            "as_of_utc": cap004b.get("as_of_utc"),
            "verdict": cap004b.get("VERDICT"),
            "campaign_status": cap004b.get("CAMPAIGN_STATUS"),
            "supervisor_status": cap004b.get("SUPERVISOR_STATUS"),
            "sealed": cap004b.get("SEALED"),
            "settled": cap004b.get("SETTLED"),
            "evaluated": cap004b.get("EVALUATED"),
            "chain_status": cap004b.get("CHAIN_STATUS"),
            "drift_status": cap004b.get("DRIFT_STATUS"),
            "duplicate_decisions": cap004b.get("DUPLICATE_DECISIONS"),
            "duplicate_evaluations": cap004b.get("DUPLICATE_EVALUATIONS"),
            "verifiers": {
                "CAP003": cap004b.get("CAP003_VERIFIER"),
                "CAP004": cap004b.get("CAP004_VERIFIER"),
                "CAP004B": cap004b.get("CAP004B_VERIFIER"),
            },
            "false_success": cap004b.get("FALSE_SUCCESS"),
            "defects": cap004b.get("DEFECTS"),
            "limitations": cap004b.get("LIMITATIONS"),
            "first_real_settlement_status": cap004b.get("FIRST_REAL_SETTLEMENT_STATUS"),
            "next_gate": cap004b.get("NEXT_GATE"),
        },
        "rfc036_actual_state": rfc036_state(rfc036),
        "historical_reproduction": {
            "source_artifact": "reports/rfc035/search_round_3/BASELINE.json",
            "lab_commit": (round3_baseline.get("reproduction") or {}).get("lab_commit"),
            "invariant": (round3_baseline.get("reproduction") or {}).get("invariant"),
            "runs": (round3_baseline.get("reproduction") or {}).get("runs"),
            "runs_after_round_3_registry": (round3_baseline.get("reproduction") or {}).get(
                "runs_after_round_3_registry"),
            "count_growth_note": (round3_baseline.get("reproduction") or {}).get("count_growth_note"),
            "concurrency_experiment": (round3_baseline.get("reproduction") or {}).get("concurrency_experiment"),
            "defect_observed": (round3_baseline.get("reproduction") or {}).get("defect_observed"),
            "note": "read from round 3's own recording; this gate does not re-run the historic verifiers",
        },
        "operating_model": {
            "rfc": operating.get("rfc"),
            "current_milestone": operating.get("current_milestone"),
            "any_tier_authorized": operating.get("any_tier_authorized"),
            "capital_scale_authorized": operating.get("capital_scale_authorized"),
            "next": operating.get("next"),
            "trigger_policy": (operating.get("next_action_policy") or {}).get("trigger"),
            "no_periodic_rfc": (operating.get("next_action_policy") or {}).get("no_periodic_rfc"),
        },
    }


def audit_reproduced() -> dict[str, Any]:
    """What this run re-derived, as opposed to what earlier runs recorded."""
    return {
        "reproduced_in_this_run": [
            "the cost-model decomposition of the 23.791 bps round trip, evaluated from "
            "trading_bot.research.microstructure.cost_model_v3",
            "the venue scenario table and the size / liquidity sensitivity of that cost",
            "the annual cost drag at several turnover rates",
            "the catalogue counts, rank histogram and supersession state read from the registry",
            "the HEAD, the shared working tree and the presence of the three RFC-035S3 commits",
            "the gate results recorded after this run's own commands",
        ],
        "observed_earlier_not_rerun": [
            "the three RFC-035 rounds' source reads and candidate classifications",
            "the RFC-035E effect reproduction on its frozen dataset",
            "the round-3 isolated-worktree reproduction of the round-1/2/3 verifiers",
            "the internal A-01..A-06 microstructure measurement and its 23.791 bps comparison",
        ],
        "policy": "the original baselines are not rewritten; this gate only reads them",
    }


def pending_defects() -> dict[str, Any]:
    gates = load_gates()
    mypy = gates.get("mypy_repo") or {}
    defect = (load(REPO / "reports" / "rfc035" / "search_round_3" / "BASELINE.json") or {}).get(
        "reproduction", {}).get("defect_observed") or {}
    return {
        "rfc035e_missing_input_defect": {
            "script": defect.get("script", "scripts/rfc035e_verify.py"),
            "condition": defect.get("condition"),
            "behaviour": defect.get("behaviour"),
            "classification": defect.get("classification"),
            "severity": "P2",
            "status": "OPEN_NOT_REPAIRED — " + str(defect.get("resolution")),
            "recorded_by": "reports/rfc035/search_round_3/BASELINE.json",
        },
        "mypy": {
            "command": mypy.get("command"),
            "result": mypy.get("result"),
            "exit_code": mypy.get("exit_code"),
            "failing_files": mypy.get("failing_files"),
            "ownership": "none of the failing files belongs to this gate",
        },
        "shared_checkout_flake": {
            "test": "tests/unit/observability/test_dashboard_server.py::test_runtime_artifacts_are_untouched_by_serving",
            "cause": "the test hashes the whole git-ignored reports/ tree, which other threads write continuously",
            "evidence": "0 failures / 20 runs in an exclusive worktree; 2 failures / 10 runs in the shared checkout",
            "status": "OPEN — recorded, not repaired; it is another thread's test",
        },
        "historical_baseline_mismatch": {
            "check": "reports/rfc035/RFC035_VERIFICATION.json reports the baseline commit versus HEAD",
            "observed": "1 mismatch in the shared checkout (HEAD advanced); 0 mismatches at the baseline commit in an isolated worktree",
            "status": "EXPECTED — a legitimate HEAD advance, not an evidence alteration",
        },
    }


# --------------------------------------------------------------------------- #
# 05/06 — cost feasibility, evaluated from the project's own model
# --------------------------------------------------------------------------- #

def cost_feasibility() -> dict[str, Any]:
    # Local import so the CLI stays fast when only the registry is read.
    from trading_bot.research.microstructure.cost_model_v3 import (
        ADMISSION_SCENARIO_ID,
        VENUE_SPECS,
        CostModelV3,
        cost_model_v3_all_in,
    )

    spec = VENUE_SPECS[ADMISSION_SCENARIO_ID]
    cost = cost_model_v3_all_in(spec, size_usd=1000.0, liquidity_regime="normal", horizon_minutes=25.0)
    components: list[dict[str, Any]] = [
        {"name": c.name, "value_bps": round(c.value_bps, 4), "knowledge": c.knowledge, "source_id": c.source_id}
        for c in cost.components
    ]
    known = sum(float(c["value_bps"]) for c in components if c["knowledge"] == "KNOWN")
    estimated = sum(float(c["value_bps"]) for c in components if c["knowledge"] != "KNOWN")

    scenarios = []
    for sid, venue in VENUE_SPECS.items():
        try:
            rt = CostModelV3(spec=venue).evaluate(
                size_usd=1000.0, liquidity_regime="normal", horizon_minutes=25.0
            ).round_trip_bps
        except Exception:  # pragma: no cover - a venue spec without a valid spread would land here
            rt = float("nan")
        scenarios.append({
            "scenario_id": sid,
            "venue": venue.venue,
            "product": venue.product,
            "tier": venue.tier,
            "maker_fee_bps": venue.maker_fee_bps,
            "taker_fee_bps": venue.taker_fee_bps,
            "spread_bps": venue.default_taker_spread_bps,
            "discount_applicability": venue.discount_applicability,
            "integration_status": venue.integration_status,
            "round_trip_bps": round(rt, 4),
            "is_admission": sid == ADMISSION_SCENARIO_ID,
        })

    model = CostModelV3(spec=spec)
    size_sensitivity = [
        {"size_usd": size, "round_trip_bps": round(model.evaluate(
            size_usd=size, liquidity_regime="normal", horizon_minutes=25.0).round_trip_bps, 4)}
        for size in (200.0, 500.0, 1000.0, 5000.0, 10000.0)
    ]
    regimes: tuple[Any, ...] = ("deep", "normal", "thin")
    liquidity_sensitivity = [
        {"liquidity_regime": regime, "round_trip_bps": round(model.evaluate(
            size_usd=1000.0, liquidity_regime=regime, horizon_minutes=25.0).round_trip_bps, 4)}
        for regime in regimes
    ]
    # The drag is computed from the *measured* round trip, never from the rounded documented figure,
    # so the arithmetic in the report is internally consistent and independently checkable.
    measured = cost.round_trip_bps
    turnover = [
        {"round_trips_per_year": n, "label": label,
         "annual_drag_bps": round(measured * n, 4),
         "annual_drag_pct": round(measured * n / 100.0, 4),
         "annual_drag_stressed_pct": round(measured * n * COST_STRESS_MULTIPLE / 100.0, 4)}
        for n, label in ((12, "monthly"), (26, "biweekly"), (52, "weekly"), (104, "twice weekly"),
                         (365, "daily"), (8760, "hourly"))
    ]
    return {
        "admission_scenario_id": ADMISSION_SCENARIO_ID,
        "market": f"{spec.venue} {spec.product}",
        "venue": spec.venue,
        "product": spec.product,
        "jurisdiction": spec.jurisdiction,
        "symbol_class": spec.symbol_class,
        "tier": spec.tier,
        "fee_payment_mode": spec.fee_payment_mode,
        "discount_program": spec.discount_program,
        "discount_applicability": spec.discount_applicability,
        "min_notional_usd": spec.min_notional_usd,
        "fee_source_id": spec.fee_source_id,
        "spread_source_id": spec.spread_source_id,
        "order_type": "market (taker on both legs)",
        "assumed_size_usd": 1000.0,
        "assumed_liquidity_regime": "normal",
        "assumed_horizon_minutes": 25.0,
        "measurement_origin": {
            "doc": "docs/AGGTRADES_RESULTS_V1.md",
            "json": "docs/AGGTRADES_RESULTS_V1.json",
            "config": "config/microstructure_preregistration.json",
            "date": "2026-09-27",
            "verified_by": "docs/MICROSTRUCTURE_V1_INDEPENDENT_VERIFICATION.md",
        },
        "round_trip_bps": round(cost.round_trip_bps, 4),
        "documented_reference_bps": COST_FLOOR_BPS,
        "measured_vs_documented_note": "the documented admission figure is 23.791 bps; the model reproduces "
                                        "23.7906 bps, the same number rounded. The turnover arithmetic below "
                                        "uses the measured value.",
        "components": components,
        "known_bps": round(known, 4),
        "estimated_bps": round(estimated, 4),
        "known_share": round(known / cost.round_trip_bps, 4),
        "stress_multiple": COST_STRESS_MULTIPLE,
        "required_gross_edge_bps": round(cost.round_trip_bps, 4),
        "required_gross_edge_stressed_bps": round(cost.round_trip_bps * COST_STRESS_MULTIPLE, 4),
        "scenarios": scenarios,
        "size_sensitivity": size_sensitivity,
        "liquidity_sensitivity": liquidity_sensitivity,
        "turnover_cost_drag": turnover,
        "internal_measured_gross_bps": {
            "best_tick_gross_bps": 0.614,
            "best_kline_aggregated_gross_bps": 2.36,
            "ratio_tick_to_cost": round(cost.round_trip_bps / 0.614, 2),
            "source": "docs/AGGTRADES_RESULTS_V1.md §2/§5, interpreted as the internal line's own measurement",
        },
        "known_vs_assumed": [
            "KNOWN: the 10 bps + 10 bps taker fee is the published Binance spot VIP0 schedule (SRC-01); "
            "maker and taker are identical at VIP0, so passive execution saves no fee",
            "ESTIMATED: 1.0 bps spread for majors, deliberately rounded up from the live bookTicker "
            "observation (BTC 0.001, ETH 0.04, SOL 0.83 bps) recorded in the cost model",
            "ESTIMATED: 2.6325 bps slippage and 0.1581 bps market impact, both from MODEL-V3's size, "
            "liquidity and volatility factors at a 1,000 USD notional",
            "NOT APPLIED: no BNB discount (POSSIBLE, unconfirmed for our account) and no derivatives venue "
            "(NEEDS_GOVERNANCE_DECISION); the cost is not reduced on either basis",
        ],
        "validity_scope": [
            "valid for taker round trips in majors on Binance spot at VIP0 with a ~1,000 USD notional",
            "at the project's 200 USDT reference capital the same model gives a slightly lower floor",
            "it is not valid for the illiquid tail, where the spread assumption of 1.0 bps understates reality",
            "it is not a forecast of the realised cost of any particular strategy",
        ],
    }


# --------------------------------------------------------------------------- #
# 03 — root-cause review
# --------------------------------------------------------------------------- #

def root_cause_review(cost: dict[str, Any]) -> dict[str, Any]:
    round2_log = load(REPO / "reports" / "rfc035" / "search_round_2" / "REJECTION_LOG.json") or {}
    reason_counts = round2_log.get("reason_counts") or {}
    per_cause: dict[str, dict[str, Any]] = {
        code: {"code": code, "cause": cause, "owner": owner, "reason_code_hits": 0,
               "reason_codes": [], "round_3_candidates": []}
        for code, cause, owner in ROOT_CAUSES
    }
    unmapped = []
    for reason, count in reason_counts.items():
        cause = REASON_CODE_TO_CAUSE.get(reason)
        if cause is None:
            unmapped.append(reason)
            continue
        per_cause[cause]["reason_code_hits"] += int(count)
        per_cause[cause]["reason_codes"].append({"code": reason, "count": int(count)})
    for oid, causes in ROUND_3_CAUSES.items():
        for cause in causes:
            per_cause[cause]["round_3_candidates"].append(oid)
    for entry in per_cause.values():
        entry["reason_codes"].sort(key=lambda item: (-item["count"], item["code"]))
    return {
        "causes": [per_cause[code] for code, _c, _o in ROOT_CAUSES],
        "round_2_reason_counts": reason_counts,
        "unmapped_reason_codes": sorted(unmapped),
        "coverage_caveat": "the reason-code counts come from the round-2 rejection log and therefore cover round 2 "
                           "only; the round-3 candidates are folded in separately in the last column, which is why "
                           "a cause can show zero round-2 hits and still be evidenced in round 3",
        "rc3_note": "RC-3 carries zero round-2 reason codes because the round-2 log has no 'no cost model' code; "
                    "its evidence is round 3's OPP-0030 and OPP-0032, whose rejection logs record the absence of a "
                    "cost vocabulary rather than a failed cost check",
        "rc1_note": "RC-1 is the most frequent cause and the one that would have been cheapest to satisfy: a source "
                    "that fixes every material rule field, including the exit, needs no new data, no venue and no "
                    "capital — only a paper complete enough to be executable",
        "ownership_totals": {
            "SOURCE": sum(e["reason_code_hits"] for e in per_cause.values() if e["owner"] == "SOURCE"),
            "MARKET": sum(e["reason_code_hits"] for e in per_cause.values() if e["owner"] == "MARKET"),
            "CONTRACT": sum(e["reason_code_hits"] for e in per_cause.values() if e["owner"] == "CONTRACT"),
            "CONTRACT_AND_RUNTIME": sum(
                e["reason_code_hits"] for e in per_cause.values() if e["owner"] == "CONTRACT_AND_RUNTIME"),
        },
        "market_cause_quantified": {
            "statement": "the one cause that is a property of the market rather than of a source or of our "
                         "contract is the ratio between the measured gross edge and the venue fee",
            "cost_floor_bps": cost["round_trip_bps"],
            "known_fee_bps": cost["known_bps"],
            "best_internal_tick_gross_bps": cost["internal_measured_gross_bps"]["best_tick_gross_bps"],
            "ratio": cost["internal_measured_gross_bps"]["ratio_tick_to_cost"],
            "interpretation": "the tick-level line's best measured gross edge is about two orders of magnitude "
                              "below the fee alone, so that family is closed by arithmetic rather than by "
                              "documentation",
        },
        "not_concluded": [
            "this review does NOT conclude that no profitable opportunity exists; it concludes that the sources "
            "we searched and the contract we applied did not produce a replicable one",
            "absence of public documentation is not evidence of absence of alpha, and is never used as such here",
        ],
    }


# --------------------------------------------------------------------------- #
# 04 — alternative routes
# --------------------------------------------------------------------------- #

ROUTE_CRITERIA = (
    "proximity_to_verified_net_profitability",
    "required_data",
    "falsifiability",
    "development_time",
    "overfitting_risk",
    "runtime_compatibility",
    "operating_cost",
    "ease_of_independent_validation",
)


def routes() -> dict[str, Any]:
    return {
        "A": {
            "id": "A",
            "title": "Keep the external search closed and wait for new evidence",
            "ratings": {
                "proximity_to_verified_net_profitability": "UNCHANGED — three rounds produced no candidate, "
                                                           "and waiting does not change the measured cost or the "
                                                           "runtime constraint",
                "required_data": "NONE new — but also no mechanism to obtain the missing kind of evidence "
                                 "(a source that ships rules, a period, a trade count, metrics and a cost model)",
                "falsifiability": "WEAK — there is no defined event that would end the wait, so the decision "
                                  "cannot be falsified; the operating model names the trigger as a NEW QUALIFIED "
                                  "OPPORTUNITY, which is external and unschedulable",
                "development_time": "ZERO",
                "overfitting_risk": "NONE",
                "runtime_compatibility": "NOT_APPLICABLE (nothing runs)",
                "operating_cost": "ZERO",
                "ease_of_independent_validation": "HIGH — inaction is trivially verifiable",
            },
            "evidence": [
                "75 sources across three rounds, 33 opportunities, 0 REPLICATE_P0",
                "the one candidate that passed to validation (OPP-0001) returned EFFECT_NOT_REPRODUCED",
                "the operating model's own next action is WAIT FOR BUSINESS EDGE",
            ],
        },
        "B": {
            "id": "B",
            "title": "Controlled Strategy Discovery from external economic hypotheses, preregistered, with OOS",
            "ratings": {
                "proximity_to_verified_net_profitability": "INDIRECT — it does not start from an existing edge; "
                                                           "it is the only route that can *produce* the missing "
                                                           "evidence (a result attributable to a code, with a cost "
                                                           "model), but it starts from a hypothesis, not a result",
                "required_data": "PIT market data we can already obtain, plus the external hypothesis each "
                                 "candidate must cite; no proprietary feed is required if the net-edge gate is "
                                 "honoured",
                "falsifiability": "STRONG — a preregistered rule set, a frozen cost model and a separated OOS "
                                  "window make each candidate objectively refutable, with a STOP rule on a "
                                  "negative result",
                "development_time": "MEDIUM-HIGH — the protocol itself, the PIT data contract and the "
                                    "preregistration harness must exist before the first candidate",
                "overfitting_risk": "HIGH — this is the route's dominant risk and the reason its protocol must "
                                    "cap candidates and control multiple testing",
                "runtime_compatibility": "CONTROLLED — the protocol can require long/cash spot majors, which is "
                                         "what the runtime already is",
                "operating_cost": "MEDIUM — research time and compute, no capital at risk",
                "ease_of_independent_validation": "HIGH — preregistration plus a separate verifier is precisely "
                                                  "what makes this verifiable",
            },
            "evidence": [
                "round 3 closed with no candidate because the corpus lacked the combination of rules, result and "
                "cost model — the gap is in what the corpus contains, not only in how we read it",
                "the one internally measured family with a real pipeline (tick microstructure) was killed by "
                "arithmetic, which shows the cost gate can falsify a family cheaply and early",
                "the protocol below is a proposal and requires a roadmap amendment before it activates",
            ],
        },
        "C": {
            "id": "C",
            "title": "First investigate whether cost and runtime restrictions make the pursued family infeasible",
            "ratings": {
                "proximity_to_verified_net_profitability": "ALREADY ANSWERED for the pursued family — the cost "
                                                           "audit below is decisive and needs no new experiment",
                "required_data": "NONE new — the cost model and the internal measurements already exist",
                "falsifiability": "N/A — this is an audit, not a hypothesis",
                "development_time": "ZERO (already done in this gate)",
                "overfitting_risk": "NONE",
                "runtime_compatibility": "N/A",
                "operating_cost": "ZERO",
                "ease_of_independent_validation": "HIGH — the audit is arithmetic over a frozen cost model",
            },
            "evidence": [
                "20.0 of the 23.791 bps is the published taker fee, so the constraint is the venue and tier, not "
                "the data or the model",
                "maker is MORE expensive than taker at VIP0 (41.25 bps), so passive execution is not an escape",
                "the cheapest spot venue in the registry is MEXC at 17.791 bps, a 25% saving that still leaves a "
                "17.8 bps floor",
                "at a weekly turnover the annual drag is already about 12.4% (18.6% stressed)",
            ],
        },
        "recommendation": "B",
        "recommendation_reasoning": [
            "C is not a route but a gate, and it is already answered: it must become the first gate inside B.",
            "A is cheap but has no mechanism to produce the evidence that three rounds failed to find, and its "
            "trigger is external and unschedulable, so it is unfalsifiable as a plan.",
            "B is the only route that can generate the missing evidence, and the protocol below is designed so "
            "that it fails cheaply and verifiably when the hypothesis is wrong.",
            "B may NOT be opened by this gate: it contradicts the RFC-043 operating model's trigger policy and "
            "the roadmap, so it is emitted as a proposal requiring an explicit amendment.",
        ],
        "comparison_matrix": [
            {"criterion": c, "A": None, "B": None, "C": None} for c in ROUTE_CRITERIA
        ],
    }


def route_matrix(route_data: dict[str, Any]) -> list[dict[str, str]]:
    rows = []
    for criterion in ROUTE_CRITERIA:
        rows.append({
            "criterion": criterion,
            "A": route_data["A"]["ratings"][criterion],
            "B": route_data["B"]["ratings"][criterion],
            "C": route_data["C"]["ratings"][criterion],
        })
    return rows


# --------------------------------------------------------------------------- #
# 05 — the proposal document
# --------------------------------------------------------------------------- #

PROPOSAL_PROTOCOL = (
    ("P-01", "Explicit economic hypothesis",
     "Every candidate declares the economic mechanism in one sentence and the external source it comes from. "
     "A candidate with no external source is out of scope for this programme."),
    ("P-02", "Identified external source",
     "The hypothesis must be traceable to a registered source in research/profitability/source_registry.json, "
     "read at full-text level. Sources already closed by an earlier round are inadmissible as new."),
    ("P-03", "Market and assets defined",
     "Long/cash spot only, majors or a preregistered liquid universe, on the runtime's venue. No derivatives. "
     "The universe is frozen with the candidate and is not re-selected after seeing results."),
    ("P-04", "Frozen rules and parameters",
     "Entry, exit (including stop and target, or an explicit statement that none exists), sizing, warmup and "
     "order semantics are frozen and hashed BEFORE any measurement. No parameter search."),
    ("P-05", "Point-in-time data",
     "Every input carries a PIT availability rule and a unit check. A feature whose publication timestamp "
     "cannot be pinned is not used."),
    ("P-06", "Costs and execution model",
     "The admission cost is the project's own cost model at the candidate's venue, size and liquidity regime; "
     "the project's 23.791 bps floor applies unless a cheaper scenario is explicitly justified and recorded. "
     "No result is reported gross and called net."),
    ("P-07", "Development and OOS separation",
     "A development window is frozen first; the out-of-sample window is opened once, after the candidate is "
     "hashed. Touching OOS to select or tune a candidate invalidates the candidate."),
    ("P-08", "Capped candidates and experiments",
     "A hard cap on candidates and on experiments per candidate, declared before the programme starts, so that "
     "the number of attempts is visible in the result."),
    ("P-09", "Multiple-testing control",
     "The programme records the total number of hypotheses and experiments and applies an explicit correction "
     "or an explicit honesty statement about the effective significance level."),
    ("P-10", "Net-profitability gate",
     "A candidate passes only if its net edge after the frozen cost model is positive AND exceeds the "
     "benchmark alternative; DO_NOT_TRADE is a first-class benchmark, not an afterthought."),
    ("P-11", "Robustness test",
     "A predeclared battery: cost stress at 1.25x and 1.5x, sub-period stability, sign stability across "
     "splits, and a sensitivity check that was named before the result was seen."),
    ("P-12", "Independent verifier",
     "A second program re-derives the candidate's rules, data lineage, cost model and result, and may return "
     "FAIL even when the author recommends promotion. Builder != verifier."),
    ("P-13", "STOP on a negative result",
     "A failed candidate closes; it is not re-tuned. The programme stops when the cap is reached or when a "
     "predeclared stop rule fires, and the result is written up whether positive or negative."),
)


def render_proposal(routes_data: dict[str, Any], cost: dict[str, Any]) -> str:
    lines = [
        "# PROFITABILITY_DISCOVERY_PROPOSAL",
        "",
        "- status: **PROPOSED — NOT ACTIVATED**",
        "- proposed_id: **RFC-046** (see §0: RFC-036 is NOT available — it was already used by `d0efb51` for a "
        "managed-futures trend reproduction, and the RFC-035 lineage's claim that it is reserved for exact "
        "replication does not match the repository)",
        "- proposed_by_artifact: `reports/profitability_gate035/FINAL_REPORT.json` (that artifact, not "
        "this document, records the commit the gate was evaluated at)",
        f"- as_of_utc: {RETRIEVED_AT}",
        "",
        "> This document is a **proposal**. It is not a decision, it does not open an RFC, and it does not "
        "authorize any work. The programme may start only after an explicit amendment of the master roadmap and "
        "of the RFC-043 operating model, both named in §5.",
        "",
        "## 0. A correction this proposal must carry",
        "",
        "RFC-035's rounds 2 and 3 (and this gate's own brief) describe **RFC-036 as reserved for the exact "
        "replication of an RFC-035 candidate**. That is not what the repository shows: RFC-036 was opened on "
        "**2026-10-05** in commit `d0efb51` for a *managed-futures trend reproduction*, its scripts and tests "
        "are tracked, and `tasks/roadmap.md` contains no RFC-016/035/036 reservation at all. The number is "
        "therefore **occupied**, and this proposal does not reuse it.",
        "",
        "The mandated status `RFC-036_REPLICATION = BLOCKED` is still correct, but for a different and honest "
        "reason: there is **no `REPLICATE_P0` candidate to replicate**, so no replication work can be opened "
        "from RFC-035 at all. The blocked thing is the replication of an RFC-035 candidate, not the number.",
        "",
        "Whoever amends the roadmap should resolve the numbering explicitly: if an RFC-035 candidate ever "
        "appears, its replication needs a free number chosen at that time. This proposal takes RFC-046 and "
        "reserves nothing.",
        "",
        "## 1. Why this is being proposed instead of continued search",
        "",
        "RFC-035 closed as `CLOSED_NO_SUITABLE_EXTERNAL_STRATEGY`: three rounds read 75 sources, registered 33 "
        "opportunities and promoted none, because the external corpus did not contain a source that ships "
        "complete rules *and* an attributable result *and* a realistic cost model *and* fits this runtime.",
        "The search was not the problem; the object it was looking for was not in the places it was allowed to "
        "look. That is a statement about the investigated universe, not about the market.",
        "",
        "## 2. What the proposal is not",
        "",
        "- it is not an exact replication programme: that work is blocked for the separate reason given in §0, "
        "namely that there is no RFC-035 candidate to replicate, and RFC-036 is already occupied anyway",
        "- it is not a strategy generator, an optimiser or a parameter search",
        "- it does not weaken any acceptance criterion; the business-edge requirement "
        "(NET POSITIVE + BENCHMARK-ADJUSTED VALUE + EXECUTABLE + ROBUST) is unchanged",
        "- it does not authorize capital, paper trading or live execution; `TRADES_AUTHORIZED` stays 0",
        "",
        "## 3. Mandatory protocol",
        "",
        "| id | requirement | rule |",
        "| --- | --- | --- |",
    ]
    for pid, requirement, rule in PROPOSAL_PROTOCOL:
        lines.append(f"| {pid} | **{requirement}** | {rule} |")
    lines += [
        "",
        "## 4. The cost gate is the first gate, not the last",
        "",
        f"The audited admission cost is **{cost['round_trip_bps']} bps** round trip, of which "
        f"**{cost['known_bps']} bps is the published taker fee** — an irreducible KNOWN term, not a model "
        "assumption. No candidate in this programme is measured until its gross edge per round trip is above "
        f"{cost['required_gross_edge_bps']} bps, and none is promoted until it is above the "
        f"{cost['required_gross_edge_stressed_bps']} bps stressed threshold with a turnover profile whose "
        "annual drag the programme can state in advance.",
        "",
        "Consequence for candidate selection: a family whose per-trade edge is a few basis points is excluded "
        "before any data is loaded. The protocol therefore prefers low-turnover hypotheses whose per-trade "
        "expected edge can plausibly exceed the fee.",
        "",
        "## 5. Required amendments before activation",
        "",
        "| # | document | required change |",
        "| --- | --- | --- |",
        "| 1 | `tasks/roadmap.md` | add the discovery programme as its own phase with its own exit criteria, and "
        "name RFC-046 as the vehicle |",
        "| 2 | `docs/research/PROFITABILITY_OPERATING_MODEL.json` | amend `next_action_policy.trigger`, which "
        "today admits only a NEW QUALIFIED OPPORTUNITY or a MATERIAL CAPITAL / INSTRUMENT CHANGE; this programme "
        "proceeds without either, so the policy must say so explicitly or the programme must not start |",
        "| 3 | `docs/governance/PROFITABILITY_FIRST_FREEZE.md` | record that the RFC-035-scoped prohibition on "
        "our own backtesting lapses with RFC-035, and that discovery is admissible again only under this "
        "protocol |",
        "| 4 | `tasks/decisions.md` | one ADR recording the amendment, the reason and the stop rule |",
        "",
        "Until all four are done, the correct action is route A: wait.",
        "",
        "## 6. Stop rule",
        "",
        "The programme stops, and writes up the negative result, when any of these fires:",
        "",
        "- the candidate cap is reached with no candidate above the stressed net-edge gate;",
        "- any candidate's robustness battery fails the predeclared criterion;",
        "- the independent verifier returns FAIL on a promoted candidate;",
        "- the actual cost measured in paper execution exceeds the modelled cost by more than the predeclared "
        "tolerance.",
        "",
        "A stop is a result, not a failure of the programme.",
        "",
    ]
    return "\n".join(lines) + "\n"


def write_proposal(routes_data: dict[str, Any], cost: dict[str, Any]) -> str:
    PROPOSAL.parent.mkdir(parents=True, exist_ok=True)
    PROPOSAL.write_text(render_proposal(routes_data, cost), encoding="utf-8")
    return str(PROPOSAL.relative_to(REPO)).replace("\\", "/")


# --------------------------------------------------------------------------- #
# renderers
# --------------------------------------------------------------------------- #

def rounds_text(baseline: dict[str, Any]) -> str:
    parts = []
    for entry in baseline["catalogue"]["rounds"]:
        parts.append(f"{entry.get('rfc')}={entry.get('sources')}")
    return ", ".join(parts)


def render_final(baseline: dict[str, Any], cost: dict[str, Any], causes: dict[str, Any],
                 routes_data: dict[str, Any], defects: dict[str, Any], proposal_path: str,
                 gates: dict[str, Any]) -> str:
    iv = baseline["independent_verifications"]
    lines = [
        "# PROFITABILITY-GATE-035 — FINAL REPORT",
        "",
        "## 1. Closure",
        "",
        "```text",
        "RFC-035                 = CLOSED_NO_SUITABLE_EXTERNAL_STRATEGY",
        "REPLICATE_P0            = NONE",
        "RFC-036_REPLICATION     = BLOCKED",
        "PROFITABILITY_VERIFIED  = FALSE",
        "TRADES_AUTHORIZED       = 0",
        f"CURRENT HEAD            = {baseline['current_head']}",
        "```",
        "",
        "The closure refers to **the universe of sources investigated and the criteria applied**, not to the "
        "non-existence of profitable opportunities. No acceptance criterion was lowered retroactively, and "
        "every artifact, hash and rejection reason is preserved.",
        "",
        "## 2. Baseline audit",
        "",
        f"- HEAD: `{baseline['current_head']}`",
        f"- RFC-035S3 commits present in history: **{str(baseline['rfc035s3_commits']['all_in_history']).lower()}** "
        f"({', '.join(baseline['rfc035s3_commits']['expected'])})",
        f"- working tree: {baseline['working_tree']['tracked_modifications']} tracked modifications "
        f"(all owned by other threads), {baseline['working_tree']['untracked_entries']} untracked entries",
        f"- catalogue: **{baseline['catalogue']['sources']} sources**, "
        f"{baseline['catalogue']['unique_source_ids']} unique, rounds {rounds_text(baseline)}",
        f"- opportunities: **{baseline['opportunities']['total']}**, ranks {baseline['opportunities']['rank_counts']}",
        f"- frozen selections: {baseline['opportunities']['frozen_selections']}",
        "",
        "### Independent verifications (read, not re-run)",
        "",
        "| artifact | status | checks | mismatches | false success |",
        "| --- | --- | --- | --- | --- |",
    ]
    for name, entry in iv.items():
        lines.append(f"| `{name}` | **{entry['status']}** | {entry['passed']}/{entry['checks']} | "
                     f"{entry['mismatches']} | {entry['false_success']} |")
    lines += [
        "",
        "The single mismatch in `reports/rfc035/RFC035_VERIFICATION.json` is the baseline-commit-versus-HEAD "
        "check; it was reproduced as zero mismatches in an isolated worktree at the baseline commit, so it is a "
        "legitimate HEAD advance and not an alteration of evidence.",
        "",
        "### Historical reproduction (read from round 3's own record)",
        "",
    ]
    hist = baseline["historical_reproduction"]
    if hist.get("runs"):
        lines += [
            "| verifier | registry state | status | checks | mismatches | false success | exit |",
            "| --- | --- | --- | ---: | ---: | ---: | ---: |",
        ]
        for run in hist["runs"]:
            lines.append(f"| `{run.get('script')}` | {run.get('registry_state')} | **{run.get('status')}** | "
                         f"{run.get('checks')} | {run.get('mismatches')} | {run.get('false_success')} | "
                         f"`{run.get('exit_code')}` |")
        for run in hist.get("runs_after_round_3_registry") or []:
            lines.append(f"| `{run.get('script')}` | after the round-3 registry | **{run.get('status')}** | "
                         f"{run.get('checks')} | {run.get('mismatches')} | — | — |")
        lines += [
            "",
            f"- lab commit: `{hist.get('lab_commit')}`",
            f"- invariant: **{hist.get('invariant')}**",
            f"- count growth: {hist.get('count_growth_note')}",
        ]
    else:
        lines.append("- (round 3 recorded no reproduction block)")
    lines += [
        "",
        "This gate did **not** re-run the historic verifiers; it reads round 3's recording, which is the correct "
        "source and does not touch frozen evidence.",
        "",
        "### Campaign and CAP-004B",
        "",
        f"- campaign `{baseline['campaign']['campaign_id']}` v{baseline['campaign']['campaign_version']} "
        f"({baseline['campaign']['source_type']})",
        f"- alpha_claimed = **{baseline['campaign']['alpha_claimed']}**, "
        f"alpha_research_freeze = **{baseline['campaign']['alpha_research_freeze']}**, "
        f"next_alpha_rfc_allowed = **{baseline['campaign']['next_alpha_rfc_allowed']}**",
        f"- runtime_promotion = **{baseline['campaign']['runtime_promotion']}**, "
        f"trades_authorized = **{baseline['campaign']['trades_authorized']}**, "
        f"min_evaluable_decisions = {baseline['campaign']['min_evaluable_decisions']}",
        f"- CAP-004B as of {baseline['cap004b']['as_of_utc']}: **{baseline['cap004b']['verdict']}**, "
        f"supervisor {baseline['cap004b']['supervisor_status']}, chain {baseline['cap004b']['chain_status']}, "
        f"drift {baseline['cap004b']['drift_status']}",
        f"- sealed {baseline['cap004b']['sealed']} / settled {baseline['cap004b']['settled']} / "
        f"evaluated {baseline['cap004b']['evaluated']}; duplicate decisions "
        f"{baseline['cap004b']['duplicate_decisions']}, duplicate evaluations "
        f"{baseline['cap004b']['duplicate_evaluations']}",
        f"- CAP-004B verifiers: {compact(baseline['cap004b']['verifiers'])}, "
        f"FALSE_SUCCESS = {baseline['cap004b']['false_success']}",
        f"- first real settlement: {baseline['cap004b']['first_real_settlement_status']}",
        f"- CAP-004B next gate: **{baseline['cap004b']['next_gate']}**",
        "",
        "CAP-004B runs **in parallel and independently of this gate**: it accumulates real-market decisions with "
        "`alpha_claimed = NONE` and `trades_authorized = 0`. Its `runtime_promotion = FORBIDDEN` and "
        "`next_alpha_rfc_allowed = NO` are the same governance position this gate reaches, from a different "
        "direction, and neither was relaxed here.",
        "",
        "CAP-004B's own limitations are recorded for completeness: it had **0 evaluable decisions** at its "
        "last export against a threshold of 100, and it declares two open defects (heartbeat written before the "
        "verify phase; exported Windows task XML omits `Enabled`/`RunLevel`). Neither belongs to this gate.",
        "",
        "### Operating model",
        "",
        f"- RFC-043 operating model: milestone **{baseline['operating_model']['current_milestone']}**, "
        f"any_tier_authorized={str(baseline['operating_model']['any_tier_authorized']).lower()}, "
        f"capital_scale_authorized={str(baseline['operating_model']['capital_scale_authorized']).lower()}, "
        f"next=`{baseline['operating_model']['next']}`",
        f"- standing trigger policy: {baseline['operating_model']['trigger_policy']}",
        f"- no_periodic_rfc: {baseline['operating_model']['no_periodic_rfc']}",
        "",
        "## 3. Rejection root causes",
        "",
        "| cause | owner | reason-code hits | round-3 candidates |",
        "| --- | --- | ---: | --- |",
    ]
    for entry in causes["causes"]:
        lines.append(f"| **{entry['code']}** {entry['cause']} | {entry['owner']} | {entry['reason_code_hits']} | "
                     f"{', '.join(entry['round_3_candidates']) or '—'} |")
    lines += [
        "",
        f"> {causes['coverage_caveat']}",
        "",
        f"> {causes['rc3_note']}",
        "",
        f"Ownership totals: SOURCE {causes['ownership_totals']['SOURCE']}, "
        f"MARKET {causes['ownership_totals']['MARKET']}, "
        f"CONTRACT {causes['ownership_totals']['CONTRACT']}, "
        f"CONTRACT_AND_RUNTIME {causes['ownership_totals']['CONTRACT_AND_RUNTIME']}.",
        "",
        f"> {causes['market_cause_quantified']['statement']}: "
        f"{causes['market_cause_quantified']['best_internal_tick_gross_bps']} bps measured gross against "
        f"{causes['market_cause_quantified']['cost_floor_bps']} bps cost "
        f"(ratio {causes['market_cause_quantified']['ratio']}).",
        "",
        f"> {causes['not_concluded'][0]}",
        "",
        "## 4. Economic feasibility",
        "",
        f"- admission scenario: `{cost['admission_scenario_id']}` — {cost['venue']} {cost['product']}, "
        f"{cost['tier']}",
        f"- round trip: **{cost['round_trip_bps']} bps**, of which {cost['known_bps']} bps KNOWN and "
        f"{cost['estimated_bps']} bps ESTIMATED (documented as {cost['documented_reference_bps']} bps)",
        f"- stressed requirement (x{cost['stress_multiple']}): {cost['required_gross_edge_stressed_bps']} bps",
        f"- assumed size {cost['assumed_size_usd']:.0f} USD, liquidity `{cost['assumed_liquidity_regime']}`",
        "",
        "## 5. Alternative routes",
        "",
        "| criterion | A | B | C |",
        "| --- | --- | --- | --- |",
    ]
    for row in route_matrix(routes_data):
        lines.append(f"| {row['criterion']} | {row['A']} | {row['B']} | {row['C']} |")
    lines += [
        "",
        f"**Recommended next path: {routes_data['recommendation']}** — "
        f"{routes_data['B']['title']}.",
        "",
    ]
    for reason in routes_data["recommendation_reasoning"]:
        lines.append(f"- {reason}")
    lines += [
        "",
        "## 6. Pending technical defects",
        "",
    ]
    for key, entry in defects.items():
        lines.append(f"- **{key}** — {compact(entry)}")
    lines += [
        "",
        "## 7. Required roadmap amendment",
        "",
        f"The proposal is written to `{proposal_path}` and is **PROPOSED, NOT ACTIVATED**. It requires:",
        "",
        "1. `tasks/roadmap.md` gains the discovery phase and names RFC-046;",
        "2. `docs/research/PROFITABILITY_OPERATING_MODEL.json` amends `next_action_policy.trigger`;",
        "3. `docs/governance/PROFITABILITY_FIRST_FREEZE.md` records that the RFC-035-scoped prohibition lapses;",
        "4. `tasks/decisions.md` records one ADR.",
        "",
        "### The RFC-036 numbering conflict, recorded rather than inherited",
        "",
        "The RFC-035 lineage (rounds 2 and 3) and this gate's brief describe **RFC-036 as reserved for the "
        "exact replication of an RFC-035 candidate**. The repository contradicts that, and this gate does not "
        "repeat the claim.",
        "",
        "| fact | evidence |",
        "| --- | --- |",
        "| RFC-036 was already opened on 2026-10-05 for a managed-futures trend reproduction | commit "
        "`d0efb51`; `scripts/rfc036_run.py`, `tests/unit/research/test_rfc036_managed_futures.py` (tracked) |",
        "| its own artifact claims a validated net edge, with its holdout gate not run | `reports/RFC036_FINAL_REPORT.json` |",
        "| no document reserves RFC-036 for anything | `tasks/roadmap.md` contains no RFC-035/036/044/045/046 "
        "reference at all |",
        "",
        "`RFC-036_REPLICATION = BLOCKED` is therefore kept, but read honestly: **the blocked thing is the "
        "replication of an RFC-035 candidate, which does not exist (`REPLICATE_P0 = NONE`), not the RFC "
        "number.** This gate reserves no number, reuses none, and does not validate, promote or endorse "
        "RFC-036; the conflict belongs to the amendment.",
        "",
        "Until the amendment is made the correct action is route A.",
        "",
        "## 8. Gates measured in this run",
        "",
        "| gate | command | result | exit |",
        "| --- | --- | --- | --- |",
    ]
    if gates.get("status") == "NOT_RUN":
        lines.append("| (none) | — | NOT_RUN | — |")
    else:
        for name, entry in gates.items():
            if not isinstance(entry, dict):
                continue
            lines.append(f"| {name} | `{entry.get('command')}` | {entry.get('result')} | "
                         f"`{entry.get('exit_code')}` |")
    lines += [
        "",
        "## 9. Vocabulary",
        "",
        "This report never asserts PROFITABLE, EDGE_CONFIRMED or PRODUCTION_READY. No strategy was designed, "
        "optimized or executed. No real trading was started.",
        "",
    ]
    return "\n".join(lines) + "\n"


def final_payload(baseline: dict[str, Any], cost: dict[str, Any], causes: dict[str, Any],
                  routes_data: dict[str, Any], defects: dict[str, Any], proposal_path: str,
                  gates: dict[str, Any]) -> dict[str, Any]:
    sup = baseline["opportunities"]["superseded_in_round_3"]
    r36 = baseline.get("rfc036_actual_state") or {}
    return {
        "gate": "PROFITABILITY-GATE-035",
        "as_of_utc": RETRIEVED_AT,
        "current_head": baseline["current_head"],
        "rfc_035_final_status": "CLOSED_NO_SUITABLE_EXTERNAL_STRATEGY",
        "closure": {
            "RFC-035": "CLOSED_NO_SUITABLE_EXTERNAL_STRATEGY",
            "REPLICATE_P0": "NONE",
            "RFC-036_REPLICATION": "BLOCKED",
            "PROFITABILITY_VERIFIED": False,
            "TRADES_AUTHORIZED": 0,
            "scope": "the universe of sources investigated and the criteria applied, not the non-existence of "
                     "profitable opportunities",
            "criteria_lowered": False,
            "artifacts_preserved": True,
        },
        "rfc_036_actual_state": r36,
        "candidates_accepted": {
            "REPLICATE_P0": 0,
            "superseded_replication_ranks": sup,
            "note": "the two REPLICATE_P1 ranks were superseded in round 3 after the four-state audit; their "
                    "frozen ranks are preserved and their current rank is INSUFFICIENT_EVIDENCE",
        },
        "baseline_audit": baseline,
        "baseline_reproduction": audit_reproduced(),
        "rejection_root_causes": causes,
        "current_runtime_state": {
            "mode": "paper",
            "live_trading_enabled": False,
            "exchange_sandbox": True,
            "require_manual_confirmation_for_live": True,
            "strategy_states": "research / paper only, with a mandated progression research -> paper -> "
                               "live_candidate -> live",
            "no_trade_is_first_class": True,
            "risk_engine": "deterministic (src/trading_bot/risk/manager.py)",
            "reference_capital_usdt": 200.0,
            "capital_tier": "TIER_0 CANARY",
            "business_edge_milestone": baseline["operating_model"]["current_milestone"],
        },
        "pending_technical_defects": defects,
        "cost_feasibility": cost,
        "recommended_next_path": {
            "route": routes_data["recommendation"],
            "title": routes_data["B"]["title"],
            "status": "PROPOSED",
            "reasoning": routes_data["recommendation_reasoning"],
            "comparison_matrix": route_matrix(routes_data),
        },
        "required_roadmap_amendment": {
            "proposal_path": proposal_path,
            "status": "PROPOSED_NOT_ACTIVATED",
            "proposed_id": "RFC-046",
            "numbering": {
                "RFC-036": "NOT available: already used by commit d0efb51 on 2026-10-05 for a managed-futures "
                           "trend reproduction. The RFC-035 lineage's description of it as reserved for exact "
                           "replication is not supported by the repository.",
                "RFC-044": "taken by an earlier programme",
                "RFC-045": "excluded by the standing next-action policy (no periodic RFC)",
                "RFC-046": "the free number this proposal takes",
                "blocked_reason": "RFC-036_REPLICATION = BLOCKED because REPLICATE_P0 = NONE: there is no "
                                  "RFC-035 candidate to replicate. The number being occupied is a separate "
                                  "fact, reported rather than relied on.",
            },
            "required_changes": [
                "tasks/roadmap.md gains the discovery phase and names RFC-046",
                "docs/research/PROFITABILITY_OPERATING_MODEL.json amends next_action_policy.trigger",
                "docs/governance/PROFITABILITY_FIRST_FREEZE.md records that the RFC-035-scoped prohibition lapses",
                "tasks/decisions.md records one ADR",
            ],
            "blocking_conflict": "the operating model admits only a NEW QUALIFIED OPPORTUNITY or a MATERIAL "
                                 "CAPITAL / INSTRUMENT CHANGE as a trigger, and this programme has neither",
        },
        "independent_verification": "SEE_INDEPENDENT_VERIFICATION",
        "false_success": "SEE_INDEPENDENT_VERIFICATION",
        "gates": gates,
        "next_gate": "AWAIT_ROADMAP_AMENDMENT_DECISION — RFC-036 stays BLOCKED",
        "flags": {
            "TRADES_AUTHORIZED": 0,
            "PROFITABLE": False,
            "EDGE_CONFIRMED": False,
            "PRODUCTION_READY": False,
            "alpha_research_freeze": "ACTIVE until RFC-035 closure is recorded",
        },
    }


def render_postmortem(baseline: dict[str, Any], causes: dict[str, Any]) -> str:
    lines = [
        "# PROFITABILITY-GATE-035 — SEARCH POSTMORTEM",
        "",
        "## 1. What was searched",
        "",
        f"Three rounds, **{baseline['catalogue']['sources']} sources** "
        f"({rounds_text(baseline)}) and "
        f"**{baseline['opportunities']['total']} registered opportunities**.",
        "",
        "| round | verdict | what it established |",
        "| --- | --- | --- |",
        "| RFC-035 | `OPEN_NO_REPLICABLE_EXTERNAL_STRATEGY` | 9 opportunities, 1 selected (OPP-0001) |",
        "| RFC-035E | `EFFECT_NOT_REPRODUCED` | the selected claim did not survive its own replication |",
        "| RFC-035S2 | `CONTINUE_SEARCH` | 44 new sources; no candidate cleared the P0 contract |",
        "| RFC-035S3 | `NO_SUITABLE_EXTERNAL_STRATEGY` | the two best candidates failed a corrected, "
        "four-state audit |",
        "",
        "## 2. Where the rejections came from",
        "",
        "| cause | owner | hits |",
        "| --- | --- | ---: |",
    ]
    for entry in causes["causes"]:
        lines.append(f"| **{entry['code']}** {entry['cause']} | {entry['owner']} | {entry['reason_code_hits']} |")
    lines += [
        "",
        "The ranking matters. The three most frequent causes are *contract-shaped*: the corpus does not state "
        "every material field, is read too thinly to promote, or ships no code. Cost headroom is the fourth and "
        "the first that is a property of the market rather than of a document.",
        "",
        "## 3. The uncomfortable finding",
        "",
        "Cost headroom is not a documentation problem. The internal microstructure line measured its best "
        "tick-level gross edge at **+0.614 bps** against a **23.791 bps** round trip — a factor of about 39. "
        "That line was closed by arithmetic, not by an absent paper. Any family whose edge per trade is a few "
        "basis points is excluded before a source is even read.",
        "",
        "## 4. What the postmortem does not say",
        "",
        "- it does not say the market has no edge; it says the sources we could read did not carry a replicable one",
        "- it does not say the criteria were too strict; it says the criteria were applied consistently and the "
        "corpus did not meet them",
        "- it does not treat missing public documentation as evidence of missing alpha",
        "",
        "## 5. What would have made a difference",
        "",
        "One source that shipped all four together: complete executable rules, a stated period with a trade "
        "count and metrics attributable to the code, a cost model, and a universe this runtime can hold. "
        "Fourteen of the 33 opportunities failed on the first alone.",
        "",
    ]
    return "\n".join(lines) + "\n"


def render_economic(cost: dict[str, Any], r36: dict[str, Any]) -> str:
    lines = [
        "# PROFITABILITY-GATE-035 — ECONOMIC FEASIBILITY",
        "",
        "Every number below is evaluated from the project's own cost model "
        "(`trading_bot.research.microstructure.cost_model_v3`) in this run. Nothing is reduced artificially "
        "and no expected return is invented.",
        "",
        "## 1. Where the 23.791 bps comes from",
        "",
        f"- scenario: `{cost['admission_scenario_id']}`",
        f"- market: {cost['market']} — {cost['tier']}",
        f"- symbol class: {cost['symbol_class']}",
        f"- jurisdiction: {cost['jurisdiction']}",
        f"- order type: {cost['order_type']}",
        f"- assumed size: {cost['assumed_size_usd']:.0f} USD, liquidity `{cost['assumed_liquidity_regime']}`, "
        f"horizon {cost['assumed_horizon_minutes']:.0f} min",
        f"- measurement origin: {cost['measurement_origin']['doc']} "
        f"({cost['measurement_origin']['date']}), verified by {cost['measurement_origin']['verified_by']}",
        "",
        "| component | bps | knowledge | source |",
        "| --- | ---: | --- | --- |",
    ]
    for component in cost["components"]:
        lines.append(f"| {component['name']} | {component['value_bps']:.4f} | {component['knowledge']} | "
                     f"{component['source_id']} |")
    lines += [
        f"| **round trip** | **{cost['round_trip_bps']:.4f}** | | |",
        "",
        f"**KNOWN: {cost['known_bps']} bps ({cost['known_share'] * 100:.1f}% of the total).** The taker fee is "
        "the published Binance spot VIP0 schedule, not a modelling choice. Maker and taker are identical at "
        f"VIP0, so a passive fill saves no fee at all. **ESTIMATED: {cost['estimated_bps']} bps.**",
        "",
        f"The project documents this admission cost as **{cost['documented_reference_bps']} bps**. The model "
        f"reproduces **{cost['round_trip_bps']} bps** — the same number at full precision, so the documented "
        "figure still holds and nothing was reduced. Every arithmetic statement below uses the measured "
        "value rather than the rounded one, so the report is internally consistent and independently "
        "checkable; the two differ only in the last decimal place.",
        "",
        "## 2. Known versus assumed",
        "",
    ]
    for item in cost["known_vs_assumed"]:
        lines.append(f"- {item}")
    lines += [
        "",
        "## 3. Venue scenarios in the same model",
        "",
        "| scenario | venue | product | tier | maker | taker | spread | RT bps | status |",
        "| --- | --- | --- | --- | ---: | ---: | ---: | ---: | --- |",
    ]
    for scenario in cost["scenarios"]:
        star = " **(admission)**" if scenario["is_admission"] else ""
        lines.append(f"| `{scenario['scenario_id']}`{star} | {scenario['venue']} | {scenario['product']} | "
                     f"{scenario['tier'][:38]} | {scenario['maker_fee_bps']:.1f} | {scenario['taker_fee_bps']:.1f} | "
                     f"{scenario['spread_bps']:.2f} | {scenario['round_trip_bps']:.3f} | "
                     f"{scenario['integration_status']} |")
    lines += [
        "",
        "Two readings matter. **Maker is more expensive than taker at VIP0** (41.250 vs 23.791 bps), because "
        "the fee is unchanged and the maker leg adds adverse-selection and missed-fill penalties — so posting "
        "limit orders is not a cost escape at this tier. And the cheapest spot venue in the registry is MEXC at "
        "17.791 bps, a real but partial 25% saving that still leaves a 17.8 bps floor.",
        "",
        "## 4. Sensitivity to size and liquidity",
        "",
        "| size (USD) | RT bps |",
        "| ---: | ---: |",
    ]
    for entry in cost["size_sensitivity"]:
        lines.append(f"| {entry['size_usd']:.0f} | {entry['round_trip_bps']:.4f} |")
    lines += ["", "| liquidity | RT bps |", "| --- | ---: |"]
    for entry in cost["liquidity_sensitivity"]:
        lines.append(f"| {entry['liquidity_regime']} | {entry['round_trip_bps']:.4f} |")
    lines += [
        "",
        "The cost is remarkably flat in size at this tier, because the fee dominates and the slippage term is "
        "small at these notionals. It is *not* flat in liquidity: a thin book costs about 4.2 bps more.",
        "",
        "## 5. What turnover can afford",
        "",
        f"At {cost['round_trip_bps']} bps per round trip, the annual drag is mechanical:",
        "",
        "| turnover | round trips / year | annual cost drag | stressed (x"
        f"{cost['stress_multiple']}) |",
        "| --- | ---: | ---: | ---: |",
    ]
    for entry in cost["turnover_cost_drag"]:
        lines.append(f"| {entry['label']} | {entry['round_trips_per_year']} | {entry['annual_drag_pct']:.2f}% | "
                     f"{entry['annual_drag_stressed_pct']:.2f}% |")
    lines += [
        "",
        "This is the single most useful number the gate produces. Daily trading must earn about **87% per year "
        "gross** before costs just to break even at this tier; weekly trading, about **12.4%**. Any hypothesis "
        "proposed for a future programme must state its turnover and clear that arithmetic first.",
        "",
        "## 6. The internal counter-example",
        "",
        f"- best measured tick-level gross edge: "
        f"**{cost['internal_measured_gross_bps']['best_tick_gross_bps']} bps**",
        f"- best kline-aggregated gross edge: "
        f"**{cost['internal_measured_gross_bps']['best_kline_aggregated_gross_bps']} bps**",
        f"- ratio to the cost floor: **{cost['internal_measured_gross_bps']['ratio_tick_to_cost']}x**",
        f"- source: {cost['internal_measured_gross_bps']['source']}",
        "",
        "The project has already measured, with its own data, that the family it was pursuing has an edge two "
        "orders of magnitude below the fee. That measurement is the strongest existing evidence about which "
        "families are worth pursuing next, and it points away from intraday microstructure.",
        "",
        "## 6b. A cost profile that does work, and why it is not a result of this gate",
        "",
        "§06 asks which families could hold enough margin without inventing a return. The repository "
        "already contains one measured, cost-modelled counter-example to the intraday family, and it is worth "
        "quoting precisely because it was **not** produced here.",
        "",
        "RFC-036 (`reports/RFC036_FINAL_REPORT.json`, introduced by commit `d0efb51` on 2026-10-05) is a "
        "diversified managed-futures trend reproduction: 26 markets, 6 asset classes, **monthly** rebalance. "
        "Its own artifact reports:",
        "",
        "| window | gross pnl | cost pnl | net pnl | cost share of gross |",
        "| --- | ---: | ---: | ---: | ---: |",
    ]
    for window, block in (("discovery", r36.get("cost_ratio", {}).get("discovery", {})),
                          ("validation", r36.get("cost_ratio", {}).get("validation", {}))):
        if not block:
            continue
        lines.append(f"| {window} | {block.get('gross_pnl'):.0f} | {block.get('cost_pnl'):.0f} | "
                     f"{block.get('net_pnl'):.0f} | {block.get('cost_share_of_gross', 0) * 100:.2f}% |")
    lines += [
        "",
        f"The contrast with this gate's own arithmetic is the point: monthly rebalancing pays a small "
        f"fraction of gross in costs, whereas the {cost['round_trip_bps']} bps spot floor at a daily turnover "
        "demands about 87% a year before costs. Turnover, not cleverness, is what decides whether a family can "
        "clear the floor.",
        "",
        "**What this gate does not say about RFC-036.** It does not validate it, promote it, or treat its "
        f"claim as an edge. The artifact states `{r36.get('holdout_gate')}` for its holdout gate and "
        f"`{r36.get('next')}` as its next step, and its own net-edge statement "
        f"(`{r36.get('own_net_edge_claim')}`) is quoted here as the artifact's claim, not as a finding of "
        "this gate. No profitability verdict is transferred from it to anything else.",
        "",
        "## 7. Validity scope",
        "",
    ]
    for item in cost["validity_scope"]:
        lines.append(f"- {item}")
    lines += [
        "",
        "## 8. What is not claimed",
        "",
        "- no cost was reduced to make a candidate look viable",
        "- the BNB discount is POSSIBLE but unconfirmed, so it is not applied",
        "- a derivatives venue is much cheaper in the same model but requires a governance decision and is "
        "outside the runtime's instrument set, so it is not applied",
        "- none of these figures is a forecast of any strategy's realised cost",
        "",
    ]
    return "\n".join(lines) + "\n"


def render_alternatives(routes_data: dict[str, Any]) -> str:
    lines = [
        "# PROFITABILITY-GATE-035 — ALTERNATIVE PATHS",
        "",
        "Three routes, evaluated on the eight criteria §04 names. The ratings are qualitative and are backed by "
        "the evidence in `FINAL_REPORT.json` and the cost audit in `ECONOMIC_FEASIBILITY.md`.",
        "",
    ]
    for key in ("A", "B", "C"):
        route = routes_data[key]
        lines += [
            f"## Route {key} — {route['title']}",
            "",
            "| criterion | rating |",
            "| --- | --- |",
        ]
        for criterion in ROUTE_CRITERIA:
            lines.append(f"| {criterion} | {route['ratings'][criterion]} |")
        lines += ["", "Evidence:", ""]
        lines += [f"- {item}" for item in route["evidence"]]
        lines += [""]
    lines += [
        "## Recommendation",
        "",
        f"**Route {routes_data['recommendation']}** — {routes_data['B']['title']}.",
        "",
    ]
    lines += [f"- {reason}" for reason in routes_data["recommendation_reasoning"]]
    lines += [
        "",
        "### Why not A as the recommendation",
        "",
        "Route A is not wrong; it is the status quo and it respects the RFC-043 operating model exactly. It is "
        "not recommended as the *plan* because a plan whose success condition is an external event that may "
        "never occur cannot be evaluated, and because it does not address the finding that the corpus lacks the "
        "combination of properties the contract requires.",
        "",
        "### Why not C as the recommendation",
        "",
        "C is not a route. It is a gate, and this report has already run it: the cost constraint is quantified, "
        "and it is a property of the venue and tier rather than of the data. Keeping C available as the first "
        "gate inside B is how it should be used.",
        "",
        "### The condition on B",
        "",
        "B may not start from this document. It contradicts the standing next-action policy (which admits only a "
        "new qualified opportunity or a material capital or instrument change) and the roadmap knows nothing "
        "about it. Until the four amendments listed in the proposal are made, the correct action is A.",
        "",
    ]
    return "\n".join(lines) + "\n"


def write_run_report(baseline: dict[str, Any], gates: dict[str, Any], proposal_path: str) -> None:
    payload = {
        "run": "PROFITABILITY-GATE-035",
        "as_of_utc": RETRIEVED_AT,
        "builder": "scripts/pgate035_closure.py",
        "verifier": "scripts/pgate035_verify.py",
        "current_head": baseline["current_head"],
        "final_status": "CLOSED_NO_SUITABLE_EXTERNAL_STRATEGY",
        "recommended_route": "B (PROPOSED)",
        "proposal_path": proposal_path,
        "gates": gates,
    }
    (OUT / "RUN_REPORT.json").write_text(
        json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")
    lines = [
        "# PROFITABILITY-GATE-035 — RUN_REPORT",
        "",
        f"- builder: `{payload['builder']}`",
        f"- verifier: `{payload['verifier']}`",
        f"- current HEAD: `{baseline['current_head']}`",
        "- final status: **CLOSED_NO_SUITABLE_EXTERNAL_STRATEGY**",
        "- recommended route: **B (PROPOSED, not activated)**",
        f"- proposal: `{proposal_path}`",
        "",
        "## Gates",
        "",
        "| gate | command | result | exit |",
        "| --- | --- | --- | --- |",
    ]
    if gates.get("status") == "NOT_RUN":
        lines.append("| (none) | — | NOT_RUN | — |")
    else:
        for name, entry in gates.items():
            if not isinstance(entry, dict):
                continue
            lines.append(f"| {name} | `{entry.get('command')}` | {entry.get('result')} | `{entry.get('exit_code')}` |")
    (OUT / "RUN_REPORT.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    gates = load_gates()
    baseline = audit_baseline()
    cost = cost_feasibility()
    causes = root_cause_review(cost)
    routes_data = routes()
    defects = pending_defects()

    (OUT / "BASELINE.json").write_text(
        json.dumps({"gate": "PROFITABILITY-GATE-035", "artifact": "BASELINE_AUDIT", **baseline,
                    "reproduction": audit_reproduced(), "defects": defects},
                   indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")
    (OUT / "ROOT_CAUSES.json").write_text(
        json.dumps({"gate": "PROFITABILITY-GATE-035", "artifact": "ROOT_CAUSES", **causes},
                   indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")
    (OUT / "ECONOMIC_FEASIBILITY.json").write_text(
        json.dumps({"gate": "PROFITABILITY-GATE-035", "artifact": "ECONOMIC_FEASIBILITY", **cost},
                   indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")
    (OUT / "ALTERNATIVE_PATHS.json").write_text(
        json.dumps({"gate": "PROFITABILITY-GATE-035", "artifact": "ALTERNATIVE_PATHS",
                    "routes": routes_data, "comparison_matrix": route_matrix(routes_data)},
                   indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")

    proposal_path = write_proposal(routes_data, cost)

    (OUT / "SEARCH_POSTMORTEM.md").write_text(render_postmortem(baseline, causes), encoding="utf-8")
    (OUT / "ECONOMIC_FEASIBILITY.md").write_text(
        render_economic(cost, baseline.get("rfc036_actual_state") or {}), encoding="utf-8")
    (OUT / "ALTERNATIVE_PATHS.md").write_text(render_alternatives(routes_data), encoding="utf-8")
    report = final_payload(baseline, cost, causes, routes_data, defects, proposal_path, gates)
    (OUT / "FINAL_REPORT.json").write_text(
        json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")
    (OUT / "FINAL_REPORT.md").write_text(
        render_final(baseline, cost, causes, routes_data, defects, proposal_path, gates), encoding="utf-8")
    write_run_report(baseline, gates, proposal_path)

    print("PROFITABILITY-GATE-035 BUILT")
    print(f"CURRENT HEAD   = {baseline['current_head']}")
    print(f"RFC-035        = {report['rfc_035_final_status']}")
    print(f"COST           = {cost['round_trip_bps']} bps ({cost['known_bps']} KNOWN, {cost['estimated_bps']} ESTIMATED)")
    print(f"RECOMMENDATION = route {routes_data['recommendation']} (PROPOSED)")
    print(f"PROPOSAL       = {proposal_path}")
    for name in ("FINAL_REPORT.md", "FINAL_REPORT.json", "SEARCH_POSTMORTEM.md", "ECONOMIC_FEASIBILITY.md",
                 "ALTERNATIVE_PATHS.md"):
        print(f"  wrote {name}: {(OUT / name).is_file()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
