# FINAL_REPORT — RFC-TAP-EVIDENCE-004

**Fecha:** 2026-10-18 · **WP:** EVIDENCE-004A/B/C/D/E · **Alcance:** reporting, verificadores y
documentación. Cero cambios en `src/`, `tests/`, `config/risk.yaml`, brokers o estrategias.

**Estado:** `REPORT_CURRENT_CONSISTENCY` pasa de **FAIL** a **PASS verificado**, con la
contradicción histórica preservada y sellada en lugar de borrada.

## 1. El defecto, reproducido antes de arreglarlo

`RUN_REPORT_REA_FIRST.json` contaba `9` operaciones por código de salida. `RUN_REPORT.json`
decía `7` evidenciadas + `2` no ejecutadas. Los dos documentos se presentaban como el mismo
resultado. La contradicción se reproduce hoy como **FAIL** del verificador
`check historical_report_is_declared_superseded` si el sello de supersesión desaparece, y el
informe antiguo sigue en el árbol, byte a byte, con su hash en `SUPERSESSION_MANIFEST.json`.

## 2. Qué se construyó

| pieza | archivo | qué garantiza |
| --- | --- | --- |
| Clasificador | `scripts/evidence004_ledger.py` | `execution_class` separado de `exit_code`; evidencia declarada ≠ verificada; ids locales ≠ ids de REA; logs truncados o duplicados se rechazan |
| Generador | `scripts/evidence004_generate.py` | un objeto canónico → todos los informes; claims atados a contador o `evidence_id`; escritura atómica; un solo escritor |
| Verificador | `scripts/evidence004_verify.py` | relee los logs por su cuenta, recomputa todo, descubre todos los informes bajo `reports/ai-bots/` y rechaza 14 mutaciones |
| Objeto canónico | `evidence-004/canonical/CANONICAL_RUN.json` | 16 eventos, dos ámbitos, claims resueltos |
| Informes derivados | `evidence-004/derived/<ledger_sha>/` | `RUN_REPORT.json/.md`, `INFORME_EJECUTIVO_NUMEROS.md`, manifiesto con hashes |
| Sello histórico | `evidence-004/SUPERSESSION_MANIFEST.json` | 6 documentos antiguos con hash de bytes y motivo; ninguno editado |

## 3. Cifras, con sus dos denominadores

| contador | valor |
| --- | --- |
| `phase_v31.work.operations` | 9 |
| `phase_v31.work.executed_with_evidence_id` | 7 |
| `phase_v31.work.executed_with_verified_artifact` | 2 |
| `phase_v31.work.not_executed` | 2 |
| `phase_v31.readiness.operations` | 1 |
| `all_dossiers.distinct_evidence_ids` | 12 |

Siete operaciones con `evidence_id` y dos rechazadas son **el mismo ámbito** (trabajo REA de esta
iteración). Los doce ids distintos son **otro ámbito** (los cuatro dossiers completos). Ningún
documento los suma, y el verificador falla si alguien lo intenta.

De las siete evidencias, **sólo dos** tienen artefacto en este repositorio cuyo sha256 coincide con
el digest declarado (las capturas de FenixAI y Semantic Signal). Las otras cinco son evidencia
**declarada** y corroborada en su dossier, no comprobada byte a byte. Esa distinción es la razón
por la que ningún patrón externo puede certificarse todavía.

## 4. Aceptación

| requisito | estado | prueba |
| --- | --- | --- |
| Contradicción 9 vs 7/2 reproducida como FAIL | **PASS** | mutación `supersession_entry_removed` ⇒ 2 FAIL |
| `execution_class` separado de `exit_code` | **PASS** | `test_the_refused_operation_with_exit_zero_is_not_counted_as_executed` |
| Evidencia declarada vs verificada | **PASS** | `test_a_verified_artefact_is_distinguished_from_a_declared_id` |
| Generador único para todas las cifras | **PASS** | 5 documentos llevan el mismo bloque; mutar uno ⇒ FAIL |
| Informes históricos conservados y sellados | **PASS** | 6 documentos con hash de bytes; `historical_report_still_shows_the_defect_it_had` |
| Verificador independiente del builder | **PASS** | `test_the_verifier_does_not_import_the_builder` + recomputación propia |
| Mutaciones rechazadas | **PASS** | 14/14 |
| Sin degradar los 73 checks existentes | **PASS** | `scripts/ai_bots_rea_verify.py` ⇒ 73 PASS / 0 FAIL |
| Fallo de escritura atómica no deja informe a medias | **PASS** | `test_a_failed_atomic_write_leaves_no_partial_file` |
| Dos escritores simultáneos imposibles | **PASS** | `test_a_second_writer_is_refused_while_the_lock_is_held` |

## 5. Comandos y códigos de salida

```text
./.venv/Scripts/python.exe scripts/evidence004_generate.py      exit 0
./.venv/Scripts/python.exe scripts/evidence004_verify.py        exit 0   (36 PASS / 0 FAIL)
./.venv/Scripts/python.exe scripts/evidence004_verify.py --mutations
                                                                exit 0   (14/14 rechazadas)
                                                                -> evidence-004/MUTATION_REPORT.json
./.venv/Scripts/python.exe scripts/ai_bots_rea_verify.py        exit 0   (73 PASS / 0 FAIL)
./.venv/Scripts/python.exe -m pytest tests/unit/reports tests/unit/vision tests/unit/intelligence -q
                                                                exit 0   (176 passed)
./.venv/Scripts/python.exe -m ruff check ...                    exit 0
./.venv/Scripts/python.exe -m mypy ...                          exit 0
```

## 6. Lo que este WP no hace

- No reejecuta REA ni llama a ningún modelo: cuenta lo que los logs ya registraron.
- No convierte evidencia declarada en verificada: sigue habiendo 5 ids sin artefacto en disco.
- No certifica ningún patrón externo ni mide rentabilidad (`REAL_MODEL_CALLED = false`).
- Descubre los informes de `reports/ai-bots/`; los de la raíz pertenecen a otros agentes.
- No ejecuta la suite completa del repositorio: sólo los paquetes afectados. Un PASS global con
  ficheros ajenos en vuelo sería exactamente el tipo de afirmación que este WP elimina.

## 7. Siguiente WP

`AI-BOTS-003` (issue #12) sigue siendo el trabajo funcional: causalidad temporal de `bar.ts_ms`,
latencia de respuesta y MTM neto. EVIDENCE-004 no lo bloquea ni lo sustituye; sólo garantiza que,
cuando ese trabajo publique números, no puedan contradecirse entre informes.
