# FINAL_REPORT — WP-ECONOMIC-RECOVERY-006

**Estado: `RESEARCH`.** El motor económico está reparado y verificado; hay datos reales
trazables y una evaluación ejecutada. No hay ninguna estrategia admitida, así que PAPER
sigue `NOT_AUTHORIZED` y `admitted_for_paper` sigue en `0/24`.

## 1. Línea base confirmada (no asumida)

Antes de tocar nada, en el checkout local:

| comprobación | resultado |
| --- | --- |
| HEAD | `a6290714f8685dc3b91fdbc7ed4a66c305dba848` (rama `repro/economic-recovery-002`) |
| preflight WP-005 | `BLOCKED`, 2 bloqueos (`NO_DATASETS_IN_CANONICAL_INPUT_PATH`, `NO_MULTI_FAMILY_RESULTS`), exit 2 |
| datasets canónicos | 0 |
| resultados económicos válidos | 0 |
| ledger | 24 estrategias, 0 `admitted_for_paper` |
| suite completa | 71 fallos + 14 errores (3 334 passed) |

El estado comunicado se sostenía. Los artefactos de WP-005 se commitearon antes de
empezar (`912a46d2`).

## 2. Datos reales (D8)

No había ninguna serie OHLCV utilizable en el árbol: el único kline versionado
(`data/rfc048/raw/binance_usdm_btcusdt_5m_klines.json`) son 1 000 barras de 3,5 días,
insuficientes para DEV/VAL/OOS.

Se descargó histórico real del endpoint **público** que el propio repositorio ya usaba
(`https://fapi.binance.com/fapi/v1/klines`), sin credenciales nuevas:

| campo | valor |
| --- | --- |
| activos | BTCUSDT, ETHUSDT, SOLUSDT |
| barra | 5m |
| barras | 34 560 por activo (103 680 en total) |
| periodo | 2026-06-27T17:40Z → 2026-10-25T17:35Z |
| huecos | 0 |
| peticiones | 24 por activo, cada una con URL, parámetros, HTTP status, `sha256` de la respuesta y bytes |
| barras no cerradas | descartadas por construcción (`close_time >= ahora`) |

Artefactos: `data/economic/w006/MANIFEST.json` + `datasets/*.json`.
Validador independiente `scripts/w006_validate_data.py` → `DATA_QUALITY.json`: **PASS** en
los tres activos (digest, proveniencia por petición, monotonía, alineación al grid de
5m, cobertura, PIT, OHLC, huecos y particiones no vacías).

PIT verificado: la última barra (17:35Z) cierra antes del instante de descarga; ninguna
barra futura entra en el dataset.

## 3. Defectos reparados

Cada fila tiene su test en `tests/unit/research/test_w006_engine.py` (18 tests).

| # | defecto reproducido en WP-005 | reparación | evidencia |
| --- | --- | --- | --- |
| D1 | con 0 datasets el motor escribía 62 KB de resultados y salía con 0 | sin manifiesto, dataset alterado o muestra insuficiente: `MULTI_FAMILY_RUN.json` con `status: NO_DATA`, **ningún** `MULTI_FAMILY_RESULTS.json`, exit 2 | `test_a_missing_manifest_is_no_data_and_writes_no_results`, `test_a_tampered_dataset_is_refused_before_any_evaluation` |
| D2 | `except Exception: alphas = []` convertía un fallo en «sin señal» | la excepción se registra con tipo, mensaje, barra y traceback; la familia se aborta tras 3 fallos y queda `ERROR`; el run pasa a `INCOMPLETE`, **no** escribe resultados, exit 3 | `test_a_failing_family_blocks_the_results_artifact`, `test_the_cli_exits_three_on_an_incomplete_run` |
| D3 | `gross` incluía slippage; comisiones y slippage no separables | por operación: `gross_pnl` (precios de referencia), `spread_cost`, `slippage_cost`, `fees`, `net_pnl`, con la identidad `net = gross − spread − slippage − fees` asertada por operación y por agregado (`reconciliation_residual`) | `test_each_trade_reconciles_gross_minus_costs`, `test_gross_pnl_does_not_move_when_slippage_moves`, `test_fees_are_charged_once_per_leg` |
| D4 | DEV/VAL/OOS se deducía del prefijo del nombre del fichero | particiones cronológicas sobre la cobertura agregada (50/25/25), publicadas con límites ISO y ms; un dataset que no cubre el rango se declara en `coverage_mismatch` | `test_partitions_are_monotone_and_cover_the_range`, `test_partitions_do_not_depend_on_dataset_names`, `test_a_partition_gap_is_published_not_hidden` |
| D5 | el fill se ejecutaba al cierre de la barra que generaba la señal | la señal decide en el cierre de `i`; la entrada se ejecuta en el **open de `i+1`**; una señal sin barra siguiente no se ejecuta y se cuenta en `unfilled_signals` | `test_a_signal_fills_at_the_next_bar_open`, `test_the_signal_window_never_includes_a_future_bar` |
| D6 | equity solo realizada; drawdown y Sharpe ciegos al riesgo abierto | equity marcada a mercado en cada barra, incluyendo el coste de cerrar la posición abierta; `max_dd_pct_mtm` y Sharpe sobre esa curva, con `max_dd_pct_realized` publicado al lado para comparación | `test_drawdown_sees_the_open_position` |

