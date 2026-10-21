# FINAL REPORT — RFC-PAPER-RECOVERY-004 / WP-003-01

**Decisión: `PASS (LAB ONLY)`.** Las ventanas críticas se han interrumpido con procesos
reales, se han recuperado, y la economía recuperada es la del control. No es autorización de
producción ni de paper E2E.

## COMMITS

| | |
|---|---|
| `source_commit` (runtime ejecutado) | `33ea87b5a881856e588dfb97e3a305037c2fca6f` |
| `code_sha` | `33ea87b5a881856e588dfb97e3a305037c2fca6f` |
| `test_commit_sha` | `33ea87b5a881856e588dfb97e3a305037c2fca6f` |
| ancla de evidencia | el commit que contiene este fichero; se verifica con `verify_recovery.py --evidence-sha <sha>` |

## IMPLEMENTED

- `src/trading_bot/vision/failpoints.py`: inyección de caídas por entorno, **OFF** por
  defecto, sandbox obligatorio, `os._exit` en vez de excepción.
- `durable.py`: 9 puntos en `save`/`event`/`lock`, `recover()` con seis veredictos, y
  reparación registrada de colas rotas en `BOOK_EVENTS.jsonl`.
- `ledger.py`: `operation_id` con deduplicación idéntica y `OperationConflict` cuando el
  número cambia; recorte de cola rota con `<ledger>.torn.json`.
- `lane.py`: identidad en `FILL`/`CLOSE`, failpoints alrededor del commit, y **el arreglo de
  DEF-01** (`risk_equity`/`marked_equity` en el commit de reconstrucción).

## TESTS

`.venv/Scripts/python.exe -m pytest -q tests/unit/vision tests/unit/paper tests/unit/risk` → **577 passed in 521.57s (0:08:41)**, `exit 0`, 521.57 s.
Nuevos: 16 unitarios + 1 regresión. Repo completo: `exit 1`, 101 fallos **preexistentes**
(idéntico conjunto en el commit padre, 0 nuevos).

## RUNTIME_VALIDATION

16/16 escenarios PASS, 146.4 s, con
49 procesos hijos reales. `PROCESS_CRASH_VERIFIED`.

## PAPER_VALIDATION

`NOT_PERFORMED`. Fuera de alcance por el RFC; sin sesión paper E2E.

## LIVE / ÓRDENES

0 órdenes, 0 credenciales, 0 peticiones externas. La ruta live se invocó sólo sin
`--confirm-live`, para probar que se niega (exit 2) antes de cualquier I/O.

## FALSE_SUCCESS

0. Un escenario sin `exit 86` no cuenta; un PASS con un check fallido no cuenta; el
verificador re-deriva cada afirmación y sus 10 controles negativos deben ser rechazados.

## DEFECTS

- **DEF-01** (runtime): the commit that books a gap reconstruction published risk_equity != marked_equity — lane._apply_gap_plan re-marks the risk engine from the broker before the commit
- **DEF-02** (instrumentation): no failpoint on any persistence call: the ledger fsync -> book replace window had never been interrupted — vision/failpoints.py + 14 points in durable.py, ledger.py and lane.py
- **DEF-03** (recovery): a torn tail in BOOK_EVENTS.jsonl or a session ledger raised instead of being classified — documented truncation of the uncommitted tail with a REPAIR row / .torn.json record
- **DEF-04** (idempotency): a CLOSE row had no economic identity, so a re-executed bar wrote a second row for one effect — operation_id on FILL/CLOSE + dedup that refuses a different number (OperationConflict)
- **DEF-05** (laboratory): three defects in the laboratory itself, found by its first pass — corrected oracles; no threshold relaxed

## BLOCKERS

Ninguno para el alcance declarado. Fuera del alcance y declarados: reconciliación externa,
durabilidad ante corte de alimentación, paper E2E.

## EVIDENCE

`RECOVERY_LAB.json`, `ECONOMIC_EQUIVALENCE.json`, `NETWORK_ISOLATION_AUDIT.json`,
`SUITE_IDENTITY.json`, `RECOVERY_BRANCH_MATRIX.json`, `FAILPOINT_MATRIX.json`,
`EVIDENCE_MANIFEST.json`, `VERIFICATION.json` y los logs primarios de cada hijo en `lab/logs/`.

## ARCHITECTURE_STATUS

El libro sigue siendo la autoridad (no se invierte a ledger autoritativo). El ledger es
proyección at-least-once deduplicada por `operation_id`. La desviación respecto de §5.1 del
RFC está documentada en `runtime_authority_map.md`.

## RFC_STATUS

WP-003-01 cerrado como `PASS (LAB ONLY)`. Dimensiones:

| Dimensión | Resultado | Base |
|---|---|---|
| IMPLEMENTATION | PASS | failpoints + operation_id + recover() in the runtime path |
| TESTS | PASS | acceptance suite 577 passed, exit 0; repo-wide 101 failed, 0 of them not already failing at the parent commit |
| RUNTIME_VALIDATION | PASS | 8 crash scenarios, 8 real child kills at exit 86 |
| INDEPENDENT_VERIFICATION | PENDING | verify_recovery.py has not run against the evidence commit yet |
| PAPER_VALIDATION | NOT_PERFORMED | out of scope by the RFC; no end-to-end paper session is claimed |
| NETWORK_ISOLATION | PASS | process-wide audit hook; the only audited call is the loopback control |
| PLATFORM_DURABILITY | PROCESS_CRASH_VERIFIED_ONLY | NTFS cannot fsync a directory from Python; POWER_LOSS_DURABILITY_NOT_VERIFIED |
| FALSE_SUCCESS | 0 | no scenario claims PASS with a failed check; the verifier re-derives each claim |

## NEXT_PHASE

`RFC-PAPER-ISOLATION-005 / WP-003-02` (aislamiento operativo y prohibición verificable de
órdenes/red externa). Después, `WP-003-03` para paper E2E con rentabilidad medida aparte.

## VERIFICACIÓN INDEPENDIENTE

**PENDING** · controles negativos rechazados:
**—/—**

| Control | Mutación | Resultado | Rechazado por |
|---|---|---|---|
| — | pendiente de la pasada contra el commit | — | — |
