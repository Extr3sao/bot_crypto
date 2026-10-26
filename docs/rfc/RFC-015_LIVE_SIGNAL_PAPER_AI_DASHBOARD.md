# RFC-TDM-015 — Live Signal Intelligence, Paper Operations & Dashboard

**Estado:** PROPOSED / NOT_IMPLEMENTED / NOT_VERIFIED
**Fecha:** 2026-10-26
**Proyecto:** Trading Agentic Portable
**Prioridad:** P0 OPERATIVO
**Tipo:** Integración de runtime autoritativo, señales prospectivas, PAPER continuo y observabilidad de IA
**Modo:** `PAPER_ONLY`, sin órdenes reales
**Dependencias:** cierre documentado de RFC-TDM-014A; reutilizar RFC-EXP-003P y RFC-TAP-AI-BOTS-003 si están implementados y son runtime-reachable, sin duplicarlos.
**Estado económico heredado e inalterable:** `NO_ELIGIBLE_CANDIDATE / REJECTED_ALPHA`.

> Nota de ubicación: el RFC §10 nombra `docs/rfcs/RFC-TDM-015-…md`. Este repositorio
> numera sus RFC en `docs/rfc/` (RFC-046, RFC-048, RFC-049…), así que el documento vive
> aquí por convención del proyecto. La ruta se declara en
> `evidence/tdm/wp-tdm-15/FINAL_REPORT.json`.

## 1. Decisión y objetivo

**DECISION:** convertir los subsistemas ya implementados en **un circuito operativo demostrable** que reciba datos en vivo, evalúe estrategias en velas cerradas, genere y registre señales/candidaturas/rechazos, ofrezca análisis LLM real pero no autoritativo, ejecute únicamente órdenes PAPER experimentales autorizadas por reglas deterministas y muestre todo en un dashboard actualizado. Prioridad absoluta a **runtime reachability, observabilidad, trazabilidad y disponibilidad**, no a ampliar el catálogo de agentes ni a declarar una ventaja económica no demostrada.

**Objetivo del usuario:** mantener PAPER funcionando como servicio continuo, ver señales aparecer en tiempo real, entender cómo las analiza la IA y observar órdenes simuladas, bloqueos, riesgo y PnL neto.

**No confundir:** `PAPER_SERVICE_RUNNING` (plataforma funcionando) ≠ `ALPHA_ELIGIBLE` (estrategia rentable) ≠ `LIVE_TRADING_AUTHORIZED` (capital real). La aceptación de este RFC solo autoriza la primera afirmación si hay evidencias de ejecución real.

## 2. Evidencia y límites del punto de partida

- **Fuente 1, autoridad alta pero indirecta:** cierre suministrado de RFC-TDM-014A: `fix/tdm14a` en `c8a8af16`, 12/12 ACC PASS, 43/43 tests dirigidos, 10/10 negativos, 27/27 comprobaciones de cierre, 79 fallos de suite heredados en baseline; dos replays LF/CRLF; ninguna orden PAPER/LIVE; verificación organizativa independiente no demostrada; D-05 abierto. *Son resultados reportados, no re-ejecutados aquí.*
- **Fuente 2, repositorio remoto inspeccionado:** `Extr3sao/Bot-Trading`, `main` = `cadb0f08b58e99eb56b4233c312f5a9ede476f14`, último commit visible de 2026-05-10; **NO contiene** la rama `fix/tdm14a` ni el HEAD `c8a8af16`. El remoto visto es un snapshot histórico AstraQuant/AETHEL-BOT y **no acredita** ser el Git remoto autoritativo del runtime TDM actual.
- **Fuente 3, código histórico verificado** en `Extr3sao-s-Org/AETHEL-BOT/aethel_bot/sim/paper_live_engine.py`: `on_ohlcv` es `pass` y `run_paper_live` solo conecta el ticker a `PaperBroker.on_tick`; no se demuestra generación de señales en ese circuito.
- **Fuente 4, código histórico verificado** en `.../intelligence/agent_bridge.py`: `SimpleAgentBridge` ejecuta `_mock_llm_call` y usa `random.choice`; no es análisis LLM real. Prohibido atribuirle decisiones inteligentes reales.
- **Fuente 5, código histórico verificado** en `.../analysis/signal_engine.py`: existe generación de candidatos, diagnósticos de rechazo, filtro ML y puente de IA. **No presumir** que esta es la ruta operativa actual.
- **Fuente 6, interfaz histórica verificada:** `.../src/aethel/services/dashboardApi.ts`, `.../src/aethel/components/SignalDiagnosticsPanel.tsx` y `docs/signal-observability-audit.md` indican endpoints y visualización de diagnóstico. **No crear otro dashboard** sin revisar la interfaz realmente desplegable en la versión actual.
- **Fuente 7, código histórico verificado** en `.../sim/paper_broker.py`: los cierres de `on_tick` y `_execute_exit` describen explícitamente supuestos LONG; comprobar simetría LONG/SHORT si el código es alcanzable en runtime actual.

