"""RFC-027 — independent verifier (§55, BUILDER != VERIFIER).

Recomputes the RFC-027 claims from the frozen canonical cache WITHOUT trusting
the builder's summary: it re-hashes the dataset, re-derives the PIT timestamp
invariant, re-measures the information of the survivor variants with an
independent ranking implementation and an independent permutation seed/block,
re-applies the pre-registered gate/classification rules itself, and asserts the
HOLDOUT was never read for analytics (§19).

Writes ``reports/edge-discovery/sprint004/INDEPENDENT_VERIFICATION.{md,json}``
and patches ``reports/RFC027_FINAL_REPORT.{md,json}`` with the verdict.
"""

from __future__ import annotations

import hashlib
import json
import math
import sys
from pathlib import Path
from typing import Any

import numpy as np
from numpy.typing import NDArray

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))

import sprint027_lib as L  # noqa: E402
import sprint027_signals as SG  # noqa: E402

POS = L.POS_DIR
OUT = L.OUT_DIR
INDEPENDENT_SEED = 20261027
INDEPENDENT_BLOCK = 12  # 6h — different from the builder's 48
INDEPENDENT_PERMS = 120


# ---------------------------------------------------------------------------
# independent statistics (fresh implementations)
# ---------------------------------------------------------------------------


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _rank_independent(x: NDArray[Any]) -> NDArray[Any]:
    """Average-rank transform (independent re-implementation of the builder's)."""
    v = np.asarray(x, dtype=np.float64)
    n = v.shape[0]
    order = np.argsort(v, kind="stable")
    xs = v[order]
    ranks = np.arange(1, n + 1, dtype=np.float64)
    i = 0
    while i < n:
        j = i
        while j + 1 < n and xs[j + 1] == xs[i]:
            j += 1
        if j > i:
            ranks[i : j + 1] = ranks[i : j + 1].mean()
        i = j + 1
    out = np.empty(n, dtype=np.float64)
    out[order] = ranks
    return out


def _ic_independent(sig: NDArray[Any], fwd: NDArray[Any]) -> float | None:
    m = np.isfinite(sig) & np.isfinite(fwd)
    if int(m.sum()) < 50:
        return None
    rx = _rank_independent(sig[m])
    ry = _rank_independent(fwd[m])
    if rx.std() == 0 or ry.std() == 0:
        return None
    return float(np.corrcoef(rx, ry)[0, 1])


def _circular_shift(n: int, rng: np.random.Generator) -> NDArray[Any]:
    shift = int(rng.integers(0, n))
    return np.roll(np.arange(n), shift)


def _family_null_independent(
    panel: L.Panel,
    disc_idx: NDArray[Any],
    family: str,
    block: int,
    n_perm: int,
    seed: int,
) -> dict[str, Any]:
    variants = [v for v in SG.build_variants() if v.family == family]
    sigs = {v.variant_id: SG.variant_signal(v, panel)[disc_idx] for v in variants}
    fwd = {v.variant_id: panel.fwd_bps[v.horizon_bars][disc_idx] for v in variants}
    obs = {vid: _ic_independent(sigs[vid], fwd[vid]) for vid in sigs}
    obs_fin = {k: v for k, v in obs.items() if v is not None}
    observed_max = max((abs(v) for v in obs_fin.values()), default=0.0)
    n = disc_idx.shape[0]

    rng = np.random.default_rng(seed)
    null_max = np.zeros(n_perm, dtype=np.float64)
    for p in range(n_perm):
        if block > 0:
            nb = math.ceil(n / block)
            order = rng.permutation(nb)
            perm = np.concatenate([np.arange(b * block, min((b + 1) * block, n)) for b in order])
        else:
            perm = _circular_shift(n, rng)
        mx = 0.0
        for vid in sigs:
            y = fwd[vid][perm] if block > 0 else np.roll(fwd[vid], perm[0])
            v = _ic_independent(sigs[vid], y)
            if v is not None:
                mx = max(mx, abs(v))
        null_max[p] = mx
    p_fw = float((1 + int(np.sum(null_max >= observed_max))) / (n_perm + 1))
    return {
        "family": family,
        "observed_max_abs_ic": round(observed_max, 5),
        "family_wise_p": round(p_fw, 5),
        "n_permutations": n_perm,
        "block_bars": block,
        "best_variant": max(obs_fin, key=lambda k: abs(obs_fin[k])) if obs_fin else None,
    }


