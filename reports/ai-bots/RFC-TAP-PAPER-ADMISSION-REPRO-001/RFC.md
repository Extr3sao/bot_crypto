# RFC-TAP-PAPER-ADMISSION-REPRO-001 — evidencia versionada y verificable del diagnóstico PAPER

- **Estado:** `IMPLEMENTED` (ver `FINAL_REPORT.md` para el estado de cada gate).
- **Predecesor:** `CODEX-PAPER-ADMISSION-DIAG-001` (auditoría, no implementación).
- **Veredicto económico heredado:** `NO_GO` para admisión PAPER. Este RFC **no lo reevalúa**.

## 0. Procedencia de este documento

El cuerpo del RFC no existía en el workspace: se recibió como mandato de implementación en
la conversación (objetivo, condiciones 1-10, entregables, criterio de cierre). Este documento
lo transcribe y lo descompone en paquetes, sin añadir criterios nuevos. Cuando el mandato y
la práctica difieren, la diferencia se declara en `FINAL_REPORT.md` §Desviaciones.

## 1. Problema

El diagnóstico `CODEX-PAPER-ADMISSION-DIAG-001` respondió *por qué* ninguna estrategia está
admitida, pero lo hizo con tres defectos materiales que impiden usarlo como evidencia:

1. **El diagnóstico no está en Git.** Vive en `reports/ai-bots/CODEX-PAPER-ADMISSION-DIAG-001/`,
   ruta que `.gitignore:463` (`reports/ai-bots/*`) excluye. Seis documentos sin hash en ningún
   commit: cualquiera puede reescribirlos y nadie puede notarlo.
2. **`test_windowless` falla.** El contrato de ejecución sin ventana tiene 3 offenders `HIGH`,
   dos de ellos introducidos por la propia lane del supervisor.
3. **El verificador de la campaña de lock juzga campañas ajenas.** `paper_lock_campaign_verify.py`
   no comprueba el `schema_version` de `CAMPAIGN.json`, así que puntúa la campaña del supervisor
   (otro layout) y emite `FAIL 28/32` con `false_success=2` en vez de negarse.
4. **El entorno no es reproducible.** `pyproject.toml` declara `matplotlib` (lane de visión) y
   `uv.lock` no lo tiene: `uv lock --check` sale 1 y `uv sync --frozen` sale **0** dejando un
   entorno sin `matplotlib`, es decir, sin runtime importable.

## 2. Objetivo

Convertir el diagnóstico en evidencia **versionada, reproducible y comprobada por un verificador
independiente del que hizo las correcciones**, sin ampliar el alcance ni tocar lo que no se puede
tocar.

## 3. Paquetes de trabajo

| WP | Objetivo | Criterio de aceptación | Estado |
| --- | --- | --- | --- |
| **WP-00** | Auditar y capturar el baseline antes de tocar nada. | Commits de `main` y de la lane, árbol del worktree, entorno, y la salida **original** de cada comprobación que se va a tocar, guardada como log. | `DONE` |
| **WP-01** | Cerrar los 3 offenders de `test_windowless` sin debilitar la auditoría. | `ops_background_audit.py` → `HIGH: 0`; `tests/unit/ops/test_windowless.py` → 0 fallos; el mecanismo de cada offender sustituido, no silenciado. | `DONE` |
| **WP-02** | Hacer que el verificador de lock compruebe `schema_version`. | Una campaña de otro schema se **rechaza por nombre** (`UNSUPPORTED_CAMPAIGN_SCHEMA`) y no se puntúa; la campaña honesta sigue dando `PASS` con `false_success=0`. | `DONE` |
| **WP-03** | Reproducibilidad del entorno `uv`. | `uv lock --check` sale 0; en un checkout limpio `uv sync --frozen` instala `matplotlib` y el runtime importa. | `DONE` |
| **WP-04** | Evidencia, verificación independiente e informes. | `evidence_manifest.json`, `BASELINE.md`, `RUN_REPORT.md/.json`, `FINAL_REPORT.md` y `verify_repro.py` con `false_success = 0`. | `DONE` |

## 4. Fuera de alcance (explícito)

- No se evalúa ni se cambia la economía: **`NO_GO` para PAPER se conserva**.
- No se tocan el ledger (`config/strategy_admission.json`), los límites de riesgo, los criterios
  de admisión, ni B-1/B-2.
- No se ejecuta PAPER ni LIVE: el RFC produce y verifica evidencia, no órdenes.
- No se abren RFC nuevos, ni se añaden agentes, frameworks o arquitecturas.
- No se corrigen defectos distintos de los tres nombrados. Los que aparecen se documentan como
  abiertos, con su evidencia, en `FINAL_REPORT.md` §Defectos abiertos.

## 5. Criterio de cierre

`IMPLEMENTATION + TESTS + REAL_EXECUTION + EVIDENCE + INDEPENDENT_VERIFICATION`.

Un gate obligatorio fallido o una evidencia insuficiente **no** se declara `PASS`: se declara
`BLOCKED` con la causa exacta y se conserva lo que sí se ejecutó.