**CLAIM:** existe un riesgo demostrado de **componentes nominalmente completos pero no conectados de extremo a extremo** en el snapshot histórico. **DECISION:** empezar por auditoría runtime; si el código actual ya resuelve algo, reutilizarlo y documentar evidencia, no reimplementarlo.

## 3. Alcance e invariantes

### In scope
1. Reconstruir cadena `entrypoint → scheduler → data feed → strategy → proposal → review → deterministic decision/risk → experimental paper broker → reconciliation → dashboard` con pruebas reales de ejecución.
2. Datos de mercado reales en vivo para una cesta inicial configurable (BTC, ETH, SOL; símbolos y mercados solo si el proveedor lo soporta), timeframes 5m/1h/4h y reglas point-in-time. Reutilizar infra existente y priorizar velas cerradas como disparador de señales; ticks para marcar posiciones.
3. Registrar por ciclo: activos evaluados, estrategias seleccionadas/no aplicables, señales generadas, propuestas, rechazos y causa; `NO_TRADE` explícito.
4. Analista de IA conectado a un proveedor LLM real si hay credenciales y permisos, asíncrono, acotado y con salida estructurada. Mostrar análisis y errores, nunca inventar respuestas.
5. PAPER experimental continuo con costes, fees, spread, slippage y, si aplica, funding; cartera persistente, conciliación y recuperación tras caída.
6. Extender dashboard existente para representar señales/eventos reales y estado de cada subsistema en tiempo real.
7. Empaquetado reproducible, runbook de arranque automático y despliegue seguro de PAPER 24/7, sin acceso de capital.
8. Versionar, **commitear y hacer push a GitHub del remoto autoritativo verificado** todos los avances y reportes no sensibles.

### Fuera de alcance
- Órdenes live, permisos `PRODUCTION_ACTION`, fondos reales, leverage real, modificación del motor de riesgo o relajación de límites para forzar actividad.
- Dar por rentable, apta o promovida una estrategia cuyo estado actual sea `REJECTED_ALPHA`.
- Entrenar/reentrenar modelos en producción o autoeditar estrategias, prompts críticos, sizing o criterios de verificación.
- Inventar señales para una demo, usar respuesta LLM mock/random como real, pintar un dashboard con datos fake sin etiqueta explícita, completar un ACC por inspección estática.
- Sustituir frameworks enteros, crear otro orquestador, nuevas bases de datos o UI paralela si las actuales son reutilizables.

## 4. Arquitectura requerida

```text
PUBLIC MARKET FEED (WS + REST recovery)
  -> DataValidation [timestamps, finalized candles, gaps, freshness, dedup]
  -> MarketContext + AssetContext + Regime
  -> StrategyRegistry / StrategyRouter (real existing runtime)
  -> SignalObservation (incl. NONE / REJECTED reasons)
  -> TradeProposal [evidence, counterevidence, invalidation]
  +-> Async AI Analyst/Critic [REAL / ERROR / UNAVAILABLE; advisory only]
  -> Deterministic Decision + Risk Gate + Eligibility Policy
      +-> NO_TRADE / OBSERVE [record]
      +-> EXPERIMENTAL_PAPER_ONLY [paper-only route]
             -> PaperOrder -> PaperFill -> Portfolio / Reconciliation
  -> Append-only DecisionTrace / EventStore -> API SSE or WebSocket -> EXISTING dashboard
  -> Operational metrics + alerts + Run Reports
```

**Separación obligatoria:** `Research/Shadow Signal` es observable incluso si se rechaza. `ExperimentalPaperOrder` solo nace de una estrategia y política experimental explícitas, verificadas, y jamás cambia `REJECTED_ALPHA` a `APPROVED_ALPHA`. IA no puede ordenar operaciones, decidir tamaño, cambiar el risk engine ni invalidar sus vetos.

