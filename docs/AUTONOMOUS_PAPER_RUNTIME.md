# AUTONOMOUS_PAPER_RUNTIME — ejecutable, verificable, con evidencia

> Fase: **AUTONOMOUS-PAPER-RUNTIME-V1**. Implementación: `src/trading_bot/autonomous/`,
> entrypoint `scripts/autonomous_paper.py`. Es la primera vez que el proyecto tiene un
> camino completo `datos reales → decisión → verificación → riesgo → PAPER/SHADOW/NO_TRADE
> → trace → outcome → experiencia` ejecutado de verdad.
>
> Estado actual: `SHADOW_DECISION_RUNTIME_VERIFIED` (ver `docs/FINAL_REPORT.md`).
> Detalle de validación: `docs/RISK_SHADOW_VALIDATION.md`,
> `docs/OUTCOME_VALIDATION.md`, `docs/DECISION_TRACE_REPORT.md`,
> `docs/REPLAY_VALIDATION.md`.

## 1. Entrypoint

```bash
# ONE_SHOT (un ciclo)
uv run python scripts/autonomous_paper.py --cycles 1 --assets BTC,ETH,SOL

# BOUNDED_LOOP (N ciclos, intervalo en segundos; nunca infinito)
uv run python scripts/autonomous_paper.py --cycles 4 --interval 340 \
  --assets BTC,ETH,SOL --timeframe 5m --horizon-minutes 5 \
  --provider ccxt --config-dir config/realdata \
  --run-id autonomous-paper-real-004
```

- `--provider ccxt` usa el composition root real (`resolve_scanner_source`) con el
  `exchange_id` configurado y datos **públicos de solo lectura**. No hay path LIVE:
  el script rechaza arrancar si `runtime.mode != paper`.
- `--provider fake` usa el fetcher sintético (tests/smoke offline, rotulado).
- Salidas: `reports/autonomous-paper/<run_id>/RUN_REPORT.{md,json}`,
  `traces.jsonl` (append-only, hash-chained), `outcomes.jsonl`, `performance.json`.

## 2. Un ciclo, por activo

```text
[solo lectura, una vez por ciclo]
  scanner (datos públicos) → snapshots
  FetcherBarReader → histórico PIT por símbolo (barras CERRADAS)
  closed_bar_slice → barras consumibles (close <= decision_time)

[determinista, sin I/O]
  AssetContext (validado) → régimen
  por cada candidato en orden de ranking (ledger + experiencia acotada):
      StrategyRouter.route({candidato})       → SELECTED / REJECTED
      familia.generate(barras, {}, None)      → ¿emite alpha?
  selección: mayor expected gross edge entre los que emiten
  TradeProposal (gross / cost / net + evidencia)
  AgentRegistry.review(...)                   → observations / critiques / vetos
  DecisionEngine.intend(...)                  → intención pura
  RiskManager.check_signal(...)               → SIEMPRE que haya propuesta
                                                 (binding si podría ordenar,
                                                  advisory en SHADOW/NO_TRADE)
  IndependentVerifier.verify(...)             → PASS / FAIL
  DecisionEngine.decide(...)                  → TRADE_PAPER | SHADOW_TRADE | NO_TRADE
  ejecución (únicamente TRADE_PAPER)          → PaperBroker.execute_signal
  DecisionTrace.append(...)                   → sellado en la cadena de hashes

[post-ciclo]
  PaperBroker.reconcile_session → delta de trades cerrados → RiskManager
  OutcomeEvaluator.resolve_pending(...) → OutcomeRecord (o PENDING_OUTCOME)
  StrategyPerformanceStore.update_from_outcome(...)   (idempotente por OutcomeKey)
```

## 3. Reglas de decisión (orden fijo, fail closed)

| # | Condición | Modo | Clasificación | `no_trade_kind` |
| --- | --- | --- | --- | --- |
| 1 | un agente emite VETO | NO_TRADE | `AGENT_VETO` | `NO_TRADE_CONFLICT` |
| 2 | verifier != PASS | NO_TRADE | `VERIFIER_FAIL` | `NO_TRADE_CONFLICT` |
| 3 | sin propuesta | NO_TRADE | `NO_PROPOSAL` / `NO_ALPHA` / `UNKNOWN_STRATEGY` | `NO_TRADE_STRATEGIC` |
| 4 | sin snapshot / sin contexto | NO_TRADE | `NO_MARKET_DATA` / `CONTEXT_ERROR` | `NO_TRADE_DATA` |
| 5 | `RiskManager` VETO (binding) | NO_TRADE | `RISK_VETO` | `NO_TRADE_RISK` |
| 6 | gross edge <= 0 | NO_TRADE | `NO_GROSS_EDGE` | `NO_TRADE_STRATEGIC` |
| 7 | net > 0 **y** admitida **y** riesgo PASS/ADJUST | **TRADE_PAPER** | `PAPER_ADMITTED` | — |
| 8 | gross > 0, no admitida (o net <= 0) | **SHADOW_TRADE** | `NOT_ADMITTED` / `COST_KILLED` | — |

