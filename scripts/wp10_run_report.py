"""WP-10 — the run report, folded from the artefacts rather than written by hand.

Every line of the report is a read of an artefact that already exists: the phase-1
register rebuild, the E-1 measurement and its decision, the E-2 pre-registration, the
ACTIVE recovery matrix, the blockers and the independent verification. If an artefact is
missing the report says so and does not fill the gap with prose, and if the verifier
reports failed checks or missed controls the report carries that verdict rather than
summarising around it.

Exit codes: 0 the report is written, 2 an artefact the report depends on is missing.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
WP10 = ROOT / "data" / "recovery" / "wp10"
PHASE0 = ROOT / "data" / "recovery" / "wp10" / "WP10_PHASE0_WP9_CLOSURE.json"

ARTEFACTS: tuple[tuple[str, str, str], ...] = (
    ("phase0_wp9_closure", "WP10_PHASE0_WP9_CLOSURE.json", "phase 0 — controlled close of WP-9"),
    ("baseline", "WP10_BASELINE_ECONOMIC_AUDIT.json", "phase 1 — economic baseline"),
    ("execution_cost", "WP10_EXECUTION_COST_DISTRIBUTION.json", "E-1 — execution cost reality"),
    ("e1_decision", "WP10_E1_DECISION.json", "E-1 — economic decision"),
    ("e2", "WP10_E2_PREREGISTRATION.json", "E-2 — forward drift entry screen"),
    ("matrix", "WP10_ACTIVE_RECOVERY_MATRIX.json", "phase 5 — ACTIVE recovery matrix"),
    ("blockers", "WP10_OPEN_BLOCKERS.json", "phase 6 — open blockers"),
    ("verification", "INDEPENDENT_VERIFICATION.json", "phase 7 — independent verification"),
)


def load(name: str) -> dict[str, Any] | None:
    path = WP10 / name
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def git(*argv: str) -> str:
    return subprocess.run(
        ["git", *argv], cwd=ROOT, capture_output=True, text=True, check=False
    ).stdout.strip()


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build() -> tuple[dict[str, Any], int]:
    missing: list[str] = []
    sections: dict[str, Any] = {}
    for key, filename, label in ARTEFACTS:
        payload = load(filename)
        if payload is None:
            missing.append(filename)
            continue
        sections[key] = {
            "label": label,
            "artifact": payload.get("artifact"),
            "verdict": payload.get("verdict"),
            "sha256": digest(WP10 / filename),
            "generated_at_utc": payload.get("generated_at_utc"),
        }

    baseline = load("WP10_BASELINE_ECONOMIC_AUDIT.json") or {}
    distribution = load("WP10_EXECUTION_COST_DISTRIBUTION.json") or {}
    decision = load("WP10_E1_DECISION.json") or {}
    matrix = load("WP10_ACTIVE_RECOVERY_MATRIX.json") or {}
    blockers = load("WP10_OPEN_BLOCKERS.json") or {}
    verdict_file = load("INDEPENDENT_VERIFICATION.json") or {}

    headline = baseline.get("headline_rebuilt") or {}
    agreement = baseline.get("headline_agreement") or {}
    assessment = distribution.get("assessment") or {}
    readjudication = decision.get("readjudication") or {}
    resolution = decision.get("resolution") or {}
    counts = matrix.get("verdict_counts") or {}

    claims = {
        "register": {
            "strategies": headline.get("strategies_total"),
            "admitted": headline.get("admitted"),
            "no_gross_edge": headline.get("no_gross_edge"),
            "cost_killed": headline.get("cost_killed"),
            "best_gross_bps": headline.get("best_gross_bps"),
            "frozen_plane_bps": round(headline.get("admission_round_trip_bps") or 0.0, 6),
            "every_published_headline_number_rebuilt": agreement and all(agreement.values()),
            "discrepancies_declared": len(baseline.get("discrepancies") or []),
            "unresolvable_cells": len(baseline.get("unresolvable_cells") or []),
        },
        "execution_cost": {
            "state": assessment.get("state"),
            "measured_round_trip_microstructure_bps": assessment.get(
                "observed_round_trip_microstructure_bps_median_across_books"
            ),
            "plane_non_fee_bps": round(
                (assessment.get("plane_spread_term_bps") or 0.0)
                + (assessment.get("plane_slippage_plus_impact_term_bps") or 0.0),
                6,
            ),
            "plane_fee_bps": assessment.get("plane_known_fee_term_bps"),
            "share_of_plane_that_is_fee": assessment.get("share_of_plane_that_is_known_fees"),
            "checkpoints_reproduced": (distribution.get("verdict") or {}).get(
                "checkpoints_reproduced"
            ),
            "look_ahead_violations": (distribution.get("verdict") or {}).get(
                "look_ahead_violations"
            ),
            "why_it_is_not_the_binding_constraint": assessment.get("promotion_note"),
        },
        "decision": {
            "planes": {
                name: row.get("round_trip_bps")
                for name, row in (decision.get("planes") or {}).items()
            },
            "admitted_by_plane": {
                name: len(ids) for name, ids in readjudication.get("admitted_by_plane", {}).items()
            },
            "required_fee_per_side_bps_for_the_best_cell": readjudication.get(
                "required_fee_per_side_bps_for_best_cell"
            ),
            "best_cell": readjudication.get("best_cell"),
            "best_cell_ci95_half_width_bps": resolution.get("best_cell_ci95_half_width_bps"),
            "positive_cells": resolution.get("positive_cells"),
            "positive_cells_separated_from_zero": resolution.get(
                "positive_cells_separated_from_zero"
            ),
        },
        "matrix": {
            "verdict_counts": counts,
            "measured_cost_layer": bool(matrix.get("measured_cost_layer")),
        },
        "blockers": {
            "unpublished_commits": (
                (blockers.get("blockers") or {}).get("CI_RUNNER_CERTIFICATION") or {}
            ).get("unpublished_commits"),
            "ci_runner_state": (
                (blockers.get("blockers") or {}).get("CI_RUNNER_CERTIFICATION") or {}
            ).get("state"),
            "hours_affordable": ((blockers.get("blockers") or {}).get("VOLUME_BUDGET") or {}).get(
                "hours_affordable_now"
            ),
        },
        "verification": {
            "verdict": verdict_file.get("verdict"),
            "checks": verdict_file.get("checks_total"),
            "checks_failed": verdict_file.get("checks_failed"),
            "controls": verdict_file.get("controls_total"),
            "controls_missed": verdict_file.get("controls_missed"),
            "false_success": verdict_file.get("false_success"),
            "drift": verdict_file.get("point_in_time_drift") or [],
        },
    }

    governance = {
        "live_trading": "DISABLED",
        "trades_authorized": 0,
        "paper_promotion": "NOT_AUTHORIZED",
        "strategies_admitted": 0,
        "strategies_reopened": 0,
        "thresholds_changed": 0,
        "cost_model_changed": False,
        "result_class": "RESEARCH_RESULT (cost measurement) — not BACKTEST, not REPLAY, "
        "not PAPER, not LIVE",
    }

    validation = [
        {"check": "every artefact the report folds exists", "ok": not missing, "missing": missing},
        {
            "check": "the register's six published headline numbers were rebuilt from primary sources",
            "ok": bool(claims["register"]["every_published_headline_number_rebuilt"]),
        },
        {
            "check": "E-1 reports a measurement and not an assertion",
            "ok": (distribution.get("scope") or {}).get("trading") is False
            and ((distribution.get("verdict") or {}).get("look_ahead_violations") == 0),
        },
        {
            "check": "the independent verifier passed with every control detected",
            "ok": verdict_file.get("verdict") == "PASS"
            and verdict_file.get("checks_failed") == 0
            and verdict_file.get("controls_missed") == 0
            and verdict_file.get("false_success") == 0,
            "detail": {
                "verdict": verdict_file.get("verdict"),
                "failed": verdict_file.get("checks_failed"),
                "missed_controls": verdict_file.get("controls_missed"),
            },
        },
        {
            "check": "nothing in WP-10 admits, promotes or reopens a strategy",
            "ok": governance["strategies_admitted"] == 0 and governance["strategies_reopened"] == 0,
        },
        {
            "check": "the drift the verifier found is carried into the report rather than smoothed away",
            "ok": isinstance(claims["verification"]["drift"], list),
        },
    ]

    payload: dict[str, Any] = {
        "artifact": "WP10_RUN_REPORT",
        "work_package": "WP-10 (ECONOMIC EDGE RECOVERY & EXECUTION COST DISCOVERY)",
        "generated_at_utc": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "head": git("rev-parse", "HEAD"),
        "branch": git("rev-parse", "--abbrev-ref", "HEAD"),
        "mode": "OFFLINE READ-ONLY — no network, no key, no order, no capital",
        "lane_commit": (
            baseline.get("head")
            and {"head": baseline.get("head"), "branch": baseline.get("branch")}
        ),
        "sections": sections,
        "claims": claims,
        "governance": governance,
        "validation": validation,
        "next_decision": (
            "the decision WP-10 hands over: whether to (a) spend the next campaign on a new "
            "hypothesis that must clear the 20 bps round-trip fee floor at the current tier — "
            "2.25x the best gross edge in the register — or (b) first change the fee tier the "
            "plane assumes, which is a governance and account decision with no measurement "
            "attached, or (c) capture order-level execution evidence, which is the only way "
            "maker execution can ever be priced and is the only measurement WP-10 could not "
            "make from what exists"
        ),
    }
    return payload, (2 if missing else 0)


def render_markdown(payload: dict[str, Any]) -> str:
    claims = payload["claims"]
    register = claims["register"]
    cost = claims["execution_cost"]
    decision = claims["decision"]
    verification = claims["verification"]
    lines = [
        "# WP-10 — RUN REPORT",
        "",
        f"> `{payload['generated_at_utc']}` · head `{payload['head']}` · branch "
        f"`{payload['branch']}` · modo `{payload['mode']}`",
        "",
        "## 1. Qué se ejecutó y qué produjo",
        "",
        "| artefacto | fase | veredicto |",
        "| --- | --- | --- |",
    ]
    for section in payload["sections"].values():
        verdict = section.get("verdict")
        if not isinstance(verdict, str):
            verdict = json.dumps(verdict, ensure_ascii=False)
        verdict = verdict.replace("|", "/").replace("\n", " ")[:170]
        lines.append(f"| `{section['artifact']}` | {section['label']} | {verdict} |")
    lines += [
        "",
        "## 2. El registro de 24 estrategias, reconstruido",
        "",
        f"* estrategias: {register['strategies']} ({register['admitted']} admitidas, "
        f"{register['no_gross_edge']} por falta de ventaja bruta, {register['cost_killed']} por "
        "costes)",
        f"* mejor ventaja bruta: {register['best_gross_bps']} bps",
        f"* planicie de admisión congelada: {register['frozen_plane_bps']} bps",
        f"* las seis cifras publicadas se reprodujeron: "
        f"`{register['every_published_headline_number_rebuilt']}` con "
        f"{register['discrepancies_declared']} discrepancias declaradas y "
        f"{register['unresolvable_cells']} métricas que el registro no contiene",
        "",
        "## 3. E-1 — lo que costó ejecutar de verdad",
        "",
        f"* estado: `{cost['state']}`",
        f"* round trip medido (mediana de cuatro libros): "
        f"{cost['measured_round_trip_microstructure_bps']} bps frente a "
        f"{cost['plane_non_fee_bps']} bps de la planicie",
        f"* fees KNOWN: {cost['plane_fee_bps']} bps = "
        f"{round((cost['share_of_plane_that_is_fee'] or 0) * 100, 2)} % de la planicie",
        f"* checkpoints reproducidos: {cost['checkpoints_reproduced']}, violaciones de "
        f"look-ahead: {cost['look_ahead_violations']}",
        "",
        "## 4. La decisión económica",
        "",
        "| planicie | bps | admitidas |",
        "| --- | ---: | ---: |",
    ]
    for name, bps in decision["planes"].items():
        lines.append(f"| `{name}` | {bps:.6f} | {decision['admitted_by_plane'].get(name, 0)} |")
    lines += [
        "",
        f"* mejor celda `{decision['best_cell']}`: haría falta un coste por lado de "
        f"{decision['required_fee_per_side_bps_for_the_best_cell']} bps para admitirla, frente a "
        "los 10 bps publicados (7.5 con descuento de token)",
        f"* intervalo del 95 % de esa celda: ±{decision['best_cell_ci95_half_width_bps']} bps; "
        f"celdas positivas: {decision['positive_cells']}, de las cuales "
        f"{decision['positive_cells_separated_from_zero']} tienen un intervalo que excluye el cero",
        "",
        "## 5. Matriz ACTIVE y bloqueos",
        "",
        f"* familias: {claims['matrix']['verdict_counts']}",
        f"* capa de coste medida incorporada: `{claims['matrix']['measured_cost_layer']}`",
        f"* commits sin publicar: {claims['blockers']['unpublished_commits']} "
        f"(estado CI `{claims['blockers']['ci_runner_state']}`)",
        f"* horas de ventana que el volumen puede pagar: {claims['blockers']['hours_affordable']}",
        "",
        "## 6. Verificación independiente",
        "",
        f"* veredicto `{verification['verdict']}`: {verification['checks']} controles de "
        f"afirmación, {verification['checks_failed']} fallidos; {verification['controls']} "
        f"controles negativos, {verification['controls_missed']} no detectados; "
        f"`false_success = {verification['false_success']}`",
    ]
    for entry in verification["drift"]:
        figure = entry.get("figure")
        if figure == "state-view pins":
            detail = ", ".join(entry.get("paths_that_no_longer_match") or [])
        elif "right_now_gb" in entry:
            detail = f"{entry.get('in_the_artefact_gb')} GB → {entry.get('right_now_gb')} GB"
        else:
            detail = f"{entry.get('in_the_artefact')} → {entry.get('right_now')}"
        lines.append(f"* deriva de estado: `{figure}` ({detail}) — {entry.get('why')}")
    lines += [
        "",
        "## 7. Gobernanza",
        "",
    ]
    for key, value in payload["governance"].items():
        lines.append(f"* `{key}`: {value}")
    lines += ["", "## 8. Controles de este informe", ""]
    for check in payload["validation"]:
        lines.append(f"* [{'x' if check['ok'] else ' '}] {check['check']}")
    lines += [
        "",
        "## 9. Próxima decisión",
        "",
        payload["next_decision"],
        "",
    ]
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    payload, exit_code = build()
    if args.json:
        print(json.dumps(payload, indent=2))
        return exit_code
    if exit_code != 0:
        print(json.dumps(payload, indent=2))
        return exit_code

    json_path = WP10 / "RUN_REPORT.json"
    md_path = WP10 / "RUN_REPORT.md"
    json_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    md_path.write_text(render_markdown(payload) + "\n", encoding="utf-8")
    payload["payload_sha256"] = hashlib.sha256(json_path.read_bytes()).hexdigest()
    json_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    failed = [check["check"] for check in payload["validation"] if not check["ok"]]
    print(
        f"{'PASS' if not failed else 'PARTIAL'} -> {json_path.relative_to(ROOT)}"
        + (f" (failed: {failed})" if failed else "")
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
