# TSK-104 - OHLCV Scheduler: Requirements (Command 01)

> Documento de requisitos elicitados para `src/trading_bot/scheduler/`.
> Consumido por `02-bdd.md`, `03-specify.md`, `04-plan.md`, `05-tasks.md`.
> Metodologia: `.ai/commands/01-requirements.md`.
> Estado del ticket: `tasks/sprint-002.md` (live) y `tasks/backlog.md`.

---

## 1. Resumen ejecutivo

TSK-104 implementa el **OHLCV Scheduler** sobre la base desacoplada
construida por TSK-099 (configuracion tipada Pydantic), TSK-101
(`ExchangeConnector` / `CCXTExchangeConnector`) y TSK-102 (`OHLCVStore`
+ `OHLCVFetcher`). El scheduler mantiene el `OHLCVStore` fresco
disparando pulls periodicos del `OHLCVFetcher` sobre el
`universe.pairs`, dentro de la ventana `active_hours_start/end`,
respetando el `kill_switch` y aislando errores transitorios.

El scanner (TSK-103, mergeado via F5 squash) **NO** es responsable
de scheduling: consume `OHLCVStore` directamente. El scheduler es el
unico componente que escribe al store en runtime.

El scheduler corre como `asyncio` task dentro del mismo proceso que
el scanner. NO es un proceso separado (no es cron / systemd timer).

## 2. Alcance

### 2.1 En scope (TSK-104)

- Disparar pulls periodicos del `OHLCVFetcher` sobre `universe.pairs`.
- Respetar `runtime.scheduler.active_hours_start/end` (default 0-23).
- **Cache hit**: si `OHLCVStore` tiene la ultima vela para un par con
  `freshness_window_minutes` no expirado, NO pull.
- **Cache miss**: pull fresco + upsert en `OHLCVStore` (idempotente,
  PK compuesta `(symbol, timestamp)`).
- **Kill-switch**: si `risk.kill_switch_enabled=true`, abortar el pull
  pendiente + log `scheduler.paused.kill_switch` SIN invocar el fetcher.
- **Aislamiento de errores**: una excepcion transitoria en un par no
  aborta el resto del batch.
- **Mode-aware**: `paper` usa sandbox=True; `live` usa endpoint real
  (sandbox=False); `backtest`/`research` usan
  `MarketDataSourceProtocol` synthetic (NO connector real, NO
  sandbox flag). `shadow_live` se trata identico a `live` (mismo
  patron que `UniverseScanner._SCANNER_MODE_MAP` en TSK-103): la
  diferencia entre `live` y `shadow_live` solo afecta `execution`
  (shadow NO envia ordenes reales), fuera del scheduler.
- **Observabilidad**: structlog con `scheduler_iteration_id`,
  `duration_ms`, `pulls_attempted`, `pulls_succeeded`, `pulls_failed`,
  `cache_hits`, eventos `scheduler.pull.completed` /
  `scheduler.pull.skipped` / `scheduler.pull.failed` /
  `scheduler.iteration.completed`.
- **Graceful shutdown** en SIGINT: cierra el loop limpiamente, sin
  zombie threads.
- **Cross-layer**: scheduler solo importa `trading_bot.market_data` y
  `trading_bot.config`. NO toca `execution`, `strategies`, `risk`,
  `portfolio` (cubierto por test AST, mismo patron que TSK-103 RF-8).

### 2.2 Fuera de scope (TSK-104, sigue en tickets posteriores)

- Ejecucion de ordenes (Fase 9, ticket live release gate).
- Estrategias y generacion de senales (Fase 4, `TSK-4xx`).
- Risk manager position sizing / drawdown (Fase 5, `TSK-5xx`).
- Indicadores tecnicos (Fase 2, `TSK-2xx`).
- Multi-exchange simultaneo (ADR-0006 fija Binance+CCXT unico).
- Backfill historico (cubierto por TSK-102 `OHLCVStore`).
- WebSocket / streaming (TSK-104 es pull-based; tick <= minuto).
- Multi-timeframe scheduling (un solo `primary_timeframe` por proceso).

## 2.3 Contrato de `SchedulerResult`

El scheduler retorna un `SchedulerResult` dataclass (frozen + slots) por
cada `run_once()`, con los counters observados via structlog y la
duracion de la iteracion:

