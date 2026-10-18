# RFC-TAP-MARKET-005 — Continuous Market Intelligence & Incremental Data Orchestration

**Fecha:** 2026-10-18  | **Estado:** PROPOSED / READY FOR CODEX AUDIT, NOT IMPLEMENTED  
**Repositorio:** `https://github.com/Extr3sao/bot_crypto`  
**Baseline fuente validada:** `agent/ai-bots/RFC-TAP-AI-BOTS-003` @ `fe9b5e2623b0d023833249e9687b753eaacd27d4`  
**Relación:** RFC-TAP-AI-BOTS-003 (PIT / provider / prospective) y RFC-TAP-AI-BOTS-004 (crítico SHADOW).  
**Prioridad:** P0 para continuidad de datos y reducción de lecturas redundantes; P1 para analítica IA; sin tocar LIVE.

## 0. Decisión ejecutiva

**No es correcto parar todas las descargas porque ahora analizaremos con IA.** Un modelo necesita un flujo íntegro y actualizado de datos. **Sí es correcto investigar y, después de demostrar equivalencia funcional, sustituir recargas de miles de velas por captura incremental**, evitando ventanas de consola y duplicación de llamadas.

Separar: (A) **bootstrap histórico** una vez por universo/timeframe; (B) **market data incremental** al cerrar vela o recibirse tick/quote observable; (C) **market intelligence determinista** sobre snapshot cerrado; (D) **IA de alto nivel por evento**, no por cada tick; (E) **decisión + riesgo + paper** bajo runtime canónico. Freebuff/Codebuff es una herramienta para desarrollar; no constituye un servicio de inferencia garantizado ni un plano de market data. Un bot autónomo debe poder seguir operando en SHADOW/PAPER sin Freebuff abierto.

`SOURCE -> INSIGHT -> REQ -> ACC -> ARCH -> RFC -> WP -> IMP -> TEST -> EXEC -> EVID`. `REAL_RUNTIME > EXECUTION_EVIDENCE > TESTS > CODE > RFC > ASSUMPTION`; `FALSE_SUCCESS=0`.

## 1. Hallazgos de auditoría source vs ejecución (no confundir)

