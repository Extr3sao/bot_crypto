# RFC-TA-EXP-003J-001 — Real Signal Admission & Paper Validation

- **Proyecto:** Trading Agentic Portable
- **Fecha:** 2026-10-20
- **Estado:** PROPOSED — apto para implementación segura y autónoma **después de congelar/recoger la evidencia de WP005L**; no equivale a aprobación live.
- **Tipo:** experimento controlado de runtime real + validación paper end-to-end
- **Prioridad:** P0 para pasar de infraestructura a trading medible
- **Antecedentes:** `RFC-TAP-MARKET-005/WP005L`, `RFC-AI-BOTS-003I`, `EXP-003I-THROUGHPUT-001`
- **Decisión por defecto:** `NO_CHANGE` en riesgo, posiciones, salidas, slots y producción; `live_trading_enabled=false`.
- **Autoridad:** `REAL_RUNTIME > EXECUTION_EVIDENCE > TESTS > SOURCE_CODE > ARCH/RFC > ASSUMPTION`.

## 1. CONTEXT / ESTADO DE PARTIDA

La observación `WP005L` prueba principalmente scheduling, leases e integridad, no efectividad de trading. En el informe inicial: cuatro ciclos `NOOP` con exit 0; cuatro ventanas; 1/24 horas observadas; muestreo de lease 3/4 (75 %, objetivo >=95 %); estado `NOT_YET_COMPLETE`; cierre previsto para `2026-10-21T05:15:00Z`. Se declararon `DISK_WARNING` (~4,6–4,96 GB libres) y 26 fallos heredados. No reinterpretar un `NOOP` como operación.

Según la evidencia de trabajo comunicada para `003I`: `BLOCKED / NO_CHANGE`, **0/30 cierres esperados**, 35/36 señales bloqueadas en `resolve_intent`, y el experimento `paper-script` determinista **no constituye alpha**. La estrategia `EmaCrossoverStrategy` es baseline de investigación; la evaluación comunicada dio expectativa bruta negativa en 18 celdas y win rate ~41,8–42,7 % frente a ~42,86 % de break-even asumido en esas pruebas. El control de drawdown del 5 % llegó a bloquear símbolos y gran cantidad de señales. **Son observaciones reportadas, no revalidadas aquí contra el repositorio**.

### Hipótesis de trabajo

El sistema debe demostrar que una señal originada por una estrategia realmente alcanzable en runtime, sobre datos reales con integridad temporal, puede seguir sin atajos toda la cadena hasta una decisión de `TRADE` o `NO_TRADE`, una ejecución **simulada** cuando proceda, su reconciliación y una medición económica neta; todo reproducible e independientemente verificable.

### Dependencia y aislamiento de WP005L

- **No tocar** tareas de Windows Task Scheduler, observador, leases, ventanas, hashes desplegados ni archivos de evidencia mientras WP005L continúa.
- Preparación **read-only** del RFC y del inventario: permitida sin interferencia.
- Implementación que modifique scripts/tareas/rutas usadas por WP005L: **bloqueada** hasta el cierre y la captura del veredicto independiente; preferir rama/worktree aislado aun después.
- La conclusión de WP005L debe conservarse tal cual (`PASS`, `FAIL`, `INCOMPLETE`); un eventual fallo allí no puede taparse con el éxito de 003J. Si afecta al runtime requerido, bloquear la validación operativa hasta corregirlo.

## 2. PROBLEM

Se están verificando muchos mecanismos de infraestructura sin demostrar suficiente **admisión de señales reales, trazabilidad de rechazos, trades paper observados y expectativa económica neta**. Los `NOOP`, datos sintéticos y scripts deterministas son útiles como controles, pero no certifican una estrategia. También puede existir un cuello de botella previo a Risk (`resolve_intent`): no debe resolverse quitando barreras o fabricando señales.

## 3. GOALS Y NON-GOALS

### Goals

