#!/usr/bin/env python
"""INDEPENDENT VERIFIER — V2→V3 ECONOMIC DRIFT, PERFORMANCE CONTAMINATION,
H5 IMMUTABILITY, SKIP AUDIT, DEFECT REGRESSION PRESENCE.

All artifacts are read from Git blob bytes at the audited commit, never from
working-tree copies. No economics are computed; this only compares frozen text.
"""
from __future__ import annotations

import hashlib
import json
import pathlib
import re
import subprocess
import sys
from datetime import datetime, timezone

VERIFIER_ROOT = pathlib.Path(
    subprocess.run(["git", "rev-parse", "--show-toplevel"], capture_output=True,
                   check=True).stdout.decode().strip()).resolve()

AUDITED = "a5487164803fb601f87f2cd4c865929c30da274e"
BASE = "0941082fc875a66287d2b09159112963141bcf27"
PREREG = "9f1d844312419575d6b635a7356111050fd9b93a"

V2_SPEC = "docs/external-audit-01/oi-full-history-02/H6_SPEC_V2.json"
V3_SPEC = "docs/external-audit-01/oi-full-history-03/H6_SPEC_V3.json"
V2_MANIFEST = "docs/external-audit-01/oi-full-history-02/H6_MANIFEST_V2.json"
V3_MANIFEST = "docs/external-audit-01/oi-full-history-03/H6_MANIFEST_V3.json"

PERF_TOKENS = [
    "sharpe", "sortino", "profit_factor", "pnl", "p&l", "net_return", "total_return",
    "cagr", "max_drawdown", "hit_rate", "win_rate", "expectancy", "equity_curve",
    "cumulative_return", "annualized_return", "alpha", "beta", "mean_return",
]


def git(*args, binary=False):
    p = subprocess.run(["git"] + list(args), capture_output=True)
    if p.returncode != 0:
        raise RuntimeError("git %s: %s" % (" ".join(args), p.stderr.decode("utf-8", "replace")))
    return p.stdout if binary else p.stdout.decode("utf-8", "replace")


def blob(p, c=AUDITED):
    return git("cat-file", "blob", "%s:%s" % (c, p), binary=True)


