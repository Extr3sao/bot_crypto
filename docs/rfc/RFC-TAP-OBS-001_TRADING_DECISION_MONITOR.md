# RFC-TAP-OBS-001 — Trading Decision Monitor + REA Evidence Workflows

**Proyecto:** Trading Agentic Portable  
**Estado:** PROPOSED — pendiente de auditoría del runtime y verificación de interfaces reales  
**Prioridad:** P1, con *slice* P0 de trazabilidad mínima si el runtime carece de ella  
**Fecha:** 2026-10-24  
**Ámbito:** Observabilidad de decisiones en PAPER/SHADOW, sin modificar reglas ni activar LIVE  
**Responsables lógicos:** Runtime owner (Builder), Frontend/Observability (Builder), Independent Verifier (distinto del Builder)

> **No es una certificación del repositorio.** Los documentos de arquitectura aportados describen objetivos y gaps; no acreditan que los event hooks, endpoints, frontend, REA MCP o runtime requerido existan ya en la instalación actual. Codex debe resolverlo mediante ejecución local y evidencia, sin inventar interfaces.

## 1. Contexto, problema y decisión

### Problema

El sistema puede generar señales, propuestas, rechazos y decisiones, pero no existe una vista demostrada que permita observar sobre el precio del activo qué ocurrió, cuándo y con qué motivo. Sin esa trazabilidad visual es difícil distinguir: (a) no hay señales, (b) hay señales pero NO_TRADE, (c) hay veto de riesgo, (d) hubo autorización, pero no ejecución, (e) hubo orden paper y fallo posterior, y (f) los datos están atrasados.

### Decisión propuesta

Construir **Trading Decision Monitor (TDM)** como **proyección de solo lectura sobre el runtime autoritativo**, no como un nuevo decision engine. Incluye gráfico de velas con marcadores, timeline textual, panel de detalle enlazado a `DecisionTrace` y reproducción histórica. La UI refleja eventos originales y evidencias; no inventa decisiones ni calcula permisos para operar.

**Beneficio medible:** cualquier decisión observada debe poder enlazarse a una traza de runtime y su evidencia, y cualquier decisión de runtime relevante debe aparecer en el monitor o quedar marcada como lag/error observable.

### Separación de planos

- `TRADING RUNTIME`: market data, estrategias, proposals, independent verification, Risk Engine, ejecución y reconciliación, todos autoritativos.
- `OBSERVABILITY PROJECTION`: lector de eventos persistidos + API de consulta/stream + gráfico + explicación breve.
- `REA INVESTIGATION WORKFLOW`: herramienta externa de Codex para descubrir, contrastar y verificar interfaces existentes; **no** participa en decisiones ni arranque operacional del bot.

## 2. Autoridad y no objetivos

**Autoridad de datos:** `REAL_RUNTIME > EXECUTION_EVIDENCE > TESTS > SOURCE_CODE > ARCH/RFC > EXTERNAL_SOURCE > ASSUMPTION`.

**No objetivos:**

1. Crear estrategias, cambiar señales o aflojar Risk Engine para generar más marcadores.
2. Habilitar LIVE, enviar órdenes desde el gráfico o permitir interacción con capital.
3. Usar REA en cada tick o como dependencia de producción.
4. Clonar TradingView o analizar componentes cerrados de terceros sin autorización; usar únicamente API y licencia de Lightweight Charts.
5. Reescribir frontend/backend y event bus si existe uno compatible.
6. Escribir explicaciones mediante LLM si la evidencia real no las sustenta. El texto determinista es el comportamiento por defecto.
7. Declarar que el monitor está en tiempo real cuando reproduce fixtures/históricos o la conexión está desconectada.

## 3. Preflight obligatorio: REA + auditoría de runtime

**No implementar nada antes de esta fase.** Generar `reports/trading-decision-monitor/preflight/`.

### 3.1 Confirmar objetivo autoritativo