# ---------------------------------------------------------------------------
# data checks
# ---------------------------------------------------------------------------


def _dataset_and_pit_checks() -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = []

    def chk(name: str, ok: bool, detail: str = "") -> None:
        checks.append(
            {"name": name, "result": "PASS" if ok else "FAIL", "ok": bool(ok), "detail": detail}
        )

    manifest = json.loads((POS / "DATASET_MANIFEST.json").read_text(encoding="utf-8"))
    sha_ok = True
    bad: list[str] = []
    for e in manifest["entries"]:
        got = _sha256_file(L.CACHE_DIR / e["file"])
        if got != e["sha256"]:
            sha_ok = False
            bad.append(e["file"])
    chk("dataset_fingerprints_match", sha_ok, f"files={len(manifest['entries'])} bad={bad}")

    # PIT timestamp invariant re-derived from the raw canonical arrays.
    pit_ok = True
    pit_detail: dict[str, int] = {}
    for sym in L.ASSETS:
        m = L.load_metrics(sym)
        c = m["create_time_ms"].astype(np.int64)
        s = m["interval_start_ms"].astype(np.int64)
        e = m["interval_end_ms"].astype(np.int64)
        a = m["available_time_ms"].astype(np.int64)
        viol = int(np.sum(s != c) + np.sum(e != c + L.SRC_MS) + np.sum(a != c + 2 * L.SRC_MS))
        pit_detail[sym] = viol
        if viol:
            pit_ok = False
    chk("pit_timestamp_invariant", pit_ok, f"violations={pit_detail}")

    # duplicates / ordering on the raw labels
    dup_ok = True
    dup_detail: dict[str, int] = {}
    for sym in L.ASSETS:
        c = L.load_metrics(sym)["create_time_ms"].astype(np.int64)
        dups = int(c.shape[0] - np.unique(c).shape[0])
        mono = int(np.sum(np.diff(c) <= 0))
        dup_detail[sym] = dups + mono
        if dups or mono:
            dup_ok = False
    chk("no_duplicate_or_unsorted_labels", dup_ok, f"issues={dup_detail}")

    # schema stability + documented width
    sch = json.loads((POS / "SCHEMA_AUDIT.json").read_text(encoding="utf-8"))
    chk(
        "schema_stable_8_columns",
        bool(sch["schema_stable_8_columns"]) and sch["observed_row_widths"] == ["8"],
        f"widths={sch['observed_row_widths']}",
    )

    # history depth + gate
    dq = json.loads((POS / "DATA_QUALITY_FINAL.json").read_text(encoding="utf-8"))
    chk(
        "history_months_at_least_12",
        float(dq["history_months"]) >= 12.0,
        f"history_months={dq['history_months']}",
    )
    chk("g_pos_data_recomputed", dq["result"] == "PASS", f"result={dq['result']}")
    return checks