`NO_TRADE` es una decisión de primera clase, no un error: se persiste con su causa y
con su `no_trade_kind`. La regla 7 es el **único** camino que crea una orden.

### 3.1 NO_TRADE vs FALLO OPERATIVO

Nunca se mezclan. Si lo que ocurre es una incidencia — el proveedor falla, la
estrategia lanza una excepción, el broker falla — la fila **no** lleva
`no_trade_kind`: lleva `failure_kind` (`PROVIDER_FAILURE`, `INTERNAL_ERROR`,
`ADAPTER_FAILURE`, `INVALID_DATA`) y suma en `totals.runtime_failures`, **no** en
`totals.no_trades`. Identidad contable comprobada en tests:

```text
paper_trades + shadow_trades + no_trades + runtime_failures
    == asset_cycle_evaluations
```

Un fallo operativo tampoco forma hipótesis: no hay propuesta ⇒ no hay outcome, así
que jamás entra en `StrategyPerformance`.

### 3.2 NO_TRADE como hipótesis medible

Un `NO_TRADE_STRATEGIC` con propuesta (p. ej. `NO_GROSS_EDGE` o `COST_KILLED`
cuando SHADOW está desactivado) **sí** se evalúa: su outcome mide si evitar la
operación fue económicamente correcto. Esas muestras se guardan bajo su propio modo
(`no_trade_sample_size`) y **no** pueden reordenar la selección por sí solas.

## 4. SHADOW_TRADE

Un `SHADOW_TRADE` observa qué habría ocurrido con un candidato de research **sin**
crear orden, sin tocar el portfolio y sin consumir capital:

- `ShadowTradeDecision` va marcado (`marked_shadow=True`, `mode="SHADOW_TRADE"`);
- el runtime jamás llama al broker en ese camino (probado con broker espía);
- `DecisionTrace.__post_init__` **rechaza** un trace SHADOW con `order_created=True`;
- el verifier comprueba `orders_created == 0` para SHADOW.

Existe para que el sistema pueda aprender mientras `PAPER_CANDIDATES = 0`.

## 5. Riesgo: observable SIEMPRE, autoridad única

El motor determinista es **uno**: `trading_bot.risk.manager.RiskManager`. No existe
un RiskManager “de shadow”. Lo que cambia con el modo es la **vinculación**:

| Modo | Revisión | Efecto |
| --- | --- | --- |
| `TRADE_PAPER` | **binding** (`advisory=false`) | PASS/ADJUST autoriza; VETO bloquea |
| `SHADOW_TRADE` | **advisory** (`advisory=true`) | informativa: no autoriza ni bloquea |
| `NO_TRADE` con propuesta | **advisory** | informativa: se registra aunque no haya trade |
| `NO_TRADE` sin propuesta | no aplicable | `NOT_APPLICABLE`, `evaluated=false` |

Toda fila y todo trace llevan:

```text
risk_evaluated / risk_result / risk_rule / risk_reason / risk_inputs
```

Estados observables: `APPROVED`, `VETOED`, `NOT_APPLICABLE`. Además existe
`NOT_EVALUATED`: un veredicto que nadie produjo **nunca** se reporta como PASS —
`RiskReview.state` degrada a `NOT_EVALUATED` cualquier PASS con
`evaluated=false` (`test_a_pass_nobody_produced_is_not_evaluated_never_approved`).
Una revisión evaluada debe nombrar la regla aplicada y un veto debe dar su motivo
(validado en `__post_init__`).

Cinturón y tirantes: `DecisionEngine.decide` **rechaza** (raise) un paquete
order-authorising que traiga una revisión advisory, así que marcar la revisión como
“informativa” no puede saltarse la puerta
(`test_advisory_risk_can_never_sit_on_an_order_authorising_packet`).

## 6. Admisión (ledger)

`config/strategy_admission.json`, generado por `scripts/build_strategy_admission.py`
desde artefactos de research versionados
(`docs/STRATEGY_DISCOVERY_V3_RESULTS.json`, `docs/STRATEGY_ADMISSION_MATRIX.json`),
con los SHA-256 de las fuentes registrados:

