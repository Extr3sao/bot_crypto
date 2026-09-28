# AUTONOMOUS_PAPER_RUNTIME — ejecutable, verificable, con evidencia

> Fase: **AUTONOMOUS-PAPER-RUNTIME-V1**. Implementación: `src/trading_bot/autonomous/`,
> entrypoint `scripts/autonomous_paper.py`. Es la primera vez que el proyecto tiene un
> camino completo `datos reales → decisión → verificación → riesgo → PAPER/SHADOW/NO_TRADE
> → trace → outcome → experiencia` ejecutado de verdad.

## 1. Entrypoint

```bash
# ONE_SHOT (un ciclo)
uv run python scripts/autonomous_paper.py --cycles 1 --assets BTC,ETH,SOL

# BOUNDED_LOOP (N ciclos, intervalo en segundos; nunca infinito)
uv run python scripts/autonomous_paper.py --cycles 3 --interval 340 \
  --assets BTC,ETH,SOL --timeframe 5m --horizon-minutes 5 \
  --provider ccxt --config-dir config/realdata \
  --run-id autonomous-paper-real-001
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
  FetcherBarReader → histórico PIT por símbolo (<= as_of)
  trim_to_pit → barras consumibles

[determinista, sin I/O]
  AssetContext (validado) → régimen
  por cada candidato en orden de ranking (ledger + experiencia acotada):
      StrategyRouter.route({candidato})       → SELECTED / REJECTED
      familia.generate(barras, {}, None)      → ¿emite alpha?
  selección: mayor expected gross edge entre los que emiten
  TradeProposal (gross / cost / net + evidencia)
  AgentRegistry.review(...)                   → observations / critiques / vetos
  DecisionEngine.intend(...)                  → intención pura
  RiskManager.check_signal(...)               → SOLO si la intención podría ordenar
  IndependentVerifier.verify(...)             → PASS / FAIL
  DecisionEngine.decide(...)                  → TRADE_PAPER | SHADOW_TRADE | NO_TRADE
  ejecución (únicamente TRADE_PAPER)          → PaperBroker.execute_signal
  DecisionTrace.append(...)                   → sellado en la cadena de hashes

[post-ciclo]
  PaperBroker.reconcile_session → delta de trades cerrados → RiskManager
  OutcomeEvaluator.resolve_pending(...) → OutcomeRecord (o PENDING_OUTCOME)
  StrategyPerformanceStore.update_from_outcome(...)
```

## 3. Reglas de decisión (orden fijo, fail closed)

| # | Condición | Modo | Clasificación |
| --- | --- | --- | --- |
| 1 | un agente emite VETO | NO_TRADE | `AGENT_VETO` |
| 2 | verifier != PASS | NO_TRADE | `VERIFIER_FAIL` |
| 3 | sin propuesta | NO_TRADE | `NO_PROPOSAL` / `NO_ALPHA` / `NO_MARKET_DATA` / `CONTEXT_ERROR` |
| 4 | estrategia desconocida en el ledger | NO_TRADE | `UNKNOWN_STRATEGY` |
| 5 | `RiskManager` VETO | NO_TRADE | `RISK_VETO` |
| 6 | gross edge <= 0 | NO_TRADE | `NO_GROSS_EDGE` |
| 7 | net > 0 **y** admitida **y** riesgo PASS/ADJUST | **TRADE_PAPER** | `PAPER_ADMITTED` |
| 8 | gross > 0, no admitida (o net <= 0) | **SHADOW_TRADE** | `NOT_ADMITTED` / `COST_KILLED` |

`NO_TRADE` es una decisión de primera clase, no un error: se persiste con su causa.
La regla 7 es el **único** camino que crea una orden.

## 4. SHADOW_TRADE

Un `SHADOW_TRADE` observa qué habría ocurrido con un candidato de research **sin**
crear orden, sin tocar el portfolio y sin consumir capital:

- `ShadowTradeDecision` va marcado (`marked_shadow=True`, `mode="SHADOW_TRADE"`);
- el runtime jamás llama al broker en ese camino (probado con broker espía);
- `DecisionTrace.__post_init__` **rechaza** un trace SHADOW con `order_created=True`;
- el verifier comprueba `orders_created == 0` para SHADOW.