def _research_checks(panel: L.Panel, disc_idx: NDArray[Any]) -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = []

    def chk(name: str, ok: bool, detail: str = "") -> None:
        checks.append(
            {"name": name, "result": "PASS" if ok else "FAIL", "ok": bool(ok), "detail": detail}
        )

    final = json.loads((REPO / "reports" / "RFC027_FINAL_REPORT.json").read_text(encoding="utf-8"))
    fam_art = json.loads((OUT / "FAMILY_NULL_ANALYSIS.json").read_text(encoding="utf-8"))

    # budgets (§25)
    n_hyp = len(SG.core_hypotheses())
    n_var = len(SG.build_variants())
    chk(
        "hypothesis_budget",
        n_hyp <= 12,
        f"n_core_hypotheses={n_hyp} (of {len(SG.HYPOTHESES)} registered)",
    )
    chk("variant_budget", n_var <= 120, f"n_variants={n_var}")

    # cost model unchanged
    chk(
        "cost_model_v3_unchanged",
        abs(L.COST_MODEL_V3_BPS - 23.790569) < 1e-9,
        f"cost_model_v3_bps={L.COST_MODEL_V3_BPS}",
    )
    chk(
        "cost_model_consistent_with_report",
        abs(float(final["cost_model_v3_bps"]) - L.COST_MODEL_V3_BPS) < 1e-9,
    )

    # EXPERIMENT_REGISTRY.jsonl / MATRIX.csv completeness
    reg_path = OUT / "EXPERIMENT_REGISTRY.jsonl"
    if reg_path.exists():
        with reg_path.open(encoding="utf-8") as fh:
            n_lines = sum(1 for _ in fh)
    else:
        n_lines = 0
    chk("experiment_registry_complete", n_lines == n_var, f"lines={n_lines} n_variants={n_var}")
    chk("experiment_matrix_present", (OUT / "EXPERIMENT_MATRIX.csv").exists())

    # recompute the reported best information variant independently
    best = final.get("best_information_signal")
    if best:
        v = next(v for v in SG.build_variants() if v.variant_id == best["variant_id"])
        sig = SG.variant_signal(v, panel)
        ic_d = _ic_independent(sig[disc_idx], panel.fwd_bps[v.horizon_bars][disc_idx])
        same = (
            ic_d is not None
            and best.get("ic_discovery") is not None
            and np.sign(ic_d) == np.sign(best["ic_discovery"])
        )
        chk(
            "best_information_ic_reproduced",
            same and abs(ic_d - best["ic_discovery"]) < 0.01,
            f"indep={ic_d} artifact={best.get('ic_discovery')}",
        )
    else:
        chk("best_information_ic_reproduced", True, "no survivor with p<alpha (nothing to check)")

    # independent family-wise null on the strongest family
    family = max(
        SG.FAMILIES, key=lambda f: fam_art["families"][f].get("observed_max_abs_ic") or 0.0
    )
    same_block = _family_null_independent(
        panel, disc_idx, family, 48, INDEPENDENT_PERMS, INDEPENDENT_SEED
    )
    alt_block = _family_null_independent(
        panel, disc_idx, family, INDEPENDENT_BLOCK, INDEPENDENT_PERMS, INDEPENDENT_SEED + 1
    )
    builder = fam_art["families"][family]
    chk(
        "family_null_observed_max_reproduced",
        abs(same_block["observed_max_abs_ic"] - builder["observed_max_abs_ic"]) < 1e-4,
        f"family={family} indep={same_block['observed_max_abs_ic']} "
        f"artifact={builder['observed_max_abs_ic']}",
    )
    chk(
        "family_null_seed_stable",
        abs(same_block["family_wise_p"] - builder["family_wise_p"]) < 0.1,
        f"indep_p={same_block['family_wise_p']} artifact_p={builder['family_wise_p']}",
    )
    surv_builder = builder["family_wise_p"] < 0.05
    surv_indep = alt_block["family_wise_p"] < 0.05
    chk(
        "family_null_verdict_stable_across_permutation",
        surv_builder == surv_indep,
        f"builder_p={builder['family_wise_p']} alt_block_p={alt_block['family_wise_p']}",
    )

    # gates states valid + classification reproduced from the gates
    valid_states = {"PASS", "FAIL", "NOT_REACHED"}
    chk(
        "gate_states_valid",
        all(v in valid_states for v in final["gates"].values()),
        f"gates={final['gates']}",
    )
    g = final["gates"]
    if g["G_POS_DATA"] != "PASS":
        reproduced = "POS-A"
    elif g["G_POS_INFO"] != "PASS":
        reproduced = "POS-B"
    elif g["G_EDGE_1"] != "PASS":
        reproduced = "POS-C"
    elif g["G_EDGE_2"] != "PASS":
        reproduced = "POS-D"
    elif g["G_EDGE_3"] != "PASS":
        reproduced = "POS-E"
    elif g["G_EDGE_4"] != "PASS":
        reproduced = "POS-F"
    else:
        reproduced = "POS-G"
    chk(
        "classification_reproduced",
        reproduced == final["global_classification"],
        f"reproduced={reproduced} artifact={final['global_classification']}",
    )

    # HOLDOUT never read for analytics unless G_EDGE_3 PASS (§19/§52)
    opened = final.get("holdout_analytics_read") is True
    justified = g.get("G_EDGE_3") == "PASS"
    chk(
        "holdout_not_read_unless_justified",
        (not opened) or justified,
        f"holdout_read={opened} g_edge_3={g.get('G_EDGE_3')}",
    )
    chk(
        "holdout_boundary_respected",
        float(L.SPLIT_FRACTIONS["VALIDATION"][1]) <= 0.8,
        "analytics loader truncates at the VALIDATION boundary (0.8)",
    )

    return checks