| ID | Afirmación | Fuente / evidencia | Estado de confianza |
|---|---|---|---|
| S-01 | Los logs `fetch_ohlcv_start/ok` se emiten en `CCXTExchangeConnector.fetch_ohlcv`; la operación crea `req_id`, símbolo, timeframe y limit y llama al CCXT real. | [`exchange_connector.py`](https://github.com/Extr3sao/bot_crypto/blob/fe9b5e2623b0d023833249e9687b753eaacd27d4/src/trading_bot/market_data/exchange_connector.py) líneas ~291–333; captura aportada en conversación. | **SOURCE + USER_SCREENSHOT** |
| S-02 | `real_market_context.py` solicita exactamente 1000×1h, 500×4h, 500×1d, para una historia que incluye SMA(200); son cantidades que coinciden con la captura. | [`real_market_context.py`](https://github.com/Extr3sao/bot_crypto/blob/fe9b5e2623b0d023833249e9687b753eaacd27d4/src/trading_bot/research/real_market_context.py) (`FETCH_LIMITS`). | **SOURCE CORRELATION, CALLER UNPROVEN** |
| S-03 | Esa coincidencia NO identifica el proceso ni prueba que Task Scheduler sea quien descargó las velas: sin árbol PID→parent, task action/log, run_id y horario no podemos atribuirlo. | `scripts/ops_window_origin.py` / captura; falta correlación por `req_id`. | **UNKNOWN / P0 DIAGNOSTIC** |
| S-04 | `cap004_supervisor.py` tiene `DEFAULT_INTERVAL_SECONDS=900` (15 min), nombre de tarea `TradingAgentic-CAP004-Campaign` y generador de XML que ahora propone `pythonw.exe` + windowless launcher. | [`cap004_supervisor.py`](https://github.com/Extr3sao/bot_crypto/blob/fe9b5e2623b0d023833249e9687b753eaacd27d4/scripts/cap004_supervisor.py) | **SOURCE, NO TASK ACTIVE ASSUMPTION** |
| S-05 | La tarea real de CAP004 **no fue instalada/modificada** por `WP-OPS-BACKGROUND-001`; no dar por hecho que esté activa. | [`FINAL_REPORT.md`](https://github.com/Extr3sao/bot_crypto/blob/fe9b5e2623b0d023833249e9687b753eaacd27d4/reports/ops/WP-OPS-BACKGROUND-001/FINAL_REPORT.md) | **EXECUTION REPORT** |
| S-06 | Existe `OHLCVFetcher` con validación y caché/idempotencia; `oos_capture` aporta conservación append-only y marcas de cobertura. | [`ohlcv_fetcher.py`](https://github.com/Extr3sao/bot_crypto/blob/fe9b5e2623b0d023833249e9687b753eaacd27d4/src/trading_bot/market_data/ohlcv_fetcher.py), [`oos_capture.py`](https://github.com/Extr3sao/bot_crypto/blob/fe9b5e2623b0d023833249e9687b753eaacd27d4/src/trading_bot/research/oos_capture.py) | **SOURCE; REACHABILITY BY TARGET TO VALIDATE** |
| S-07 | Existe `forward_collector.py` WebSocket-first de microestructura, pero se declara **DISCOVERY PLANE ONLY**, sin interfaz al circuito de decisión. No promocionar el collector ni datos a trading solo por existir. | [`forward_collector.py`](https://github.com/Extr3sao/bot_crypto/blob/fe9b5e2623b0d023833249e9687b753eaacd27d4/scripts/forward_collector.py) | **SOURCE; RESEARCH_ONLY** |
| S-08 | El camino PAPER canónico documentado es `scripts/autonomous_paper.py` → strategy admission/agents → RiskManager → PaperBroker. En la rama económica se informó que no había estrategia admitida. | [`runtime_authority_map.md`](https://github.com/Extr3sao/bot_crypto/blob/fe9b5e2623b0d023833249e9687b753eaacd27d4/docs/runtime/runtime_authority_map.md), EDGE-017F. | **HISTORICAL EXECUTION, REVALIDATE CURRENT** |
| S-09 | `BOT-VIS-01`/`BOT-CTX-01` siguen sin llamadas a modelo verificadas. El provider actual contempla `VISION_API_KEY` y la infraestructura de requests; además, si el proveedor no entrega `id`, sintetiza un request id aparentemente real. | [`provider.py`](https://github.com/Extr3sao/bot_crypto/blob/fe9b5e2623b0d023833249e9687b753eaacd27d4/src/trading_bot/vision/provider.py) líneas ~313–315; AI-003C report. | **SOURCE / BLOCKED_MODEL_API** |
| S-10 | `Freebuff.exe → bun.exe → bash.exe` es el origen medido de la consola en esa sesión, pero también existía una ruta propia de tarea Python; ningún informe demuestra aún 0 popups visuales ni Task Scheduler activado con el nuevo wrapper. | WP-OPS-BACKGROUND-001. | **STRUCTURAL VERIFIED; VISUAL UNOBSERVED** |

**GAP prioritario:** falta un inventario operativo que una cada descarga visible con proceso, tarea, destino, consumidor, coste y si alimenta **realmente** al runtime. Un log `fetch_ohlcv_ok` prueba que una petición terminó, **no** que se utilizó su dato ni que se ejecutó una decisión.

## 2. Alcance / no alcance

**Objetivos**
1. Inventariar TODOS los entrypoints de adquisición, programadores, scripts `fetch_*`, WebSocket, snapshots, storage, temporales, research y consumer paths sin borrar nada.
2. Evidenciar quién provoca las descargas en Windows (Freebuff, tarea programada, worker manual u otro) y qué alimentan.
3. Crear/normalizar un flujo **incremental, idempotente, en un solo propietario lógico por símbolo/timeframe**, con bootstrap seguro y almacenamiento limitado; reutilizar adapters y colectores reales demostrados.
4. Entregar `MarketSnapshot` causal consumible por agentes de mercado/visual/contextual, con una única fuente de verdad de datos y una puerta de disponibilidad por tiempo.
5. Disparar análisis IA **por cambio significativo y por cierre válido**, condicionado a cuotas, coste y modo permitido; `NO_ANALYSIS/NO_TRADE` es resultado legítimo.
6. Mostrar salud y cobertura: barras esperadas/recibidas/gaps/corregidas/retrasadas, age, failures, cuota, llamadas realmente procesadas, latencia, coste/LLM y ventanas visibles.
7. Facilitar pausa, reanudación, fallos y rollback conservando campañas/evidencias existentes.

**No objetivos / prohibido**: usar Freebuff como API implícita; transformar un script de investigación en trader de producción sin admisión; parar tareas reales sin consentimiento; borrar datasets, logs, campañas, evidencias o credenciales; operar en exchange real, cambiar tamaño, leverage, risk/weekend/admission; gastar API LLM sin autorización; asegurar rentabilidad por tener IA.

## 3. Arquitectura mínima propuesta — reutilización, no reescritura

```text
                 PRE-FLIGHT / OWNER MAP  (read-only, PID/task -> command -> consumer)
                                      |
             Public Exchange REST / verified WS feeds (read-only)
                                      |
          One Incremental Ingestion Supervisor (or EXISTING supervisor adapter)
             |                         |                        |
      bootstrap (1 vez)         bar-close deltas            quote/1m optional
          / warm-up             since last watermark        after response only
             +-------------------------+------------------------+
                                      |
          Canonical Store + append-only original + source/sha/watermarks
                                      |
           PIT MarketSnapshot Gate (closed/received/available/fresh)
                                      |
              Deterministic market/asset intelligence + changes
                                      |
       Event Trigger and Throttler (closed candle / material change)
                                      |
                  BOT-CTX-01  +  BOT-VIS-01
                  (REAL provider only if explicitly authorized)
                                      |
         TradeProposal + DecisionTrace + critics shadow (optional)
                                      |
         Strategy Admission → Deterministic RiskManager → PaperBroker
                                      |
        reconciliation + coverage/decision/latency/LLM-cost report
```

The external Freebuff GUI can build/monitor/administer this system. **It is NOT in its data or inference dependency graph.** Only compatible, authorized provider APIs can supply actual LLM inference.

### Ownership and adapters
- Prefer `CCXTExchangeConnector` / `OHLCVFetcher` + `OHLCVStore`, `market_data/quota.py`, existing `research/oos_capture` and `risk/manager.py`; do **not** introduce a second broker, clock or RiskManager.
- New modules ONLY if necessary: `market_data/ingestion_registry.py` (owners/capabilities), `market_data/incremental.py` (watermark/ingest), `market_data/snapshot.py` (contract), `market_data/market_events.py` (trigger policy), `autonomous/market_intelligence_bridge.py` (PAPER SHADOW wiring). Prefer compositions around existing classes.
- The forward microstructure WebSocket collector stays in DISCOVERY until test + RFC admission proves correct source, freshness, conservative costs, quotas and route reachability. Do not blindly stream every tick into an LLM.

## 4. Contratos

### `MarketDataEvent v1`

```
source_id, provider, market_type, symbol, timeframe, event_kind,
open_time_ms, close_boundary_ms, exchange_event_time_ms,
observed_at_ms, received_at_ms, persisted_at_ms, available_at_ms,
is_final, ohlcv, quality_status, source_hash, content_hash,
ingestion_run_id, sequence, correction_of, storage_ref
```

Kinds: `BOOTSTRAP_BAR`, `CLOSED_BAR`, `CORRECTION`, `GAP`, `QUOTE`, `PROVIDER_FAILURE`, `PROVIDER_RECOVERY`. Distinguish **exchange timestamp** vs receive timestamp; if source does not provide it, mark `UNKNOWN`, never fabricate. `CLOSED_BAR` only when data closed and actually received. `bar.ts_ms` is **open time**, not decision time. Higher timeframe 4h/1d cannot be read before its close.

### `IngestionWatermark v1`

```
(source, symbol, timeframe) -> last_verified_open_ms,
last_closed_boundary_ms, last_ingested_seq, last_persisted_sha,
coverage_window, upstream_cursor, updated_at_ms, checksum
```

Bootstrap fetches enough warm-up for the strategies it actually serves (existing `1000/500/500` must be justified per consumer); subsequent fetches use **since/watermark** plus a small configurable overlap for provider corrections. If provider lacks `since` or the adapter cannot prove it, provide a bounded last-N snapshot and de-duplicate; never claim delta without evidence. CRLF/source hashes have explicit domains; historical originals remain immutable with corrections represented by new linked events rather than silently rewriting evidence.

### Causality and quote scope

```text
bar.open < bar.close_boundary <= actual_receive <= snapshot_built
                           <= model_request <= model_response <= risk_review
                           <= observed_executable_quote <= paper_fill
```

No future 4h/1d candle, no stale context, no `bar.open` used as data availability. If LLM responds after the last quote, it waits for a *new* price event or produces `NO_EXECUTABLE_PRICE`. Historical 1m OHLC can support offline causality tests but does not imply a real millisecond-executable bid/ask.

### Event/cost policy
- Always-on cheap deterministic checks are permitted under public read quotas.
- LLM triggers: **new final candle**, `regime/material change` verified from closed data, or explicit manual research, each with stable event id, dedupe key and cooldown. Frequency and approximate spend limits declared; no LLM call merely because Task Scheduler ran.
- Cache per `snapshot_hash + prompt_version + model_version` with TTL, strict invalidation and provider receipt; never present a cached response as fresh if conditions changed.
- API failures, stale bars, gap/quote insufficiency, budget exhaust or missing credential: `SKIP_LLM`/`NO_TRADE`, **not fake fallback**. `request_id` missing from provider = `UNKNOWN`, not a model-timestamp synthesis; do not conflate mock/live.

## 5. Work packages / commits recomendados

| WP | Trabajo | Entregable/gate |
|---|---|---|
| **WP-MKT-005A** | Auditoría de tareas y procedencia, solo lectura | `RUNTIME_FETCH_AUTHORITY_MAP.md`, `FETCH_PROCESS_TRACE.jsonl`, `SCHEDULER_INVENTORY.json`, lista clasificada de todos los scripts y conexiones; NO desactivar nada |
| **WP-MKT-005B** | Baseline medible: 24h o ventana disponible sin costes LLM | P50/P95 latency, llamadas por símbolo/timeframe, bytes/IO, coste de red, CPU/disco, gaps, decisiones reales, uso de snapshots y salud; si no hay 24h => periodo exacto + COVERAGE_UNKNOWN |
| **WP-MKT-005C** | Watermarks y delta-reader prototipo | read-only bootstrap+delta, idempotencia, reanudación, expected/observed, corrections and run_id; test RED→GREEN contra el mismo provider adapter |
| **WP-MKT-005D** | `MarketSnapshot` y puente al runtime | source/time/hash/state y gate fail-closed; demostrar consumer reachability `PAPER/SHADOW` con RiskManager intacto, no estrategia nueva admitida sin OOS |
| **WP-MKT-005E** | Event-driven AI gate **OFFLINE** | triggers, debounce, quota/cost-per-attempt, mock adapters, no recibo falso, presupuesto=0/clave ausente -> 0 LLM requests |
| **WP-MKT-005F** | Simulación comparable y decisión sobre redundancias | Matriz `KEEP/OPTIMIZE/MERGE/DISABLE_CANDIDATE/REJECT`; baselines mismo mercado y eventos; instrumentación sin modificar Task Scheduler |
| **WP-MKT-005G** | Verificación independiente + pruebas adversariales | mutaciones de `since`, future HTF, stale/gaps, duplicate scheduler execution, disk-full, burst 429, timestamps, missing model receipt; `TEST_TARGET == RUNTIME_TARGET` |
| **WP-MKT-005H** | Activación opcional de una sola vía `PAPER/SHADOW` | solo tras equivalencia + autorización de modificación de tarea Windows; rollback en un comando; nunca LIVE |

**Orden:** A→B→C→D→E→F→G. La auditoría C–F puede desarrollarse offline sin gasto ni privilegios. H es un gate operativo, NO una tarea que se ejecute automáticamente.

## 6. Inventario de tareas: clasificación exigida antes de retirar descargas

| Tipo descubierto | Default / decisión | Qué verificar |
|---|---|---|
| Lecturas de warm-up `real_market_context` | **KEEP_BOOTSTRAP, OPTIMIZE_REUSE** | Una lectura inicial y futuras lecturas delta; dataset y calidad equivalentes. |
| Lecturas regulares para scanner/PAPER canónico | **KEEP_CRITICAL** | Runtime consumers; sin datos nuevos no puede analizar ni decidir. |
| CAP004 campaign supervisor, si está instalado | **PRESERVE CAMPAIGN** | Ownership, run_id, LEASE, due slot, modo no-live, evidencia original. No modificar sin autorización. |
| EDGE/OOS append-only | **PRESERVE EVIDENCE** | Verificar consumidor y si necesita planificador; no borrar historial congelado. |
| Forward WebSocket research | **RESEARCH_ONLY / EVALUATE** | No alcanzable desde trading; no declarar sustituto de data plane PAPER. |
| Historias repetidas por tests/manuales | **OPTIMIZE/DEDUP** si prueban mismo universo/snapshot | Evitar 1000x cada 15min sin prueba de consumidor; conservar un único dueño. |
| Task Scheduler y Freebuff shells | **SEPARATE ORIGINS** | Proceso/horario/run_id y ventana; no atribuir descarga a `bun.exe` solo por la ventana. |

## 7. Definition of Done / pruebas adversariales

### MUST-PASS

- ACC-01: mapa de procesos real desde Windows: PID, PPID, exe, subsistema PE, command_line redactada, tarea/acción, `run_id` / `req_id`, caller stack si es seguro. Si el evento ya terminó: `NOT_ATTRIBUTABLE`, no hipótesis como prueba.
- ACC-02: inventario de entrypoints/schedulers y consumers por clasificación runtime; los fetches 1000/500/500 correlacionados con `real_market_context` por stack/llamada y no solo por números.
- ACC-03: tabla de baseline y resultados de **mismo activo/timeframe/ventana** con reducción medida de requests/bytes sin pérdida de información; si no mejora -> `NO_DEPLOY`.
- ACC-04: delta con idempotencia/restart y persistencia, 0 lookahead, 0 HTF future, gap/duplicate/correction explicitados.
- ACC-05: `NO_TRADE/NO_ANALYSIS` por stale, incomplete, missing quote, proveedor caído o quota, manteniendo datos originales y sin exit-0 falso.
- ACC-06: trigger de IA **no** es `cada consulta REST`: unique CLOSED_BAR/event con debounce y model cost receipt; `MISSING_CREDENTIAL`/budget0 -> 0 llamadas.
- ACC-07: PAPER/SHADOW canónicos alcanzables con snapshot correcto, estrategia admission `NO_ADMITTED_STRATEGY` no se salta; bot visual separado continúa sólo si su propio risk y PIT pasan.
- ACC-08: prueba offline de Freebuff cerrado: pipeline READONLY→SHADOW funciona igual, sin ejecutar API LLM; no dependencia GUI.
- ACC-09: hereda windowless helper para hijos Windows; conserva stdout/stderr/exit/PID; no afirmar 0 ventanas Freebuff si falta prueba visual; proceso propietario demostrado.
- ACC-10: no nueva tarea scheduler ni apagado de una existente sin autorización; informe delta de tareas preparado y rollback testado sin afectar host.
- ACC-11: no guardar datos sensibles ni claves en logs; HTTPS, proveedor público read-only, rate-limits, backoff, disco con reserva vigente.
- ACC-12: ninguna modificación en `config/risk.yaml`, stop/TP, leverage, live, weekend, admission ni `PaperBroker` sin un RFC/permiso separado.
- ACC-13: builder != verifier, tests RED→GREEN y mutantes válidos, PASS solo runtime ejecutado, ejecución en commit/publicación, artefactos hash y reportes JSON+MD.
- ACC-14: controles comparativos CURRENT vs PROPOSED y rollback; 0 falsas operaciones con datos inventados. LLM real aún `false` sin clave y autorización.
- ACC-15: no abrir raw WebSocket 1m/depth indefinido en disco al 99%; medir disco primero, mantener reserva y cuotas.
- ACC-16: los tres orígenes posibles de la ventana/descarga distinguidos: Freebuff subprocess, tareas CAP004 si existe, y procesos manuales/otros; resultado `NOT_OBSERVABLE` si no reproducible.

### Mutation suite sugerida

Falsificar `bar.is_final`; mover respuesta antes de la vela; destruir `watermark`; simular dos ejecuciones de Task Scheduler; duplicar vela; snapshot de 4h sin cerrar; dato viejo marcado fresh; devolver un `fetch_ohlcv_ok` sin datos; cache con `age=0` tratado como default; crear `request_id` de modelo falso; contador de requests duplicado; retorno `exit=0` con `NOT_EXECUTED`; riesgo sin sync; ledger hash manipulado; watch Windows con PowerShell oculto que pierde stderr; cerrar colecciones ajenas.

## 8. Observabilidad y métricas comparables

Para cada ejecución: `run_id`, `commit`, provider, exchange market, symbols/timeframes, `trigger`, source, `origin_pid/task`, data_event, request_id, source_hash, received/closed_at, `used_by`, model_receipt(real/mock), decision, risk, fill, PnL neto y latencia, disk read/write bytes, request counts.

Un resultado A/B favorable requiere mismos datos, activos, intervalo, ventanas OOS, costes/risk, cadencia y precios. Desplegar collector más eficiente **no** prueba rentabilidad; reduce costes/errores. Operativa rentable necesita evidencia prospectiva de modelo auténtico y ventaja neta demostrada con gates.

## 9. Fallos, seguridad, rollback

- Disk guard y cuotas existentes son autoritativas; corte por espacio bajo, no eliminar raw evidence. Reutilizar datos; mantener SHA y `source_registry`.
- Single-owner lease con TTL, process exit y journal; no doble Task Scheduler paralelo; fallo de proveedor -> backoff, no data -> `DATA_UNAVAILABLE`, sin `NO_SIGNAL` engañoso.
- WebSocket desconectado: reconstruir continuidad de datos finalizados mediante REST de fuente válida; time de recepción distingue backfill, jamás operar retrospectivo como live.
- Nuevas credenciales solo en variables de entorno/secret store, accesos read-only de exchange públicos, logs redactados. Modelo cloud requiere autorización explícita de API/coste por límites del usuario.
- Rollback seguro: feature flag para usar consumidor antiguo, dedupe watermark y conservación del último snapshot certificado; H se activa manualmente con checkpoint después del rollback ensayado; sin modificar scheduler por defecto.

## 10. Entregables mínimos

`docs/runtime/RUNTIME_FETCH_AUTHORITY_MAP.md`  
`reports/market-data/RFC-TAP-MARKET-005/FETCH_PROCESS_TRACE.jsonl`  
`reports/market-data/RFC-TAP-MARKET-005/SCHEDULER_INVENTORY.json`  
`reports/market-data/RFC-TAP-MARKET-005/CURRENT_VS_PROPOSED.json`  
`reports/market-data/RFC-TAP-MARKET-005/COVERAGE_LEDGER.jsonl`  
`reports/market-data/RFC-TAP-MARKET-005/AI_TRIGGER_LEDGER.jsonl`  
`reports/market-data/RFC-TAP-MARKET-005/INDEPENDENT_VERIFICATION.json`  
`reports/market-data/RFC-TAP-MARKET-005/RUN_REPORT.json/.md`  
`reports/market-data/RFC-TAP-MARKET-005/FINAL_REPORT.md`  
`docs/rfc/RFC-TAP-MARKET-005.md` / roadmap actualizado.

## 11. Criterios de cierre

**DONE para ingeniería offline:** A–G con pruebas, tracing, impacto medido y sin modificar tareas reales.  
**READY_TO_ACTIVATE (no ACTIVATED):** H solo cuando schedule/consumer/rollback probados y modificación autorizada.  
**PROSPECTIVE_AI_PAPER:** solo cuando haya verdadero proveedor, datos frescos, decisiones post-recepción, estrategia aprobada, reconciliación y verificación separada.  
**PRODUCTION_READY:** NO declarar con los resultados actuales. El motor de riesgo puede rechazar propuestas; 0 operaciones es perfectamente correcto si no hay evidencia o permisos.