1. Reconstruir el **runtime autoritativo** para market data → estrategia → señal → admisión → propuesta → decisión → risk → paper broker → fills → posiciones → reconciliación → métricas.
2. Hacer observable cada transición, incluidos `NO_SIGNAL`, `REJECTED`, `NO_TRADE`, `PAPER_ORDER`, `PAPER_FILL` y `CLOSED_TRADE`, sin confundir categorías.
3. Reproducir y explicar los rechazos de `003I` con códigos estables, sin cambiar automáticamente su lógica.
4. Ejecutar una campaña **OOS/replay con datos reales** y, cuando el runtime lo soporte, una campaña **paper observada en tiempo de mercado**, dejando ambas inequívocamente separadas.
5. Medir costes y resultados netos: comisiones, spread, slippage, exposición, PnL realizado/no realizado, drawdown, expectancy y cobertura.
6. Introducir verificación independiente capaz de detectar muestras adulteradas y positivos falsos.
7. Producir un dictamen separado para **funcionamiento técnico** y **viabilidad de la estrategia**.

### Non-goals

- **No** habilitar órdenes reales, credenciales de trading, leverage real ni producción.
- **No** alterar drawdown máximo, sizing, exposición, límites, slots, reglas de salida o admisión para aumentar artificialmente operaciones.
- **No** incorporar nuevas familias de alpha, agentes, frameworks, memorias ni arquitectura no exigida por un gap verificado.
- **No** etiquetar backtest, replay o ejecución sintética como `PAPER_OBSERVED`.
- **No** sustituir EMA por una estrategia supuestamente rentable sin su propia admisión/pipeline de investigación.
- **No** autorizar promoción de estrategias por cumplir una frecuencia de trades.

## 4. SOURCE / CLAIM / EVIDENCE / DECISION

| Claim | Fuente disponible | Nivel | Decisión |
|---|---|---|---|
| WP005L demuestra scheduler saludable pero aún no certifica 24 h | Informe comunicado 2026-10-20 | Reporte de ejecución, pendiente de contraste directo | Conservar `NOT_YET_COMPLETE` hasta verificar toda la cobertura |
| 003I no confirmó los 30 cierres y bloqueó 35/36 señales en `resolve_intent` | Resultado 003I comunicado | Reportado, requiere auditoría read-only | Diagnosticar admisión, no cambiar reglas por volumen |
| EMA baseline no demuestra edge positivo | Evaluación 18 celdas comunicada | Experimental reportado | Mantener `RESEARCH_ONLY`, no promocionar |
| Risk es un gate determinista | Contrato del proyecto / arquitectura VNext | Arquitectónico | Prohibir bypass; preservar límites |
| Un NOOP no equivale a rentabilidad ni a una orden | Semántica de ejecución | Contrato | Separar veredictos técnicos/financieros |

**Regla de procedencia:** no reemplazar una fuente faltante por suposición. Registrar `UNKNOWN`, `NOT_OBSERVED` o `BLOCKED` cuando no haya artefacto verificable.

## 5. ARCHITECTURE / RUNTIME FLOW

```text
REAL MARKET DATA (provider + event timestamp + provenance)
  -> Data Quality + point-in-time validation
  -> Existing Strategy Registry / Strategy Runtime (do not invent)
  -> Signal [or NO_SIGNAL]
  -> Existing resolve_intent / Admission Gate
  -> TradeProposal [or REJECTED + reason]
  -> Existing Decision/Review gate if runtime-reachable
  -> Deterministic Risk Engine [can veto]
  -> PAPER_EXECUTION_ONLY (never live)
  -> Simulated orders/fills with configured fees/slippage
  -> Portfolio & position accounting
  -> Reconciliation
  -> NET Performance + DecisionTrace + Independent Verifier
```

**Implementación mínima:** reutilizar los adaptadores autoritativos y el flujo actual. Si una capa del diagrama es conceptual/no alcanzable, documentarla en `runtime_authority_map.md`; no crear una segunda implementación para satisfacer el RFC. Todo elemento crítico debe estar **runtime-reachable**, no solo testeado en aislamiento.

### Capas y límites

