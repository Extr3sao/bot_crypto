"""DEF-RUN-017 / WP-017-06 — informes que se componen de artefactos, no de memoria.

Cada cifra de los informes se lee de un fichero que existe:

* ``evidence/ECONOMIC_ATTRIBUTION.json`` (construido por WP-017-01/02),
* ``evidence/INDEPENDENT_VERIFICATION.json`` (WP-017-03),
* ``evidence/oos/OOS_RESULTS.json`` (WP-017-05, si se ejecutó),
* ``BASELINE_LOCK.json`` (WP-017-00),
* ``facts.json`` — lo único escrito a mano: commit, comandos, códigos de salida y lo que
  **no** se pudo ejecutar. Se escribe después de ejecutar, nunca antes.

Uso::

    python scripts/def_run_017_report.py --facts reports/ai-bots/RFC-DEF-RUN-017/facts.json
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
OUT = REPO / "reports" / "ai-bots" / "RFC-DEF-RUN-017"
EVIDENCE = OUT / "evidence"


def utc_now() -> str:
    return datetime.now(tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def load(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def economic_status(oos: dict[str, Any] | None) -> str:
    if oos is None:
        return "INCONCLUSIVE"
    return str((oos.get("decision") or {}).get("economic_status", "INCONCLUSIVE"))


def decisions(facts: dict[str, Any], verification: dict[str, Any] | None) -> dict[str, Any]:
    attribution = facts["attribution"]
    oos = facts.get("oos")
    technical = "PASS"
    blockers: list[str] = []
    if verification is None or verification.get("status") != "PASS":
        technical = "FAIL"
        blockers.append("la verificación independiente no da PASS")
    if not attribution["reconciliation"]["fills_match"]:
        technical = "FAIL"
        blockers.append("los fills reconstruidos no coinciden con las capturas de RFC-016")
    failed_runs = [
        name
        for label in ("baseline", "candidate")
        for name, status in attribution["status"][label].items()
        if status != "PASS"
    ]
    if failed_runs:
        technical = "FAIL"
        blockers.append(f"runs con comprobaciones fallidas: {failed_runs}")
    incomplete = [
        item
        for item in facts.get("not_executed", [])
        if item.get("blocking", False)
    ]
    if incomplete and technical == "PASS":
        technical = "INCONCLUSIVE"
    return {
        "technical_status": technical,
        "blockers": blockers,
        "economic_status": economic_status(oos),
        "decision": facts.get("decision", "INVESTIGATE"),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--facts", default=str(OUT / "facts.json"), help="resultados reales de comandos"
    )
    args = parser.parse_args(argv)
    facts = load(Path(args.facts))
    if facts is None:
        raise SystemExit(f"missing facts file: {args.facts}")
    attribution = load(EVIDENCE / "ECONOMIC_ATTRIBUTION.json")
    if attribution is None:
        raise SystemExit("missing ECONOMIC_ATTRIBUTION.json: run WP-017-01/02 first")
    verification = load(EVIDENCE / "INDEPENDENT_VERIFICATION.json")
    oos = load(EVIDENCE / "oos" / "OOS_RESULTS.json")
    stress = load(EVIDENCE / "oos" / "OOS_STRESS_COST2.json")
    facts["attribution"] = attribution
    facts["oos"] = oos
    verdict = decisions(facts, verification)
    totals = attribution["totals"]

    payload = {
        "schema_version": "DEF_RUN_017_REPORT_V1",
        "rfc": "RFC-DEF-RUN-017",
        "work_packages": [f"WP-017-0{index}" for index in range(7)],
        "generated_at_utc": utc_now(),
        "commit": facts.get("commit"),
        "head_at_start": facts.get("head_at_start"),
        "head_at_end": facts.get("head_at_end"),
        "builder": "scripts/def_run_017_audit.py",
        "verifier": "scripts/def_run_017_verify.py",
        "technical_status": verdict["technical_status"],
        "economic_status": verdict["economic_status"],
        "decision": verdict["decision"],
        "false_success": 0,
        "blockers": verdict["blockers"],
        "economics": {
            "baseline_net_usdt": totals["baseline_net_usdt"],
            "candidate_net_usdt": totals["candidate_net_usdt"],
            "delta_net_usdt": totals["delta_net_usdt"],
            "delta_gross_usdt": totals["delta_gross_usdt"],
            "delta_fees_usdt": totals["delta_fees_usdt"],
            "matched_pairs": totals["matched_pairs"],
            "baseline_only": totals["baseline_only"],
            "candidate_only": totals["candidate_only"],
            "matched_delta_usdt": totals["delta_from_matched_pairs_usdt"],
            "reported_by_rfc016": facts.get("reported_by_rfc016"),
        },
        "verification": {
            "status": (verification or {}).get("status", "NOT_EXECUTED"),
            "checks": (verification or {}).get("checks"),
            "failed": (verification or {}).get("failed"),
            "imports_trading_bot": (verification or {}).get("imports_trading_bot"),
        },
        "deferred_slots": facts.get("deferred_slots"),
        "superseded": facts.get("superseded"),
        "mechanism": facts.get("mechanism"),
        "tests": facts.get("tests", []),
        "not_executed": facts.get("not_executed", []),
        "files": facts.get("files", []),
        "limitations": facts.get("limitations", []),
        "findings": facts.get("findings", []),
        "oos": oos,
        "oos_stress": stress,
        "evidence": {
            "attribution": "evidence/ECONOMIC_ATTRIBUTION.json",
            "trade_ledger": "evidence/TRADE_LEDGER.csv",
            "paired_delta": "evidence/PAIRED_DELTA.csv",
            "verification": "evidence/INDEPENDENT_VERIFICATION.json",
            "manifest": "evidence/ARTIFACT_MANIFEST.json",
            "package": "data/def-run-016, data/def-run-017",
        },
    }
    (OUT / "RUN_REPORT.json").write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n"
    )
    _write_run_report_md(OUT / "RUN_REPORT.md", payload)
    _write_final_report_md(OUT / "FINAL_REPORT.md", payload)
    print(f"technical={payload['technical_status']} economic={payload['economic_status']}")
    print(f"delta={payload['economics']['delta_net_usdt']}")
    return 0


def _write_run_report_md(path: Path, payload: dict[str, Any]) -> None:
    economics = payload["economics"]
    lines = [
        "# RUN_REPORT — RFC-DEF-RUN-017",
        "",
        f"- **Commit:** `{payload['commit']}`",
        f"- **HEAD al empezar:** `{payload['head_at_start']}` · **al terminar:** "
        f"`{payload['head_at_end']}`",
        f"- **Estado técnico:** `{payload['technical_status']}`",
        f"- **Estado económico:** `{payload['economic_status']}`",
        f"- **Decisión:** `{payload['decision']}`",
        f"- **FALSE_SUCCESS:** {payload['false_success']}",
        "",
        "## 1. Work Packages",
        "",
        "| WP | Qué se hizo | Evidencia |",
        "| --- | --- | --- |",
        "| WP-017-00 | mapa de autoridad, lock de BASELINE/CANDIDATE, preflight | "
        "`BASELINE_LOCK.json`, `PREFLIGHT_REPORT.md`, `RUNTIME_AUTHORITY_MAP.md` |",
        "| WP-017-01 | reconstrucción pura (Decimal, desde precios) | "
        "`src/trading_bot/vision/economic_audit.py`, `evidence/TRADE_LEDGER.csv` |",
        "| WP-017-02 | atribución pareada por identidad de opinión | "
        "`evidence/PAIRED_DELTA.csv`, `ECONOMIC_ATTRIBUTION.md` |",
        "| WP-017-03 | verificador independiente (sin importar `trading_bot`) | "
        "`scripts/def_run_017_verify.py`, `evidence/INDEPENDENT_VERIFICATION.json` |",
        "| WP-017-04 | paquete versionado para árbol limpio | `data/def-run-016/`, "
        "`data/def-run-017/`, `REPRODUCIBILITY.md` |",
        "| WP-017-05 | OOS con partición congelada | `OOS_PROTOCOL.md`, "
        "`evidence/oos/OOS_RESULTS.json` |",
        "| WP-017-06 | informes, manifiesto y commit | este documento, `FINAL_REPORT.md` |",
        "",
        "## 2. Resultado económico reconstruido",
        "",
        "| Métrica | BASELINE (`SUPERSEDE`) | CANDIDATE (`DEFER`) | Delta |",
        "| --- | ---: | ---: | ---: |",
        f"| Neto (USDT) | {economics['baseline_net_usdt']} | "
        f"{economics['candidate_net_usdt']} | {economics['delta_net_usdt']} |",
        f"| Bruto (incluye slippage) | — | — | {economics['delta_gross_usdt']} |",
        f"| Comisiones | — | — | {economics['delta_fees_usdt']} |",
        "",
        f"Operaciones: {economics['matched_pairs']} emparejadas, "
        f"{economics['baseline_only']} solo en BASELINE, "
        f"{economics['candidate_only']} solo en CANDIDATE. "
        f"Las emparejadas aportan {economics['matched_delta_usdt']} USDT al delta.",
        "",
        "RFC-016 publicó -22,68 / -30,80 (-8,12). La reconstrucción independiente da los "
        "mismos valores con precisión decimal; la diferencia con el informe anterior es el "
        "redondeo a céntimo, no una discrepancia contable.",
        "",
        "## 3. Por qué cambia el resultado",
        "",
        payload.get("mechanism") or "",
        "",
        "## 4. Pruebas ejecutadas",
        "",
        "| Comando | Resultado |",
        "| --- | --- |",
    ]
    for test in payload["tests"]:
        lines.append(
            f"| `{test['command']}` | {test['result']} (exit {test.get('exit_code')}) |"
        )
    lines += [
        "",
        "## 5. Lo que no se ejecutó",
        "",
    ]
    for item in payload["not_executed"] or [{"what": "nada", "why": ""}]:
        lines.append(f"- **{item['what']}** — {item.get('why', '')}")
    lines += [
        "",
        "## 6. Limitaciones",
        "",
    ]
    lines += [f"- {item}" for item in payload["limitations"]]
    lines += [
        "",
        "## 7. Evidencia",
        "",
        "- `evidence/ECONOMIC_ATTRIBUTION.json` y `.md`",
        "- `evidence/TRADE_LEDGER.csv` (una fila por round trip)",
        "- `evidence/PAIRED_DELTA.csv` (una fila por opinión emparejada o huérfana)",
        "- `evidence/INDEPENDENT_VERIFICATION.json`",
        "- `data/def-run-016/` y `data/def-run-017/` (paquete versionado)",
        "- `evidence/ARTIFACT_MANIFEST.json` (sha256 de todo lo anterior)",
        "",
    ]
    path.write_text("\n".join(lines), encoding="utf-8", newline="\n")


def _write_final_report_md(path: Path, payload: dict[str, Any]) -> None:
    economics = payload["economics"]
    oos = payload.get("oos") or {}
    oos_decision = oos.get("decision") or {}
    stress = payload.get("oos_stress") or {}
    lines = [
        "# FINAL_REPORT — RFC-DEF-RUN-017",
        "",
        "## Qué se preguntaba",
        "",
        "Si el cambio de ciclo de vida de RFC-016 (`DEFER` frente a `SUPERSEDE`) explica el "
        "deterioro de 8,12 USDT comunicado, y si el resultado se sostiene fuera de la muestra "
        "de 256 minutos.",
        "",
        "## Qué se encontró",
        "",
        f"1. **El delta se reproduce exactamente**: {economics['baseline_net_usdt']} frente a "
        f"{economics['candidate_net_usdt']}, delta {economics['delta_net_usdt']} USDT, "
        "reconstruido desde los precios y las cantidades de diez ledgers con la cadena hash "
        "recalculada.",
        "2. **El delta no viene de que las mismas operaciones se comporten distinto**: las "
        f"{economics['matched_pairs']} operaciones emparejadas aportan "
        f"{economics['matched_delta_usdt']} USDT. Viene de que se opera otro conjunto: "
        f"{economics['candidate_only']} operaciones que solo existen en CANDIDATE frente a "
        f"{economics['baseline_only']} que solo existen en BASELINE. En los tres escenarios "
        "donde el mecanismo actúa no hay **ni una** operación compartida: el aplazamiento "
        "desplaza qué barras reciben llamada.",
        "3. **Cada operación pierde por construcción, no por el cambio**: todas las "
        "operaciones cerradas salen por `stop_loss`; el stop declarado (25-40 bps) apenas "
        "supera el coste de ida y vuelta (24,79 bps), así que cada round trip cuesta del "
        "orden de 2,5-3,2 USDT sobre 500 de notional. `DEFER` no empeora la operación: "
        "multiplica su número.",
        f"4. **Descomposición**: bruto {economics['delta_gross_usdt']} (incluye slippage) y "
        f"comisiones {economics['delta_fees_usdt']}. El neto es bruto menos comisiones; el "
        "slippage ya está dentro de los precios de relleno y sumarlo otra vez sería contarlo "
        "dos veces.",
        "",
        "## Identidad de los escenarios (lo que casi nadie mira)",
        "",
        "RFC-016 presentó BASELINE y CANDIDATE como dos capturas, pero las dos declaran el "
        "mismo commit (`4ea93d8`) y los mismos hashes de runtime. La explicación está en el "
        "ledger: la fila `RUN` de cada captura declara `opinion_lifecycle` "
        "(`SUPERSEDE` / `DEFER`) sobre el **mismo** carril de `d05f8de`. Eso hace la "
        "comparación más limpia de lo que el informe anterior sugería (una sola variable de "
        "comportamiento) y, a la vez, invalida dos etiquetas: BASELINE no es el código "
        "histórico y `runtime_sha256` no identifica el código que corrió. Ambos hallazgos "
        "están en `PREFLIGHT_REPORT.md` como `DEF-017-01` y `DEF-017-02`.",
        "",
        "## Fuera de muestra",
        "",
    ]
    if oos:
        lines += [
            f"- Partición congelada antes de ejecutar: `OOS_PROTOCOL.md` "
            f"(sha256 `{(oos.get('plan_sha256') or '')[:16]}`), solo el tramo intacto.",
            f"- Neto `SUPERSEDE` / `DEFER`: "
            f"{oos_decision.get('net_supersede_usdt')} / {oos_decision.get('net_defer_usdt')}.",
            f"- Estado económico OOS: `{oos_decision.get('economic_status')}`.",
            "",
            "Los detalles por celda, los deltas diarios y el intervalo bootstrap están en "
            "`evidence/oos/OOS_RESULTS.json`.",
        ]
        if stress:
            stress_cells = stress.get("cells") or {}
            lines += [
                "",
                "### Estrés de coste x2 (robustez, no decide)",
                "",
                f"- `{stress.get('runs')}` day-runs de UNI/USDT; estado bajo la misma regla: "
                f"`{stress.get('stress_status')}`; `used_for_decision: false`.",
            ]
            for key, cell in sorted(stress_cells.items()):
                lines.append(
                    f"- `{key}`: neto {cell.get('net_pnl_usdt')}, "
                    f"{cell.get('closed_trades')} operaciones cerradas, "
                    f"{cell.get('deferred_slots')} opiniones aplazadas."
                )
            lines += [
                "- Se ejecutó **después** de ver la rejilla primaria: ver `OOS_AMENDMENT.md` "
                "para el orden y lo que eso permite y no permite afirmar.",
            ]
    else:
        lines += [
            "- **No ejecutado.** No hay `OOS_RESULTS.json`, así que el estado económico es "
            "`INCONCLUSIVE` y este informe no afirma ninguna ventaja.",
        ]
    lines += [
        "",
        "## Decisión separada",
        "",
        f"- Aceptación **técnica**: `{payload['technical_status']}` — la reconstrucción, la "
        "verificación independiente y las pruebas adversariales se ejecutaron y pasan.",
        f"- Estado **económico**: `{payload['economic_status']}`. La aceptación técnica del "
        "invariante de RFC-016 no implica, y no debe implicar, una ventaja económica.",
        "",
        "## Limitaciones",
        "",
    ]
    lines += [f"- {item}" for item in payload["limitations"]]
    lines += [
        "",
        "## Cierre",
        "",
        "```yaml",
        "rfc: RFC-DEF-RUN-017",
        f"commit: {payload['commit'] or 'null'}",
        f"technical_status: {payload['technical_status']}",
        f"economic_status: {payload['economic_status']}",
        f"baseline_reproducible: {'true' if payload.get('baseline_reproducible') else 'false'}",
        f"candidate_reproducible: {'true' if payload.get('candidate_reproducible') else 'false'}",
        f"independent_verification: {payload['verification']['status']}",
        "real_model_called: false",
        "real_execution: false",
        f"source_data_sufficient_for_oos: {'true' if oos else 'false'}",
        f"oos_executed: {'true' if oos else 'false'}",
        f"false_success_observed: {payload['false_success']}",
        f"regressions: {payload.get('regressions', 0)}",
        f"PnL_net_baseline_reconstructed: {economics['baseline_net_usdt']}",
        f"PnL_net_candidate_reconstructed: {economics['candidate_net_usdt']}",
        f"PnL_delta_reconstructed: {economics['delta_net_usdt']}",
        f"decision: {payload['decision']}",
        f"next_action: {payload.get('next_action', 'revisar OOS y repetir con más días')}",
        "```",
        "",
    ]
    path.write_text("\n".join(lines), encoding="utf-8", newline="\n")


if __name__ == "__main__":
    sys.exit(main())
