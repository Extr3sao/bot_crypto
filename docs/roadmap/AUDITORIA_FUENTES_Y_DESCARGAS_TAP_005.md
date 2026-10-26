# Auditoría breve — ¿de dónde salen las descargas y las ventanas?

Fecha: 2026-10-18 · rama revisada `fe9b5e2623b0` · método: GitHub source, reportes de ejecución publicados y captura aportada por usuario. **No hubo acceso a Process Explorer, Task Scheduler, registro de procesos ni panel Windows del usuario durante esta auditoría**.

## Lo que sí sabemos

1. La consola mostrada comunica `fetch_ohlcv_start` y `fetch_ohlcv_ok` para 1h, 4h y 1d, BTC/ETH/SOL. Esos nombres de evento los emite `src/trading_bot/market_data/exchange_connector.py` en `CCXTExchangeConnector.fetch_ohlcv`; la operación es lectura de datos públicos, no análisis LLM.
2. La forma y cantidades coinciden con los valores de `real_market_context.FETCH_LIMITS`: 1h=1000, 4h=500, 1D=500. Esto sugiere que el consumidor es el constructor de contexto multitemporal o un llamante que usa sus contratos. **Es solo correlación del patrón, no identificación de caller**.
3. `cap004_supervisor.py` define scheduler cada 900 segundos y una tarea Windows llamada `TradingAgentic-CAP004-Campaign`. El WP de windows reporta que no registró la tarea en Windows; por tanto, **no sabemos si ese task está instalado previamente en el host**.
4. La cadena `explorer→Freebuff GUI→bun.exe CONSOLE→bash.exe→python.exe` atribuye la creación de la consola en aquella ejecución a Freebuff/Bun. No atribuye automáticamente todas las lecturas market data que ocurran a la misma hora.
5. `forward_collector.py` es WebSocket-first, read-only, pero discovery-only; no sustituye al paper runtime. `oos_capture.py` mantiene evidencia históricamente útil y no debe eliminarse.
6. `AI-BOTS-003C` valida reloj, riesgo y ejecución paper con proveedor **replay**: `REAL_MODEL_CALLED=false`, `PROSPECTIVE_PAPER_VALIDATED=false`. El problema actual no se arregla poniendo un LLM en vez de la API de precios.
7. En `provider.py` el request ID sintético fallback (`model-timestamp`) debe corregirse antes de acreditar ejecuciones de proveedor real; RFC-003D es dueño de esa reparación y RFC-005 no debe duplicarla.

## NO sabemos todavía

- PID / command-line / línea de código que originó la descarga concreta fotografiada.
- Si la tarea CAP004 (u otra) está instalada y con qué `LastRunResult` y trigger exactos.
- Cuántas de esas 1.000/500/500 barras son nuevas, si hay cache compartida y si el destino es research o paper.
- Si el screenshot pertenece a Freebuff, a una tarea Python o a una operación lanzada manualmente; hay más de un origen posible.
- Que haya un proveedor de IA al que Freebuff dé acceso programático autónomo. Que aparezca IA en la GUI no es suficiente.

## Lecturas permitidas para el primer WP

- Enumerar la tarea con PowerShell `Get-ScheduledTask` y `Get-ScheduledTaskInfo` (solo lectura), registrar XML/Triggers/Actions/LastRunTime/LastTaskResult, sin guardar nombres de usuario/token innecesarios.
- Enumerar PID/PPID/CommandLine/ExecutablePath con procesos de Windows durante la reproducción; redactar secretos, nunca volcar variables de entorno.
- Registrar en el mismo `run_id` timestamp, `req_id`, traceback caller autorizado, consumer marker, `source_sha`, destino y counters. Permitir `NOT_ATTRIBUTABLE` si el proceso ha terminado.
- Comparar llamadas reales `N_PER_HOUR`, bytes/bar, latency y cache hits, con la prueba de baseline y propuesta usando la misma ventana.

## Decisión de seguridad

Mantener las tareas como estén hasta conocer su valor y consumidor; no deshabilitar/editar `Task Scheduler`, no suprimir datasets OOS, no asumir que Freebuff es el origen único. La mejora buscada es **eliminar recargas redundantes, no el mercado**.