- **Deterministic Runtime Plane:** calidad/tiempo de datos, indicadores, señales, `resolve_intent`, sizing/risk, paper execution, contabilidad, reconciliación y métricas.
- **Agent Intelligence Plane:** análisis, críticas y contexto, solo cuando ya sea parte del camino autoritativo. Ningún LLM puede modificar límites, capital, órdenes ni resultados contables.
- **Discovery Plane:** experimentos con estrategias y replay separados del runtime paper observado; cambios de estrategia requieren proceso propio de promoción.

## 6. DATA CONTRACTS (CANÓNICOS O ADAPTADORES)

No duplicar los modelos existentes. Implementar adaptadores solo si la auditoría demuestra que faltan campos necesarios para evidencia. Contratos lógicos mínimos:

```yaml
SignalEvent:
  run_id: string
  signal_id: string       # estable e idempotente
  asset: string
  strategy_id: string
  strategy_version: string
  timeframe: string
  market_event_time_utc: datetime
  decision_time_utc: datetime
  direction: BUY|SELL|FLAT
  source: REAL_MARKET_DATA|SYNTHETIC_TEST
  data_fingerprint: sha256
  params_fingerprint: sha256
  evidence_refs: [string]

AdmissionResult:
  run_id: string
  signal_id: string
  admission: ADMITTED|REJECTED|NO_SIGNAL|ERROR
  reason_code: string
  reason_detail: string
  policy_version: string
  evidence_refs: [string]

PaperExecutionRecord:
  run_id: string
  proposal_id: string
  decision: TRADE|NO_TRADE
  risk_result: PASS|VETO|ERROR|NOT_APPLICABLE
  order_status: NONE|SIMULATED_SUBMITTED|SIMULATED_FILLED|SIMULATED_REJECTED
  exchange_order_id: null  # no live ID
  fill_time_utc: datetime|null
  fees: decimal|null
  spread_cost: decimal|null
  slippage_cost: decimal|null
  position_id: string|null
  source_mode: PAPER_OBSERVED|REAL_DATA_REPLAY_OOS|SYNTHETIC_NEGATIVE_CONTROL
  evidence_refs: [string]

RunVerdict:
  technical: PASS|FAIL|INCOMPLETE|BLOCKED
  signal_quality: REJECT|RESEARCH_ONLY|INSUFFICIENT_EVIDENCE|CANDIDATE_FOR_FURTHER_PAPER
  observed_trades: integer
  replay_trades: integer
  synthetic_trades: integer
  false_success: integer
  live_orders: 0
```

Invariantes:

- `market_event_time_utc <= decision_time_utc`; no HTF futuro ni timestamps falsos.
- Identidad de datos/config/código/estrategia mediante hashes/commit completos.
- Idempotencia por `(run_id, signal_id, stage)`; no duplicar fills ni contabilizaciones.
- `REJECTED`/`NO_TRADE` no produce orden; fallo técnico no se convierte en `NO_TRADE` sano.
- Resultado económico **solo** de fills y cierres reconciliados; no usar señales como operaciones.
- Métricas separadas para `PAPER_OBSERVED`, `REAL_DATA_REPLAY_OOS`, `SYNTHETIC_NEGATIVE_CONTROL`.
- Costes modelados con hipótesis identificables; `UNKNOWN_COST` impide una afirmación de rentabilidad neta fiable.
- Live deshabilitado en **configuración y adaptador real**, verificado por el tester.

## 7. WORK PACKAGES (EXECUTE IN ORDER)

### WP-003J-00 — Baseline & Runtime Authority Audit

**Trabajo:** inventariar entrypoints, Task Scheduler, market feeds, símbolos, calendarios, `EmaCrossoverStrategy`, strategy/router, `resolve_intent`, risk, portfolio, execution adapters, ledger, reconciliación, tests y scripts. Localizar el camino real alcanzable y reproducir la baseline 003I sin modificarla. Identificar `RUNTIME_AUTHORITATIVE / RUNTIME_REACHABLE / TEST_ONLY / RESEARCH_ONLY / EXPERIMENTAL / LEGACY / ORPHAN / DEAD_CODE`.

