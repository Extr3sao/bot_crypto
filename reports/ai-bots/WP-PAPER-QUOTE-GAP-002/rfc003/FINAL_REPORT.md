# FINAL REPORT — RFC-PAPER-QUOTE-GAP-003 · Fase A

**Decisión: `PASS (LAB ONLY)`** — la identidad código↔evidencia está demostrada desde un
checkout limpio, y no se afirma nada por encima de la recuperación de un hueco en laboratorio.

---

## COMMITS

| SHA | qué es |
|---|---|
| `aab65cf` | **`CODE_SHA`** — código, tests, scripts, `pyproject.toml`, `uv.lock`, fixture de 1 minuto y el `archive/` del WP |
| `fed5476` | test de la rama post-`COMMIT` (solo `tests/`, 0 ficheros de `src/`) |
| `EVIDENCE_SHA` | informes, artefactos y manifiesto (ver `SEAL` al final) |

El diff `aab65cf..fed5476` toca **un** fichero, y es un test. Ningún byte de runtime cambió
entre los dos, así que el sello de runtime sigue describiendo el árbol que corrió los 694.

## IMPLEMENTED

Sin cambios de comportamiento. Lo que se construyó es la *autoridad* que faltaba:

- **`.gitignore`**: re-inclusión de `WP-PAPER-RESUME-001/` y `WP-PAPER-QUOTE-GAP-002/`, con el
  mismo mecanismo que ya usaban `RFC-AI-BOTS-002/003G/003H` y `EXP-003M`. Sin esto ningún
  `EVIDENCE_SHA` era posible: `reports/ai-bots/*` ignoraba el árbol entero.
- **`.gitattributes`**: los dos árboles de evidencia con `-text`, porque sus digests nombran
  bytes. El repo ya había aprendido esto con EXP-003M (sello 0/18 tras un checkout con
  `autocrlf`).
- **`uv.lock`**: regenerado. Declaraba todo menos `matplotlib`, así que `uv sync --frozen`
  producía un entorno donde 24 módulos de test no se podían ni recolectar.
- **Test post-`COMMIT`** en `test_session_recovery.py`: dos reanudaciones sobre el libro ya
  cerrado, cero cierres, digest estable.

Instrumentación (no runtime): `rfc003/tools/{import_identity_gate,run_suite,verify_phase_a,probe_no_orders,build_artifacts,make_reports,seal}.py`.

## TESTS

- **694** recogidos y ejecutados en **cinco tramos disjuntos** (`310+240+92+33+19`), **694 passed**,
  cinco exit 0. Coincidencia exacta con lo auditado: delta 0, sin maquillar el total.
- **20 passed** en `test_session_recovery.py` en `fed5476`, incluido el test post-`COMMIT`.
- `ruff` 0 en 17 ficheros, `mypy` 0 en 7, `quote_feed_source verify` 0.
- Verificador del WP replicado: **83/83** con los mismos nombres y el mismo `first_failure`.

## RUNTIME_VALIDATION

- `trading_bot.__file__` → `<clean>/src/trading_bot/__init__.py`, sin `PYTHONPATH`.
- Control negativo: con un paquete señuelo en `PYTHONPATH`, el gate sale **3 / `REFUSED`**.
- 20 ficheros de runtime y test hashean a su blob de `HEAD` (`git hash-object --path`, que
  respeta `autocrlf`; hashear bytes crudos habría dado un falso fallo en todos los `.py`).

## PAPER_VALIDATION

`NOT_PERFORMED`. No se abrió sesión PAPER end-to-end; esta fase mide recuperación y autoridad.

## LIVE / ÓRDENES

- `live_enabled=false` en cada corrida del drill y del laboratorio — **medido**.
- `order_submit_attempts = 0` — **medido** con tres espías armados sobre
  `ccxt.Exchange.create_order`, `ccxt.binance.create_order` y `ccxt.binanceusdm.create_order`
  durante una sesión completa (abrir, commit, reanudar). `spies_armed=3`, `calls_crossed=[]`.
  Cero con cero espías no probaría nada; por eso el payload publica cuántos se armaron.
