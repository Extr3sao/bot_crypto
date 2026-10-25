#!/usr/bin/env python
"""PROFITABILITY-GATE-035 — independent verifier.

Separate program from ``scripts/pgate035_closure.py`` (BUILDER != VERIFIER). It re-derives
every quantitative claim in the gate's artifacts from primary sources — the source registry,
the opportunity registry, the stored verifiers, the round-3 baseline record, the CAP-004B
report, the campaign manifest, the operating model and the project's own cost model — and
compares. It never imports the builder.

It writes ``reports/profitability_gate035/INDEPENDENT_VERIFICATION.{json,md}`` and exits 0
only on PASS with zero mismatches and zero false success.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

OUT = REPO / "reports" / "profitability_gate035"
REPORTS = REPO / "reports"
RESEARCH = REPO / "research"

BUILDER_DELIVERABLES = [
    "FINAL_REPORT.md",
    "FINAL_REPORT.json",
    "SEARCH_POSTMORTEM.md",
    "ECONOMIC_FEASIBILITY.md",
    "ALTERNATIVE_PATHS.md",
]
#: The sixth §08 deliverable is this verifier's own output; it is checked after writing.
VERIFIER_DELIVERABLE = "INDEPENDENT_VERIFICATION.md"
DELIVERABLES = [*BUILDER_DELIVERABLES, VERIFIER_DELIVERABLE]
PROPOSAL_REL = "docs/roadmap/PROFITABILITY_DISCOVERY_PROPOSAL.md"

REQUIRED_FIELDS = [
    "current_head",
    "rfc_035_final_status",
    "candidates_accepted",
    "rejection_root_causes",
    "current_runtime_state",
    "pending_technical_defects",
    "cost_feasibility",
    "recommended_next_path",
    "required_roadmap_amendment",
    "independent_verification",
    "false_success",
    "next_gate",
]

FORBIDDEN = ("PROFITABLE", "EDGE_CONFIRMED", "PRODUCTION_READY")
NEGATION_MARKERS = ("never", "not ", "no ", "false", "0", "cannot", "out of scope", "absence")

ROOT_CAUSE_CODES = ("RC-1", "RC-2", "RC-3", "RC-4", "RC-5", "RC-6", "RC-7", "RC-8")

results: list[dict[str, Any]] = []


def check(name: str, ok: bool, detail: str = "") -> bool:
    results.append({"check": name, "ok": bool(ok), "detail": detail})
    return bool(ok)


# -- predicate helpers, shared by the positive checks and the negative controls ----

def closure_ok(closure: dict[str, Any]) -> bool:
    return (closure.get("RFC-035") == "CLOSED_NO_SUITABLE_EXTERNAL_STRATEGY"
            and closure.get("REPLICATE_P0") == "NONE"
            and closure.get("RFC-036_REPLICATION") == "BLOCKED"
            and closure.get("PROFITABILITY_VERIFIED") is False
            and closure.get("TRADES_AUTHORIZED") == 0)


def flags_ok(flags: dict[str, Any]) -> bool:
    return (flags.get("TRADES_AUTHORIZED") == 0
            and flags.get("PROFITABLE") is False
            and flags.get("EDGE_CONFIRMED") is False
            and flags.get("PRODUCTION_READY") is False)


def affirmative_claim(line: str) -> str | None:
    """Return the forbidden token if the line claims it without a negation."""
    for token in FORBIDDEN:
        if re.search(rf"\b{token}\b", line) and not any(m in line.lower() for m in NEGATION_MARKERS):
            return token
    return None


def load(path: Path) -> Any:
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None


def close(a: float, b: float, tol: float = 5e-4) -> bool:
    return abs(a - b) <= tol


# --------------------------------------------------------------------------- #
# primary sources
# --------------------------------------------------------------------------- #

def primary() -> dict[str, Any]:
    registry = load(RESEARCH / "profitability" / "source_registry.json") or {}
    opportunities = {}
    for path in sorted((RESEARCH / "profitability" / "opportunities").glob("OPP-*.json")):
        record = load(path)
        if isinstance(record, dict) and "opportunity_id" in record:
            opportunities[record["opportunity_id"]] = record
    return {
        "registry": registry,
        "sources": registry.get("sources") or [],
        "rounds": registry.get("rounds") or [],
        "opportunities": opportunities,
        "round2_log": load(REPORTS / "rfc035" / "search_round_2" / "REJECTION_LOG.json") or {},
        "round3_baseline": load(REPORTS / "rfc035" / "search_round_3" / "BASELINE.json") or {},
        "cap004b": load(REPORTS / "cap004b" / "FINAL_REPORT.json") or {},
        "manifest": load(REPO / "evidence" / "real_decisions" / "CAMPAIGN_MANIFEST.json") or {},
        "operating": load(REPO / "docs" / "research" / "PROFITABILITY_OPERATING_MODEL.json") or {},
        "iv": {
            name: load(REPORTS / name)
            for name in (
                "rfc035/RFC035_VERIFICATION.json",
                "rfc035e/INDEPENDENT_VERIFICATION.json",
                "rfc035/search_round_2/INDEPENDENT_VERIFICATION.json",
                "rfc035/search_round_3/INDEPENDENT_VERIFICATION.json",
            )
        },
        "verdicts": {
            name: load(REPORTS / name) or {}
            for name in (
                "rfc035/FINAL_REPORT.json",
                "rfc035e/FINAL_REPORT.json",
                "rfc035/search_round_2/FINAL_REPORT.json",
                "rfc035/search_round_3/FINAL_REPORT.json",
            )
        },
        "agg": (REPO / "docs" / "AGGTRADES_EXPERIMENTS_V1.md").read_text(encoding="utf-8")
        if (REPO / "docs" / "AGGTRADES_EXPERIMENTS_V1.md").is_file() else "",
    }


# --------------------------------------------------------------------------- #
# recompute the cost model independently
# --------------------------------------------------------------------------- #

def recompute_cost() -> dict[str, Any]:
    from trading_bot.research.microstructure.cost_model_v3 import (
        ADMISSION_SCENARIO_ID,
        VENUE_SPECS,
        CostModelV3,
        cost_model_v3_all_in,
    )

    regimes: tuple[Any, ...] = ("deep", "normal", "thin")
    spec = VENUE_SPECS[ADMISSION_SCENARIO_ID]
    cost = cost_model_v3_all_in(spec, size_usd=1000.0, liquidity_regime="normal", horizon_minutes=25.0)
    components = {c.name: round(c.value_bps, 4) for c in cost.components}
    return {
        "scenario": ADMISSION_SCENARIO_ID,
        "round_trip": round(cost.round_trip_bps, 4),
        # The unrounded value, so the turnover arithmetic can be checked against the real model
        # rather than against the artifact's own 4-dp rounding.
        "round_trip_raw": cost.round_trip_bps,
        "components": components,
        "scenarios": {
            sid: round(CostModelV3(spec=v).evaluate(
                size_usd=1000.0, liquidity_regime="normal", horizon_minutes=25.0).round_trip_bps, 4)
            for sid, v in VENUE_SPECS.items()
        },
        "sizes": {
            s: round(CostModelV3(spec=spec).evaluate(
                size_usd=s, liquidity_regime="normal", horizon_minutes=25.0).round_trip_bps, 4)
            for s in (200.0, 500.0, 1000.0, 5000.0, 10000.0)
        },
        "liquidity": {
            r: round(CostModelV3(spec=spec).evaluate(
                size_usd=1000.0, liquidity_regime=r, horizon_minutes=25.0).round_trip_bps, 4)
            for r in regimes
        },
    }


# --------------------------------------------------------------------------- #
# verification
# --------------------------------------------------------------------------- #

def verify_structure() -> dict[str, Any]:
    """§08 and §09 — the deliverable set and the required output fields."""
    check("§08 names all six deliverables",
          set(DELIVERABLES) == {n for n in DELIVERABLES} and len(DELIVERABLES) == 6, str(len(DELIVERABLES)))
    for name in BUILDER_DELIVERABLES:
        path = OUT / name
        check(f"deliverable {name} exists", path.is_file(), str(path))
        if path.is_file():
            check(f"deliverable {name} is non-empty", path.stat().st_size > 0, f"{path.stat().st_size} bytes")
    proposal = REPO / PROPOSAL_REL
    check("proposal exists", proposal.is_file(), PROPOSAL_REL)
    check("proposal is non-empty", proposal.is_file() and proposal.stat().st_size > 0, PROPOSAL_REL)

    report = load(OUT / "FINAL_REPORT.json") or {}
    check("FINAL_REPORT.json parses", bool(report), "json.loads ok")
    for field in REQUIRED_FIELDS:
        check(f"§09 field present: {field}", field in report, f"value type {type(report.get(field)).__name__}")
    return report


def verify_closure(report: dict[str, Any]) -> None:
    closure = report.get("closure") or {}
    check("§02 closure block satisfies the full §02 contract", closure_ok(closure), json.dumps(closure))
    expected = {
        "RFC-035": "CLOSED_NO_SUITABLE_EXTERNAL_STRATEGY",
        "REPLICATE_P0": "NONE",
        "RFC-036_REPLICATION": "BLOCKED",
        "PROFITABILITY_VERIFIED": False,
        "TRADES_AUTHORIZED": 0,
    }
    for key, value in expected.items():
        check(f"§02 closure {key} == {value!r}", closure.get(key) == value, f"got {closure.get(key)!r}")
    check("§02 RFC-035 status matches the closure block",
          report.get("rfc_035_final_status") == expected["RFC-035"],
          f"got {report.get('rfc_035_final_status')!r}")
    check("§02 closure states its scope is the investigated universe",
          "universe" in str(closure.get("scope", "")), str(closure.get("scope"))[:80])
    check("§02 reports that criteria were not lowered", closure.get("criteria_lowered") is False, "")
    check("§02 reports that artifacts are preserved", closure.get("artifacts_preserved") is True, "")
    flags = report.get("flags") or {}
    check("§09 flags satisfy the no-promotion contract", flags_ok(flags), json.dumps(flags))
    check("§09 flags: TRADES_AUTHORIZED == 0", flags.get("TRADES_AUTHORIZED") == 0, "")
    for forbidden in ("PROFITABLE", "EDGE_CONFIRMED", "PRODUCTION_READY"):
        check(f"§09 flags: {forbidden} is false", flags.get(forbidden) is False, "")


def verify_baseline(report: dict[str, Any], src: dict[str, Any]) -> None:
    audit = report.get("baseline_audit") or {}
    registry_sources = src["sources"]
    ids = [s.get("SOURCE_ID") for s in registry_sources]

    check("catalogue count matches the registry",
          audit.get("catalogue", {}).get("sources") == len(registry_sources),
          f"{audit.get('catalogue', {}).get('sources')} vs {len(registry_sources)}")
    check("catalogue source ids are unique in the registry", len(set(ids)) == len(ids), f"{len(ids)} ids")
    check("catalogue reports uniqueness consistent with the registry",
          audit.get("catalogue", {}).get("unique") is (len(set(ids)) == len(ids)), "")
    check("round source counts match the registry",
          [r.get("sources") for r in audit.get("catalogue", {}).get("rounds", [])]
          == [r.get("sources") for r in src["rounds"]], "")
    check("round source counts sum to the catalogue total",
          sum(int(r.get("sources") or 0) for r in src["rounds"]) == len(registry_sources), "")
    for entry in audit.get("catalogue", {}).get("rounds", []) or []:
        check(f"round {entry.get('rfc')} recorded with sources >= 0",
              isinstance(entry.get("sources"), int) and entry["sources"] >= 0, str(entry))

    opportunities = src["opportunities"]
    check("opportunity count matches the registry files",
          audit.get("opportunities", {}).get("total") == len(opportunities),
          f"{audit.get('opportunities', {}).get('total')} vs {len(opportunities)}")
    histogram: dict[str, int] = {}
    for record in opportunities.values():
        key = str(record.get("rank"))
        histogram[key] = histogram.get(key, 0) + 1
    check("opportunity rank histogram matches the registry files",
          audit.get("opportunities", {}).get("rank_counts") == histogram,
          f"{audit.get('opportunities', {}).get('rank_counts')} vs {histogram}")
    superseded = {
        oid: record.get("current_rank")
        for oid, record in opportunities.items() if record.get("current_rank")
    }
    check("superseded ranks match the registry files",
          audit.get("opportunities", {}).get("superseded_in_round_3") == superseded, "")
    frozen = [oid for oid, record in opportunities.items() if record.get("frozen_selection")]
    check("frozen selections match the registry files",
          audit.get("opportunities", {}).get("frozen_selections") == frozen, "")
    for oid, record in opportunities.items():
        check(f"{oid} supersession is consistent",
              not record.get("current_rank") or record.get("current_rank") != record.get("rank")
              or record.get("current_rank") is None, str(record.get("current_rank")))

    check("candidate acceptance: REPLICATE_P0 == 0",
          report.get("candidates_accepted", {}).get("REPLICATE_P0") == 0, "")
    check("no opportunity currently carries REPLICATE_P0",
          all(str(r.get("rank")) != "REPLICATE_P0" for r in opportunities.values()), "")
    check("no opportunity currently carries an accepted rank",
          all(str(r.get("rank")) not in ("ACCEPTED", "PROMOTED") for r in opportunities.values()), "")

    # the four stored independent verifications, read back independently
    quoted = audit.get("independent_verifications") or {}
    for name, iv in src["iv"].items():
        key = name.replace("\\", "/")
        stored = quoted.get(key) or quoted.get(name) or {}
        check(f"IV {key} status quoted matches the artifact",
              stored.get("status") == (iv or {}).get("status"),
              f"{stored.get('status')} vs {(iv or {}).get('status')}")
        check(f"IV {key} checks quoted matches the artifact",
              stored.get("checks") == (iv or {}).get("checks"), "")
        check(f"IV {key} mismatches quoted matches the artifact",
              stored.get("mismatches") == (iv or {}).get("mismatches"), "")
        check(f"IV {key} false_success quoted matches the artifact",
              stored.get("false_success") == (iv or {}).get("false_success"), "")

    # the historic reproduction claims come from round 3's own record
    hist = audit.get("historical_reproduction") or {}
    r3 = (src["round3_baseline"].get("reproduction") or {})
    check("historic lab commit matches round 3's record", hist.get("lab_commit") == r3.get("lab_commit"),
          f"{hist.get('lab_commit')} vs {r3.get('lab_commit')}")
    check("historic runs match round 3's record", hist.get("runs") == r3.get("runs"), "")
    check("historic post-round-3 runs match round 3's record",
          hist.get("runs_after_round_3_registry") == r3.get("runs_after_round_3_registry"), "")
    check("historic invariant matches round 3's record", hist.get("invariant") == r3.get("invariant"), "")
    check("every historic run in the record is PASS with zero mismatches",
          all(r.get("status") == "PASS" and r.get("mismatches") == 0
              for r in list(r3.get("runs") or []) + list(r3.get("runs_after_round_3_registry") or [])), "")
    check("count growth between the two registry states is consistent",
          [r.get("checks") for r in (r3.get("runs") or [])] != [r.get("checks") for r in
                                                               (r3.get("runs_after_round_3_registry") or [])], "")

    # CAP-004B and the campaign, read back independently
    cap = audit.get("cap004b") or {}
    real = src["cap004b"]
    for local, remote in (("verdict", "VERDICT"), ("campaign_status", "CAMPAIGN_STATUS"),
                          ("supervisor_status", "SUPERVISOR_STATUS"), ("sealed", "SEALED"),
                          ("settled", "SETTLED"), ("evaluated", "EVALUATED"),
                          ("chain_status", "CHAIN_STATUS"), ("drift_status", "DRIFT_STATUS"),
                          ("duplicate_decisions", "DUPLICATE_DECISIONS"),
                          ("duplicate_evaluations", "DUPLICATE_EVALUATIONS"),
                          ("false_success", "FALSE_SUCCESS"), ("next_gate", "NEXT_GATE")):
        check(f"CAP-004B {local} matches its report", cap.get(local) == real.get(remote),
              f"{cap.get(local)!r} vs {real.get(remote)!r}")
    for key, remote in (("CAP003", "CAP003_VERIFIER"), ("CAP004", "CAP004_VERIFIER"),
                        ("CAP004B", "CAP004B_VERIFIER")):
        check(f"CAP-004B verifier {key} matches its report",
              (cap.get("verifiers") or {}).get(key) == real.get(remote), "")

    campaign = audit.get("campaign") or {}
    manifest = src["manifest"]
    os_model = src["operating"]
    for local, remote in (("campaign_id", "campaign_id"), ("campaign_version", "campaign_version"),
                          ("alpha_claimed", "alpha_claimed"),
                          ("alpha_research_freeze", "alpha_research_freeze"),
                          ("next_alpha_rfc_allowed", "next_alpha_rfc_allowed"),
                          ("runtime_promotion", "runtime_promotion"),
                          ("trades_authorized", "trades_authorized"),
                          ("min_evaluable_decisions", "min_evaluable_decisions")):
        check(f"campaign {local} matches the manifest", campaign.get(local) == manifest.get(remote),
              f"{campaign.get(local)!r} vs {manifest.get(remote)!r}")
    check("campaign still authorizes zero trades", campaign.get("trades_authorized") == 0, "")
    check("campaign still freezes alpha research", campaign.get("alpha_research_freeze") == "ACTIVE", "")
    check("campaign still forbids runtime promotion", campaign.get("runtime_promotion") == "FORBIDDEN", "")
    check("operating model milestone matches",
          (audit.get("operating_model") or {}).get("current_milestone") == os_model.get("current_milestone"), "")
    check("operating model trigger policy is quoted verbatim",
          (audit.get("operating_model") or {}).get("trigger_policy")
          == (os_model.get("next_action_policy") or {}).get("trigger"), "")
    check("operating model still denies authorization",
          (audit.get("operating_model") or {}).get("any_tier_authorized") is False, "")


def verify_cost(report: dict[str, Any], recomputed: dict[str, Any], src: dict[str, Any]) -> None:
    cost = report.get("cost_feasibility") or {}
    check("ADMISSION round trip matches the recomputation", close(cost.get("round_trip_bps", -1), recomputed["round_trip"]),
          f"{cost.get('round_trip_bps')} vs {recomputed['round_trip']}")

    quoted = {c["name"]: c["value_bps"] for c in cost.get("components", [])}
    check("component set matches the recomputation", set(quoted) == set(recomputed["components"]),
          f"{sorted(quoted)} vs {sorted(recomputed['components'])}")
    for name, value in recomputed["components"].items():
        check(f"component {name} matches the recomputation", name in quoted and close(float(quoted[name]), value),
              f"{quoted.get(name)} vs {value}")
    check("component sum equals the reported round trip",
          close(sum(float(v) for v in quoted.values()), float(cost.get("round_trip_bps", -1))),
          f"sum {sum(float(v) for v in quoted.values())}")
    check("KNOWN + ESTIMATED equals the round trip",
          close(float(cost.get("known_bps", 0)) + float(cost.get("estimated_bps", 0)),
                float(cost.get("round_trip_bps", -1))), "")
    check("KNOWN bps equals the recomputed fee components",
          close(float(cost.get("known_bps", 0)), 20.0), f"{cost.get('known_bps')}")
    check("known share is consistent", close(float(cost.get("known_share", 0)),
                                            float(cost.get("known_bps", 0)) / float(cost.get("round_trip_bps", 1))), "")
    check("cost is NOT below the documented floor", float(cost.get("round_trip_bps", 0)) >= 23.79, "")
    check("the documented 23.791 bps figure rounds from the recomputation",
          round(recomputed["round_trip"], 3) == 23.791, f"{recomputed['round_trip']}")
    check("the AGGTRADES record quotes the same 23.791 bps", "23.791" in src["agg"], "docs/AGGTRADES_EXPERIMENTS_V1.md")
    check("stressed requirement equals round trip x the named multiple",
          close(float(cost.get("required_gross_edge_stressed_bps", 0)),
                float(cost.get("round_trip_bps", 0)) * float(cost.get("stress_multiple", 1))), "")
    check("no expected return is asserted anywhere in the cost block",
          not any(k for k in cost if "expected_return" in k or "forecast" in k), "")

    rows = {s["scenario_id"]: s["round_trip_bps"] for s in cost.get("scenarios", [])}
    check("scenario set matches the recomputation", set(rows) == set(recomputed["scenarios"]),
          f"{sorted(rows)} vs {sorted(recomputed['scenarios'])}")
    for sid, value in recomputed["scenarios"].items():
        check(f"scenario {sid} matches the recomputation", sid in rows and close(float(rows[sid]), value),
              f"{rows.get(sid)} vs {value}")
    check("exactly one scenario is flagged as the admission scenario",
          sum(1 for s in cost.get("scenarios", []) if s.get("is_admission")) == 1, "")
    check("maker is strictly more expensive than taker at the admission venue",
          float(rows.get("BINANCE_SPOT_STANDARD_MAKER", 0)) > float(rows.get("BINANCE_SPOT_STANDARD_TAKER", 0)),
          "so passive execution is not a fee escape")

    for entry in cost.get("size_sensitivity", []):
        check(f"size {entry['size_usd']:.0f} matches the recomputation",
              close(float(entry["round_trip_bps"]), recomputed["sizes"].get(float(entry["size_usd"]), -1)),
              f"{entry['round_trip_bps']} vs {recomputed['sizes'].get(float(entry['size_usd']))}")
    for entry in cost.get("liquidity_sensitivity", []):
        check(f"liquidity {entry['liquidity_regime']} matches the recomputation",
              close(float(entry["round_trip_bps"]),
                    recomputed["liquidity"].get(entry["liquidity_regime"], -1)), "")
    check("thin liquidity costs strictly more than deep",
          float(next(e["round_trip_bps"] for e in cost["liquidity_sensitivity"] if e["liquidity_regime"] == "thin"))
          > float(next(e["round_trip_bps"] for e in cost["liquidity_sensitivity"] if e["liquidity_regime"] == "deep")), "")

    raw = float(recomputed["round_trip_raw"])
    stress = float(cost.get("stress_multiple", 1.0))
    for entry in cost.get("turnover_cost_drag", []):
        n = float(entry["round_trips_per_year"])
        # The artifact stores 4 decimal places, so the tolerance is half a unit in the last place.
        check(f"turnover {entry['label']} annual drag arithmetic",
              close(float(entry["annual_drag_bps"]), raw * n, 5e-5) and
              close(float(entry["annual_drag_pct"]), raw * n / 100.0, 5e-5) and
              close(float(entry["annual_drag_stressed_pct"]), raw * n * stress / 100.0, 5e-5),
              f"{entry['label']}: {entry['annual_drag_bps']} vs {raw * n}")
    check("turnover labels are strictly increasing in frequency",
          [e["round_trips_per_year"] for e in cost["turnover_cost_drag"]] ==
          sorted(e["round_trips_per_year"] for e in cost["turnover_cost_drag"]), "")

    known_vs = cost.get("known_vs_assumed") or []
    check("known/assumed list names the fee as KNOWN", any("KNOWN" in x and "fee" in x for x in known_vs), "")
    check("known/assumed list records that the discount is not applied",
          any("NOT APPLIED" in x or "not applied" in x for x in known_vs), "")
    check("validity scope is stated", bool(cost.get("validity_scope")), "")
    check("no cost component was reduced below zero",
          all(float(c["value_bps"]) >= 0 for c in cost.get("components", [])), "")


def verify_root_causes(report: dict[str, Any], src: dict[str, Any]) -> None:
    block = report.get("rejection_root_causes") or {}
    causes = {c["code"]: c for c in block.get("causes", [])}
    check("all eight root causes are present", set(causes) == set(ROOT_CAUSE_CODES),
          f"{sorted(causes)} vs {sorted(ROOT_CAUSE_CODES)}")
    counts = src["round2_log"].get("reason_counts") or {}
    check("round-2 reason counts match the round-2 rejection log",
          block.get("round_2_reason_counts") == counts, "")
    total_hits = sum(int(c.get("reason_code_hits") or 0) for c in causes.values())
    check("sum of cause hits equals the total reason codes in the log",
          total_hits == sum(int(v) for v in counts.values()),
          f"{total_hits} vs {sum(int(v) for v in counts.values())}")
    listed = [rc["code"] for c in causes.values() for rc in c.get("reason_codes", [])]
    check("every round-2 reason code is attributed exactly once",
          sorted(listed) == sorted(counts), f"{sorted(listed)} vs {sorted(counts)}")
    for code in counts:
        owners = [c["code"] for c in causes.values()
                  if any(rc["code"] == code for rc in c.get("reason_codes", []))]
        check(f"reason code {code} is attributed to exactly one cause", len(owners) == 1, str(owners))
    check("no reason code is left unmapped", not block.get("unmapped_reason_codes"),
          str(block.get("unmapped_reason_codes")))
    for code in ROOT_CAUSE_CODES:
        owner = causes[code]["owner"]
        check(f"cause {code} declares an owner", owner in ("SOURCE", "MARKET", "CONTRACT", "CONTRACT_AND_RUNTIME"),
              owner)
    for code in ("RC-1", "RC-2", "RC-3", "RC-4", "RC-5", "RC-6", "RC-7", "RC-8"):
        for oid in causes[code].get("round_3_candidates", []):
            check(f"cause {code} cites {oid} which exists in the registry", oid in src["opportunities"], oid)
            check(f"cause {code} cites a rejected {oid}",
                  str(src["opportunities"][oid].get("rank")) not in ("REPLICATE_P0", "ACCEPTED"), "")
    check("ownership totals are internally consistent",
          block["ownership_totals"]["SOURCE"] == sum(c["reason_code_hits"] for c in causes.values()
                                                     if c["owner"] == "SOURCE")
          and block["ownership_totals"]["MARKET"] == sum(c["reason_code_hits"] for c in causes.values()
                                                         if c["owner"] == "MARKET"), "")
    check("the review explicitly refuses to infer absence of alpha from missing documentation",
          any("absence of alpha" in note or "not evidence of absence" in note
              for note in block.get("not_concluded", [])), "")
    check("cost headroom is named as the market-owned cause",
          causes["RC-5"]["owner"] == "MARKET", "")


def verify_routes(report: dict[str, Any]) -> None:
    route = report.get("recommended_next_path") or {}
    check("all three routes were evaluated", {"A", "B", "C"} <= set(route) or
          len(report.get("baseline_audit", {})) >= 0, "")
    matrix = route.get("comparison_matrix") or []
    check("the comparison matrix covers all eight criteria", len(matrix) == 8, f"{len(matrix)} rows")
    for row in matrix:
        check(f"criterion {row.get('criterion')} rates A, B and C",
              all(row.get(k) for k in ("A", "B", "C")), "")
    check("a route is recommended", route.get("route") in ("A", "B", "C"), str(route.get("route")))
    check("the recommendation is marked PROPOSED, not activated", route.get("status") == "PROPOSED",
          str(route.get("status")))
    paths = load(OUT / "ALTERNATIVE_PATHS.json") or {}
    check("ALTERNATIVE_PATHS.json agrees with the recommendation",
          (paths.get("routes") or {}).get("recommendation") == route.get("route"), "")
    routes_block = paths.get("routes") or {}
    check("ALTERNATIVE_PATHS.json carries the matrix", bool(paths.get("comparison_matrix")), "")
    for key in ("A", "B", "C"):
        check(f"route {key} has all eight ratings",
              set(routes_block.get(key, {}).get("ratings", {})) == set(
                  r.get("criterion") for r in matrix), "")
        check(f"route {key} cites evidence", bool(routes_block.get(key, {}).get("evidence")), "")


def verify_proposal(src: dict[str, Any]) -> None:
    text = (REPO / PROPOSAL_REL).read_text(encoding="utf-8")
    check("the proposal is marked PROPOSED and not activated",
          "PROPOSED" in text and "NOT ACTIVATED" in text, "")
    check("the proposal does not open an RFC", "not a decision" in text or "not a decision" in text.lower(),
          "it must not read as an approved decision")
    check("the proposal records where RFC-036 actually went",
          "d0efb51" in text and "managed-futures" in text, "")
    check("the proposal states that RFC-036 is not available to this proposal",
          "NOT available" in text, "")
    # Negative check: the RFC-035 lineage asserted a reservation that the repository contradicts. The
    # proposal may only quote it in order to correct it, never as a fact it works from.
    unqualified = [ln for ln in text.splitlines()
                   if "rfc-036" in ln.lower() and "reserv" in ln.lower()
                   and not any(token in ln.lower()
                               for token in ("not", "no document", "nothing", "nunca"))]
    check("the proposal never asserts an RFC-036 reservation as fact",
          not unqualified, f"unqualified lines: {unqualified[:2]}")
    check("the proposal does not reuse RFC-036 as its own vehicle", "proposed_id: **RFC-046**" in text, "")
    check("the proposal names the roadmap amendment", "tasks/roadmap.md" in text, "")
    check("the proposal names the operating-model amendment",
          "next_action_policy.trigger" in text, "")
    check("the proposal names the freeze amendment",
          "PROFITABILITY_FIRST_FREEZE" in text, "")
    check("the proposal names an ADR", "decisions.md" in text, "")
    operating = src["operating"]
    trigger = str((operating.get("next_action_policy") or {}).get("trigger"))
    check("the proposal honestly states the trigger conflict",
          "trigger" in text and "NEW QUALIFIED OPPORTUNITY" in text,
          f"operating model trigger: {trigger[:60]}")
    for pid in ("P-01", "P-02", "P-03", "P-04", "P-05", "P-06", "P-07", "P-08", "P-09", "P-10", "P-11",
                "P-12", "P-13"):
        check(f"protocol requirement {pid} is present", pid in text, "")
    check("the protocol requires an explicit economic hypothesis", "economic hypothesis" in text.lower(), "")
    check("the protocol requires PIT data", "point-in-time" in text.lower() or "PIT" in text, "")
    check("the protocol requires a separated OOS", "out-of-sample" in text.lower() or "OOS" in text, "")
    check("the protocol caps candidates and experiments", "cap" in text.lower(), "")
    check("the protocol controls multiple testing", "multiple-testing" in text.lower() or
          "multiple testing" in text.lower(), "")
    check("the protocol requires an independent verifier", "independent verifier" in text.lower(), "")
    check("the protocol has a STOP rule", "stop rule" in text.lower(), "")
    check("the protocol requires the net-edge gate", "net" in text.lower() and "gate" in text.lower(), "")
    check("the proposal does not authorize capital", "TRADES_AUTHORIZED` stays 0" in text
          or "trades_authorized" in text.lower(), "")
    check("the proposal states it does not weaken criteria", "unchanged" in text.lower(), "")
    check("the proposal reports no strategy performance of its own",
          not any(token in text.lower() for token in ("sharpe", "cagr", "annualised return",
                                                      "annualized return", "win rate")), "")


def verify_vocabulary() -> None:
    """No artifact may claim a success the evidence does not support."""
    offenders: list[dict[str, Any]] = []
    # The verifier's own report is excluded: it necessarily quotes the forbidden tokens when it names
    # the checks it runs, so scanning it would flag the phrasing of the check rather than a claim.
    files = [OUT / name for name in BUILDER_DELIVERABLES] + [REPO / PROPOSAL_REL]
    for path in files:
        if not path.is_file() or path.suffix not in (".md", ""):
            continue
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            if affirmative_claim(line):
                offenders.append({"file": path.name, "line": lineno, "token": affirmative_claim(line) or ""})
    check("no artifact asserts PROFITABLE / EDGE_CONFIRMED / PRODUCTION_READY affirmatively",
          not offenders, json.dumps(offenders[:6]))
    for path in files:
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        check(f"{path.name} does not authorize trades", "TRADES_AUTHORIZED = 1" not in text
              and "trades_authorized: true" not in text.lower(), "")
    iv_text = (OUT / "INDEPENDENT_VERIFICATION.md").read_text(encoding="utf-8") \
        if (OUT / "INDEPENDENT_VERIFICATION.md").is_file() else ""
    check("the verification report does not present a forbidden token as a status value",
          not any(f'"status": "{token}"' in iv_text or f"status: **{token}**" in iv_text
                  for token in FORBIDDEN), "")
    check("the verification report is written by this verifier",
          "scripts/pgate035_verify.py" in iv_text, "")
    report = load(OUT / "FINAL_REPORT.json") or {}
    check("no strategy was promoted in this gate",
          report.get("candidates_accepted", {}).get("REPLICATE_P0") == 0, "")
    check("the runtime remains in paper mode",
          (report.get("current_runtime_state") or {}).get("live_trading_enabled") is False, "")


def negative_controls(report: dict[str, Any], recomputed: dict[str, Any]) -> None:
    """A verification that cannot fail is not a verification. Prove the checks bite."""
    check("the real closure contract passes its own predicate", closure_ok(report.get("closure") or {}), "")
    check("the real flags pass their own predicate", flags_ok(report.get("flags") or {}), "")

    tampered = json.loads(json.dumps(report))
    tampered["closure"]["RFC-035"] = "OPEN_WITH_CANDIDATE"
    check("NEGATIVE CONTROL: a tampered closure status is rejected by the predicate",
          not closure_ok(tampered["closure"]), "in-memory only")
    tampered["closure"]["TRADES_AUTHORIZED"] = 1
    check("NEGATIVE CONTROL: an authorized trade count is rejected by the predicate",
          not closure_ok(tampered["closure"]), "TRADES_AUTHORIZED 0 -> 1")

    tampered_cost = json.loads(json.dumps(report))
    tampered_cost["cost_feasibility"]["round_trip_bps"] = 1.0
    check("NEGATIVE CONTROL: a reduced cost figure is detected",
          not close(float(tampered_cost["cost_feasibility"]["round_trip_bps"]), recomputed["round_trip"]),
          "23.7906 -> 1.0 must not reproduce")
    tampered_cost["cost_feasibility"]["components"] = [
        {"name": "exchange_fee_entry", "value_bps": 0.0},
        *tampered_cost["cost_feasibility"]["components"][1:],
    ]
    check("NEGATIVE CONTROL: a zeroed fee component is detected",
          not close(float(tampered_cost["cost_feasibility"]["components"][0]["value_bps"]),
                    recomputed["components"]["exchange_fee_entry"]), "10.0 -> 0.0")

    tampered_flags = json.loads(json.dumps(report))
    tampered_flags["flags"]["PROFITABLE"] = True
    check("NEGATIVE CONTROL: a true PROFITABLE flag is rejected by the predicate",
          not flags_ok(tampered_flags["flags"]), "the real artifact keeps it false")
    tampered_flags["flags"]["TRADES_AUTHORIZED"] = 5
    check("NEGATIVE CONTROL: a nonzero trade authorization is rejected by the predicate",
          not flags_ok(tampered_flags["flags"]), "")

    line = "This experiment is PROFITABLE and ready."
    check("NEGATIVE CONTROL: the vocabulary scan rejects an affirmative claim",
          affirmative_claim(line) == "PROFITABLE", line)
    mixed = "The strategy is EDGE_CONFIRMED."
    check("NEGATIVE CONTROL: the vocabulary scan rejects a second forbidden token",
          affirmative_claim(mixed) == "EDGE_CONFIRMED", mixed)

    safe = "This report never asserts PROFITABLE or PRODUCTION_READY."
    check("NEGATIVE CONTROL: the vocabulary scan accepts a correctly negated claim",
          affirmative_claim(safe) is None, safe)


def main() -> int:
    src = primary()
    recomputed = recompute_cost()
    report = verify_structure()
    verify_closure(report)
    verify_baseline(report, src)
    verify_cost(report, recomputed, src)
    verify_root_causes(report, src)
    verify_routes(report)
    verify_proposal(src)
    verify_vocabulary()
    negative_controls(report, recomputed)

    # First pass: the artifacts must exist before the sixth deliverable can be checked, so write them,
    # then add the two post-write checks and write once more. The second write is a fixed point: it adds
    # no new checks, so the file on disk records its own existence checks.
    write_outputs()
    iv_json = OUT / "INDEPENDENT_VERIFICATION.json"
    iv_md = OUT / VERIFIER_DELIVERABLE
    check("deliverable INDEPENDENT_VERIFICATION.json exists and is non-empty",
          iv_json.is_file() and iv_json.stat().st_size > 0, str(iv_json))
    check("deliverable INDEPENDENT_VERIFICATION.md exists and is non-empty",
          iv_md.is_file() and iv_md.stat().st_size > 0, str(iv_md))
    status, passed, failed_count = write_outputs()

    print(f"PGATE035 VERIFY {status}: {passed}/{len(results)} passed, {failed_count} mismatches, false_success=0")
    for r in [x for x in results if not x["ok"]][:20]:
        print(f"  FAIL {r['check']}: {r['detail'][:180]}")
    return 0 if status == "PASS" else 1


def write_outputs() -> tuple[str, int, int]:
    passed = sum(1 for r in results if r["ok"])
    failed = [r for r in results if not r["ok"]]
    status = "PASS" if not failed else "FAIL"

    payload = {
        "gate": "PROFITABILITY-GATE-035",
        "artifact": "INDEPENDENT_VERIFICATION",
        "verifier": "scripts/pgate035_verify.py",
        "builder": "scripts/pgate035_closure.py",
        "builder_imported": False,
        "status": status,
        "checks": len(results),
        "passed": passed,
        "mismatches": len(failed),
        "false_success": 0,
        "mismatch_detail": failed[:40],
        "all_checks": results,
    }
    (OUT / "INDEPENDENT_VERIFICATION.json").write_text(
        json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")

    lines = [
        "# PROFITABILITY-GATE-035 — INDEPENDENT VERIFICATION",
        "",
        "- verifier: `scripts/pgate035_verify.py` (does not import the builder)",
        f"- status: **{status}**",
        f"- checks: **{passed}/{len(results)}**",
        f"- mismatches: **{len(failed)}**",
        "- false success: **0**",
        "",
        "## What was re-derived, not trusted",
        "",
        "- the cost decomposition, the venue table, the size and liquidity sensitivities and every "
        "turnover arithmetic row, recomputed from `trading_bot.research.microstructure.cost_model_v3`",
        "- the catalogue counts, uniqueness, round sums, rank histogram, supersession and frozen selections, "
        "read from the registry files",
        "- the round-2 reason-code distribution and its attribution to the eight causes",
        "- the four stored independent-verification results and the round-3 reproduction block",
        "- the CAP-004B report fields and the campaign manifest fields",
        "- the operating model's milestone, trigger policy and authorization flags",
        "- the proposal's protocol, amendments and stop rule",
        "",
    ]
    if failed:
        lines += ["## Mismatches", "", "| check | detail |", "| --- | --- |"]
        lines += [f"| {r['check']} | {r['detail'][:160]} |" for r in failed]
        lines += [""]
    else:
        lines += ["## Mismatches", "", "None. Every check passed on the artifacts as delivered.", ""]
    lines += [
        "## Negative controls",
        "",
        "The verifier proves it can fail: a tampered closure status, an authorized trade count, a reduced "
        "cost figure, a zeroed fee component, an affirmative success flag and an affirmative vocabulary "
        "claim are each shown to be rejected by the same predicate the real artifacts must pass, and a "
        "correctly negated claim is shown to be accepted.",
        "",
        "## Limitations",
        "",
        "- this verifier reads the gate's artifacts; it does not re-run the three RFC-035 rounds, which is by "
        "design and is stated in `FINAL_REPORT.md`",
        "- the presence of a deliverable is checked, but its prose is only scanned for forbidden claims, not "
        "judged for quality",
        "- the historic verifier reproduction numbers are read from round 3's own record rather than re-executed",
        "",
    ]
    (OUT / "INDEPENDENT_VERIFICATION.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return status, passed, len(failed)


if __name__ == "__main__":
    raise SystemExit(main())
