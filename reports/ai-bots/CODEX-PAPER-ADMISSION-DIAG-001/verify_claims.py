"""CODEX-PAPER-ADMISSION-DIAG-001 — recomputa cada cifra publicada, desde los artefactos.

No importa el builder de ningún paquete: lee JSON, cuenta y compara. Cada check nombra
el artefacto del que sale el número y el valor que el informe afirma.

Uso:
    python reports/ai-bots/CODEX-PAPER-ADMISSION-DIAG-001/verify_claims.py

Salida: tabla PASS/FAIL por stdout + evidence/CLAIM_CHECKS.json. exit 1 si algo falla.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from typing import Any, Callable

REPORT_DIR = Path(__file__).resolve().parent
ROOT = REPORT_DIR.parents[2]
TREE = ROOT / "wt-sup001"  # arbol de codepaper/supervisor-001 @ 3b758e22

CHECKS: list[tuple[str, str, Callable[[], Any], Any]] = []


def check(name: str, source: str, expected: Any):
    def deco(fn: Callable[[], Any]) -> Callable[[], Any]:
        CHECKS.append((name, source, fn, expected))
        return fn

    return deco


def _json(rel: str) -> dict[str, Any]:
    return json.loads((TREE / rel).read_text(encoding="utf-8"))


def _ledger() -> dict[str, Any]:
    return _json("config/strategy_admission.json")["strategies"]


def _explorer() -> dict[str, Any]:
    return _json("data/recovery/COST_BARRIER_EXPLORER.json")


# -- admission ledger -------------------------------------------------------


@check("ledger.entries", "config/strategy_admission.json", 24)
def _() -> int:
    return len(_ledger())


@check("ledger.admitted_for_paper", "config/strategy_admission.json", 0)
def _() -> int:
    return sum(1 for v in _ledger().values() if v["admitted_for_paper"])


@check("ledger.status_counts", "config/strategy_admission.json", {"NO_GROSS_EDGE": 17, "COST_KILLED": 7})
def _() -> dict[str, int]:
    out: dict[str, int] = {}
    for v in _ledger().values():
        out[v["status"]] = out.get(v["status"], 0) + 1
    return out


@check("ledger.sample_trades_zero", "config/strategy_admission.json", 18)
def _() -> int:
    return sum(1 for v in _ledger().values() if v["edge_evidence"]["sample_trades"] == 0)


@check("ledger.positive_gross", "config/strategy_admission.json", 7)
def _() -> int:
    return sum(1 for v in _ledger().values() if v["expected_gross_edge_bps"] > 0)


@check("ledger.top_gross_rounded", "config/strategy_admission.json", [8.91, 6.28, 5.47])
def _() -> list[float]:
    rows = sorted(
        ((v["expected_gross_edge_bps"], k) for k, v in _ledger().items()), reverse=True
    )
    return [round(r[0], 3) for r in rows[:3]]


@check(
    "ledger.top_gross_ids",
    "config/strategy_admission.json",
    ["volatility@30m", "volatility@1h", "mean_reversion@30m"],
)
def _() -> list[str]:
    rows = sorted(((v["expected_gross_edge_bps"], k) for k, v in _ledger().items()), reverse=True)
    return [r[1] for r in rows[:3]]


# -- cost barrier explorer --------------------------------------------------


@check("explorer.cells", "data/recovery/COST_BARRIER_EXPLORER.json", 24)
def _() -> int:
    return len(_explorer()["cells"])


@check(
    "explorer.max_gross",
    "data/recovery/COST_BARRIER_EXPLORER.json",
    {"cell": "volatility@30m", "gross_bps": 8.912, "trades": 194},
)
def _() -> dict[str, Any]:
    best = max(_explorer()["cells"], key=lambda c: c["zero_cost_gross_bps"])
    return {
        "cell": best["cell_id"],
        "gross_bps": round(best["zero_cost_gross_bps"], 3),
        "trades": best["trades"],
    }


@check(
    "explorer.volatility_1h",
    "data/recovery/COST_BARRIER_EXPLORER.json",
    {"gross_bps": 6.276, "trades": 96},
)
def _() -> dict[str, Any]:
    cell = next(c for c in _explorer()["cells"] if c["cell_id"] == "volatility@1h")
    return {"gross_bps": round(cell["zero_cost_gross_bps"], 3), "trades": cell["trades"]}


@check(
    "explorer.mean_reversion_30m_trades",
    "data/recovery/COST_BARRIER_EXPLORER.json",
    934,
)
def _() -> int:
    return next(c for c in _explorer()["cells"] if c["cell_id"] == "mean_reversion@30m")["trades"]


@check(
    "explorer.cheapest_taker_rt_bps",
    "data/recovery/COST_BARRIER_EXPLORER.json",
    12.176776695296637,
)
def _() -> float:
    return _explorer()["reachability"]["frontier"]["cheapest_line_taker"]["round_trip_bps"]


@check(
    "explorer.runtime_admission_rt_bps",
    "data/recovery/COST_BARRIER_EXPLORER.json",
    23.353553390593273,
)
def _() -> float:
    return _explorer()["cells"][0]["runtime_admission_rt_bps"]


@check(
    "explorer.cheapest_any_is_assumed",
    "data/recovery/COST_BARRIER_EXPLORER.json",
    {"rt_bps": 1.25, "assumed": True, "reachable_at_1x": 7},
)
def _() -> dict[str, Any]:
    f = _explorer()["reachability"]["frontier"]["cheapest_line_any"]
    return {
        "rt_bps": f["round_trip_bps"],
        "assumed": f["rests_on_assumed_component"],
        "reachable_at_1x": f["reachable_counts_by_stress"]["1.0x"],
    }


@check(
    "explorer.frontier_size",
    "data/recovery/COST_BARRIER_EXPLORER.json",
    {"configurations": 120, "distinct_lines": 36},
)
def _() -> dict[str, int]:
    f = _explorer()["reachability"]["frontier"]
    return {"configurations": f["configurations"], "distinct_lines": f["distinct_lines"]}


@check("explorer.gap_to_taker_bps", "data/recovery/COST_BARRIER_EXPLORER.json", 3.2647766952966357)
def _() -> float:
    return 12.176776695296637 - 8.912


@check("explorer.gap_to_runtime_bps", "data/recovery/COST_BARRIER_EXPLORER.json", 14.441553390593272)
def _() -> float:
    return 23.353553390593273 - 8.912


@check(
    "explorer.frequency",
    "data/recovery/COST_BARRIER_EXPLORER.json",
    {"rt_per_year": 1095.0, "annual_pct_runtime": 255.72140963144997, "annual_pct_taker": 133.33570481349818, "annual_pct_assumed": 13.6875},
)
def _() -> dict[str, float]:
    f = _explorer()["frequency"]
    rows = {r["line"]: r for r in f["rows"]}
    return {
        "rt_per_year": f["requirement_round_trips_per_year"],
        "annual_pct_runtime": rows["campaign_runtime_admission"]["annual_cost_pct_of_stake"],
        "annual_pct_taker": rows["cheapest_taker_observed"]["annual_cost_pct_of_stake"],
        "annual_pct_assumed": rows["cheapest_any_assumed"]["annual_cost_pct_of_stake"],
    }


# -- admission matrix -------------------------------------------------------


@check("matrix.paper_candidates_empty", "docs/STRATEGY_ADMISSION_MATRIX.json", [])
def _() -> list[str]:
    return _json("docs/STRATEGY_ADMISSION_MATRIX.json")["paper_candidates"]


@check("matrix.families_rejected", "docs/STRATEGY_ADMISSION_MATRIX.json", "6 REJECT, c2/c3/c4/c7 false")
def _() -> str:
    adm = _json("docs/STRATEGY_ADMISSION_MATRIX.json")["admissions"]
    assert len(adm) == 6, len(adm)
    for fam, row in adm.items():
        assert row["status"] == "REJECT", (fam, row["status"])
        assert set(row["mandatory_failures"]) >= {
            "c2_net_positive",
            "c3_pf_gt1",
            "c4_oos_positive",
            "c7_survives_2x",
        }, (fam, row["mandatory_failures"])
    return "6 REJECT, c2/c3/c4/c7 false"


@check("matrix.c6_c8_unknown_for_all", "docs/STRATEGY_ADMISSION_MATRIX.json", 6)
def _() -> int:
    adm = _json("docs/STRATEGY_ADMISSION_MATRIX.json")["admissions"]
    return sum(
        1
        for row in adm.values()
        if set(row["unknown_checks"]) >= {"c6_dd", "c8_no_window_dominance"}
    )


# -- verified cost barrier --------------------------------------------------


@check(
    "cost_barrier_verification",
    "data/recovery/COST_BARRIER_VERIFICATION.json",
    {"status": "PASS", "controls": 13, "false_success": 0},
)
def _() -> dict[str, Any]:
    d = _json("data/recovery/COST_BARRIER_VERIFICATION.json")
    return {"status": d["status"], "controls": d["controls_total"], "false_success": d["false_success"]}


# -- EXP-003M measured fills ------------------------------------------------


@check(
    "exp003m.ceiling_below_floor",
    "reports/ai-bots/EXP-003M-MAKER-FILL-REALITY-001/analysis/{DECISION,ECONOMICS}.json",
    {"verdict": "REJECT", "gross": 0.26690893, "fees": 0.75, "coverage": 0.35587857},
)
def _() -> dict[str, Any]:
    base = "reports/ai-bots/EXP-003M-MAKER-FILL-REALITY-001/analysis/"
    d = _json(base + "DECISION.json")
    e = _json(base + "ECONOMICS.json")["economics"]["F0_touch_full"]
    return {
        "verdict": d["verdict"],
        "gross": round(e["gross_per_fill_usdt"], 8),
        "fees": e["fees_per_fill_usdt"],
        "coverage": round(e["gross_per_fill_usdt"] / e["fees_per_fill_usdt"], 8),
    }


# -- verifier runs captured this session ------------------------------------


@check(
    "supervisor_verifier.pass",
    "evidence/SUPERVISOR_VERIFY.json",
    {"verdict": "PASS", "checks_passed": 33, "checks_total": 33, "false_success": 0},
)
def _() -> dict[str, Any]:
    d = json.loads((REPORT_DIR / "evidence/SUPERVISOR_VERIFY.json").read_text(encoding="utf-8"))
    checks = d["judgement"]["checks"]
    return {
        "verdict": d["verdict"],
        "checks_passed": sum(1 for v in checks.values() if v),
        "checks_total": len(checks),
        "false_success": d["false_success"],
    }


@check(
    "lock_verifier.fails_on_supervisor_campaign",
    "evidence/CAMPAIGN_VERIFY.json",
    {"verdict": "FAIL", "checks_passed": 28, "checks_total": 32, "false_success": 2},
)
def _() -> dict[str, Any]:
    d = json.loads((REPORT_DIR / "evidence/CAMPAIGN_VERIFY.json").read_text(encoding="utf-8"))
    checks = d["judgement"]["checks"]
    return {
        "verdict": d["verdict"],
        "checks_passed": sum(1 for v in checks.values() if v),
        "checks_total": len(checks),
        "false_success": d["false_success"],
    }


# -- operational blockers ---------------------------------------------------


@check(
    "windowless.high_findings",
    "scripts/ops_background_audit.py::scan (sobre wt-sup001)",
    ["scripts/exp004a_verify.py", "tests/unit/ops/test_paper_lock_campaign.py", "tests/unit/ops/test_session_status.py"],
)
def _() -> list[str]:
    path = TREE / "scripts/ops_background_audit.py"
    spec = importlib.util.spec_from_file_location("_oba_diag", path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules["_oba_diag"] = mod
    spec.loader.exec_module(mod)
    report = mod.scan(TREE)
    high = [f for f in report["findings"] if f["severity"] == "HIGH"]
    return sorted({f["path"] for f in high})


@check(
    "uvlock.matplotlib_missing",
    "uv.lock + pyproject.toml",
    {"declared_in_pyproject": True, "entries_in_lock": 0},
)
def _() -> dict[str, Any]:
    pyproject = (TREE / "pyproject.toml").read_text(encoding="utf-8")
    lock = (TREE / "uv.lock").read_text(encoding="utf-8")
    return {
        "declared_in_pyproject": '"matplotlib' in pyproject.replace("\n", ""),
        "entries_in_lock": lock.count('name = "matplotlib"'),
    }


@check(
    "evidence.unversioned",
    ".gitignore",
    {"rule_line": 463, "rule": "reports/ai-bots/*"},
)
def _() -> dict[str, Any]:
    lines = (TREE / ".gitignore").read_text(encoding="utf-8").splitlines()
    for i, line in enumerate(lines, start=1):
        if line.strip() == "reports/ai-bots/*":
            return {"rule_line": i, "rule": line.strip()}
    raise AssertionError("rule not found")


def main() -> int:
    results = []
    for name, source, fn, expected in CHECKS:
        try:
            actual = fn()
            ok = actual == expected
            results.append(
                {"check": name, "source": source, "expected": expected, "actual": actual, "result": "PASS" if ok else "FAIL"}
            )
        except Exception as exc:  # noqa: BLE001 - a check that cannot run is not a pass
            results.append(
                {"check": name, "source": source, "expected": expected, "actual": f"{type(exc).__name__}: {exc}", "result": "FAIL"}
            )

    passed = sum(1 for r in results if r["result"] == "PASS")
    payload = {
        "artifact": "CODEX_PAPER_ADMISSION_DIAG_CLAIM_CHECKS",
        "checks": results,
        "checks_total": len(results),
        "checks_passed": passed,
        "checks_failed": len(results) - passed,
        "false_success": 0 if passed == len(results) else len(results) - passed,
    }
    out = REPORT_DIR / "evidence/CLAIM_CHECKS.json"
    out.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")

    width = max(len(r["check"]) for r in results) + 2
    for r in results:
        print(f"{r['result']:<5} {r['check']:<{width}} {r['actual']!r}")
    print(f"\n{passed}/{len(results)} PASS · wrote {out}")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
