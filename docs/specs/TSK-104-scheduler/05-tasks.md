# TSK-104 - OHLCV Scheduler: Tasks (Command 05)

> Tareas pequenas, trazables y ejecutables una a una. Cada tarea
> cabe en un commit. Metodologia: `.ai/commands/05-tasks.md`.
> Consume `04-plan.md` (5 macro-tickets: F1 + F2 + F3a + F3b + F4).
> Distribucion ejecutable end-to-end = **17 stubs atómicos**.

Convenciones:
- `P` = prioridad dentro del ticket (1 = mas alta).
- `dep` = dependencias (`-` si ninguna).
- `DoD` = Definition of Done.

---

## TSK-104.1 - Tipos y protocolos (F1)

| ID            | Descripcion                                                                                    | Archivos                                                  | Tests esperados                                                                              | dep | P | DoD                                                                            |
| ------------- | ---------------------------------------------------------------------------------------------- | --------------------------------------------------------- | -------------------------------------------------------------------------------------------- | --- | - | ------------------------------------------------------------------------------ |
| TSK-104.1.1   | Dataclasses frozen: `SchedulerResult` (6 campos + invariante), `PullOutcome` (6 campos),       | `src/trading_bot/scheduler/types.py`                      | `test_types.py::test_scheduler_result_frozen`, `...::test_pull_outcome_frozen`,             | -   | 1 | mypy strict verde; `FrozenInstanceError` al mutar.                              |
|               | `CacheHitDecision` (7 campos), `CacheState` (Enum 4 valores), `SkipReason` +                    |                                                           | `...::test_cache_hit_decision_frozen`, `...::test_cache_state_enum_values`,                  |     |   |                                                                                  |
|               | `PullFailureReason` Literals cerrados.                                                          |                                                           | `...::test_skip_reason_literal_values`, `...::test_pull_failure_reason_literal_values`,    |     |   |                                                                                  |
|               |                                                                                                |                                                           | `...::test_scheduler_result_invariante_pulls_attempted_eq_sum`                              |     |   |                                                                                  |
| TSK-104.1.2   | Protocols: `OHLCVSourceProtocol` (runtime_checkable, 2 metodos async),                          | `src/trading_bot/scheduler/protocols.py`                  | `test_protocols.py::test_ohlcv_source_protocol_runtime_checkable`,                          | TSK-104.1.1 | 1 | `isinstance(fake_source, OHLCVSourceProtocol) -> True`.                            |
|               | `ConnectorFactory` (Callable tipada), `PullMetricsSink` (Protocol con 4 metodos async).        |                                                           | `...::test_connector_factory_callable_type`, `...::test_pull_metrics_sink_protocol`         |     |   |                                                                                  |
| TSK-104.1.3   | Excepciones custom: `SchedulerError` base, `KillSwitchActiveError`,                            | `src/trading_bot/scheduler/exceptions.py`                 | `test_types.py::test_exceptions_inherit_scheduler_error`,                                   | TSK-104.1.1 | 2 | Las 4 clases importables; solo `KillSwitchActiveError` y `RetryExhaustedError`  |
|               | `EmptyUniverseWarning`, `RetryExhaustedError`.                                                     |                                                           | `test_exceptions.py::test_retry_exhausted_chains_last_exception`                            |     |   | heredan de `SchedulerError`; `EmptyUniverseWarning` de `UserWarning`.             |
| TSK-104.1.4   | `__init__.py` con docstring + re-exports (`SchedulerResult`, `PullOutcome`,                      | `src/trading_bot/scheduler/__init__.py`                   | `tests/unit/scheduler/__init__.py` vacio                                                     | TSK-104.1.1..1.3 | 2 | `python -c "import trading_bot.scheduler; print(SchedulerResult)"` exit 0.        |
|               | `CacheHitDecision`, `CacheState`, 2 Literals, 3 Protocols, 4 Excepciones, `ConnectorFactory`).  |                                                           |                                                                                              |     |   |                                                                                  |

