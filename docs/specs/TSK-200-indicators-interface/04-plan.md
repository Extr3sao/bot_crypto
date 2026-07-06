# TSK-200 - Motor de indicadores: Architectural Plan (Command 04)

> Plan incremental de implementacion. 5 tickets pequenos, ordenados
> por reversibilidad y verifica-antes-de-avanzar. Metodologia:
> `.ai/commands/04-plan.md`.

---

## Pre-condiciones

1. TSK-099, TSK-101, TSK-102, TSK-103, TSK-104 mergeados en `main`
   (todos cerrados al cierre de sprint-003 antes de TSK-200 arrancar).
2. ADR-0013 firmada: la decision Protocol-vs-ABC del motor (ver
   `docs/specs/TSK-200-indicators-interface/01-requirements.md`
   seccion 4 RF-12 + `03-specify.md` seccion 3). Cualquier cambio
   de contrato requiere ADR firmada antes del merge final.
3. `IndicatorsConfig` (TSK-099) vigente + `config/indicators.yaml`
   sin cambios.

## Fases

### F1. TSK-200.1 - Tipos y errores base

- **Objetivo**: tener el contrato publico cerrado antes de cualquier
  logica de indicator o registry.
- **Archivos nuevos**:
  - `src/trading_bot/indicators/__init__.py` (re-exports).
  - `src/trading_bot/indicators/types.py` (`IndicatorOutput`,
    `IndicatorParams`).
  - `src/trading_bot/indicators/exceptions.py`
    (`IndicatorError`, `RegistryFrozenError`,
    `InsufficientHistoryError`, `ParamsHashError`).
- **Tests**:
  - `tests/unit/indicators/__init__.py` vacio.
  - `tests/unit/indicators/test_types.py`: dataclass frozen+slots,
    `IndicatorOutput.__post_init__` valida NaN/inf.
- **Gate**: `pytest tests/unit/indicators/test_types.py` >= 5 verde;
  mypy verde. Cobertura 100% modulo `types.py`.
- **Reversibilidad**: borrar 3 archivos, zero side-effects.

### F2. TSK-200.2 - Protocols + params_hash

- **Objetivo**: definir el contrato `Indicator` + helper
  determinista de hash antes de cualquier implementacion concreta.
- **Archivos nuevos**:
  - `src/trading_bot/indicators/protocols.py` (`Indicator`
    `@runtime_checkable Protocol`).
  - `tests/unit/indicators/test_protocols.py`: isinstance check.
  - `tests/unit/indicators/test_params_hash.py`: invariancia al
    orden de keys + TypeError defensivo (CL-4).
    **NOTA**: el `compute_params_hash` se prueba contra la
    implementacion cache-adyacente en F3, pero aqui ya vive standalone.
- **Gate**: `pytest tests/unit/indicators/test_protocols.py
  tests/unit/indicators/test_params_hash.py` >= 6 verde.
- **Reversibilidad**: borrar 2 archivos, F1 intacta.

### F3. TSK-200.3 - Registry + Cache

- **Objetivo**: encapsular composicion + memoization, separado del
  indicator concreto. AQUI vive el thread-safety lock.
- **Archivos nuevos**:
  - `src/trading_bot/indicators/registry.py` (`IndicatorRegistry`
    con `freeze()`).
  - `src/trading_bot/indicators/cache.py` (`IndicatorCache`,
    `IndicatorCacheStats`, `compute_params_hash`).
  - `tests/unit/indicators/test_registry.py`: register, freeze,
    duplicados, idempotencia de freeze.
  - `tests/unit/indicators/test_cache.py`: hit, miss, eviction,
    invalidate, threading pool test (RNF-4).
- **Gate**: `pytest tests/unit/indicators/test_registry.py
  tests/unit/indicators/test_cache.py` >= 14 verde.
- **Reversibilidad**: borrar 2 archivos + 2 tests, F1-F2 intactas.

### F4. TSK-200.4 - Indicator de referencia (EmaIndicator) + BDD scenarios + cross-layer

- **Objetivo**: tener UN indicator concreto que exercita el Pipeline
  Protocol -> Registry -> Cache end-to-end. Los demas indicators
  (TSK-201..203) repiten el patron.
- **Archivos nuevos**:
  - `src/trading_bot/indicators/ema.py` (`EmaIndicator` minimo).
  - `tests/unit/indicators/test_ema.py`: parametrized
    `period in {9, 14, 21}` + insufficient_history test.
  - `bdd/features/indicators.feature` (17 escenarios per
    `02-bdd.md`).
  - `tests/bdd/step_defs/test_indicator_steps.py`: step glue
    para los 17 escenarios BDD.
  - `tests/unit/indicators/test_cross_layer.py`: AST parse
    verifica prohibicion de imports cross-layer (RF-11).