**Entregables:** `runtime_authority_map.md`, `BASELINE_REPORT.md` con commit y fingerprints, tabla de fallos heredados (impacto / origen / owner lógico / gate afectado). Preservar el resultado de WP005L y anotar su relación sin sobrescribir sus artefactos.

**ACC:** cada nodo del flujo está vinculado a un archivo/función/entrypoint **real** o marcado como `NOT_IMPLEMENTED`; no se declara continuidad basada en mocks. `git status` y hashes previos capturados.

### WP-003J-01 — Provenance & Point-in-Time Data Gate

**Trabajo:** seleccionar al menos una combinación activo/timeframe realmente soportada, con datos de mercado verificables. Capturar timestamps de exchange/proveedor, zona horaria, gaps, duplicados, stale data, alineación HTF y fingerprints. Definir una partición cronológica `TRAIN/RESEARCH` y `OOS`, congelando estrategia/parámetros antes del OOS. No usar datos futuros.

**Entregables:** `DATA_MANIFEST.json`, `DATA_QUALITY_REPORT.md`, lista de particiones/periodos y checksums.

**ACC:** 100 % de eventos admitidos cumplen los controles PIT y procedencia; inyecciones de stale, future timestamp, duplicate y corrupted fingerprint resultan bloqueadas. Si falla el feed: `BLOCKED_DATA`, nunca PASS.

### WP-003J-02 — Signal Admission Trace & 003I Root Cause

**Trabajo:** instrumentar sin cambiar semántica el trayecto `strategy -> signal -> resolve_intent -> proposal/NO_TRADE`; crear un catálogo de razones de no admisión. Reproducir el 35/36 de 003I si el dataset y evidencia originales están disponibles; si no lo están, dejar `NOT_REPRODUCED` con causa, no inventar equivalencia. Resolver **defectos demostrados** con regresión y sin cambiar política de riesgo/salidas/slots; si el supuesto defecto es una decisión legítima de política, mantener `NO_CHANGE` y documentar el bloqueo.

**Entregables:** `SIGNAL_FUNNEL.json/.md`, `003I_ROOT_CAUSE.md`, trazas por signal_id.

**ACC:** 100 % de señales evaluadas tienen razón/etapa terminal, sumatorios reconciliados (`signals = admitted + rejected + error` según semántica real), sin atajos; no se maquilla `NO_SIGNAL` como fallo ni un rechazo de riesgo como fallo del router.

### WP-003J-03 — Real Signal to Paper E2E

**Trabajo:** conectar estrategia existente runtime-reachable con el paper broker real del proyecto bajo flag **apagado por defecto**, p. ej. `REAL_SIGNAL_PAPER_CAMPAIGN_ENABLED=false`, y guardias adicionales `live_trading_enabled=false`, `sandbox=true`. Ejecutar en dos pistas separadas: (A) `REAL_DATA_REPLAY_OOS`, con eventos históricos reales reproducidos causalmente, y (B) `PAPER_OBSERVED`, con data real capturada en el momento de ejecución cuando el entorno lo permita. El flujo debe registrar decisiones `NO_TRADE` y, si hay señales admitidas y risk pasa, órdenes/fills **simulados**.

**Entregables:** `DECISION_TRACE.jsonl`, `PAPER_ORDERS.jsonl`, `PAPER_FILLS.jsonl`, `PORTFOLIO_LEDGER.jsonl` y `RUN_REPORT.json/.md`. No crear archivo de órdenes si no hubo ninguna: declarar explícitamente `0` con evidencia.

**ACC técnico positivo:** al menos una trayectoria completa y natural, con datos de mercado reales y riesgo vigente, desde señal hasta paper fill y reconciliación, **sin inyección artificial**, o el resultado es `BLOCKED_NO_ADMITTED_SIGNAL`, no PASS E2E. Tests sintéticos pueden pasar para probar cableado, pero nunca sustituyen esta evidencia. Se admite un resultado `NO_TRADE` como decisión correctamente registrada, **sin** equipararlo a ejecución paper validada.

### WP-003J-04 — Net Economics & ACTIVE Frequency Evaluation