| Campo                   | Tipo   | Descripcion                                                                 |
| ----------------------- | ------ | --------------------------------------------------------------------------- |
| `pulls_attempted`       | `int`  | Total de pares en el batch (incluye cache hits y pull failures).            |
| `pulls_succeeded`       | `int`  | Pulls que retornaron OK y se upsertaron al `OHLCVStore`.                    |
| `pulls_failed`          | `int`  | Pulls que fallaron tras agotar retries (HTTP 429 agotado, timeout, etc).   |
| `cache_hits`            | `int`  | Pares omitidos por freshness (no pull).                                     |
| `duration_ms`           | `int`  | Wall-clock duration de la iteracion completa.                               |
| `scheduler_iteration_id`| `UUID` | UUIDv4 unico por iteracion, para correlacionar con structlog.               |

**Invariante** (sobre el subconjunto que pasa filtros `active_hours` y `kill_switch`): `pulls_attempted == pulls_succeeded + pulls_failed + cache_hits`. Pares fuera de `active_hours` (RF-2) o bajo `kill_switch` (RF-3) se filtran pre-batch y NO aparecen en contadores.

## 3. Requisitos funcionales (RF)

| ID   | Requisito                                                          | Criterio de aceptacion                                                              |
| ---- | ------------------------------------------------------------------ | ----------------------------------------------------------------------------------- |
| RF-1 | `Scheduler.run_once()` dispara pull sobre `universe.pairs`.         | Test: 25 pares en `universe.pairs` -> 25 invocaciones al fetcher (o cache hits).     |
| RF-2 | Pull se omite si `current_time ∉ [active_hours_start, end)`.        | Test parametrizado 0-23 cubre dentro/fuera de ventana (default 0-23 = nunca skip).  |
| RF-3 | Pull se aborta si `risk.kill_switch_enabled=true`.                 | Return sin invocar fetcher; log `scheduler.paused.kill_switch` UNA vez.             |
| RF-4 | Cache hit: skip pull si `last_candle_ts >= current_ts - primary_timeframe AND current_ts - last_candle_ts < freshness_window_min`. | Test: vela del periodo actual (4 min en TF 5m, freshness 5m) -> skip; vela de periodo previo (10 min en TF 5m, freshness 5m) -> pull; vela de 1 hora -> pull. |
| RF-5 | `OHLCVFetcherTimeoutError` en un par no aborta el batch.           | Counter `pulls_failed+=1`; resto de pares recibe pull normal.                        |
| RF-6 | Structlog eventos `pull.completed` / `skipped` / `failed` con 4 counters. | Test captura 4+ eventos con `scheduler_iteration_id`, `duration_ms`, counters. |
| RF-7 | `live` usa connector con sandbox=False; `paper` usa connector con sandbox=True. **Mode change (runtime.mode flip) requiere re-inyeccion del connector via DI; NO se muta el flag `sandbox` in-place (CCXTExchangeConnector lo setea en `__init__` antes de `load_markets`, ver TSK-101).** | Test parametrizado 2 modos (live + paper) verifica flag `sandbox` en el connector inyectado; test explicito de re-inyeccion cubre el mode-flip. |
| RF-7b | `backtest|research` usa `MarketDataSourceProtocol` synthetic impl (NO connector, NO sandbox flag). | Test: en modo backtest el OHLCVFetcher es un mock que retorna velas sinteticas; el connector real no se invoca. |
| RF-8 | Cross-layer: solo importa `market_data` + `config` (no `execution`/`strategies`/`risk`/`portfolio`). | Test AST: scanner detecta imports de capas vedadas y falla el test. |
| RF-9 | Cobertura >= 90% en `src/trading_bot/scheduler/`.                  | `pytest --cov-fail-under=90` verde.                                                  |
| RF-10| mypy strict verde.                                                 | `mypy src/trading_bot/scheduler/` exit 0.                                           |

## 4. Requisitos no funcionales (RNF)

| ID    | Requisito                                                    | Criterio                                                                |
| ----- | ------------------------------------------------------------ | ----------------------------------------------------------------------- |
| RNF-1 | Latencia P95 de un batch (25 pares sandbox) <= 6s.           | Benchmark contra testnet Binance.                                       |
| RNF-2 | Logs JSON con `request_id` + `scheduler_iteration_id`.       | structlog binding por iteracion.                                         |
| RNF-3 | Determinismo: re-run con fake clock produce mismo output.    | Test property-based con `hypothesis` + `freezegun.freeze_time`.          |
| RNF-4 | Graceful shutdown en SIGINT en <= 2s; CancelledError se propaga del inner await al caller sin ser tragado. | Test: SIGINT durante run() cierra loop sin zombie threads en <= 2s; `CancelledError` del inner `await run_once()` propaga al caller. |
| RNF-5 | Idempotencia: pull repetido del mismo timeframe no duplica. | `OHLCVStore` PK compuesta `(symbol, timestamp)` + upsert last-write-wins. |
| RNF-6 | Memoria por iteracion < 50 MB.                              | `tracemalloc` snapshot.                                                 |

