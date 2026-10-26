# RFC-PAPER-008 — PAPER/SHADOW 24×7, dashboard de señales reales e IA en tiempo cercano al real

**Fecha:** 2026-10-26  
**Estado:** PROPOSED / IMPLEMENTATION-READY / NOT CERTIFIED  
**Prioridad:** P0 operativa  
**Repo:** `Extr3sao/bot_crypto`  
**Issue principal:** https://github.com/Extr3sao/bot_crypto/issues/50  
**Implementación de partida:** https://github.com/Extr3sao/bot_crypto/pull/51 (DRAFT, rama `feat/wp-signal-001-003`, HEAD observado antes de esta documentación `3be8e5bd36cab4f6fc532a0b891147b1f21efe08`)  
**Restricción:** PAPER/SHADOW y lectura de mercados; LIVE órdenes/dinero real deshabilitado.

## 1. Contexto y evidencia

El repositorio ya contiene el camino `scripts/autonomous_paper.py → DecisionTrace → signals.jsonl → dashboard /api/signals` y un sidecar `scripts/ai_signal_analyst.py → analysis.jsonl → /api/analysis`, supervisados por `scripts/start_paper_lab.py`. La PR #51 publicó estos componentes, pero sigue en DRAFT; código publicado NO equivale a servicio probado.

La evidencia G-7 compartida el 26-10-2026 muestra ingestión real, decisión, trazas y un outcome de shadow; también 0/24 estrategias admitidas, 0 PAPER_TRADE, rentabilidad no acreditada y una divergencia de criterios del router entre lanes. G-7 (`audit/g7-real-paper`, `ea87dc1f`) no estaba integrado con la rama de señales en el momento del informe. No asumir que cualquier commit de G-7 está presente ni que su replay prueba 24 h de funcionamiento continuo.

**Baseline de verificación pendiente:** checkout limpio + versiones concretas + tests + CI + HTTP real + Windows + proveedor IA real. Tratar como `NOT_VERIFIED` cualquier fase sin ejecución y evidencias.

## 2. Objetivo y no-objetivos

**Objetivo:** operar 24 h continuas de PAPER/SHADOW con datos de mercado públicos reales en un host Windows 11 encendido, mostrar decisiones y señales automáticamente en el dashboard existente y adjuntar análisis de IA read-only cuando exista un proveedor autorizado. Cualquier caída, dato stale, falta de señal o falta de IA debe ser visible, no ocultarse.

**No objetivos:** rediseñar la arquitectura, crear segundo dashboard/broker/router, forzar BUY/SELL, cambiar el ledger de admisión, bajar umbrales de riesgo, habilitar LIVE, prometer rentabilidad, desplegar GitHub Actions como servicio 24×7, exponer el dashboard públicamente o instalar herramientas grandes sin necesidad demostrada.

## 3. Reglas de autoridad

1. `REAL_RUNTIME > EXECUTION_EVIDENCE > TESTS > SOURCE_CODE > ARCH/RFC`.
2. `DecisionTrace` es autoridad para `SignalEvent`; el dashboard y la IA son consumidores. No pueden inventar ni mutar decisiones.
3. `SIGNAL/SHADOW` puede operar sin estrategias admitidas, mostrando `NO_ALPHA`, `NO_TRADE`, `REJECTED` o `OPERATIONAL_FAILURE` cuando corresponda. `PAPER_ORDER` continúa `BLOCKED` con 0 admisiones; `LIVE` sigue `DISABLED`.
4. Riesgo, sizing, ejecución, contabilidad y admisión siempre deterministas. La IA no recibe credenciales de trading ni facultad de ordenar.
5. `data_time <= decision_time <= analysis_time` cuando exista análisis. Ninguna observación futura ni timestamps inventados.
6. `BUILDER != VERIFIER`; `FALSE_SUCCESS = 0`. El verificador debe poder rechazar un run cuya evidencia esté incompleta.
7. No destruir, sobrescribir ni limpiar evidencias existentes; no forzar pushes ni fusionar baselines divergentes sin comparación.

## 4. Contratos y flujo de runtime

