# RUN_REPORT — RFC-TAP-MARKET-005

**Fecha:** 2026-10-18 · **Rama:** `agent/market/RFC-TAP-MARKET-005` · **Base:** `fe9b5e2623b0d023833249e9687b753eaacd27d4`
**Worktree:** `C:/Users/GVLLFR0035/Downloads/bot_crypto_005` (nuevo; ningún worktree existente se reutilizó)
**Estado:** ingeniería offline **DONE** (WP-005A…G). Activación en el host **NO EJECUTADA** (WP-005H, `USER_APPROVAL_REQUIRED`).
**Modelo real:** `REAL_MODEL_CALLED=false` · **Llamadas de pago:** 0 · **Trading real:** no.

---

## 1. Qué se auditó (WP-005A), sin modificar nada

Seis tareas `TradingAgentic-*` instaladas, `Ready`, todas `PT15M`; cinco lanzan `python.exe` (consola). La auditoría anterior (`WP-OPS-BACKGROUND-001`) decía que la tarea CAP004 no se había instalado: **el host la tiene**. Detalle completo en
[`RUNTIME_FETCH_AUTHORITY_MAP.md`](../../../docs/runtime/RUNTIME_FETCH_AUTHORITY_MAP.md),
[`SCHEDULER_INVENTORY.json`](SCHEDULER_INVENTORY.json) y
[`FETCH_PROCESS_TRACE.jsonl`](FETCH_PROCESS_TRACE.jsonl).

Atribución honesta:

| Pregunta | Respuesta |
|---|---|
| ¿Quién puede emitir `fetch_ohlcv` con 1000/500/500? | Solo `real_market_context.fetch_provider_ohlcv`, alcanzable desde `cap004_campaign_runner`, `cap002_real_run.py` y `cap003_campaign.py`. |
| ¿Cuál produjo la captura del usuario? | **`NOT_ATTRIBUTABLE`**: no hay `req_id` persistido ni proceso vivo; se descarta inventarlo. |
| ¿La tarea CAP004 descarga cada 15 min? | **No.** 1080 de 1081 operaciones son `NOOP` sin descarga (`operations.jsonl`). Descarga solo cuando hay slot debido; el único `RUN` fue 2026-10-07. |
| ¿El dato se usa? | En CAP004 sí (4 decisiones evaluadas en ese `RUN`); en CAP002/003 alimenta artefactos de investigación. |
| ¿De dónde salen las ventanas? | De las cinco tareas con `python.exe`. El repo ya tiene `windowless.py`, pero la tarea instalada es anterior a ese cambio. |

Clasificación por descarga: `KEEP_CAMPAIGN` (CAP004) · `KEEP_CRITICAL` (ALPHA002, retención de 30 días en el venue) · `KEEP_OPS` (CAP004D) · `RESEARCH_ONLY` (EDGE04/05, ST6, CAP002/003) · `OPTIMIZE` (la recarga 1000/500/500 de `real_market_context`) · **`DISABLE_CANDIDATE`: ninguna** — no se demostró que ninguna descarga sea prescindible, así que no se propone apagar nada.

## 2. Qué se implementó (WP-005C/D/E)

Cinco módulos nuevos, todos composición sobre lo existente:

| Fichero | Responsabilidad |
|---|---|
| `src/trading_bot/market_data/incremental.py` | Watermark por `(source, symbol, timeframe)`, bootstrap único, delta acotado con overlap, sólo velas cerradas, cobertura probada o fallo cerrado. |
| `src/trading_bot/market_data/timeframe_store.py` | Vista `TimeframeStore` sobre `OHLCVStore`, cuya PK `(symbol, timestamp)` **no tiene dimensión de timeframe** (ver §5, hallazgo H-2). |
| `src/trading_bot/market_data/snapshot.py` | `MarketSnapshot` PIT + `gate_snapshot` (disponibilidad, frescura por timeframe, precio ejecutable). |
| `src/trading_bot/market_data/market_events.py` | `EventGate` (dedupe por vela cerrada, cooldown, tope horario, presupuesto, credencial) + `ResponseCache` con TTL e identidad. |
| `src/trading_bot/market_data/replay.py` | Conector de reproducción read-only para verificar offline con la misma semántica "últimas N". |
| `scripts/mkt005_market_intel.py` | CLI: `capture`, `ingest`, `baseline`, `snapshot`. |
| `scripts/mkt005_verify.py` | Verificador independiente (no importa `trading_bot`) + suite de mutaciones. |

Reutilización: `CCXTExchangeConnector` (y su retry), `OHLCVStore`, `candle_filter.timeframe_seconds_or_raise`, `Exchange`/`real_market_context` (universo y límites). No se creó un segundo cliente HTTP, ni un segundo broker, ni un segundo motor de riesgo.

