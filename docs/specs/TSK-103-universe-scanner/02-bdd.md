# TSK-103 - Universe Scanner: BDD (Command 02)

> Traduccion de RF-1..RF-12 y CL-1..CL-7 a escenarios Gherkin
> ejecutables. Salida canonica: `bdd/features/market_scanner.feature`
> (se extiende in-place, no se reemplaza). Metodologia:
> `.ai/commands/02-bdd.md`.

---

## 1. Mapeo requisito -> escenario

| Requisito | Escenario(s) Gherkin                                                |
| --------- | ------------------------------------------------------------------- |
| RF-1      | `Escanear los 25 pares configurados` (ya), `Rechaza par disabled en whitelist` (nuevo) |
| RF-2      | `Snapshot contiene los 10 campos requeridos` (nuevo), `Snapshot es frozen dataclass` (nuevo) |
| RF-3      | `Rechazar par sin volumen suficiente` (ya), `Rechazar par con spread excesivo` (ya), `Rechazar par con ATR fuera de rango` (nuevo), `Motivo insufficient_history cuando OHLCV < N` (nuevo) |
| RF-4      | `Pausar el escaneo cuando kill_switch esta activo` (ya)             |
| RF-5      | `Continuar si falla un par y registrar el error` (ya), `Counter scanner_errors se incrementa` (nuevo), `Continuar cuando OHLCVFetcher levanta timeout` (nuevo) |
| RF-6      | `Iteracion registra duracion y contadores` (nuevo)                  |
| RF-7      | `Modo live endurece filtro volumen a 10M USDT` (nuevo), `Modo backtest usa MarketDataSourceProtocol oficial` (nuevo) |
| RF-8      | `Scanner no importa exchange/strategies/execution/risk` (nuevo - test de integridad estatico) |
| RF-9      | `FilterRegistry expone los 3 filtros default en orden` (nuevo), `Custom filter se anade al registry sin tocar scanner` (nuevo) |
| RF-10     | `rank_score se calcula con la formula especificada` (nuevo), `Lista se entrega en orden de insercion` (nuevo) |
| RF-11     | Cubierto por gate CI global; BDD no lo duplica.                    |
| RF-12     | Cubierto por `mypy src/trading_bot/scanner/`; BDD no lo duplica.   |

Casos limite:

| Caso | Escenario                                                                  |
| ---- | -------------------------------------------------------------------------- |
| CL-1 | `Lista vacia si universe.pairs esta vacio` (nuevo)                         |
| CL-2 | `Motivo insufficient_history cuando OHLCV < N` (nuevo)                     |
| CL-3 | `Todos los pares fallan -> lista vacia + warn` (nuevo)                     |
| CL-6 | `Tie-break alfabetico cuando dos pares comparten rank_score` (nuevo)       |

## 2. Resumen de cambios sobre `bdd/features/market_scanner.feature`

- **Preservar**: los 6 escenarios ya existentes (`Escanear los 25
  pares`, `Ignorar pares no permitidos`, `Rechazar par sin volumen
  suficiente`, `Rechazar par con spread excesivo`, `Continuar si
  falla un par`, `Pausar el escaneo cuando kill_switch`).
- **Anadir**: 17 nuevos escenarios listados en la seccion 3.

## 3. Escenarios nuevos a agregar al `.feature`

Los escenarios nuevos se listan a continuacion y se anyaden in-place
al archivo `bdd/features/market_scanner.feature` (no se toca el
`Background:` ni el `Feature:`).

### 3.1 RF-2 / RNF-6

```gherkin
Scenario: Snapshot contiene los 10 campos requeridos
  Given un scan ejecutandose sobre el universo paper
  When el scanner completa una iteracion
  Then cada MarketSnapshot contiene los campos:
    | field            | type             |
    | symbol           | str              |
    | last_price       | float            |
    | volume_24h_usdt  | float            |
    | spread_bps       | float            |
    | atr_pct          | Optional[float]  |
    | volatility_pct   | Optional[float]  |
    | active           | bool             |
    | rejection_reason | Optional[str]    |
    | timestamp        | int              |
    | rank_score       | float            |
  And todos los campos son inmutables despues de construccion

Scenario: Snapshot es frozen dataclass
  Given un MarketSnapshot valido cualquiera
  When intento asignar snapshot.rank_score = 0.99
  Then debe levantar dataclasses.FrozenInstanceError
```

### 3.2 RF-3

```gherkin
Scenario: Rechazar par con ATR fuera de rango
  Given un par "BTC/USDT" con atr_pct = 12.0
  And max_atr_percent = 8.0
  When el scanner evalua el snapshot
  Then debe marcar el par como "inactivo"
  And debe registrar el motivo "atr_out_of_range"

Scenario: Motivo insufficient_history cuando OHLCV < N
  Given el par "FOO/USDT" tiene menos de 100 velas OHLCV
  And min_history_candles = 100
  When el scanner evalua el snapshot
  Then debe marcar el par como "inactivo"
  And debe registrar el motivo "insufficient_history"
```

### 3.3 RF-5