- Identificar `git remote -v`, commit, rama, árbol limpio/sucio y `AGENTS.md`/reglas del repositorio real.
- Localizar entrypoints y llamadas **alcanzables en runtime** de market data, OHLCV, strategies, strategy router, trade proposal, decision engine, verifier, risk, paper execution, ledger/reconciliation, events, db, API/UI y tests.
- Clasificar cada pieza `RUNTIME_AUTHORITATIVE / RUNTIME_REACHABLE / TEST_ONLY / RESEARCH_ONLY / EXPERIMENTAL / LEGACY / ORPHAN / DEAD_CODE`.
- Construir `runtime_authority_map.md` con flechas de llamadas y pruebas de alcanzabilidad; no inferir la autoridad porque una clase o archivo se llame `RiskEngine`.
- Tomar baseline PAPER sin cambios: una ejecución reproducible con eventos/ausencias, test target y entorno reales. Documentar fuente de velas y event timestamps.

### 3.2 Utilizar el MCP REA conectado a Codex

REA oficial: `morluto/rea`, servidor npm `rea-agents` registrado mediante MCP. No hay conexión al MCP local del usuario disponible en esta conversación; la ejecución de REA corresponde a Codex en el PC/entorno donde se ejecuta Trading Agentic Portable.

Secuencia de verificación:

1. Ejecutar `rea doctor --json`, `rea capabilities --json` y confirmar en la sesión de Codex `tools/list` del servidor `rea`. Registrar CLI/servidor/skill versión, estado y capabilities **realmente anunciadas**. No asumir que una herramienta existe por aparecer en otra versión de la documentación.
2. Si Codex no ve REA, registrar `REA_MCP_UNAVAILABLE` y las causas. No falsear salidas ni instalar/actualizar silenciosamente; documentar registro MCP exacto y solicitar la acción de configuración que necesite aprobación. Mientras tanto, continuar auditoría tradicional **etiquetada `REA_NOT_PERFORMED`**, sin cerrar los criterios de aceptación de REA.
3. Emplear selectivamente las herramientas REA anunciadas cuando su tipo de entrada encaje con el objetivo. Usar nombres exactos descubiertos, no fabricados.
4. Exportar Evidence canónica y crear un `rea_evidence_manifest.json` con IDs de evidencia, hash, destino, cobertura, incertidumbres y enlace a claim/test. Interpretar `normalized_result`, `evidence_id`, limitaciones y unknowns; **no transformar una inferencia en hecho observado**.
5. Proteger secretos/tokens/credenciales: usar navegador y datos sintéticos PAPER; redactar HAR y cabeceras antes de archivar; no introducir claves en prompts/evidencias.

### 3.3 Matriz de funciones REA según aplicabilidad

| Función/capacidad REA | Uso en este proyecto | Condición de uso | Evidencia a entregar |
|---|---|---|---|
| `doctor`, `capabilities`, descubrimiento MCP | Comprobar conexión, providers y versiones | Siempre | `rea_doctor.json`, `rea_catalog.md` |
| `capture_browser_scenario` y proyecciones de HAR (`inspect_analysis_view`) | Registrar carga de gráfico, filtros, timeline, detalles, reconexión, requests observables | Si está expuesto y existe UI local accesible | captura, red/flujo y Evidence IDs |
| `analyze_javascript_application` | Mapear assets/bundles JS/Electron de **nuestra** UI cuando los haya | Solo si hay artefacto soportado | módulos/imports/coverage |
| `inspect_artifact` / `inventory_artifact` | Catalogar los artefactos entregables del panel, comparar huellas | Si build/artefacto compatible | manifest/cobertura/hash |
| `capture_process_scenario` | Observar arranque y ciclo de vida de la app PAPER en entorno aislado | Solo tras revisar efectos/permisos del tool y comandos seguros | salida, efectos, cleanup, limitaciones |
| `inspect_analysis_view` / Evidence export-import / compare | Leer facets, conservar resultados íntegros, comparar baseline frente a propuesta | Si existe la función en esa versión | bundle y comparación |
| Unknowns/obligation ledger (si se anuncia) | Registrar rutas sin demostrar, eventos no observados, gaps y sus revisiones | Si está disponible | registro de unknowns y resolución |
| Ingeniería inversa nativa (`open_binary`, Ghidra/IDA/Hopper) | **No procede normalmente** para runtime Python y UI propia | Únicamente un binario relevante y consentimiento/permisos | justificación, alcance y Evidence |
| Análisis Android/.NET/firmware/EVM | **Fuera de alcance** | Solo nuevo gap demostrado y RFC posterior | `NOT_APPLICABLE` |

