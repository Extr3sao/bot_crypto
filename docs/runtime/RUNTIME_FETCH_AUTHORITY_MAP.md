# RUNTIME_FETCH_AUTHORITY_MAP — quién descarga mercado y quién lo usa

**RFC:** RFC-TAP-MARKET-005 · **Base:** `fe9b5e2623b0d023833249e9687b753eaacd27d4` (rama `agent/ai-bots/RFC-TAP-AI-BOTS-003`)
**Método:** `Get-ScheduledTask`, `Get-ScheduledTaskInfo`, `Get-CimInstance Win32_Process`, lectura de fuentes, `evidence/real_decisions/operations.jsonl` y `logs/cap004_supervisor.log`. Todo **read-only**; no se detuvo, editó ni registró ninguna tarea.
**Captura:** 2026-10-18T19:46:42Z (`SCHEDULER_INVENTORY.json`).

## 1. La corrección más importante de esta auditoría

`reports/ops/WP-OPS-BACKGROUND-001/FINAL_REPORT.md` afirma que la tarea CAP004 no se instaló. **El host dice lo contrario**: existen **seis** tareas `TradingAgentic-*`, todas `Ready`, todas con repetición `PT15M`.

La autoridad del runtime local prevalece sobre el informe histórico. Cualquier plan que asumiera "no hay tareas" habría sido falso.

| Tarea | Repetición | Último resultado | Acción | Consola |
|---|---|---|---|---|
| `TradingAgentic-ALPHA002-Capture` | PT15M | 0 | `alpha002_capture.cmd` → `pythonw.exe` + `windowless.py` | **no** |
| `TradingAgentic-CAP004-Campaign` | PT15M | 3 | `python.exe cap004_supervisor.py run` | **sí** |
| `TradingAgentic-CAP004D-HealthWatch` | PT15M | 30 | `python.exe cap004d_health_check.py` | **sí** |
| `TradingAgentic-EDGE04-Forward` | PT15M | 5 | `python.exe edge04_observer.py --scheduled --due` | **sí** |
| `TradingAgentic-EDGE05-Watchdog` | PT15M | 12 | `python.exe edge05_watchdog.py` | **sí** |
| `TradingAgentic-ST6-Forward` | PT15M | 0 | `python.exe st6_forward_regime.py --due --scheduled` | **sí** |

`last_task_result = 3` en CAP004 **no es un fallo**: el supervisor sale con `3` cuando no hay trabajo debido (`logs/cap004_supervisor.log`: `action=NOOP ... exit=3`). Los resultados 30/5/12 de las otras tareas no se interpretan aquí; se preservan sin tocarlas.

## 2. Quién emite `fetch_ohlcv_start` / `fetch_ohlcv_ok`

El evento se emite **solo** en `CCXTExchangeConnector.fetch_ohlcv` (`market_data/exchange_connector.py`). El `limit` de la llamada es el que aparece en la traza.

Rutas que llegan a esa función:

| Origen | Ruta | Límites | ¿Coincide con la captura? | Clasificación |
|---|---|---|---|---|
| CAP004-Campaign | `cap004_supervisor.run_cycle` → `cap004_campaign_runner.run_cycle` → `real_market_context.fetch_provider_ohlcv` | 1000/500/500 × 4 activos | **sí, por código** | `KEEP_CAMPAIGN` |
| Manual / agente | `scripts/cap002_real_run.py` (2 activos), `scripts/cap003_campaign.py` (4 activos) | 1000/500/500 | **sí, por código** | `RESEARCH_ONLY` |
| ALPHA002 | endpoints `/futures/data/*` | 1000 filas de funding | no | `KEEP_CRITICAL` |
| ST6 | `urllib /api/v3/klines?limit=25` | 25 | no | `RESEARCH_ONLY` |
| EDGE04 / EDGE05 / CAP004D | sin descarga de mercado | — | no | `KEEP_OPS` / `RESEARCH_ONLY` |

**Atribución de la captura concreta: `NOT_ATTRIBUTABLE`.** No sobrevive ningún `req_id` de consola, ningún proceso estaba vivo en la captura y por tanto no se puede demostrar cuál de los dos candidatos (tarea o ejecución manual) la produjo. Lo que **sí** está demostrado es que solo `real_market_context` usa esos tres límites, y que la tarea CAP004 es la única ruta programada que puede alcanzarlo.

## 3. ¿El dato se usa?

- `cap004_campaign_runner` construye el `MarketSnapshot` contractual y decide con él; el `RUN` del 2026-10-07 (pid 32052) evaluó 4 decisiones. Es decir: **el fetch de la campaña sí alimenta una decisión**, pero solo en el slot debido (1 de 1081 operaciones). El resto son `NOOP` que **no** descargan.
- `cap002/cap003` alimentan artefactos de investigación, no el runtime PAPER.
- `ST6` alimenta su propio registro forward.
- `ALPHA002` alimenta el dataset de derivados (retención de 30 días en el venue: perder una ejecución destruye datos).

Ningún log `fetch_ohlcv_ok` prueba por sí solo que el dato se usó. En esta auditoría la prueba de uso es la evaluación del ledger de CAP-004, no el log del connector.

## 4. Por qué hay ventanas cada 15 minutos

Cinco de las seis tareas ejecutan `python.exe` (subsistema de consola) bajo un principal interactivo: la ventana pertenece a la tarea, no a Freebuff.

El repositorio **ya** tiene la solución (`scripts/windowless.py` + `cap004_supervisor.task_arguments()` genera `pythonw.exe` + launcher), pero **la tarea instalada es anterior a ese cambio** y sigue apuntando al intérprete de consola. Re-registrarla es una modificación del host → **WP-005H, requiere autorización**; el plan exacto y el rollback están en `reports/market-data/RFC-TAP-MARKET-005/RUN_REPORT.md` §6.

## 5. Autoridad que este RFC no toca

- `RiskManager`, `PaperBroker`, `strategy_admission`: sin cambios (verificado con `git diff` en `INDEPENDENT_VERIFICATION.json`).
- Ninguna tarea se detuvo, creó, editó ni ejecutó.
- Ningún dataset se borró.
- Ninguna llamada a modelo: `REAL_MODEL_CALLED=false`.

## 6. Límites de esta auditoría

- El árbol de procesos es una **foto**; un proceso terminado antes de la captura no se puede reconstruir (`NOT_ATTRIBUTABLE`).
- `last_task_result` 5/12/30 no se interpretan sin el código de salida documentado de cada entrypoint.
- El XML completo de cada tarea no se adjuntó (contiene el SID del principal); se guardaron acción, trigger y directorio de trabajo, que es lo que decide la descarga.
