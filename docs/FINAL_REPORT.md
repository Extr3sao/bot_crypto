# FINAL_REPORT — RISK-IN-SHADOW + BAR-CLOSE AVAILABILITY

> Fase dentro de **AUTONOMOUS-PAPER-RUNTIME-V1**. Alcance: PAPER / SHADOW /
> RESEARCH / datos publicos de solo lectura / tests / documentacion / commits
> seguros. **No** se ha tocado LIVE, credenciales, capital, leverage ni ordenes
> reales.

## 1. Punto de partida

El run real `autonomous-paper-real-003` (commit `aa61440`) produjo 5 decisiones
SHADOW y 7 NO_TRADE, y en **las 12 filas** el trace decia `Risk: NOT_APPLICABLE`: el
motor determinista de riesgo nunca se ejecuto, porque solo se consultaba cuando la
intencion podia generar una orden y `PAPER_CANDIDATES = 0`. El riesgo era
inobservable.

Ademas, la disponibilidad temporal se calculaba con el **timestamp de apertura** de
la barra, lo que permitia (a) consumir una barra en formacion y (b) fechar un outcome
en la apertura de la barra que lo contenia.

## 2. Commit / HEAD

```text
HEAD BEFORE: aa61440  feat(autonomous): measure rejected hypotheses and document the runtime map
HEAD AFTER:  (docs)    ver seccion 9
COMMIT DE RUNTIME: ddaf14d  feat(autonomous): wire deterministic risk into SHADOW and make availability bar-close
```

`ddaf14d` es el commit sobre el que se ejecuto el run real 004. El commit final
anade **solo documentacion** (y un test que afirma la identidad de evidencia con
campos estructurados): `git diff ddaf14d..HEAD -- src/ config/ scripts/` debe estar
vacio, y asi se comprueba en la seccion 8.

## 3. Que se implemento

| # | Requisito | Estado | Evidencia |
| --- | --- | --- | --- |
| 1 | riesgo determinista cableado en SHADOW/NO_TRADE reutilizando el `RiskManager` canonico | HECHO | `runtime._risk_review`; 12/12 revisiones evaluadas en el run 004 |
| 2 | riesgo observable sin trade (`risk_evaluated/risk_result/risk_rule/risk_reason/risk_inputs`) | HECHO | `RiskReview.to_dict`; campos en cada trace |
| 3 | estados APPROVED/VETOED/NOT_APPLICABLE y `NOT_EVALUATED` jamas como PASS | HECHO | `RiskState`; `test_a_pass_nobody_produced_is_not_evaluated_never_approved` |
| 4 | `SHADOW != EXECUTION` y autoridad de riesgo identica | HECHO | `test_admitted_and_unadmitted_paths_share_one_risk_engine`, broker espia, `order_created=false` |
| 5 | clasificacion de NO_TRADE (STRATEGIC/RISK/DATA/CONFLICT) sin mezclar errores | HECHO | `NoTradeKind` + `RuntimeFailureKind`; `test_a_provider_outage_is_a_runtime_failure_not_a_no_trade` |
| 6 | contrato de outcome completo con `reference_price_time <= decision_time < future_price_time` | HECHO | `OutcomeRecord.__post_init__`; verificado en los 6 outcomes reales |
| 7 | disponibilidad = CIERRE de barra, con regression test | HECHO | `autonomous/pit.py`; `test_outcome_instant_is_the_close_of_the_bar_not_its_open` |
| 8 | PENDING → RESOLVED idempotente con `OutcomeKey = decision_id + horizon` | HECHO | `OutcomeRecord.outcome_key`; `append_outcome` idempotente; `test_pending_then_resolved_is_idempotent` |
| 9 | replay con estados FULL/PARTIAL/NOT_AVAILABLE | HECHO | `ReplayResult.status`; run 004: 6 FULL / 6 PARTIAL |
| 10 | decision cost-aware (gross − cost = net; gross positivo != trade) | HECHO | contrato + `test_fixture_positive_gross_that_does_not_clear_cost_is_shadow` |
| 11 | identidad de evidencia consciente del timeframe | HECHO | `entries_for_timeframe`; `test_evidence_identity_is_timeframe_aware`, `test_the_evidence_identity_names_strategy_asset_timeframe_and_cost_model` |
| 12 | edges historicos como HISTORICAL_ESTIMATE con fuente/muestra/periodo/timeframe/estado | HECHO | generador del ledger + `EdgeEvidence.evidence_class` |
| 13 | run real de shadow con ≥3 ciclos y ≥1 horizonte cerrado, sin inventar outcomes | HECHO | run 004: 4 ciclos, 12 evaluaciones, 6 outcomes resueltos, 6 pendientes |
| 14 | fixture determinista candidate → cost gate → proposal → Risk APPROVED/VETOED, separado del mercado | HECHO | `tests/unit/autonomous/test_cost_gate_risk_fixture.py` (rotulado en cabecera) |
| 15 | verifier independiente sobre el HEAD final | HECHO | seccion 8 |
| 16 | pruebas, ruff, mypy, suite completa en el estado commiteado | HECHO | seccion 7 |