Gate de F1: `pytest tests/unit/scheduler/test_types.py
tests/unit/scheduler/test_protocols.py` >= 8 verde;
`mypy src/trading_bot/scheduler/` exit 0.

---

## TSK-104.2 - Cache hit + filtros pre-batch (F2)

| ID            | Descripcion                                                                                       | Archivos                                                  | Tests esperados                                                                                              | dep       | P | DoD                                                                                            |
| ------------- | ------------------------------------------------------------------------------------------------- | --------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------ | --------- | - | ---------------------------------------------------------------------------------------------- |
| TSK-104.2.1   | `evaluate_cache_hit` pure function (RF-4). 5 paths: EMPTY / STALE (fp)/ FRESH / STALE (corrupt). | `src/trading_bot/scheduler/cache.py`                      | `test_cache.py::test_cache_hit_decision_empties`, `...::test_cache_hit_decision_fresh`,                    | TSK-104.1.1 | 1 | Boundary: TF=1m, freshness=1m, age==exactly-1m -> STALE (strict `<`).                              |
|               | Pine contract: `last_candle_ts=None` -> EMPTY; period prev -> STALE; period actual + fresh -> FRESH. |                                                           | `...::test_cache_hit_decision_stale_outside_window`, `...::test_cache_hit_boundary_strict_lt`,              |     |   | Cubrir parametrizado 12+ casos (boundary ±1s, EMPTY / STALE / FRESH / corrupt).                   |
|               | Retorna `CacheHitDecision` frozen dataclass.                                                      |                                                           | `...::test_cache_hit_no_io` (test no toca `OHLCVStore`; pure function.)                                     |     |   |                                                                                                  |
| TSK-104.2.2   | `filters.py`: `check_kill_switch` (RF-3) + `check_active_hours` (RF-2) + `ActiveHoursWindow`.     | `src/trading_bot/scheduler/filters.py`                    | `test_filters.py::test_kill_switch_enabled_returns_skip`, `...::test_kill_switch_disabled_returns_continue`,| TSK-104.1.1 | 1 | Parametrizado 6 modos (research/backtest/paper/live/shadow_live/None).                            |
|               | Wrap-around window: `start=22, end=6` -> incluye `hour >= 22 OR hour < 6`.                          |                                                           | `...::test_active_hours_normal_window`, `...::test_active_hours_wrap_around_window`,                       |     |   | Default `0..23` (RF-2 / CL-5).                                                                  |
|               | Sin I/O, sin state. Solo leen `Settings`.                                                          |                                                           | `...::test_active_hours_entera_in_window_inclusive_start_exclusive_end`                                     |     |   |                                                                                                  |

Gate de F2: `pytest tests/unit/scheduler/test_cache.py
tests/unit/scheduler/test_filters.py` >= 14 verde.

---

## TSK-104.3a - Orquestador skeleton (F3a)

