# TSK-200 - Motor de indicadores: Requirements (Command 01)

> Documento de requisitos elicitados para `src/trading_bot/indicators/`.
> Consumido por `02-bdd.md`, `03-specify.md`, `04-plan.md`, `05-tasks.md`.
> Metodologia: `.ai/commands/01-requirements.md`.
> Estado del ticket: `tasks/sprint-003.md` (live) y `tasks/backlog.md`.

---

## 1. Resumen ejecutivo

TSK-200 implementa el **motor enchufable de indicadores tecnicos** sobre
la base ya construida por TSK-099 (configuracion tipada
Pydantic), TSK-101 (`CCXTExchangeConnector`), TSK-102 (`OHLCVStore`
+ `OHLCVFetcher`) y TSK-103 (UniverseScanner con `MarketSnapshot`
como input). El motor expone una `Indicator` Protocol determinista
que computa indicadores sobre `list[OHLCV]` + `Mapping[str, Any]`
(params) y retorna un `IndicatorOutput` (dataclass inmutable con
`dict[str, float]`). El `IndicatorRegistry` (mirror de `FilterRegistry`
de F2) permite composicion extensible; el `IndicatorCache` (LRU con
invalidacion temporal por `last_candle_ts`) elimina recomputacion
durante scans repetidos.

## 2. Alcance

### 2.1 En scope (TSK-200)

- Definir contrato publico cerrado: `Indicator` Protocol +
  `IndicatorOutput` + `IndicatorRegistry` + `IndicatorCache`.
- Implementar **un** indicador de referencia (`EmaIndicator` minimo)
  que exercita el Protocol end-to-end y sirve como plantilla para
  TSK-201..TSK-203 (los indicadores masivos entran en tickets
  siguientes).
- Catologo de indicadores leido de `config/indicators.yaml`
  (seccion `indicators.indicators:<name>`) y consumido via
  `trading_bot.config.indicators.IndicatorsConfig`.
- `IndicatorRegistry.freeze()` al arrancar el motor; `register()`
  en modo build devuelve `ValueError` despues de `freeze()`.
- `IndicatorCache` keyed by `(indicator_name, params_hash,
  last_candle_ts)` con eviction LRU + invalidacion explicita cuando
  llega `last_candle_ts` nuevo (i.e., una nueva vela entro alOHLCV).
- Property tests con `hypothesis` que verifican invariantes: (a)
  determinismo para inputs identicos; (b) `IndicatorOutput.values`
  contiene solo escalares finitos (NaN/inf -> ValueError explicito);
  (c) cache hit/miss coherentes entre threads.
- Cross-layer enforcement: `indicators/`
  importa `trading_bot.market_data.types` (input `OHLCV`) y
  `trading_bot.config.indicators` (catalogo), y **NO** importa
  `strategies`, `execution`, `risk`, `portfolio`, `exchange`,
  `scanner` directo (las estrategias recibiran snapshots ARGAMENTE
  via protocol de Fase 4).

### 2.2 Fuera de scope (TSK-200, sigue en tickets siguientes)

- Implementacion concreta de los 10+ indicadores (TSK-201 + TSK-202).
- Order book imbalance con feed real (TSK-203, detras de feature
  flag segun `config/indicators.yaml`).
- Optimizacion per-pair del cache (TSK-204 hypothesis property tests
  extiende la cobertura, no el opt).
- Integracion con strategies (Fase 4). Las strategies leen
  `IndicatorOutput` desde un canal desacoplado (TSK-4xx).
- Backfilling de indicadores contra `OHLCVStore` historico (TSK-100+
  storage + TSK-2xx full coverage).
- Multi-timeframe aggregation del mismo `indicator` (un solo
  `primary_timeframe` por cache key).

## 3. Requisitos funcionales (RF)

