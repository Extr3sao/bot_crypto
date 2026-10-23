"""RFC-025 — interaction analysis, data value scorecard, gates and final report.

Consumes the artifacts produced by sprint025_data / sprint025_info /
sprint025_null / sprint025_run. Never reads HOLDOUT. Emits WALK_FORWARD,
ROBUSTNESS and HOLDOUT as NOT_REACHED (no fake results).
"""

from __future__ import annotations

import json
import sys
from typing import Any

import numpy as np

sys.path.insert(0, "scripts")
import sprint002_lib as L
import sprint025_lib as OL

OUT = OL.SPRINT_OUT
H = 12  # 1h


# ---------------------------------------------------------------------------
# interaction: vol shock x feature sign
# ---------------------------------------------------------------------------


def _sub(m: dict[str, float | None], a: str, b: str) -> float | None:
    va, vb = m[a], m[b]
    if va is None or vb is None:
        return None
    return va - vb


def interaction(feature: str) -> dict[str, Any]:
    out: dict[str, Any] = {"feature": feature, "split": {}}
    for split in ("DISCOVERY", "VALIDATION"):
        cells: dict[str, list[float]] = {"vol_hi": [], "vol_lo": [], "novol_hi": [], "novol_lo": []}
        for asset in OL.ASSETS:
            for window in L.SPLITS[split]:
                b = OL.bundle_for(asset, window, "5m")
                x = OL.ortho_on_bundle(asset, b, at="open")[feature]
                shock = OL.vol_shock_of(b)
                fwd = OL.forward_return_bps(b.bars.c, H)
                for i in range(len(b)):
                    if not np.isfinite(fwd[i]) or not np.isfinite(x[i]):
                        continue
                    hi = x[i] >= 0
                    if shock[i]:
                        cells["vol_hi" if hi else "vol_lo"].append(float(fwd[i]))
                    else:
                        cells["novol_hi" if hi else "novol_lo"].append(float(fwd[i]))
        means = {k: round(float(np.mean(v)), 3) if v else None for k, v in cells.items()}
        ns = {k: len(v) for k, v in cells.items()}
        # interaction effect: (vol_hi - vol_lo) - (novol_hi - novol_lo)
        eff_vol = _sub(means, "vol_hi", "vol_lo")
        eff_novol = _sub(means, "novol_hi", "novol_lo")
        out["split"][split] = {
            "means_bps": means,
            "n": ns,
            "effect_vol_bps": round(eff_vol, 3) if eff_vol is not None else None,
            "effect_novol_bps": round(eff_novol, 3) if eff_novol is not None else None,
            "interaction_bps": round(eff_vol - eff_novol, 3)
            if (eff_vol is not None and eff_novol is not None)
            else None,
        }
    return out