**Temporalidad:** `source_time <= candle_close_time <= decision_time <= event_persisted_at` en evaluaciones de velas cerradas; en eventos de tick, usar sus timestamps propios y mantener el orden causal. HTF solo si había cerrado antes del instante de decisión. No usar datos futuros, timestamps falsos ni datos stale.

## 5. Contratos mínimos versionados

### `SignalEvent.v1`

```json
{
  "schema_version": "1",
  "event_id": "uuid",
  "run_id": "uuid",
  "cycle_id": "uuid",
  "asset": "BTC/USDT",
  "market": "spot",
  "strategy_id": "strategy-versioned",
  "strategy_version": "commit-or-version",
  "timeframe": "5m",
  "candle_close_time_utc": "ISO-8601 UTC",
  "decision_time_utc": "ISO-8601 UTC",
  "direction": "LONG|SHORT|NONE",
  "state": "EVALUATED|CANDIDATE|PROPOSED|REJECTED|NO_TRADE|EXPERIMENTAL_PAPER_ELIGIBLE",
  "reason_code": "ENUM_STABLE",
  "reason_details": {},
  "indicator_snapshot": {},
  "data_fingerprint": "sha256",
  "evidence_refs": [],
  "counter_evidence_refs": [],
  "invalidation": null,
  "cost_model_version": "versioned",
  "runtime_commit": "git-sha"
}
```

`SignalEvent` siempre existe por activo/estrategia/ciclo, incluso sin señal; cardinalidad controlada. Estados mutuamente coherentes, transiciones explícitas e idempotentes. Identificador dedupe determinista derivado de `source + asset + strategy_version + timeframe + closed_candle_time + candidate_key`, separado de `event_id`.

### `AIReview.v1`

`review_id, signal_event_id, run_id, model/provider, prompt_id/version, request_time, response_time, status(REAL|TIMEOUT|ERROR|UNAVAILABLE|SKIPPED_BUDGET), claim, rationale_summary, evidence_refs[], counter_evidence_refs[], uncertainty_flags[], confidence_if_calibrated, cost, tokens, latency_ms, output_schema_version, operator_mode=ADVISORY_ONLY`.

- Las opiniones y confianzas del LLM no deben presentarse como probabilidad estadística de rentabilidad salvo calibración externa.
- Una respuesta local heurística puede existir como `HEURISTIC`, diferenciada visualmente de `REAL`; prohibido mock probabilístico en camino productivo.
- Si IA no está disponible: `AI_UNAVAILABLE`, análisis omitido y visible; PAPER determinista sigue solo si su política y gates independientes permiten continuidad. No declarar "IA analizando" si no hubo inferencia.

### `PaperLifecycle.v1`

`proposal_id, signal_event_id, eligibility_status, decision_id, risk_gate_id, paper_order_id, fill_id, account_id, side, requested_qty, filled_qty, modeled_spread, modeled_slippage, fees, funding_if_applicable, order_status, fill_time, mark_time, realized_pnl, unrealized_pnl, net_pnl, reconciliation_status, config_version, event_sequence`.

Separar flujos `OBSERVATION_ONLY`, `EXPERIMENTAL_PAPER` y `ALPHA_ELIGIBLE_PAPER`; este RFC solo habilita los dos primeros y nunca promueve al tercero por defecto.

### `RuntimeHealth.v1`

`service, status(HEALTHY|DEGRADED|BLOCKED|STOPPED|UNKNOWN), last_good_event_at, feed_age_seconds, last_closed_candle_at, scan_cycle_lag, ai_queue_age, paper_reconcile_age, persistence_lag, uptime, run_id, commit, blocker, actionable_hint`.

El dashboard jamás puede mostrar estado `RUNNING/HEALTHY` únicamente porque la web responde HTTP 200: la salud depende de eventos vivos y reconciliación.

## 6. Dashboard existente — experiencia exigida

Pantallas o bloques, integrados en la UI actual:

1. **Estado LIVE:** `PAPER ONLY`, exchange/mercado, conectividad, último tick, última vela cerrada, lag/freshness, scheduler activo, IA `REAL/UNAVAILABLE`, estado de cartera y persistencia; alerta clara de fallo o datos stale.
2. **Flujo de señales en vivo:** línea temporal por asset/estrategia con evento real, hora, timeframe, resultado y razón; filtro `CANDIDATE / REJECTED / NO_TRADE / EXPERIMENTAL_PAPER`, expansible con indicadores y evidencia.
3. **Análisis IA:** texto breve y evidencia/counter-evidence por señal, modelo, marca temporal, coste, duración y estado; distinción `REAL` versus `HEURISTIC` versus `UNAVAILABLE`.
4. **PAPER:** operaciones abiertas/cerradas, entradas/salidas, fees/slippage/funding, equity, drawdown, net PnL, exposición, órdenes rechazadas, reconciliación.
5. **Diagnóstico:** embudo `evaluations → candidates → proposals → risk_pass → paper_orders → fills`; principales bloqueos por activo, estrategia y tiempo. Mostrar **0** cuando el contador es realmente cero; **UNKNOWN / NO_DATA** si la telemetría falta.
6. **Alerta no elegible:** banner persistente `REJECTED_ALPHA — EXPERIMENTAL PAPER, NOT VALIDATED` mientras se mantenga la decisión heredada.

UI read-only por defecto; `PAUSE/RESUME` solo en entorno PAPER, autenticado, auditado y sin habilitar LIVE. Datos enviados por SSE o WS con `event_id`, orden estable y reanudación por cursor; fallback polling si procede. No filtrar credenciales.

## 7. Plan de implementación limitado

### WP-TDM-015-00 — Baseline y GitHub authoritative sync (obligatorio primero)

- Inspeccionar `pwd`, `git remote -v`, rama, HEAD, worktrees, git status, tags, orígenes y SHA `c8a8af16`; comprobar si el checkout contiene el historial TDM-014A.
- Identificar entrada **realmente usada** para market data, estrategias, agentes, riesgo, paper, persistencia, API y frontend; emitir `runtime_authority_map.md` con `RUNTIME_AUTHORITATIVE / RUNTIME_REACHABLE / TEST_ONLY / EXPERIMENTAL / LEGACY / ORPHAN / DEAD_CODE`.
- Ejecutar comandos de arranque y tests existentes sin cambiar código; capturar `BASELINE_RUN_REPORT.md/.json`, defectos y bloqueos; distinguir 79 fallos heredados frente a regresiones.
- **GitHub:** la única copia remota accesible durante redacción fue `Extr3sao/Bot-Trading` con `main=cadb0f08` (mayo), distinto de TDM actual. **No empujar TDM-014A ni RFC-015 a ese remoto sin prueba de que `origin` local pertenece a dicho repositorio.** Validar URL exacta de `origin`, capacidad de `fetch/push`, rama base y árbol Git. Si es coherente, publicar en rama `feat/tdm-015-live-paper`, preservando `fix/tdm14a`, sin force push ni sobrescribir worktree ajeno. Si no es coherente: `GITHUB_SYNC_BLOCKED` con comando y evidencia, sin afirmar que se publicó.
- El flujo debe quedar diseñado para que **cada WP terminado tenga commit + push a rama correcta** con SHA remoto verificado y enlaces de commit; `NO_PUSH != DONE` (salvo impedimento documentado, en cuyo caso `BLOCKED`). CI debe ejecutarse sobre el commit remoto; no fusionar automáticamente a main si los gates no pasan.
- **ACC-WP00:** baseline reproducible + mapa de autoridad + remoto identificado + trazas; sin acciones destructivas ni borrado de evidencia.

### WP-TDM-015-01 — Live Feed → Signal Evaluation

- Reutilizar proveedor/infra de datos actual. Inicializar snapshot REST histórico suficiente para los indicadores; alimentar con WS, reconectar y recuperar gaps. Registrar recibos de datos reales con timestamps/fuente.
- Evaluar cada estrategia registrada en cierre de vela verificable. Priorizar BTC/ETH/SOL en 5m, HTF 1h/4h point-in-time; portfolio y configuraciones revisadas para multi-activo. `NO_SIGNAL` es resultado válido y visible.
- No bajar umbrales para fabricar señales. Medir conteos de candidatos y rechazos; identificar reglas que frenan actividad sin tocarlas. Objetivo de exploración ACTIVE ~3 operaciones/día **solo indicador aspiracional**, nunca criterio para ejecutar malas operaciones o forzar trades.
- Persistencia de eventos auditables, idempotencia ante reinicio y duplicate/replayed WS. Tests de stale, futuro HTF, exchange failover, e.g. sequence reordering, candle reopening, min-bars y dedupe.
- **ACC-WP01:** ejecución prospectiva real; por lo menos un evento de evaluación verificable por cada activo habilitado en un cierre de vela; cero look-ahead; un resultado completo si no hay candidato; no se exige señal de compra/venta artificial.