**Regla:** utilizar toda la **superficie aplicable** de REA, no invocar funcionalidades decompiladoras, extracción o manipulación ajenas al problema. REA complementa la inspección del código Python, sus tests y la validación de ejecución real, no los sustituye.

**Resultados mínimos de la auditoría:** `runtime_authority_map.md`, `baseline_report.md`, `rea_capability_matrix.md`, `source_registry.md`, `gap_matrix.md` y `RUN_REPORT.json`. Sin esta evidencia el siguiente WP queda `BLOCKED_AUDIT`, nunca `PASS`.

## 4. Arquitectura objetivo y flujo de eventos

```text
Market Data / Candle Stream ───────────────> Candle Read Model ──┐
                                                                  │
Strategy → TradeProposal → Critic/Decision → Verifier → Risk ────┤
                                        │                         │
                                        └──> immutable events     │
Execution PAPER → Order Ack/Fill/Reject → Reconciliation ────────┤
                    │                                             │
                    └──> append-only Decision/Execution Store ───┼─> Query API + SSE/WS
                                                                  │            │
                                                     TDM (read only) <─────────┘
                                                      ├─ candles + indicators
                                                      ├─ decision markers
                                                      ├─ event timeline + reasons
                                                      └─ DecisionTrace/replay details

Codex + REA MCP: auditar interfaces de estos componentes y comprobar la UI;
no conectar REA al camino de mercado, riesgo o ejecución.
```

### 4.1 Fuente de datos y comunicación

- **Fuente de verdad:** ledger/event store ya existente si soporta lecturas por `run_id`/`decision_id` + `asset/timeframe` y orden estable. No construir un segundo ledger sin demostrar que falta.
- Reutilizar market data existente. Cada vela declara exchange/venue, símbolo normalizado, timeframe, `bar_open_time`, `bar_close_time`, `is_closed`, fuente y `ingested_at`. Describir claramente vela en formación.
- Para simplicidad y seguridad, **preferir HTTP REST + SSE** para un panel exclusivamente lector. **Reutilizar WebSocket** si el runtime ya dispone de una infraestructura válida; decisión final tras preflight y coste demostrado. Snapshot inicial REST + cursor de stream, sin hueco entre ambos.
- Toda conexión tiene `run_id`, `mode` (`PAPER|SHADOW|REPLAY`), `as_of`, heartbeat, `last_sequence`, `data_age_ms`, `connection_state`.
- Estado UI: `LIVE_DATA`, `DELAYED`, `DISCONNECTED`, `REPLAY` y `SIMULATED_FIXTURE` (para pruebas visuales). No usar verde/“en vivo” si no está demostrado.
- Tráfico read-only sin autenticación de órdenes; autorización propia de consultas según mecanismo actual, sin exponer secretos.

### 4.2 Contratos propuestos (adaptar a contratos actuales, no imponer duplicados)

**A. Evento normalizado `TradingDecisionEventV1`:**

