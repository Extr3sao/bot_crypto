# TSK-104 - OHLCV Scheduler: Architectural Plan (Command 04)

> Plan incremental de implementacion. 4 tickets pequenos, ordenados
> por reversibilidad y verifica-antes-de-avanzar. Metodologia:
> `.ai/commands/04-plan.md`. Consume `03-specify.md` (contratos
> cerrados) y `01-requirements.md` (RF/RNF/CL) + `02-bdd.md` (17
> escenarios Gherkin).

---

## Pre-condiciones

1. TSK-099 mergeado en `main` (ya verdadero; `FlatEnvAliasSource`).
2. TSK-101 mergeado en `main` (PR #12; `CCXTExchangeConnector` con
   `sandbox` pineado en `__init__`, retries tenacity, client_order_id
   idempotente).
3. TSK-102 mergeado en `main` (PR #13; `OHLCVStore` SQLite + WAL,
   `OHLCVFetcher` con pull+validate+cache).
4. TSK-103 mergeado en `main` via F5 squash-merge (PR #13/F5;
   `UniverseScanner` con cross-layer enforcement AST). El scanner
   consume `OHLCVStore` read-only; el scheduler es el unico writer
   en runtime (asi no hay contention en el SQLite WAL).
5. ADR-0013 firmada (TSK-102/103 scope reconciliation). Aplicar
   mismo criterio al scheduler: el `OHLCVSourceProtocol` es la
   abstraccion que el scheduler conoce; `OHLCVFetcher` +
   `OHLCVStore` son detalles de `market_data` que el scheduler
   NO importa directamente.
6. PR #7 (TSK-104 spec pack: 01-requirements + 02-bdd + 03-specify)
   mergeado en `main`. Cero codigo antes de merge del spec.

## Fases

### F1. TSK-104.1 - Tipos y protocolos

- **Objetivo**: tener el contrato publico cerrado antes de cualquier
  logica. Cero logica de negocio.
- **Archivos nuevos**:
  - `src/trading_bot/scheduler/__init__.py` (re-exports).
  - `src/trading_bot/scheduler/types.py` (`SchedulerResult`,
    `PullOutcome`, `CacheHitDecision`, `CacheState`, `Literal` de
    motivos `SkipReason` + `PullFailureReason`).
  - `src/trading_bot/scheduler/protocols.py` (`OHLCVSourceProtocol`,
    `ConnectorFactory`, `PullMetricsSink`).
  - `src/trading_bot/scheduler/exceptions.py`
    (`SchedulerError`, `KillSwitchActiveError`, `EmptyUniverseWarning`,
    `RetryExhaustedError`).
- **Tests**:
  - `tests/unit/scheduler/test_types.py`: dataclass frozen, slots,
    campos obligatorios, invariante `SchedulerResult` post-filter
    batch.
  - `tests/unit/scheduler/test_protocols.py`: `runtime_checkable`
    sobre `OHLCVSourceProtocol`; `ConnectorFactory` callable tipada.
- **Gate**: `pytest tests/unit/scheduler/test_types.py
  tests/unit/scheduler/test_protocols.py` >= 8 verde;
  `mypy src/trading_bot/scheduler/` exit 0.
- **Reversibilidad**: borrar 4 archivos, cero side-effects.

### F2. TSK-104.2 - Cache + filtros pre-batch

- **Objetivo**: pure functions y guards deterministas, testeables sin
  I/O ni freezegun (mas alla del `clock_fn` inyectable en el cache
  predicate).
- **Archivos nuevos**:
  - `src/trading_bot/scheduler/cache.py`
    (`evaluate_cache_hit`, pure function RF-4).
  - `src/trading_bot/scheduler/filters.py` (`check_kill_switch`,
    `check_active_hours`, `ActiveHoursWindow` dataclass).
- **Tests**:
  - `tests/unit/scheduler/test_cache.py`: parametrizado 12+ casos
    cubriendo `EMPTY` / `STALE` / `FRESH` / boundary (TF=1m,
    freshness=1m, age=exactamente-1m → STALE per strict `<`).
  - `tests/unit/scheduler/test_filters.py`: parametrizado `mode`
    + `kill_switch` + `active_hours` (incluye wrap-around 22..6).