## 4. Run real 004 (`autonomous-paper-real-004`)

```text
environment: ccxt:binance      assets: BTC, ETH, SOL      timeframe: 5m
cycles: 4 (interval 340s)      asset_cycle_evaluations: 12
```

| Bloque | Valores |
| --- | --- |
| decisiones | 0 TRADE_PAPER · 0 SHADOW_TRADE · 12 NO_TRADE (12 `NO_TRADE_STRATEGIC`) |
| fallos operativos | 0 (`runtime_failures = 0`) |
| candidatos evaluados | 6 familias x 12 evaluaciones activo-ciclo = 72 comprobaciones |
| candidatos seleccionados | `ema_crossover@5m` x 11, `momentum@5m` x 1 |
| edes brutos estimados | −4.56 bps (ema_crossover@5m), −1.88 bps (momentum@5m) — priors HISTORICAL_ESTIMATE |
| coste de ejecucion | 22.79 - 23.64 bps (COST_MODEL_V3 con spread OBSERVED del ciclo) |
| edes netos | −25.52 a −28.20 bps |
| revisiones de riesgo | 12 (12 APPROVED, 0 VETOED, 0 NOT_APPLICABLE, 0 NOT_EVALUATED) |
| shadow intents | 0 (el unico emisor tenia gross negativo) |
| ordenes reales / fills | 0 / 0 |
| outcomes | 12 creados (12 hipotesis con propuesta) · 6 pendientes · 6 resueltos |
| NO_TRADE outcomes | 6 resueltos (los 6 con `mode = NO_TRADE`) |
| integridad temporal | `reference_price_time <= decision_time < future_price_time` en los 6 |
| fugas futuras | 0 detectadas (cadena de hashes intacta, PIT por cierre verificado) |
| trace | 12 registros, `hash chain intact` |
| replay | 12 intentados, 12 reconstruidos, 0 fallos, 6 FULL / 6 PARTIAL, sin acceso a mercado |
| acciones de produccion | 0 |

Los 6 outcomes resueltos: ciclo 1 con gross +13.29/+16.08/+20.35 bps y ciclo 2 con
−13.64/−5.07/−0.00 bps, todos net-negativos tras 22.8-23.6 bps de coste. La decision
de no operar fue economicamente correcta en los 6 casos, con **muestra insuficiente**
para afirmar nada mas alla de la observacion.

## 5. Defectos

| ID | Observacion | Reproduccion | Causa raiz | Fix | Test | Estado |
| --- | --- | --- | --- | --- | --- | --- |
| DEF-AUTO-7 | el outcome de un horizonte de 5m se preciaba con la barra abierta en `T+5m` (precio de `T+10m`) y se fechaba en la apertura | `test_outcome_instant_is_the_close_of_the_bar_not_its_open` antes/despues | el evaluador tomaba la primera barra con `timestamp > decision_time` y estampaba `bar.timestamp` | seleccion por CIERRE + `reference_price_time_ms` | `test_outcome_contract_temporal_ordering`, `test_the_forming_bar_is_not_usable_at_the_decision_time` | CERRADO |
| DEF-AUTO-8 | un fallo de proveedor se registraba como NO_TRADE, indistinguible de una decision | `test_a_provider_outage_is_a_runtime_failure_not_a_no_trade` | la fila terminal solo llevaba `classification` | `no_trade_kind` XOR `failure_kind`; `totals.no_trades` excluye incidencias | mismo test + identidad de conteo | CERRADO |
| DEF-AUTO-9 | un `RiskReview(PASS)` que nadie produjo podia leerse como aprobacion | `test_a_pass_nobody_produced_is_not_evaluated_never_approved` | no existia la nocion “se ejecuto de verdad” | `evaluated`/`rule` obligatorios; `state` degrada a `NOT_EVALUATED` | mismo test | CERRADO |
| DEF-AUTO-10 | una revision advisory podia acompanar a un paquete que si autoriza orden | `test_advisory_risk_can_never_sit_on_an_order_authorising_packet` | la vinculacion del riesgo no estaba validada en el motor de decision | `_reject_advisory_risk_on_an_order` (fail closed) | mismo test | CERRADO |

P0 abiertos: **0**. P1 abiertos: **0**.

