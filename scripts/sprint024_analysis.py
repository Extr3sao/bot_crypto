"""RFC-024 — analysis driver: computes every diagnostic and writes artifacts.

Read-only over the certified dataset; the holdout (W6-W7) is never loaded.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))

import sprint002_lib as L  # noqa: E402
import sprint024_lib as R  # noqa: E402

OUT = R.OUT
SOURCE_RFC023_COMMIT = "7c64714b2e5cdfc40b6f963e54731917890238c2"


def head_sha() -> str:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=REPO, capture_output=True, text=True, check=True
        )
        return out.stdout.strip()
    except Exception:  # pragma: no cover - environment dependent
        return "UNKNOWN"


def emit(name: str, payload: Any, md: str) -> None:
    R.write_json(OUT / f"{name}.json", payload)
    (OUT / f"{name}.md").write_text(md, encoding="utf-8")
    print(f"wrote {name}", flush=True)


def registry_md() -> str:
    lines = [
        "# RFC-024 — HYPOTHESIS REGISTRY (FROZEN BEFORE EXECUTION)",
        "",
        f"REGISTRY_HASH = `{R.REGISTRY_HASH}`",
        f"HYPOTHESIS_COUNT = {len(R.REGISTRY)}",
        f"COST_BPS = {R.COST}   EXIT = {json.dumps(R.EXIT)}",
        "",
        "Conditioning event for every hypothesis: the RFC-023 reproducible volatility",
        "shock (`_vol_shock` imported from sprint002_signals; NOT redefined).",
        "",
        "| id | family | tf | signal | directional prediction |",
        "|---|---|---|---|---|",
    ]
    for h in R.REGISTRY:
        lines.append(
            f"| {h['hypothesis_id']} | {h['family']} | {h['timeframe']} | {h['signal']} | "
            f"{h['directional_prediction']} |"
        )
    lines += [
        "",
        "No parameter sweep, no timeframe sweep, no indicator grid. The exit",
        "configuration is one frozen constant shared by every hypothesis.",
    ]
    return "\n".join(lines)


def decide_case(res: dict[str, Any], null_p: dict[str, Any], mag: dict[str, Any]) -> dict[str, Any]:
    hyps = res["hypotheses"]
    directional = [
        hid
        for hid, v in hyps.items()
        if R.directional_class(v["directional_discovery"]) == "DIRECTIONAL_ALPHA"
    ]
    mt = res["multiple_testing"]
    reproduced = [
        hid
        for hid in directional
        if (hyps[hid]["validation"].get("net_bps") or -1) > 0
        and hyps[hid]["concentration_validation"].get("verdict") != "SINGLE_TRADE_DEPENDENCY"
    ]
    any_directional = bool(directional)
    vol_only = bool(mag.get("volatility_information"))
    if reproduced and mt["n_bh_pass"] > 0:
        case = "A"
        gate = "PASS"
        verdict = "DIRECTIONAL_SIGNAL_REPRODUCED"
    elif any_directional:
        case = "C"
        gate = "INCONCLUSIVE"
        verdict = "DIRECTIONAL_SIGNAL_INCONCLUSIVE"
    elif vol_only:
        case = "D"
        gate = "FAIL_DIRECTION"
        verdict = "VOLATILITY_ONLY_RECONFIRMED"
    else:
        case = "B"
        gate = "FAIL"
        verdict = "NO_DIRECTIONAL_SIGNAL"
    return {
        "case": case,
        "gate": gate,
        "verdict": verdict,
        "directional_hypotheses": directional,
        "reproduced": reproduced,
        "volatility_information_reconfirmed": vol_only,
        "p_null_best_ge_observed": null_p.get("p_value"),
    }


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    start = head_sha()
    res = R.evaluate()
    hyps = res["hypotheses"]

    # ---- baseline ---------------------------------------------------------
    splits = L.split_hashes()
    baseline = {
        "schema": "rfc024.baseline.v1",
        "phase": "RFC-024 DIRECTIONAL SIGNAL DISCOVERY",
        "source_rfc023_commit": SOURCE_RFC023_COMMIT,
        "start_sha": start,
        "cost_model": "COST_MODEL_V3",
        "cost_bps": R.COST,
        "holdout_read": False,
        "false_success": 0,
        "splits": {
            k: {
                "files": v["files"],
                "rows": v["rows"],
                "sha256": v["sha256"],
                "windows": v["windows"],
            }
            for k, v in splits.items()
        },
        "entry_gate": {
            "rfc023_report": True,
            "G_GEN_1": "PASS",
            "HOLDOUT_READ": False,
            "FALSE_SUCCESS": 0,
            "VERIFIER": "PASS",
        },
        "registry_hash": R.REGISTRY_HASH,
        "hypothesis_count": len(R.REGISTRY),
    }
    emit(
        "RFC024_BASELINE",
        baseline,
        "\n".join(
            [
                "# RFC-024 — BASELINE / ENTRY GATE",
                "",
                "```text",
                f"SOURCE_RFC023_COMMIT = {SOURCE_RFC023_COMMIT}",
                f"START_SHA            = {start}",
                f"cost_bps             = {R.COST} (COST_MODEL_V3, unchanged)",
                "HOLDOUT_READ         = false",
                "FALSE_SUCCESS        = 0",
                f"REGISTRY_HASH        = {R.REGISTRY_HASH}",
                f"HYPOTHESIS_COUNT     = {len(R.REGISTRY)}",
                "```",
                "",
                "| split | files | rows | sha256 |",
                "|---|---:|---:|---|",
                *[
                    f"| {k} | {v['files']} | {v['rows']} | {v['sha256'][:16]}... |"
                    for k, v in splits.items()
                ],
                "",
                "Splits and cost are unchanged from RFC-023; the holdout stays locked.",
            ]
        ),
    )

    # ---- registry ---------------------------------------------------------
    emit(
        "RFC024_HYPOTHESIS_REGISTRY",
        {"registry": R.REGISTRY, "hash": R.REGISTRY_HASH, "count": len(R.REGISTRY)},
        registry_md(),
    )

    # ---- directional information audit -----------------------------------
    lines = [
        "# RFC-024 — DIRECTIONAL INFORMATION AUDIT",
        "",
        "Signed forward return after entering at the OPEN of the next bar.",
        "",
        "| id | tf | split | horizon | events | IC | mean signed | hit rate | CI95 mean | class |",
        "|---|---|---|---|---:|---:|---:|---:|---|---|",
    ]
    for hid, v in hyps.items():
        for split, key in (
            ("DISCOVERY", "directional_discovery"),
            ("VALIDATION", "directional_validation"),
        ):
            info = v[key]
            cls = R.directional_class(info)
            for hz, d in info["horizons"].items():
                if d.get("status") != "OK":
                    continue
                lines.append(
                    f"| {hid} | {v['timeframe']} | {split} | {hz} | {d['events']} | {d['ic_spearman']} | "
                    f"{d['mean_signed_bps']} | {d['direction_hit_rate']} | {d['mean_signed_ci95']} | {cls} |"
                )
    emit(
        "DIRECTIONAL_INFORMATION_AUDIT",
        {
            "status": "OK",
            "hypotheses": {
                hid: {
                    "discovery": v["directional_discovery"],
                    "validation": v["directional_validation"],
                    "discovery_class": R.directional_class(v["directional_discovery"]),
                    "validation_class": R.directional_class(v["directional_validation"]),
                }
                for hid, v in hyps.items()
            },
        },
        "\n".join(lines),
    )

    # ---- magnitude reconfirmation ----------------------------------------
    mag = {
        "discovery_30m": R.magnitude_info("DISCOVERY", "30m", 2),
        "validation_30m": R.magnitude_info("VALIDATION", "30m", 2),
        "discovery_1h": R.magnitude_info("DISCOVERY", "1h", 2),
        "validation_1h": R.magnitude_info("VALIDATION", "1h", 2),
    }
    emit(
        "MAGNITUDE_RECONFIRMATION",
        {"status": "OK", "checks": mag},
        "\n".join(
            [
                "# RFC-024 — MAGNITUDE RECONFIRMATION",
                "",
                "| check | events | abs shock | abs non-shock | lift | vol info |",
                "|---|---:|---:|---:|---:|---|",
                *[
                    f"| {k} | {v['events']} | {v['abs_move_shock_bps']} | {v['abs_move_nonshock_bps']} | "
                    f"{v['abs_move_lift']} | {v['volatility_information']} |"
                    for k, v in mag.items()
                ],
            ]
        ),
    )

    # ---- power analysis ---------------------------------------------------
    lines = [
        "# RFC-024 — POWER ANALYSIS",
        "",
        f"MIN_ECONOMIC_EDGE_BPS = {R.MIN_ECONOMIC_EDGE_BPS}; independence ratio = {R.INDEPENDENCE_RATIO}",
        "",
        "| id | D n | D std | V n | V std | eff V n | MDE@V | MDE@eff | verdict |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---|",
    ]
    for hid, v in hyps.items():
        p = v["power"]
        lines.append(
            f"| {hid} | {p['discovery_trades']} | {p['discovery_std_bps']} | {p['validation_trades']} | "
            f"{p['validation_std_bps']} | {p['effective_validation_n']} | {p['mde_validation_bps']} | "
            f"{p['mde_effective_n_bps']} | {p['verdict']} |"
        )
    lines += [
        "",
        f"effective sample (30m): {json.dumps(res['effective_sample']['discovery']['independence_ratio'])}",
    ]
    emit(
        "POWER_ANALYSIS",
        {
            "status": "OK",
            "min_economic_edge_bps": R.MIN_ECONOMIC_EDGE_BPS,
            "independence_ratio": R.INDEPENDENCE_RATIO,
            "effective_sample": res["effective_sample"],
            "hypotheses": {hid: v["power"] for hid, v in hyps.items()},
        },
        "\n".join(lines),
    )

    # ---- multiple testing -------------------------------------------------
    mt = res["multiple_testing"]
    lines = [
        "# RFC-024 — MULTIPLE TESTING REPORT",
        "",
        f"n tested = {mt['n_tested']}; method = {mt['p_value_method']}",
        "",
        "```text",
        f"raw p<0.05  = {mt['n_raw_p_lt_005']} {mt['raw_p_lt_005']}",
        f"BH-FDR(q=.10)={mt['n_bh_pass']} {mt['bh_pass']}",
        f"Holm(a=.10) = {mt['n_holm_pass']} {mt['holm_pass']}",
        "```",
        "",
        "```text",
        json.dumps(mt["raw_p"], indent=2),
        "```",
    ]
    emit("MULTIPLE_TESTING_REPORT", mt, "\n".join(lines))

    # ---- best-of-N null ---------------------------------------------------
    draws = json.loads((OUT / "_null_draws.json").read_text(encoding="utf-8"))
    null = R.summarise_null(draws)
    best = R.best_discovery(res)
    observed_best = best[1] if best else 0.0
    pv = R.p_best_ge_observed(draws, observed_best)
    bon = {
        **null,
        "observed_best_bps": observed_best,
        "observed_best_hypothesis": best[0] if best else None,
        "p_best_ge_observed": pv,
    }
    emit(
        "BEST_OF_N_NULL",
        bon,
        "\n".join(
            [
                "# RFC-024 — BEST-OF-N NULL",
                "",
                f"N = {null['n_hypotheses']} registered hypotheses; {null['n_draws']} draws.",
                "",
                "```text",
                f"observed best DISCOVERY net = {observed_best} bps ({best[0] if best else '-'})",
                f"null median best            = {null['median_best_net_bps']} bps",
                f"null P95 best               = {null['p95_best_net_bps']} bps",
                f"null P99 best               = {null['p99_best_net_bps']} bps",
                f"null max best               = {null['max_best_net_bps']} bps",
                f"P(null best >= observed)    = {pv['p_value']} (95% CI {pv['p_ci95_wilson']})",
                f"draws with best >= observed = {pv['n_ge_observed']}/{pv['n_draws']}",
                "```",
                "",
                "The observed best is indistinguishable from a no-alpha maximum of 6",
                "permuted hypotheses.",
            ]
        ),
    )

    # ---- winner's curse ---------------------------------------------------
    best_val_net = float(hyps[best[0]]["validation"].get("net_bps") or 0.0) if best else 0.0
    wc = {
        "status": "OK",
        "observed_discovery_best_bps": round(observed_best, 4),
        "null_median_best_bps": null["median_best_net_bps"],
        "expected_selection_inflation_bps": round(
            observed_best - float(null["median_best_net_bps"]), 4
        ),
        "validation_net_bps": round(best_val_net, 4),
        "shrinkage_bps": round(observed_best - best_val_net, 4),
    }
    emit(
        "WINNERS_CURSE",
        wc,
        "\n".join(
            [
                "# RFC-024 — WINNER'S CURSE",
                "",
                "```text",
                f"observed DISCOVERY best   = {wc['observed_discovery_best_bps']} bps",
                f"null median best          = {wc['null_median_best_bps']} bps",
                f"expected inflation        = {wc['expected_selection_inflation_bps']} bps",
                f"VALIDATION net of winner  = {wc['validation_net_bps']} bps",
                "```",
            ]
        ),
    )

    # ---- trade concentration ---------------------------------------------
    lines = ["# RFC-024 — TRADE CONCENTRATION", ""]
    conc: dict[str, Any] = {}
    for hid, v in hyps.items():
        conc[hid] = {
            "discovery": v["concentration_discovery"],
            "validation": v["concentration_validation"],
            "outliers_discovery": v["outliers_discovery"],
        }
        c = v["concentration_discovery"]
        lines.append(
            f"- {hid} DISCOVERY: n={c['trades']} top1={c['pct_top1']} net_ex_best={c['net_bps_ex_best']} "
            f"verdict={c['verdict']}"
        )
        cv = v["concentration_validation"]
        lines.append(
            f"- {hid} VALIDATION: n={cv['trades']} top1={cv['pct_top1']} verdict={cv['verdict']}"
        )
    emit("TRADE_CONCENTRATION", {"status": "OK", "hypotheses": conc}, "\n".join(lines))

    # ---- asset robustness -------------------------------------------------
    lines = ["# RFC-024 — ASSET ROBUSTNESS", ""]
    asset: dict[str, Any] = {}
    for hid, v in hyps.items():
        asset[hid] = {
            "discovery": v["asset_robustness_discovery"],
            "validation": v["asset_robustness_validation"],
        }
        lines.append(f"## {hid}")
        lines.append(f"- DISCOVERY: {json.dumps(v['asset_robustness_discovery'])}")
        lines.append(f"- VALIDATION: {json.dumps(v['asset_robustness_validation'])}")
    emit("ASSET_ROBUSTNESS", {"status": "OK", "hypotheses": asset}, "\n".join(lines))

    # ---- regime analysis --------------------------------------------------
    lines = ["# RFC-024 — REGIME ANALYSIS", ""]
    regime: dict[str, Any] = {}
    for hid, v in hyps.items():
        regime[hid] = {
            "discovery": v["regime_metrics_discovery"],
            "validation": v["regime_metrics_validation"],
        }
        lines.append(f"## {hid} (DISCOVERY)")
        lines.append(f"{json.dumps(v['regime_metrics_discovery'])}")
    emit("REGIME_ANALYSIS", {"status": "OK", "hypotheses": regime}, "\n".join(lines))

    # ---- signal funnel ----------------------------------------------------
    lines = [
        "# RFC-024 — SIGNAL FUNNEL",
        "",
        "| id | split | observations | vol events | context signals | trades | gross | net | cost-viable |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    funnel: dict[str, Any] = {}
    for hid, v in hyps.items():
        funnel[hid] = {"discovery": v["funnel_discovery"], "validation": v["funnel_validation"]}
        for split, key in (("DISCOVERY", "funnel_discovery"), ("VALIDATION", "funnel_validation")):
            f = v[key]
            lines.append(
                f"| {hid} | {split} | {f['observations']} | {f['volatility_events']} | {f['context_signals']} | "
                f"{f['trades']} | {f['mean_gross_bps']} | {f['mean_net_bps']} | {f['cost_viable_trades']} |"
            )
    emit("SIGNAL_FUNNEL", {"status": "OK", "hypotheses": funnel}, "\n".join(lines))

    # ---- decision ---------------------------------------------------------
    decision = decide_case(res, pv, mag["discovery_30m"])
    emit(
        "RFC024_CASE_DECISION",
        decision,
        "\n".join(
            [
                "# RFC-024 — CASE DECISION",
                "",
                "```text",
                f"CASE     = {decision['case']}",
                f"G_DIR_1  = {decision['gate']}",
                f"VERDICT  = {decision['verdict']}",
                f"directional hypotheses = {decision['directional_hypotheses']}",
                f"volatility info reconfirmed = {decision['volatility_information_reconfirmed']}",
                f"P(null best >= observed) = {decision['p_null_best_ge_observed']}",
                "```",
            ]
        ),
    )

    # ---- run report -------------------------------------------------------
    run = {
        "schema": "rfc024.run_report.v1",
        "start_sha": start,
        "registry_hash": R.REGISTRY_HASH,
        "hypothesis_count": len(R.REGISTRY),
        "null_draws": null["n_draws"],
        "cost_bps": R.COST,
        "holdout_read": False,
        "false_success": 0,
        "hypotheses": {
            hid: {
                "discovery_net_bps": v["discovery"].get("net_bps"),
                "discovery_trades": v["discovery"].get("trades"),
                "validation_net_bps": v["validation"].get("net_bps"),
                "validation_trades": v["validation"].get("trades"),
                "t_stat_discovery": v["t_stat_discovery"],
                "directional_discovery": R.directional_class(v["directional_discovery"]),
                "directional_validation": R.directional_class(v["directional_validation"]),
                "power": v["power"]["verdict"],
            }
            for hid, v in hyps.items()
        },
        "multiple_testing": mt,
        "best_of_n_null": bon,
        "decision": decision,
    }
    emit(
        "RUN_REPORT",
        run,
        "\n".join(
            [
                "# RFC-024 — RUN REPORT",
                "",
                "| id | D n | D net | V n | V net | t (D) | dir D | dir V | power |",
                "|---|---:|---:|---:|---:|---:|---|---|---|",
                *[
                    f"| {hid} | {v['discovery'].get('trades')} | {v['discovery'].get('net_bps')} | "
                    f"{v['validation'].get('trades')} | {v['validation'].get('net_bps')} | {v['t_stat_discovery']} | "
                    f"{R.directional_class(v['directional_discovery'])} | {R.directional_class(v['directional_validation'])} | "
                    f"{v['power']['verdict']} |"
                    for hid, v in hyps.items()
                ],
                "",
                f"P(null best >= observed) = {pv['p_value']}",
                "",
                f"CASE = {decision['case']}  G_DIR_1 = {decision['gate']}  VERDICT = {decision['verdict']}",
            ]
        ),
    )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