```json
{
  "schema_version": "1.0",
  "event_id": "uuid",
  "run_id": "run-20261024-001",
  "sequence": 184,
  "decision_id": "dec-0024",
  "proposal_id": "prop-0024",
  "order_id": null,
  "symbol": "BTC/USDT",
  "venue": "BINANCE_SPOT",
  "timeframe": "5m",
  "strategy_id": "strategy-from-registry",
  "mode": "PAPER",
  "event_type": "DECISION_REJECTED",
  "decision_status": "NO_TRADE",
  "signal_direction": "LONG",
  "reason_codes": ["RISK_VOLATILITY_LIMIT"],
  "reason_summary": "Rechazada: la volatilidad supera el límite configurado.",
  "observed_market_time": "2026-10-24T08:40:00Z",
  "decision_time": "2026-10-24T08:40:02Z",
  "emitted_at": "2026-10-24T08:40:02.200Z",
  "evidence_refs": ["evidence://runs/run-20261024-001/dec-0024"],
  "verification": "PASS",
  "risk_gate": "VETO",
  "confidence": null,
  "source_component": "risk_engine",
  "source_commit": "<actual-git-sha>"
}
```

Este JSON es un **contrato de diseño, no una muestra de ejecución real**. Campos de riesgo/estrategia se rellenan a partir de las salidas existentes; si no existen, `null` o `UNKNOWN` más una incidencia, nunca contenido supuesto. No se almacenan instrucciones de LLM privadas ni credenciales.

**B. Catálogo de estados:**

| Clase de evento | Texto en UI | Marcador | Condición necesaria |
|---|---|---|---|
| `SIGNAL_DETECTED` | Señal detectada | neutro | estrategia evaluada y evidencia |
| `PROPOSAL_CREATED` | Propuesta creada | neutro | proposal ID |
| `UNDER_REVIEW` | En evaluación | amarillo | transición emitida realmente |
| `DECISION_REJECTED` | Rechazada / NO_TRADE | rojo | decisión de rechazo atribuida |
| `DECISION_ACCEPTED` | Aceptada para ejecución | verde | verifier + risk gates PASS y decisión final |
| `ORDER_SUBMITTED` | Orden enviada a PAPER | azul tenue | orden real enviada al ejecutor paper |
| `ORDER_FILLED` | Ejecutada PAPER | azul intenso | confirmación paper y registro reconciliable |
| `ORDER_REJECTED` | Orden fallida/rechazada | rojo contorno | resultado del ejecutor |
| `POSITION_CLOSED` | Posición cerrada | azul / salida | cierre y reconciliation probados |
| `SYSTEM_DATA_STALE` / `PIPELINE_ERROR` | Datos atrasados / error de sistema | alerta de sistema, no trade | evento de diagnóstico |

Prohibido: inferir `ORDER_FILLED` desde `DECISION_ACCEPTED`; colocar marcador si no hay decisión; transformar silencio de estrategia en `DECISION_REJECTED`; confundir una `confidence` con probabilidad estadística de beneficio.

**C. Proyección de motivos:** `reason_code`, `short_text` (máx. 160 caracteres como objetivo UX), `component`, `severity`, `measured_value`, `threshold`, `unit`, `evidence_ref` y `explanation_version`. Valores/límites solo si registrados por el componente autoritativo. Registrar también `counter_evidence`, agente(s) que discreparon y motivos de rechazo cuando existan en la traza.

**D. API candidata** (solo implementar rutas equivalentes cuando no existan ya):

```text
GET /api/monitor/health
GET /api/monitor/assets
GET /api/monitor/candles?symbol=...&timeframe=...&from=...&to=...
GET /api/monitor/decisions?run_id=...&symbol=...&status=...&cursor=...&limit=...
GET /api/monitor/decisions/{decision_id}
GET /api/monitor/runs/{run_id}/trace
GET /api/monitor/events/stream?run_id=...&cursor=...   # SSE, o WS existente
```

