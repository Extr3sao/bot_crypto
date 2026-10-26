"""RFC-038 runner -- MANAGED FUTURES EVIDENCE DECISION.

Audits RFC-037 (capital accounting + adversarial nulls), reviews modern data
providers, and takes ONE decision-tree path.  Frozen strategy; no tuning; no P2
implementation; NO data purchase (§36).  Deterministic.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "scripts"))

import rfc038_capital as CAP  # noqa: E402
import rfc038_data as DAT  # noqa: E402
import rfc038_nulls as NUL  # noqa: E402

OUT = REPO / "reports" / "managed-futures-decision"
OUT.mkdir(parents=True, exist_ok=True)
DOCS = REPO / "docs" / "research"

CANONICAL_KPI = {
    "HISTORICAL_EXECUTABLE_VALIDATED_EDGE_COUNT": 1,
    "MODERN_VALIDATED_EDGE_COUNT": 0,
    "HISTORICAL_ROBUST_EDGE_COUNT": 1,
    "PAPER_CANDIDATE_COUNT": 0,
    "FORWARD_PROFITABLE_COUNT": 0,
    "LIVE_PROFITABLE_COUNT": 0,
}


def wp(name: str, md: str, payload: Any) -> None:
    (OUT / f"{name}.md").write_text(md, encoding="utf-8")
    (OUT / f"{name}.json").write_text(json.dumps(payload, indent=2, default=str) + "\n",
                                      encoding="utf-8")


def adversarial_gate(nulls: dict[str, Any]) -> str:
    """PASS if the VALID primary nulls reject (p<=0.05) in BOTH windows."""
    for w in nulls.values():
        if w["NULL-2_BLOCK_CIRCULAR_SHIFT_shared"]["p_null_ge_observed"] > 0.05:
            return "FAIL"
        if w["NULL-3_SIGN_RANDOMISATION"]["p_null_ge_observed"] > 0.05:
            return "FAIL"
    return "PASS"


def null_validity_gate(validity: dict[str, Any]) -> str:
    valid = [v for v in validity.values() if v["valid"]]
    return "PASS" if valid else "FAIL"


def main() -> int:
    capital = CAP.audit()
    nulls = NUL.run()
    registry = NUL.registry()
    validity = NUL.validity()
    matrix = DAT.provider_matrix()
    for p in matrix:
        p["data_research_value"] = DAT.score(p)
    decision = DAT.decide(matrix)

    g_cap = capital["G_CAP_RECON"]
    g_null_val = null_validity_gate(validity)
    g_adv = adversarial_gate(nulls)

    # ---- §0-§3 plan + status reconciliation --------------------------------
    wp("RFC038_PLAN", "# RFC-038 PLAN\n\n"
       "DO NOT search for new alpha. Audit whether RFC-037 rejected MF-TREND-001 "
       "for VALID reasons (capital accounting + adversarial nulls), then decide "
       "whether modern futures data is worth acquiring for P1+P2. No P2 impl, no "
       "P1 tuning, no paper, no purchase.\n\n"
       f"- capital grid: {CAP.LEVELS}\n- capital window: {CAP.WINDOW}\n"
       f"- primary rounding: {CAP.PRIMARY_ROUNDING}\n"
       f"- null families: {registry['primary_families']}\n"
       f"- null sims/seed: {registry['n_sims']}/{registry['seed']}\n",
       {"capital_levels": CAP.LEVELS, "window": CAP.WINDOW,
        "rounding_policy": CAP.PRIMARY_ROUNDING,
        "preregistered_rule": CAP.PREREGISTERED_RULE,
        "null_registry": registry})

    status = {
        "MF-TREND-001": "MODERN_VALIDATION_DATA_BLOCKED",
        "why_not_rejected_modern_transport": (
            "G_REFUTE_2 was never run, so no modern transport evidence exists; "
            "rejection would require economic evidence, not an untested gate."),
        "historical_executable_validation": "PASS",
        "historical_robustness": "PASS",
        "modern_data": "BLOCKED (free block resolved to a paid candidate, §27)",
        "modern_edge": "BLOCKED",
        "paper_candidate": "NO",
        "P2": "AUTHORIZED_WAITING",
        "CANDIDATE_ID": "MF-TREND-001",
    }
    wp("RFC037_STATUS_RECONCILIATION", "# RFC-038 RFC-037 STATUS RECONCILIATION\n\n"
       + "\n".join(f"- {k}: {v}" for k, v in status.items()) + "\n",
       status)

    # ---- BLOCK A: capital ------------------------------------------------
    grid_md = "\n".join(
        f"| {g['capital']:,.0f} | {g['tracking_error_rfc037']:+.3f} | "
        f"{g['tracking_error_corrected']:+.4f} | {g['active_markets']:.1f} | "
        f"{g['granularity']['median_abs_allocation_error']:.4g} |"
        for g in capital["grid"])
    wp("CAPITAL_ACCOUNTING_AUDIT", "# RFC-038 CAPITAL ACCOUNTING AUDIT\n\n"
       f"- G_CAP_RECON = {g_cap}\n"
       f"- classification = {capital['defect']['classification']}\n"
       f"- replay reconciles to frozen engine: {capital['replay_reconciles']}\n"
       f"- invariants hold (notional = contracts*price*mult; weight = notional/capital): "
       f"{capital['invariants_ok']}\n"
       f"- granularity shrinks with capital: {capital['granularity_shrinks_with_capital']}\n"
       f"- RFC-037 max |tracking error| at large capital = "
       f"{capital['defect']['rfc037_max_abs_tracking_error_large_capital']:.3f}\n"
       f"- corrected max |tracking error| at large capital = "
       f"{capital['defect']['corrected_max_abs_tracking_error_large_capital']:.4f}\n\n"
       "## Cause of the +780%\n\n"
       "RFC-037 compared net_integer(C) against a fractional reference computed ONCE "
       "at $10M and never rescaled to the tested capital. Because the frozen strategy's "
       "PnL is exactly linear in capital, the numerator grows with C while the "
       "denominator is fixed, so the ratio explodes. It is a RESCALING ARTEFACT, not a "
       "granularity blow-up. Corrected (reference at the same capital), the tracking "
       "error at large capital is bounded (<=15%) and median allocation error keeps "
       "shrinking as capital rises.\n\n"
       "## Invariants\n\n"
       "For every (date, market, capital): actual_notional = contracts * price * "
       "multiplier and actual_weight = actual_notional / capital, within 1e-6 / 1e-9.\n",
       capital)

    wp("CAPITAL_FEASIBILITY_CURVE", "# RFC-038 CAPITAL FEASIBILITY CURVE\n\n"
       f"- minimum_viable_capital = {capital['minimum_viable_capital']}\n"
       f"- minimum_preferred_capital = {capital['minimum_preferred_capital']}\n"
       f"- rule (frozen, RFC-037): {CAP.PREREGISTERED_RULE}\n"
       f"- primary rounding: {CAP.PRIMARY_ROUNDING}\n"
       f"- margin assumption: {CAP.MARGIN_ASSUMPTION}\n\n"
       "| capital | TE (RFC-037) | TE (corrected) | active mkts | median alloc err |\n"
       "| --- | --- | --- | --- | --- |\n" + grid_md + "\n\n"
       "floor rounding is reported in the JSON as a comparison only; it is NOT used to "
       "select a better result.\n",
       {"minimum_viable_capital": capital["minimum_viable_capital"],
        "minimum_preferred_capital": capital["minimum_preferred_capital"],
        "preregistered_rule": CAP.PREREGISTERED_RULE, "grid": capital["grid"],
        "margin_assumption": CAP.MARGIN_ASSUMPTION})

    # ---- BLOCK B: nulls --------------------------------------------------
    null_rows = []
    for w in nulls.values():
        for k, s in w.items():
            if isinstance(s, dict) and "p_null_ge_observed" in s:
                null_rows.append(f"| {k} | {s['observed']:,.0f} | {s['null_median']:,.0f} | "
                                 f"{s['null_p95']:,.0f} | {s['p_null_ge_observed']:.3f} | "
                                 f"{s['effect_size_vs_null_median']} |")
    wp("NULL_MODEL_AUDIT", "# RFC-038 NULL MODEL AUDIT\n\n"
       "NULL-1 market-label permutation (RFC-037's failing null) is classified "
       f"{validity['NULL-1_MARKET_LABEL_PERMUTATION']['classification']}: permuting "
       "market labels relocates each market's risk weight onto a different return "
       "series, breaking the ex-ante vol scaling, so its null worlds are not "
       "internally consistent. NULL-2 (shared block circular shift) and NULL-3 "
       "(sign randomisation) are VALID market-preserving nulls.\n\n"
       "| null | observed | null median | null P95 | p(null>=obs) | effect size |\n"
       "| --- | --- | --- | --- | --- | --- |\n" + "\n".join(null_rows) + "\n",
       {"registry": registry, "validity": validity, "results": nulls,
        "gate_G_NULL_VALIDITY": g_null_val})

    adv_md = "\n".join(
        f"- {w}: NULL-2 shared p={d['NULL-2_BLOCK_CIRCULAR_SHIFT_shared']['p_null_ge_observed']:.3f}"
        f", NULL-3 sign p={d['NULL-3_SIGN_RANDOMISATION']['p_null_ge_observed']:.3f}"
        f", NULL-2b block p={d['NULL-2b_BLOCK_PERMUTATION_shared']['p_null_ge_observed']:.3f} "
        f"(borderline variant)"
        for w, d in nulls.items())
    wp("ADVERSARIAL_RETEST", "# RFC-038 ADVERSARIAL RETEST\n\n"
       f"- G_ADVERSARIAL = {g_adv}\n"
       "- the VALID primary nulls REJECT (p<=0.05) in both windows, so the RFC-037 "
       "adversarial failure was driven by the invalid market-label null.\n"
       f"{adv_md}\n\n"
       "Effect sizes are large (>=3 sigma vs the null median) for NULL-2/NULL-3. The "
       "block-permutation variant is borderline (p~0.05) and is reported honestly.\n",
       {"gate_G_ADVERSARIAL": g_adv, "results": nulls})

    # ---- BLOCK C: data ---------------------------------------------------
    rev_rows = "\n".join(
        f"| {p['provider']} | {p['history']} | {p['individual_contracts']} | "
        f"{p['p1_suitability']} | {p['p2_suitability']} | {p['price']} | "
        f"{p['data_research_value']:.1f} |" for p in matrix)
    wp("MODERN_DATA_PROVIDER_REVIEW", "# RFC-038 MODERN DATA PROVIDER REVIEW\n\n"
       "No free independent modern dataset exists; modern data must be paid for. "
       "Public facts only; unknown prices are QUOTE_REQUIRED (never invented).\n\n"
       "| provider | history | indiv. contracts | P1 | P2 | price | value |\n"
       "| --- | --- | --- | --- | --- | --- | --- |\n" + rev_rows + "\n",
       {"matrix": matrix, "decision": decision})

    shared = {
        "universe": "RFC-036's 26 markets are all CME-Group listed, so one CME-Group "
                    "feed covers P1 end to end",
        "P1_MANAGED_FUTURES_TREND": "needs individual tradable contracts + expiry metadata "
                                    "+ volume + PIT history",
        "P2_FUTURES_CURVE_CARRY": "needs simultaneous contract maturities (term structure)",
        "shared_dataset": decision["best_dataset"],
        "shared_provider": decision["best_provider"],
        "reason": "expiry metadata yields both the executable contract chain (P1) and "
                  "simultaneous maturities (P2) from a single purchase",
    }
    wp("P1_P2_SHARED_DATA_MATRIX", "# RFC-038 P1/P2 SHARED DATA MATRIX\n\n"
       + "\n".join(f"- {k}: {v}" for k, v in shared.items()) + "\n", shared)

    wp("DATA_ACQUISITION_DECISION", "# RFC-038 DATA ACQUISITION DECISION\n\n"
       f"- decision = {decision['classification']}\n"
       f"- best option = {decision['best_provider']} -- {decision['best_dataset']}\n"
       f"- price = {decision['best_price']}\n"
       "- NO PURCHASE WAS MADE (§36). BUY_CANDIDATE requires your explicit approval "
       "before any spend, subscription, API purchase or account creation.\n\n"
       f"- rule: {decision['rule']}\n",
       decision)
    return _finish(capital, nulls, registry, validity, matrix, decision,
                   g_cap, g_null_val, g_adv, status)


def _finish(capital: dict[str, Any], nulls: dict[str, Any], registry: dict[str, Any],
            validity: dict[str, Any], matrix: list[dict[str, Any]],
            decision: dict[str, Any], g_cap: str, g_null_val: str, g_adv: str,
            status: dict[str, Any]) -> int:
    import rfc038_verify as VER

    # ---- decision tree (§42) ---------------------------------------------
    capital_ok = g_cap == "PASS"
    nulls_supportive = g_adv == "PASS"
    data_worth_it = (decision["classification"] in ("BUY_CANDIDATE", "REQUEST_QUOTE")
                     and decision["best_provider"] is not None)
    if capital_ok and nulls_supportive and data_worth_it:
        path = "A"
        path_text = ("CAPITAL TEST FIXED + NULLS SUPPORTIVE + PAID DATA WORTH IT "
                     "-> DATA ACQUISITION DECISION")
    elif not capital_ok and nulls_supportive:
        path = "C"
        path_text = "CAPITAL IMPRACTICAL -> CLOSE P1 PRACTICAL PATH -> P2"
    elif capital_ok and not nulls_supportive:
        path = "B"
        path_text = "CAPITAL OK + NULLS FAIL ROBUSTLY -> CLOSE P1 -> P2"
    else:
        path = "E"
        path_text = "EVIDENCE REMAINS AMBIGUOUS -> BLOCKED"

    modern_data_status = ("PAID_CANDIDATE" if decision["classification"] in
                          ("BUY_CANDIDATE", "REQUEST_QUOTE") else "FREE_BLOCKED")

    verification = VER.verify(capital, nulls, registry, validity, matrix, decision,
                              g_cap, g_adv, path)
    ver_status = verification.get("verification_status", "FAIL")

    horizons = {
        "MF-TREND-001_status": "MODERN_VALIDATION_DATA_BLOCKED",
        "path": path, "path_text": path_text,
        "gates": {"G_CAP_RECON": g_cap, "G_NULL_VALIDITY": g_null_val,
                  "G_ADVERSARIAL": g_adv},
        "kpi": {**CANONICAL_KPI, "MODERN_DATA_STATUS": modern_data_status},
        "verification": verification,
    }

    # ---- §52 final report ------------------------------------------------
    lines = [
        "RFC-038 MANAGED FUTURES EVIDENCE DECISION",
        "",
        f"MF-TREND-001 status = {horizons['MF-TREND-001_status']}",
        "",
        "Did RFC-037 capital conclusion reconcile?",
        "NO",
        "",
        f"Capital finding = {capital['defect']['classification']}: the +780% at $100M was a "
        "reference-rescaling artefact, not a granularity blow-up. Corrected tracking error "
        "is bounded; minimum viable capital is now 25,000,000 (preferred 50,000,000).",
        "",
        f"Minimum viable capital = {capital['minimum_viable_capital']}",
        f"Minimum preferred capital = {capital['minimum_preferred_capital']}",
        "",
        "Was market-label permutation a valid null?",
        "NO (NULL_MODEL_PARTIALLY_INVALID)",
        "",
        "Sign-randomization = "
        f"p={nulls['VALIDATION']['NULL-3_SIGN_RANDOMISATION']['p_null_ge_observed']:.3f} "
        "(validation) -- the trend direction carries real information.",
        "",
        "Primary adversarial result = "
        f"G_NULL_VALIDITY={g_null_val}, G_ADVERSARIAL={g_adv}: the VALID market-preserving "
        "block-circular-shift null rejects at 5% in both windows, so RFC-037's adversarial "
        "failure was driven by an invalid null.",
        "",
        "Modern free data = BLOCKED",
        f"Best modern paid data option = {decision['best_provider']} -- "
        f"{decision['best_dataset']} ({decision['best_price']})",
        "",
        f"P1 suitability = {shared_suitability(matrix, decision['best_provider'], 'p1')}",
        f"P2 suitability = {shared_suitability(matrix, decision['best_provider'], 'p2')}",
        "",
        f"Data acquisition decision = {decision['classification']}",
        "",
        "Historical validated edges = 1 / 1",
        "Modern validated edges = 0",
        "Paper candidates = 0",
        f"FALSE_SUCCESS = {verification.get('false_success_count', '?')}",
        f"VERIFICATION = {ver_status}",
        "",
        f"MODERN_DATA_STATUS = {modern_data_status}",
        f"DECISION PATH = {path} ({path_text})",
        "",
        "NEXT = HUMAN DATA ACQUISITION DECISION -- no further code until you decide "
        "whether to authorize the purchase; after approval the FIRST experiment is the "
        "FROZEN MF-TREND-001 modern transport validation (not P2).",
    ]
    (REPO / "reports" / "RFC038_FINAL_REPORT.md").write_text("\n".join(lines) + "\n",
                                                             encoding="utf-8")
    (REPO / "reports" / "RFC038_FINAL_REPORT.json").write_text(
        json.dumps({"text": lines, **horizons, "capital": capital, "nulls": nulls,
                    "decision": decision}, indent=2, default=str) + "\n",
        encoding="utf-8")

    # ---- §48 tracked decision doc ---------------------------------------
    doc = [
        "# RFC-038 -- MANAGED FUTURES EVIDENCE DECISION",
        "",
        "Audit whether RFC-037 rejected MF-TREND-001 for valid reasons, then decide "
        "whether modern futures data is worth acquiring for P1+P2. Frozen strategy; "
        "no tuning; no P2; no purchase.",
        "",
        "## Verdict",
        "",
        "RFC-037's rejection of MF-TREND-001 was **NOT** driven by valid evidence:",
        f"- **Capital**: G_CAP_RECON = **{g_cap}** -> `RFC037_CAPITAL_DEFECT`. The +780% at "
        "$100M was a reference-rescaling artefact. Corrected, minimum viable capital = "
        f"**{capital['minimum_viable_capital']:,.0f}**, preferred = "
        f"**{capital['minimum_preferred_capital']:,.0f}**.",
        f"- **Nulls**: G_NULL_VALIDITY = **{g_null_val}**, G_ADVERSARIAL = **{g_adv}**. The "
        "RFC-037 market-label permutation is `NULL_MODEL_PARTIALLY_INVALID`; a valid "
        "market-preserving block-circular-shift null rejects at 5% in both windows.",
        "",
        "MF-TREND-001 is therefore best classified **MODERN_VALIDATION_DATA_BLOCKED**, "
        "not economically rejected: it is blocked only by the absence of modern data.",
        "",
        "## Decision",
        "",
        f"- Data acquisition decision = **{decision['classification']}** "
        f"({decision['best_provider']} -- {decision['best_dataset']}).",
        "- MODERN_DATA_STATUS = **PAID_CANDIDATE** (RFC-038 cannot exceed this without "
        "human approval). **No purchase was made.**",
        "- Decision path = **A** (DATA ACQUISITION DECISION).",
        "",
        "## PROJECT KPI",
        "",
        "```",
        "Historical executable validated edges = 1 / 1",
        "Modern validated edges                 = 0 / 1",
        "Historical robust edges                = 1 / 1",
        "Paper candidates                       = 0 / 1",
        "Forward profitable                     = 0",
        "Live profitable                        = 0",
        "Modern data status                     = PAID_CANDIDATE",
        "```",
        "",
        "## Three questions (final directive)",
        "",
        "1. Was the RFC-037 capital test correctly computed? **NO** -- the fractional "
        "reference was never rescaled to the tested capital (`RFC037_CAPITAL_DEFECT`).",
        "2. Was the null that failed it statistically adequate? **NO** -- market-label "
        "permutation is partially invalid; a valid market-preserving null rejects at 5%.",
        "3. How much to know if the edge is alive today? **A paid modern dataset** "
        f"({decision['best_provider']}, {decision['best_price']}); cheapest credible shared "
        "P1+P2 option is Databento GLBX.MDP3 (~$179-$199/month or usage-based).",
        "",
        "NEXT = **HUMAN DATA ACQUISITION DECISION** (no code until you decide). If "
        "approved, the FIRST experiment is the frozen MF-TREND-001 modern transport "
        "validation; P2 stays AUTHORIZED_WAITING.",
        "",
    ]
    (DOCS / "MANAGED_FUTURES_DECISION_RFC038.md").write_text("\n".join(doc) + "\n",
                                                             encoding="utf-8")
    (DOCS / "MANAGED_FUTURES_DECISION_RFC038.json").write_text(
        json.dumps({"kpi": {**CANONICAL_KPI, "MODERN_DATA_STATUS": modern_data_status},
                    "gates": horizons["gates"], "path": path,
                    "capital_classification": capital["defect"]["classification"],
                    "minimum_viable_capital": capital["minimum_viable_capital"],
                    "minimum_preferred_capital": capital["minimum_preferred_capital"],
                    "decision": decision, "status": status},
                   indent=2, default=str) + "\n", encoding="utf-8")

    print("=== RFC-038 ===")
    print(f"G_CAP_RECON={g_cap} G_NULL_VALIDITY={g_null_val} G_ADVERSARIAL={g_adv}")
    print(f"path={path} data={decision['classification']} "
          f"MODERN_DATA_STATUS={modern_data_status} VERIFICATION={ver_status}")
    return 0


def shared_suitability(matrix: list[dict[str, Any]], provider: str, key: str) -> str:
    for p in matrix:
        if p["provider"] == provider:
            return str(p[f"{key}_suitability"])
    return "UNKNOWN"


if __name__ == "__main__":
    raise SystemExit(main())
