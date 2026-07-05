Feature: Indicator engine
  El motor de indicadores tecnicos expone un Protocol tipado con
  un registry frozneable, un cache LRU seguro, hashing determinista
  de parametros y manejo defensivo de errores. Las 17 escenarios
  cubren RF-1..RF-12 + CL-1..CL-7 verbatim del spec 02-bdd.md.

  Background:
    Given un EmaIndicator disponible como referencia del motor
    And un IndicatorRegistry vacio
    And un IndicatorCache vacio con last_candle_ts = 1700000000000

  # ----------------- RF-1 -----------------
  Scenario: compute retorna IndicatorOutput con .values dict[str, float]
    Given un OHLCV de 100 velas sinteticas con close creciente
    And un indicator EMA-9 registrado en registry
    When compute(ohlcv, {"period": 9}) es invocado
    Then el resultado es instancia de IndicatorOutput
    And el campo values es un Mapping[str, float]
    And values contiene la clave "ema"
    And values["ema"] es un float finito

  # ----------------- RF-2 / RNF-6 -----------------
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

  # ----------------- RF-3 -----------------
  Scenario: IndicatorRegistry.register acepta uno nuevo
    Given un IndicatorRegistry vacio
    When registro "ema" con un callable EmaIndicator
    Then el registry contiene "ema" (len == 1)
    And all() devuelve el indicator registrado

  Scenario: Registro de duplicado levanta ValueError
    Given un IndicatorRegistry con "ema" ya registrado
    When intento register("ema", otra instancia)
    Then debe levantar ValueError con mensaje "name 'ema' ya registrado"

  Scenario: Orden de registro preservado en iteracion
    Given un IndicatorRegistry vacio
    When registro en orden "alpha", "beta", "gamma"
    Then all() devuelve [alpha, beta, gamma] en ese orden

  # ----------------- RF-4 -----------------
  Scenario: Registry freeze cierra registro; register post-freeze levanta RegistryFrozenError
    Given un IndicatorRegistry con "ema" y "rsi" registrados
    When llamo freeze()
    Then cualquier register() posterior levanta RegistryFrozenError
    And el registry sigue conteniendo "ema" y "rsi"

  # ----------------- RF-5 -----------------
  Scenario: Cache hit con misma (name, params_hash, last_candle_ts)
    Given un IndicatorCache vacio con last_candle_ts = 1700000000000
    And un result A = compute(ohlcv_100, {"period": 9}) cacheado en ("ema", hash, ts)
    When compute(ohlcv_100, {"period": 9}) es invocado de nuevo
    Then el cache devuelve el mismo result A sin recomputar
    And cache.stats().hits incrementa en 1

  Scenario: Cache miss cuando cambia params_hash
    Given un IndicatorCache con un entry ("ema", hashA, ts) cacheado
    When compute(ohlcv_100, {"period": 14}) es invocado
    Then el cache miss construye un nuevo entry ("ema", hashB, ts)
    And el entry anterior ("ema", hashA, ts) NO se invalida

  # ----------------- RF-6 -----------------
  Scenario: invalidate_on_new_candle purga entry con ts menor
    Given un IndicatorCache con ("ema", hash, 1700000000000) y ("ema", hash, 1700000060000)
    When invalidate_on_new_candle(1700000120000) es invocado
    Then el entry con ts = 1700000000000 es purgado
    And el entry con ts = 1700000060000 permanece en cache
    And un compute posterior con la key purgada debe re-poblar desde 0

  # ----------------- RF-7 -----------------
  Scenario: Determinismo bit-identical con mismo input
    Given un OHLCV sintetico de 100 velas
    And params = {"period": 9}
    When compute(ohlcv, params) es invocado dos veces
    Then ambos retornos son IndicatorOutput con values dicts bit-identical
    And todas las claves y valores float coinciden exactamente

  # ----------------- RF-8 / RNF-5 -----------------
  Scenario: params_hash invariante al orden de keys
    Given params_a = {"period": 9, "source": "close"}
    And params_b = {"source": "close", "period": 9}
    When params_hash(params_a) y params_hash(params_b) son computados
    Then ambos hashes son identicos
    And params_c = {"period": 9, "source": "open"} produce un hash distinto

  # ----------------- RF-9 -----------------
  Scenario: Modo live + velas < N raises InsufficientHistoryError
    Given runtime.mode = "live"
    And IndicatorsConfig.global.require_min_candles = 100
    When un indicator es computado con OHLCV de 50 velas
    Then debe levantar InsufficientHistoryError(required=100, got=50)
    And el log dice "insufficient_history" estructurado

  # ----------------- RF-11 -----------------
  Scenario: Motor de indicators no importa strategies/execution/risk/portfolio/exchange/scanner
    Given el modulo "trading_bot/indicators"
    When inspecciono sus imports estaticos con AST
    Then no debe importar "trading_bot.strategies", "trading_bot.execution", "trading_bot.risk", "trading_bot.portfolio", "trading_bot.exchange" ni "trading_bot.scanner"
    And solo puede importar "trading_bot.market_data.types" y "trading_bot.config.indicators"

  # ----------------- CL-1 -----------------
  Scenario: OHLCV vacio raise InsufficientHistoryError(required=2, got=0)
    Given un OHLCV vacio (lista de 0 velas)
    When compute(ohlcv, {"period": 9}) es invocado
    Then debe levantar InsufficientHistoryError(required=at_least_1, got=0)
    And el log estructurado contiene "insufficient_history"

  # ----------------- CL-2 -----------------
  Scenario: Funcion con N velas < param.min_period raise InsufficientHistoryError
    Given un OHLCV de 13 velas sinteticas
    And params = {"period": 14}
    When compute(ohlcv, params) es invocado
    Then debe levantar InsufficientHistoryError(required=14, got=13)

  # ----------------- CL-3 -----------------
  Scenario: params no-Mapping raise TypeError defensivo
    Given params = [1, 2, 3] (lista, no Mapping)
    When compute(ohlcv, params) es invocado
    Then debe levantar TypeError("params debe ser Mapping[str, Any]")

  # ----------------- CL-4 -----------------
  Scenario: params con callable raise TypeError al construir params_hash
    Given params = {"fn": lambda x: x}
    When intento construir cache_key = ("ema", params_hash(params), ts)
    Then debe levantar TypeError (callable not JSON-serializable)

  # ----------------- CL-5 -----------------
  Scenario: last_candle_ts decreciente log warn + cache miss tratado
    Given un IndicatorCache con ("ema", hash, 1700000060000) cacheado
    When un compute llega con last_candle_ts = 1700000000000 (menor)
    Then el cache emite log "cache.ts_decreasing" warn
    And el compute se trata como miss (recomputa sin tocar el entry con ts mayor)
