# PROMPT PARA CODEX — RFC-TAP-MARKET-005

**Misión:** implanta autónomamente RFC-TAP-MARKET-005 sin apagar nada ni consumir APIs LLM de pago. El usuario quiere IA que estudie el mercado de forma continuada, pero desea eliminar descargas históricas repetidas y ventanas molestas si son innecesarias.

**Repositorio:** Extr3sao/bot_crypto. **Baseline conocida:** `fe9b5e2623b0d023833249e9687b753eaacd27d4` en rama `agent/ai-bots/RFC-TAP-AI-BOTS-003`. Confirma HEAD, permisos, disco, procesos y worktree antes de tocar. Rama/worktree aislado. No asumir que `main` incluye los fixes del carril AI ni que la rama económica esté fusionada.

**Hechos conocidos:** screenshot muestra `fetch_ohlcv_start/ok` del conector `CCXTExchangeConnector`; `real_market_context.py` define límites 1000 velas 1h, 500 4h, 500 1d que coinciden. La coincidencia NO identifica el parent/caller; `Freebuff→bun→bash` es un origen de ventana, no prueba de que sea el scheduler del fetch. CAP004 define Task Scheduler cada 15min, pero WP-OPS informó que NO instaló/modificó la tarea real. Hay collectors y cachés ya disponibles. `REAL_MODEL_CALLED=false`.

## Proceder con máxima autonomía en safe/offline

1. **WP-005A READ-ONLY PRIMERO**: ejecuta `Get-ScheduledTask`/`Get-ScheduledTaskInfo`, árbol de procesos, XML de acciones, inventario de auto-start, log req_id y consumidores; correlaciona cada `fetch_ohlcv` visible con `PID, PPID, task, run_id, stack/entrypoint, destino, consumer`; si no es reconstruible, `UNKNOWN`, jamás atribuir por parecido. Identifica si descarga 1000/500/500 se repite cada ciclo y quién la usa.
2. En paralelo define matriz `KEEP_BOOTSTRAP / KEEP_INCREMENTAL / KEEP_CAMPAIGN / RESEARCH_ONLY / REDUNDANT_CANDIDATE / UNKNOWN / DEAD_CODE`; todo desconocido se preserva.
3. Crea baseline en el runtime, con tasa de requests, transferencias, age, gaps, dedup y coste/disco, sin modificar configuración de tareas/campañas.
4. Implementa **solo si evidencia justifica** delta-reader por watermark/since+overlap/validación de vela final. Reusa `CCXTExchangeConnector`, `OHLCVFetcher`, `OHLCVStore`, `quota` y `oos_capture`; no hacer un segundo framework. Compara `CURRENT vs PROPOSED` con mismos datos y demuestra reducción medible.
5. Introduce `MarketSnapshot` PIT y puente de datos hacia BOT-VIS/CTX y runtime PAPER/SHADOW, manteniendo StrategyAdmission, RiskManager y PaperBroker sin bypass. Las 4h/1d no estarán disponibles hasta cerrar.
6. Gate de eventos IA, caching y límites **en modo offline/test**; no inferencia pagada ni request_id inventado; si no hay proveedor acreditado, salida `BLOCKED_MODEL_API` y ninguna operación atribuida a IA.
7. Corrige logging/supervisor windowless **propio** donde proceda; Freebuff/Bun externo queda bloqueado si no hay build oficial con `windowsHide`, nunca parchear binario firmado.
8. Ejecuta RED→GREEN, pruebas de corrección de vela, duplicados, unavailable HTF, restart, disk full, `0` datos nuevos, 2 schedulers solapados, cuotas/429/500, API key missing y ausencia de fills al precio pasado. Verificador independiente; mutaciones reales contra ruta ejecutada.
9. Publica reportes y evidencias exactas, commits fast-forward en rama propia, `FINAL_REPORT` con `PASS / FAIL / BLOCKED / NOT_RUN`; prepara update del Excel maestro en **rama `project/roadmap-trading-agentic`** con ids TAP-064..TAP-071 (o actualízalos si ya existen). No dupliques libros; comprobar commit HEAD en dicha rama antes de modificar.
10. **NO ejecutar WP-005H** (ni detener tareas, programar repetición, instalar servicios Windows) sin autorización de modificación del host. Genera plan detallado, comandos idempotentes, rollback y `USER_APPROVAL_REQUIRED`. Los WPs 005A–G sí se pueden hacer autónomamente.

**Entregar:** `RUNTIME_FETCH_AUTHORITY_MAP`, `SCHEDULER_INVENTORY`, `FETCH_PROCESS_TRACE`, `CURRENT_VS_PROPOSED`, `COVERAGE_LEDGER`, `AI_TRIGGER_LEDGER`, `INDEPENDENT_VERIFICATION`, `RUN_REPORT.json/.md`, `FINAL_REPORT.md`, checkpoint, comparación de las lecturas históricas con las incrementales, estado de modelo real y decisión por cada descarga a KEEP/OPTIMIZE/DISABLE_CANDIDATE.

**Reglas:** `FALSE_SUCCESS=0`; `BUILDER != VERIFIER`; `TEST_TARGET == RUNTIME_TARGET`; `DATA_TIME<=DECISION_TIME`; sin live trading, capital, leverage, risk changes, API pagada, credenciales de usuario ni borrar dataset; sin alterar `config/risk.yaml` ni `config/strategy_admission.json`. No confundir Codebuff IDE con servicio LLM autónomo.
