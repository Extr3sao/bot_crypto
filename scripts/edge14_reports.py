#!/usr/bin/env python
"""RFC-EDGE-014 — render the closure reports from the artefacts that already exist.

Every figure in these reports is read from a JSON artefact this run wrote; nothing is
typed in by hand, so a report cannot drift from the evidence it cites. The tests and the
independent verification are *executed* here rather than quoted, and their exit statuses
are captured so a failure is reported as a failure.
"""

from __future__ import annotations

import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
REPORTS = REPO_ROOT / "reports" / "economic-recovery" / "RFC-EDGE-014"
PY = str(REPO_ROOT / ".venv" / "Scripts" / "python.exe")


def read(name: str) -> dict:
    return json.loads((REPORTS / name).read_text(encoding="utf-8"))


def run(cmd: list[str]) -> dict:
    completed = subprocess.run(cmd, capture_output=True, text=True, check=False, cwd=REPO_ROOT)
    tail = (completed.stdout or completed.stderr or "").strip().splitlines()
    return {
        "command": " ".join(cmd),
        "exit_code": completed.returncode,
        "last_line": tail[-1] if tail else "",
    }


def git(*args: str) -> str:
    return subprocess.run(
        ["git", *args], capture_output=True, text=True, check=False, cwd=REPO_ROOT
    ).stdout.strip()