**Trabajo:** producir métricas separadas para observed/replay, por activo, régimen, estrategia, sesión y costes. Incluir fees, spread, slippage, PnL neto, drawdown, expectancy neta, profit factor (si hay pérdidas y ganancias suficientes), win rate, distribución de R, duración, turn-over, órdenes rechazadas y razones de `NO_TRADE`. Comparar con EMA baseline y un `NO_TRADE` baseline, con **mismos activos/periodo/datos/costes/restricciones**. Sensibilidades de coste y outliers, sin optimizar sobre OOS.

**Frecuencia ACTIVE:** reportar número de operaciones cerradas por día y porcentaje de días con >=3 operaciones en mercados cripto 24/7; objetivo de producto **>=3 diarias**, sin convertirlo en una cuota que permita fabricar operaciones. Informar días sin operaciones, distribución y motivos. La estrategia QUALITY conserva su perfil de menor frecuencia; no mezclar.

**Entregables:** `ECONOMICS_REPORT.md/.json`, `FREQUENCY_REPORT.md/.json`, `BASELINE_COMPARISON.md`.

**ACC:** métricas recomputables desde fills/ledger; retorno neto siempre incluye costes; muestras insuficientes se marcan `INSUFFICIENT_EVIDENCE`. Nunca declarar rentable por win rate aislado, 1–4 operaciones o una campaña `NOOP`. Para considerar **candidata** a posterior paper sostenido: muestra OOS razonable y declarada, expectancy neta positiva en evaluación robusta, incertidumbre estimada y ausencia de violaciones; sin umbral arbitrario de operaciones como garantía de beneficio.

### WP-003J-05 — Independent Verification & Adversarial Gates

**Trabajo:** verificador separado del implementador y no dependiente de banderas de éxito de los propios reports. Recomputar del ledger/hashes las cuentas de señales, rechazos, decisiones, fills, trades cerrados, costes, equity y clasificación de fuentes. Inyectar controles negativos en un directorio aislado: orden live forjada; fill duplicado; hash alterado; stale data; HTF futuro; `NOOP` etiquetado como trade; costes ausentes; leakage OOS; política risk omitida; resultado `PASS` con cero fills naturales.

**Entregables:** `INDEPENDENT_VERIFICATION.json`, `VERIFICATION_REPORT.md`, pruebas automáticas; conteo de negativos detectados y defectos sin ocultar.

**ACC:** 100 % de controles negativos especificados producen `FAIL/BLOCKED` correctos, `FALSE_SUCCESS=0` en el conjunto cubierto; el verificador no comparte ni llama a una función que autodeclare el mismo PASS. Ninguna llamada real de órdenes permitida.

### WP-003J-06 — Final Campaign Report & Next Decision

**Trabajo:** consolidar todas las ejecuciones en un `RUN_REPORT.json/.md` con `run_id`, commit, environment, provider/data fingerprints, estrategia/versión, flags, parámetros, ventanas OOS, cada transición, métricas, errores, hashes y resultado; producir `FINAL_REPORT.md`. Separar advertencias externas (disco, scheduler, 26 fallos) según su impacto; ningún `PASS` general es válido con gate crítico abierto.

**Entregables:** `FINAL_REPORT.md`, `RUN_REPORT.json`, `RUN_REPORT.md`, índice `evidence/`, `NEXT_DECISION.md`, tabla de requirements/acceptance/evidence.

**ACC:** reporte fresco, verificable, reproducible, commit incluido y evidencias completas. Dictámenes separados:

- `TECHNICAL_E2E`: `PASS / FAIL / BLOCKED / INCOMPLETE`.
- `STRATEGY_ECONOMICS`: `NEGATIVE / INSUFFICIENT_EVIDENCE / RESEARCH_CANDIDATE` (no `CERTIFIED_PROFITABLE`).
- `PAPER_OBSERVABILITY`: `OBSERVED / NOT_OBSERVED / PARTIAL`.
- `LIVE_TRADING`: siempre `NO_GO`.

## 8. TEST PLAN / MINIMUM EVIDENCE

