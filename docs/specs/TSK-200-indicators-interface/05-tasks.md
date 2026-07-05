# TSK-200 - Motor de indicadores: Tasks (Command 05)

> Tareas pequenas, trazables y ejecutables una a una. Cada tarea
> cabe en un commit. Metodologia: `.ai/commands/05-tasks.md`.

Convenciones:
- `P` = prioridad dentro del ticket (1 = mas alta).
- `dep` = dependencias (`-` si ninguna).
- `DoD` = Definition of Done.

---

## TSK-200.1 - Tipos y errores base (F1)

| ID            | Descripcion                                                | Archivos                                                                                | Tests esperados                                                            | dep | P | DoD                                                              |
| ------------- | ---------------------------------------------------------- | --------------------------------------------------------------------------------------- | -------------------------------------------------------------------------- | --- | - | ---------------------------------------------------------------- |
| TSK-200.1.1   | Crear paquete `indicators/` con `__init__.py` docstring-only. | `src/trading_bot/indicators/__init__.py`                                                | `tests/unit/indicators/__init__.py` vacio                                 | -   | 1 | `uv run python -c "import trading_bot.indicators"` exit 0. Nota: `python -c` puro (sin `uv run` o sin venv activado) requiere registro del paquete en site-packages del Python del sistema; no es portable cross-shell. La forma canonica del proyecto es uv-managed; spec literal ajustado per code-review de f32d04c. |
| TSK-200.1.2   | `IndicatorOutput` dataclass frozen+slots + `IndicatorParams` alias. | `src/trading_bot/indicators/types.py`                                       | `test_types.py::test_indicator_output_frozen`, `...::test_indicator_output_frozen_slots` | TSK-200.1.1 | 1 | `FrozenInstanceError` al mutar; `slots=True` verificado. |
| TSK-200.1.3   | `__post_init__` valida `values` finiteness + isinstance.   | `src/trading_bot/indicators/types.py`                                                   | `test_types.py::test_indicator_output_post_init_rejects_nan`, `...::test_indicator_output_post_init_rejects_inf`, `...::test_indicator_output_post_init_rejects_non_float` | TSK-200.1.2 | 1 | NaN, inf, strings -> raise explicito; float valido pasa. |
| TSK-200.1.4   | Jerarquia de excepciones custom (`IndicatorError` base + 3 derivados). | `src/trading_bot/indicators/exceptions.py`                                  | `test_types.py::test_exceptions_inherit_indicator_error`, `...::test_insufficient_history_error_attributes_required_got` | TSK-200.1.2 | 2 | `RegistryFrozenError`, `InsufficientHistoryError`, `ParamsHashError` importables; `InsufficientHistoryError` expone `.required` y `.got`. |

Gate de F1: `pytest tests/unit/indicators/test_types.py` >= 5 verde;
mypy verde; cobertura 100% modulo `types.py`.

---

## TSK-200.2 - Protocols + params_hash (F2)

| ID            | Descripcion                                                | Archivos                                                | Tests esperados                                                                                  | dep       | P | DoD                                                       |
| ------------- | ---------------------------------------------------------- | ------------------------------------------------------- | ------------------------------------------------------------------------------------------------ | --------- | - | --------------------------------------------------------- |
| TSK-200.2.1   | `Indicator` Protocol `@runtime_checkable`.                  | `src/trading_bot/indicators/protocols.py`               | `test_protocols.py::test_indicator_protocol_runtime_checkable`                                  | TSK-200.1.2 | 1 | isinstance(fake, Indicator) -> True; mypy detecta contratos. |
| TSK-200.2.2   | Atributo `name: str` parte del protocolo.                  | `src/trading_bot/indicators/protocols.py`               | `test_protocols.py::test_indicator_protocol_attr_name`                                           | TSK-200.2.1 | 2 | `name` accesible sin instanciar mypy.                     |
| TSK-200.2.3   | `compute_params_hash` con `json.dumps(sort_keys=True, default=str)`. | `tests/unit/indicators/test_params_hash.py` (puede vivir standalone aqui o en cache.py) | `test_params_hash.py::test_params_hash_invariant_to_key_order`, `...::test_params_hash_changes_when_value_changes`, `...::test_params_hash_rejects_non_serializable` | TSK-200.2.1 | 1 | Hash bit-identical para keys permutadas; TypeError para `lambda: x`. |