- **Gate**: `pytest tests/unit/indicators/` >= 25 verde + `pytest-bdd`
  17/17 `bdd/features/indicators.feature` sin uncollected. mypy strict
  verde. ruff clean.
- **Reversibilidad**: borrar `ema.py` + scenarios, F1-F3 intactas.

### F5. TSK-200.5 - Wiring con Settings + quality gates + ADR sync

- **Objetivo**: cerrar el ciclo con `trading_bot.config.Settings`,
  validar los 6 quality gates locales per `docs/ci.md sec 3`, y
  firmar ADR-0013-Fase2 (decision Protocol vs ABC).
- **Cambios**:
  - En `src/trading_bot/indicators/__init__.py` ensure RUF022
    / `__all__` explicito coincidente con imports publicos.
  - Anadir entradas en `tasks/roadmap.md` y `tasks/sprint-003.md`
    documentando el cierre de TSK-200.
  - Confirmar que `IndicatorsConfig.indicators["ema_*"]` se mapea
    a `EmaIndicator` (smoke test con `Settings(...)` real).
  - 6 quality gates verdes localmente per `docs/ci.md` seccion 3:
    ruff, ruff format, mypy strict, pytest --cov-fail-under=90,
    pip-audit (ADR-0012).
  - Firmar ADR-0013-Fase2 en `tasks/decisions.md` (Protocol +
    IndicatorOutput dict + freeze on startup + LRU 256).
- **Gate**: 6 gates verdes en CI; reviewer verdict clean; ADR firmada;
  coverage >= 90% en `src/trading_bot/indicators/`.
- **Reversibilidad**: borrar wiring + ADR; F1-F4 intactas.

## Ticket breakdown (resumen)

| ID        | Tam | FASE | Riesgo | DoD resumida                                        |
| --------- | --- | ---- | ------ | --------------------------------------------------- |
| TSK-200.1 | S   | 2    | L      | Tipos frozen + errores + 5 tests verdes             |
| TSK-200.2 | S   | 2    | L      | Protocol + params_hash + 6 tests verdes             |
| TSK-200.3 | M   | 2    | M      | Registry + Cache + threading test + 14 tests verdes |
| TSK-200.4 | M   | 2    | M      | EmaIndicator + BDD 17 escenarios + cross-layer      |
| TSK-200.5 | S   | 2    | M      | Settings wiring + 6 gates + ADR-0013-Fase2 firmada  |

## Orden de ejecucion

```
F1 (TSK-200.1) -> F2 (TSK-200.2) -> F3 (TSK-200.3) -> F4 (TSK-200.4) -> F5 (TSK-200.5)
```

F1-F3 son trivialmente paralelizables entre si (zero imports cruzados).
F4 depende de F1-F3. F5 depende de F4 + cierre de TSK-099/101/102/103/104
(todos mergeados en `main`).

## Riesgos del plan

- **R1**: mypy strict + `Protocol` con `runtime_checkable` requiere
  cuidado para no introducir `Any` accidental. Mitigacion: mypy en
  cada fase + `__all__` explicito.
- **R2**: threading test puede ser flaky en CI Windows. Mitigacion:
  usar `pytest.mark.flaky` + retry logic, con timeout suave.
- **R3**: cross-layer enforcement via AST parsing puede ser fragil
  si Python 3.11 syntax cambia. Mitigacion: usar `ast` stdlib directo,
  sin `astroid` (lo mismo que F2 scanner).
- **R4**: cobertura >= 90% en `indicators/` puede quedar justa si el
  modulo crece. Mitigacion: omit defensivo solo para ramas
  `pragma: no cover` marcadas explicitamente; el motor es chiquito por
  diseno.
- **R5**: LRU eviction durante compute concurrente (CL-9) puede
  introducir race. Mitigacion: el lock per-instance + el
  re-check post-compute documentado en `spec §5`.

## Criterio de salida del plan

- Los 5 tickets pueden entrar en marcha independientemente.
- Cada ticket tiene DoD medible (test count + gate list).
- El plan no asume capacidad adicional de reviewer: el flujo
  `06-implement-next.md` + `code-reviewer-minimax-m3` cubre cada
  PR pequeno.
- ADR-0013-Fase2 firmada ANTES del merge final de F5.

## Siguiente fase (handoff a `05-tasks.md`)

`05-tasks.md` expande cada ticket del plan en 1..N tareas pequenas
con archivos exactos, tests esperados y dependencias entre tareas.
