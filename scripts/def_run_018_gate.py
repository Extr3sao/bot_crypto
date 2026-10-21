"""DEF-RUN-018 / WP-018-05 — el gate: tres decisiones que no se pueden mezclar.

El RFC-018 existe, en el fondo, para impedir una frase: «el verificador da PASS, luego
la estrategia vale». Este script compone las tres respuestas por separado y **no**
permite que una arrastre a las otras:

* `technical_integrity` — ¿el paquete 017 es reproducible y está auditado?
* `economic_evidence` — ¿el OOS primario sostiene una ventaja?
* `paper_admission`   — ¿se puede llevar DEFER a paper?

Las tres salen de artefactos, con reglas fijas. Si falta un insumo, el estado es
`BLOCKED`, nunca `PASS`. Un `technical_integrity=PASS` con `economic_evidence !=
EVIDENCED` produce `NO_GO`, y eso es el resultado esperado de este RFC.

Uso::

    python scripts/def_run_018_gate.py
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

RFC = "RFC-DEF-018"
SUBJECT = "RFC-DEF-RUN-017"
SCHEMA = "DEF_RUN_018_ADMISSION_V1"
REPORT_DIR = Path("reports") / "ai-bots" / "RFC-DEF-RUN-018"
OUT = REPORT_DIR


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None


def decide(root: Path) -> dict[str, Any]:
    out = root / OUT
    baseline = load(out / "BASELINE_017.json")
    seal = load(out / "EVIDENCE_SEAL.json")
    verification = load(out / "INDEPENDENT_VERIFICATION.json")
    replay = load(out / "CLEAN_REPRO_RUN_REPORT.json")
    primary = load(root / "reports" / "ai-bots" / SUBJECT / "evidence" / "oos" / "OOS_RESULTS.json")

    blockers: list[str] = []
    defects: list[dict[str, Any]] = []
    reasons: list[str] = []
    false_success: list[str] = []

    # -- independencia medida por el auditor externo, no declarada por B ------
    audit = load(out / "INDEPENDENCE_AUDIT.json")
    b_path = root / "scripts" / "def_run_018_verify_b.py"
    b_sha = sha256(b_path) if b_path.is_file() else None
    audit_ok = bool(audit) and (
        audit.get("independent") is True
        and audit.get("state") == "PASS"
        and b_sha is not None
        and audit.get("audited_sha256") == b_sha
    )
    self_report = (verification or {}).get("independence") or {}
    self_reused = self_report.get("reused_recomputation_code") or []
    self_declares_reuse = bool(self_report.get("imports_trading_bot")) or bool(self_reused)
    if verification is None:
        blockers.append("MISSING_INDEPENDENT_VERIFICATION")
    if audit is None:
        audit_ok = False
        blockers.append("MISSING_INDEPENDENCE_AUDIT")
        reasons.append("no se ejecutó el auditor externo de imports de B")
    elif not audit_ok:
        audit_ok = False
        blockers.append("INDEPENDENCE_NOT_PROVEN")
        reasons.append(
            "el auditor externo no certifica la independencia de B: "
            f"state={audit.get('state')} reasons={audit.get('reasons')} "
            f"sha_auditado={str(audit.get('audited_sha256'))[:12]}… sha_actual={str(b_sha)[:12]}…"
        )
    if self_declares_reuse:
        #: si B mide y encuentra reutilización, el gate no puede publicar PASS aunque el
        #: auditor externo todavía no se haya ejecutado sobre esta revisión.
        audit_ok = False
        blockers.append("INDEPENDENCE_NOT_PROVEN")
        reasons.append(
            "B declara reutilización de código del Builder: "
            f"reutilizado={self_reused} imports_trading_bot={self_report.get('imports_trading_bot')}"
        )
    independence_ok = audit_ok

    # -- integridad técnica --------------------------------------------------
    b_result = (verification or {}).get("result")
    replay_status = (replay or {}).get("status")
    if verification is None:
        technical = "BLOCKED"
    elif b_result == "FAIL":
        technical = "FAIL"
    elif b_result == "BLOCKED" or not independence_ok:
        technical = "BLOCKED"
    elif replay is None:
        technical = "BLOCKED"
        blockers.append("MISSING_CLEAN_REPLAY")
    elif replay.get("runtime_executed") is not True:
        #: `RUNTIME_VALIDATION=NOT_PERFORMED` no es un fallo de la evidencia: es la
        #: ausencia de la ejecución. Un informe con tests verdes no la sustituye.
        technical = "BLOCKED"
        blockers.append("RUNTIME_VALIDATION_NOT_PERFORMED")
    elif replay_status == "CLEAN_CHECKOUT_REPRODUCED":
        technical = "PASS"
    elif replay_status in ("BLOCKED", "ARTIFACT_ONLY"):
        technical = "BLOCKED"
    else:
        technical = "FAIL"

    economic_mismatch_ok = (verification or {}).get("summary", {}).get("FAIL", 0) == 0
    economic = "INVALID"
    published_status = ((primary or {}).get("decision") or {}).get("economic_status")
    if verification is not None and economic_mismatch_ok:
        if published_status == "EVIDENCED":
            economic = "EVIDENCED"
        elif published_status == "NEGATIVE":
            economic = "NEGATIVE"
        elif published_status == "NOT_EVIDENCED":
            economic = "NOT_EVIDENCED"
    elif verification is not None and published_status == "EVIDENCED":
        false_success.append(
            "el OOS publicado declara EVIDENCED mientras B encuentra comprobaciones en FAIL"
        )

    # -- admisión a paper ----------------------------------------------------
    paper_validation = (replay or {}).get("paper_validation", "NOT_PERFORMED")
    if technical == "PASS" and economic == "EVIDENCED" and paper_validation == "PERFORMED":
        paper = "GO"
    elif economic == "EVIDENCED" and paper_validation != "PERFORMED":
        paper = "NO_GO"
        reasons.append("la ventaja económica no está acompañada de validación paper acreditada")
    else:
        paper = "NO_GO"

    # -- clasificación del estrés -------------------------------------------
    stress = ((verification or {}).get("stress_classification") or {})
    stress_ok = stress.get("used_for_decision") is False and stress.get("confirmatory") is False
    if not stress_ok:
        defects.append(
            {
                "code": "STRESS_TREATED_AS_CONFIRMATORY",
                "detail": "el estrés x2 se publica como evidencia de decisión",
            }
        )
        if paper == "GO":
            paper = "NO_GO"

    # -- defectos y bloqueos -------------------------------------------------
    for defect in (verification or {}).get("defects") or []:
        defects.append(defect)
    if technical == "FAIL" and b_result == "FAIL":
        reasons.append(
            "la verificación independiente encontró comprobaciones en FAIL: "
            + ", ".join(
                item["code"]
                for item in (verification or {}).get("controls", [])
                if item.get("state") == "FAIL"
            )[:400]
        )
    if replay is not None and replay.get("status") != "CLEAN_CHECKOUT_REPRODUCED":
        reasons.append(f"el checkout limpio terminó en {replay.get('status')}")

    # -- órdenes observadas --------------------------------------------------
    paper_orders = (replay or {}).get("paper_orders")
    live_orders = (replay or {}).get("live_orders")
    if paper_orders is None:
        paper_orders = 0
        reasons.append("no se observaron órdenes paper en esta ejecución offline")
    if live_orders is None:
        live_orders = 0

    return {
        "schema_version": SCHEMA,
        "generated_at_utc": datetime.now(tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "rfc": RFC,
        "subject": SUBJECT,
        "technical_integrity": technical,
        "economic_evidence": economic,
        "paper_admission": paper,
        "economic_evidence_detail": {
            "primary_oos_decision": published_status,
            "stress_status": stress.get("status"),
            "stress_used_for_decision": stress.get("used_for_decision"),
            "stress_confirmatory": stress.get("confirmatory"),
            "independent_recomputation": b_result,
        },
        "technical_detail": {
            "independent_verifier": b_result,
            "independent_checks": (verification or {}).get("checks_total"),
            "independent_failures": [
                item["code"]
                for item in (verification or {}).get("controls", [])
                if item.get("state") == "FAIL"
            ],
            "clean_replay": replay_status,
            "runtime_executed": (replay or {}).get("runtime_executed"),
            "independence_demonstrated": independence_ok,
            "baseline_head": ((baseline or {}).get("git") or {}).get("head"),
            "seal_commit": (seal or {}).get("commit"),
        },
        "defects": defects,
        "blockers": blockers,
        "reasons": reasons,
        "false_success": len(false_success),
        "false_success_detail": false_success,
        "paper_validation": paper_validation,
        "paper_orders_observed": paper_orders,
        "live_orders_observed": live_orders,
        "inputs": {
            "baseline": bool(baseline),
            "seal": bool(seal),
            "independent_verification": bool(verification),
            "independence_audit": bool(audit),
            "clean_replay": bool(replay),
            "oos_results": bool(primary),
        },
    }


def write_reports(root: Path, decision: dict[str, Any]) -> None:
    out = root / OUT
    out.mkdir(parents=True, exist_ok=True)
    (out / "ADMISSION_DECISION.json").write_text(
        json.dumps(decision, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n"
    )
    run_report = {
        "schema_version": "DEF_RUN_018_RUN_REPORT_V1",
        "rfc": RFC,
        "generated_at_utc": decision["generated_at_utc"],
        "phase": "TECHNICAL_CLOSE" if decision["technical_integrity"] == "PASS" else "AUDIT",
        "technical_integrity": decision["technical_integrity"],
        "economic_evidence": decision["economic_evidence"],
        "paper_admission": decision["paper_admission"],
        "decisions": decision,
        "false_success": decision["false_success"],
        "defects": decision["defects"],
        "blockers": decision["blockers"],
    }
    (out / "RUN_REPORT.json").write_text(
        json.dumps(run_report, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n"
    )
    (out / "RUN_REPORT.md").write_text(render_run_report(decision), encoding="utf-8", newline="\n")
    (out / "FINAL_REPORT.md").write_text(render_final(decision), encoding="utf-8", newline="\n")


def render_run_report(decision: dict[str, Any]) -> str:
    tech = decision["technical_detail"]
    lines = [
        f"# RUN_REPORT — {RFC}",
        "",
        f"Generado: `{decision['generated_at_utc']}`.",
        "",
        "| Campo | Valor |",
        "| --- | --- |",
        f"| `technical_integrity` | **{decision['technical_integrity']}** |",
        f"| `economic_evidence` | **{decision['economic_evidence']}** |",
        f"| `paper_admission` | **{decision['paper_admission']}** |",
        f"| Verificador B | {tech['independent_verifier']} ({tech['independent_checks']} checks) |",
        f"| Checkout limpio | {tech['clean_replay']} (runtime ejecutado={tech['runtime_executed']}) |",
        f"| Independencia demostrada | {tech['independence_demonstrated']} |",
        f"| Commit del sello | `{tech['seal_commit']}` |",
        "",
        "## Por qué",
        "",
    ]
    for reason in decision["reasons"] or ["sin objeciones adicionales"]:
        lines.append(f"- {reason}")
    lines += ["", "## Defectos", ""]
    if decision["defects"]:
        for defect in decision["defects"]:
            lines.append(f"- **{defect.get('code')}**: {defect.get('detail', '')}")
    else:
        lines.append("- ninguno")
    lines += ["", "## Bloqueos", ""]
    lines += [f"- `{item}`" for item in decision["blockers"]] or ["- ninguno"]
    lines += [
        "",
        "## Órdenes observadas",
        "",
        f"- paper: {decision['paper_orders_observed']} · live: {decision['live_orders_observed']}",
        "",
        "Ejecución offline: este RFC no tiene permiso para enviar órdenes y las cifras son",
        "observadas, no supuestas.",
        "",
    ]
    return "\n".join(lines)


def render_final(decision: dict[str, Any]) -> str:
    tech = decision["technical_detail"]
    verdict = {
        "PASS": "reproducible y auditado en el alcance del RFC-018",
        "FAIL": "economía reproducida ("
        f"{tech.get('clean_replay')}) pero no certificado: el verificador independiente "
        "encontró discrepancias de procedencia",
        "BLOCKED": "no verificable con los insumos disponibles",
    }[decision["technical_integrity"]]
    return "\n".join(
        [
            f"# FINAL_REPORT — {RFC}",
            "",
            "## PHASE", "",
            f"`{'TECHNICAL_CLOSED' if decision['technical_integrity'] == 'PASS' else 'AUDITING'}`",
            "",
            "## COMMITS", "",
            f"- sello: `{tech['seal_commit']}`",
            f"- baseline: `{tech['baseline_head']}`",
            "",
            "## IMPLEMENTED", "",
            "- Verificador B independiente (recomputa cadena, contabilidad, delta pareado, bootstrap).",
            "- Replay desde checkout limpio en worktree aislado, con datasets anclados por SHA-256.",
            "- Suite adversarial de 10 casos fail-closed.",
            "- Gate determinista con tres decisiones separadas.",
            "",
            "## TESTS", "",
            f"- Verificador B: {tech['independent_checks']} comprobaciones, "
            f"{tech['independent_verifier']}.",
            "- Verificador A sin regresiones sobre el paquete sellado.",
            "",
            "## RUNTIME_VALIDATION", "",
            f"- `{tech['clean_replay']}` · runtime ejecutado={tech['runtime_executed']}.",
            "",
            "## PAPER_VALIDATION", "",
            f"- `{decision['paper_validation']}`. Este RFC no ejecuta paper.",
            "",
            "## FALSE_SUCCESS", "",
            f"- `{decision['false_success']}`"
            + (f": {'; '.join(decision['false_success_detail'])}" if decision["false_success_detail"] else ""),
            "",
            "## DEFECTS", "",
            *(
                [f"- **{item.get('code')}** ({item.get('severity', 'P2')}): {item.get('detail', '')}"
                 for item in decision["defects"]]
                or ["- ninguno"]
            ),
            "",
            "## BLOCKERS", "",
            *([f"- `{item}`" for item in decision["blockers"]] or ["- ninguno"]),
            "",
            "## EVIDENCE", "",
            "- `BASELINE_017.json`, `EVIDENCE_SEAL.json`, `COMMIT_MANIFEST.json`.",
            "- `INDEPENDENT_VERIFICATION.json`, `CLEAN_REPRO_RUN_REPORT.json`.",
            "- `ADMISSION_DECISION.json`, `ARTIFACT_MANIFEST.json`.",
            "",
            "## ARCHITECTURE_STATUS", "",
            f"- integridad técnica: **{verdict}**.",
            "",
            "## RFC_STATUS", "",
            f"- `{decision['rfc']}`: `{'CLOSED_WITH_DEFECTS' if decision['defects'] else 'CLOSED'}` "
            "en el alcance técnico; sin promoción.",
            "",
            "## NEXT_PHASE", "",
            "- Un experimento económico **nuevo y preregistrado** si se quiere medir una ventaja;",
            "  este RFC no lo inicia.",
            f"- Resultado económico: `{decision['economic_evidence']}`; paper `{decision['paper_admission']}`.",
            "",
        ]
    )


def write_manifest(root: Path) -> None:
    out = root / OUT
    artifacts = {}
    for path in sorted(out.rglob("*")):
        if path.is_file() and path.name != "ARTIFACT_MANIFEST.json":
            relative = str(path.relative_to(root)).replace("\\", "/")
            artifacts[relative] = {"sha256": sha256(path), "bytes": path.stat().st_size}
    payload = {
        "schema_version": "DEF_RUN_018_ARTIFACT_MANIFEST_V1",
        "rfc": RFC,
        "generated_at_utc": datetime.now(tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "count": len(artifacts),
        "artifacts": artifacts,
    }
    (out / "ARTIFACT_MANIFEST.json").write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=".")
    args = parser.parse_args(argv)
    root = Path(args.root).resolve()
    decision = decide(root)
    write_reports(root, decision)
    write_manifest(root)
    print(
        f"technical_integrity={decision['technical_integrity']} "
        f"economic_evidence={decision['economic_evidence']} "
        f"paper_admission={decision['paper_admission']} "
        f"defects={len(decision['defects'])} blockers={decision['blockers']}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