- clave `"<family>@<timeframe>"`; entrada por (familia, timeframe) porque la evidencia
  de research es por horizonte;
- `PAPER_CANDIDATE` + `admitted_for_paper=true` sólo si el artefacto lista la familia en
  `paper_candidates` con gross medido positivo — hoy **ninguna** lo está;
- gross > 0 pero bajo coste ⇒ `COST_KILLED`; el resto `NO_GROSS_EDGE`;
- estrategia ausente ⇒ `UNKNOWN` ⇒ nunca PAPER (fail closed);
- `PAPER_CANDIDATE` sin evidencia de edge ⇒ **error de carga**.

Regeneración reproducible: `uv run python scripts/build_strategy_admission.py --check`.

### 6.1 El edge histórico es HISTORICAL_ESTIMATE, nunca verdad futura

Cada entrada lleva su procedencia completa:

```text
source_doc · metric · value_bps · knowledge · sample_trades
evidence_class = HISTORICAL_ESTIMATE · period · timeframe · status
```

`period` es la ventana real de muestreo (`W1-W7 2026-03-01..2026-09-24`) y `status`
es la clasificación que la familia se ganó. Ese valor es **el prior de un candidato**,
no una promesa de rentabilidad, y jamás se escribe como constante universal.

La identidad de la evidencia y del rendimiento incluye
`estrategia · activo · timeframe · régimen · modelo de coste`:
`AdmissionLedger.entries_for_timeframe` impide que evidencia de 30m se use como si
fuera de 5m (`test_evidence_identity_is_timeframe_aware`).

## 7. Coste

`COST_MODEL_V3` (research) evaluado **por ciclo**, con el spread **OBSERVED** del
snapshot real de este ciclo (clase de conocimiento registrada en el trace), tamaño real
(`--size-usd`) y horizonte pre-registrado (`--horizon-minutes`). El trace guarda el
desglose por componentes (fee KNOWN, spread OBSERVED, slippage/impact ESTIMATED) y la
versión del modelo. No se hardcodea ningún coste y no existe camino `ZERO_COST`.

Un gross positivo **no** implica operar: la decisión exige
`expected_net_edge = expected_gross_edge − expected_execution_cost > 0`
(`test_fixture_positive_gross_that_does_not_clear_cost_is_shadow`).

## 8. Verificación independiente

`IndependentVerifier` (BUILDER != VERIFIER) recibe el histórico crudo, la porción PIT
consumida, la propuesta y los inputs del coste, y **re-deriva**:

1. `pit_slice_exact` — la porción consumida es exactamente
   `closed_bar_slice(raw_history, decision_time)` (close <= decision_time): ni una
   barra futura, ni una barra en formación, ni una barra descartada en silencio;
2. `context_fingerprint` — la propuesta referencia el fingerprint del contexto;
3. `paper_requires_proposal` — TRADE_PAPER exige propuesta **y** una revisión de
   riesgo que realmente se ejecutó (`risk_evaluated`);
4. `cost_model_applied` — recalcula el coste con COST_MODEL_V3 y lo compara;
5. `proposal_arithmetic` — `net == gross - cost` y hay evidencia;
6. `admission_recomputed` — relee el ledger (no confía en la propuesta);
7. `shadow_purity` — SHADOW/NO_TRADE con 0 órdenes.

Cualquier fallo ⇒ `FAIL` ⇒ NO_TRADE.

## 9. Disponibilidad temporal: cuando CIERRA la barra

Una barra aporta información **al cerrar**, no al abrir. `src/trading_bot/autonomous/pit.py`
es el único sitio donde se declara la regla:

```text
infer_bar_interval_ms  → el espaciado, inferido de las barras (nunca declarado)
availability_ms(bar)   → bar.timestamp + interval   (su cierre)
closed_bar_slice(...)  → barras cuyo cierre <= decision_time
```

Se aplica en los tres sitios donde importa: la porción PIT que consume la decisión, la
comprobación `pit_slice_exact` del verifier y la evaluación del outcome. Consumir una
barra en formación, o fechar un outcome con la apertura de una barra, es look-ahead.

## 10. Trazabilidad y replay

`DecisionTrace` (append-only JSONL, cadena de hashes `prev_hash`/`trace_hash`) contiene
run/decision id, tiempos de mercado y decisión, contexto de mercado y de activo,
régimen, candidatos con `router_status`/`emitted_alpha`/`selected`, propuesta con
economía y procedencia del edge, mensajes de agentes, resultado del verifier, revisión
de riesgo completa, modo, motivo, clasificación, `no_trade_kind`, errores y
`cost_model_version`.