Gate de F2: `pytest tests/unit/indicators/test_protocols.py
tests/unit/indicators/test_params_hash.py` >= 6 verde.

> **NOTA**: `compute_params_hash` puede vivir en `cache.py` (F3) y
> los tests de `params_hash` se mueven ahi. La eleccion se confirma
> durante F3 segun convenga para `test_cache.py::test_params_hash_*`.

---

## TSK-200.3 - Registry + Cache (F3)

| ID            | Descripcion                                                | Archivos                                                | Tests esperados                                                                                  | dep            | P | DoD                                                                |
| ------------- | ---------------------------------------------------------- | ------------------------------------------------------- | ------------------------------------------------------------------------------------------------ | -------------- | - | ------------------------------------------------------------------ |
| TSK-200.3.1   | `IndicatorRegistry` con OrderedDict.                        | `src/trading_bot/indicators/registry.py`                | `test_registry.py::test_register_new`, `...::test_register_duplicate_raises`, `...::test_all_order`, `...::test_len` | TSK-200.2.1    | 1 | Duplicados -> ValueError; orden preservado.                          |
| TSK-200.3.2   | `freeze()` idempotente + `register()` post-freeze -> `RegistryFrozenError`. | `src/trading_bot/indicators/registry.py` | `test_registry.py::test_freeze_blocks_register`, `...::test_freeze_idempotent`, `...::test_is_frozen_property` | TSK-200.3.1    | 1 | `is_frozen == True` post-freeze; 2da freeze silenciosa OK.           |
| TSK-200.3.3   | `get()` + `__contains__` + `__len__` exhaustivos.           | `src/trading_bot/indicators/registry.py`                | `test_registry.py::test_get_returns_indicator`, `...::test_get_raises_keyerror`                | TSK-200.3.1    | 2 | `get("missing")` -> KeyError.                                       |
| TSK-200.3.4   | `IndicatorCache.get_or_compute` (hit/miss/LRU/lock).        | `src/trading_bot/indicators/cache.py`                   | `test_cache.py::test_cache_hit_returns_memoized`, `...::test_cache_miss_computes_once`, `...::test_cache_lru_eviction`, `...::test_cache_max_entries_default_256` | TSK-200.2.3, TSK-200.1.2 | 1 | Hit speedup verificable via mock `compute_fn` que cuenta calls. |
| TSK-200.3.5   | `invalidate_on_new_candle(ts)` purga entries con `ts < ts`. | `src/trading_bot/indicators/cache.py`                   | `test_cache.py::test_invalidate_on_new_candle_purges_old_ts`, `...::test_invalidate_returns_count` | TSK-200.3.4    | 1 | Retorna count purgado; entry con `ts > new_ts` permanece.         |
| TSK-200.3.6   | `stats()` retorna `IndicatorCacheStats` frozen snapshot.   | `src/trading_bot/indicators/cache.py`                   | `test_cache.py::test_stats_returns_frozen_snapshot`, `...::test_stats_size_matches_actual`, `...::test_stats_evictions_increments` | TSK-200.3.4 | 2 | `stats()` retorna mismo valor dentro de 1 lock iteration.          |
| TSK-200.3.7   | Threading test: N readers + 1 writer sin corrupcion.         | `tests/unit/indicators/test_cache.py`                   | `test_cache.py::test_cache_thread_safe_read_write`, parametrized 8 threads  | TSK-200.3.4    | 1 | Pool de threads; asserts `len(cache._cache) == contador esperado`.  |
| TSK-200.3.8   | Race condition post-compute: si el entry ya existe, `stick`. | `src/trading_bot/indicators/cache.py`                   | `test_cache.py::test_cache_post_compute_race_sticks_with_existing`     | TSK-200.3.4    | 2 | Documentado en docstring `get_or_compute`; test con dos threads concurrentes. |

Gate de F3: `pytest tests/unit/indicators/test_registry.py
tests/unit/indicators/test_cache.py` >= 14 verde; threading pool test
estable (no flaky).