El backend valida allowlist/entitlements, timeframes y límites de paginación, hace rate-limit, devuelve UTC ISO 8601, cursor estable, `ETag` o versión cuando proceda y read-only enforced. Event store con índice por `run_id, sequence` y por `venue, symbol, timeframe, decision_time` solo si mediciones avalan necesidad.

### 4.3 Orden, idempotencia, temporalidad

- `event_id` único y deduplicado. `sequence` monotónica **por run/stream**; `emitted_at` no sirve como único criterio de orden.
- Reconnect con `Last-Event-ID`/cursor, entrega *at least once*, dedupe, gap detection, backfill y límite de retención declarado; al perder tramo irrecuperable, UI `INCOMPLETE_HISTORY`.
- UI agrupa múltiples decisiones dentro de una misma vela sin ocultarlas (badge de cantidad + lista al pulsar).
- Etiquetas visuales ancladas a `decision_time`, no falsear que la decisión ocurrió al cierre de una vela si fue posterior.
- Invariante PIT: `observed_market_time <= decision_time`. Para marcos HTF, **prohibido** utilizar cierre futuro como dato disponible. Si timestamp imposible: `INVALID_TEMPORAL_EVIDENCE`, bloquea marcador de aceptación y produce alerta.
- Aceptar datos fuera de orden dentro de política documentada; no retroescribir eventos inmutables: emitir correcciones/reconciliaciones enlazadas.
- En caso de fallo parcial del sistema de observabilidad, no perturbar el trade loop: bounded queues, backpressure, métricas de dropped/disconnected, almacenamiento durable de eventos esenciales, fail-closed para afirmaciones de completitud del monitor.

## 5. UX y experiencia de usuario

**Vista principal:**

1. Cabecera: estado PAPER/SHADOW/REPLAY explícito; estado conexión y frescura; fecha/hora UTC y zona local seleccionable.
2. Filtros: activo, venue, timeframe, estrategia, estado, `run_id`, intervalo. Por defecto solo activos/estrategias realmente disponibles.
3. Gráfico candlestick Lightweight Charts: velas, volumen opcional, marcadores BUY/SELL/NO_TRADE/fill/close, bandas SL/TP **solo cuando hay valores reales validados**. Zoom, crosshair, leyenda y navegación histórica.
4. Bajo gráfico: **timeline conciso** con fecha, estado, motivo principal, strategy/risk/verifier y precio si fue observado.
5. Al pulsar un marcador: panel `DecisionTrace` completo con proposal → evidence → agents/critique → decision → independent verifier → deterministic risk → paper execution → reconciliation. Elementos faltantes = `NOT_RECORDED`, nunca inventados.
6. Vista `NO SIGNAL / NO EVALUATION`: mostrar contadores separados de velas recibidas, estrategias evaluadas, señales, propuestas, aceptaciones, rechazos, órdenes presentadas, fills; si no hay eventos, decir exactamente cuál es el último paso observable.
7. Replay: seleccionar `run_id`, filtrar y avanzar con reloj de eventos sin reejecutar el motor ni volver a enviar órdenes.

**Semántica visual:** color + icono + texto (accesibilidad); evitar que un fill tenga la misma forma que una aceptación. Tooltip breve y panel ampliado. Layout responsive. Nada se representa como live si proviene de fixtures. Etiquetas: `ACEPTADA (NO EJECUTADA)`, `EJECUTADA PAPER`, etc.

**Biblioteca:** TradingView Lightweight Charts 5.x o versión compatible comprobada. Usar API pública de `createChart`, candlestick series, `update` incremental y markers según la versión fijada en lockfile. Respetar licencia Apache-2.0 y atribución TradingView exigida por su documentación.

## 6. Requisitos (REQ) y criterios de aceptación (ACC)