| Suite | Qué prueba | Condición de aprobación |
|---|---|---|
| UNIT / SCHEMA | tipados, eventos, timestamps, costes, razón de rechazo | PASS sin saltos |
| CONTRACT | interfaces de `strategy -> admission -> risk -> paper` | ningún test-only sustituyendo runtime |
| INTEGRATION | idempotencia, persistencia, intent-to-fill | cuentas reconciliadas |
| PIT / ADVERSARIAL | leakage, stale, duplicados, forjas | todas detectadas |
| REAL_DATA_REPLAY_OOS | entrada de datos reales congelados y replay causal | clasificación correcta, sin leakage |
| PAPER_OBSERVED | episodios reales de mercado, sin mocks de señal | evidencia real, aunque `NO_TRADE` |
| RECONCILIATION | precios, fees, PnL, equity, drawdown | recomputación exacta dentro de tolerancia decimal definida |
| REGRESSION | 003I, risk limits, scheduler | sin debilitar comportamiento previamente válido |
| INDEPENDENT | verificación externa de resultados | no autoverificación |

**Invariante final:** `TEST_TARGET == RUNTIME_TARGET` en tests que certifican el runtime. Los tests unitarios/mocks no otorgan certificación operacional.

## 9. MEASUREMENT / DECISION POLICY

No mezclar estos cuatro conceptos:

| Concepto | Demostración exigida |
|---|---|
| Infraestructura sana | observación completa WP005L + verificación |
| Flujo paper técnicamente funcional | señal real -> admisión -> riesgo -> fill simulado -> reconciliación |
| Estrategia con señal/actividad | señales admitidas y actividad medidas, sin forzar trades |
| Rentabilidad estadísticamente defendible | OOS, costes netos, suficientes observaciones, robustez y validación independiente |

Un `PASS` técnico puede coexistir con `NEGATIVE` económico. Un `NO_TRADE` legítimo es una buena **decisión**, pero no un paper fill. Si la estrategia no produce señales, emitir `BLOCKED_NO_ADMITTED_SIGNAL`; si Risk veta, `RISK_VETO` trazado; si hay estrategia sin edge, `NEGATIVE/RESEARCH_ONLY`. Nunca promover por presión de calendario.

## 10. FAILURE MODES / SECURITY

- **Disk warning / bajo espacio:** no eliminar evidencia para liberar disco; detener campaña si existe riesgo de corrupción o almacenamiento insuficiente. Limpieza segura solo fuera de los artefactos protegidos y previa clasificación.
- **Provider failure / stale / gaps:** fail closed, reportar ausencia de datos.
- **Scheduler inestable:** no confundir fallos de adquisición/ejecución con fallos de estrategia; bloquear el modo observado si corresponde.
- **Lost lease / duplicate run:** clave idempotente y verificador independiente de contabilidad.
- **Market-hours:** en acciones respetar calendarios/feriados; no presumir 24/7 salvo en criptomercados.
- **Credentials:** no solicitar ni registrar credenciales; acceso a API pública de lectura si ya está soportado y sin coste relevante.
- **Live orders:** prohibidos; el adaptador ejecutor real no debe ser alcanzable desde el flag paper.
- **LLM:** sin propiedad sobre sizing, risk, accounting ni órdenes.
- **Unclean worktree:** inventariar; preservar cambios ajenos; no sobrescribir ni limpiar sin justificación.

## 11. ACCEPTANCE MATRIX / DEFINITION OF DONE

- `ACC-01`: WP005L permanece intacto; veredicto capturado y no reinterpretado.
- `ACC-02`: mapa de runtime y baseline real, identificando entrypoints/commits.
- `ACC-03`: datos reales con provenance, PIT y huellas verificables.
- `ACC-04`: embudo de señales/rechazos y causa 003I explicada, sin tocar límites.
- `ACC-05`: al menos un paper fill natural E2E reconciliado, o `BLOCKED`, nunca PASS sintético.
- `ACC-06`: evidencia separada `REPLAY_OOS` / `PAPER_OBSERVED` / `SYNTHETIC_TEST`.
- `ACC-07`: costes completos y performance reconstruible sin resultados inventados.
- `ACC-08`: frecuencia ACTIVE diaria medida, no impuesta.
- `ACC-09`: independencia del verificador, controles negativos detectados, falsos éxitos observados = 0.
- `ACC-10`: ningún envío de orden live, secretos o cambios de risk/exits/slots.
- `ACC-11`: informes commit-linked, tests ejecutados, fallos heredados declarados.
- `ACC-12`: dictámenes técnico/económico/observabilidad/live independientes.

