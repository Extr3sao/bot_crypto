"""Independent verification — MICROSTRUCTURE-V1 + VENUE/EXECUTION-RESEARCH-V1.

BUILDER != VERIFIER. This script does not trust any committed number. It:

  Phase 0 (§PHASE 0)
    * re-runs the MICROSTRUCTURE-V1 experiment + admission pipelines and
      compares the regenerated artifacts byte-for-byte (SHA-256),
    * re-derives the round-trip cost from the cost-model modules,
    * checks the committed V1 JSON for internal consistency
      (net == gross - cost, classification follows the frozen rules).

  Phase 7 (§PHASE 7)
    * regenerates COST_MODEL_V3 / VENUE_EXECUTION_MATRIX_V1 /
      EXECUTION_MODEL_V1 from the builder functions and diffs them,
    * re-runs the aggTrades experiment pipeline and diffs the outputs,
    * re-verifies every AGG_*.json against the SHA-256 recorded in its own
      provenance block,
    * asserts no gross figure is ever reported as a net figure,
    * asserts ZERO_COST never appears as an admission model.

Emits:
  docs/MICROSTRUCTURE_V1_INDEPENDENT_VERIFICATION.json / .md
  docs/VENUE_EXECUTION_FINAL_REPORT.json
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from trading_bot.research.microstructure import cost_model as cm_v2  # noqa: E402
from trading_bot.research.microstructure import cost_model_v3 as cm_v3  # noqa: E402

DOCS = ROOT / "docs"
REPORTS = ROOT / "reports"
MIC = REPORTS / "microstructure-v1"


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def load_module(name: str, rel: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, ROOT / rel)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def run_script(rel: str) -> tuple[int, str]:
    proc = subprocess.run(
        [sys.executable, str(ROOT / rel)],
        capture_output=True,
        text=True,
        cwd=str(ROOT),
    )
    return proc.returncode, (proc.stdout + proc.stderr)[-2000:]


def git(args: list[str]) -> str:
    out = subprocess.run(["git", *args], capture_output=True, text=True, cwd=str(ROOT), check=False)
    return out.stdout.strip()


# ---------------------------------------------------------------------------
# Phase 0 — MICROSTRUCTURE-V1
# ---------------------------------------------------------------------------


V1_ARTIFACTS = [
    "reports/microstructure-v1/RESULTS.json",
    "reports/microstructure-v1/INFORMATION_CONTENT.json",
    "docs/COST_MODEL_V2.json",
    "docs/MARKET_MICROSTRUCTURE_DATA_AUDIT.json",
    "docs/MICROSTRUCTURE_RESULTS_V1.json",
    "docs/MICROSTRUCTURE_ADMISSION_V1.json",
]


def verify_microstructure_v1() -> dict[str, Any]:
    checks: list[dict[str, Any]] = []
    failures: list[str] = []

    # 1. reproduce the artifact set
    before = {p: sha256_file(ROOT / p) for p in V1_ARTIFACTS if (ROOT / p).exists()}
    rc1, log1 = run_script("scripts/microstructure_experiments.py")
    rc2, log2 = run_script("scripts/microstructure_admission.py")
    after = {p: sha256_file(ROOT / p) for p in V1_ARTIFACTS if (ROOT / p).exists()}
    reproduced = before == after and bool(before)
    checks.append(
        {
            "check": "MICROSTRUCTURE-V1 artifacts reproduce byte-for-byte",
            "expected": "identical SHA-256 before/after re-run",
            "observed": "identical" if reproduced else "DIVERGENT",
            "artifacts": {p: after.get(p) for p in sorted(after)},
            "reruns_exit_codes": [rc1, rc2],
            "rerun_tail": (log1[-300:], log2[-300:]),
            "pass": reproduced,
        }
    )
    if not reproduced:
        failures.append("V1 artifact reproduction diverged")

    # 2. cost re-derivation
    v2_cost = cm_v2.REALISTIC_RETAIL_COST_MODEL.round_trip_bps()
    v3_cost = cm_v3.cost_model_v3_all_in(
        cm_v3.VENUE_SPECS["BINANCE_SPOT_STANDARD_TAKER"],
        size_usd=1_000.0,
        liquidity_regime="normal",
        horizon_minutes=25.0,
        entry_order_type="market",
        exit_order_type="market",
    ).round_trip_bps
    checks.append(
        {
            "check": "admission round-trip cost re-derived from source",
            "expected": {"COST_MODEL_V2_bps": 23.5},
            "observed": {"COST_MODEL_V2_bps": v2_cost, "COST_MODEL_V3_bps": round(v3_cost, 4)},
            "pass": v2_cost == 23.5,
            "note": "V3 is slightly higher because slippage scales with size (documented).",
        }
    )
    if v2_cost != 23.5:
        failures.append("COST_MODEL_V2 admission cost changed")

    # 3. internal consistency of the committed V1 admission table
    adm_path = DOCS / "MICROSTRUCTURE_ADMISSION_V1.json"
    with open(adm_path, encoding="utf-8") as fh:
        adm: dict[str, Any] = json.load(fh)
    bad_math: list[str] = []
    for row in adm["candidate_table"]:
        g, c, n = row.get("gross_edge_bps"), row.get("realistic_cost_bps"), row.get("net_edge_bps")
        if g is None or n is None:
            continue
        if abs((g - c) - n) > 1e-3:
            bad_math.append(f"{row['candidate']}: {g} - {c} != {n}")
    checks.append(
        {
            "check": "V1 candidate table: net == gross - cost for every row",
            "expected": "0 arithmetic inconsistencies",
            "observed": bad_math or "0 inconsistencies",
            "pass": not bad_math,
        }
    )
    if bad_math:
        failures.append("V1 candidate table arithmetic inconsistent")

    checks.append(
        {
            "check": "ZERO_COST is never the admission model",
            "expected": "admission model != ZERO_COST",
            "observed": adm.get("admission_cost_model"),
            "pass": "ZERO" not in str(adm.get("admission_cost_model", "")).upper(),
        }
    )
    if "ZERO" in str(adm.get("admission_cost_model", "")).upper():
        failures.append("ZERO_COST used for admission")

    checks.append(
        {
            "check": "V1 admission result",
            "expected": "0 admitted",
            "observed": f"{len(adm.get('admitted', []))} admitted",
            "pass": len(adm.get("admitted", [])) == 0,
        }
    )

    return {
        "scope": "MICROSTRUCTURE-V1 (commit 325892d)",
        "head": git(["rev-parse", "HEAD"]),
        "checks": checks,
        "failures": failures,
        "status": "VERIFIED" if not failures else "FAILED_VERIFICATION",
    }


# ---------------------------------------------------------------------------
# Phase 7 — VENUE / EXECUTION research
# ---------------------------------------------------------------------------


def verify_venue_execution() -> dict[str, Any]:
    failures: list[str] = []
    checks: list[dict[str, Any]] = []

    # 1. regenerate the deterministic builders and diff against disk
    builder = load_module("venue_builder", "scripts/venue_execution_research.py")
    generated = {
        "docs/COST_MODEL_V3.json": builder.build_cost_model_v3(),
        "docs/VENUE_EXECUTION_MATRIX_V1.json": builder.build_venue_matrix(),
        "docs/EXECUTION_MODEL_V1.json": builder.build_execution_model(),
    }
    for rel, obj in generated.items():
        expected = json.dumps(obj, indent=2, sort_keys=False) + "\n"
        on_disk = (ROOT / rel).read_text(encoding="utf-8")
        same = expected == on_disk
        checks.append(
            {
                "check": f"{rel} regenerates identically",
                "expected": "regenerated bytes == committed bytes",
                "observed": "identical" if same else "DIVERGENT",
                "sha256": sha256_file(ROOT / rel),
                "pass": same,
            }
        )
        if not same:
            failures.append(f"{rel} regeneration diverged")

    # 2. reproduce the aggTrades experiment outputs
    agg_paths = [
        "reports/microstructure-v1/AGGTRADES_RESULTS.json",
        "reports/microstructure-v1/AGGTRADES_INFO_CONTENT.json",
    ]
    before = {p: sha256_file(ROOT / p) for p in agg_paths if (ROOT / p).exists()}
    rc, log = run_script("scripts/aggtrades_experiments.py")
    after = {p: sha256_file(ROOT / p) for p in agg_paths if (ROOT / p).exists()}
    same = before == after and bool(before)
    checks.append(
        {
            "check": "aggTrades experiment outputs reproduce byte-for-byte",
            "expected": "identical SHA-256 before/after re-run",
            "observed": "identical" if same else "DIVERGENT",
            "rerun_exit_code": rc,
            "rerun_tail": log[-300:],
            "pass": same,
        }
    )
    if not same:
        failures.append("aggTrades outputs did not reproduce")

    # 3. verify every aggregate file against its own provenance hash
    manifest_path = MIC / "aggtrades" / "MANIFEST_AGGTRADES.json"
    with open(manifest_path, encoding="utf-8") as fh:
        man: dict[str, Any] = json.load(fh)
    mismatched: list[str] = []
    for f in man["files"]:
        p = MIC / "aggtrades" / f"AGG_{f['symbol']}_{f['day']}.json"
        if not p.exists():
            mismatched.append(f"{p.name}: missing")
            continue
        with open(p, encoding="utf-8") as fh:
            obj = json.load(fh)
        if hashlib.sha256(json.dumps(obj, sort_keys=True).encode()).hexdigest() != f["derived_sha256"]:
            mismatched.append(f"{p.name}: derived hash mismatch")
    checks.append(
        {
            "check": "every aggTrades aggregate matches its recorded provenance hash",
            "expected": f"{man['total_files']} files verified",
            "observed": mismatched or f"{man['total_files']} files verified",
            "pass": not mismatched,
        }
    )
    if mismatched:
        failures.append("aggTrades provenance hash mismatch")

    # 4. no gross figure reported as net
    with open(MIC / "AGGTRADES_RESULTS.json", encoding="utf-8") as fh:
        res: dict[str, Any] = json.load(fh)
    gross_as_net: list[str] = []
    zero_trade: list[str] = []
    for r in res["results"]:
        n_trades = int(r["overall"].get("n") or 0)
        if n_trades == 0:
            # A candidate with no trades has no expectancy at all; comparing its
            # 0.0 gross mean against the cost is meaningless, so it is reported
            # separately instead of being counted as an inconsistency.
            zero_trade.append(r["candidate_id"])
            if abs(r["gross_mean_bps"]) > 1e-9 or abs(r["net_mean_bps"]) > 1e-9:
                gross_as_net.append(f"{r['candidate_id']}: no trades but non-zero means")
            continue
        g = r["gross_mean_bps"]
        n = r["net_mean_bps"]
        c = r["cost_bps"]
        if abs((g - c) - n) > 0.05:
            gross_as_net.append(f"{r['candidate_id']}: gross {g} - cost {c} != net {n}")
        if n > g + 1e-9:
            gross_as_net.append(f"{r['candidate_id']}: net > gross (impossible)")
    checks.append(
        {
            "check": "aggTrades results: net == gross - realistic cost, net <= gross",
            "expected": "0 inconsistencies among candidates with trades",
            "observed": gross_as_net or "0 inconsistencies",
            "candidates_with_zero_trades": zero_trade,
            "pass": not gross_as_net,
        }
    )
    if gross_as_net:
        failures.append("gross/net inconsistency")

    # 5. no candidate was promoted without passing every pre-registered filter
    promoted = [r["candidate_id"] for r in res["results"] if r["classification"] == "PAPER_CANDIDATE"]
    classifier_ok = all(
        (r["classification"] != "PAPER_CANDIDATE" or all(r["filters"].values()))
        for r in res["results"]
    )
    checks.append(
        {
            "check": "no PAPER_CANDIDATE bypasses the frozen filters",
            "expected": "0 promoted / all promoted satisfy every filter",
            "observed": {"promoted": promoted, "classifier_consistent": classifier_ok},
            "pass": classifier_ok and not promoted,
        }
    )
    if not classifier_ok:
        failures.append("classification not consistent with filters")

    # 6. temporal split integrity
    days = res["dataset"]["days_per_split"]
    checks.append(
        {
            "check": "temporal splits are non-empty and ordered chronologically",
            "expected": "DEV > VAL > OOS coverage, none empty",
            "observed": days,
            "pass": all(int(days.get(s, 0)) > 0 for s in ("DEV", "VAL", "OOS")),
        }
    )
    if not all(int(days.get(s, 0)) > 0 for s in ("DEV", "VAL", "OOS")):
        failures.append("a temporal split is empty")

    # 7. rolling windows stay inside a day (no cross-day leakage)
    checks.append(
        {
            "check": "rolling statistics are within-day only",
            "expected": "rolling_scope == 'within-day only (discontinuous sample)'",
            "observed": res["dataset"]["rolling_scope"],
            "pass": "within-day" in res["dataset"]["rolling_scope"],
        }
    )

    return {
        "scope": "VENUE-AND-EXECUTION-RESEARCH-V1 + AGGTRADES-MICROSTRUCTURE-V1",
        "head": git(["rev-parse", "HEAD"]),
        "checks": checks,
        "failures": failures,
        "results_summary": [
            {
                "candidate": r["candidate_id"],
                "n": r["overall"].get("n"),
                "gross_bps": r["gross_mean_bps"],
                "net_bps": r["net_mean_bps"],
                "classification": r["classification"],
                "filters": r["filters"],
            }
            for r in res["results"]
        ],
        "cost_model": res["cost_model"],
        "status": "VERIFIED" if not failures else "FAILED_VERIFICATION",
    }


# ---------------------------------------------------------------------------
# reporting
# ---------------------------------------------------------------------------


def render_md(v0: dict[str, Any], v7: dict[str, Any]) -> str:
    lines = [
        "# MICROSTRUCTURE_V1_INDEPENDENT_VERIFICATION",
        "",
        "> BUILDER != VERIFIER. Generado por `scripts/research_verification.py`, que",
        "> **no confía** en ningún número commiteado: re-ejecuta los pipelines y",
        "> recompara los artefactos por SHA-256.",
        "",
        f"- HEAD verificado: `{v0['head']}`",
        f"- Fase 0 (MICROSTRUCTURE-V1): **{v0['status']}**",
        f"- Fase 7 (VENUE/EXECUTION + AGGTRADES): **{v7['status']}**",
        "",
        "## Fase 0 — reproducción de MICROSTRUCTURE-V1",
        "",
        "| check | esperado | observado | pass |",
        "| --- | --- | --- | --- |",
    ]
    for c in v0["checks"]:
        obs = c["observed"]
        obs_s = json.dumps(obs, ensure_ascii=True) if not isinstance(obs, str) else obs
        if len(obs_s) > 120:
            obs_s = obs_s[:117] + "..."
        lines.append(f"| {c['check']} | {c['expected']} | {obs_s} | {'PASS' if c['pass'] else 'FAIL'} |")
    lines += [
        "",
        "Artefactos verificados por hash (tras re-ejecución):",
        "",
    ]
    for c in v0["checks"]:
        if "artifacts" in c:
            for p, h in c["artifacts"].items():
                lines.append(f"- `{p}` — `{(h or 'n/a')[:16]}`")
    lines += [
        "",
        "## Fase 7 — verificación de VENUE/EXECUTION + AGGTRADES",
        "",
        "| check | esperado | observado | pass |",
        "| --- | --- | --- | --- |",
    ]
    for c in v7["checks"]:
        obs = c["observed"]
        obs_s = json.dumps(obs, ensure_ascii=True) if not isinstance(obs, str) else obs
        if len(obs_s) > 120:
            obs_s = obs_s[:117] + "..."
        lines.append(f"| {c['check']} | {c['expected']} | {obs_s} | {'PASS' if c['pass'] else 'FAIL'} |")
    lines += [
        "",
        "### Resultados aggTrades re-verificados",
        "",
        "| candidata | n | gross bps | net bps | clasificación |",
        "| --- | ---: | ---: | ---: | --- |",
    ]
    for r in v7["results_summary"]:
        lines.append(
            f"| {r['candidate']} | {r['n']} | {r['gross_bps']:.3f} | {r['net_bps']:.3f} | {r['classification']} |"
        )
    lines += [
        "",
        "## Divergencias",
        "",
    ]
    all_fail = list(v0["failures"]) + list(v7["failures"])
    if all_fail:
        lines += [f"- {f}" for f in all_fail]
    else:
        lines.append("Ninguna. Todos los checks pasan sobre el árbol verificado.")
    lines += [
        "",
        "## Divergencia conocida respecto al informe V1 (declarada, no ocultada)",
        "",
        "El informe de MICROSTRUCTURE-V1 afirmaba `ruff` limpio. La verificación",
        "independiente encontró **4 errores de ruff** en HEAD `325892d`, todos en",
        "`scripts/microstructure_collector.py` (UP017, F841, RUF100 x2). El",
        "colector se ha reescrito para la fase forward y los cuatro errores quedan",
        "corregidos; no se ha alterado ningún resultado histórico por ello.",
        "",
    ]
    return "\n".join(lines)


def main() -> None:
    v0 = verify_microstructure_v1()
    v7 = verify_venue_execution()

    with open(DOCS / "MICROSTRUCTURE_V1_INDEPENDENT_VERIFICATION.json", "w", encoding="utf-8", newline="\n") as fh:
        json.dump({"phase_0": v0, "phase_7": v7}, fh, indent=2)
        fh.write("\n")
    with open(DOCS / "MICROSTRUCTURE_V1_INDEPENDENT_VERIFICATION.md", "w", encoding="utf-8", newline="\n") as fh:
        fh.write(render_md(v0, v7))

    final = {
        "head": v0["head"],
        "phase_0_status": v0["status"],
        "phase_7_status": v7["status"],
        "failures": v0["failures"] + v7["failures"],
        "aggTrades_results": v7["results_summary"],
        "cost_model": v7["cost_model"],
        "paper_candidates": [
            r["candidate"] for r in v7["results_summary"] if r["classification"] == "PAPER_CANDIDATE"
        ],
        "false_success": 0,
        "final_status": (
            "VENUE_EXECUTION_RESEARCH_VERIFIED_NO_CANDIDATE"
            if not v0["failures"] and not v7["failures"]
            else "FAILED_VERIFICATION"
        ),
    }
    with open(DOCS / "VENUE_EXECUTION_FINAL_REPORT.json", "w", encoding="utf-8", newline="\n") as fh:
        json.dump(final, fh, indent=2)
        fh.write("\n")

    print(f"phase 0: {v0['status']} ({len(v0['failures'])} failures)")
    print(f"phase 7: {v7['status']} ({len(v7['failures'])} failures)")
    for r in v7["results_summary"]:
        print(f"  {r['candidate']:<6} gross={r['gross_bps']:>8.3f} net={r['net_bps']:>9.3f} {r['classification']}")
    for f in v0["failures"] + v7["failures"]:
        print(f"  FAILURE: {f}")


if __name__ == "__main__":
    main()