| ID | Requisito | Aceptación comprobable |
|---|---|---|
| REQ-TDM-001 | Observabilidad no intrusiva | Con monitor activo/inactivo, misma decisión, señal, riesgo, fill y PnL en replay determinista; diferencia de eventos del motor = 0 |
| REQ-TDM-002 | Procedencia de cada marcador | 100% de marcadores visibles vinculados a `event_id`, `run_id`, `decision_id` y source/evidence verificable; si falta, estado UNKNOWN y no aceptación |
| REQ-TDM-003 | Distinción de estados | 0 casos de `DECISION_ACCEPTED` representado como fill; pruebas positivas/negativas por estado |
| REQ-TDM-004 | Consistencia de timeline/chart | Eventos del rango cargado = eventos de consulta, salvo filtros explícitos y alertas de gap; agrupaciones sin pérdida |
| REQ-TDM-005 | Fuente de velas + PIT | Velas alineadas a venue/timeframe y `market_time <= decision_time`; rechazo de 4 familias de timestamps futuros |
| REQ-TDM-006 | Frescura, lag y reconexión | Test caída/reconnect sin duplicados; gap detectado/backfill; lag alto muestra DELAYED y nunca LIVE |
| REQ-TDM-007 | Lectura histórica | Replay de run congelado produce misma secuencia, motivos y posiciones visuales |
| REQ-TDM-008 | Motivos atribuibles | Para cada rechazo hay `reason_codes`, origen y Evidence; sin evidencia ⇒ `REASON_UNAVAILABLE`, no explicación especulativa |
| REQ-TDM-009 | Seguridad | Read-only API; ningún endpoint/UI permite mutar límites, credenciales, estrategias ni enviar órdenes |
| REQ-TDM-010 | REA | `doctor` + tools discovery, al menos una inspección **aplicable** y una validación del comportamiento UI respaldadas por Evidence; si no aplicable, declaración razonada, nunca `PASS` ficticio |
| REQ-TDM-011 | Ejecución PAPER | Prueba E2E con runtime PAPER real (no solo mocks): señal rechazada, señal aprobada sin fill, orden paper confirmada, error y reconnect con pruebas a su nivel |
| REQ-TDM-012 | Verificación independiente | Builder distinto de Verifier; verifier coteja event store vs UI/trace y genera informe separado |
| REQ-TDM-013 | Métricas observabilidad | Métricas de stream delay, event ingestion lag, duplicated/gapped events, rejected reasons y render latency medibles desde un test local |
| REQ-TDM-014 | Compatibilidad | Sin nueva tecnología de orquestación si la infraestructura actual sirve; tests existentes pasan, rollback simple y no ruptura de API |

**Objetivos iniciales de rendimiento (no certificados, validar con baseline):** eventos UI visibles en ≤2 s p95 desde `emitted_at` para PAPER local sano; load/replay 2.000 marcadores sin bloqueo evidente de UI; consumo incremental medido vs baseline. En lugar de declarar PASS si no se alcanza, registrar desviación y evidencia real.

## 7. Pruebas: adversariales y de aceptación

**Unit/contract:** serialización v1, estados válidos/inválidos, razones sin umbral conocido, timezone, UTC, orden monotónico, dedupe, validación de inputs, marcadores múltiples por vela, textos accesibles.

**Integración:** el origen del evento es exclusivamente el runtime alcanzable; snapshot + cursor + stream no dejan ventana ciega; reconnect con pérdida/hueco; SSE no admite comandos; no cambia señales ni sizing.

**Runtime PAPER real:** 1) ninguna señal; 2) señal + veto; 3) propuesta criticada + NO_TRADE; 4) aceptación sin orden; 5) orden enviada pero no fill; 6) fill confirmado; 7) reconciliation; 8) market data stale; 9) provider caído; 10) `run_id` y filtros de varios activos/estrategias.

**PIT/adversarial:** look-ahead HTF; timestamp fabricado; llega fill antes que acceptance por jitter de red; duplicate `event_id`; evento con ID inválido; Evidence inexistente; evento con datos secretos; caída DB/stream; dependencia REA no disponible; UI conectada con data stale; cambio de run entre filtros; total market/decision discrepancy.

