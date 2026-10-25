# WP-ECONOMIC-RECOVERY-004 — Run report

> Registro legible de la ejecución. La versión para máquinas es
> [`RUN_REPORT.json`](RUN_REPORT.json); las transcripciones están en [`evidence/`](evidence/).

- **Rama:** `repro/economic-recovery-002`
- **Base:** `2bd6e346`
- **Commit bajo prueba:** `265d09ed`
- **Fecha de medición:** 2026-10-25
- **Entorno:** CPython 3.11.15, Windows-10-10.0.26200, `core.autocrlf=true`
- **Alcance:** integridad del ledger de admisión y recertificación del lane del
  cost-barrier. Sin órdenes, sin claves, sin capital, sin ruta live.

---

## Commits

| commit | mensaje | contenido |
| --- | --- | --- |
| `7311e553` | `feat(evidence): give the admission ledger a versioned semantic identity` | contrato v1, las tres implementaciones, la decisión del gate, `newline="\n"` en los escritores, 24 tests de contrato |
| `265d09ed` | `fix(evidence): re-pin the ledger the commit carries and rebuild the lane at it` | artefactos reconstruidos, pines de productor, evidencia del input, `REPAIR_EVIDENCE.md` |
| `c447cdb7` | `docs(audit): recertify the ledger repair and publish the independent check` | informes, verificación independiente, registro reemitido, evidencia |
| tip (sin hash por diseño) | `docs(audit): re-check the final tree against the record it now carries` | las tres comprobaciones que leen el registro reemitido, repetidas sobre `c447cdb7`: gate 13/13, verificador 22/22, suite del lane 73 passed |

---

## Comandos

| # | comando | commit | exit | estado |
| --- | --- | --- | --- | --- |
| 1 | `cost_barrier_gate.py --check` | `2bd6e346` | **5** | `INTEGRITY_FAILURE`, 10/11 |
| 2 | `cost_barrier_gate.py` (completo) | `265d09ed` | **0** | `FULL_REPRODUCTION_PASS`, 13/13 |
| 3 | `cost_barrier_gate.py --check` | `265d09ed` | 2 | `CHECK_ONLY_PASS`, 12/12 (parcial por diseño) |
| 4 | suite de lane (7 ficheros) | `265d09ed` | 0 | 137 passed |
| 5 | `pytest -q` (completa) | `2bd6e346` | 1 | 90 F + 14 E = **104** rojos, 3270 passed |
| 6 | `pytest -q` (completa) | `265d09ed` | 1 | 71 F + 14 E = **85** rojos, 3314 passed |
| 7 | `wp_eco004_verify.py` | `265d09ed` | 0 | **22/22 PASS** |
| 8 | `cost_barrier_certify.py` (intento 1) | `265d09ed` | **4** | `FAILED` — registro obsoleto (DEF-4) |
| 9 | `cost_barrier_certify.py` (intento 2) | `265d09ed` | **0** | `CERTIFIED` |

Diferencia entre las dos corridas completas, **por identidad de nodo**: 19 cerrados, todos
`tests/unit/research/test_cost_barrier_*`; 0 introducidos; 0 rojos en el lane.

---

## Artefactos

| objeto | valor |
| --- | --- |
| ledger, bytes | `5e2ccc57…` (idéntico a `2bd6e346`) |
| ledger, estado | `4d1b1e6a…` bajo `strategy-admission-ledger-identity-v1` |
| ledger, entradas | 24 estrategias, `admitted_for_paper=false` en todas |
| explorer, `payload_sha256` | `4383d812…` (idéntico a `2bd6e346`) |
| explorer, bytes | `fdc6892f…`; 13 líneas de contenido distintas (procedencia + 2 pines) |
| input inmutable | `data/recovery/wp7/evidence/COST_BARRIER.json` = `2437f446…`, comprobado por bytes exactos |
| gobernanza | `NOT_AUTHORIZED`, 0 trades, `false_success 0` |

---

## Lo que sigue rojo

- **85 nodos** de la suite completa, ya rojos antes de este WP (`2bd6e346`): 71 `FAILED` +
  14 `ERROR`. Ninguno es del lane del cost-barrier. No se han reclasificado, ni marcado
  como skip, ni ocultado.
- Los seis `MULTI_FAMILY_RESULTS_*.json` siguen sin existir en ningún commit, y
  `reports/strategy-baseline` no aparece en el historial.
- El registro de certificación certifica el **lane**, no la plataforma, y no autoriza nada.

## Defectos encontrados

| id | descripción | estado |
| --- | --- | --- |
| DEF-1 | el pin del ledger era el render CRLF de una revisión anterior, no un blob commiteado | **reparado** |
| DEF-2 | los cinco escritores del lane dejaban que el host eligiera los finales de línea (rebuild Windows: 21 605 líneas reescritas sin cambiar un número) | **reparado** |
| DEF-3 | `--materialize` exige productores pinneados y `--capture` exige el input presente: en una máquina sin el input y con el productor cambiado se bloquean mutuamente | declarado, fuera de alcance |
| DEF-4 | el certificador no puede reemitir su propio registro: el paso de tests corre antes de escribir el registro, y un test valida el registro. Exige dos ejecuciones | declarado, fuera de alcance |
| DEF-5 | `COST_BARRIER_ADVERSARIAL_REPORT.json` identifica el gate en `a551fdc` (`6ff2793a…`); el gate reparado es `a533e33f…`. No se regeneró: describe lo que probó | declarado, no certificante |