| ID              | Descripcion                                                                                       | Archivos                                                  | Tests esperados                                                                                                                  | dep                  | P | DoD                                                                                  |
| --------------- | ------------------------------------------------------------------------------------------------- | --------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------- | -------------------- | - | ------------------------------------------------------------------------------------ |
| TSK-104.3a.1   | `OHLCVScheduler.__init__` con DI (settings, source_factory, connector_factory=None OK,           | `src/trading_bot/scheduler/scheduler.py`                  | `test_scheduler_skeleton.py::test_init_minimal_args_connector_factory_none_paper_ok`                                            | TSK-104.1.1, TSK-104.1.2 | 1 | `ConfigurationError` si `source_factory=None`. `connector_factory=None` valido para backtest/research. |
|                 | metrics_sink, scheduler_iteration_id_factory=uuid4, clock_fn=time.time). Resuelve source per mode actual. |                                                           | `...::test_init_resolves_source_via_factory`, `...::test_init_metrics_sink_default_is_structlog_sink`                          |                      |   |                                                                                      |
| TSK-104.3a.2   | `_execute_iteration(scan_id)` con kill switch pre-batch (RF-3) + empty universe pre-batch (CL-1)  | `src/trading_bot/scheduler/scheduler.py`                  | `test_scheduler_skeleton.py::test_run_once_kill_switch_aborts_pre_batch`, `...::test_run_once_empty_universe_returns_zero_counter`| TSK-104.3a.1         | 1 | `early_exit` tag discriminante (None / "kill_switch" / "empty_universe"); counters inicializados a 0. |
|                 | + per-pair loop delegando a `_process_one_pair`.                                                   |                                                           | `...::test_pull_succeeded_upserts_to_store` (mock pull OK)                                                                       |                      |   |                                                                                      |
| TSK-104.3a.3   | `_process_one_pair(symbol, source, scan_id)` con active_hours check (RF-2 per-par) +            | `src/trading_bot/scheduler/scheduler.py`                  | `test_scheduler_skeleton.py::test_run_once_active_hours_skip_per_pair`, `...::test_run_once_cache_hit_skips_pull`              | TSK-104.3a.2, TSK-104.2.1, TSK-104.2.2 | 1 | Per-pair active_hours omit; per-pair cache_hit omit; pulls delegate via `source.fetch_one()` (F3b implementará retry).         |
|                 | `evaluate_cache_hit` (RF-4) + pull delegate via `source.fetch_one()` (F3b will add retry).         |                                                           | `...::test_run_once_pull_failed_does_not_abort_batch`                                                                           |                      |   |                                                                                      |
| TSK-104.3a.4   | Reentrancy guard (`_running` boolean + `try/finally`) para `run_once()` Y `run()`.               | `src/trading_bot/scheduler/scheduler.py`                  | `test_reentrancy.py::test_run_once_second_call_raises_runtime_error`, `...::test_run_second_call_skipped_via_running_flag`     | TSK-104.3a.2         | 1 | `RuntimeError` claro + message cita TSK-103 spec section 10 (mismo patron scanner). |

Gate de F3a: `pytest tests/unit/scheduler/test_scheduler_skeleton.py
tests/unit/scheduler/test_reentrancy.py` >= 7 verde; mypy strict verde;
ruff format + ruff check verdes; cobertura >= 90% en `scheduler.py`.

---

## TSK-104.3b - Retries, run loop, eventos, mode-flip, cross-layer (F3b)