### WP-TDM-015-02 — Experimental PAPER lifecycle

- Conectar únicamente `EXPERIMENTAL_PAPER` usando interfaz existente de propuestas y motor de riesgo. La selección debe basarse en manifest versionado de experimento, jamás "alpha validado". Si no hay estrategia habilitada, registrar `NO_PAPER_ELIGIBLE` y continuar capturando señales.
- Simular y guardar `NEW → ACCEPTED/REJECTED → PARTIAL_FILLED/FILLED → MARKED → CLOSED/CANCELLED → RECONCILED` según los estados soportados; entrada, SL/TP, LONG y SHORT, reinicio, pérdida de WS, reconciliación idempotente, double-fills y gaps.
- Costes definidos por venue/tipo de orden; fees, spread, slippage y funding para derivados si aplica. Defaults explícitos de simulación y perfiles realistas pero sin prometer ejecución real. Diferenciar PnL bruto/neto.
- **ACC-WP02:** pruebas de órdenes 100% simuladas sin llamar a API privada de ejecución; reconstrucción cartera exacta tras restart; no operaciones duplicadas; risk veto comprobado.

### WP-TDM-015-03 — Live AI Reviewer REAL (asíncrono)

- Localizar IA actual: `MOCK/HEURISTIC/REAL/ABSENT`. Reutilizar agente analista y critic si existen en runtime. Integrar adaptador real a proveedor permitido con credenciales seguras; sin credenciales, UI muestra `UNAVAILABLE` y no simula respuestas.
- Activación por nuevo `CANDIDATE` o `REJECTED` relevante (y resumen periódico opcional), no por cada tick. Cola con idempotencia, timeout, retry limitado, rate limit, token/cost budget y circuit breaker. Modelo/prompt/schema versionados.
- El output observa hipótesis, evidencia, contraindicios y posibles causas de rechazo; **no modifica directamente órdenes, sizing, risk o criterios de promoción**. NO_TRADE y ausencia de confianza son válidos.
- **ACC-WP03:** al menos una inferencia REAL demostrada en un entorno configurado, con request/response metadata, coste y evidencia; casos de timeout/denegación deben quedar marcados como `UNAVAILABLE/BLOCKED` sin false success. Si no existe autorización/credenciales, esta ACC queda BLOQUEADA, no PASS ficticio.

### WP-TDM-015-04 — Dashboard operacional conectado

- Auditar frontend y endpoints actuales, reutilizar componentes de diagnóstico, portfolio, API y autenticación. Fijar contrato backend/frontend; asegurar que solo consume estado persistido del runtime, no fixtures.
- Timeline live y embudo, análisis IA etiquetado, cartera paper, health/freshness y alertas; actualización SSE/WS con reconexión o polling de respaldo.
- Probar E2E real (navegador) que entra un `SignalEvent` desde feed/worker persistido y aparece en UI, incluyendo `NO_TRADE`, IA fallida y un evento PAPER simulado. Fixture solo permitido en tests, etiquetado y aislado.
- **ACC-WP04:** capturas reales + traces API, sin necesidad de activar live trading; UI no dice HEALTHY ante ausencia de datos.

### WP-TDM-015-05 — Servicio PAPER 24/7 y certificación operacional

- Empaquetar el entrypoint existente como servicio con restart policy, health/readiness/dependency checks, logs rotados, copia/backup y retención de eventos, runbook de despliegue para entorno del usuario (Windows/Docker/Linux según lo disponible). **No configurar servicios ni exponer UI a Internet sin controls de acceso adecuados.**
- Soak de **72 horas** recomendado con datos reales y PAPER ONLY, más pruebas inyectadas de caída de WS, reinicio, duplicado, fallo proveedor IA, falta de credenciales y almacenamiento. Si la ventana no puede completarse, terminar en `NOT_YET_VERIFIED`, no certificar 24/7.
- Medir disponibilidad, lapsos sin ciclos, antigüedad datos, errores, duración IA, costes, latencia de eventos al dashboard, conteos por activo, rechazos, paper trades, PnL neto; todos los artefactos trazables a `run_id`/commit.
- **ACC-WP05:** servicio arranca/reanuda sin intervención manual, dashboard muestra flujos del mismo `run_id`, reconciliación correcta tras reinicio, orders live=0 y fallos etiquetados.