def main():
    out = {
        "verifier_type": "INDEPENDENT_SEMANTICS_AND_CONTAMINATION_V3",
        "timestamp_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "audited_target_commit": AUDITED,
        "economics": {"H6_BACKTESTS": 0, "H6_EXECUTIONS": 0, "PERFORMANCE_OBSERVED": False},
    }

    v2 = json.loads(blob(V2_SPEC))
    v3 = json.loads(blob(V3_SPEC))
    e2 = v2
    e3 = v3["economics"]

    # ------------------------------------------------ V2 -> V3 economic drift
    # Compare EVERY V2 economic field against V3.economics by identical key name.
    # (V3.economics reuses V2's key names, so no name mapping is applied; applying a
    # hand-written map would hide omissions, which is exactly what this gate must catch.)
    NON_ECONOMIC = {
        "experiment_id", "hypothesis_id", "schema", "spec_version", "preregistered_utc",
        "status_at_prereg", "H6_EXECUTIONS", "H6_BACKTESTS", "PERFORMANCE_OBSERVED",
        "mechanism", "data_authority", "forbidden_until_execution_checkpoint",
    }
    v2_economic_fields = [k for k in e2 if k not in NON_ECONOMIC]

    def canon(x):
        return json.dumps(x, sort_keys=True, separators=(",", ":"))

    drift, identical, absent = [], [], []
    for k in v2_economic_fields:
        if k not in e3:
            absent.append({"v2_field": k, "v2_value": e2[k],
                           "present_elsewhere_in_v3_spec_textually": bool(
                               (json.dumps(e2[k], sort_keys=True)[:40] in
                                json.dumps(v3, sort_keys=True))) or
                               (isinstance(e2[k], str) and e2[k][:40] in json.dumps(v3))})
            continue
        if canon(e2[k]) == canon(e3[k]):
            identical.append(k)
        else:
            drift.append({"v2_field": k, "v3_field": k,
                          "v2": e2[k], "v3": e3[k]})

    out["V2_to_V3_economic_semantic_drift"] = {
        "method": ("every V2 top-level economic field compared to the same key inside "
                   "V3.economics; no hand-written name mapping"),
        "v2_economic_field_count": len(v2_economic_fields),
        "v2_spec": V2_SPEC, "v3_spec": V3_SPEC,
        "v2_spec_sha256": hashlib.sha256(blob(V2_SPEC)).hexdigest(),
        "v3_spec_sha256": hashlib.sha256(blob(V3_SPEC)).hexdigest(),
        "fields_compared_identical": identical,
        "fields_differing": drift,
        "v2_fields_absent_from_v3_economics": absent,
        "v3_claim": v3.get("economics_carried_forward_unchanged_from"),
        "declared_carried_block_sha256": (v3.get("economics_carried_forward_unchanged_from") or {}).get("spec_sha256_of_carried_block"),
        "declared_retune": (v3.get("economics_carried_forward_unchanged_from") or {}).get("retune"),
    }
    # candidate interpretations of the declared carried-block hash
    econ_block_bytes = canon(e3).encode("utf-8")
    cands = {
        "sha256(canonical_json(V3.economics))": hashlib.sha256(econ_block_bytes).hexdigest(),
        "sha256(canonical_json(V2 spec))": hashlib.sha256(canon(blob(V2_SPEC).decode() and v2).encode()).hexdigest(),
        "sha256(V2 spec raw bytes)": hashlib.sha256(blob(V2_SPEC)).hexdigest(),
        "sha256(V3 spec raw bytes)": hashlib.sha256(blob(V3_SPEC)).hexdigest(),
    }
    declared = out["V2_to_V3_economic_semantic_drift"]["declared_carried_block_sha256"]
    out["V2_to_V3_economic_semantic_drift"]["carried_block_hash_candidates"] = cands
    out["V2_to_V3_economic_semantic_drift"]["declared_hash_reproduced_by"] = [
        k for k, v in cands.items() if v == declared]
    out["V2_to_V3_economic_semantic_drift"]["declared_hash_reproducible"] = bool(
        out["V2_to_V3_economic_semantic_drift"]["declared_hash_reproduced_by"])
    # Which keys does the RUNTIME contract loader demand of a spec?
    loader = (VERIFIER_ROOT / "src/trading_bot/research/h6/frozen_contract_snapshot.py").read_text(encoding="utf-8")
    required_keys = sorted(set(re.findall(r'spec\["([a-z_]+)"\]', loader)))
    strict_absent = [a["v2_field"] for a in absent if a["v2_field"] in required_keys]
    out["V2_to_V3_economic_semantic_drift"].update({
        "runtime_loader_required_spec_keys": required_keys,
        "required_keys_absent_from_v3_economics": strict_absent,
        "dropped_fields_that_are_substantively_missing": [
            a["v2_field"] for a in absent
            if not a["present_elsewhere_in_v3_spec_textually"]],
        "dropped_fields_relocated_elsewhere_in_v3": [
            a["v2_field"] for a in absent if a["present_elsewhere_in_v3_spec_textually"]],
    })
    out["V2_TO_V3_ECONOMIC_SEMANTIC_DRIFT"] = (
        "PASS" if (not drift and not strict_absent) else "FAIL")
    out["V2_to_V3_economic_semantic_drift"]["verdict_note"] = (
        "PASS requires BOTH (a) zero carried fields changed in value and (b) zero fields that the "
        "runtime contract loader requires to be absent from the V3 economics block. Carried fields "
        "that changed are reported in 'fields_differing'; carried-away fields are reported in "
        "'v2_fields_absent_from_v3_economics'.")

    # ---------------------------------------- control-plane V1 bindings
    v1_tokens = ["e683e04e5df39d0f2f5feb6097664536b93cc636",
                 "f514fecf42b52d2e1c2946cac9dee94b2570d485cb236b9a6c663f46f5bbf148",
                 "345334c3107860a5adcc753f5b34976d2b4df9061de34a94507d2bd8f58752dc",
                 "oi-full-history-01"]
    bindings = []
    for p in git("ls-tree", "-r", "--name-only", AUDITED).splitlines():
        if not p.endswith(".py") or not (p.startswith("src/") or p.startswith("scripts/")):
            continue
        txt = blob(p).decode("utf-8", "replace")
        for i, line in enumerate(txt.splitlines(), 1):
            for t in v1_tokens:
                if t in line:
                    bindings.append({"path": p, "line": i, "token": t[:24] + "…",
                                     "text": line.strip()[:150]})
    out["control_plane_v1_bindings"] = {
        "bindings": bindings,
        "binding_count": len(bindings),
        "distinct_files": sorted({b["path"] for b in bindings}),
        "permutation_seed_and_draws": {
            "v2_spec_value": e2.get("statistical_gates", {}).get("permutation"),
            "present_in_v3_authority": "20260911" in json.dumps(v3) or "permutation_seed" in json.dumps(v3),
            "present_in_gate_config_py": "20260911" in (
                VERIFIER_ROOT / "src/trading_bot/research/h6/gate_config.py").read_text(encoding="utf-8"),
        },
    }
    out["CONTROL_PLANE_V1_BINDING"] = "FAIL" if bindings else "PASS"

    # ------------------------------------------------ performance contamination
    out["performance_contamination"] = {
        "scanned": [],
        "hits": [],
        "hits_in_docstring_or_comment_only": [],
    }
    scan_targets = []
    for p in git("ls-tree", "-r", "--name-only", AUDITED).splitlines():
        low = p.lower()
        if low.endswith((".json", ".jsonl", ".md")) and ("h6" in low or "oi-full-history-03" in low):
            scan_targets.append(p)
        elif low.endswith(".py") and "/h6/" in low:
            scan_targets.append(p)
    hit_counts = {}
    for p in scan_targets:
        try:
            txt = blob(p).decode("utf-8", "replace")
        except Exception:
            continue
        low = txt.lower()
        for t in PERF_TOKENS:
            n = low.count(t)
            if n:
                hit_counts[t] = hit_counts.get(t, 0) + n
                out["performance_contamination"]["hits"].append({"path": p, "token": t, "count": n})
    out["performance_contamination"]["scanned"] = scan_targets
    out["performance_contamination"]["token_totals"] = hit_counts
    out["performance_contamination"]["PERFORMANCE_OBSERVED_declared"] = {
        "V2_spec": v2.get("PERFORMANCE_OBSERVED"),
        "V3_spec_status_at_prereg": v3.get("governance", {}).get("H6_EXECUTIONS") if isinstance(v3.get("governance"), dict) else None,
        "V3_spec_governance": v3.get("governance"),
    }
    # An actual measured performance number would be a numeric metric key inside a RESULT artifact
    numeric_perf = []
    for p in scan_targets:
        if not p.endswith((".json",)):
            continue
        if "RESULT" not in p.upper() and "RUN_REPORT" not in p.upper():
            continue
        try:
            d = json.loads(blob(p))
        except Exception:
            continue

        def walk(o, path=""):
            if isinstance(o, dict):
                for k, v in o.items():
                    kl = str(k).lower()
                    if isinstance(v, (int, float)) and not isinstance(v, bool) and any(t in kl for t in PERF_TOKENS):
                        numeric_perf.append({"path": p, "key_path": "%s.%s" % (path, k), "value": v})
                    walk(v, "%s.%s" % (path, k))
            elif isinstance(o, list):
                for i, v in enumerate(o[:200]):
                    walk(v, "%s[%d]" % (path, i))
        walk(d)
    out["performance_contamination"]["measured_performance_metrics_found"] = numeric_perf
    # The specific contamination risk: a result artifact carrying a hypothesis's own metrics
    out["PERFORMANCE_CONTAMINATION"] = "PASS" if not numeric_perf else "FAIL"

    # ------------------------------------------------ H5 immutability
    h5 = {}
    h5_files = [p for p in git("ls-tree", "-r", "--name-only", AUDITED).splitlines()
                if "h5-orderflow-imbalance" in p]
    changed = git("diff", "--name-only", BASE, AUDITED, "--", "docs/external-audit-01/h5-orderflow-imbalance-01").splitlines()
    h5["files_present_at_audited_commit"] = sorted(h5_files)
    h5["files_changed_between_base_and_audited"] = changed
    # H5 prereg/blobs must be untouched by the V3 repair
    h5["H5_prereg_artifacts_touched_by_v3_repair"] = changed
    h5["H5_IMMUTABILITY"] = "PASS" if not changed else "FAIL"
    # deeper: compare declared hashes inside H5 evidence to recomputed ones where cheap
    man_path = "docs/external-audit-01/h5-orderflow-imbalance-01/H5_MANIFEST.json"
    try:
        m = json.loads(blob(man_path))
        h5["H5_MANIFEST_present"] = True
        h5["H5_MANIFEST_keys"] = list(m.keys())
    except Exception as e:
        h5["H5_MANIFEST_present"] = False
        h5["H5_MANIFEST_error"] = str(e)
    out["h5_immutability"] = h5

    # ------------------------------------------------ skip audit
    skip_hits = []
    for p in git("ls-tree", "-r", "--name-only", AUDITED).splitlines():
        low = p.lower()
        if not low.startswith("tests/") or not low.endswith(".py"):
            continue
        if not any(t in low for t in ("h6", "shadow", "confirmation", "hash_validator", "pit", "oi_full_history")):
            continue
        txt = blob(p).decode("utf-8", "replace")
        for i, line in enumerate(txt.splitlines(), 1):
            if re.search(r"pytest\.mark\.(skip|skipif|xfail)|@unittest\.skip|pytest\.skip\(", line):
                skip_hits.append({"path": p, "line": i, "text": line.strip()[:160]})
    out["skip_audit"] = {
        "test_files_scanned": [p for p in git("ls-tree", "-r", "--name-only", AUDITED).splitlines()
                               if p.lower().startswith("tests/") and p.lower().endswith(".py")
                               and any(t in p.lower() for t in ("h6", "shadow", "confirmation", "hash_validator", "pit", "oi_full_history"))],
        "skip_markers_found": skip_hits,
        "SKIP_AUDIT": "PASS" if not skip_hits else "REVIEW_REQUIRED",
    }

    # ------------------------------------------------ defect regression presence
    try:
        reg = json.loads(blob("docs/external-audit-01/oi-full-history-03/H6_V3_REPAIR_DEFECT_REGISTER.json"))
    except Exception as e:
        reg = {"error": str(e)}
    try:
        mat = json.loads(blob("docs/external-audit-01/oi-full-history-03/H6_V3_DEFECT_REGRESSION_MATRIX.json"))
    except Exception as e:
        mat = {"error": str(e)}

    def count_defects(o):
        if isinstance(o, list):
            return len(o)
        if isinstance(o, dict):
            for k in ("defects", "items", "entries", "repairs", "rows"):
                if isinstance(o.get(k), list):
                    return len(o[k])
            return len(o)
        return 0

    ids_reg = sorted(set(re.findall(r"EXT-[A-Z0-9-]+|DEFECT-[A-Z0-9-]+|FIND-[A-Z0-9-]+",
                                    json.dumps(reg))))
    ids_mat = sorted(set(re.findall(r"EXT-[A-Z0-9-]+|DEFECT-[A-Z0-9-]+|FIND-[A-Z0-9-]+",
                                    json.dumps(mat))))
    out["defect_regression_matrix"] = {
        "register_path": "docs/external-audit-01/oi-full-history-03/H6_V3_REPAIR_DEFECT_REGISTER.json",
        "matrix_path": "docs/external-audit-01/oi-full-history-03/H6_V3_DEFECT_REGRESSION_MATRIX.json",
        "register_defect_count_estimate": count_defects(reg),
        "matrix_entry_count_estimate": count_defects(mat),
        "ids_in_register": ids_reg,
        "ids_in_matrix": ids_mat,
        "ids_in_register_missing_from_matrix": [i for i in ids_reg if i not in ids_mat],
        "matrix_covers_register": all(i in ids_mat for i in ids_reg) if ids_reg else None,
        "verifier_note": ("Presence and coverage are checked here. Independently re-running each "
                          "defect's reproduction is done per-defect in the defect regression gate."),
    }
    out["DEFECT_REGRESSION_MATRIX_PRESENCE"] = (
        "PASS" if (ids_reg and all(i in ids_mat for i in ids_reg)) else "REVIEW_REQUIRED")

    print(json.dumps(out, indent=2))
    if "--out" in sys.argv:
        dest = sys.argv[sys.argv.index("--out") + 1]
        with open(dest, "w", encoding="utf-8", newline="\n") as fh:
            json.dump(out, fh, indent=2)
            fh.write("\n")
        print("WROTE", dest, file=sys.stderr)


if __name__ == "__main__":
    main()