- **Gate**: `pytest tests/unit/scheduler/test_cache.py
  tests/unit/scheduler/test_filters.py` >= 14 verde.
- **Reversibilidad**: borrar 2 archivos, F1 intacta.

### F3a. TSK-104.3a - Orquestador Skeleton

- **Objetivo**: pegar F1+F2 en un orchestrator inicial (skeleton).
  Construir `__init__` con DI, iteracion basica sin retries ni
  re-inyeccion compleja, cortando en el boundary delegado de
  `_process_one_pair` (pull delegate a F3b). Pine contract:
  `connector_factory: ConnectorFactory | None = None` PERO la
  validacion runtime se hace en `connector_reinjector()` (F3b,
  opcion b pineada en R1) — no en `__init__`.
- **Archivos nuevos**:
  - `src/trading_bot/scheduler/scheduler.py` (skeleton:
    `OHLCVScheduler`, `_SchedulerCounters`, `run_once()` async
    unit, `_execute_iteration()` con kill switch + empty universe
    + per-pair loop, `_process_one_pair()` con active_hours +
    cache_hit + pull delegate a F3b).
- **Tests** (6 tests):
  - `tests/unit/scheduler/test_scheduler_skeleton.py`:
    - `test_run_once_empty_universe_returns_zero_counters` (CL-1)
    - `test_run_once_kill_switch_aborts_pre_batch` (RF-3)
    - `test_run_once_active_hours_skip_per_pair` (RF-2)
    - `test_run_once_cache_hit_skips_pull` (RF-4)
    - `test_run_once_pull_succeeded_upserts_to_store` (RF-1,
      mock pull que retorna OK)
    - `test_run_once_pull_failed_does_not_abort_batch`
      (CL-2 + RF-5, mock pull que raises)
  - `tests/unit/scheduler/test_reentrancy.py` (2 tests):
    - `RuntimeError` si `run_once()` ya en curso
    - `RuntimeError` si `run()` ya en curso y se invoca `run()`
      de nuevo
- **Gate**: `pytest tests/unit/scheduler/test_scheduler_skeleton.py
  tests/unit/scheduler/test_reentrancy.py` >= 7 verde; mypy strict
  verde; ruff format + ruff check verdes; cobertura >= 90% en
  el modulo.
- **Reversibilidad**: borrar 1 archivo, F1-F2 intactas.

### F3b. TSK-104.3b - Retries, Eventos, Loop, Mode-Flip, Cross-Layer

- **Objetivo**: completar la logica fina: `_fetch_with_retry` con
  jitter + Retry-After (CL-9), `run()` async loop con
  `asyncio.sleep` + CancelledError propagation, `connector_reinjector()`
  para RF-7 mode-flip, los 7 structlog events con single-emission
  point, reentrancy guard extendido, y el cross-layer AST test.

> **TODO(R1) — `connector_reinjector` valida factory None en runtime
> (opcion b pineada).** Si el caller invoca
  `connector_reinjector(new_mode)` con `new_mode in {paper, live,
  shadow_live}` y `self._connector_factory is None`, elevar
  `ConfigurationError` con hint a `tasks/decisions.md`. Esto
  resuelve el mode-flip edge case: el scheduler puede construirse
  con `mode=backtest` (sin factory) y luego intentar flip a `live`
  — el flip falla FAST con error claro, no crashea mid-iteration.

- **Archivos modificados**:
  - `src/trading_bot/scheduler/scheduler.py` (anadir
    `_fetch_with_retry`, `run()`, `connector_reinjector()`, 7
    structlog events, extension reentrancy guard).
  - `tests/unit/scheduler/test_cross_layer.py` (nuevo): AST test
    que verifica que `scheduler.py` no importa
    `execution`/`strategies`/`risk`/`portfolio`/`paper`/
    `observability`. Mismo patron que
    `tests/unit/scanner/test_cross_layer.py`.