| ID              | Descripcion                                                                                                  | Archivos                                       | Tests esperados                                                                                                                | dep       | P | DoD                                                                                                |
| --------------- | ------------------------------------------------------------------------------------------------------------ | ---------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------ | --------- | - | -------------------------------------------------------------------------------------------------- |
| TSK-104.3b.1   | `_fetch_with_retry(source_factory, symbol, ...)` con jitter + Retry-After (CL-9). 3 retries max.            | `src/trading_bot/scheduler/scheduler.py`      | `test_retry.py::test_fetch_with_retry_jitter_on_429`, `...::test_fetch_with_retry_exhausted_after_3`,                          | TSK-104.3a.3 | 1 | 429 + jitter ±25% (1s/2s/4s); Retry-After clamp 1..60s; tras 3 retries -> `RetryExhaustedError` chain. `rate_limit_exhausted` pulled-out en `pull.failed`. |
|                 | `retry_arg = tenacity.Retrying(...)`. `PullFailureReason` discrimina (`rate_limit_exhausted` vs `network_timeout`). |                                              | `...::test_fetch_with_retry_respects_retry_after_header_clamp_60`                                                               |           |   |                                                                                                    |
| TSK-104.3b.2   | `run()` async: `while not cancelled: await run_once(); await asyncio.sleep(interval_seconds)`.               | `src/trading_bot/scheduler/scheduler.py`      | `test_run_loop.py::test_run_loop_cancelled_error_propagates_untrapped`, `...::test_run_loop_graceful_shutdown_under_2s`         | TSK-104.3a.4, TSK-104.3b.1 | 1 | `CancelledError` desde inner `await run_once()` propaga al caller; `finally` cierra connector. SLO shutdown <= 2s pine con `tracemalloc`. |
| TSK-104.3b.3   | `connector_reinjector(new_mode: TradingMode)` para RF-7 mode-flip. Cierra viejo + construye nuevo via       | `src/trading_bot/scheduler/scheduler.py`      | `test_connector_reinjector.py::test_connector_reinjector_closes_old_connector`,                                                  | TSK-104.3a.1 | 1 | (R1 opcion b) Pine contract: si `new_mode in {paper, live, shadow_live}` y `self._connector_factory is None` -> `ConfigurationError` con hint `tasks/decisions.md`. |
|                 | `self._connector_factory(new_mode)`. Valida factory None + raise ConfigurationError si mode requiere connector. |                                              | `...::test_connector_reinjector_constructs_new_one_via_factory`                                                                  |           |   |                                                                                                    |
|                 |                                                                                                              |                                              | `...::test_connector_reinjector_does_not_mutate_sandbox_in_place` (RF-7, pine)                                                   |           |   |                                                                                                    |
|                 |                                                                                                              |                                              | `...::test_connector_reinjector_raises_when_factory_none_and_mode_needs_connector` (R1 opcion b)                                |           |   |                                                                                                    |
| TSK-104.3b.4   | 7 structlog events con single-emission point + structlog binding por iteracion.                              | `src/trading_bot/scheduler/scheduler.py`      | `test_structlog_events.py::test_iteration_completed_emitted_once_per_run_once`,                                                  | TSK-104.3a.2, TSK-104.3b.2 | 1 | Captura 7 eventos (`iteration.started`/`paused.kill_switch`/`universe.empty`/`pull.completed`/`pull.skipped`/`pull.failed`/`iteration.completed`) con `early_exit` tag. |
|                 | `iteration.completed` SIEMPRE al final del `run_once()`, con `early_exit` tag discriminante.                |                                              | `...::test_iteration_completed_includes_scheduler_iteration_id_duration_ms_counters`                                            |           |   |                                                                                                    |
|                 |                                                                                                              |                                              | `...::test_pull_events_carry_symbol_and_attempts`                                                                               |           |   |                                                                                                    |
| TSK-104.3b.5   | Cross-layer AST test: pine que `scheduler.py` no importa `execution`/`strategies`/`risk`/`portfolio`/        | `tests/unit/scheduler/test_cross_layer.py`     | `test_cross_layer.py::test_scheduler_does_not_import_forbidden_layers`,                                                         | TSK-104.3a.1 | 1 | Mismo patron que `tests/unit/scanner/test_cross_layer.py::_parse_imports()`. Falla el test si scheduler.py rota la constraint. |
|                 | `paper`/`observability`. Solo `market_data` + `config` + stdlib.                                              |                                              | `...::test_scheduler_only_imports_market_data_and_config`                                                                        |           |   |                                                                                                    |

Gate de F3b: 6 quality gates per `docs/ci.md` §3 — ruff check + ruff
format + mypy strict + pytest `--cov-fail-under=90` + safety check +
pip-audit — todos verde. `pytest tests/unit/scheduler/` >= 20 verde
total (7 F3a + 13 F3b). Cross-layer AST verde.

---

## TSK-104.4 - Wiring con Settings + BDD + ADR-0014 + 6 gates (F4)

> **Pre-condición bloqueante**: PR #7 (este spec pack de 5 docs + BDD
> feature + tracker rebadge) mergeado en `main` ANTES de iniciar F4.
> Sin spec en main, F4 no puede correr BDD contra Settings reales.
> ADR-0014 cubre concurrencia secuencial pineada en 03-specify §6.2.