Decisión de diseño declarada: **stop y objetivo se anclan al precio de referencia**, no al
fill. Si se anclaran al fill, un escenario de costes distintos movería los niveles y por
tanto el PnL bruto, y la sensibilidad a costes dejaría de medir costes. El efecto de un
fill peor está en `slippage_cost`, que es donde debe estar.

## 4. Clasificación de los 85 fallos preexistentes

`scripts/w006_classify_failures.py` sobre el XML de la suite completa (71 fallos + 14
errores). Detalle completo en [FAILURE_CLASSIFICATION.md](FAILURE_CLASSIFICATION.md) y
`evidence/FAILURE_CLASSIFICATION.json` (con el nodeid de cada uno).

| categoría | nº | causa demostrada |
| --- | --- | --- |
| `MISSING_VERSIONED_ARTIFACT` | 41 | el test afirma sobre un fichero que ningún commit porta (`reports/profitability_gate035/*`, `reports/rfc035/search_round_3/*`, `data/raw/alpha003/price/*`, `data/st6/ST6_HEALTH_STATUS.json`); comprobado con `git ls-files` → no versionado |
| `EVIDENCE_DIGEST_MISMATCH` | 18 | un artefacto de verificación registra un digest que los bytes que nombra ya no tienen |
| `FIXTURE_INVENTORY_GAP` | 8 | el doble de test lanza `StopIteration` porque la combinación (activo, ventana, marco) no existe |
| `UNTRIAGED_ASSERTION` | 18 | fallo de aserción no atribuido en esta pasada; se publica con su línea, **no** se reclasifica como irrelevante |

Hallazgo dentro de `EVIDENCE_DIGEST_MISMATCH`, verificado con `git show`: los manifiestos
congelados de 9 experimentos ARP fijan `config_hash = 6c4dd0be…` mientras el ledger de
admisión lleva al menos cinco commits siendo `5e2ccc57…`. Es decir: **esas
pre-registraciones ya no pueden demostrar el binding de configuración que afirman.** No se
reparan aquí porque re-congelar un manifiesto pre-registrado destruiría su valor
probatorio; queda declarado como bloqueo de esas líneas, no como fallo de este runtime.

Ninguno de los 85 toca `scripts/multi_family_backtest.py` ni los ficheros modificados por
WP-006. Los que sí son de este lane (`test_cost_drift_monitor`,
`test_economic001_evidence_closure`, `test_rfc046_economic_gate`,
`test_futures_independent_verifier`) fallan por **pins obsoletos en artefactos de otras
líneas**, no por lógica del motor; se documentan y no se reescriben sus evidencias.

## 5. Verificación independiente (BUILDER ≠ VERIFIER)

`scripts/w006_verify.py` no importa el motor: relee CSV, barras y manifiesto y recalcula.
Sobre **23 444 operaciones** y 216 bloques agregados:

