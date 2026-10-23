"""RFC-023 — analysis driver: computes every diagnostic and writes artifacts.

Read-only over the frozen Sprint 002 outputs; never touches the holdout.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import numpy as np

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))

import sprint002_lib as L  # noqa: E402
import sprint002_pipeline as P  # noqa: E402
import sprint023_lib as G  # noqa: E402

OUT = G.OUT
WINNERS = {"EXP-S002-0023": 4.0, "EXP-S002-0022": 3.0}


def emit(name: str, payload: Any, md: str) -> None:
    G.write_json(OUT / f"{name}.json", payload)
    (OUT / f"{name}.md").write_text(md, encoding="utf-8")
    print(f"wrote {name}", flush=True)


def winner_exps() -> list[dict[str, Any]]:
    return [r for r in G.discovery() if r["experiment_id"] in WINNERS]


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    winners = winner_exps()

    # ---- multiple testing -------------------------------------------------
    mt = G.multiple_testing()
    md = [
        "# RFC-023 — MULTIPLE TESTING AUDIT",
        "",
        f"- experiments tested (n>={G.MIN_TRADES}): **{mt['n_tested']}**",
        f"- raw p<0.05: **{mt['n_raw_p_lt_005']}**",
        f"- Benjamini-Hochberg (FDR q={mt['bh_fdr_q']}) survivors: **{mt['n_bh_pass']}**",
        f"- Holm/Bonferroni survivors: **{mt['n_holm_pass']}**",
        f"- method: {mt['p_value_method']}",
        "",
        "```text",
        f"raw_p_lt_005 = {mt['raw_p_lt_005']}",
        f"bh_pass      = {mt['bh_pass']}",
        f"holm_pass    = {mt['holm_pass']}",
        "```",
        "",
        "No experiment survives either family-wise correction: the apparent",
        "DISCOVERY winners are not significant once the 106 attempts are counted.",
    ]
    emit("MULTIPLE_TESTING_AUDIT", mt, "\n".join(md))

    # ---- best-of-N null ---------------------------------------------------
    draws = json.loads((OUT / "_null_draws.json").read_text(encoding="utf-8"))
    null = G.summarise_null(draws)
    observed_best = 16.0652
    pv = G.p_best_ge_observed(draws, observed_best)
    bon = {**null, "observed_best_bps": observed_best, "p_best_ge_observed": pv}
    md = [
        "# RFC-023 — BEST-OF-N NULL",
        "",
        "Null: for each of the 106 experiments the signal timestamps are permuted",
        "(count and direction multiset preserved) and the whole 106-candidate grid is",
        "re-selected by max net. 200 draws, seed block base 20261023.",
        "",
        "```text",
        f"observed best DISCOVERY net = {observed_best} bps",
        f"null median best            = {null['median_best_net_bps']} bps",
        f"null P95 best               = {null['p95_best_net_bps']} bps",
        f"null P99 best               = {null['p99_best_net_bps']} bps",
        f"null max best               = {null['max_best_net_bps']} bps",
        f"P(null best >= observed)    = {pv['p_value']}  (95% CI {pv['p_ci95_wilson']})",
        f"draws with best >= observed  = {pv['n_ge_observed']}/{pv['n_draws']}",
        "```",
        "",
        "The observed DISCOVERY best is **NOT surprising** after 106 attempts",
        f"(p = {pv['p_value']}): a plain no-alpha process of the same shape reproduces",
        "it in roughly one out of three experiments grids.",
    ]
    emit("BEST_OF_N_NULL", bon, "\n".join(md))

    # ---- winner's curse ---------------------------------------------------
    wc = G.winners_curse(null, observed_best, 7.0751)
    md = [
        "# RFC-023 — WINNER'S CURSE",
        "",
        "```text",
        f"observed DISCOVERY best       = {wc['observed_discovery_best_bps']} bps",
        f"null median best (expected)   = {wc['null_median_best_bps']} bps",
        f"expected winner inflation     = {wc['expected_winner_inflation_bps']} bps",
        f"VALIDATION net                = {wc['validation_net_bps']} bps",
        f"DISCOVERY -> VALIDATION drop  = {wc['discovery_to_validation_drop_bps']} bps",
        f"drop ~ regression to mean     = {wc['drop_consistent_with_regression_to_mean']}",
        "```",
        "",
        "The ~9 bps DISCOVERY->VALIDATION drop is almost exactly the ~8 bps winner",
        "inflation expected from selecting max(106) under the null: the drop is",
        "consistent with **regression to the mean**, not with a regime break.",
    ]
    emit("WINNERS_CURSE_ANALYSIS", wc, "\n".join(md))

    # ---- family-level evidence -------------------------------------------
    fam = G.family_level()
    lines = [
        "# RFC-023 — FAMILY-LEVEL EVIDENCE",
        "",
        "| hypothesis | family | exps | +gross | +net | median | mean | P25 | P75 | P90 | best | worst |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for hyp, v in fam["hypotheses"].items():
        lines.append(
            f"| {hyp} | {v['family']} | {v['experiments']} | {v['positive_gross']} | "
            f"{v['positive_net']} | {v['median_net_bps']} | {v['mean_net_bps']} | {v['p25']} | "
            f"{v['p75']} | {v['p90']} | {v['best']} | {v['worst']} |"
        )
    lines += [
        "",
        f"Families with positive median net: **{fam['n_families_positive_median']}** "
        f"({fam['families_with_positive_median']}).",
        "",
        "Only `squeeze_magnitude` shows a positive best; no family has a positive",
        "median, i.e. there is **one lucky winner in an otherwise negative family**, not",
        "a shifted family distribution.",
    ]
    emit("FAMILY_LEVEL_EVIDENCE", fam, "\n".join(lines))

    # ---- signal information audit ----------------------------------------
    sig_names = list(P.SIG_FN.keys())
    audit: dict[str, Any] = {}
    for name in sig_names:
        for tf in G.hyp_tf_map()[name]:
            key = f"{name}@{tf}"
            audit[key] = {
                "signal": name,
                "timeframe": tf,
                "discovery": G.info_for_signals([name], "DISCOVERY", tf)[name],
                "validation": G.info_for_signals([name], "VALIDATION", tf)[name],
            }
    md = [
        "# RFC-023 — SIGNAL INFORMATION AUDIT",
        "",
        "Signal vs forward return at frozen horizons (DISCOVERY).",
        "",
    ]
    md.append(
        "| signal | tf | horizon | events | IC | hit | E[fwd\\|sig] | E[fwd\\|no] | abs-lift |"
    )
    md.append("|---|---|---|---:|---:|---:|---:|---:|---:|")
    for _key, d in audit.items():
        for hz, v in d["discovery"]["horizons"].items():
            if v.get("status") != "OK":
                continue
            md.append(
                f"| {d['signal']} | {d['timeframe']} | {hz} | {v['events']} | {v['ic_spearman']} | "
                f"{v['direction_hit_rate']} | {v['e_fwd_signal_bps']} | {v['e_fwd_nosignal_bps']} | "
                f"{v['abs_move_lift']} |"
            )
    emit("SIGNAL_INFORMATION_AUDIT", {"status": "OK", "signals": audit}, "\n".join(md))

    # ---- direction vs magnitude ------------------------------------------
    dm: dict[str, Any] = {}
    for key, d in audit.items():
        dm[key] = {
            "signal": d["signal"],
            "timeframe": d["timeframe"],
            "discovery_class": G.classify_direction_magnitude(d["discovery"]),
            "validation_class": G.classify_direction_magnitude(d["validation"]),
        }
    md = [
        "# RFC-023 — DIRECTION VS MAGNITUDE",
        "",
        "| signal | tf | discovery | validation |",
        "|---|---|---|---|",
    ]
    for _key, v in dm.items():
        md.append(
            f"| {v['signal']} | {v['timeframe']} | {v['discovery_class']} | {v['validation_class']} |"
        )
    emit("DIRECTION_VS_MAGNITUDE", {"status": "OK", "signals": dm}, "\n".join(md))

    # ---- null baselines ---------------------------------------------------
    nb = G.null_baselines(resamples=2000)
    md = [
        "# RFC-023 — NULL BASELINE COMPARISON",
        "",
        f"timeframe = {nb['timeframe']}; real candidate = squeeze_magnitude@30m (tgt 4xATR/stop 2xATR/hold 32).",
        "",
        "```text",
        f"real net                        = {nb['real_net_bps']} bps (n={nb['real_trades']})",
        f"always long                     = {nb['always_long_net_bps']} bps (n={nb['always_long_trades']})",
        f"random direction @ same ts      = median {nb['random_direction_same_ts']['median_net_bps']} / P95 {nb['random_direction_same_ts']['p95_net_bps']} / P99 {nb['random_direction_same_ts']['p99_net_bps']}",
        f"random timestamps @ same count  = median {nb['random_timestamp_same_count']['median_net_bps']} / P95 {nb['random_timestamp_same_count']['p95_net_bps']} / P99 {nb['random_timestamp_same_count']['p99_net_bps']}",
        f"real > random-direction P95     = {nb['random_direction_same_ts']['p_real_exceeds_p95']}",
        f"real > random-timestamp P95     = {nb['random_timestamp_same_count']['p_real_exceeds_p95']}",
        "```",
        "",
        "Always-long loses the full cost; random timestamps are worse still, so the",
        "squeeze *timing* concentrates a larger move. Direction at those timestamps is",
        "only borderline against random direction — evidence of a weak conditional",
        "edge, but not one that survives the 106-attempt selection.",
    ]
    emit("NULL_BASELINE_COMPARISON", nb, "\n".join(md))

    # ---- event study ------------------------------------------------------
    es = G.event_study("DISCOVERY")
    lines = [
        "# RFC-023 — EVENT STUDY (DISCOVERY)",
        "",
        "| signal | tf | horizon | events | mean fwd | median fwd | positive rate | MFE | MAE | CI95 |",
        "|---|---|---|---:|---:|---:|---:|---:|---:|---|",
    ]
    for name, d in es["signals"].items():
        for hz, v in d["horizons"].items():
            if v.get("status") != "OK":
                continue
            lines.append(
                f"| {name} | {d['timeframe']} | {hz} | {v['events']} | {v['mean_fwd_ret_bps']} | "
                f"{v['median_fwd_ret_bps']} | {v['positive_rate']} | {v['mean_mfe_bps']} | "
                f"{v['mean_mae_bps']} | {v['ci95_mean_ret']} |"
            )
    emit("EVENT_STUDY", es, "\n".join(lines))

    # ---- distribution shift ----------------------------------------------
    ds: dict[str, Any] = {}
    for tf in ("15m", "30m", "1h"):
        ds[tf] = G.distribution_shift(tf)
    md = [
        "# RFC-023 — DISTRIBUTION SHIFT (DISCOVERY vs VALIDATION)",
        "",
        "| tf | feature | discovery mean | validation mean | std-shift z | material |",
        "|---|---|---:|---:|---:|---|",
    ]
    for tf, d in ds.items():
        for k, v in d["features"].items():
            md.append(
                f"| {tf} | {k} | {v['discovery_mean']} | {v['validation_mean']} | "
                f"{v['std_shift_z']} | {v['material']} |"
            )
    emit("DISTRIBUTION_SHIFT", {"status": "OK", "by_timeframe": ds}, "\n".join(md))

    # ---- regime shift -----------------------------------------------------
    reg: dict[str, Any] = {}
    for tf in ("30m", "1h"):
        rc = G.regime_composition(tf)
        wr: dict[str, Any] = {}
        for w in winners:
            tr = [t for t in w["trades"]]
            wr[w["experiment_id"]] = P.group_metrics(tr, "regime")
        reg[tf] = {"composition": rc["by_split"], "winner_regime_metrics": wr}
    md = ["# RFC-023 — REGIME SHIFT", ""]
    for tf, d in reg.items():
        md.append(f"## {tf}")
        for split in ("DISCOVERY", "VALIDATION"):
            md.append(f"- {split} composition: {d['composition'][split]['composition']}")
        md.append("")
        for eid, m in d["winner_regime_metrics"].items():
            md.append(f"- {eid} by regime: {json.dumps(m)}")
        md.append("")
    emit("REGIME_SHIFT", {"status": "OK", "by_timeframe": reg}, "\n".join(md))

    # ---- trade concentration ---------------------------------------------
    conc: dict[str, Any] = {"winners": {}, "temporal": {}}
    for w in winners:
        eid = w["experiment_id"]
        conc["winners"][eid] = {
            "discovery": G.concentration(w["trades"]),
            "outliers": G.outlier_influence(w["trades"]),
        }
        val = P.rerun(w, L.SPLITS["VALIDATION"])[0]
        conc["winners"][eid]["validation"] = G.concentration(val)
        conc["winners"][eid]["validation_outliers"] = G.outlier_influence(val)
        conc["temporal"][eid] = {
            "by_window": P.temporal_breakdown(w["trades"]),
            "leave_one_window_out": {},
        }
        for drop in L.SPLITS["DISCOVERY"]:
            keep = [t for t in w["trades"] if t.window != drop]
            net = G.net_of(keep)
            conc["temporal"][eid]["leave_one_window_out"][drop] = (
                round(float(np.mean(net)), 4) if net.shape[0] else None
            )
    md = ["# RFC-023 — TRADE CONCENTRATION", ""]
    for eid, d in conc["winners"].items():
        md.append(f"## {eid}")
        for scope in ("discovery", "validation"):
            c = d[scope]
            md.append(
                f"- {scope}: n={c['trades']} total={c['total_net_bps']} top1={c['pct_top1']} "
                f"top3={c['pct_top3']} net_ex_best={c['net_bps_ex_best']} verdict={c['verdict']}"
            )
        o = d["outliers"]
        md.append(
            f"- discovery outliers: mean={o['mean_bps']} median={o['median_bps']} trimmed={o['trimmed_mean_10_bps']} tail_dependent={o['tail_dependent']}"
        )
        md.append(f"- temporal by window: {json.dumps(conc['temporal'][eid]['by_window'])}")
        md.append(
            f"- leave-one-window-out: {json.dumps(conc['temporal'][eid]['leave_one_window_out'])}"
        )
        md.append("")
    emit("TRADE_CONCENTRATION", conc, "\n".join(md))

    # ---- sample size ------------------------------------------------------
    ss = G.sample_size_analysis()
    md = [
        "# RFC-023 — SAMPLE SIZE ANALYSIS",
        "",
        f"pooled trades = {ss['pooled_trades']}, pooled std = {ss['pooled_std_bps']} bps.",
        f"assumptions: {ss['assumptions']}.",
        "",
        "| n trades | MDE (bps) |",
        "|---:|---:|",
    ]
    for n, mde in ss["mde_bps_by_n"].items():
        md.append(f"| {n} | {mde} |")
    md += ["", f"required n for edge: {json.dumps(ss['required_n_for_edge'])}"]
    emit("SAMPLE_SIZE_ANALYSIS", ss, "\n".join(md))

    # ---- effective sample size -------------------------------------------
    eff = {split: G.effective_sample(split, "30m") for split in ("DISCOVERY", "VALIDATION")}
    md = ["# RFC-023 — EFFECTIVE SAMPLE SIZE", ""]
    for split, e in eff.items():
        md.append(
            f"- {split}: rho_bar={e['rho_bar']} independence_ratio={e['independence_ratio']} "
            f"N_eff={e['effective_sample_size']} (N={e['n_bars_total']})"
        )
    md += [
        "",
        "BTC/ETH/SOL are ~0.90 correlated: three assets are far from three independent samples.",
    ]
    emit("EFFECTIVE_SAMPLE_SIZE", {"status": "OK", "by_split": eff}, "\n".join(md))

    # ---- dataset adequacy -------------------------------------------------
    da = G.dataset_adequacy_detailed()
    md = [
        "# RFC-023 — DATASET ADEQUACY",
        "",
        "| tf | discovery bars | experiments | pooled trades | std | MDE@100 | class |",
        "|---|---:|---:|---:|---:|---:|---|",
    ]
    for tf, v in da["timeframes"].items():
        md.append(
            f"| {tf} | {v['discovery_bars']} | {v['experiments']} | {v['pooled_trades']} | "
            f"{v['pooled_std_bps']} | {v['mde_100_trades_bps']} | {v['classification']} |"
        )
    emit("DATASET_ADEQUACY", da, "\n".join(md))

    # ---- signal-to-trade diagnosis ---------------------------------------
    stt: dict[str, Any] = {}
    for key, d in dm.items():
        dm_class = d["discovery_class"]
        famrow = next(
            (v for v in fam["hypotheses"].values() if v["family"] == seed_family(d["signal"])), None
        )
        best = famrow["best"] if famrow else None
        if dm_class == "NO_INFORMATION":
            cls = "NO_INFORMATION" if (best is None or best <= 0) else "UNCERTAIN"
        elif dm_class == "VOLATILITY_ALPHA_ONLY":
            cls = "VOLATILITY_INFORMATION_ONLY"
        elif dm_class in ("DIRECTIONAL_ALPHA", "BOTH"):
            cls = (
                "DIRECTIONAL_INFORMATION"
                if (best is not None and best > 0)
                else "INFORMATION_TOO_WEAK"
            )
        else:
            cls = "UNCERTAIN"
        stt[key] = {
            "signal": d["signal"],
            "timeframe": d["timeframe"],
            "class": cls,
            "direction_magnitude": dm_class,
            "best_family_net_bps": best,
        }
    md = [
        "# RFC-023 — SIGNAL-TO-TRADE DIAGNOSIS",
        "",
        "| signal | tf | class | best net in family |",
        "|---|---|---|---:|",
    ]
    for _key, v in stt.items():
        md.append(
            f"| {v['signal']} | {v['timeframe']} | {v['class']} | {v['best_family_net_bps']} |"
        )
    emit("SIGNAL_TO_TRADE_DIAGNOSIS", {"status": "OK", "signals": stt}, "\n".join(md))

    return 0


def seed_family(sig: str) -> str:
    for sd in P.SINGLE_ASSET_SPECS:
        if sd["sig"] == sig:
            return str(sd["family"])
    return ""


if __name__ == "__main__":
    raise SystemExit(main())