```text
REAL public market data
  → market data validation (freshness / PIT / bars cerradas)
  → runtime autoritativo (StrategyRouter → Proposal → Review → Decision → Risk)
  → DecisionTrace append-only
  → SignalEvent projection → signals.jsonl ───────────────┐
  → shadow outcomes / paper reconciliation (si elegible) │
                                                         ├→ dashboard existente (GET, loopback)
  → AI analyst read-only (sidecar) → analysis.jsonl ─────┘
  → independent verifier + RUN_REPORT.{md,json}
```

**Estados diferenciados en la interfaz:**
- Proceso: `STARTING / RUNNING / STALE / DEGRADED / DOWN / STOPPED`.
- Decisión/señal: `ALPHA / NO_ALPHA / NO_TRADE / OPERATIONAL_FAILURE` y etapa `CANDIDATE / REJECTED / SHADOW / PAPER`.
- Análisis: `ANALYZED / PENDING / FAILED / NOT_CONFIGURED`.
- Permisos: `INGEST/SIGNALS/SHADOW` separados de `PAPER_ORDER` y `LIVE`.
- Resultados: `SHADOW_OUTCOME` separado de `PAPER_FILL` y PnL contable; no sumar hipótesis como fills reales.

Conservar campos actuales de `SignalEvent` (`signal_id`, `run_id`, `decision_id`, `symbol`, `venue`, `timeframe`, `strategy_id`, `bar_close_time`, `decision_time`, `source`, `stage`, `kind`, `gross/cost/net_edge_bps`, `evidence_refs`). Cualquier ampliación debe ser compatible con el esquema existente, versionada y cubierta por test.

## 5. Work Packages: ejecutar en este orden

### WP-PAPER-008A — Baseline única y verificación de la PR #51

- En el repositorio local identificar `origin`, commit, rama, `git status --porcelain`, worktrees y diferencias contra `main`, PR #18, rama G-7 y PR #51. No tocar cambios concurrentes/sucios. Crear o usar checkout de trabajo limpio de la rama pertinente.
- Auditar en código los entrypoints `start_paper_lab.py`, `autonomous_paper.py`, `paper_lab_dashboard.py`, `ai_signal_analyst.py`, `wp_signal_verify.py` y archivos de evidencia.
- Ejecutar suite focal `tests/unit/autonomous/test_signal_*.py`, `tests/unit/autonomous/test_lab_operations.py`, `tests/unit/observability/test_paper_lab_signal_view.py` y la regresión pertinente. Reportar `N/N`, errores y exit codes reales; no dar por buenos tests no ejecutados.
- Revisar desalineaciones G-7 vs PR #51: `provider` ausente de `PAPER_RUN.json`, discrepancia de atribución de outcomes y configuración `require_confirmed` entre lanes. Corregir solo defectos realmente alcanzables, con tests; no relajar gates.
- **Salida:** `BASELINE_REPORT.md` con SHAs exactos, tabla `CAPABILITY: IMPLEMENTED/VERIFIED/BLOCKED`, riesgos de integración y evidencia de pruebas.

### WP-PAPER-008B — E2E REAL: señal → fichero → HTTP → dashboard

- Ejecutar `uv run python scripts/start_paper_lab.py --dry-run --provider ccxt --assets BTC,ETH,SOL --timeframe 5m --paper-cadence bar-close --duration-hours 2` desde el checkout limpio; registrar preflight, provider real, disco, permisos y exit code.
- Si el preflight pasa, iniciar **una ventana supervisada, acotada**, con un `run_id` persistente, para ver datos reales tras cierre de barras. No falsificar señales por alcanzar volumen. Validar el dataset/venue/timeframe reales y las dependencias del collector; no deshabilitar controles de proveedor por comodidad.
- Levantar el dashboard existente `uv run python scripts/paper_lab_dashboard.py --run-id <RUN_ID>`; verificar por HTTP `GET /healthz`, `/api/status`, `/api/signals`, `/api/analysis`. Comprobar desde navegador local que cada evento visible coincide con una traza autoritativa.
- Probar explícitamente `source=REAL`, `data_time<=decision_time`, ids deterministas, idempotencia, ausencia de duplicados, reinicio con mismo `run_id`, paginación, `STALE/DOWN`, `NO_ALPHA` y `OPERATIONAL_FAILURE`.
- `GET` permitido, métodos de mutación rechazados; bind solo `127.0.0.1`/`::1` sin apertura de red.
- **Salida:** una traza real verificable, vista HTTP derivada de ella y capturas/salida del dashboard; si ninguna estrategia emite ALPHA, registrar `NO_ALPHA` legítimo, no marcar falla solo por baja frecuencia.