## 8. Criterios de aceptación globales RFC-TDM-015

| ID | Criterio mensurable | Evidencia exigida |
| --- | --- | --- |
| ACC-01 | Mapa de runtime y baseline del HEAD real; repo remoto identificado | `runtime_authority_map.md`, logs, Git SHA |
| ACC-02 | Rama de implementación y evidencias publicadas y consultables en GitHub correcto | URL remoto, commit remoto, CI; no force-push |
| ACC-03 | Ciclos vivos reales para BTC/ETH/SOL (o incompatibilidades explícitas) | Eventos cerrados con fuente y timestamps |
| ACC-04 | Cero datos futuros, stale filtrado, gaps/duplicados gestionados | Tests adversariales + ejecución |
| ACC-05 | Se registran observaciones, candidatas, rechazos y NO_TRADE con códigos estables | Contadores reconciliables por `run_id` |
| ACC-06 | Estrategias clasificadas y trade proposals solo desde datos reales | Evidence chain y versionado |
| ACC-07 | PAPER experimental integrado con gates deterministas, sin promover alpha | Manifest, risk veto, órdenes simuladas |
| ACC-08 | Ledger/portfolio/reconciliation consistente en arranque y restart | Re-ejecución y pruebas LONG/SHORT |
| ACC-09 | IA REAL instrumentada; fallback explicito y sin mocks | Modelo, inferencia real, tokens/costes; o `BLOCKED` |
| ACC-10 | UI consume eventos reales y muestra health, señales, IA, PAPER y motivos | Capturas E2E, API traces, browser logs |
| ACC-11 | Operación continua 72h, o estado honesto `NOT_YET_VERIFIED` | Soak report, fallos, restart, uptime |
| ACC-12 | Sin live order, secretos filtrados o saltos de riesgos; verificación separada | tests negativos, 0 live orders, verificador |
| ACC-13 | Informe final sin false success; fallos baseline y D-05 visibles | `FINAL_REPORT.md/json`, cierre remoto |

**Regla de veredicto:** `PAPER_OPERATIONAL_VERIFIED` requiere ACC-01..ACC-13 PASS, y ventana 72h completada con criterios SLO definidos antes del ensayo. Cualquier excepción = `PARTIAL`, `BLOCKED` o `NOT_YET_VERIFIED`. Independencia se informa como `INDEPENDENCE_NOT_DEMONSTRATED` mientras el verificador no sea suficientemente independiente; nunca sustituir por una etiqueta de certificación no sustentada.

**Gates separados:**
- `SIGNAL_STREAM_VERIFIED`: datos+evaluación+auditoría+UI.
- `EXPERIMENTAL_PAPER_VERIFIED`: simulación realista, persistencia y riesgo.
- `AI_REAL_VERIFIED`: provider LLM ejecutado, no mock.
- `PAPER_OPERATIONAL_VERIFIED`: integra los tres anteriores y evidencia de continuidad.
- `ALPHA_ELIGIBLE`: **NO**, permanecerá `REJECTED_ALPHA` salvo RFC de promoción posterior, basado en experimentos de ventaja neta.

## 9. Estrategia de tests y medición

- `UNIT`: esquemas, estados, slippage/fees/funding, dedupe, error reasons.
- `CONTRACT`: señales, IA, dashboard API, PaperLifecycle, health.
- `INTEGRATION`: feed real/snapshot ↔ strategy ↔ trace; decision ↔ broker ↔ ledger; SSE ↔ UI.
- `RUNTIME`: startup, cierre de vela, ticks, restart, pérdida temporal de datos, persistencia.
- `E2E`: navegador real contra el mismo backend/DB usados por el PAPER de pruebas.
- `ADVERSARIAL`: future HTF, stale/fake timestamps, duplicate candles, provider throttle, LLM fake success, partial fill duplicado, kill switch, disconnected feed.
- `REGRESSION`: comparar HEAD contra baseline, sin ocultar los **79 tests heredados** ni declararlos solucionados sin re-ejecutar.
- `PAPER_SOAK`: actividad continua e informes automáticos; 0 live order, 0 FALSE_SUCCESS.