```gherkin
Scenario: Counter scanner_errors se incrementa
  Given el contador "scanner_errors" parte en 0
  When tres pares distintos levantan excepciones transitorias consecutivas
  Then el contador "scanner_errors" debe valer 3 بعد finalizada la iteracion

Scenario: Continuar cuando OHLCVFetcher levanta timeout
  Given el par "SOL/USDT" levanta OHLCVFetcherTimeoutError en fetch_recent
  When el scanner procesa "SOL/USDT"
  Then el par es omitido pero la iteracion continua
  And el resto de pares reciben su snapshot normalmente
```

### 3.4 RF-6 / RNF-4

```gherkin
Scenario: Iteracion registra duracion y contadores
  Given un scan sobre 25 pares en sandbox
  When el scanner completa una iteracion
  Then debe emitir log estructurado "scanner.iteration.completed"
  And el log contiene "scan_iteration_id", "duration_ms",
    "pairs_processed", "pairs_active", "pairs_inactive",
    "scanner_errors"
```

### 3.5 RF-7

```gherkin
Scenario: Modo live endurece filtro volumen a 10M USDT
  Given runtime.mode = "live"
  And universe.filters.min_24h_volume_usdt = 5_000_000
  When el scanner evalua un par con volume_24h_usdt = 7_000_000
  Then debe marcar el par como "inactivo" con motivo "volume_below_threshold_for_live_min_10M"

Scenario: Modo backtest usa MarketDataSourceProtocol oficial
  Given runtime.mode = "backtest"
  And OHLCVFetcher inyectado retorna velas sinteticas
  When el scanner ejecuta una iteracion
  Then cada snapshot.last_price coincide con el close de la ultima vela sintetica
```

### 3.6 RF-8

```gherkin
Scenario: Scanner no importa exchange/strategies/execution/risk/portfolio
  Given el modulo "trading_bot/scanner"
  When inspecciono sus imports (estatico)
  Then no debe importar nada desde
    - "trading_bot.exchange.*"
    - "trading_bot.execution.*"
    - "trading_bot.strategies.*"
    - "trading_bot.risk.*"
    - "trading_bot.portfolio.*"
  And solo puede importar "trading_bot.market_data" y "trading_bot.config"
```

### 3.7 RF-9

```gherkin
Scenario: FilterRegistry expone los 3 filtros default en orden
  Given una instancia de UniverseScanner construida con Settings por defecto
  When inspecciono el FilterRegistry interno
  Then debe contener [VolumeFilter, SpreadFilter, AtrFilter] en ese orden

Scenario: Custom filter se anade al registry sin tocar scanner
  Given un callable PriceFilter que rechaza si last_price < 1.0
  When registro el filtro en runtime con registry.register("price", callable)
  Then el scanner aplicado incluye PriceFilter en la composicion
  And un par con last_price = 0.5 queda inactivo con motivo
    "price_below_threshold"
```

### 3.8 RF-10

```gherkin
Scenario: rank_score se calcula con la formula especificada
  Given un par con spread_bps = 10, volume_24h_usdt = 50_000_000, atr_pct = 2.0
  And los rangos de normalizacion son spread_max=30, vol_max=100_000_000, atr_optimo=2.0
  When el scanner evalua el snapshot
  Then rank_score debe aproximarse a
    0.5 * (1 - 10/30) + 0.3 * (50_000_000 / 100_000_000) + 0.2 * 1.0
    ~= 0.4833 (dentro de tolerancia 1e-3)

Scenario: Lista se entrega en orden de insercion
  Given una iteracion que produce 10 snapshots activos
  When el scanner retorna la lista
  Then el orden de la lista sigue el orden de iteracion sobre universe.pairs
  And no se aplica ordenamiento por rank_score en la salida
```

### 3.9 CL-1 / CL-3 / CL-6

```gherkin
Scenario: Lista vacia si universe.pairs esta vacio
  Given la whitelist contiene 0 pares con enabled=true
  When el scanner ejecuta una iteracion
  Then retorna lista vacia
  And registra un warning "scanner.universe.empty"

Scenario: Todos los pares fallan -> lista vacia + warn
  Given los 25 pares lanzan excepcion transitoria
  When el scanner completa una iteracion
  Then retorna lista vacia
  And el log "scanner.iteration.completed" reporta scanner_errors=25
  And pairs_active=0, pairs_inactive=0

Scenario: Tie-break alfabetico cuando dos pares comparten rank_score
  Given BTC/USDT y BNB/USDT se evaluan con rank_score identico
  When el scanner ordena los snapshots activos
  Then BTC/USDT aparece antes que BNB/USDT
```

## 4. Criterio de finalizacion

- `pytest-bdd` ejecuta cada uno de los 23 escenarios (6 existentes +
  17 nuevos) sin uncollected.
- 100% de los RF-1..RF-12 tienen al menos un escenario.
- Ningun escenario depende de implementacion interna (solo
  comportamiento observable: outputs, logs, contadores, motivos).

## 5. NO

- No escribir tests unitarios directamente aqui (se harnearan en
  `tests/unit/scanner/test_universe_scanner.py`).
- No usar jerga interna: solo `MarketSnapshot`, `FilterRegistry`,
  `UniverseScanner`, motivos normalizados, eventos `scanner.*`.