| ID              | Descripcion                                                                                              | Archivos                                                              | DoD                                                                                       |
| --------------- | -------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------- | ----------------------------------------------------------------------------------------- |
| TSK-104.4.1   | `src/trading_bot/app.py scheduler-run` command. Carga `Settings` real + construye `source_factory` per `runtime.mode` (segun tabla §6.1 de 03-specify). | `src/trading_bot/app.py`                                              | `python -m trading_bot.app scheduler-run --mode paper` arranca `OHLCVScheduler.run()` y muestra logs. |
| TSK-104.4.2   | 17 escenarios BDD nuevos en `tests/bdd/step_defs/test_scheduler_steps.py` (siguiendo patron TSK-103.5.2). Step defs cubriendo RF-1..RF-7b + CL-1/2/4/5/9 + CL-ext (mixed-batch + mode-switch). | `tests/bdd/step_defs/test_scheduler_steps.py`                        | `pytest tests/bdd -k ohlcv_scheduler` 17/17 verde, cero `uncollected`.                      |
| TSK-104.4.3   | ADR-0014 firmada: "OHLCV Scheduler concurrencia secuencial". Decision: pulls NO concurrentes (mitiga rate limit CL-9 + mantiene determinismo RNF-5). Cambio a concurrencia requiere ADR futura. | `tasks/decisions.md`                                                  | `grep "ADR-0014"` -> 1 entrada en cada seccion (`## Decisiones` + `## Excepciones firmadas`). |
| TSK-104.4.4   | 6 quality gates verde end-to-end (los mismos que F3b). Full pre-flight local: `ruff format`, `ruff check`, `mypy`, `pytest --cov` con cobertura >= 90%, `safety check`, `pip-audit`. | (CI run; no archivos)                                                  | 6/6 verde en GitHub Actions + 6/6 verde en local preflight via `scripts/validate_local.ps1`. |

Gate de F4: 17 BDD escenarios verde + 6 quality gates verde end-to-end
+ ADR-0014 firmada + COVERAGE scanner-eligible (>= 90%) + PR F-spec-implementation
mergeado a `main` con tag `v0.6.0-rc.1`.

---

## Cobertura esperada (resumen)

- `test_types.py`: ~6 tests (incl. pine invariante `pulls_attempted == pulls_succeeded + pulls_failed + cache_hits`).
- `test_protocols.py`: ~3 tests (runtime_checkable, callable type, struct).
- `test_cache.py`: ~12 tests parametrizados (boundary cases).
- `test_filters.py`: ~8 tests parametrizados (kill + active_hours wrap).
- `test_scheduler_skeleton.py`: ~6 tests (full F3a scope: empty / kill / cache / pull-OK / pull-fail / active_hours).
- `test_reentrancy.py`: ~2 tests.
- `test_retry.py`: ~3 tests (jitter 429 positive, exhausted negative, Retry-After clamp).
- `test_run_loop.py`: ~2 tests (CancelledError propagation, graceful shutdown 2s SLO).
- `test_connector_reinjector.py`: ~3 tests (closes old, constructs new, validates None + mode mismatch).
- `test_structlog_events.py`: ~3 tests (7 event capture, single-emission point, fields binding).
- `test_cross_layer.py`: ~2 tests (forbidden layers, allowed only market_data + config).
- BDD (`pytest-bdd`): 17 escenarios.

**Total ~50 tests unit + 17 BDD scenarios** = 67 verde target.

## Notas operativas

- Cualquier extension del Literal `SkipReason` o `PullFailureReason` requiere ADR firmada en `tasks/decisions.md` antes del commit (mismo criterio que `scanner.types.RejectionReason`).
- Cross-layer AST test es **bloqueante para merge** (TSK-104.3b.5); no se puede omitir.
- `connector_factory=None` es válido SOLO para modos `research`/`backtest`. Cualquier intento de usar esos modos con `connector_factory=None` Y luego flip a `live`/`paper` levanta `ConfigurationError` (R1 opcion b pineada en F3b + 04-plan §R1).
- Concurrencia secuencial (ADR-0014): pine contract codificado en 03-specify §6.2. Cambio a concurrencia requiere ADR futura firmada en `tasks/decisions.md`.
- 04-plan.md y 05-tasks.md de TSK-104 son inputs paralelos (no se bloquean mutuamente). `06-implement-next.md` con TDD es el flujo de ejecucion por sub-ticket: rojo → verde → refactor.