Métricas: `data_freshness, evaluated_assets_per_cycle, evaluation_count, candidate_rate, rejection_reason_distribution, proposal_count, experimental_paper_count, fill_rate, net_pnl, drawdown, unrealized_pnl, spread_slippage_fees, ai_real_rate, ai_error_rate, ai_cost, event_to_ui_latency, uptime, recovery_duration`. No optimizar únicamente número de operaciones. Aspiración ACTIVE de ~3 operaciones/día sujeta a restricciones y a aprobación económica posterior.

## 10. Registro de evidencias y cierre

Generar en repositorio actual (o adaptar rutas existentes):

```text
docs/rfcs/RFC-TDM-015-LIVE-SIGNAL-PAPER-AI-DASHBOARD.md
docs/runtime/runtime_authority_map.md
evidence/tdm/wp-tdm-15/BASELINE_RUN_REPORT.md
evidence/tdm/wp-tdm-15/BASELINE_RUN_REPORT.json
evidence/tdm/wp-tdm-15/SIGNAL_RUN_REPORT.json
evidence/tdm/wp-tdm-15/PAPER_RECONCILIATION.json
evidence/tdm/wp-tdm-15/AI_REAL_INFERENCE.json
evidence/tdm/wp-tdm-15/DASHBOARD_E2E.json
evidence/tdm/wp-tdm-15/SOAK_REPORT.json
evidence/tdm/wp-tdm-15/GITHUB_SYNC_REPORT.json
evidence/tdm/wp-tdm-15/FINAL_REPORT.md
evidence/tdm/wp-tdm-15/FINAL_REPORT.json
```

No almacenar claves, tokens, datos personales, dumps sensibles o logs gigantes en Git. Evidencias pequeñas con hashes + rutas a artefactos externos si procede; nunca falsificar integridad ni declarar un hash sin verificar bytes.

Cada `RUN_REPORT` incluye `run_id, git_head, branch, remote, env, real_vs_mock, data_source, assets, time_range, agents, strategies, signal_counts, risk_decisions, paper_orders, live_orders, warnings, failures, test_counts, cost, latency, result, evidence_refs`.

**Cierre obligatorio:** `PHASE / COMMITS / PUSHED_REMOTE_SHA / IMPLEMENTED / TESTS / RUNTIME_VALIDATION / PAPER_VALIDATION / AI_VALIDATION / FALSE_SUCCESS / DEFECTS / BLOCKERS / EVIDENCE / ARCHITECTURE_STATUS / RFC_STATUS / NEXT_PHASE`.

## 11. Secuencia obligatoria para Codex (autónoma, sin bucles de arquitectura)

1. Identifica checkout y remote actuales. Si hay worktree compartido modificado, no alterarlo: crear un worktree/branch aislado desde commit autorizado. Investiga por qué GitHub visible y TDM-014A difieren.
2. Conserva `fix/tdm14a`/`c8a8af16` y todos los artefactos; usa Git como autoridad de identidad para comparar fuentes, según TDM-014A. No inventes que GitHub estaba actualizado.
3. Ejecuta baseline y demuestra qué código actual sirve para señales, PAPER, IA y dashboard. Publica hallazgos; no construyas framework nuevo si existe camino reutilizable.
4. Completa WP-00 a WP-05 secuencialmente. Cada WP: código mínimo, tests, ejecución real, evidencia, revisión independiente de código, commit, **push a GitHub correcto**, verificación SHA remoto y breve reporte.
5. Si un bloqueo requiere credenciales nuevas, costes pagados o autorización de despliegue expuesto: no inventes ni pidas datos en texto plano. Completa el resto sin esas capacidades, deja ACC afectada `BLOCKED` y especifica un único desbloqueo concreto.
6. Prohíbe LIVE real desde configuración, CLI, API, tests y permisos en esta entrega; comprueba rutas negativas de ejecución. Un PAPER real 24/7 no es una orden con capital.
7. No fusionar automáticamente ramas, no forzar git push, no borrar resultados, no reabrir `REJECTED_ALPHA`.
8. Al terminar, entregar enlaces de GitHub exactos, comandos reproducibles de arranque PAPER/dash, URL local del dashboard **medida**, último `run_id`, estado operativo, nº real de señales/candidatos/órdenes, y bloqueos honestos.

**Definition of Done:** `REQ → ACC → ARCH → RFC → WP → IMP → TEST → EXEC → EVID → VERIFIER` más `REMOTE_PUSH_VERIFIED`, `FALSE_SUCCESS = 0`, `LIVE_ORDERS = 0`; PAPER y dashboard deben verse corriendo en runtime real, no únicamente con capturas estáticas.