**Visual/E2E:** probar gráfico, filtros, timeline, drilldown, zoom y replay con Playwright u otra suite ya presente. Si REA `capture_browser_scenario` está disponible, capturar escenarios de la UI local y comparar Evidence before/after; ninguna captura sustituye a los asserts.

**Independencia:** Verifier distinto del implementador compara un muestreo completo y aleatorio estratificado por tipo de evento contra ledger/traces y verifica `FALSE_SUCCESS=0` en la suite; ausencia de Evidence ⇒ FAIL/INCOMPLETE.

## 8. Work Packages (WP), orden y puertas de salida

| WP | Alcance cerrado | Entregable | Gate |
|---|---|---|---|
| WP-TDM-00 | Read-only preflight y REA discovery, baseline runtime | mapas, catalog, gap y reporte preflight | no implementación sin alcance real |
| WP-TDM-01 | Modelo normalizado y proyector de eventos **sin cambios de decisión** | contrato v1, adapters, event tests | igualdad con eventos runtime |
| WP-TDM-02 | REST histórico + stream read-only incremental | APIs, dedupe/cursor, observabilidad | reconnect/gaps/PIT PASS |
| WP-TDM-03 | UI candlestick + timeline y filtros | panel propio con marcadores y estados explícitos | E2E visual y sin falsos fills |
| WP-TDM-04 | Drilldown DecisionTrace + replay | navegación run/decision/evidence | reconstrucción determinista |
| WP-TDM-05 | REA scenario verification, performance, independent verification | pruebas runtime PAPER, artifacts REA, `FINAL_REPORT` | gate independiente, sin LIVE |

La entrega debe ser incremental, con un único objetivo por WP. No ampliar el alcance cuando se detecten gaps ajenos; registrarlos con decisión `DEFER` y un WP separado solo si bloquean requisitos críticos.

## 9. Registro de evidencias, artefactos y fuentes

**Rutas recomendadas bajo repositorio real** (ajustables a convenciones actuales):

```text
docs/rfc/RFC-TAP-OBS-001_TRADING_DECISION_MONITOR.md
reports/trading-decision-monitor/
  preflight/runtime_authority_map.md
  preflight/rea_doctor.json
  preflight/rea_catalog.md
  preflight/rea_capability_matrix.md
  preflight/baseline_report.md
  preflight/source_registry.md
  preflight/gap_matrix.md
  preflight/RUN_REPORT.json
  WP-TDM-01/{RUN_REPORT.md,RUN_REPORT.json,...}
  WP-TDM-02/{RUN_REPORT.md,RUN_REPORT.json,...}
  WP-TDM-03/{RUN_REPORT.md,RUN_REPORT.json,...}
  WP-TDM-04/{RUN_REPORT.md,RUN_REPORT.json,...}
  WP-TDM-05/{RUN_REPORT.md,RUN_REPORT.json,rea_evidence_manifest.json,rea_evidence_bundle.json,...}
  FINAL_REPORT.md
```

Cada `RUN_REPORT.json`: `run_id`, commit, environment, mode, source of candles, strategy/agent IDs, REQ/ACC covered, test target, commands/results, event counts, risk/veto counts, paper_order_count, latency, defects, unknowns, evidence_refs, `false_success`, `status`.

**Fuentes de diseño, diferenciadas de evidencias de ejecución:**