- **Tests** (13 tests):
  - `tests/unit/scheduler/test_retry.py` (3 tests):
    - `test_fetch_with_retry_jitter_on_429` (CL-9 positive,
      429 + jitter 1s/2s/4s ± 25%)
    - `test_fetch_with_retry_exhausted_after_3` (CL-9 negative,
      3 retries agotados → `RetryExhaustedError`)
    - `test_fetch_with_retry_respects_retry_after_header` (CL-9,
      1-60s clamp; valor > 60s clampea a 60s)
  - `tests/unit/scheduler/test_run_loop.py` (2 tests):
    - `test_run_loop_cancelled_error_propagates` (RNF-4)
    - `test_run_loop_graceful_shutdown_under_2s` (RNF-4 SLO)
  - `tests/unit/scheduler/test_connector_reinjector.py` (3 tests):
    - `test_connector_reinjector_closes_old_connector` (RF-7)
    - `test_connector_reinjector_constructs_new_one` (RF-7)
    - `test_connector_reinjector_does_not_mutate_sandbox` (RF-7,
      pine que se construye nuevo, NO se muta flag in-place)
    - `test_connector_reinjector_raises_when_factory_none_and_mode_needs_connector`
      (R1 opcion b)
  - `tests/unit/scheduler/test_structlog_events.py` (3 tests):
    - captura `structlog.testing.capture_logs` y verifica los 7
      eventos
    - single-emission point: `iteration.completed` se emite UNA
      vez por `run_once()`, con `early_exit` tag
    - el log incluye `scheduler_iteration_id` UUID + `duration_ms`
      + los 5 counters
  - `tests/unit/scheduler/test_cross_layer.py` (2 tests):
    - `test_scheduler_does_not_import_forbidden_layers`
    - `test_scheduler_only_imports_market_data_and_config`
- **Gate**: **6 quality gates** de `docs/ci.md` §3 — ruff check +
  ruff format + mypy strict + pytest --cov-fail-under=90 + safety
  check + pip-audit — todos verde. `pytest tests/unit/scheduler/`
  >= 20 verde total (7 de F3a + 13 de F3b).
- **Reversibilidad**: borrar archivos F3b, F3a sigue testeando
  (skeleton no depende de retry/run-loop/re-injector).

### F4. TSK-104.4 - Wiring con Settings + BDD + 6 quality gates

- **Objetivo**: cerrar el ciclo con `trading_bot.config.Settings`
  real, anadir los 17 escenarios BDD, registrar ADR-0014
  (concurrencia secuencial pineada en 03-specify §6.2), actualizar
  backlog/sprint-002, y validar los 6 quality gates end-to-end.
  Cross-layer AST test ya cubierto en F3b (no se duplica).
- **Cambios**:
  - En `src/trading_bot/app.py`: anadir comando `scheduler-run` que
    ejecuta `OHLCVScheduler.run()` con un settings + source_factory
    inyectado. Replica el patron de `scan --demo` (TSK-103).
  - En `src/trading_bot/scheduler/scheduler.py`: el `Settings` real
    se carga via `load_settings()` en el entrypoint; el
    `source_factory` se construye segun `runtime.mode` (ver tabla
    §6.1 de 03-specify).
  - Anadir los 17 escenarios a `tests/bdd/step_defs/test_scheduler_steps.py`
    (siguiendo patron TSK-103.5.2.2-7 step definitions).
  - Registrar decision D-TSK104 (concurrencia secuencial pineada
    en 03-specify §6.2) en `tasks/decisions.md` como **ADR-0014**
    (forward-ref o nueva).
  - Actualizar `tasks/backlog.md` y `tasks/sprint-002.md`:
    TSK-104 cerrado, siguiente ticket.
- **Pre-condicion bloqueante**: PR #7 (este spec pack) debe estar
  mergeado en `main` ANTES de iniciar F4.
- **Gate**: BDD 17/17 verde + 6 quality gates (los mismos que F3b)
  todos verde end-to-end. Full pre-flight local: `ruff format`,
  `ruff check`, `mypy`, `pytest --cov` con cobertura >= 90%,
  `safety check`, `pip-audit`.
- **Reversibilidad**: borrar scenarios y ADR; F1-F3b intactas.

## Ticket breakdown (resumen)