### WP-PAPER-008C — IA real read-only, no bloqueante

- Confirmar que el sidecar procesa señales ya persistidas y solo usa datos PIT/evidencia disponible, con `analysis_id`, `signal_id`, `model`, `prompt_version`, `claims`, `counter_evidence`, incertidumbres, coste, latencia y estado.
- Ejecutar pruebas con proveedor simulado **solo para contrato**. Sin `SIGNAL_ANALYST_API_KEY`, validar `NOT_CONFIGURED` en fichero y dashboard; **NO** etiquetarlo `AI_LIVE_PASS`.
- Con proveedor real configurado y gasto autorizado, ejecutar llamada(s) reales acotadas por presupuesto; cotejar evidencia, timestamps, texto, coste y `ANALYZED`. Redactar secretos en logs, reportes y GitHub.
- Inyectar timeout, respuesta malformada, límite de presupuesto y caída de sidecar; el runtime y la interfaz siguen funcionando, muestran `FAILED/PENDING` y no generan órdenes ni alteran decisiones.
- **Salida:** `AI_REAL_PASS` solo con una respuesta de proveedor verificable; si no hay clave/autorización, `AI_REAL_BLOCKED_NOT_CONFIGURED` sin bloquear `SIGNALS`.

### WP-PAPER-008D — Resiliencia 24 h, operación Windows y certificación

- Aprovechar `paper_lab_service.cmd`, `paper_lab_dashboard.cmd`, `install_paper_lab_task.ps1`, heartbeat, stop files, restart/backoff, presupuesto de disco y retención existentes.
- Probar parada limpia, reanudación, reinicio del supervisor, reinicio de sidecar, cortes de proveedor, pérdida de red, disco insuficiente y rechazo seguro; comprobar que no se duplican decisiones/órdenes.
- Validar primero una ventana corta y **después** una ventana real observada de 24 h sobre host con alimentación/red y espacio suficientes. No declarar 24×7 por la sola existencia de una tarea programada.
- La instalación persistente en Programador de tareas Windows requiere autorización explícita antes de modificar el host; mientras tanto entregar procedimiento de arranque manual probado. No habilitar LIVE.
- Dashboard: salud, último dato/barra UTC, último ciclo, última señal, conteos por causa, fuentes, coste neto esperado, resultados shadow vs paper, estado/latencia IA, retrasos, errores y bloqueos de admisión.
- Verificar independientemente los ficheros originales y el HTTP con `uv run python scripts/wp_signal_verify.py --run-id <RUN_ID> --dashboard-url http://127.0.0.1:8787`; ejecutarlo desde un proceso/rol distinto del builder.
- **Salida:** `RUN_REPORT.md`, `RUN_REPORT.json`, `verification.json`, hashes de evidencias y `FINAL_REPORT.md`. Ausencia de ventana de 24 h = `24H_NOT_VERIFIED`, nunca `PASS`.

## 6. Criterios de aceptación (AC)

