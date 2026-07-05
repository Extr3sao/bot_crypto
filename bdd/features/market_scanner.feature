Feature: Market scanner
  El sistema debe escanear los pares configurados y aplicar filtros
  antes de propagarlos al motor de estrategias.

  Background:
    Given el modo TRADING_MODE es "paper"
    And la whitelist "config/assets.yaml" está cargada con 25 pares
    And los filtros globales están activados

  Scenario: Escanear los 25 pares configurados
    When el scanner ejecuta una iteración completa
    Then debe producir un snapshot por cada par con enabled=true
    And debe registrar la duración de la iteración
    And no debe lanzar excepciones no controladas

  Scenario: Ignorar pares no permitidos
    Given un par "FOO/USDT" no presente en la whitelist
    When el scanner recibe un mensaje OHLCV de "FOO/USDT"
    Then debe descartar el mensaje
    And debe registrar un warning indicando "symbol not whitelisted"

  Scenario: Rechazar par sin volumen suficiente
    Given un par "BTC/USDT" con volumen 24h = 100 USDT
    And min_24h_volume_usdt = 5_000_000
    When el scanner evalúa el snapshot
    Then debe marcar el par como "inactivo"
    And debe registrar el motivo "volume_below_threshold"

  Scenario: Rechazar par con spread excesivo
    Given un par "ETH/USDT" con spread 80 bps
    And max_spread_bps = 30
    When el scanner evalúa el snapshot
    Then debe marcar el par como "inactivo"
    And debe registrar el motivo "spread_above_threshold"

  Scenario: Continuar si falla un par y registrar el error
    Given el par "SOL/USDT" lanza una excepción de tipo transitorio
    When el scanner procesa "SOL/USDT"
    Then debe registrar el error en logs estructurados
    And debe continuar con el siguiente par
    And debe incrementar un contador de "scanner_errors"

  Scenario: Pausar el escaneo cuando kill_switch está activo
    Given kill_switch_enabled = true y activo
    When el scanner intenta una nueva iteración
    Then debe abortar la iteración
    And debe registrar el evento "scanner_paused_kill_switch"

  Scenario: Snapshot contiene los 10 campos requeridos
    Given un scan ejecutandose sobre el universo paper
    When el scanner completa una iteracion
    Then cada MarketSnapshot contiene los campos:
      | field            | type            |
      | symbol           | str             |
      | last_price       | float           |
      | volume_24h_usdt  | float           |
      | spread_bps       | float           |
      | atr_pct          | Optional[float] |
      | volatility_pct   | Optional[float] |
      | active           | bool            |
      | rejection_reason | Optional[str]   |
      | timestamp        | int             |
      | rank_score       | float           |
    And todos los campos son inmutables despues de construccion

  Scenario: Snapshot es frozen dataclass
    Given un MarketSnapshot valido cualquiera
    When intento asignar snapshot.rank_score = 0.99
    Then debe levantar dataclasses.FrozenInstanceError

  Scenario: Rechazar par con ATR fuera de rango
    Given un par "BTC/USDT" con atr_pct = 12.0
    And max_atr_percent = 8.0
    When el scanner evalua el snapshot
    Then debe marcar el par como "inactivo"
    And debe registrar el motivo "atr_out_of_range"

  Scenario: Motivo insufficient_history cuando OHLCV < N
    Given el par "FOO/USDT" tiene menos de 100 velas OHLCV
    And min_history_candles = 100
    When el scanner evalua el snapshot con OHLCV insuficiente
    Then debe marcar el par como "inactivo"
    And debe registrar el motivo "insufficient_history"

  Scenario: Counter scanner_errors se incrementa
    Given el contador "scanner_errors" parte en 0
    When tres pares distintos levantan excepciones transitorias consecutivas
    Then el contador "scanner_errors" debe valer 3 al final de la iteracion

  Scenario: Continuar cuando OHLCVFetcher levanta timeout
    Given el par "SOL/USDT" levanta OHLCVFetcherTimeoutError en fetch_recent
    When el scanner procesa "SOL/USDT"
    Then el par es omitido pero la iteracion continua
    And el resto de pares reciben su snapshot normalmente

  Scenario: Iteracion registra duracion y contadores
    Given un scan sobre 25 pares en sandbox
    When el scanner completa una iteracion sobre 25 pares en sandbox
    Then debe emitir log estructurado "scanner.iteration.completed"
    And el log contiene los campos "scan_iteration_id", "duration_ms", "pairs_processed", "pairs_active", "pairs_inactive" y "scanner_errors"

  Scenario: Modo live endurece filtro volumen a 10M USDT
    Given runtime.mode = "live"
    And universe.filters.min_24h_volume_usdt = 5_000_000
    When el scanner evalua un par con volume_24h_usdt = 7_000_000
    Then debe marcar el par como "inactivo" con motivo "volume_below_threshold_for_live_min_10M"

  Scenario: Modo backtest usa MarketDataSourceProtocol oficial
    Given runtime.mode = "backtest"
    And OHLCVFetcher inyectado retorna velas sinteticas
    When el scanner ejecuta una iteracion en modo backtest
    Then cada snapshot.last_price coincide con el close de la ultima vela sintetica

  Scenario: Scanner no importa exchange/strategies/execution/risk/portfolio
    Given el modulo "trading_bot/scanner"
    When inspecciono sus imports estaticamente
    Then no debe importar nada desde "trading_bot.exchange.*", "trading_bot.execution.*", "trading_bot.strategies.*", "trading_bot.risk.*" ni "trading_bot.portfolio.*"
    And solo puede importar "trading_bot.market_data" y "trading_bot.config"

  Scenario: FilterRegistry expone los 3 filtros default en orden
    Given una instancia de UniverseScanner construida con Settings por defecto
    When inspecciono el FilterRegistry interno
    Then debe contener [VolumeFilter, SpreadFilter, AtrFilter] en ese orden

  Scenario: Custom filter se anade al registry sin tocar scanner
    Given un callable PriceFilter que rechaza si last_price < 1.0
    When registro el filtro en runtime con FilterRegistry.register
    Then el scanner aplicado incluye PriceFilter en la composicion
    And un par con last_price = 0.5 queda inactivo con motivo "price_below_threshold"

  Scenario: rank_score se calcula con la formula especificada
    Given un par con spread_bps = 10, volume_24h_usdt = 50_000_000, atr_pct = 2.0
    And los rangos de normalizacion son spread_max=30, vol_max=100_000_000, atr_optimo=2.0
    When el scanner evalua el snapshot para calcular rank_score
    Then rank_score debe aproximarse a 0.4833 dentro de tolerancia 1e-3

  Scenario: Lista se entrega en orden de insercion
    Given una iteracion que produce 10 snapshots activos
    When el scanner retorna la lista
    Then el orden de la lista sigue el orden de iteracion sobre universe.pairs
    And no se aplica ordenamiento por rank_score en la salida

  Scenario: Lista vacia si universe.pairs esta vacio
    Given la whitelist contiene 0 pares con enabled=true
    When el scanner ejecuta una iteracion sobre universo vacio
    Then retorna lista vacia
    And registra un warning "scanner.universe.empty"

  Scenario: Todos los pares fallan -> lista vacia + warn
    Given los 25 pares lanzan excepcion transitoria
    When el scanner completa una iteracion con 25 pares fallando
    Then retorna lista vacia tras los fallos
    And el log "scanner.iteration.completed" reporta scanner_errors=25
    And pairs_active=0, pairs_inactive=0

  Scenario: Tie-break alfabetico cuando dos pares comparten rank_score
    Given BTC/USDT y BNB/USDT se evaluan con rank_score identico
    When el scanner ordena los snapshots activos
    Then BTC/USDT aparece antes que BNB/USDT