**Delta real, sin `since`:** el contrato del connector es `(symbol, timeframe, limit)`, así que el delta es una lectura acotada de las últimas N velas + deduplicación, y se *prueba* cobertura exigiendo `min(timestamp) <= first_needed`. No se declara "since" que el provider no ofrece.

## 3. Medición CURRENT vs PROPOSED (WP-005B/F)

Mismos datos, mismos 4 activos, mismos 3 timeframes, misma cadencia de 15 minutos, 96 ciclos (24 h), ventana de decisión de 200 velas cerradas.

| Métrica | CURRENT | PROPOSED | Δ |
|---|---|---|---|
| Peticiones | **1 164** | **136** | −88,32 % |
| Velas transferidas | **770 312** | **8 496** | −98,90 % |
| Bytes (payload medido) | **133,32 MiB** | **1,47 MiB** (incluye bootstrap) | −98,90 % |
| Bytes en régimen estable | 133,32 MiB/día | **108,6 KiB/día** | **−99,92 %** |
| Ventana cerrada equivalente | — | — | **12/12 series idénticas** |

Procedencia de los bytes: `curl` contra `api.binance.com/api/v3/klines` para las dos formas de petición (`1h/1000`=178 500 B, `1h/5`=891 B, `4h/500`=90 774 B, `4h/5`=904 B, `1d/500`=93 640 B, `1d/5`=928 B) multiplicado por las velas que cada estrategia transfirió en la ventana. El sobre de ccxt no se incluye en ninguno de los dos lados.

Desglose por serie en [`CURRENT_VS_PROPOSED.json`](CURRENT_VS_PROPOSED.json). El ledger de 97 ciclos ([`COVERAGE_LEDGER.jsonl`](COVERAGE_LEDGER.jsonl)) reproduce exactamente los mismos totales que la comparación (136 peticiones, 8 496 velas), por dos caminos distintos.

## 4. Snapshots y gate de IA (WP-005D/E)

`SNAPSHOT_GATE_REPORT.json`: 4/4 snapshots causales para `decision_ms = 1792352634561`.

```
1h   última vela cerrada 1792346400000 → cierra 1792350000000
4h   última vela cerrada 1792324800000 → cierra 1792339200000
1d   última vela cerrada 1792195200000 → cierra 1792281600000
available_at_ms = 1792350000000 ≤ decision_ms
```

`4h` disponible a las 20:00 y `1d` a las 00:00: ninguna vela posterior entra en la decisión. El gate se niega (`NOT_YET_AVAILABLE`, `STALE_TIMEFRAME`, `NO_EXECUTABLE_PRICE`) en vez de degradar.

IA por evento: **4 decisiones, 0 triggers, 0 llamadas de modelo**. Con `credentials_present=false` el motivo es `MISSING_CREDENTIAL`; el presupuesto por defecto es 0 USD. Un acierto de caché sólo es válido si coinciden `snapshot_hash + prompt_version + model_version` y no ha expirado el TTL.

## 5. Hallazgos que cambian el diseño

- **H-1 — el "delta" con overlap fijo pedía en cada tick.** La primera implementación restaba el overlap siempre y emitía una petición por ciclo aunque no hubiera vela nueva. Lo detectó un test (28 → 29 fallos): el overlap ahora sólo se gasta cuando existe al menos una vela nueva, y `NO_NEW_DATA` hace **0 peticiones**.
- **H-2 — `OHLCVStore` no distingue timeframe.** Su PK es `(symbol, timestamp)`; al sembrar 1h/4h/1d del mismo símbolo, la vela de 4h sobrescribía a la de 1h en el mismo instante y un "snapshot multitemporal" devolvía una serie mezclada con huecos. Se corrigió con `OHLCVTimeframeStore` (namespace `symbol@timeframe`), sin tocar el esquema ni las bases existentes.
- **H-3 — la frescura no puede ser absoluta.** Un rechazo por `age > 4h` habría invalidado siempre la vela diaria. La regla es `age > max_age + duración_del_timeframe`.

## 6. WP-005H — activación opcional en el host (NO EJECUTADA)

**Requiere autorización explícita de modificación del host.** Sin ella, aquí sólo se documenta.

Objetivo: que las cinco tareas de consola dejen de abrir ventana y que la campaña use el lector incremental. Ninguna tarea se apaga; ninguna se crea.

Esbozo idempotente (uno por tarea, con `pythonw.exe` + `scripts/windowless.py`, el mismo patrón que ya usa `alpha002_capture.cmd`):