- `external_orders = NOT_VERIFIABLE` y `exchange_reconciliation = NOT_VERIFIABLE`.

> **Corrección a A5.** La frase «no hay ruta de orden» era cierta de `vision/` y `paper/` y
> falsa del proceso: el lane carga `ccxt` y `trading_bot.execution` de forma transitiva, y
> `src/trading_bot/app.py` contiene un comando real (`_cmd_place_order` →
> `futures_client.place_order`) protegido por `--confirm-live` y credenciales. Hay 41
> apariciones de tokens de envío en `src/`, 7 de ellas en la ruta live/execution. Lo que
> sostiene el cero es la frontera armada, no la ausencia de código.

## FALSE_SUCCESS

No se declara `FALSE_SUCCESS=0` global. La métrica medida y acotada es:

- **`unsupported_pass_count = 0`** sobre **10** casos adversariales preregistrados (import
  ajeno, blob mutado, log alterado, node ID duplicado, tramo omitido, crash pre/post `COMMIT`,
  envío armado, claim de «sin órdenes» falsificado, inventario incompleto).

## DEFECTS

**Cerrados:** O1 (import atado al árbol), O2 (logs primarios versionados), O3 (rama
post-`COMMIT` con regresión), O4 (semántica de `false_success` acotada), O5 (`ledger.py` en el
inventario), O6 (`pyproject.toml` en LF; `git diff --check` limpio para código), O7 (cabezas de
cadena separadas de hashes de fichero), O9 (claims de órdenes medidos).

**Encontrados en esta fase:**

1. **`digests_equal = false` en el lab es correcto y estaba mal contado.** Los 14 kills dejan
   `closed 0→0` (todos **antes** del `COMMIT`), y el digest crudo difiere del control porque
   incluye `session_id` y `closed_at`; la economía sí coincide al último decimal
   (`9996.380966197243` en ambos). Decir «digest idéntico» de esa comparación habría sido falso.
2. **`git diff --check` global sigue en `rc=2`**: 128 avisos, todos CR de ficheros `-text` cuyo
   digest cubre ese byte. El check acotado a código/config da `rc=0`. No se “arregla” un
   fixture digest-pinned para satisfacer un linter.
3. **Un constructor de `ccxt` hace red.** La primera versión de `NEG-08` creaba
   `ccxt.binance({...})` y el constructor contactó la API de Binance, que respondió
   `AuthenticationError`. Sin orden, sin credenciales reales, pero **fue una petición externa
   no intencionada**; el caso se reescribió sobre `ccxt.Exchange({})`, que no abre transporte.

## BLOCKERS

Ninguno para Fase A. Fuera de alcance por diseño: reconciliación con el exchange y el crash
entre `fsync` del ledger y el rename del libro (sin punto de inyección determinista).

## EVIDENCE

`rfc003/` — `BASELINE_AUTHORITY.json`, `PREREGISTRATION.md`, `CLEAN_CHECKOUT_REPORT.json`,
`SUITE_IDENTITY.json`, `DATA_PROVENANCE.json`, `VERIFICATION_REPLAY.json`,
`RECOVERY_BRANCH_MATRIX.json`, `ORDER_BOUNDARY_AUDIT.json`, `PHASE_A_VERIFICATION.json`,
`EVIDENCE_MANIFEST.json`, `RUN_REPORT.{md,json}`, `FINAL_REPORT.{md,json}` y `evidence/` con
los logs primarios.

## ARCHITECTURE_STATUS

Sin cambios de arquitectura. La recuperación a través de un hueco sigue siendo un contrato
ejecutable, ahora anclado a un commit y reproducible fuera de este disco.

## RFC_STATUS

`RFC-PAPER-QUOTE-GAP-003` → **implementado y verificado en Fase A**. `PASS (LAB ONLY)` no
implica `PAPER_READY`, ni `LIVE_READY`, ni rentabilidad.

## NEXT_PHASE

PAPER end-to-end observable con accounting interno y reconciliación contra el destino, con
decisión separada y credenciales propias.
