# WP-051-02D — run report

**Run**: `wp051-02d/EXP-004A/2026-10-21`
**Rama**: `agent/ai-bots/RFC-TAP-AI-BOTS-003`
**Declaración sucesora**: `EXP-004A.datasets.phase2/v1` (`a179ed0`)
**Generador**: `scripts/exp004a_capture.py` @ `fc036d967923f09a6092cb0e5de7409afd07ebd7`
**Ventana**: `2026-10-22T00:00:00Z` → `2027-01-20T00:00:00Z` (cerrada al emitir este informe)
**Deadline**: antes de la apertura de la ventana — cumplido.

---

## 1. Resultado

`C_015_PROVENANCE = PASS` para la declaración nueva y para la regla de elegibilidad.
`CERTIFICATION = BLOCKED`. `PROMOTION = NO_PROMOTION`. `PAPER_VALIDATION = NOT_PASS`.
`economic_executions = 0`.

No significa que EXP-004A esté validado: significa que una captura ya no puede ser técnicamente
correcta y procedencialmente huérfana.

## 2. Qué se ha entregado

| Pieza | Estado |
| --- | --- |
| Declaración sucesora versionada, ligada por hash a la original | `config/preregistrations/EXP-004A.datasets.phase2.json` |
| Contrato de validación, autoridad temporal y elegibilidad | `src/trading_bot/research/prospective/provenance.py` |
| Generador gobernado y bloque de procedencia en cada manifiesto | `scripts/exp004a_capture.py` |
| Preflight de 15 controles | `scripts/exp004a_provenance_preflight.py` → **PASS** |
| Verificador independiente de 5 controles + sello | `scripts/exp004a_provenance_verify.py` |
| Pruebas nuevas | 22 de procedencia + 5 de gobernanza en el extractor |

## 3. Números

| Comprobación | Resultado | Exit |
| --- | --- | --- |
| Suite procedencia + extractor | 46 passed | 0 |
| Suite de admisión (C-004, no regresión) | 36 passed | 0 |
| Suites del gate de preregistro | 69 passed, 1 skipped (symlinks) | 0 |
| Verificador adversarial existente | 20 passed | 0 |
| Forward observer EDGE-03 | 33 passed | 0 |
| Preflight de procedencia | 15/15 PASS | 0 |
| `st6:tape`, vacío, declaración ausente, pre-vigencia, sobrescritura | 2 / 3 / 2 / 5 / 2 | como se declara |
| Slice elegible con fixture controlada | escrito y verbatim | 0 |

La suite completa `tests/unit/research` **no** se ejecutó (timeout histórico de 600 s); se reportan
las suites afectadas por separado. `ruff check` pasa en todos los ficheros tocados.

## 4. Los tres rechazos que sostienen la procedencia

1. **Sin declaración válida no se escribe nada.** El generador valida antes de construir: digest de la
   original, `supersedes`, SHA completo del commit, blob del generador, worktree limpio y commit de la
   declaración anterior a la ventana. Cualquier fallo → exit 2, cero bytes escritos.
2. **Una barra anterior a la vigencia no es elegible.** `fetched_at_ms` de la barra < `effective_from`
   → exit 5. El dato se conserva en el store; lo que no ocurre es que se convierta en evidencia.
3. **`st6:tape` sigue sin contrato.** La freeze no define la regla ronda→ventana, así que el
   extractor se niega a inventarla (exit 2) y el preflight lo comprueba.

## 5. Estado de la declaración histórica

`config/preregistrations/EXP-004A.datasets.json` conserva `sha256 8946f871…` y blob `43c9deea…`,
idénticos al blob del commit `47116b2`. Ninguna entrada histórica se ha regenerado ni re-sellado, y la
original no se abre en escritura en ningún camino del código (hay una prueba que lo verifica).

## 6. Lo que no se declara

1. **No hay validación prospectiva**: la ventana abre el 2026-10-22 y no existe ninguna jornada
   observada bajo la nueva declaración.
2. **C-013 sigue `TIME_PROOF_WEAK`**: la cronología se apoya en ascendencia de Git y en el reloj de
   ingesta; no hay sello de tiempo externo, y cada registro lo dice (`external_timestamp: UNAVAILABLE`).
3. **C-016 sigue inalcanzable** con el modelo de coste declarado; el umbral no se mueve.
4. **No se toca la certificación**, ni la decisión independiente, ni ningún artefacto sellado.

## 7. Evidencia

`WP_051_02D_PREFLIGHT.json` · `WP_051_02D_PREFLIGHT.md` · `WP_051_02D_BASELINE.json` ·
`WP_051_02D_TEST_REPORT.md` · `WP_051_02D_CHANGELOG.md` · `WP_051_02D_PROVENANCE_VERIFICATION.json` ·
`WP_051_02D_VERIFIER_SEAL.json` · `EVIDENCE_MANIFEST.json` · `evidence/` (logs, `CLI_CONTROLS.json`).

`RUN_REPORT.json` es la versión legible por máquina de este documento; el veredicto del verificador
vive en su propio fichero, no aquí.