| check | resultado |
| --- | --- |
| identidad de PnL por operación | PASS |
| `gross` recalculado desde precios y cantidad | PASS |
| costes recalculados desde bps y nocional | PASS |
| fills recalculados desde el modelo de costes | PASS |
| causalidad (entrada = barra siguiente a la señal) | PASS |
| realismo de salidas | PASS |
| MFE/MAE recalculados sobre la exposición | PASS |
| particiones según los límites publicados | PASS |
| agregados = sumas del CSV | PASS |
| sin operaciones en warmup | PASS |

La primera corrida del verificador falló dos checks y **se investigó la causa** en lugar
de relajar la tolerancia sin motivo: (a) la identidad solo puede cerrar hasta la
precisión publicada (4 campos redondeados a 6 decimales ⇒ cota 2·10⁻⁶, ahora derivada y
documentada, con el residuo máximo publicado); (b) el verificador contaba como exposición
la barra en la que un flip cierra **al open**, cuando el motor deja de estar expuesto ahí.

## 6. Criterios de aceptación

| criterio | estado |
| --- | --- |
| Dataset real validado y trazable | **sí** — 103 680 barras, 72 peticiones con digest, `DATA_QUALITY` PASS |
| Excepciones visibles y propagadas | **sí** — D2, con exit 3 y sin artefacto de resultados |
| Ausencia de look-ahead | **sí** — D5, verificado por el chequeo de causalidad sobre las 23 444 operaciones |
| PnL reconciliable operación por operación | **sí** — identidad exacta y verificación independiente |
| Particiones cronológicas correctas | **sí** — D4, publicadas y verificadas |
| Ejecución reproducible | **sí** — sin reloj, sin aleatoriedad, datos con hash; 4m33s |
| Sin nuevos fallos de tests | **sí** — ver §7 |
| Verificación independiente | **sí** — 10/10 checks |

El preflight de WP-005 sobre el árbol final ya no bloquea por ausencia de datos: lee el
manifiesto, verifica los tres digests y encuentra tres artefactos de resultados con
operaciones reales.

```
REQUIRES_RUNTIME_EXECUTION_AND_INDEPENDENT_VERIFICATION | datasets=3 | results=3 | blockers=0
EXIT=0
```

Sigue sin poder emitir `PASS`: la procedencia y la admisión económica no son cosas que un
escaneo de presencia pueda certificar. Transcripción: `evidence/preflight_after.txt`.

Durante la comprobación final aparecieron cuatro defectos **míos**, corregidos antes de
cerrar: los dos llamadores legacy del simulador (§7) y dos lecturas erróneas del propio
preflight (el sobre `results` de WP-006 y la ruta de los datos). Con el artefacto nuevo el
preflight declaraba seis familias ausentes: un falso bloqueo, tan malo como un falso pase.

## 7. Tests

- Nuevos: 18 en `tests/unit/research/test_w006_engine.py`, todos en verde.
- Suite completa antes: 71 fallos + 14 errores (3 334 passed).
- Suite completa después: 71 fallos + 14 errores (3 351 passed), **mismo conjunto de
  nodeids** (`introduced=0`, `fixed=0`, `identical=True`). El +17 es exactamente lo que
  esa corrida recogió del fichero nuevo; el test 18 (adaptador legacy) se añadió después
  y pasa en ejecución dirigida.
- Ese adaptador no es cosmético: `scripts/multi_tf_backtest.py` y
  `scripts/strategy_dynamic_experiment.py` importaban `simulate_family` con la firma
  antigua. La reescritura los habría roto en silencio y ningún test los cubre, así que se
  conserva `simulate_family_legacy` con el contrato anterior y se prueba.

## 8. Lo que este WP no hace

- No admite ninguna estrategia: eso se decide en WP-007 con los números de este motor.
- No toca el ledger, los gates ni `admitted_for_paper`.
- No introduce arquitectura nueva: se reparó el entrypoint existente y se añadieron un
  fetcher (`w006_fetch_klines`), un validador de datos (`w006_validate_data`), un
  verificador independiente (`w006_verify`) y dos clasificadores (`w006_classify_failures`,
  `w007_classify`).
- No repara evidencias de otras líneas (pins obsoletos, artefactos no versionados): las
  clasifica y las deja declaradas.
