# TSK-103 - Universe Scanner: Requirements (Command 01)

> Documento de requisitos elicitados para `src/trading_bot/scanner/`.
> Consumido por `02-bdd.md`, `03-specify.md`, `04-plan.md`, `05-tasks.md`.
> Metodologia: `.ai/commands/01-requirements.md`.
> Estado del ticket: `tasks/sprint-002.md` (live) y `tasks/backlog.md`.

---

## 1. Resumen ejecutivo

TSK-103 implementa el **Universe Scanner** sobre la base desacoplada
ya construida por TSK-099 (configuracion tipada Pydantic), TSK-101
(`ExchangeConnector` / `CCXTExchangeConnector`) y TSK-102
(`OHLCVStore` + `OHLCVFetcher`). El scanner itera los pares del
universo configurado en `config/assets.yaml`, aplica filtros de
volumen 24h, spread y ATR/volatilidad, y produce `MarketSnapshot`
rankeados para el motor de estrategias (Fase 4).

## 2. Reconciliacion del scope conflict (Decision D1)

Existe inconsistencia entre `tasks/backlog.md` y `tasks/sprint-002.md`
respecto al alcance de TSK-103:

- **backlog.md**: "Persistencia funcional de OHLCV para consumo del
  scanner" - ya entregada como parte de TSK-102.
- **sprint-002.md**: "Universe scanner + filters (vol 24h, spread,
  ATR)" - alcance vivo del sprint.

**Resolucion adoptada**: opcion (a), minimo churn documental.

1. TSK-103 = Universe scanner per sprint-002 (live scope manda).
2. La intencion original de "persistencia funcional" se considera
   absorbida por TSK-102 (referencia explicita en el ticket backlog
   actualizado).
3. ADR-0013 cubre retroactivamente la limpieza del scope conflict
   en el inventario.

## 3. Alcance

### 3.1 En scope (TSK-103)

- Iterar los pares USDT definidos en `config/assets.yaml` (25 por
  defecto) con `enabled=true`.
- Aplicar filtros por par:
  - `volume_24h_usdt >= universe.filters.min_24h_volume_usdt` (5M).
  - `spread_bps <= universe.filters.max_spread_bps` (30).
  - `atr_pct ∈ [universe.filters.min_atr_percent, max_atr_percent]`
    (0.05..8.0) calculado sobre OHLCV reciente.
- Excluir pares no presentes en la whitelist (Origen externo).
- Manejar errores transitorios sin abortar el loop.
- Respetar `risk.kill_switch_enabled=true` y abortar la iteracion
  con evento `scanner_paused_kill_switch`.
- Emitir `MarketSnapshot` por par (activo/inactivo + motivo).
- Asignar `rank_score ∈ [0,1]` por snapshot activo (combinacion
  lineal: spread_bps invertido 0.5 + volume_24h_usdt norm 0.3 +
  atr_en_rango norm 0.2).
- Logs estructurados `structlog` con eventos `scanner.iteration.*`
  y counters `pairs_processed`, `pairs_active`, `pairs_inactive`,
  `scanner_errors`.

### 3.2 Fuera de scope (TSK-103, sigue en tickets posteriores)

- Estrategias y generacion de senales (Fase 4, tickets `TSK-4xx`).
- Position sizing / riesgo (Fase 5, tickets `TSK-5xx`).
- Ejecucion de ordenes (Fase 9, ticket live release gate).
- Indicadores tecnicos pesados (Fase 2, TSK-2xx). ATR basico si; EMA,
  RSI, MACD, BB, VWAP no.
- Backtest motor (Fase 6, TSK-104-equivalent).
- Multi-exchange simultaneo. ADR-0006 fija Binance+CCXT unico.
- Order book imbalance (TSK-203, Fase 2, detras de feature flag).

## 4. Requisitos funcionales (RF)

| ID    | Requisito                                                         | Criterio de aceptacion                                                    |
| ----- | ----------------------------------------------------------------- | ------------------------------------------------------------------------- |
| RF-1  | Itera `universe.pairs` con `enabled=true`.                         | `len(return) == count(enabled=true)`                                      |
| RF-2  | Cada par produce `MarketSnapshot` con 10 campos.                  | Dataclass `MarketSnapshot` validado, todos los campos populados.          |
| RF-3  | Pares que no pasan filtros quedan `active=false` con motivo.       | Motivos ∈ {`not_whitelisted`,`volume_below_threshold`,`spread_above_threshold`,`atr_out_of_range`,`insufficient_history`}. |
| RF-4  | `kill_switch_enabled=true` aborta antes de cualquier I/O.         | Return `[]` + log `scanner.paused.kill_switch` + counter N/A.            |
| RF-5  | Error transitorio (`ccxt.NetworkError`) en un par no aborta loop. | Test continua con los siguientes + counter `scanner_errors+=1`.          |
| RF-6  | Cada iteracion registra duracion + 4 counters en logs.            | structlog capture verifica 4 counters + 1 evento `iteration.completed`.  |
| RF-7  | Funciona en `research|backtest|paper|live`; `live` endurece filtros. | Test por modo verifica policy live (volumen minimo 10M USDT, atras 5s). |
| RF-8  | `MarketSnapshot` sin acoplamiento a `execution` / `strategies`.   | `grep` confirma cero imports cross-layer en `src/trading_bot/scanner/`.  |
| RF-9  | Filtros se aplican via `FilterRegistry` registrado al instanciar. | Test verifica defaults: `VolumeFilter`, `SpreadFilter`, `AtrFilter`.     |
| RF-10 | `rank_score` calculado pero la lista se entrega en orden de insercion. | Formula `0.5*(1-spread_norm) + 0.3*vol_norm + 0.2*atr_in_range_norm`. |
| RF-11 | Cobertura de tests >= 90% en lineas nuevas.                       | `pytest --cov-fail-under=90` verde.                                       |
| RF-12 | mypy strict verde.                                                | `mypy src/trading_bot/scanner/` exit 0.                                   |