---

## TSK-200.4 - EmaIndicator + BDD + cross-layer (F4)

| ID            | Descripcion                                                | Archivos                                                | Tests esperados                                                                                  | dep            | P | DoD                                                                |
| ------------- | ---------------------------------------------------------- | ------------------------------------------------------- | ------------------------------------------------------------------------------------------------ | -------------- | - | ------------------------------------------------------------------ |
| TSK-200.4.1   | `EmaIndicator` frozen dataclass con `name: str = "ema"`.  | `src/trading_bot/indicators/ema.py`                     | `test_ema.py::test_ema_indicator_frozen`, `...::test_ema_name_is_str` | TSK-200.1.2, TSK-200.2.1 | 1 | `name` accesible; dataclass frozen.                                |
| TSK-200.4.2   | `compute()` formula EMA-9 con configurable period.        | `src/trading_bot/indicators/ema.py`                     | `test_ema.py::test_ema_compute_default_period_9`, `...::test_ema_compute_period_14`, `...::test_ema_compute_period_21`, parametrized | TSK-200.4.1    | 1 | `IndicatorOutput(values={"ema": float})` retornado; valor en [low, high] del input. |
| TSK-200.4.3   | `compute()` raises `InsufficientHistoryError` en N < period. | `src/trading_bot/indicators/ema.py`                     | `test_ema.py::test_ema_compute_raises_insufficient_history_empty`, `...::test_ema_compute_raises_insufficient_history_too_few` | TSK-200.4.2 | 1 | `InsufficientHistoryError(required=N, got=actual)` con attrs correctos. |
| TSK-200.4.4   | `compute()` raises `TypeError` si `params` no es Mapping. | `src/trading_bot/indicators/ema.py`                     | `test_ema.py::test_ema_compute_raises_typeerror_on_list_params`                                  | TSK-200.4.2    | 2 | TypeError explicito.                                              |
| TSK-200.4.5   | BDD file con 17 escenarios verbatim desde `02-bdd.md`.     | `bdd/features/indicators.feature`                       | `pytest-bdd --collect-only` lista 17 scenarios                                                  | TSK-200.4.2    | 1 | Zero uncollected; zero skipped.                                    |
| TSK-200.4.6   | Step definitions para los 17 escenarios en BDD.            | `tests/bdd/step_defs/test_indicator_steps.py`           | `pytest-bdd bdd/features/indicators.feature` 17/17 verde                                         | TSK-200.4.5    | 1 | Smoke `pytest tests/bdd -k indicators_feature`.                    |
| TSK-200.4.7   | Cross-layer AST enforcement (RF-11).                       | `tests/unit/indicators/test_cross_layer.py`             | `test_cross_layer.py::test_indicators_does_not_import_forbidden_layers`, parametrized forbidden list | TSK-200.4.5 | 1 | Falla si `indicators/` importa `strategies/execution/risk/portfolio/exchange/scanner`. |
| TSK-200.4.8   | Integracion EmaIndicator + IndicatorRegistry + IndicatorCache. | `tests/unit/indicators/test_ema.py`                  | `test_ema.py::test_ema_end_to_end_registry_cache_full_pipeline`                                  | TSK-200.4.2, TSK-200.3.4 | 1 | `EmaIndicator -> registry.register -> cache.get_or_compute` end-to-end. |

Gate de F4: `pytest tests/unit/indicators/` >= 25 verde +
`pytest-bdd bdd/features/indicators.feature` 17/17 verde + mypy strict
verde + ruff clean. Cobertura total paquete indicators >= 90%.

---

## TSK-200.5 - Settings wiring + 6 quality gates + ADR-0013-Fase2 (F5)

