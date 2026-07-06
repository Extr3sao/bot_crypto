# TSK-200 - Motor de indicadores: BDD (Command 02)

> Traduccion de RF-1..RF-12 y CL-1..CL-9 a escenarios Gherkin
> ejecutables. Salida canonica: `bdd/features/indicators.feature`
> (nuevo archivo; se crea, no se reemplaza). Metodologia:
> `.ai/commands/02-bdd.md`.

---

## 1. Mapeo requisito -> escenario

| Requisito | Escenario(s) Gherkin                                                |
| --------- | ------------------------------------------------------------------- |
| RF-1      | `compute retorna IndicatorOutput con .values dict[str, float]` (nuevo) |
| RF-2      | `IndicatorOutput es frozen dataclass + values solo float` (nuevo), `values[k] no acepta NaN/inf` (nuevo) |
| RF-3      | `IndicatorRegistry.register acepta uno nuevo` (nuevo), `Registro de duplicado levanta ValueError` (nuevo), `Orden de registro preservado en iteracion` (nuevo) |
| RF-4      | `Registry freeze cierra registro; register post-freeze levanta RegistryFrozenError` (nuevo) |
| RF-5      | `Cache hit con misma (name, params_hash, last_candle_ts)` (nuevo), `Cache miss cuando cambia params_hash` (nuevo) |
| RF-6      | `invalidate_on_new_candle purga entry con ts menor` (nuevo)        |
| RF-7      | `Determinismo: dos compute sobre mismo input retornan values bit-identical` (nuevo) |
| RF-8      | `params_hash invariante al orden de keys` (nuevo)                  |
| RF-9      | `Modo live + velas < N raises InsufficientHistoryError` (nuevo)   |
| RF-10     | Cubierto por gate CI global; BDD no lo duplica.                    |
| RF-11     | `Motor de indicators no importa strategies/execution/risk/portfolio/exchange/scanner` (nuevo) |
| RF-12     | Cubierto por `mypy src/trading_bot/indicators/`; BDD no lo duplica. |

Casos limite:

| Caso | Escenario                                                                  |
| ---- | -------------------------------------------------------------------------- |
| CL-1 | `OHLCV vacio raise InsufficientHistoryError(required=N, got=0)` (nuevo)   |
| CL-2 | `Funcion con N velas < param.min_period raise InsufficientHistoryError` (nuevo) |
| CL-3 | `params no-Mapping raise TypeError defensivo` (nuevo)                      |
| CL-4 | `params con callable raise TypeError al construir params_hash` (nuevo)   |
| CL-5 | `last_candle_ts decreciente log cache.ts_decreasing warn + cache miss tratado` (nuevo) |
| CL-6 | `Registro con mismo name duplicado raise ValueError` (nuevo)              |
| CL-7 | `freeze() llamado dos veces es idempotente` (nuevo)                       |

## 2. Resumen de cambios

- **Crear**: `bdd/features/indicators.feature` (archivo nuevo).
- **No tocar**: ningun `.feature` existente.

## 3. Escenarios a agregar al `.feature`

Los escenarios se listan a continuacion y se vuelcan literalmente al
nuevo archivo `bdd/features/indicators.feature` (no se anaden a un
`Background:` ni a un `Feature:` existente).

### 3.1 RF-1

```gherkin
Scenario: compute retorna IndicatorOutput con .values dict[str, float]
  Given un OHLCV de 100 velas sinteticas con close creciente
  And un indicator EMA-9 registrado en registry
  When compute(ohlcv, {"period": 9}) es invocado
  Then el resultado es instancia de IndicatorOutput
  And el campo values es un Mapping[str, float]
  And values contiene la clave "ema"
  And values["ema"] es un float finito
```

### 3.2 RF-2 / RNF-6

```gherkin
Scenario: IndicatorOutput es frozen dataclass + values solo float
  Given un IndicatorOutput valido con values = {"ema": 1.234}
  When intento asignar output.values["ema"] = 9.99
  Then debe levantar TypeError (Mapping immutable) o AttributeError
  And intento asignar output.values = {} debe levantar AttributeError o TypeError

Scenario: values[k] no acepta NaN/inf
  Given un indicator custom que retorna values = {"x": float("nan")}
  When compute emite el output
  Then compute debe levantar ValueError explicitamente
  And el log dice "IndicatorOutput.values contiene NaN/inf"
```

### 3.3 RF-3

```gherkin
Scenario: IndicatorRegistry.register acepta uno nuevo
  Given un IndicatorRegistry vacio
  When registro "ema" con un callable EmaIndicator
  Then el registry contiene "ema" (len == 1)
  And all() devuelve [EmaIndicator]

Scenario: Registro de duplicado levanta ValueError
  Given un IndicatorRegistry con "ema" ya registrado
  When intento register("ema", otra instancia)
  Then debe levantar ValueError con mensaje "name 'ema' ya registrado"

Scenario: Orden de registro preservado en iteracion
  Given un IndicatorRegistry vacio
  When registro en orden "alpha", "beta", "gamma"
  Then all() devuelve [alpha, beta, gamma] en ese orden
```

### 3.4 RF-4

```gherkin
Scenario: Registry freeze cierra registro; register post-freeze levanta RegistryFrozenError
  Given un IndicatorRegistry con "ema" y "rsi" registrados
  When llamo freeze()
  Then cualquier register() posterior levanta RegistryFrozenError
  And el registry sigue conteniendo "ema" y "rsi"
```

### 3.5 RF-5