**Definition of Done:** `REQ + ACC + ARCH/RFC + WP + IMPLEMENTATION + TEST + REAL_EXECUTION + EVIDENCE + INDEPENDENT_VERIFICATION`. El cumplimiento documental no sustituye ejecución real.

## 12. ROLLBACK

Feature flag off (`REAL_SIGNAL_PAPER_CAMPAIGN_ENABLED=false`), parar solo el proceso aislado de 003J, conservar datos/ledger/evidencia inmutables, revertir el adaptador introducido mediante commit explícito sin borrar resultados. Sin cambios a tareas WP005L ni producción. Si aparece una discrepancia contable o riesgo de ejecución live, `FAIL_CLOSED` y detener campaña.

## 13. AUTONOMOUS CODEX EXECUTION CONTRACT

1. **Leer** AGENTS.md, arquitectura actual, RFCs existentes, `003I`, `WP005L` y `git status`; no suponer nombres de módulos ni paths.
2. Comprobar si `RFC-TA-EXP-003J-001` ya existe en el repositorio. Si existe, comparar y **actualizar el mismo RFC** preservando historial; no crear duplicado ni cambiar IDs.
3. Registrar decisiones reversibles y continuar de forma autónoma. Evitar nuevas preguntas salvo producción, dinero real, secretos, costes relevantes o cambios de riesgo/gobernanza.
4. Ejecutar WP en orden; no iniciar cambios que interfieran con WP005L antes de su cierre. Documentar lo que sea seguro y read-only primero.
5. Por defecto usar estrategia(s) ya existentes, en particular EMA como baseline **no promovida**, sin inventar señales ni eludir políticas. Diagnosticar `resolve_intent` primero.
6. No añadir agentes/frameworks ni ampliar arquitectura porque sí. Implementar el parche más pequeño en el runtime autoritativo.
7. Capturar `RUN_REPORT.md` y `.json` por fase y matriz `claim/source/evidence/decision`; incluir outputs reales de comandos, exit codes, hashes y rutas verificables.
8. Exigir verificador independiente distinto del builder y ejecutarlo **después** de la implementación; no declarar PASS por tests unitarios solamente.
9. Al cerrar cada WP informar `COMPLETED`, `PARTIAL`, `BLOCKED` o `FAILED`, con evidencias y próximo WP autónomo; hacer commit solo de artefactos del encargo, sin pisar cambios preexistentes.
10. No afirmar `CERTIFIED`, `READY`, `PRODUCTION_READY` ni `PROFITABLE` salvo la evidencia requerida para cada afirmación; en este RFC **live siempre NO-GO**.

## 14. FINAL REPORT TEMPLATE

```yaml
phase: RFC-TA-EXP-003J-001
commits: []
implemented: []
tests: {unit: null, contract: null, integration: null, adversarial: null}
runtime_validation: {result: UNKNOWN, natural_signal_to_fill: false}
paper_validation: {replay_oos: UNKNOWN, observed: UNKNOWN}
false_success: UNKNOWN
defects: []
blockers: []
evidence: []
architecture_status: UNCHANGED_UNLESS_GAP_PROVEN
rfc_status: PROPOSED|IN_PROGRESS|COMPLETE|BLOCKED
technical_e2e: PASS|FAIL|INCOMPLETE|BLOCKED
strategy_economics: NEGATIVE|INSUFFICIENT_EVIDENCE|RESEARCH_CANDIDATE
live_trading: NO_GO
next_phase: null
```

**Resultado buscado:** evidencias honestas de si existe un flujo paper completo con señales de mercado y qué le sucede económicamente a la estrategia. Si no hay señales o el edge es negativo, esa conclusión documentada es un resultado válido de investigación, **no una certificación de trading exitoso**.