## 5. Casos limite y modos de fallo (CL)

| ID  | Caso                                                                 | Mitigacion                                                                 |
| --- | -------------------------------------------------------------------- | -------------------------------------------------------------------------- |
| CL-1 | `universe.pairs` vacio.                                              | Log warn `scheduler.universe.empty`, retorna `SchedulerResult(pulls_attempted=0)` sin pull, no exception. |
| CL-2 | `OHLCVFetcherTimeoutError` en un par.                                | Log warn, counter `pulls_failed+=1`, continuar.                            |
| CL-3 | Clock skew (system time salta atras o adelante).                     | Log warn, re-evaluar ventana activa en siguiente tick.                     |
| CL-4 | `Scheduler.run()` invocado dos veces en quick succession.            | Segunda llamada es no-op via asyncio.Lock + check de estado `_running`.    |
| CL-5 | `active_hours_start/end` faltantes en config.                        | Default `0..23` (todo el dia, no skip por horario).                        |
| CL-6 | `OHLCVStore` no inicializado (tabla falta).                          | Init lazy; log warn + raise `ConfigurationError` con hint a `tasks/decisions.md`. |
| CL-7 | Modo `backtest` con fixture offline.                                 | Fetcher inyectado retorna velas sinteticas (test-only, no I/O real).      |
| CL-8 | Cache hit + OHLCVStore tiene vela corrupta (NaN, high<low).          | TSK-102 OHLCVFetcher ya valida en pull; cache hit es trusted. Log info.   |
| CL-9 | Exchange rate limit (HTTP 429) durante pull batch.                   | Respetar header `Retry-After` si presente (1-60s); si no, backoff jittered (1s, 2s, 4s +/- 25%); reintentar 3 veces antes de fail. |

## 6. Dependencias y asunciones

- **TSK-099** (config tipada) - mergeado en `main` (`9eed3fd`, ADR-0010).
- **TSK-101** (`CCXTExchangeConnector`) - mergeado en `main` (PR #12).
- **TSK-102** (`OHLCVStore` + `OHLCVFetcher`) - mergeado en `main` (PR #13).
- **TSK-103** (UniverseScanner) - mergeado en `main` via F5 squash-merge.
  El scanner consume `OHLCVStore` directamente (read-only). El scheduler
  es el unico writer en runtime.
- **ADR-0006** (Binance via CCXT, sandbox paper) - sostenido.
- **ADR-0012** (gate-recovery) - sostenido; `numpy<2.1` pin.
- **ADR-0013** (TSK-102/103 scope reconciliation) - sostenido.

**Asunciones**:

- El scheduler corre como `asyncio` task dentro del mismo proceso que
  el scanner (mismo event loop). NO es cron / systemd timer.
- La `freshness_window_minutes` es configurable via
  `runtime.scheduler.freshness_minutes` (default 5 para sandbox, 1 para live).
- El scheduler expone `run_once() -> SchedulerResult` ademas de
  `run() -> None` (loop), para tests deterministas.
- El kill-switch check se hace **antes** de cualquier I/O (incluido
  el cache hit check).
- El scheduler NO coordina con el scanner via lock; ambos son
  cooperativos via el event loop de asyncio.

## 7. Criterios de aceptacion global

1. Los N tickets del plan (`04-plan.md`) ejecutados sin DERAIL de fase.
2. Cobertura >= 90% en `src/trading_bot/scheduler/`.
3. ruff format + ruff check verde.
4. mypy strict verde.
5. Pre-flight `pytest tests/unit/scheduler/ -q` >= 12 tests verdes.
6. BDD 17 escenarios verde (`bdd/features/ohlcv_scheduler.feature`).
7. Reviewer verdict = clean (sin P0).
8. Cross-layer enforcement verde (test AST, mismo patron que TSK-103).
9. 6 quality gates verde per `docs/ci.md` seccion 3.

## 8. Siguiente fase (handoff a `02-bdd.md`)

Los RF-1..RF-7b (11 functional reqs: RF-1..RF-7 + RF-7b) y CL-1..CL-9 se traducen a escenarios Gherkin en
`bdd/features/ohlcv_scheduler.feature` (nuevo archivo, no se toca
`market_scanner.feature`) y al documento resumen `02-bdd.md`.