| ID    | Requisito                                                        | Criterio de aceptacion                                                                              |
| ----- | ---------------------------------------------------------------- | --------------------------------------------------------------------------------------------------- |
| RF-1  | `compute(ohlcv, params)` retorna `IndicatorOutput`.               | isinstance result -> `IndicatorOutput`; `result.values` es Mapping[str, float].                    |
| RF-2  | `IndicatorOutput` es frozen+slotted; `values` solo escalares.    | Dataclass frozen+slots; mutacion levanta `FrozenInstanceError`; `values[k]` -> float finito.       |
| RF-3  | `IndicatorRegistry.register(name, indicator)`; duplicados -> `ValueError`. | `__contains__`, `__len__`, `all()` deterministas; orden de insercion preservado.             |
| RF-4  | `IndicatorRegistry.freeze()` cierra el registro.                | Cualquier `register()` post-freeze -> `RegistryFrozenError`.                                       |
| RF-5  | `IndicatorCache` clave por `(name, params_hash, last_candle_ts)`. | Hit iff las 3 componentes matchean; miss construye entry + memo.                                  |
| RF-6  | `IndicatorCache.invalidate_on_new_candle(ts)` purga la entrada cuyo ts < el nuevo y mismo (name, params_hash). | El mismo `compute()` luego retorna resultado recomputado; thread-safe.        |
| RF-7  | Determinismo: dos `compute()` sobre el mismo input retornan objetos con `values` bit-identical. | Property test hypothesis genera 1000 secuencias; assert `==`.                  |
| RF-8  | Parametros `Mapping[str, Any]`: serializables a hash estable para el cache. | `params_hash` = `hash(json.dumps(params, sort_keys=True, default=str))`; `__hash__` determinista. |
| RF-9  | `runtime.mode=live` endurece `min_required_candles` por defecto segun `IndicatorsConfig.global.require_min_candles`. | live + velas < N -> `InsufficientHistoryError` explicito (no NaN silencioso). |
| RF-10 | El motor no introduce dependencias runtime nuevas.               | `[dependency-groups]` del `pyproject.toml` no crece; solo stdlib + pydantic-settings ya anclados.  |
| RF-11 | Cross-layer enforcement: `ast` parsing detecta deps prohibidas.  | Test `test_cross_layer.py` falla si `indicators/` importa `strategies/execution/risk/portfolio/exchange/scanner`. |
| RF-12 | mypy strict verde.                                               | `mypy src/trading_bot/indicators/` exit 0.                                                          |

## 4. Requisitos no funcionales (RNF)

| ID    | Requisito                                                       | Criterio                                                                |
| ----- | --------------------------------------------------------------- | ----------------------------------------------------------------------- |
| RNF-1 | Cache hit rate >= 95% en regimen estable (mismo params, mismo OHLCV). | Bench sobre 1000 velas con `bench_cache_hit_rate.py`; baseline log.   |
| RNF-2 | Latencia P95 de `compute(first_time)` < 50ms por indicador (EMA sobre 1000 velas). | `pytest-benchmark` opcional; baseline >= 50ms.       |
| RNF-3 | Memoria del cache acotada: max N entries (default 256) con LRU strict. | Eviction FIFO por LRU cuando len > N; `cache.stats().evictions > 0` en test de stress. |
| RNF-4 | Thread-safety: `IndicatorCache.get/set` soporta N readers + 1 writer sin corrupcion. | Test concurrente con `threading.Thread(daemon=True)` pool; asserts. |
| RNF-5 | `params_hash` invariante al orden de keys; collision-free para params canonicos. | `hash(json.dumps({"period":14}, sort_keys=True)) == hash(json.dumps({"period":14}, sort_keys=False))`. |
| RNF-6 | Documentacion exhaustiva del Protocol + `IndicatorOutput` shape. | Docstrings estilo NumPy; `__all__` explicito en cada modulo.           |
| RNF-7 | Sin dependencias transitivas innecesarias.                       | `uv run pip-audit --strict` verde (gate TSK-008).                        |

## 5. Casos limite y modos de fallo (CL)