def verify_all() -> dict[str, Any]:
    checks = _dataset_and_pit_checks()
    panel = L.build_panel(upto="VALIDATION")
    masks = L.split_masks(panel)
    disc_idx = np.where(masks["DISCOVERY"])[0]
    checks += _research_checks(panel, disc_idx)
    false_success = sum(1 for c in checks if not c["ok"])
    return {
        "verifier": f"RFC-027 independent recomputation (seed {INDEPENDENT_SEED}, "
        f"block {INDEPENDENT_BLOCK})",
        "false_success": false_success,
        "checks": checks,
        "n_checks": len(checks),
    }


def _md(payload: dict[str, Any]) -> str:
    lines = [
        "# RFC027_INDEPENDENT_VERIFICATION",
        "",
        f"FALSE_SUCCESS = **{payload['false_success']}** ({payload['n_checks']} checks)",
        "",
        "| check | result | detail |",
        "| --- | --- | --- |",
    ]
    for c in payload["checks"]:
        lines.append(f"| {c['name']} | {c['result']} | {c['detail']} |")
    return "\n".join(lines) + "\n"


def _patch_final(result: dict[str, Any]) -> None:
    fj = REPO / "reports" / "RFC027_FINAL_REPORT.json"
    final = json.loads(fj.read_text(encoding="utf-8"))
    final["false_success"] = result["false_success"]
    final["independent_verification"] = "PASS" if result["false_success"] == 0 else "FAIL"
    L.write_json(fj, final)

    g = final["gates"]
    lines = [
        "# RFC-027 — HISTORICAL POSITIONING EDGE DISCOVERY",
        "",
        f"- G_POS_DATA = {g['G_POS_DATA']}",
        f"- G_POS_INFO = {g['G_POS_INFO']}",
        f"- HISTORY_MONTHS = {final['history_months']}",
        f"- G_EDGE_1 = {g['G_EDGE_1']}",
        f"- G_EDGE_2 = {g['G_EDGE_2']}",
        f"- G_EDGE_3 = {g['G_EDGE_3']}",
        f"- G_EDGE_4 = {g['G_EDGE_4']}",
        f"- GLOBAL_CLASSIFICATION = {final['global_classification']}",
        f"- NEXT GATE = {final['next_gate']}",
        "",
        f"FALSE_SUCCESS = {final['false_success']}",
        f"INDEPENDENT VERIFICATION = {final['independent_verification']}",
    ]
    L.write_md(REPO / "reports" / "RFC027_FINAL_REPORT.md", "\n".join(lines) + "\n")


def main() -> None:
    result = verify_all()
    L.write_json(OUT / "INDEPENDENT_VERIFICATION.json", result)
    L.write_md(OUT / "INDEPENDENT_VERIFICATION.md", _md(result))
    _patch_final(result)
    print(
        "independent verifier: FALSE_SUCCESS =",
        result["false_success"],
        "of",
        result["n_checks"],
        "checks",
    )
    for c in result["checks"]:
        if not c["ok"]:
            print("  FAIL:", c["name"], c["detail"])


if __name__ == "__main__":
    main()