- **AC-01 GitHub:** cada WP termina con commit, push, SHA, PR y estado CI conocido; no solo archivos locales.
- **AC-02 Runtime:** el proveedor real y la temporalidad están identificados; un ciclo y sus señales son reproducibles en trazas/HTTP.
- **AC-03 Honestidad:** `NO_ALPHA`, `NO_TRADE`, `OPERATIONAL_FAILURE` diferenciados; 0/24 admitted sigue bloqueando PAPER_ORDER. Nunca fake como REAL.
- **AC-04 Dashboard:** `/api/signals` y `/api/analysis` responden con datos vinculados al mismo run y muestran `STALE/DOWN` fielmente; mutaciones = 405.
- **AC-05 IA:** un fallo, timeout o ausencia de proveedor no detiene ingestión ni decisiones; análisis real solo certificado con respuesta real.
- **AC-06 Durabilidad:** cierre/reinicio conserva traza, idempotencia, outcomes y análisis; cero duplicados y cero pérdida silenciosa comprobada.
- **AC-07 Continuidad:** 24 h de ejecución observada y auditada para estado `PAPER_SHADOW_24H_VERIFIED`; si no, declarar duración efectiva y `INCOMPLETE`.
- **AC-08 Seguridad:** 0 órdenes LIVE, 0 fills PAPER sin admisión, `FALSE_SUCCESS=0`, no secretos filtrados, fail closed en datos/risk.
- **AC-09 Independent verifier:** `TEST_TARGET == RUNTIME_TARGET`, denominadores, HTTP real y hashes de artefactos; cualquier omisión = `BLOCKED`.
- **AC-10 Información al usuario:** al terminar cada WP, resumen legible: qué corre, dónde verlo, señales observadas, IA real sí/no, razón de NO_TRADE, errores y qué impide la siguiente fase.

## 7. Métricas y reporte obligatorio

`run_id / git_commit / dirty_tree / branch / operating_system / provider / venue / symbols / timeframes / started_at_utc / stopped_at_utc / observed_uptime_seconds / cycle_count / signal_counts_by_kind_and_stage / no_trade_reasons / admission_eligible / paper_orders / shadow_outcomes / paper_fills / realised_paper_pnl_after_costs / data_age_seconds / max_gap / duplicate_count / analysis_status_counts / llm_provider / llm_call_count / llm_cost_usd / llm_latency_p95_ms / HTTP_checks / errors / verifier_result / false_success / blocker / evidence_sha256`.

Si una métrica no puede medirse, escribir `null` y explicar por qué; no sustituirla por 0.

No mezclar `outcomes_resolved` de SHADOW con `paper_fills` o PnL de PAPER.

## 8. Plan de rollback y fallos

- Si hay corrupción de ledger, look-ahead, datastream stale, riesgo sin validar, contaminación REAL/FAKE o ejecución no autorizada: detener de forma segura el flujo afectado y declarar `FAILED`, preservando trazas.
- Parada reversible mediante STOP file/CLI existente; restaurar revisión anterior mediante Git si una corrección introdujo regresión. No reescribir ficheros de evidencia.
- Si falla IA, permanecer en `SIGNALS/SHADOW` con `AI_DEGRADED`, sin impacto sobre decisiones.
- Si el host está apagado, dashboard `DOWN`; no declarar continuidad ni simular barra/heartbeat.

## 9. Instrucción de ejecución para Codex

> Implementa RFC-PAPER-008 en `Extr3sao/bot_crypto`, empezando por WP-PAPER-008A. Máxima autonomía en auditoría, cambios reversibles, tests, runtime PAPER/SHADOW y verificación. No repitas funciones existentes ni abras nuevas RFC. No habilites LIVE, no modifiques risk/admission para crear señales, no instales tareas persistentes sin permiso ni consumas APIs de pago sin autorización. Ejecuta los WPs en orden y registra fallos reales. Tras cada WP haz commit y push, actualiza la PR #51 o abre PR dependiente si se requiere aislamiento, e informa SHA, tests reales, evidencia, estado y siguiente bloqueo. Declara `CERTIFIED` solo si AC-01..10 pasan con ejecución real de 24 h y verificador independiente.

**Estados finales posibles:** `CODE_ONLY`, `E2E_REAL_VERIFIED`, `AI_REAL_BLOCKED`, `AI_REAL_VERIFIED`, `24H_NOT_VERIFIED`, `PAPER_SHADOW_24H_VERIFIED`, `PAPER_ORDER_BLOCKED`. No equivalen a rentabilidad ni a autorización de trading real.