| ID   | Caso                                                              | Mitigacion                                                                  |
| ---- | ----------------------------------------------------------------- | --------------------------------------------------------------------------- |
| CL-1 | OHLCV vacio (N = 0 velas).                                         | `compute()` raise `InsufficientHistoryError(required=N, got=0)`; sin propagar NaN. |
| CL-2 | OHLCV con N velas < `param.min_period` (e.g., RSI-14 con 13 velas). | `compute()` raise `InsufficientHistoryError(required=14, got=13)`.          |
| CL-3 | `params` no es `Mapping[str, Any]` valido (e.g., lista).           | `compute()` raise `TypeError("params debe ser Mapping")` defensivo.         |
| CL-4 | `params` contiene tipos no serializables (e.g., callable).         | `params_hash` falla con `TypeError` explicito al construir cache key.      |
| CL-5 | `last_candle_ts` decreciente (sesion con datos viejos al frente).  | `IndicatorCache` log `cache.ts_decreasing` warn; no corrupte cache; treat miss. |
| CL-6 | `IndicatorRegistry` con dos indicadores del mismo `name`.         | `register()` raise `ValueError("name {name!r} ya registrado")`.             |
| CL-7 | `freeze()` llamado dos veces.                                      | Idempotente (segunda llamada silenciosa OK); assertion interna pineada.    |
| CL-8 | Concurrencia: dos threads llaman `compute` con misma key al mismo tiempo. | Lock per-key dentro del cache; uno computa y escribe; el otro espera + lee. |
| CL-9 | Cache con eviction en medio de un `compute` largo.                | Lock per-key protege; eviction FIFO es a nivel de keys completas, no valores a medias. |

## 6. Dependencias y asunciones

- **TSK-099** (config tipada) - mergeado en `main` (`9eed3fd`, ADR-0010).
- **TSK-101** (`CCXTExchangeConnector`) - mergeado en `main` (PR F1).
- **TSK-102** (`OHLCVStore` + `OHLCVFetcher`) - mergeado en `main` (PR F1).
- **TSK-103** (`UniverseScanner` + `MarketSnapshot`) - mergeado en `main` (PR F5).
- **TSK-104** (backtest engine) - mergeado en `main` (PR F2 + F3). TSK-200
  no depende directamente del engine backtest; ambos comparten `OHLCV`.
- **ADR-0005** (`sqlite3` en Fase 1) - sostenido.
- **ADR-0006** (Binance via CCXT, sandbox paper) - sostenido.
- **ADR-0007** (walk-forward pre-condicion de promotion de Fase 5) -
  sostenido; el motor de indicadores no introduce dependencias que
  invaliden walk-forward.
- **ADR-0012** (gate-recovery baseline: `numpy<2.1`, `app.py` omit,
  PYSEC-2026-597 ignorado firmado) - sostenido. El motor no introduce
  numpy (computa en Python puro; cualquier migracion a numpy requiere
  ADR firmada).

**Asunciones**:

- La fuente de `OHLCV` para el motor es la misma que usa el scanner
  (TSK-103 `MarketDataSourceProtocol`). El motor no hace I/O; solo
  computa sobre la lista en memoria que recibe.
- `params_hash` se construye con `json.dumps(..., sort_keys=True,
  default=str)`; valores que no sean JSON-serializables daran
  TypeError defensivo (CL-4) en lugar de `hash` silencioso.
- El cache usa `last_candle_ts` (int ms epoch) como tercer componente
  de la key. Esto evita invalidacion por reloj global; cualquier nueva
  vela invalida el entry asociado automaticamente (RF-6).
- El cache es per-instance (no global mutable state per RNF-1 =
  determinismo). El orchestrator (Fase 4) mantiene 1 cache compartido
  por process via DI.

## 7. Criterios de aceptacion global

1. Los tickets del plan (`04-plan.md`) ejecutados sin DERAIL de fase.
2. Cobertura >= 90% en `src/trading_bot/indicators/`.
3. ruff format + ruff check verde.
4. mypy strict verde.
5. `pytest tests/unit/indicators/ -q` >= 20 tests verde.
6. `pytest tests/unit/indicators/test_cross_layer.py` verde.
7. Property tests `hypothesis` ejecutados con 1000 ejemplos sin falla.
8. ADR-0013 firmada (Phase 2 Protocol decision) antes del merge
   final de TSK-200.

## 8. Siguiente fase (handoff a `02-bdd.md`)

Los RF-1..RF-12 y CL-1..CL-9 se traducen a escenarios Gherkin en
`bdd/features/indicators.feature` (nuevo archivo) y al documento
resumen `02-bdd.md`.