| ID          | Tam | FASE | Riesgo | DoD resumida                                        |
| ----------- | --- | ---- | ------ | --------------------------------------------------- |
| TSK-104.1   | S   | 1    | L      | Tipos frozen + protocolos + 8 tests verdes          |
| TSK-104.2   | M   | 1    | L      | CacheHitPredicate + 2 filtros pre-batch + 14 tests  |
| TSK-104.3a  | M   | 1    | M      | Skeleton `__init__` + run_once + 7 tests + reentrancy |
| TSK-104.3b  | M   | 1    | H      | Retries + run loop + events + mode-flip + cross-layer |
| TSK-104.4   | S   | 1    | M      | BDD 17/17 + Settings wiring + ADR-0014 + 6 gates   |

Tam: S = small (<200 LoC), M = medium (200-500 LoC), L = large (500+ LoC).

## Orden de ejecucion

```
F1 (TSK-104.1) ─> F2 (TSK-104.2) ─> F3a (TSK-104.3a) ─> F3b (TSK-104.3b) ─> F4 (TSK-104.4)
```

F1 trivialmente paralelo con F2 (zero imports cruzados entre tipos
y pure functions). F3 depende de F1+F2. F4 depende de F3 + que el
spec PR #7 este mergeado en `main`.

## Riesgos del plan

- **R1 (HIGH)**: `connector_factory=None` para backtest/research
  requiere decision defensiva. Si un caller construye el scheduler
  con `mode=backtest` (sin factory, valido) y luego hace flip a
  `live` via `connector_reinjector`, el scheduler intenta usar
  una factory `None` y revienta. Mitigacion (opcion b pineada en
  F3b TODO): `connector_reinjector(new_mode)` valida en runtime;
  si `new_mode in {paper, live, shadow_live}` y
  `self._connector_factory is None`, levanta `ConfigurationError`
  con hint a `tasks/decisions.md` (fail-fast, no crash
  mid-iteration). Cubierto por test
  `test_connector_reinjector_raises_when_factory_none_and_mode_needs_connector`.
- **R2 (MED)**: reentrancy guard con `asyncio.Lock` puede causar
  deadlock si el caller anida `run_once()` desde dentro de un
  callback. Mitigacion: pine contract explicito en docstring +
  `RuntimeError` claro. Tests pinean el caso.
- **R3 (MED)**: `evaluate_cache_hit` boundary case (age == window)
  es estricto `<`, no `<=`. Si en el futuro se quiere `<=`, hay
  que actualizar el BDD scenario parametrizado. Mitigacion: 1-line
  note en el codigo + pine del boundary en test parametrizado.