| ID            | Descripcion                                                | Archivos                                                | Tests esperados                                                                                  | dep            | P | DoD                                                                |
| ------------- | ---------------------------------------------------------- | ------------------------------------------------------- | ------------------------------------------------------------------------------------------------ | -------------- | - | ------------------------------------------------------------------ |
| TSK-200.5.1   | `__init__.py` con `__all__` explicito coincidente.          | `src/trading_bot/indicators/__init__.py`                 | (ya cubierto; revisitar para alinear imports publicos)                                            | TSK-200.4.8    | 1 | `from trading_bot.indicators import IndicatorOutput` exit 0.       |
| TSK-200.5.2   | Update `tasks/sprint-003.md` + `tasks/roadmap.md` con cierre TSK-200. | `tasks/sprint-003.md`, `tasks/roadmap.md` | (manual review)                                                                                   | TSK-200.4.8    | 1 | TSK-200 status `in_progress` -> `done`.                            |
| TSK-200.5.3   | Firmar ADR-0013-Fase2 en `tasks/decisions.md` (Protocol + IndicatorOutput + freeze + LRU 256). | `tasks/decisions.md`                  | (manual review)                                                                                   | TSK-200.5.2    | 1 | Bloque Status = `Decidido` con excepciones firmadas.              |
| TSK-200.5.4   | Gate 1 - `uv run ruff check .` verde.                       | (CI / local)                                            | `ruff check .` exit 0                                                                            | TSK-200.5.1    | 1 | Sin hallazgos.                                                     |
| TSK-200.5.5   | Gate 2 - `uv run ruff format --check .` verde.             | (CI / local)                                            | `ruff format --check .` exit 0                                                                   | TSK-200.5.4    | 1 | Sin pendientes de formato.                                         |
| TSK-200.5.6   | Gate 3 - `uv run mypy src/trading_bot tests/` strict verde. | (CI / local)                                            | `mypy src/trading_bot tests/` exit 0                                                              | TSK-200.5.5    | 1 | Cero errores.                                                       |
| TSK-200.5.7   | Gate 4 - `uv run pytest --cov --cov-fail-under=90` verde.   | (CI / local)                                            | `pytest -m "not slow and not market" --cov=src/trading_bot --cov-fail-under=90` exit 0            | TSK-200.5.6    | 1 | >= 25 tests verde + cobertura paquete indicators >= 90% global >= 90%. |
| TSK-200.5.8   | Gate 5 - `uv run pip-audit --ignore-vuln PYSEC-2026-597` verde. | (CI / local)                                       | `pip-audit --ignore-vuln PYSEC-2026-597 --format columns` exit 0                                 | TSK-200.5.7    | 1 | 0 reds (ADR-0012 firmado).                                         |
| TSK-200.5.9   | Gate 6 - `uv run safety check -r requirements` verde.       | (CI / local)                                            | `safety check` exit 0                                                                            | TSK-200.5.8    | 1 | 0 reds.                                                            |

Gate de F5: 6 gates verdes localmente + ADR-0013-Fase2 firmada + reviewer
verdict clean + tickets sync.

---

## Resumen de cobertura esperada

- `test_types.py`: ~5 tests.
- `test_protocols.py`: ~2 tests.
- `test_params_hash.py`: ~4 tests.
- `test_registry.py`: ~6 tests.
- `test_cache.py`: ~8 tests (incluyendo threading pool + race post-compute).
- `test_ema.py`: ~6 tests parametrizados.
- `test_cross_layer.py`: ~2 tests.
- BDD (`pytest-bdd`): 17 escenarios.

**Total ~33 tests + 17 BDD scenarios en paquete
  `tests/unit/indicators/` + `tests/bdd/step_defs/`.**

## Notas operativas

- Cualquier cambio del contrato `Indicator` Protocol o de la shape
  de `IndicatorOutput` requiere ADR nueva antes del commit.
- `compute_params_hash` usa `json.dumps(..., sort_keys=True,
  default=str)`; valores no-JSON-serializables daran TypeError
  defensivo (CL-4) en lugar de `hash()` silencioso o crash.
- El cache usa `last_candle_ts` (int ms epoch) como tercer componente
  de la key. Esto evita invalidacion por reloj global; cualquier nueva
  vela invalida el entry asociado automaticamente (RF-6). El orchestrator
  (Fase 4) llama `invalidate_on_new_candle(new_ts)` despues de cada scan.
- El cache es per-instance (no global mutable state per RNF-1 =
  determinismo). El orchestrator (Fase 4) mantiene 1 cache compartido
  por process via DI; cualquier migracion a global state requiere ADR.