Riesgos conocidos (no defectos de esta fase, heredados y sin cambios):
DEF-AUTO-2 (universo no pre-validado contra el registro de agentes), DEF-AUTO-3
(gate de frescura de 15 min que limita el timeframe), DEF-AUTO-4
(`start_paper_trading.py` marca todo `CONFIRMED`), DEF-AUTO-5 (modulos huerfanos).

## 6. Auditoria de FALSE_SUCCESS

| Condicion de PASS invalido | Comprobacion en este estado | Resultado |
| --- | --- | --- |
| el riesgo no se ejecuto realmente | 12/12 filas con `risk_evaluated = true` y `risk_inputs` poblados | NO |
| el outcome seguia pendiente y se conto como resuelto | `FULL (6) == outcomes_resolved (6)`; `PARTIAL (6) == outcomes_pending (6)` | NO |
| el timestamp tenia look-ahead | `reference_price_time <= decision_time < future_price_time` en los 6; PIT por cierre | NO |
| el replay era parcial y se declaro completo | statuses separados y derivados (`FULL` exige outcome) | NO |
| el HEAD final no fue probado | secciones 7 y 8 | NO |
| el run real no uso datos reales | `environment = ccxt:binance`, `market_context.scanner_timestamp_ms` real, spread OBSERVED | NO |
| el fixture controlado se presento como evidencia de mercado | fichero rotulado “CONTROLLED DETERMINISTIC FIXTURE”, no citado en los numeros del run | NO |

**FALSE_SUCCESS = 0.**

## 7. Pruebas y calidad

```text
uv run ruff check .    -> All checks passed!
uv run mypy .          -> Success: no issues found in 297 source files
uv run pytest -q       -> 822 passed (ver seccion 9 para el recuento del HEAD final)
pytest tests/unit/autonomous -q -> 115 passed
```

Los 115 tests del paquete autonomo cubren: contratos, decisiones, agentes,
verifier, trace/replay/outcomes, integracion del runtime, **observabilidad del
riesgo**, **contrato de outcome** y el **fixture determinista cost gate → riesgo**.

## 8. Verificacion independiente (BUILDER != VERIFIER)

Metodo: se crea un **worktree limpio** con el commit auditado, se fija
`PYTHONPATH=<worktree>/src` (comprobando que `trading_bot` resuelve desde el
worktree, no desde el checkout de trabajo) y se ejecuta desde ahi un verificador
propio, **fuera del repositorio**, que re-deriva el comportamiento en lugar de leer
los tests del proyecto. El worktree no se modifica.

Chequeos del verificador: imports y superficie de contratos; autoridad de riesgo
unica y guarda advisory; `gross − cost = net` y “gross positivo no es trade”;
`reference <= decision < outcome`; barra en formacion no consumible; estados de
replay; y sobre los artefactos reales: cadena de hashes, ausencia de ordenes y de
acciones de produccion, ≥9 evaluaciones activo-ciclo, ≥1 outcome resuelto,
observabilidad del riesgo, identidad de conteo, evidencia de replay, contrato
temporal de cada outcome, unicidad de `outcome_key`, `COST_MODEL_V3` en cada
decision y pureza shadow.

## 9. Limitaciones y estado final

- `PAPER_CANDIDATES = 0` por evidencia ⇒ `TRADE_PAPER = 0` es el resultado
  **correcto** de las reglas, no una carencia. El camino de ejecucion PAPER esta
  demostrado por el fixture determinista, no por el mercado.
- `SHADOW_TRADE = 0` en el run 004 por una razon medida y reproducida (ningun
  candidato con egde bruto positivo emitio alpha en esa ventana), no por un fallo de
  cableado. El camino SHADOW esta ejercitado en el fixture y en el run 003 (5
  decisiones SHADOW).
- Muestra real: 6 outcomes, todos con `n = 2` por celda. Cualquier lectura
  economica es `OBSERVED` / `INSUFFICIENT_SAMPLE`; **nada** aqui autoriza a afirmar
  `PROFITABLE`, `EDGE_VALIDATED` ni `PRODUCTION_READY`.
- El coste de ejecucion (≈22.8-23.6 bps round trip en Binance Spot taker) sigue
  siendo la barrera dominante: el mejor gross observado en el ledger 5m (+1.49 bps)
  esta un orden de magnitud por debajo.

**ESTADO FINAL: `SHADOW_DECISION_RUNTIME_VERIFIED`.**

**SIGUIENTE FASE RECOMENDADA (una sola): `MICROSTRUCTURE-EDGE / FORWARD-DATA
RESEARCH`** — el runtime de decision esta demostrado; lo que falta es una senal
cuyo egde bruto supere el coste, y eso es una pregunta de investigacion, no de
runtime. No se propone ninguna integracion de candidato porque no existe ningun
candidato que integrar.