`DecisionTraceStore.replay(decision_id)` reconstruye la decisión **sólo** desde el
registro persistido (sin volver a leer mercado) y re-comprueba ordering PIT, hash,
pureza shadow, round-trip de la propuesta y `outcome_time > decision_time`. Devuelve un
estado honesto:

```text
FULL          → reconstruido todo, incluido el outcome resuelto
PARTIAL       → decisión reconstruida, horizonte aún sin cerrar (no hay outcome)
NOT_AVAILABLE → algún invariante falla o el registro no existe
```

Al final de cada run acotado se reproduce **todas** las trazas persistidas
(`RunSummary.replay: attempted / ok / failed / statuses / market_data_accessed=False`),
de modo que REPLAY queda evidenciado sobre datos reales y no sólo en tests.

## 11. Outcome y experiencia

`OutcomeEvaluator` sólo usa barras que **cierran** después del instante de decisión,
exige que el horizonte haya transcurrido (si no: `PENDING_OUTCOME`, nunca un número
inventado) y registra el contrato completo:

```text
decision_id · run_id · asset · strategy_id · mode · direction
decision_time_ms · market_time_ms · reference_price_time_ms · future_price_time_ms
horizon_minutes · entry_reference · outcome_price
gross_return_bps · estimated_cost_bps · net_hypothetical_bps
mfe_bps · mae_bps · direction_correct · outcome_status · outcome_key
```

Invarian te duro, validado en el contrato:

```text
reference_price_time_ms <= decision_time_ms < outcome_time_ms
```

`reference_price_time_ms` es el **cierre** de la última barra que la decisión podía
leer; `outcome_time_ms` (= `future_price_time_ms`) es el cierre de la primera barra
cuyo cierre alcanza el horizonte. La barra elegida es la que **contiene** el final del
horizonte, no la siguiente (comportamiento conservador anterior, corregido).

Idempotencia: `OutcomeKey = <decision_id>@<horizonte>`. `append_outcome` ignora un
duplicado y devuelve el registro ya almacenado, y `resolve_pending` salta lo ya
resuelto, así que `PENDING → RESOLVED` ocurre exactamente una vez por
decisión+horizonte, aunque se reprocese el mismo ciclo.

`StrategyPerformanceStore` agrega por (estrategia, activo, régimen, timeframe) y sólo
puede **reordenar la selección** con un ajuste acotado (±0.25, y 0 con muestra < 20).
No existe API para tocar límites de riesgo, sizing, capital, contabilidad ni umbrales
de admisión (test `test_experience_module_exposes_no_policy_mutation_api`).

## 12. Invariantes probadas

- ninguna orden sin admisión + verifier PASS + riesgo PASS/ADJUST **binding**;
- SHADOW/NO_TRADE ⇒ 0 órdenes y portfolio intacto;
- riesgo evaluado y registrado en toda decisión con propuesta (advisory incluida);
- `NOT_EVALUATED` nunca se reporta como `APPROVED`;
- `reference_price_time <= decision_time < outcome_time` (anti-lookahead, doble
  sentido);
- una barra en formación no se consume nunca (PIT por cierre);
- un `OutcomeKey` produce exactamente un outcome (idempotente);
- ningún fallo operativo se cuenta como NO_TRADE;
- toda decisión deja un trace persistido (incluso los errores de contexto);
- un ciclo con excepción se reporta en `errors` del run, nunca se oculta;
- el ledger sin evidencia o sin entrada ⇒ no hay PAPER;
- replay `FULL` sólo si el outcome existe.

## 13. Limitaciones conocidas

Ver `docs/runtime_authority_map.md` §5 (DEF-AUTO-2 universo no validado contra el
registro de agentes, DEF-AUTO-3 gate de frescura de 15 min que limita el timeframe,
DEF-AUTO-4 el entrypoint legado sigue marcando todo `CONFIRMED`).

Añadido en esta fase: `PAPER_CANDIDATES = 0` ⇒ `TRADE_PAPER = 0` es el resultado
**correcto** de las reglas, no una carencia del runtime. La evidencia de que PAPER se
ejecuta de verdad cuando existe un candidato admitido es el fixture determinista
`tests/unit/autonomous/test_cost_gate_risk_fixture.py`, que está **separado** del run
de mercado real y así queda rotulado.
