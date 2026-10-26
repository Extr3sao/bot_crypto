"""RFC-022 Sprint 002 - artifact writer and final report.

Reads the computed JSONs and writes every §60 artifact that is reachable, plus
the generalization diagnosis (CASO C: G_EDGE_1 PASS, G_EDGE_2 FAIL), the top-5
candidate table, the Sprint 001 comparison and the economic classification.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

import sprint002_lib as L

OUT = L.OUT_DIR
REPORTS = L.REPO / "reports"
COST = L.CERTIFIED_ROUND_TRIP_BPS
SPRINT001 = {
    "candidate": "volatility@30m",
    "gross_bps": 19.78,
    "net_bps": -4.01,
    "edge_cost_ratio": 0.831,
    "gross_bps_corrected": 21.7784,
    "net_bps_corrected": -2.0122,
    "edge_cost_ratio_corrected": 0.9154,
}


def load(name: str) -> Any:
    return json.loads((OUT / name).read_text(encoding="utf-8"))


def table(rows: list[list[Any]], header: list[str]) -> list[str]:
    out = ["| " + " | ".join(header) + " |", "|" + "|".join(["---"] * len(header)) + "|"]
    for r in rows:
        out.append("| " + " | ".join(str(x) for x in r) + " |")
    return out


def fmt(x: Any, nd: int = 2) -> str:
    if x is None:
        return "—"
    if isinstance(x, float):
        return f"{x:.{nd}f}"
    return str(x)


def main() -> int:
    disc = load("DISCOVERY_RESULTS.json")
    val = load("VALIDATION_RESULTS.json")
    rob = load("ROBUSTNESS_RESULTS.json")
    diag = load("ROBUSTNESS_DIAGNOSTICS.json")
    hold = load("HOLDOUT_RESULTS.json")
    summ = load("PIPELINE_SUMMARY.json")
    ver = load("INDEPENDENT_VERIFICATION.json")
    plan = load("SPRINT002_PLAN.json")
    vol30 = load("VOLATILITY_30M_DIAGNOSIS.json")

    all_exps = sorted(disc["results"], key=lambda r: -float(r["metrics"].get("net_bps", -99)))
    top5 = all_exps[:5]

    # ---------------- DISCOVERY_RESULTS.md ----------------
    lines = [
        "# SPRINT 002 — DISCOVERY RESULTS (W1-W4)",
        "",
        f"```text\nexperiments = {disc['experiments_total']}\npositive_net = {disc['positive_net']}\nmin_trades = {disc['min_trades']}\ncost_bps = {COST}\nG_EDGE_1 = {disc['G_EDGE_1']}\n```",
        "",
        "## Edge/cost distribution across all 106 experiments",
        "",
    ]
    bands: dict[str, int] = {}
    for r in all_exps:
        b = L.edge_cost_band(float(r["metrics"].get("edge_cost_ratio", 0.0) or 0.0))
        bands[b] = bands.get(b, 0) + 1
    lines += table([[k, v] for k, v in sorted(bands.items())], ["edge/cost band", "experiments"])
    lines += [
        "",
        "## Top 12 by net expectancy",
        "",
    ]
    rows = []
    for r in all_exps[:12]:
        m = r["metrics"]
        rows.append(
            [
                r["experiment_id"], r["candidate_id"], r["hypothesis_id"], r["timeframe"],
                m.get("trades"), fmt(m.get("gross_bps")), fmt(m.get("net_bps")),
                fmt(m.get("edge_cost_ratio"), 3), fmt(m.get("profit_factor"), 3),
                fmt(m.get("t_stat"), 3), fmt(m.get("net_bps_ex_best_trade")),
                L.edge_cost_band(float(m.get("edge_cost_ratio", 0) or 0)),
            ]
        )
    lines += table(
        rows,
        ["exp", "candidate", "hyp", "tf", "n", "gross", "net", "ratio", "PF", "t", "net_ex_best", "band"],
    )
    lines += [
        "",
        "Parameters for the top rows are in `EXPERIMENT_REGISTRY.jsonl` / `EXPERIMENT_MATRIX.csv`.",
        "",
        f"`G_EDGE_1 = {disc['G_EDGE_1']}`: {disc['positive_net']} candidate(s) with net expectancy > 0, "
        "net PnL > 0, sample >= 50, PIT safe, accounting consistent and no single-trade dependency.",
    ]
    (OUT / "DISCOVERY_RESULTS.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

    # ---------------- VALIDATION_RESULTS.md ----------------
    lines = [
        "# SPRINT 002 — VALIDATION RESULTS (W5)",
        "",
        f"```text\nG_EDGE_2 = {val['G_EDGE_2']}\nvalidation_tested = {len(val['results'])}\nvalidation_positive = {summ['validation_positive']}\nno retuning after validation = true\n```",
        "",
        "Frozen survivors re-run on W5 with byte-identical parameters. No parameter was",
        "changed after seeing validation (verified independently).",
        "",
    ]
    rows = []
    for v in val["results"]:
        d, s = v["discovery"], v["validation"]
        rows.append(
            [
                v["candidate_id"], json.dumps(v["parameters"]),
                f"{d.get('trades')}/{s.get('trades')}",
                f"{fmt(d.get('gross_bps'))}/{fmt(s.get('gross_bps'))}",
                f"{fmt(d.get('net_bps'))}/{fmt(s.get('net_bps'))}",
                f"{fmt(d.get('edge_cost_ratio'), 3)}/{fmt(s.get('edge_cost_ratio'), 3)}",
                f"{fmt(d.get('profit_factor'), 3)}/{fmt(s.get('profit_factor'), 3)}",
                v["pass"],
            ]
        )
    lines += table(rows, ["candidate", "parameters", "n D/V", "gross D/V", "net D/V", "ratio D/V", "PF D/V", "pass"])
    lines += [
        "",
        "## Why each survivor failed validation",
        "",
    ]
    for v in val["results"]:
        s = v["validation"]
        lines += [
            f"### {v['candidate_id']} — {json.dumps(v['parameters'])}",
            "",
            f"- validation trades = {s.get('trades')} (DISCOVERY {v['discovery'].get('trades')}), "
            f"degradation {v['degradation']['trade_count_change']} trades",
            f"- validation net expectancy = {s.get('net_bps')} bps (DISCOVERY {v['discovery'].get('net_bps')}), "
            f"delta {v['degradation']['net_bps_delta']}",
            f"- median trade = {s.get('median_net_bps')} bps (mean is driven by the tail)",
            f"- single-trade dependency = {s.get('single_trade_dependency')} "
            f"(net excluding the best trade = {s.get('net_bps_ex_best_trade')} bps)",
            f"- win rate {s.get('win_rate')}, t-stat {s.get('t_stat')}, exit mix {s.get('exit_mix')}",
            "",
        ]
    lines += [
        f"`G_EDGE_2 = {val['G_EDGE_2']}`. Both survivors keep a POSITIVE gross expectancy in W5 "
        "(24.05 and 30.87 bps) but their net expectancy is fragile (0.26 and 7.08 bps) on 22 and 21 "
        "trades, and in both cases removing the single best trade makes the net expectancy negative. "
        "The gate requires `no single-trade dependency`; the observed dependency is not a borderline "
        "technicality but the honest description of a 21-22 trade sample whose median trade is negative "
        "(-53.7 and -30.7 bps).",
    ]
    (OUT / "VALIDATION_RESULTS.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

    # ---------------- WALK_FORWARD / PARAMETER / REGIME / COST ----------------
    wf_rows = []
    ps_rows = []
    rg_rows = []
    cs_rows = []
    for d in diag["diagnostics"]:
        wf = d["walk_forward"]
        for f in wf["folds"]:
            wf_rows.append([d["candidate_id"], json.dumps(d["parameters"]), f["test_window"], f["trades"], fmt(f["net_bps"]), fmt(f["profit_factor"], 3), fmt(f["max_dd_bps"])])
        pn = d["parameter_neighbourhood"]
        ps_rows.append([d["candidate_id"], json.dumps(d["parameters"]), pn.get("positive_cells"), pn.get("total_cells"), pn.get("plateau_fraction"), pn.get("verdict")])
        for reg, rv in (d["regime"] or {}).items():
            rg_rows.append([d["candidate_id"], reg, rv["trades"], fmt(rv["net_bps"]), rv["win_rate"], rv["verdict"]])
        for name, cv in d["cost_stress"]["scenarios"].items():
            cs_rows.append([d["candidate_id"], name, cv["cost_bps"], cv["trades"], fmt(cv["net_bps"])])

    (OUT / "WALK_FORWARD_RESULTS.md").write_text(
        "\n".join(
            [
                "# SPRINT 002 — WALK-FORWARD RESULTS",
                "",
                "The candidates are frozen, so each fold is a pure out-of-sample evaluation",
                "(no fitting, no train/test contamination). Fold test windows are individual",
                "DISCOVERY weeks.",
                "",
                *table(wf_rows, ["candidate", "parameters", "test window", "trades", "net bps", "PF", "maxDD bps"]),
                "",
                "Verdicts: " + ", ".join(f"{d['candidate_id']}={d['walk_forward']['verdict']} ({d['walk_forward']['positive_folds']}/{d['walk_forward']['total_folds']} folds positive)" for d in diag["diagnostics"]),
                "",
                "DIAGNOSTIC ONLY: these candidates never passed validation, so no formal",
                "walk-forward gate was awarded.",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    (OUT / "PARAMETER_STABILITY.md").write_text(
        "\n".join(
            [
                "# SPRINT 002 — PARAMETER STABILITY",
                "",
                "A 3x3x2 neighbourhood around each frozen parameter set on DISCOVERY",
                "(target ±1 ATR, stop ±0.5 ATR, hold ±16 bars). A PLATEAU means the",
                "neighbourhood is positive in most cells; ISOLATED_SPIKE means only the",
                "selected point works.",
                "",
                *table(ps_rows, ["candidate", "frozen parameters", "positive cells", "total cells", "plateau fraction", "verdict"]),
                "",
                "DIAGNOSTIC ONLY.",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    (OUT / "REGIME_ANALYSIS.md").write_text(
        "\n".join(
            [
                "# SPRINT 002 — REGIME ANALYSIS",
                "",
                "Regime labels are ONLINE and PIT-safe (the runtime's own",
                "`classify_regime` thresholds applied per bar). Used for analysis only.",
                "",
                *table(rg_rows, ["candidate", "regime", "trades", "net bps", "win rate", "verdict"]),
                "",
                "DIAGNOSTIC ONLY.",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    (OUT / "COST_STRESS.md").write_text(
        "\n".join(
            [
                "# SPRINT 002 — COST STRESS",
                "",
                "Certified round trip 23.790569 bps; stress only for candidates that passed",
                "validation. No survivor passed validation, so this is a diagnostic on the",
                "discovery survivors.",
                "",
                *table(cs_rows, ["candidate", "scenario", "cost bps", "trades", "net bps"]),
                "",
                *[
                    f"- {d['candidate_id']} {json.dumps(d['parameters'])}: "
                    f"MAX_SURVIVABLE_COST_BPS = {d['cost_stress']['max_survivable_cost_bps']} "
                    f"({d['cost_stress']['verdict']}); slippage stress = {d['slippage_stress']['verdict']} "
                    f"({json.dumps({k: v['net_bps'] for k, v in d['slippage_stress']['scenarios'].items()})})"
                    for d in diag["diagnostics"]
                ],
                "",
                "DIAGNOSTIC ONLY.",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    (OUT / "ROBUSTNESS_RESULTS.md").write_text(
        "\n".join(
            [
                "# SPRINT 002 — ROBUSTNESS RESULTS",
                "",
                f"```text\nG_EDGE_3 = {rob['G_EDGE_3']}\nreason = G_EDGE_2 = FAIL: no candidate was promoted to robustness\n```",
                "",
                "The formal robustness gate is **NOT_REACHED** because validation failed.",
                "The full battery was nevertheless computed on the discovery survivors as a",
                "DIAGNOSTIC (`ROBUSTNESS_DIAGNOSTICS.json`) so the generalisation diagnosis has",
                "quantitative evidence.",
                "",
                *table(
                    [
                        [
                            d["candidate_id"], json.dumps(d["parameters"]),
                            d["walk_forward"]["verdict"], d["cost_stress"]["verdict"],
                            d["cost_stress"]["max_survivable_cost_bps"], d["slippage_stress"]["verdict"],
                            d["parameter_neighbourhood"].get("verdict"),
                            fmt((d["bootstrap"].get("ci95_net_bps") or [None])[0]),
                            fmt((d["bootstrap"].get("ci95_net_bps") or [None, None])[1]),
                            d["bootstrap"].get("p_net_le_0"),
                        ]
                        for d in diag["diagnostics"]
                    ],
                    ["candidate", "parameters", "walk-fwd", "cost stress", "max survivable cost", "slippage", "params", "boot P2.5", "boot P97.5", "P(net<=0)"],
                ),
                "",
                "Both survivors are bootstrap-fragile: the 95% block-bootstrap interval for net",
                "expectancy straddles zero (P(net<=0) = 0.21 and 0.18), the walk-forward is only",
                "PARTIAL (1-2 of 3 folds positive), and the cost stress is FRAGILE-to-ROBUST.",
                "No overfit signature of the `ISOLATED_SPIKE` kind appears (parameter verdicts are",
                "PLATEAU and PARTIAL), which is the one genuinely encouraging diagnostic result.",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    (OUT / "HOLDOUT_RESULTS.md").write_text(
        "\n".join(
            [
                "# SPRINT 002 — HOLDOUT RESULTS (W6-W7)",
                "",
                f"```text\nstatus = {hold['status']}\nreason = {hold['reason'] or 'n/a'}\nholdout_unread = {hold['holdout_unread']}\nG_EDGE_4 = {hold['G_EDGE_4']}\n```",
                "",
                "The holdout was **never read**. No candidate cleared DISCOVERY + VALIDATION, so",
                "the pre-unlock registration is empty and no holdout bar was used for any",
                "decision, selection or tuning. W6-W7 remain unspent for a future sprint.",
                "",
                "Unlock rule (frozen): read only after a G_EDGE_3 candidate exists, with a",
                "pre-unlock registration of candidate_id, code_hash, parameter_hash, specification,",
                "asset, timeframe, selection rationale and timestamp.",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    # ---------------- STRATEGY CANDIDATE REGISTRY (§55) ----------------
    states = [
        {
            "candidate_id": r["candidate_id"],
            "hypothesis_id": r["hypothesis_id"],
            "family": r["family"],
            "timeframe": r["timeframe"],
            "parameters": r["parameters"],
            "state": (
                "REJECTED_VALIDATION" if r["metrics"].get("trades", 0) >= L.MIN_TRADES and r["metrics"].get("net_bps", -1) > 0
                else ("REJECTED_DISCOVERY" if r["metrics"].get("trades", 0) >= L.MIN_TRADES else "MAGNITUDE_REJECTED")
            ),
            "discovery_net_bps": r["metrics"].get("net_bps"),
            "discovery_ratio": r["metrics"].get("edge_cost_ratio"),
        }
        for r in all_exps
    ]
    registry = {
        "schema": "rfc022.strategy_candidate_registry.v1",
        "cost_bps": COST,
        "states_used": sorted({s["state"] for s in states}),
        "note": "PRODUCTION is never used as a state.",
        "candidates": states,
    }
    L.write_json(OUT / "STRATEGY_CANDIDATE_REGISTRY.json", registry)
    L.write_json(
        REPORTS / "edge-discovery" / "STRATEGY_CANDIDATE_REGISTRY.json",
        {**registry, "schema": "rfc022.strategy_candidate_registry.v1", "sprint": "002"},
    )
    reg_lines = [
        "# STRATEGY CANDIDATE REGISTRY — SPRINT 002",
        "",
        f"```text\ncandidates = {len(states)}\nstates = {', '.join(sorted({s['state'] for s in states}))}\n```",
        "",
        "State legend: CREATED, MAGNITUDE_REJECTED, REJECTED_DISCOVERY, PASSED_DISCOVERY,",
        "REJECTED_VALIDATION, PASSED_VALIDATION, REJECTED_WALKFORWARD, PASSED_WALKFORWARD,",
        "REJECTED_ROBUSTNESS, PASSED_ROBUSTNESS, HOLDOUT_FAIL, HOLDOUT_PASS. `PRODUCTION` is",
        "never used.",
        "",
        *table(
            [[s["candidate_id"], s["hypothesis_id"], s["timeframe"], json.dumps(s["parameters"]), fmt(s["discovery_net_bps"]), fmt(s["discovery_ratio"], 3), s["state"]] for s in states],
            ["candidate", "hypothesis", "tf", "parameters", "D net", "D ratio", "state"],
        ),
    ]
    (OUT / "STRATEGY_CANDIDATE_REGISTRY.md").write_text("\n".join(reg_lines) + "\n", encoding="utf-8")

    # ---------------- GENERALIZATION DIAGNOSIS (CASO C) ----------------
    gen_lines = [
        "# SPRINT 002 — GENERALIZATION DIAGNOSIS",
        "",
        "§66 CASO C: `G_EDGE_1 = PASS` and `G_EDGE_2 = FAIL`. The required next step is a",
        "generalization diagnosis. No further parameter tuning is performed.",
        "",
        "## What generalised and what did not",
        "",
        "| | DISCOVERY (W1-W4) | VALIDATION (W5) |",
        "|---|---:|---:|",
    ]
    for v in val["results"]:
        gen_lines.append(
            f"| {v['candidate_id']} {json.dumps(v['parameters'])} gross bps | {fmt(v['discovery'].get('gross_bps'))} | {fmt(v['validation'].get('gross_bps'))} |"
        )
    gen_lines += [
        "",
        "**The GROSS edge generalised; the NET edge did not.** Both survivors kept a",
        "positive gross expectancy in W5 (24.05 and 30.87 bps, i.e. 1.01x and 1.30x the",
        "certified cost) — the economic mechanism (compression quality predicting a larger",
        "release) survived the month change. What failed is the ability to convert it into a",
        "net edge on a small sample: 21-22 trades, a negative median trade (-53.7 and -30.7",
        "bps), and a net expectancy that flips negative when the single best trade is removed.",
        "",
        "## Quantitative diagnosis",
        "",
        "| diagnostic | survivor 1 (3.0 ATR / 1.5 stop / 32) | survivor 2 (4.0 ATR / 2.0 stop / 32) |",
        "|---|---:|---:|",
        f"| DISCOVERY trades | {val['results'][0]['discovery'].get('trades')} | {val['results'][1]['discovery'].get('trades')} |",
        f"| VALIDATION trades | {val['results'][0]['validation'].get('trades')} | {val['results'][1]['validation'].get('trades')} |",
        f"| DISCOVERY net bps | {fmt(val['results'][0]['discovery'].get('net_bps'))} | {fmt(val['results'][1]['discovery'].get('net_bps'))} |",
        f"| VALIDATION net bps | {fmt(val['results'][0]['validation'].get('net_bps'))} | {fmt(val['results'][1]['validation'].get('net_bps'))} |",
        f"| VALIDATION median trade bps | {fmt(val['results'][0]['validation'].get('median_net_bps'))} | {fmt(val['results'][1]['validation'].get('median_net_bps'))} |",
        f"| VALIDATION win rate | {val['results'][0]['validation'].get('win_rate')} | {val['results'][1]['validation'].get('win_rate')} |",
        f"| VALIDATION t-stat | {fmt(val['results'][0]['validation'].get('t_stat'), 3)} | {fmt(val['results'][1]['validation'].get('t_stat'), 3)} |",
        f"| net excluding best trade | {fmt(val['results'][0]['validation'].get('net_bps_ex_best_trade'))} | {fmt(val['results'][1]['validation'].get('net_bps_ex_best_trade'))} |",
        "",
        "## Three candidate explanations, ranked by evidence",
        "",
        "1. **SAMPLE-VARIANCE (dominant).** 21-22 trades is far below the ~200 needed to",
        "   distinguish a +7 bps edge from zero at this volatility; the t-stat is 0.32 and the",
        "   block-bootstrap 95% interval straddles zero with P(net<=0) = 0.18. The DISCOVERY",
        "   t-stat was already only 1.03, so the discovery result was itself not significant.",
        "2. **COST FRAGILITY (contributing).** The gross edge in W5 is only 1.01-1.30x cost.",
        "   At 1.01x a 3 bps deterioration in realised slippage erases the edge; the",
        "   MAX_SURVIVABLE_COST_BPS for survivor 1 is exactly the base cost.",
        "3. **REGIME CHANGE (not demonstrated).** W5 is a single month; the regime breakdown",
        "   shows the edge is not concentrated in one amplitude regime, but a single month",
        "   cannot separate a regime shift from ordinary variance. Not claimed.",
        "",
        "## What this rules out",
        "",
        "- NOT a magnitude problem: Stage 0 showed the movement exists (median forward",
        "  excursion >= cost from 1h for every hypothesis).",
        "- NOT a PIT problem: the verifier confirms derivation-past-only and next-bar-open",
        "  execution.",
        "- NOT an overfit-spike problem: the parameter neighbourhoods are PLATEAU/PARTIAL.",
        "- It IS a **generalization problem** on a weak, low-frequency signal.",
    ]
    (OUT / "GENERALIZATION_DIAGNOSIS.md").write_text("\n".join(gen_lines) + "\n", encoding="utf-8")

    # ---------------- RUN REPORT ----------------
    L.write_json(
        OUT / "RUN_REPORT.json",
        {
            "schema": "rfc022.run_report.v1",
            "run_id": "RFC022-SPRINT002",
            "source_commit": summ["source_commit"],
            "timestamp": "2026-10-04T00:00:00Z",
            "dataset_hash": plan["dataset"]["corpus_hash"],
            "split_hash": {k: v["sha256"] for k, v in summ["dataset_hashes"].items()},
            "config_hash": summ["config_hash"],
            "cost_bps": COST,
            "experiments_total": summ["experiments_total"],
            "discovery_positive": summ["discovery_positive"],
            "validation_tested": summ["validation_tested"],
            "validation_positive": summ["validation_positive"],
            "robustness_tested": summ["robustness_tested"],
            "holdout_tested": summ["holdout_tested"],
            "G_EDGE_1": summ["G_EDGE_1"],
            "G_EDGE_2": summ["G_EDGE_2"],
            "G_EDGE_3": summ["G_EDGE_3"],
            "G_EDGE_4": summ["G_EDGE_4"],
            "verifier_status": ver["verifier_result"],
            "errors": [],
            "warnings": [
                "survivor samples are small (21-22 validation trades): results are directional, not significant",
            ],
            "evidence": sorted(p.name for p in OUT.glob("*")),
        },
    )
    (OUT / "RUN_REPORT.md").write_text(
        "\n".join(
            [
                "# SPRINT 002 — RUN REPORT",
                "",
                f"```text\nrun_id           = RFC022-SPRINT002\nsource_commit    = {summ['source_commit']}\ndataset_hash     = {plan['dataset']['corpus_hash']}\nconfig_hash      = {summ['config_hash']}\ncost_bps         = {COST}\nexperiments      = {summ['experiments_total']}\nG_EDGE_1         = {summ['G_EDGE_1']}\nG_EDGE_2         = {summ['G_EDGE_2']}\nG_EDGE_3         = {summ['G_EDGE_3']}\nG_EDGE_4         = {summ['G_EDGE_4']}\nverifier         = {ver['verifier_result']}\nFALSE_SUCCESS    = 0\n```",
                "",
                "Split hashes:",
                "",
                *[f"- {k}: {v['sha256']} ({v['files']} files, {v['rows']} rows)" for k, v in summ["dataset_hashes"].items()],
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    # ---------------- FINAL REPORT ----------------
    vol30_hc = vol30["horizon_counterfactual_discovery"]
    econ_class = "C — NET EDGE FOUND IN DISCOVERY, BUT VALIDATION FAILS"
    global_diag = "GENERALIZATION_PROBLEM"
    improved = "YES (magnitude and gross edge) / NO (net edge survives to validation)"

    final = [
        "# EDGE DISCOVERY SPRINT 002 — FINAL REPORT",
        "",
        "```text",
        "PHASE                 = RFC-022 EDGE DISCOVERY SPRINT 002",
        f"SOURCE_COMMIT         = {summ['source_commit']}",
        "FINAL_COMMIT          = (recorded at commit time)",
        "G0_RUNTIME_CERTIFIED  = PASS",
        "G1_BASELINE_CERTIFIED = PASS",
        "G2_DATA_PIT_CERTIFIED = PASS",
        "FALSE_SUCCESS         = 0",
        "",
        f"SPRINT002_EXPERIMENTS_TOTAL = {summ['experiments_total']}",
        "HYPOTHESES_TOTAL            = 12 (11 executable, 1 DATA_BLOCKED)",
        "FAMILIES_TOTAL              = 12",
        "ASSETS                      = BTC, ETH, SOL",
        "TIMEFRAMES                  = 15m, 30m, 1h, 2h (+ 5m/4h in Stage 0)",
        "",
        "MAGNITUDE_REJECTED   = 0 (of 11 screened; 1 DATA_BLOCKED, 1 N/A two-leg)",
        f"DISCOVERY_TESTED     = {summ['experiments_total']}",
        f"DISCOVERY_POSITIVE   = {summ['discovery_positive']}",
        f"VALIDATION_TESTED    = {summ['validation_tested']}",
        f"VALIDATION_POSITIVE  = {summ['validation_positive']}",
        f"WALK_FORWARD_TESTED  = {len(diag['diagnostics'])} (diagnostic only)",
        "WALK_FORWARD_PASS    = 0 (no candidate promoted)",
        f"ROBUSTNESS_TESTED    = {len(diag['diagnostics'])} (diagnostic only)",
        "ROBUSTNESS_PASS      = 0",
        f"HOLDOUT_TESTED       = {summ['holdout_tested']}",
        f"HOLDOUT_PASS         = {summ['holdout_pass']}",
        "",
        f"G_EDGE_1 = {summ['G_EDGE_1']}",
        f"G_EDGE_2 = {summ['G_EDGE_2']}",
        f"G_EDGE_3 = {summ['G_EDGE_3']}",
        f"G_EDGE_4 = {summ['G_EDGE_4']}",
        "```",
        "",
        "## Stage 0 — magnitude is not the constraint",
        "",
        "`MAGNITUDE_REJECT` = 0. Every executable hypothesis has a median forward excursion",
        "at or above the 23.79 bps cost from the 1h horizon. `MFE ≈ MAE` at the event bar, so",
        "the event bar detects amplitude but not direction — the edge must come from the",
        "direction rule and the exit geometry.",
        "",
        "## VOLATILITY@30M DIAGNOSIS (mandatory, before any re-tuning)",
        "",
        "The Sprint 001 best (`volatility@30m`, gross +19.78 bps, net -4.01 bps, ratio 0.831)",
        "was re-expressed under the corrected cost convention and re-measured at the",
        "executable entry (open of the bar AFTER the signal bar):",
        "",
        "| measurement | value |",
        "|---|---:|",
        f"| Sprint 001 gross (as reported) | {SPRINT001['gross_bps']} bps |",
        f"| corrected price move | {SPRINT001['gross_bps_corrected']} bps |",
        f"| executable-entry drift @30m | {vol30_hc['30m']['mean_bps']} bps |",
        f"| executable-entry drift @1h | {vol30_hc['1h']['mean_bps']} bps |",
        f"| executable-entry drift @2h | {vol30_hc['2h']['mean_bps']} bps |",
        f"| executable-entry drift @4h | {vol30_hc['4h']['mean_bps']} bps |",
        "",
        "Conclusion: the Sprint 001 edge is **barrier geometry plus DISCOVERY-period luck, not",
        "directional alpha**. A fixed +74 bps take-profit against a ~-120 bps stop produced a",
        "71% hit rate in W1-W4 (driftless-walk benchmark ≈62%); the same geometry produced 50.0%",
        "in W5 and 51.7% in W6-W7, i.e. at or below the random-walk benchmark. The endpoint",
        "drift at every horizon is below 10 bps, so no exit/horizon change rescues it.",
        "",
        "## Sprint 001 vs Sprint 002 frontier (§64)",
        "",
        "| | Sprint 001 best | Sprint 002 best |",
        "|---|---:|---:|",
        f"| candidate | {SPRINT001['candidate']} | {top5[0]['candidate_id']} |",
        f"| trades | 108 | {top5[0]['metrics'].get('trades')} |",
        f"| gross expectancy | {SPRINT001['gross_bps']} bps | {fmt(top5[0]['metrics'].get('gross_bps'))} bps |",
        f"| cost | {COST} bps | {COST} bps |",
        f"| net expectancy | {SPRINT001['net_bps']} bps | {fmt(top5[0]['metrics'].get('net_bps'))} bps |",
        f"| edge/cost | {SPRINT001['edge_cost_ratio']} | {fmt(top5[0]['metrics'].get('edge_cost_ratio'), 3)} |",
        f"| band | COST_KILLED | {L.edge_cost_band(float(top5[0]['metrics'].get('edge_cost_ratio', 0) or 0))} |",
        "",
        f"**DID SPRINT002 IMPROVE THE ECONOMIC FRONTIER? {improved}**",
        "",
        "- Magnitude: YES. The best gross expectancy rose from 19.78 to "
        f"{fmt(top5[0]['metrics'].get('gross_bps'))} bps, and the best edge/cost from 0.831 to "
        f"{fmt(top5[0]['metrics'].get('edge_cost_ratio'), 3)}.",
        "- Net edge that survives out of sample: NO. Sprint 001 had 0/18 positive; Sprint 002",
        "  had 2/106 positive on DISCOVERY and 0/2 on VALIDATION. Both sprints end with zero",
        "  candidates past G_EDGE_2.",
        "",
        "## Top 5 candidates (§63, reported even though all fail)",
        "",
        *table(
            [
                [
                    r["candidate_id"], r["hypothesis_id"], r["family"], r["timeframe"],
                    json.dumps(r["parameters"]), r["metrics"].get("trades"),
                    fmt(r["metrics"].get("trades_per_day"), 2),
                    fmt(r["metrics"].get("gross_bps")), COST, fmt(r["metrics"].get("net_bps")),
                    fmt(r["metrics"].get("edge_cost_ratio"), 3),
                    fmt(r["metrics"].get("gross_pnl_usdt")), fmt(r["metrics"].get("net_pnl_usdt")),
                    fmt(r["metrics"].get("profit_factor"), 3), fmt(r["metrics"].get("sharpe"), 3),
                    fmt(r["metrics"].get("sortino"), 3), fmt(r["metrics"].get("max_dd_bps")),
                    fmt(r["metrics"].get("avg_hold_min"), 1), fmt(r["metrics"].get("avg_mfe_bps")),
                    fmt(r["metrics"].get("avg_mae_bps")),
                    "REJECTED_VALIDATION" if r["metrics"].get("net_bps", -1) > 0 and r["metrics"].get("trades", 0) >= L.MIN_TRADES else "REJECTED_DISCOVERY",
                ]
                for r in top5
            ],
            ["candidate", "hyp", "family", "tf", "parameters", "n", "n/day", "gross", "cost", "net", "ratio", "gross PnL", "net PnL", "PF", "Sharpe", "Sortino", "maxDD", "hold min", "MFE", "MAE", "status"],
        ),
        "",
        "## Signal / Horizon / Cost diagnosis (§53)",
        "",
        f"**{global_diag}**",
        "",
        "- The signals DO capture gross movement: Stage 0 medians clear cost from 1h, and both",
        "  survivors held a positive gross expectancy in W5 (24.05 / 30.87 bps).",
        "- It is NOT a horizon problem: the volatility@30m counterfactual shows no horizon",
        "  rescues the endpoint drift, and the Sprint 002 grid already spans hold 8/16/32 bars.",
        "- It is NOT primarily a cost problem: the W5 gross was 1.01x and 1.30x cost, and",
        "  survivor 2 survives a +50% cost stress.",
        "- It IS a generalization problem: a low-frequency signal (21-22 validation trades)",
        "  whose net expectancy depends on the single best trade and whose bootstrap interval",
        "  straddles zero.",
        "",
        "## Economic classification (§65)",
        "",
        f"```text\n{econ_class}\n```",
        "",
        "## Sprint 002 edge/cost landscape",
        "",
        *table([[k, v] for k, v in sorted(bands.items())], ["band", "experiments"]),
        "",
        "## Mandatory artifacts",
        "",
        *[
            f"- `{p.name}`"
            for p in sorted(OUT.iterdir())
            if p.is_file() and p.name.endswith((".md", ".json", ".jsonl", ".csv"))
        ],
        "",
        "## Independent verification (§58)",
        "",
        f"`verifier_result = {ver['verifier_result']}`. Checks: split hashes match the frozen",
        "plan; NO PIT violation; NO accounting mismatch; NO cost relaxation; NO holdout",
        "leakage; NO silent experiment deletion; NO validation retuning.",
        "",
        "## Next gate (§66)",
        "",
        "CASO C → **GENERALIZATION DIAGNOSIS** (written as `GENERALIZATION_DIAGNOSIS.md`).",
        "No parameter tuning is performed against validation. The holdout W6-W7 remains",
        "unread and unspent.",
    ]
    (REPORTS / "EDGE_DISCOVERY_SPRINT002_FINAL_REPORT.md").write_text(
        "\n".join(final) + "\n", encoding="utf-8"
    )
    L.write_json(
        REPORTS / "EDGE_DISCOVERY_SPRINT002_FINAL_REPORT.json",
        {
            "schema": "rfc022.final_report.v1",
            "source_commit": summ["source_commit"],
            "G0_RUNTIME_CERTIFIED": "PASS",
            "G1_BASELINE_CERTIFIED": "PASS",
            "G2_DATA_PIT_CERTIFIED": "PASS",
            "FALSE_SUCCESS": 0,
            "experiments_total": summ["experiments_total"],
            "hypotheses_total": 12,
            "families_total": 12,
            "magnitude_rejected": 0,
            "discovery_tested": summ["experiments_total"],
            "discovery_positive": summ["discovery_positive"],
            "validation_tested": summ["validation_tested"],
            "validation_positive": summ["validation_positive"],
            "walk_forward_tested": len(diag["diagnostics"]),
            "walk_forward_pass": 0,
            "robustness_tested": len(diag["diagnostics"]),
            "robustness_pass": 0,
            "holdout_tested": summ["holdout_tested"],
            "holdout_pass": summ["holdout_pass"],
            "G_EDGE_1": summ["G_EDGE_1"],
            "G_EDGE_2": summ["G_EDGE_2"],
            "G_EDGE_3": summ["G_EDGE_3"],
            "G_EDGE_4": summ["G_EDGE_4"],
            "sprint001_best": SPRINT001,
            "sprint002_best": {
                "candidate_id": top5[0]["candidate_id"],
                "hypothesis_id": top5[0]["hypothesis_id"],
                "family": top5[0]["family"],
                "timeframe": top5[0]["timeframe"],
                "parameters": top5[0]["parameters"],
                "metrics": top5[0]["metrics"],
            },
            "improved_economic_frontier": {"magnitude_and_gross": "YES", "net_surviving_oos": "NO"},
            "global_diagnosis": global_diag,
            "economic_classification": econ_class,
            "verifier_result": ver["verifier_result"],
            "next_gate": "GENERALIZATION_DIAGNOSIS",
            "volatility_30m_diagnosis": {
                "conclusion": "barrier geometry + DISCOVERY-period luck, not directional alpha",
                "executable_entry_drift_bps": {k: v["mean_bps"] for k, v in vol30_hc.items()},
            },
        },
    )
    print("final report written", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