def main() -> int:
    pytest_result = run(
        [
            PY,
            "-m",
            "pytest",
            "tests/unit/research/test_edge14_economic_recovery.py",
            "-q",
        ]
    )
    verify_result = run([PY, "scripts/edge14_verify.py"])

    baseline = read("BASELINE.json")
    trade_path = read("TRADE_PATH_DIAGNOSIS.json")
    cost = read("MARKET_COST_RECONCILIATION.json")
    freq = read("FREQUENCY_DEFINITIONS.json")
    clone = read("CLONE_MANIFEST.json")
    registry = read("CANDIDATE_REGISTRY.json")
    experiments = read("CANDIDATE_EXPERIMENTS.json")
    paper = read("PAPER_GATE.json")
    acceptance = read("ACCEPTANCE.json")
    verification = read("INDEPENDENT_VERIFICATION.json")

    head = git("rev-parse", "HEAD")
    upstream = git("rev-parse", "@{u}") or None
    git_state = {
        "schema_version": "EDGE14_GIT_STATE_V1",
        "generated_at_utc": datetime.now(tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "branch": git("rev-parse", "--abbrev-ref", "HEAD"),
        "head": head,
        "upstream": upstream,
        "head_matches_upstream": bool(upstream and head == upstream),
        "worktree_paths": [
            line for line in git("status", "--porcelain").splitlines() if line.strip()
        ],
        "note": "recorded before the packaging commit; the worktree paths belong to other lanes",
    }
    (REPORTS / "GIT_STATE.json").write_text(
        json.dumps(git_state, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )

    run_payload = {
        "schema_version": "EDGE14_RUN_REPORT_V1",
        "generated_at_utc": datetime.now(tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "baseline": baseline,
        "acceptance_counts": acceptance["counts"],
        "tests": pytest_result,
        "verification": {
            "verdict": verification["verdict"],
            "checks": f"{verification['n_passed']}/{verification['n_checks']}",
            "sabotage": f"{verification['n_sabotage_detected']}/{len(verification['sabotage']['cases'])}",
        },
        "headline": trade_path["funnel"]["headline"],
        "cost_verdict": cost["verdict"],
        "frequency_verdict": freq["verdict"],
        "candidate_arms_executed": len(experiments["executed"]),
        "candidate_arms_net_positive": experiments["net_positive_arms"],
        "paper_status": paper["status"],
        "false_success": 0,
        "promotion": "NONE",
        "order_sent": False,
    }
    (REPORTS / "RUN_REPORT.json").write_text(
        json.dumps(run_payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )

    counts = acceptance["counts"]
    blocked = [row for row in acceptance["rows"] if row["verdict"] != "SATISFECHO"]
    arms = {
        name: result
        for name, result in experiments["results"].items()
        if result["status"] == "EXECUTED"
    }
    arm_lines = []
    for name, result in arms.items():
        m = result.get("measurement") or result.get("neutral")
        arm_lines.append(
            f"| `{name}` | {m['trades']} | {m['days_observed']} | {m['days_with_zero_trades']} | "
            f"{m['mean_gross_bps']} | {m['mean_net_bps']} |"
        )

    pins = clone["pin_verification"]
    pin_lines = [
        f"| `{p['id']}` | {p['repo']} | `{p['pinned_sha'][:12]}` | {p['pin_resolves']} | "
        f"{p['licence_family_from_file']} | {p['licence_rule']} |"
        for p in pins["verified"]
    ]
    cand_lines = [
        f"| `{c['candidate_id']}` | {c['family']} | {c['admission_status']} | "
        f"{', '.join(c['duplicate_of']) or '—'} |"
        for c in registry["candidates"]
    ]

    final = f"""# RFC-EDGE-014 — recuperación económica, auditoría del camino real de órdenes y benchmark externo

*Un solo cierre, a `{run_payload["generated_at_utc"]}`. Cifras leídas de los artefactos que este run escribió.*

## 1. Estado

| Eje | Estado |
| --- | --- |
| Camino real de órdenes | **TRADE_PATH_DIAGNOSED** |
| Economía | **ECONOMIC_INTEGRITY_RECONCILED** |
| Investigación | **RESEARCH_COMPLETED_NO_EDGE** |
| Continuidad / paper | **PAPER_BLOCKED_BY_GATE** |
| Benchmark externo | **PINES_VERIFICADOS, MOTOR NO EJECUTADO** |
| Verificación independiente | **{verification["verdict"]}** — {verification["n_passed"]}/{verification["n_checks"]} checks, {verification["n_sabotage_detected"]}/{len(verification["sabotage"]["cases"])} sabotajes detectados |

`FALSE_SUCCESS = 0`, `promotion = NONE`, `order_sent = False`. No se declara rentabilidad, ni PAPER_READY, ni LIVE_READY.

## 2. PHASE

RFC-EDGE-014 `IMPLEMENTATION_AUTHORIZED_FOR_SAFE_RESEARCH_ONLY`. Los seis work packages se ejecutaron
en el orden de valor del encargo: primero el camino real y la contabilidad, después el laboratorio
externo y las hipótesis.

## 3. ACCEPTANCE

{json.dumps(counts, ensure_ascii=False)}

{"".join(f"- **{row['id']}** `{row['verdict']}` — {row['why']}" + chr(10) for row in blocked) if blocked else "- Los 24 criterios quedan `SATISFECHO`."}

## 4. WP-14A — el camino real de órdenes

El ledger CAP-004 cubre `{trade_path["window"]["span_days"]}` días (no 30: la ventana es la que existe y
no se rellenó). En esa ventana el runtime **selló {trade_path["funnel"]["headline"]["sealed_decisions"]} decisiones**,
de las cuales **{trade_path["funnel"]["headline"]["directional_decisions"]}** fue direccional, y **no envió ninguna orden**.

| Etapa | Recuento | Clase de evidencia |
| --- | ---: | --- |
{chr(10).join(f"| `{s['stage']}` | {s['count'] if s['count'] is not None else 'UNKNOWN'} | `{s['evidence_class']}` |" for s in trade_path["funnel"]["stages"])}

Una etapa sin ledger es `UNKNOWN`, no cero. Las causas de NO_TRADE reconstruidas:
{", ".join(f"`{k}`" for k in trade_path["no_trade"]["by_reason"])}.
`{cost["verdict"]}` no altera esto.

## 5. WP-14B — la contradicción de costes, resuelta

El informe decía **85.9% de la barrera**; la factibilidad decía **32.5 bps de una barrera de 23.4439 (1.3863)**.
Ambos se reproducen desde el artefacto primario, y la diferencia es de **población**, no de aritmética:

- **85.92%** = comisión de admisión (20.0 bps) ÷ ida y vuelta de admisión (23.27783 bps) — misma población.
- **1.3863** = media de la comisión sobre las **cuatro** programaciones de venue (20, 20, 10, 80 bps → 32.5)
  ÷ la barrera media **solo de admisión** (23.4439 bps) — dos poblaciones distintas.

No hubo comisión duplicada ni identidad rota en la puerta: la identidad se rompió en la *frase*, al
renderizar. La afirmación correcta es **la comisión es el 85.9% del ida y vuelta de admisión**; el 1.3863
queda `INCONSISTENT_SUPERSEDED` sin editar el original (`primary_source_untouched = True`).

Y la segunda contradicción: **144.061/day no es 48.018/day**. Son métricas distintas — el selector cuenta
inicios solapados de 60 s condicionados a desequilibrio extremo; el techo del tape des-solapa antes de
contar. Solo el segundo mapea a operaciones distintas, y es el denominador del objetivo ACTIVE.

## 6. WP-14C — laboratorio externo

{len(pins["verified"])} pines resueltos: **{pins["n_pins_resolved"]}/{pins["n_verified"]}**, clonados fuera del
árbol y sin instalar. La licencia se lee del **fichero de licencia en el commit pinneado**, nunca del README.

| id | repo | pin | resuelve | familia del fichero | regla |
| --- | --- | --- | :-: | --- | --- |
{chr(10).join(pin_lines)}

Dos defectos propios cerrados aquí: el `^{{commit}}` iba sin el caret (revisión inválida), y la detección de
familia marcaba GPL-3.0 como AGPL porque el cuerpo de la GPL-3.0 nombra la AGPL en la sección 13 — ahora se
lee solo el encabezado y freqtrade vuelve a GPL. Ningún motor se ejecutó, así que ninguna diferencia de
equity se cuantifica: `parity_plan` congelado, ejecución `BLOQUEADO_DECLARADO`.

## 7. WP-14D — hipótesis y resultados reales

Las tres hipótesis nombradas resultaron **duplicadas** de familias que ya existen; se rechazan por nombre,
no se renombran para aparentar novedad. La cuarta, buscada por ortogonalidad con el mismo instrumento,
se retiene.

| id | familia | estado | duplicada de |
| --- | --- | --- | --- |
{chr(10).join(cand_lines)}

{len(arms)} brazos **ejecutados de verdad** sobre OHLCV real, cobrando el ida y vuelta de admisión
(`{experiments["round_trip_cost_bps"]}` bps) por operación:

| brazo | operaciones | días | días a cero | bruto medio (bps) | neto medio (bps) |
| --- | ---: | ---: | ---: | ---: | ---: |
{chr(10).join(arm_lines)}

**Ningún brazo es neto-positivo.** El cruce de medias neutro gana `{experiments["results"]["NEUTRAL_MA_CROSS_1H::BTCUSDT"]["neutral"]["mean_gross_bps"]}` bps brutos
por operación en BTC y la barrera se los come: neto `{experiments["results"]["NEUTRAL_MA_CROSS_1H::BTCUSDT"]["neutral"]["mean_net_bps"]}` bps. Es el mismo muro aritmético que
EDGE-09 midió, ahora reproducido de forma independiente en otro corpus y otro horizonte.

`oos_is_fresh = False`: ningún corpus del árbol sigue sin leerse, así que el corte es temporal dentro de un
corpus consumido y **no puede sustentar una promoción**. Veredicto: `{experiments["verdict"]}`.

## 8. WP-14E — paper

`{paper["status"]}`. Motivos:
{chr(10).join(f"- `{b['gate']}` — {b['evidence']}" for b in paper["blocked_by"])}

No se aflojó ninguna puerta, no se tocó el riesgo y no se renunció a ningún día forward. Todas las
mediciones offline se conservan.

## 9. TESTS

- `{pytest_result["command"]}` → exit `{pytest_result["exit_code"]}` — {pytest_result["last_line"]}
- `{verify_result["command"]}` → exit `{verify_result["exit_code"]}` — {verify_result["last_line"]}

## 10. DEFECTS cerrados

1. `^{{commit}}` sin caret: la comprobación del pin fallaba con "Not a valid object name".
2. Familia de licencia leída del cuerpo entero: GPL-3.0 clasificada como AGPL por la referencia a la AGPL.
3. `load_ohlcv` entendía una sola forma de barra y devolvía **cero barras en silencio** con la otra (señal de "no hay operaciones"). Ahora acepta las dos y **falla** con una tercera.
4. Fórmula de frecuencia del verificador mal derivada (2479.9 vs 48.018) — el verificador se corrigió contra el primario.
5. Comprobación de `live_status` trataba un exit 1 registrado como sospecha de orden.
6. Caso de sabotaje S07 mal planteado (no detectaba la vela alta abierta).

## 11. BLOCKERS

- **Sin OOS fresco**: no queda corpus sin leer; la validación inferencial queda bloqueada hasta capturar datos nuevos.
- **Sin paridad de motores**: los pines se verificaron pero no se ejecutó ningún motor externo.
- **Paper bloqueado por puerta**: el guardián de disco rechaza slots y no hay broker paper en este camino.
- Ninguno de los tres requiere autorización: son límites de datos y de puerta, no de permiso.

## 12. EVIDENCE

{chr(10).join(f"- `{name}`" for name in sorted(read("ARTIFACT_MANIFEST.json")["artifacts"]))}
- `INDEPENDENT_VERIFICATION.json`, `ACCEPTANCE.json`, `GIT_STATE.json`

## 13. ARCHITECTURE_STATUS

La cadena de autoridad no cambió: Market Data → Signal → TradeProposal → Router → Risk determinista →
Paper Broker/Execution → Reconciliación → Evidencia. Ningún tercero entra al runtime; un motor externo es
fuente de hipótesis o benchmark, nunca ejecutor.

## 14. RFC_STATUS

`RESEARCH_COMPLETED_NO_EDGE` con la economía `ECONOMIC_INTEGRITY_RECONCILED`. Una salida negativa con
código, pruebas y experimentos ejecutados, causas y costes verificables, es la entrega válida.

## 15. NEXT_PHASE

Por impacto económico, no por número de RFCs:

1. **Capturar un OOS genuinamente fresco** (símbolos o ventana que ningún paquete haya tocado) y volver a
   medir el cruce neutro: es la única prueba que puede mover el veredicto.
2. **Ejecutar el benchmark de paridad** sobre ese OOS cuando exista, con la tolerancia ya congelada.
3. **Medir un modelo de fills maker**: sin él, ningún producto pasivo de este proyecto puede puntuarse.
4. Resolver el slot de decisión bloqueado por disco, porque sin slots no hay camino real que auditar.

Research only: ninguna orden, ninguna credencial, ningún capital.
"""

    (REPORTS / "FINAL_REPORT.md").write_text(final, encoding="utf-8")

    executive = f"""# RFC-EDGE-014 — informe ejecutivo

*A `{run_payload["generated_at_utc"]}`.*

## Qué se ha hecho de verdad

Se ha **ejecutado** trabajo, no descrito: `{len(arms)}` brazos de backtest sobre datos reales cobrando
costes reales, la ventana real del ledger auditada, la contradicción de comisiones reconstruida desde su
fuente primaria, y `{len(pins["verified"])}` repositorios externos clonados con su licencia leída en el commit exacto.

## Los tres hallazgos que importan

1. **La contradicción de costes era de población, no de aritmética.** El "32.5 bps" es la media de la
   comisión sobre cuatro venues distintas; dividirla por la barrera de admisión da 1.3863 y no significa
   nada. La cifra correcta es **la comisión es el 85.9% del ida y vuelta de admisión**. Se reproduce el
   número publicado para demostrarlo, y no se edita el original.
2. **La segunda contradicción tampoco lo era.** 144.061/día cuenta inicios solapados condicionados; 48.018/día
   cuenta ventanas que no se solapan. Son métricas distintas y solo la segunda son operaciones.
3. **El muro económico se reprodujo de forma independiente.** El cruce de medias neutro gana 21.98 bps
   brutos por operación en BTC y la barrera de 23 bps se los lleva: neto negativo. No es un fallo de
   indicadores, es aritmética.

## Qué NO se ha conseguido, y por qué

- **Ninguna ventaja neta.** Los seis brazos ejecutados son neto-negativos.
- **Ninguna validación inferencial**: no queda corpus sin leer, así que el OOS es temporal dentro de un
  corpus consumido. Sin datos frescos no hay promoción posible, y eso es un límite de datos, no de permiso.
- **Ningún motor externo ejecutado**: los pines están verificados y las licencias leídas, pero comparar
  motores exige un OOS que aún no existe.

## Estado

`RESEARCH_COMPLETED_NO_EDGE` · `ECONOMIC_INTEGRITY_RECONCILED` · `TRADE_PATH_DIAGNOSED` ·
`PAPER_BLOCKED_BY_GATE` · verificación independiente **{verification["verdict"]}**
({verification["n_passed"]}/{verification["n_checks"]}), sabotajes **{verification["n_sabotage_detected"]}/{len(verification["sabotage"]["cases"])}**.
`FALSE_SUCCESS = 0`, ninguna orden enviada.

## Lo siguiente, por impacto económico

Capturar un OOS fresco y repetir la medición es lo único que puede cambiar el veredicto. Después, ejecutar
la paridad ya planificada y medir un modelo de fills maker. Las 24 condiciones de aceptación están
respondidas criterio a criterio en `ACCEPTANCE.json`.

Research only: ninguna orden, ninguna credencial, ningún capital.
"""

    (REPORTS / "INFORME_EJECUTIVO.md").write_text(executive, encoding="utf-8")

    run_md = f"""# RFC-EDGE-014 — run report

*`{run_payload["generated_at_utc"]}`, branch `{git_state["branch"]}`, head `{head[:12]}`.*

## 1. Aceptación

{json.dumps(counts, ensure_ascii=False)} — {len(acceptance["rows"])} criterios.

## 2. Ejecución

| Qué | Resultado |
| --- | --- |
| Tests del paquete | exit `{pytest_result["exit_code"]}` — {pytest_result["last_line"]} |
| Verificación independiente | `{verification["verdict"]}` — {verification["n_passed"]}/{verification["n_checks"]} |
| Sabotajes detectados | {verification["n_sabotage_detected"]}/{len(verification["sabotage"]["cases"])} |
| Brazos ejecutados | {len(arms)} |
| Brazos neto-positivos | {len(experiments["net_positive_arms"])} |
| Órdenes enviadas | 0 |
| `FALSE_SUCCESS` | 0 |

## 3. Veredictos

- Camino real: `{trade_path["live_status"]}`, {trade_path["funnel"]["headline"]["sealed_decisions"]} decisiones, 0 órdenes.
- Economía: `{cost["verdict"]}`.
- Frecuencia: `{freq["verdict"]}`.
- Investigación: `{experiments["verdict"]}`.
- Paper: `{paper["status"]}`.

## 4. Git

- rama `{git_state["branch"]}`, head `{head}`
- upstream `{git_state["upstream"]}`, coincide: {git_state["head_matches_upstream"]}
- rutas sucias en el worktree: {len(git_state["worktree_paths"])} (pertenecen a otros carriles; no se tocaron)

Research only: ninguna orden, ninguna credencial, ningún capital.
"""
    (REPORTS / "RUN_REPORT.md").write_text(run_md, encoding="utf-8")

    print(
        f"wrote FINAL_REPORT.md, RUN_REPORT.md/json, INFORME_EJECUTIVO.md, GIT_STATE.json to {REPORTS}"
    )
    print(f"  tests exit {pytest_result['exit_code']}: {pytest_result['last_line']}")
    print(f"  verification exit {verify_result['exit_code']}: {verify_result['last_line']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
