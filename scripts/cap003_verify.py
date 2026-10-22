"""CAP-003 independent verification — outcome evaluation, ledger and scorecard.

Builder != verifier.  This script re-derives every invariant from the *written*
artefacts (it never imports the CAP-003 modules or the runner): the evaluator is
deterministic and never self-scores, the ledger lives outside ``reports/``, every
hash recomputes, the chain resolves, costs are shared and ``NO_TRADE`` pays
nothing, no outcome exists before its horizon closed and no matured decision was
skipped, comparator D matches the analyst's own distribution, the scorecard's
numbers recompute, the frozen prompt digest matches the source, the pipeline
self-test is real but does not count as a campaign observation, no RFC-045
exists, no trade is authorized and ``ECONOMIC_STATE.json`` is byte-identical to
the frozen canonical state.

Research only: no orders, no credentials, no capital.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import time
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
OUT = REPO / "reports" / "agentic-campaign-cap003"
REPORTS = REPO / "reports"
DOCS = REPO / "docs" / "research"
LEDGER_ROOT = REPO / "evidence" / "real_decisions"

# --- independently re-declared contract (the verifier must not import) ------- #
LEDGER_VERSION = "REAL_DECISION_LEDGER_V1"
DECISIONS_FILENAME = "decisions.jsonl"
OUTCOMES_FILENAME = "outcomes.jsonl"
EVALUATIONS_FILENAME = "evaluations.jsonl"
HORIZON_SECONDS = {"4H": 14_400, "24H": 86_400, "72H": 259_200}
PROVENANCE_FIELDS = (
    "analyst_id",
    "prompt_version",
    "prompt_digest",
    "model",
    "provider",
    "temperature",
    "schema_version",
    "feature_version",
    "dataset",
)
NOT_MACHINE_CHECKABLE = "NOT_MACHINE_CHECKABLE_TEXT_INVALIDATION"
EVALUATOR_ID = "DecisionOutcomeEvaluator"
EVALUATOR_VERSION = "DECISION_OUTCOME_EVALUATOR_V1"
AGENT_ID = "A_MARKET_ANALYST_V1"
BASELINE_DETERMINISTIC = "B_DETERMINISTIC_TREND_RULE"
BASELINE_BUY_AND_HOLD = "C_BUY_AND_HOLD"
BASELINE_RANDOM = "D_RANDOM_MATCHED_DISTRIBUTION"
SEAL_TIME_COMPARATORS = (BASELINE_DETERMINISTIC, BASELINE_BUY_AND_HOLD)
COST_BPS_PER_SIDE = 10.0
ROUND_TRIP = 2.0 * (COST_BPS_PER_SIDE / 10_000.0)
MIN_EVALUABLE_DECISIONS = 100
CHECKPOINTS = (20, 50, 100)
RANDOM_SEED = 20_261_003
CONCLUSION_NOT_MEASURABLE = "EDGE_NOT_MEASURABLE_NO_EVALUABLE_DECISIONS"
CONCLUSION_INSUFFICIENT = "INSUFFICIENT_SAMPLE_NO_EDGE_VERDICT"
CONCLUSION_NON_POSITIVE = "EDGE_NON_POSITIVE"
CONCLUSION_POSITIVE = "EDGE_POSITIVE_PRELIMINARY_ONLY"
EXPECTED_CONCLUSIONS = {
    CONCLUSION_NOT_MEASURABLE,
    CONCLUSION_INSUFFICIENT,
    CONCLUSION_NON_POSITIVE,
    CONCLUSION_POSITIVE,
}
#: Frozen canonical digest of docs/research/ECONOMIC_STATE.json.
ECONOMIC_STATE_DIGEST = "bda63db863771823501ddb5715e664c686774486882efef4778d53b84be496e8"
PROMPT_VERSION = "MARKET_ANALYST_V1.0"
ANALYST_SOURCE = "src/trading_bot/research/market_analyst_v1.py"
EVALUATOR_SOURCE = "src/trading_bot/research/decision_outcomes.py"
LEDGER_SOURCE = "src/trading_bot/research/decision_ledger.py"
CAMPAIGN_SCRIPT = "scripts/cap003_campaign.py"

#: Code-shaped patterns the campaign must never contain.
FORBIDDEN_CODE_PATTERNS = (
    r"\bcreate_order\b",
    r"\bset_leverage\b",
    r"\bcancel_order\b",
    r"api_secret\s*=",
    r"api_key\s*=",
    r"\bimport\s+openai\b",
    r"\bimport\s+anthropic\b",
    r"\blangchain\b",
    r"\brequests\.post\b",
    r"mcp\.tradingview\.com",
)

CHECKS: list[dict[str, Any]] = []


def check(name: str, ok: bool, detail: str = "") -> bool:
    CHECKS.append({"check": name, "passed": bool(ok), "detail": detail})
    return bool(ok)


def load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def read_lines(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def canonical(payload: Any) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def approx(a: float, b: float, tol: float = 1e-12) -> bool:
    return math.isclose(float(a), float(b), rel_tol=0.0, abs_tol=tol)


def decision_hash_of(entry: dict[str, Any]) -> str:
    sealed = {
        "timestamp": entry["decision_time"],
        "prompt_version": entry["prompt_version"],
        "evidence_snapshot_hash": entry["snapshot_hash"],
        "agent_output": entry["agent_output"],
        "critic_output": entry["critic_output"],
        "decision": entry["decision"],
    }
    return sha256_text(canonical(sealed))


def outcome_hash_of(entry: dict[str, Any]) -> str:
    return sha256_text(canonical({k: v for k, v in entry.items() if k != "outcome_hash"}))


def evaluation_hash_of(entry: dict[str, Any]) -> str:
    return sha256_text(canonical({k: v for k, v in entry.items() if k != "evaluation_hash"}))


def frozen_prompt_digest() -> str:
    path = REPO / ANALYST_SOURCE
    if not path.is_file():
        return ""
    match = re.search(r'SYSTEM_PROMPT = """(.*?)"""', path.read_text(encoding="utf-8"), re.DOTALL)
    return sha256_text(match.group(1)) if match else ""


def main() -> int:
    now = int(time.time())
    decisions = read_lines(LEDGER_ROOT / DECISIONS_FILENAME)
    outcomes = read_lines(LEDGER_ROOT / OUTCOMES_FILENAME)
    evaluations = read_lines(LEDGER_ROOT / EVALUATIONS_FILENAME)

    # --- artifacts ----------------------------------------------------------- #
    for path in (
        REPORTS / "CAP003_CAMPAIGN_REPORT.json",
        REPORTS / "ALPHA_SCORECARD.json",
        OUT / "LEDGER_CHAIN.json",
        OUT / "PIPELINE_SELFTEST.json",
    ):
        check(f"artifact present: {path.name}", path.is_file())
    report = load(REPORTS / "CAP003_CAMPAIGN_REPORT.json")
    scorecard = load(REPORTS / "ALPHA_SCORECARD.json")
    chain = load(OUT / "LEDGER_CHAIN.json")
    selftest = load(OUT / "PIPELINE_SELFTEST.json")

    # --- evaluator is deterministic, separate and not self-scoring ---------- #
    evaluator_path = REPO / EVALUATOR_SOURCE
    check("decision outcome evaluator exists", evaluator_path.is_file())
    evaluator_text = evaluator_path.read_text(encoding="utf-8") if evaluator_path.is_file() else ""
    check("evaluator declares its frozen identity", EVALUATOR_ID in evaluator_text)
    check("evaluator version is declared", EVALUATOR_VERSION in evaluator_text)
    check("evaluator refuses a premature horizon", "HorizonNotMaturedError" in evaluator_text)
    check("evaluator never guesses a free-text invalidation", NOT_MACHINE_CHECKABLE in evaluator_text)
    ledger_text = (REPO / LEDGER_SOURCE).read_text(encoding="utf-8")
    check("ledger refuses a decision without provenance", "provenance_missing" in ledger_text)
    check("ledger is append-only by construction", "open(\"a\"" in ledger_text)
    check("ledger lives outside reports/", "reports" not in str(LEDGER_ROOT).lower(), str(LEDGER_ROOT))
    campaign_text = (REPO / CAMPAIGN_SCRIPT).read_text(encoding="utf-8")
    code_hits = [p for p in FORBIDDEN_CODE_PATTERNS if re.search(p, campaign_text)]
    check("campaign contains no order / credential / LLM code", code_hits == [], str(code_hits))

    # --- the frozen prompt is really the one in the source ------------------ #
    digest = frozen_prompt_digest()
    check("frozen prompt digest recomputes from source", bool(digest), digest[:16])
    check(
        "campaign recorded the frozen prompt digest",
        report["market_analyst"]["prompt_digest"] == digest,
        f"{report['market_analyst']['prompt_digest'][:16]} vs {digest[:16]}",
    )
    check("campaign uses the frozen prompt version", report["market_analyst"]["version"] == PROMPT_VERSION)
    for entry in decisions:
        check(
            f"sealed decision uses the frozen prompt version ({entry['decision_id'][:12]})",
            entry["prompt_version"] == PROMPT_VERSION,
            str(entry["prompt_version"]),
        )

    # --- provenance: no unreproducible observation may enter the campaign ---- #
    check("the campaign has at least one decision", len(decisions) >= 1, str(len(decisions)))
    for entry in decisions:
        provenance = entry.get("provenance", {})
        blanks = [f for f in PROVENANCE_FIELDS if not str(provenance.get(f, "")).strip()]
        check(
            f"provenance complete for {entry['decision_id'][:12]}",
            not blanks,
            str(blanks),
        )
    check(
        "sampling parameters are declared honestly, never invented",
        all(str(e["provenance"].get("temperature", "")) for e in decisions),
    )

    # --- decision chain: snapshot -> decision ------------------------------- #
    decision_hashes = {str(entry["decision_hash"]) for entry in decisions}
    for entry in decisions:
        label = entry["decision_id"][:12]
        check(f"decision hash recomputes ({label})", decision_hash_of(entry) == entry["decision_hash"])
        check(
            f"decision id derives from the hash ({label})",
            entry["decision_id"] == "DEC-" + str(entry["decision_hash"])[:16],
        )
        check(
            f"snapshot re-digests to its hash ({label})",
            sha256_text(canonical(entry["snapshot"])) == entry["snapshot_hash"],
        )
        check(f"raw evidence hash is a digest ({label})", len(str(entry["raw_evidence_hash"])) == 64)
        check(f"ledger version is declared ({label})", entry["ledger_version"] == LEDGER_VERSION)
        check(
            f"horizon is in the frozen set ({label})",
            entry["horizon"] in HORIZON_SECONDS,
            str(entry["horizon"]),
        )
        check(
            f"decision time sits on a 4H boundary ({label})",
            int(entry["decision_time"]) % 14_400 == 0,
            str(entry["decision_time"]),
        )
        check(
            f"sealed answer time matches the seal ({label})",
            int(entry["agent_output"]["analyst"]["decision_time"]) == int(entry["decision_time"]),
        )

    # --- outcome chain: decision -> outcome --------------------------------- #
    check("no duplicate decision hashes", len(decision_hashes) == len(decisions))
    outcome_keys = {(str(e["decision_id"]), str(e["horizon"])) for e in outcomes}
    check("no duplicate outcome keys", len(outcome_keys) == len(outcomes))
    evaluation_keys = {(str(e["decision_id"]), str(e["horizon"])) for e in evaluations}
    check("no duplicate evaluation keys", len(evaluation_keys) == len(evaluations))

    by_decision = {str(entry["decision_id"]): entry for entry in decisions}
    for entry in outcomes:
        label = f"{entry['decision_id'][:12]}:{entry['horizon']}"
        check(f"outcome hash recomputes ({label})", outcome_hash_of(entry) == entry["outcome_hash"])
        check(f"outcome links to a known decision ({label})", str(entry["decision_hash"]) in decision_hashes)
        check(f"outcome was produced by the evaluator ({label})", entry["evaluator"] == EVALUATOR_ID)
        check(
            f"outcome uses the evaluator version ({label})",
            entry["evaluator_version"] == EVALUATOR_VERSION,
        )
        gross = float(entry["gross_return"])
        costs = float(entry["costs"])
        net = float(entry["net_return"])
        check(f"net equals gross minus costs ({label})", approx(net, gross - costs))
        # The label each direction must carry is pinned by the two branches below,
        # which re-derive it from the frozen rule.  The assertion that used to sit
        # here (``decision != outcome``) contradicted that rule for the legitimate
        # NO_TRADE sleeve — the frozen evaluator labels it ``NO_TRADE`` — and went
        # unnoticed only because the ledger held no outcomes when it was written.
        check(
            f"outcome names one of the frozen outcomes ({label})",
            entry["outcome"] in ("WIN", "LOSS", "FLAT", "NO_TRADE"),
        )
        check(
            f"decision names one of the frozen directions ({label})",
            entry["decision"] in ("LONG", "SHORT", "NO_TRADE"),
        )
        if entry["decision"] == "NO_TRADE":
            check(f"NO_TRADE pays exactly zero ({label})", costs == 0.0 and gross == 0.0)
            check(f"NO_TRADE is labelled NO_TRADE ({label})", entry["outcome"] == "NO_TRADE")
        else:
            check(f"an active sleeve pays the shared round trip ({label})", approx(costs, ROUND_TRIP))
            expected_gross = (
                float(entry["exit_price"]) / float(entry["entry_price"]) - 1.0
                if entry["decision"] == "LONG"
                else 1.0 - float(entry["exit_price"]) / float(entry["entry_price"])
            )
            check(f"gross recomputes from the reference prices ({label})", approx(gross, expected_gross))
            expected_label = "WIN" if net > 0.0 else ("LOSS" if net < 0.0 else "FLAT")
            check(f"outcome label matches the net sign ({label})", entry["outcome"] == expected_label)
            check(
                f"direction correctness matches the gross sign ({label})",
                bool(entry["direction_correct"]) == bool(gross > 0.0),
            )
        check(f"evidence hash is a digest ({label})", len(str(entry["evidence_hash"])) == 64)
        check(
            f"invalidation is honestly not machine-checkable ({label})",
            entry["invalidation_hit"] is None and entry["invalidation_rule"] == NOT_MACHINE_CHECKABLE,
            str(entry["invalidation_rule"]),
        )

    # --- causality: no premature outcome, no matured decision skipped ------- #
    for entry in outcomes:
        label = f"{entry['decision_id'][:12]}:{entry['horizon']}"
        expected_exit = int(entry["decision_time"]) + HORIZON_SECONDS[str(entry["horizon"])]
        check(f"outcome stops exactly at the horizon ({label})", int(entry["exit_close_time"]) == expected_exit)
        check(f"outcome was not written before maturity ({label})", expected_exit <= now)
        check(
            f"the entry bar closes at the decision time ({label})",
            int(entry["entry_close_time"]) == int(entry["decision_time"]),
        )
    settled_keys = outcome_keys
    for entry in decisions:
        key = (str(entry["decision_id"]), str(entry["horizon"]))
        if key in settled_keys:
            continue
        label = f"{entry['decision_id'][:12]}:{entry['horizon']}"
        expected_exit = int(entry["decision_time"]) + HORIZON_SECONDS[str(entry["horizon"])]
        check(f"no matured decision was left unsettled ({label})", expected_exit > now, str(expected_exit - now))

    # --- evaluation chain: outcome -> evaluation ---------------------------- #
    outcome_hashes = {str(entry["outcome_hash"]) for entry in outcomes}
    for entry in evaluations:
        label = f"{entry['decision_id'][:12]}:{entry['horizon']}"
        check(f"evaluation hash recomputes ({label})", evaluation_hash_of(entry) == entry["evaluation_hash"])
        check(f"evaluation links to a known outcome ({label})", str(entry["outcome_hash"]) in outcome_hashes)
        check(
            f"evaluation joins the seal and the outcome ({label})",
            str(entry["decision_hash"]) in decision_hashes,
        )
        produced = {str(item["baseline_id"]) for item in entry["comparisons"]}
        check(
            f"seal-time comparators are exactly B and C ({label})",
            produced == set(SEAL_TIME_COMPARATORS),
            str(sorted(produced)),
        )
        check(
            f"comparator D is not baked into an immutable evaluation ({label})",
            BASELINE_RANDOM not in produced,
        )
        check(
            f"evaluation shares the round trip with the outcome ({label})",
            approx(entry["round_trip_cost"], ROUND_TRIP),
        )

    # --- comparator D matches the analyst's own distribution --------------- #
    directions = [str(entry["decision"]) for entry in evaluations]
    observed = {direction: directions.count(direction) for direction in ("LONG", "SHORT", "NO_TRADE")}
    if scorecard["n_decisions_evaluated"]:
        random_stats = scorecard["comparators"][BASELINE_RANDOM]
        check("comparator D carries its frozen seed", random_stats["seed"] == RANDOM_SEED)
        check(
            "comparator D matches the analyst's own distribution",
            random_stats["distribution"] == observed,
            f"{random_stats['distribution']} vs {observed}",
        )
        check(
            "comparator D is an exact permutation of the analyst's directions",
            sorted(random_stats["assignment"]) == sorted(directions),
        )

    # --- scorecard numbers recompute --------------------------------------- #
    check("scorecard names the agent sleeve", scorecard["agent"]["id"] == AGENT_ID)
    check(
        "scorecard counts match the ledger",
        scorecard["n_decisions_evaluated"] == len(evaluations),
        f"{scorecard['n_decisions_evaluated']} vs {len(evaluations)}",
    )
    if evaluations:
        agent_mean = sum(float(e["net_return"]) for e in evaluations) / len(evaluations)
        check("scorecard agent expectancy recomputes", approx(scorecard["agent"]["mean_net_return"], agent_mean))
        for baseline_id in SEAL_TIME_COMPARATORS:
            values = [
                float(item["net_return"])
                for e in evaluations
                for item in e["comparisons"]
                if str(item["baseline_id"]) == baseline_id and item["available"]
            ]
            comparator_mean = scorecard["comparators"][baseline_id]["mean_net_return"]
            check(
                f"scorecard comparator mean recomputes ({baseline_id})",
                values == [] or approx(comparator_mean, sum(values) / len(values)),
            )
            edge = scorecard["incremental_edges"][baseline_id]
            check(
                f"scorecard edge recomputes ({baseline_id})",
                edge is None or approx(edge, scorecard["agent"]["mean_net_return"] - comparator_mean),
            )
    n_evaluated = int(scorecard["n_decisions_evaluated"])
    expected_conclusion = (
        CONCLUSION_NOT_MEASURABLE
        if n_evaluated == 0
        else (CONCLUSION_INSUFFICIENT if n_evaluated < MIN_EVALUABLE_DECISIONS else None)
    )
    check(
        "scorecard conclusion matches the declared sample floor",
        expected_conclusion is None or scorecard["gate"]["conclusion"] == expected_conclusion,
        f"n={n_evaluated} conclusion={scorecard['gate']['conclusion']}",
    )
    check("scorecard conclusion is a declared value", scorecard["gate"]["conclusion"] in EXPECTED_CONCLUSIONS)
    check(
        "scorecard never claims a positive edge below the sample floor",
        not (n_evaluated < MIN_EVALUABLE_DECISIONS and scorecard["gate"]["conclusion"] == CONCLUSION_POSITIVE),
    )
    if n_evaluated:
        reached = [p for p in CHECKPOINTS if n_evaluated >= p]
        check(
            "scorecard checkpoint matches the sample",
            scorecard["sample"]["checkpoint_reached"] == (max(reached) if reached else 0),
        )
    check("checkpoints are 20/50/100", tuple(scorecard["sample"]["checkpoints"]) == CHECKPOINTS)
    check("ALPHA_SCORECARD claims no alpha", scorecard["alpha_claimed"] is False)
    check("ALPHA_SCORECARD claims no profitability", scorecard["profitability_status"] == "NOT_DEMONSTRATED")
    check("ALPHA_SCORECARD claims no business evidence", scorecard["business_evidence"] is False)
    check("AGENTIC_DECISION_EDGE KPI is still zero", scorecard["kpi_agentic_decision_edge"] == 0)

    # --- pipeline self-test is real and does not count --------------------- #
    check("pipeline self-test ran on real data", selftest.get("status") in ("CHAIN_OK", "NOT_MATURED"))
    check("pipeline self-test does not count toward the campaign", selftest["counts_toward_campaign"] is False)
    check("pipeline self-test invoked no LLM", selftest["llm_invoked"] is False)
    check("pipeline self-test is not a real agent decision", selftest["agent_decision_real"] is False)
    if selftest.get("status") == "CHAIN_OK":
        check("self-test chain checks all pass", all(selftest["checks"].values()), str(selftest["checks"]))
        check("self-test is not written into the ledger", selftest["outcome"]["decision_id"] not in by_decision)

    # --- governance --------------------------------------------------------- #
    check("ledger chain is intact", chain["status"] == "INTACT", str(chain["broken"]))
    check("no duplicate decision hash in the ledger", chain["dup_decision_hashes"] == [])
    check("no duplicate outcome key in the ledger", chain["dup_outcome_keys"] == [])
    check("no duplicate evaluation key in the ledger", chain["dup_evaluation_keys"] == [])
    check("G_TV_CONTEXT stays NOT_VERIFIED", report["g_tv_context"] == "NOT_VERIFIED")
    check("G_REAL_MARKET_CONTEXT passed", report["g_real_market_context"] == "PASS")
    check("no trade authorized", report["trades_authorized"] == 0)
    check("no alpha claimed", report["alpha_claimed"] == "NONE")
    check("freeze stays ACTIVE", report["alpha_research_freeze"] == "ACTIVE")
    check("no alpha RFC is allowed", report["next_alpha_rfc_allowed"] == "NO")

    economic_path = DOCS / "ECONOMIC_STATE.json"
    economic = load(economic_path)
    check("freeze is ACTIVE in the canonical state", economic["alpha_research_freeze"] == "ACTIVE")
    check("next_alpha_rfc_allowed is still false", economic["next_alpha_rfc_allowed"] is False)
    check("PAPER stays NOT_AUTHORIZED", economic["paper_status"] == "NOT_AUTHORIZED")
    check("LIVE stays NOT_AUTHORIZED", economic["live_status"] == "NOT_AUTHORIZED")
    check(
        "ECONOMIC_STATE.json is byte-identical to the frozen canonical state",
        sha256_file(economic_path) == ECONOMIC_STATE_DIGEST,
        sha256_file(economic_path),
    )

    rfc045 = sorted(path.name for path in DOCS.rglob("*RFC045*"))
    check("no RFC-045 artifact exists", rfc045 == [], str(rfc045))

    # --- FALSE_SUCCESS (independent recomputation) -------------------------- #
    false_success: list[str] = []
    if chain["status"] != "INTACT":
        false_success.append("the ledger chain is broken")
    if any(decision_hash_of(e) != e["decision_hash"] for e in decisions):
        false_success.append("an unsealed/tampered decision was accepted into the ledger")
    if any(not all(str(e.get("provenance", {}).get(f, "")).strip() for f in PROVENANCE_FIELDS) for e in decisions):
        false_success.append("a decision without complete provenance entered the campaign")
    if any(int(e["exit_close_time"]) > now for e in outcomes):
        false_success.append("an outcome was recorded before its horizon closed")
    if any(str(e["decision"]) == "NO_TRADE" and float(e["costs"]) != 0.0 for e in outcomes):
        false_success.append("a cash sleeve was charged a cost")
    if scorecard["kpi_agentic_decision_edge"] != 0:
        false_success.append("an edge KPI was raised off zero without business evidence")
    if sha256_file(economic_path) != ECONOMIC_STATE_DIGEST:
        false_success.append("the canonical economic state was modified")
    if report["g_tv_context"] == "PASS":
        false_success.append("G_TV_CONTEXT claimed PASS without a credentialled real snapshot")
    if report["trades_authorized"] != 0:
        false_success.append("a trade was authorized by a research campaign")
    if rfc045:
        false_success.append("RFC-045 exists despite the freeze")
    if selftest.get("counts_toward_campaign") is not False:
        false_success.append("the deterministic self-test was counted as a campaign observation")

    passed = sum(1 for entry in CHECKS if entry["passed"])
    total = len(CHECKS)
    mismatches = [entry for entry in CHECKS if not entry["passed"]]
    status = "PASS" if not mismatches and not false_success else "FAIL"

    payload = {
        "campaign": "CAP-003 REAL DECISION OUTCOME & ALPHA EVALUATION",
        "status": status,
        "passed": passed,
        "total": total,
        "mismatches": len(mismatches),
        "mismatch_detail": mismatches,
        "false_success": len(false_success),
        "false_success_detail": false_success,
        "ledger": {
            "root": str(LEDGER_ROOT),
            "n_decisions": len(decisions),
            "n_outcomes": len(outcomes),
            "n_evaluations": len(evaluations),
        },
        "checks": CHECKS,
    }
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "CAP003_VERIFICATION.json").write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )

    lines = [
        "CAP-003 INDEPENDENT VERIFICATION",
        "",
        f"STATUS = {status}",
        f"CHECKS = {passed}/{total}",
        f"MISMATCHES = {len(mismatches)}",
        f"FALSE_SUCCESS = {len(false_success)}",
        "",
    ]
    for bad in mismatches:
        lines.append(f"- MISMATCH: {bad['check']} — {bad['detail']}")
    for trigger in false_success:
        lines.append(f"- FALSE_SUCCESS: {trigger}")
    lines.append("")
    (OUT / "CAP003_VERIFICATION.md").write_text("\n".join(lines), encoding="utf-8")

    report["verification"] = {
        "status": status,
        "passed": passed,
        "total": total,
        "mismatches": len(mismatches),
        "false_success": len(false_success),
        "verifier": "scripts/cap003_verify.py",
    }
    (REPORTS / "CAP003_CAMPAIGN_REPORT.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )

    print("CAP-003 INDEPENDENT VERIFICATION")
    print(f"STATUS = {status}")
    print(f"CHECKS = {passed}/{total}")
    print(f"MISMATCHES = {len(mismatches)}")
    print(f"FALSE_SUCCESS = {len(false_success)}")
    for bad in mismatches:
        print(f"  MISMATCH: {bad['check']} — {bad['detail']}")
    for trigger in false_success:
        print(f"  FALSE_SUCCESS: {trigger}")
    return 0 if status == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