- **R4 (LOW)`: cobertura 90% puede quedar justa en F3 si el
  orquestador crece con mas code paths. Mitigacion: omit defensivo
  solo para ramas `pragma: no cover` marcadas explicitamente
  (mismo criterio que TSK-103).
- **R5 (LOW)**: cross-layer AST test es fragil (parsing AST de
  Python). Mitigacion: usar el mismo helper
  ``tests/unit/scanner/test_cross_layer.py::_parse_imports()``
  pineado en TSK-103.
- **R6 (LATENT)**: el `clock_fn` inyectable en `evaluate_cache_hit`
  solo aplica al `current_ts`. Si la freshness_window o la
  primary_timeframe vienen de Settings y cambian mid-flight, el
  cache hit se vuelve inconsistente. Mitigacion: Settings se lee
  UNA vez en `__init__` del orquestador y se pasa inmutable al
  `evaluate_cache_hit` por iteracion.
- **R7 (HIGH)**: race condition entre scheduler (writer unico) y
  scanner (reader) en SQLite `OHLCVStore`. WAL asincrono previene
  bloqueos pero el reader podria retornar parciales si el writer
  esta mid-`executemany`. Mitigacion explicita (pine contract en
  F3b + scanner's `__init__` per TSK-102): (a) el writer
  (`OHLCVScheduler._process_one_pair` → `OHLCVFetcher.fetch_and_cache`
  → `OHLCVStore.upsert_ohlcv`) usa `executemany` atomico + la
  connection ya tiene `isolation_level=None` + `journal_mode=WAL`
  (TSK-102); (b) el reader (`UniverseScanner` → `OHLCVStore.get_ohlcv`)
  invoca `.fetchall()` DESPUES de que `.executemany` retorne, no
  concurrentemente. Secuencialidad garantizada por el event loop
  de asyncio: tanto `scheduler.run_once()` como `scanner.run()` son
  coroutines que se intercalan en `await` points, NO en I/O SQL
  sincrono. Cubierto por test que verifica que el scanner no ve
  un batch parcial cuando el scheduler hace upsert concurrente.

## Criterio de salida del plan

- Los 5 tickets (F1 + F2 + F3a + F3b + F4) pueden entrar en marcha
  predeciblemente (F1+F2 asincronos seguros, F3a → F3b → F4
  secuencial).
- Cada ticket tiene DoD medible (test count + 6-gate list).
- El plan no asume capacidad adicional de reviewer: el flujo
  `06-implement-next.md` + `code-reviewer-minimax-m3` cubre cada
  PR pequeno.
- **PR #7 (este spec pack) mergeado a `main` ANTES de iniciar F4**
  (pre-condicion bloqueante; sin spec en main, F4 no puede correr
  BDD contra Settings reales).
- **Cross-layer AST test verde al final de F3b** (no esperar a
  F4; la constraint es sobre `scheduler.py` que es F3b).
- ADR-0014 firmada antes de merge de TSK-104.4 (decision sobre
  concurrencia secuencial pineada en 03-specify §6.2).

## Siguiente fase (handoff a `05-tasks.md`)

`05-tasks.md` expande cada uno de los 5 macro-tickets en tareas
accionables, cada una cabe en 1 commit. Skeleton breakdowns:

- **F1 (TSK-104.1 — Tipos y protocolos, 3 stubs)**:
  - TSK-104.1.1: `types.py` (SchedulerResult, PullOutcome, CacheHitDecision, CacheState, 2 Literals)
  - TSK-104.1.2: `protocols.py` (OHLCVSourceProtocol, ConnectorFactory, PullMetricsSink)
  - TSK-104.1.3: `exceptions.py` (SchedulerError, KillSwitchActiveError, EmptyUniverseWarning, RetryExhaustedError)
- **F2 (TSK-104.2 — Cache + filtros pre-batch, 2 stubs)**:
  - TSK-104.2.1: `cache.py` (evaluate_cache_hit pure function RF-4)
  - TSK-104.2.2: `filters.py` (check_kill_switch RF-3, check_active_hours RF-2, ActiveHoursWindow)
- **F3a (TSK-104.3a — Skeleton, 3 stubs)**:
  - TSK-104.3a.1: `OHLCVScheduler.__init__` con DI
  - TSK-104.3a.2: `_execute_iteration` con kill switch + empty universe + per-pair loop
  - TSK-104.3a.3: `_process_one_pair` con active_hours + cache_hit + pull delegate
- **F3b (TSK-104.3b — Retries + loop + events + mode-flip + cross-layer, 5 stubs)**:
  - TSK-104.3b.1: `_fetch_with_retry` con jitter + Retry-After (CL-9)
  - TSK-104.3b.2: `run()` async loop + CancelledError propagation (RNF-4)
  - TSK-104.3b.3: `connector_reinjector(new_mode)` con validacion factory None (R1 opcion b)
  - TSK-104.3b.4: 7 structlog events + single-emission point
  - TSK-104.3b.5: cross-layer AST test (test_cross_layer.py)
- **F4 (TSK-104.4 — Wiring + BDD + ADR-0014 + 6 gates, 4 stubs)**:
  - TSK-104.4.1: `app.py scheduler-run` command + source_factory wiring
  - TSK-104.4.2: 17 BDD scenarios en `test_scheduler_steps.py`
  - TSK-104.4.3: ADR-0014 firma en `tasks/decisions.md` (concurrencia secuencial)
  - TSK-104.4.4: 6 quality gates verde end-to-end (los mismos que F3b)

Total ejecutable end-to-end ~17-22 stubs distribuidos en los 5
tickets. Reversibilidad: borrar el archivo/stub deja F1-F4
anteriores testeando.