```gherkin
Scenario: Cache hit con misma (name, params_hash, last_candle_ts)
  Given un IndicatorCache vacio con last_candle_ts = 1700000000000
  And un result A = compute(ohlcv_100, {"period": 9}) cacheado en ("ema9", hash, ts)
  When compute(ohlcv_100, {"period": 9}) es invocado de nuevo
  Then el cache devuelve el mismo result A sin recomputar
  And cache.stats().hits incrementa en 1

Scenario: Cache miss cuando cambia params_hash
  Given un IndicatorCache con un entry ("ema9", hashA, ts) cacheado
  When compute(ohlcv_100, {"period": 14}) es invocado
  Then el cache miss construye un nuevo entry ("ema14", hashB, ts)
  And el entry anterior ("ema9", hashA, ts) NO se invalida
```

### 3.6 RF-6

```gherkin
Scenario: invalidate_on_new_candle purga entry con ts menor
  Given un IndicatorCache con ("ema9", hash, 1700000000000) y ("ema9", hash, 1700000060000)
  When invalidate_on_new_candle(1700000120000) es invocado
  Then el entry con ts = 1700000000000 es purgado
  And el entry con ts = 1700000060000 permanece en cache
  And un compute posterior con la key purgada debe re-poblar desde 0
```

### 3.7 RF-7

```gherkin
Scenario: Determinismo bit-identical con mismo input
  Given un OHLCV sintetico de 100 velas
  And params = {"period": 9}
  When compute(ohlcv, params) es invocado dos veces
  Then ambos retornos son IndicatorOutput con values dicts bit-identical
  And todas las claves y valores float coinciden exactamente
```

### 3.8 RF-8 / RNF-5

```gherkin
Scenario: params_hash invariante al orden de keys
  Given params_a = {"period": 9, "source": "close"}
  And params_b = {"source": "close", "period": 9}
  When params_hash(params_a) y params_hash(params_b) son computados
  Then ambos hashes son identicos
  And params_c = {"period": 9, "source": "open"} produce un hash distinto
```

### 3.9 RF-9

```gherkin
Scenario: Modo live + velas < N raises InsufficientHistoryError
  Given runtime.mode = "live"
  And IndicatorsConfig.global.require_min_candles = 100
  When un indicator es computado con OHLCV de 50 velas
  Then debe levantar InsufficientHistoryError(required=100, got=50)
  And el log dice "insufficient_history" estructurado
```

### 3.10 RF-11

```gherkin
Scenario: Motor de indicators no importa strategies/execution/risk/portfolio/exchange/scanner
  Given el modulo "trading_bot/indicators"
  When inspecciono sus imports estaticos con AST
  Then no debe importar nada desde
    - "trading_bot.strategies"
    - "trading_bot.execution"
    - "trading_bot.risk"
    - "trading_bot.portfolio"
    - "trading_bot.exchange"
    - "trading_bot.scanner"
  And solo puede importar "trading_bot.market_data.types" y "trading_bot.config.indicators"
```

### 3.11 CL-1

```gherkin
Scenario: OHLCV vacio raise InsufficientHistoryError(required=N, got=0)
  Given un OHLCV vacio (lista de 0 velas)
  When compute(ohlcv, {"period": 9}) es invocado
  Then debe levantar InsufficientHistoryError(required=at_least_1, got=0)
  Y el log estructurado contiene "insufficient_history"
```

### 3.12 CL-2

```gherkin
Scenario: Funcion con N velas < param.min_period raise InsufficientHistoryError
  Given un OHLCV de 13 velas sinteticas
  And params = {"period": 14}
  When compute(ohlcv, params) es invocado
  Then debe levantar InsufficientHistoryError(required=14, got=13)
```

### 3.13 CL-3 / CL-4

```gherkin
Scenario: params no-Mapping raise TypeError defensivo
  Given params = [1, 2, 3] (lista, no Mapping)
  When compute(ohlcv, params) es invocado
  Then debe levantar TypeError("params debe ser Mapping[str, Any]")

Scenario: params con callable raise TypeError al construir params_hash
  Given params = {"fn": lambda x: x}
  When intento construir cache_key = ("ema", params_hash(params), ts)
  Then debe levantar TypeError (callable not JSON-serializable)
```

### 3.14 CL-5

```gherkin
Scenario: last_candle_ts decreciente log warn + cache miss tratado
  Given un IndicatorCache con ("ema9", hash, 1700000060000)
  When un compute llega con last_candle_ts = 1700000000000 (menor)
  Then el cache emite log "cache.ts_decreasing" warn
  Y el compute se trata como miss (recomputa sin tocar el entry con ts mayor)
```

### 3.15 CL-6 / CL-7 (cubierto por RF-3 + RF-4)

Cubierto por los escenarios RF-3 `Registro de duplicado` y RF-4
`Registry freeze cierra registro`.

## 4. Criterio de finalizacion

- `pytest-bdd` ejecuta cada uno de los 17 escenarios listados sin
  `uncollected` ni `skipped`.
- 100% de los RF-1..RF-12 tienen al menos un escenario.
- Ningun escenario depende de implementacion interna (solo
  comportamiento observable: outputs, logs, contadores, errores).

## 5. NO

- No escribir tests unitarios directamente aqui (se harnearan en
  `tests/unit/indicators/test_indicator.py`,
  `test_indicator_registry.py`,
  `test_indicator_cache.py`,
  `test_cross_layer.py`).
- No usar jerga interna: solo `Indicator`, `IndicatorOutput`,
  `IndicatorRegistry`, `IndicatorCache`, `RegistryFrozenError`,
  `InsufficientHistoryError`, motivos normalizados, eventos
  `compute.*` / `cache.*`.
- No inventar nombres de indicadores concretos distintos de `ema`
  en los escenarios (los demas llegan en TSK-201..TSK-203).