| SOURCE_ID | Tipo | Fuente | Qué soporta |
|---|---|---|---|
| TAP-ARCH-001 | Documento aportado | `10_TRADING_AGENTIC_VNEXT_ARCHITECTURE.md` | capas deterministas, decisión, observabilidad |
| TAP-GOV-001 | Documento aportado | `07_VERIFICATION_AND_GOVERNANCE.md` | builder≠verifier, event trace, evidence |
| TAP-DEC-001 | Documento aportado | `05_DECISION_SYSTEMS.md` | rechazo/decisión/risk veto explícitos |
| TAP-RFC-001 | Documento aportado | `11_PROPOSED_RFCS.md` | RFC-004, RFC-005, RFC-011 relacionados |
| TV-LWC-001 | Documentación oficial | https://tradingview.github.io/lightweight-charts/docs | velas, update incremental, licencia/atribución |
| REA-UP-001 | Repositorio oficial | https://github.com/morluto/rea | propósito y alcance de REA |
| REA-INS-001 | Documentación oficial | https://github.com/morluto/rea/blob/main/docs/installation.md | `doctor`, MCP y setup específico |
| REA-MCP-001 | Documentación oficial | https://github.com/morluto/rea/blob/main/docs/mcp-contracts.md | schema descubierto, `evidence_id`, retained Evidence, límites |

Registrar commit/version exactos de las fuentes externas consultadas en la ejecución de Codex. **Ninguna fuente conceptual sustituye `RUN_REPORT` de runtime real.**

## 10. Seguridad, fallos, rollbacks y decisión de promoción

- **PAPER-only** por defecto. `LIVE` no se habilita ni se toca. TDM carece de permisos para `PRODUCTION_ACTION`.
- Proteger logs, HAR, métricas de precios/portfolio y credenciales. Acceso local o autenticación existente; CSRF/CORS/read-only acordes a su función; CSP sin scripts remotos no autorizados.
- Rechazar objetos con payload enorme, texto incrustado no confiable, HTML arbitrario o rutas de evidencia manipuladas. Motivos renderizados como texto escapado, no HTML.
- Market data/pipeline offline: mantener último estado con `DISCONNECTED`, último timestamp y sin inferir nuevos marcadores. Evitar falsos fills.
- Si el proyector cae: trading PAPER continúa según sus propias garantías; observabilidad muestra un GAP y los controles de consistencia registran pérdida/lag. Si las evidencias del monitor están incompletas, no afirmar monitor “CERTIFIED”.
- Feature flag `TRADING_DECISION_MONITOR_ENABLED=false` por defecto hasta gate de validación.
- Rollback: apagar flag y retirar reader/API/UI nuevos, conservando event store y evidencias existentes; no restaurar reglas de trading porque no se habrán tocado.
- `GO` para uso observacional PAPER solamente si REQ/ACC pasan con pruebas de runtime **y** verificador independiente. No se puede extrapolar a producción o a rentabilidad.

## 11. Instrucciones para Codex

1. Leer instrucciones del repo y este RFC. Ejecutar WP-TDM-00; usar REA desde la sesión local **si el MCP está disponible**; conservar literal herramientas anunciadas y evidencias.
2. No detenerse en preguntas de arquitectura menores: escoger las soluciones reversibles más simples y justificar por qué.
3. No implementar nada que afecte a trading decision/risk/execution. Si no existen eventos alcanzables, proponer mínimo hook no intrusivo con contratos y test, no un sistema paralelo.
4. Completar WP sucesivos solo tras gate de anterior. Si gate falla, corregir o dejar `BLOCKED` con la evidencia; nunca declarar PASS por mocks.
5. Al terminar cada WP entregar breve informe en pantalla y `RUN_REPORT.md`/`.json`; verificador separado en WP-05.
6. Cerrar con `FINAL_REPORT.md` que incluya: `PHASE / COMMITS / IMPLEMENTED / TESTS / RUNTIME_VALIDATION / PAPER_VALIDATION / FALSE_SUCCESS / DEFECTS / BLOCKERS / EVIDENCE / ARCHITECTURE_STATUS / RFC_STATUS / NEXT_PHASE`.

**Resultado solicitado:** un panel útil para saber *cuántas oportunidades hubo, dónde estaban en el precio, por qué el sistema las aceptó/rechazó y si terminaron realmente en una operación PAPER*, sustentado por runtime y trazas verificables.