## 5. Requisitos no funcionales (RNF)

| ID    | Requisito                                                  | Criterio                                                              |
| ----- | ---------------------------------------------------------- | --------------------------------------------------------------------- |
| RNF-1 | Latencia P95 de una iteracion (25 pares sandbox) <= 4s.   | Benchmark contra testnet Binance.                                     |
| RNF-2 | Memoria por iteracion < 50 MB.                             | `tracemalloc` snapshot.                                               |
| RNF-3 | Sin bloqueos I/O: `asyncio` coherente con ADR-0006.        | `await connector.fetch_ohlcv(...)`, sin `time.sleep`.                |
| RNF-4 | Logs JSON con `request_id` y `scan_iteration_id`.          | structlog binding por iteracion.                                      |
| RNF-5 | Determinismo: doble scan sobre el mismo OHLCV mockeado -> mismo orden y mismos campos. | Test property-based con `hypothesis`. |
| RNF-6 | `frozen=True, slots=True` en todos los dataclasses publicos. | Test mutacion -> `dataclasses.FrozenInstanceError`.                  |
| RNF-7 | Sin dependencias cross-layer.                              | `pyright`-rule o grep estructural en `pyproject.toml [tool.pyright]`. |

## 6. Casos limite y modos de fallo (CL)

| ID   | Caso                                                                | Mitigacion                                                              |
| ---- | ------------------------------------------------------------------- | ----------------------------------------------------------------------- |
| CL-1 | `universe.pairs` vacio.                                             | Log warn, retorna `[]`, exit code 0.                                    |
| CL-2 | OHLCV vacio / sin historial suficiente.                             | `atr_pct=None`, `volatility_pct=None`, par queda `active=false` con `insufficient_history`. |
| CL-3 | Todos los pares fallan.                                             | Log error, `scanner_errors=25`, return `[]`.                            |
| CL-4 | `runtime.mode=backtest` con fuente offline (test fixture).           | `MarketDataSourceProtocol` permite inyeccion.                           |
| CL-5 | `runtime.mode=live` con `kill_switch=True`.                          | Abortar inmediatamente (cubre RF-4).                                    |
| CL-6 | Dos pares con mismo `rank_score`.                                    | Tie-break alfabetico por `symbol`. Determinico (cubre RNF-5).          |
| CL-7 | OHLCV de multiples timeframes mezclado en un scan.                   | Usar un unico `primary_timeframe` desde `runtime.scheduler`.            |

## 7. Dependencias y asunciones

- **TSK-099** (config tipada) - mergeado en `main` (`9eed3fd`, ADR-0010).
- **TSK-101** (`CCXTExchangeConnector`) - implementado, pendiente PR.
- **TSK-102** (`OHLCVStore` + `OHLCVFetcher`) - implementado, pendiente PR.
- **ADR-0005** (`sqlite3` en Fase 1) - sostenido.
- **ADR-0006** (Binance via CCXT, sandbox paper) - sostenido.
- **ADR-0009** (repo privado GitHub) - sostenido.
- **ADR-0012** (gate-recovery baseline) - sostenido; cualquier nuevo
  import numpy debe respetar `numpy<2.1`.

**Asunciones**:

- El scheduler (TSK-104) invocara al scanner. TSK-103 expone
  `UniverseScanner.run() -> list[MarketSnapshot]` y NO incluye un
  scheduler interno.
- La fuente de OHLCV historico para ATR es el mismo timeframe
  (`primary_timeframe`) que configurara el scheduler.
- Las estrategias (Fase 4) consumiran `MarketSnapshot.rank_score`
  como entrada, no como salida.

## 8. Criterios de aceptacion global

1. Los 5 tickets del plan (`04-plan.md`) ejecutados sin DERAIL de fase.
2. Cobertura >= 90% en `src/trading_bot/scanner/`.
3. ruff format + ruff check verde.
4. mypy strict verde.
5. Pre-flight `pytest tests/unit/scanner/ -q` >= 14 tests verdes.
6. Reviewer verdict = clean (sin P0).
7. ADR-0013 firmada para reconciliacion backlog vs sprint.

## 9. Siguiente fase (handoff a `02-bdd.md`)

Los RF-1..RF-12 y CL-1..CL-7 se traducen a escenarios Gherkin en
`bdd/features/market_scanner.feature` (extendiendo los 6 escenarios
existentes) y al documento resumen `02-bdd.md`.