Existe para que el sistema pueda aprender mientras `PAPER_CANDIDATES = 0`.

## 5. Admisión (ledger)

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

## 6. Coste

`COST_MODEL_V3` (research) evaluado **por ciclo**, con el spread **OBSERVED** del
snapshot real de este ciclo (clase de conocimiento registrada en el trace), tamaño real
(`--size-usd`) y horizonte pre-registrado (`--horizon-minutes`). El trace guarda el
desglose por componentes (fee KNOWN, spread OBSERVED, slippage/impact ESTIMATED) y la
versión del modelo. No se hardcodea ningún coste y no existe camino `ZERO_COST`.

## 7. Verificación independiente

`IndependentVerifier` (BUILDER != VERIFIER) recibe el histórico crudo, la porción PIT
consumida, la propuesta y los inputs del coste, y **re-deriva**:

1. `pit_slice_exact` — la porción consumida es exactamente `timestamp <= decision_time`
   (ni una barra futura, ni una barra descartada en silencio);
2. `context_fingerprint` — la propuesta referencia el fingerprint del contexto;
3. `paper_requires_proposal` — TRADE_PAPER exige propuesta **y** revisión de riesgo;
4. `cost_model_applied` — recalcula el coste con COST_MODEL_V3 y lo compara;
5. `proposal_arithmetic` — `net == gross - cost` y hay evidencia;
6. `admission_recomputed` — relee el ledger (no confía en la propuesta);
7. `shadow_purity` — SHADOW/NO_TRADE con 0 órdenes.

Cualquier fallo ⇒ `FAIL` ⇒ NO_TRADE.

## 8. Trazabilidad y replay

`DecisionTrace` (append-only JSONL, cadena de hashes `prev_hash`/`trace_hash`) contiene
run/decision id, tiempos de mercado y decisión, contexto de mercado y de activo,
régimen, candidatos con `router_status`/`emitted_alpha`/`selected`, propuesta con
economía y evidencia, mensajes de agentes, resultado del verifier, resultado de riesgo,
modo, motivo, clasificación, errores y `cost_model_version`.

`DecisionTraceStore.replay(decision_id)` reconstruye la decisión **sólo** desde el
registro persistido (sin volver a leer mercado) y re-comprueba ordering PIT, hash,
pureza shadow, round-trip de la propuesta y `outcome_time > decision_time`.

## 9. Outcome y experiencia

`OutcomeEvaluator` sólo usa barras con `timestamp > decision_time`, exige que el
horizonte haya transcurrido (si no: `PENDING_OUTCOME`, nunca un número inventado) y
registra retorno bruto, coste, neto hipotético, MFE/MAE y acierto de dirección.

`StrategyPerformanceStore` agrega por (estrategia, activo, régimen, timeframe) y sólo
puede **reordenar la selección** con un ajuste acotado (±0.25, y 0 con muestra < 20).
No existe API para tocar límites de riesgo, sizing, capital, contabilidad ni umbrales
de admisión (test `test_experience_module_exposes_no_policy_mutation_api`).

## 10. Invariantes probadas

- ninguna orden sin admisión + verifier PASS + riesgo PASS/ADJUST;
- SHADOW/NO_TRADE ⇒ 0 órdenes y portfolio intacto;
- `data_time <= decision_time` en toda propuesta y trace;
- `outcome_time > decision_time` (anti-lookahead);
- toda decisión deja un trace persistido (incluso los errores de contexto);
- un ciclo con excepción se reporta en `errors` del run, nunca se oculta;
- el ledger sin evidencia o sin entrada ⇒ no hay PAPER.

## 11. Limitaciones conocidas

Ver `docs/runtime_authority_map.md` §5 (DEF-AUTO-2 universo no validado contra el
registro de agentes, DEF-AUTO-3 gate de frescura de 15 min que limita el timeframe,
DEF-AUTO-4 el entrypoint legado sigue marcando todo `CONFIRMED`).