```powershell
# 0) Backup (rollback en un comando)
schtasks /Query /TN "TradingAgentic-CAP004-Campaign" /XML > backup_CAP004.xml

# 1) Re-registro con la accion windowless (generada por cap004_supervisor.build_task_xml)
schtasks /Create /TN "TradingAgentic-CAP004-Campaign" /XML cap004_windowless.xml /F

# 2) Rollback exacto
schtasks /Create /TN "TradingAgentic-CAP004-Campaign" /XML backup_CAP004.xml /F
```

Puertas antes de activar: (a) equivalencia de datos ya demostrada aquí; (b) una ejecución manual del comando nuevo con `exit code` idéntico al actual; (c) `Get-ScheduledTaskInfo` mostrando `LastTaskResult` esperado; (d) rollback ensayado en una tarea de prueba, no en la real; (e) confirmación escrita del usuario.

Lo que **no** se hará sin un RFC aparte: cambiar el universo, el intervalo de 15 min, el `NOOP` de CAP004, o migrar `ST6`/`ALPHA002` al lector compartido.

## 7. Tests ejecutados

| Comando | Resultado |
|---|---|
| `pytest tests/unit/market_data tests/unit/storage -q` | **158 passed** |
| `pytest tests/unit/research/test_real_market_context.py -q` | **21 passed** |
| `pytest tests/unit/market_data/test_{quota,ohlcv_fetcher,ccxt_connector}.py -q` | **59 passed** |
| `pytest tests/unit/market_data/test_incremental_ingestion.py tests/unit/market_data/test_market_snapshot_events.py` | **28 passed** |
| `ruff check` + `ruff format --check` (8 ficheros) | limpio |
| `mypy` (5 módulos) | `Success: no issues found` |
| `scripts/mkt005_verify.py --mutations` | **8 PASS / 0 FAIL · 5/5 mutaciones detectadas** |
| `git diff fe9b5e2 -- config/risk.yaml risk/manager.py paper/broker.py strategy_admission.json` | **vacío** |

Casos adversariales cubiertos: vela en formación nunca persistida; duplicado en la misma respuesta; filas inválidas (`high<low`, NaN); fallo de proveedor; watermark corrupto; reinicio sin re-bootstrap; backlog mayor que la ventana (rechazo + `reconcile` explícito); hueco final que detiene el watermark; HTF futuro fuera del snapshot; snapshot no disponible antes del cierre; snapshot rancio; quote ausente/caducada; credencial ausente; presupuesto 0; evento duplicado tras reinicio; cooldown; tope horario; umbral de cambio material; caché por identidad y TTL.

## 8. Regresiones y limitaciones

- **Regresiones:** 0 en las suites ejecutadas. No se ejecutó la suite completa del repositorio (fuera del alcance del WP y con otros worktrees activos): se declara `NOT_RUN`, no `PASS`.
- **`TEST_TARGET == RUNTIME_TARGET`:** el CLI que se prueba es el mismo que se ejecutaría; no existe un camino "de test" paralelo. El conector de replay sólo sustituye al exchange, no al lector.
- **Dos schedulers solapados:** no se añadió planificador. La exclusión mutua sigue siendo la del supervisor CAP004 (lease). El CLI no implementa un lock propio: si se programara dos veces en paralelo, dos escrituras de watermark competirían. Es una limitación **declarada** y una razón más para que WP-005H no se active sin diseño de lease.
- **`since`:** el provider del runtime no lo expone; el delta es acotado + deduplicado. Un backlog > 1 000 velas se rechaza y exige `reconcile`.
- **Equivalencia de datos:** demostrada sobre datos reales capturados hoy (12 series), en ventana de 24 h. No cubre regímenes anómalos del exchange (mantenimiento, huecos del venue) más allá de los casos simulados.
- **Ventanas:** siguen existiendo hasta que se autorice WP-005H. Medido: 5 tareas de consola cada 15 min.

## 9. Decisión

| Capacidad | Decisión | Base |
|---|---|---|
| Lector incremental con watermark y cobertura probada | **ADOPT** (offline, no activado) | −88,3 % peticiones, −98,9 % velas, 12/12 series idénticas |
| `MarketSnapshot` PIT + gate causal | **ADOPT** | 4/4 causales, HTF futuro excluido, fallo cerrado probado |
| `EventGate` + caché de respuestas | **EXPERIMENT** | correcto y con presupuesto 0, pero **no hay proveedor real** (`BLOCKED_MODEL_API`) |
| Re-registro windowless de las tareas | **DEFER** | WP-005H: requiere autorización de host y rollback ensayado |
| Migrar `ST6`/`ALPHA002`/`forward_collector` al lector compartido | **DEFER** | fuera de alcance; hoy no usan el connector |
| Apagar cualquier descarga | **REJECT** | ninguna resultó redundante sin sustituto |