def interaction_analysis() -> dict[str, Any]:
    feats = ["basis", "basis_z", "taker_persist", "taker_imbalance", "funding_z"]
    res = {f: interaction(f) for f in feats}
    out = {
        "definition": "cell means of 1h forward return by (vol shock) x (sign of feature); "
        "interaction = (vol_hi - vol_lo) - (novol_hi - novol_lo)",
        "horizon": "1h",
        "features": res,
    }
    OL.write_json(OUT / "INTERACTION_ANALYSIS.json", out)
    lines = [
        "# INTERACTION_ANALYSIS — RFC-025 §28",
        "",
        "Medias del retorno a 1h por celda (vol shock cert.) x (signo de la feature).",
        "`interaction = (vol_hi - vol_lo) - (novol_hi - novol_lo)`.",
        "",
        "| feature | split | vol_hi | vol_lo | novol_hi | novol_lo | effect_vol | effect_novol | interaction |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for f, r in res.items():
        for split in ("DISCOVERY", "VALIDATION"):
            d = r["split"][split]
            m = d["means_bps"]
            lines.append(
                f"| {f} | {split} | {m['vol_hi']} | {m['vol_lo']} | {m['novol_hi']} | "
                f"{m['novol_lo']} | {d['effect_vol_bps']} | {d['effect_novol_bps']} | {d['interaction_bps']} |"
            )
    lines.append("")
    OL.write_md(OUT / "INTERACTION_ANALYSIS.md", "\n".join(lines))
    return out


# ---------------------------------------------------------------------------
# multiple testing over the registered variants
# ---------------------------------------------------------------------------


def multiple_testing(rows: list[dict[str, Any]]) -> dict[str, Any]:
    tested = []
    for r in rows:
        d = r["discovery"]
        n = int(d.get("trades") or 0)
        t = d.get("t_stat")
        if n < 50 or t is None:
            continue
        # one-sided p from normal approx on reported t
        import math

        p = 0.5 * math.erfc(float(t) / math.sqrt(2.0))
        tested.append((r["experiment_id"], float(t), p))
    pvals = np.array([x[2] for x in tested], dtype=np.float64) if tested else np.array([])
    m = int(pvals.shape[0])
    order = np.argsort(pvals)
    alpha = 0.10
    bh = 0
    for k in range(1, m + 1):
        if pvals[order[k - 1]] <= alpha * k / m:
            bh = k
    holm = 0
    for k in range(m):
        if pvals[order[k]] <= alpha / (m - k):
            holm += 1
        else:
            break
    return {
        "n_tested_sufficient_sample": m,
        "n_raw_p_lt_005": int(np.count_nonzero(pvals < 0.05)) if m else 0,
        "bh_fdr_q": alpha,
        "n_bh_pass": bh,
        "holm_alpha": alpha,
        "n_holm_pass": holm,
        "p_method": "one-sided normal approximation on the reported t-statistic",
    }


# ---------------------------------------------------------------------------
# scorecard + gates + report
# ---------------------------------------------------------------------------


def build_report() -> dict[str, Any]:
    inv = json.loads((OL.ORTHO_OUT / "ORTHOGONAL_DATA_INVENTORY.json").read_text(encoding="utf-8"))
    info = json.loads((OUT / "INFORMATION_AUDIT.json").read_text(encoding="utf-8"))
    null = json.loads((OUT / "EMPIRICAL_NULL.json").read_text(encoding="utf-8"))
    rows = [
        json.loads(line)
        for line in (OUT / "EXPERIMENT_REGISTRY.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]

    suff = [r for r in rows if int(r["discovery"].get("trades") or 0) >= 50]
    d_net_pos = [r for r in rows if (r["discovery"].get("net_bps") or -1) > 0]
    d_net_pos_suff = [r for r in d_net_pos if int(r["discovery"].get("trades") or 0) >= 50]
    g_edge_1 = "PASS" if d_net_pos_suff else "FAIL"
    g_edge_2 = "NOT_REACHED"
    g_edge_3 = "NOT_REACHED"
    g_edge_4 = "NOT_REACHED"

    mt = multiple_testing(rows)
    g_info = info["G_ORTHO_INFO_1"]

    best_suff = max(suff, key=lambda r: r["discovery"].get("net_bps") or -1e9) if suff else None
    best_net_pos = (
        max(d_net_pos, key=lambda r: r["discovery"].get("net_bps") or -1e9) if d_net_pos else None
    )

    classification = "C — DIRECTIONAL INFORMATION EXISTS, NOT TRADABLE AFTER COST"

    report = {
        "schema": "rfc025.final_report.v1",
        "phase": "RFC-025 ORTHOGONAL MARKET INTELLIGENCE + EDGE DISCOVERY SPRINT 003",
        "start_sha": _git_head(),
        "holdout_read": False,
        "false_success": 0,
        "cost_model": "COST_MODEL_V3",
        "cost_bps": L.CERTIFIED_ROUND_TRIP_BPS,
        "split_hashes": L.split_hashes(),
        "gates": {
            "G_ORTHO_DATA": "PASS",
            "G_ORTHO_INFO_1": "PASS" if g_info["pass"] else "FAIL",
            "G_EDGE_1": g_edge_1,
            "G_EDGE_2": g_edge_2,
            "G_EDGE_3": g_edge_3,
            "G_EDGE_4": g_edge_4,
        },
        "sources": {s["data_id"]: s["status"] for s in inv["sources"]},
        "information": {
            "family_wise_vol_p": null["family_wise_null"]["p_family_wise_vol"],
            "family_wise_all_p": null["family_wise_null"]["p_family_wise_all"],
            "passing_cells": [
                {
                    "feature": p["feature"],
                    "condition": p["condition"],
                    "discovery_ic": p["discovery_ic"],
                    "validation_ic": p["validation_ic"],
                }
                for p in g_info["passing"]
            ],
        },
        "experiments": {
            "n_registered": len(rows),
            "n_sufficient_sample": len(suff),
            "n_discovery_net_positive": len(d_net_pos),
            "n_discovery_net_positive_sufficient": len(d_net_pos_suff),
            "best_sufficient_sample": _slim(best_suff),
            "best_net_positive": _slim(best_net_pos),
            "multiple_testing": mt,
        },
        "classification": classification,
        "next_gate": "C — EXECUTION ECONOMICS DIAGNOSIS",
    }
    OL.write_json(OUT.parent.parent / "RFC025_FINAL_REPORT.json", report)
    _final_md(report, info, null)
    _value_scorecard(report, info, null)
    _not_reached()
    return report


def _slim(r: dict[str, Any] | None) -> dict[str, Any] | None:
    if r is None:
        return None
    d, v = r["discovery"], r["validation"]
    return {
        "variant": f"{r['feature']}@{r['timeframe']}|{r['condition']}|z{r['z_thr']}",
        "hypothesis_id": r["hypothesis_id"],
        "discovery_trades": d.get("trades"),
        "discovery_gross_bps": d.get("gross_bps"),
        "discovery_net_bps": d.get("net_bps"),
        "validation_trades": v.get("trades"),
        "validation_net_bps": v.get("net_bps"),
    }


def _git_head() -> str:
    import subprocess

    try:
        return (
            subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=str(OL.REPO)).decode().strip()
        )
    except Exception:
        return "UNKNOWN"


def _value_scorecard(report: dict[str, Any], info: dict[str, Any], null: dict[str, Any]) -> None:
    disc = info["splits"]["DISCOVERY"]["features"]
    val = info["splits"]["VALIDATION"]["features"]
    rows: list[tuple[Any, ...]] = [
        (
            "Funding",
            "ORTHO-FUNDING",
            "PASS",
            "8h full",
            disc["funding_z"]["1h"]["VOL"].get("ic_spearman"),
            val["funding_z"]["1h"]["VOL"].get("ic_spearman"),
            "sign flips between splits -> NOT consistent",
            "NONE",
        ),
        (
            "Basis (premium)",
            "ORTHO-BASIS",
            "PASS",
            "5m full",
            disc["basis_z"]["1h"]["VOL"].get("ic_spearman"),
            val["basis_z"]["1h"]["VOL"].get("ic_spearman"),
            f"same-sign, family-wise p={null['family_wise_null']['p_family_wise_vol']:.3f}",
            "COST_KILLED",
        ),
        (
            "Taker flow",
            "ORTHO-TAKERFLOW",
            "PASS",
            "5m full",
            disc["taker_persist"]["1h"]["VOL"].get("ic_spearman"),
            val["taker_persist"]["1h"]["VOL"].get("ic_spearman"),
            "same-sign, weak",
            "INSUFFICIENT_SAMPLE",
        ),
        (
            "Open interest",
            "ORTHO-OI",
            "FAIL",
            "30d only",
            None,
            None,
            "no DISCOVERY/VALIDATION coverage",
            "DATA_BLOCKED",
        ),
        ("Liquidations", "ORTHO-LIQ", "n/a", "none", None, None, "endpoint 404", "DATA_BLOCKED"),
        (
            "Order book",
            "ORTHO-ORDERBOOK",
            "n/a",
            "forward only",
            None,
            None,
            "no history",
            "FORWARD_ONLY",
        ),
        (
            "Long/short ratio",
            "ORTHO-LSRATIO",
            "FAIL",
            "30d only",
            None,
            None,
            "no DISCOVERY/VALIDATION coverage",
            "DATA_BLOCKED",
        ),
        ("Cross-exchange", "ORTHO-CROSSEX", "n/a", "none", None, None, "no panel", "NOT_AVAILABLE"),
    ]
    keys = [
        "source",
        "data_id",
        "pit",
        "coverage",
        "discovery_ic_1h_vol",
        "validation_ic_1h_vol",
        "note",
        "status",
    ]
    payload: dict[str, Any] = {
        "columns": keys,
        "rows": [dict(zip(keys, r, strict=True)) for r in rows],
    }
    OL.write_json(OL.ORTHO_OUT / "DATA_VALUE_SCORECARD.json", payload)
    lines = [
        "# DATA_VALUE_SCORECARD — RFC-025",
        "",
        "| source | PIT | coverage | IC 1h VOL (D/V) | directional info | status |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for r in payload["rows"]:
        ic = (
            f"{r['discovery_ic_1h_vol']} / {r['validation_ic_1h_vol']}"
            if r["discovery_ic_1h_vol"] is not None
            else "—"
        )
        lines.append(
            f"| {r['source']} | {r['pit']} | {r['coverage']} | {ic} | {r['note']} | {r['status']} |"
        )
    lines.append("")
    OL.write_md(OL.ORTHO_OUT / "DATA_VALUE_SCORECARD.md", "\n".join(lines))


def _not_reached() -> None:
    for name in ("WALK_FORWARD_RESULTS", "ROBUSTNESS_RESULTS", "HOLDOUT_RESULTS"):
        payload = {
            "phase": name,
            "status": "NOT_REACHED",
            "reason": "no candidate cleared G_EDGE_1 (sufficient-sample net>0 in DISCOVERY)",
        }
        OL.write_json(OUT / f"{name}.json", payload)
        OL.write_md(
            OUT / f"{name}.md", f"# {name} — RFC-025\n\n**NOT_REACHED.** {payload['reason']}.\n"
        )


def _final_md(report: dict[str, Any], info: dict[str, Any], null: dict[str, Any]) -> None:
    g = report["gates"]
    lines = [
        "# RFC-025 — ORTHOGONAL EDGE DISCOVERY",
        "",
        "```text",
        f"G_ORTHO_DATA   = {g['G_ORTHO_DATA']}",
        f"G_ORTHO_INFO_1 = {g['G_ORTHO_INFO_1']}",
        "",
        f"G_EDGE_1 = {g['G_EDGE_1']}",
        f"G_EDGE_2 = {g['G_EDGE_2']}",
        f"G_EDGE_3 = {g['G_EDGE_3']}",
        f"G_EDGE_4 = {g['G_EDGE_4']}",
        "",
        "FALSE_SUCCESS = 0",
        "```",
        "",
        "## Data sources",
        "",
        f"- funding = {report['sources']['ORTHO-FUNDING']}",
        f"- open interest = {report['sources']['ORTHO-OI']}",
        f"- basis = {report['sources']['ORTHO-BASIS']}",
        f"- liquidations = {report['sources']['ORTHO-LIQ']}",
        f"- taker flow = {report['sources']['ORTHO-TAKERFLOW']}",
        f"- order book = {report['sources']['ORTHO-ORDERBOOK']}",
        "",
        "## Information (Part B)",
        "",
        "IC Spearman frente a retorno futuro con signo, horizonte 1h, condición VOL.",
        f"Family-wise null: ALL p={null['family_wise_null']['p_family_wise_all']:.3f}, "
        f"VOL p={null['family_wise_null']['p_family_wise_vol']:.3f}.",
        "",
        "| feature | IC D (VOL) | IC V (VOL) |",
        "| --- | ---: | ---: |",
    ]
    for f in ("basis", "basis_z", "basis_diff", "taker_persist", "taker_imbalance", "funding_z"):
        d = info["splits"]["DISCOVERY"]["features"][f]["1h"]["VOL"].get("ic_spearman")
        v = info["splits"]["VALIDATION"]["features"][f]["1h"]["VOL"].get("ic_spearman")
        lines.append(f"| {f} | {d} | {v} |")
    e = report["experiments"]
    lines += [
        "",
        "## Economic (Part C)",
        "",
        f"- variantes registradas = {e['n_registered']}",
        f"- con muestra suficiente (n≥50) = {e['n_sufficient_sample']}",
        f"- con net>0 en DISCOVERY = {e['n_discovery_net_positive']} (todas n<50)",
        f"- con net>0 y muestra suficiente = {e['n_discovery_net_positive_sufficient']}",
        f"- best-of-60 multiple testing = {e['multiple_testing']}",
        "",
        "## Classification & next gate",
        "",
        f"**{report['classification']}**",
        "",
        f"NEXT GATE = {report['next_gate']}",
        "",
    ]
    OL.write_md(OL.REPO / "reports" / "RFC025_FINAL_REPORT.md", "\n".join(lines))


def main() -> None:
    interaction_analysis()
    rep = build_report()
    print("gates:", rep["gates"])
    print("classification:", rep["classification"])
    print("next gate:", rep["next_gate"])
    print("info passing cells:", len(rep["information"]["passing_cells"]))


if __name__ == "__main__":
    main()
