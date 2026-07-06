Feature: OHLCV Scheduler

  Background:
    Given el modo runtime es "paper"
    And el universo contiene 25 pares USDT
    And active_hours_start = 0
    And active_hours_end = 23
    And freshness_window_minutes = 5
    And kill_switch_enabled = false
    And OHLCVStore vacio para los 25 pares

  Scenario: Scheduler pull los 25 pares en paper mode
    When scheduler.run_once() ejecuta un batch
    Then se invocan 25 pulls al OHLCVFetcher
    And cada pull usa sandbox=True
    And el log "scheduler.pull.completed" se emite 25 veces
    And el counter pulls_succeeded es 25

  Scenario: Scheduler omite pull fuera de active_hours
    Given current_time = "2026-07-04T03:00:00Z"
    And active_hours_start = 9
    And active_hours_end = 17
    When scheduler.run_once() ejecuta un batch
    Then no se invoca ningun pull al OHLCVFetcher
    And el log "scheduler.pull.skipped" se emite una vez con motivo "off_hours"
    And el counter pulls_attempted es 0

  Scenario: Scheduler aborta con kill_switch activo
    Given kill_switch_enabled = true
    When scheduler.run_once() ejecuta un batch
    Then no se invoca ningun pull al OHLCVFetcher
    And el log "scheduler.paused.kill_switch" se emite una vez
    And el counter pulls_attempted es 0
    And el batch retorna inmediatamente

  Scenario: Cache hit evita pull si vela fresca
    Given el par "BTC/USDT" tiene vela con timestamp de hace 1 minuto en OHLCVStore
    When scheduler.run_once() ejecuta un batch
    Then el pull para "BTC/USDT" se omite
    And el counter cache_hits es 1
    And el log "scheduler.pull.skipped" se emite con motivo "cache_fresh" para "BTC/USDT"

  Scenario: Cache miss dispara pull
    Given el par "BTC/USDT" tiene vela con timestamp de hace 1 hora en OHLCVStore
    When scheduler.run_once() ejecuta un batch
    Then se invoca pull para "BTC/USDT"
    And el counter pulls_succeeded incrementa en 1
    And el par "BTC/USDT" se actualiza en OHLCVStore

  Scenario: OHLCVFetcherTimeoutError no aborta batch
    Given el par "SOL/USDT" levanta OHLCVFetcherTimeoutError
    When scheduler.run_once() ejecuta un batch
    Then el resto de pares reciben pull normal (24 pares)
    And el counter pulls_failed es 1
    And el log "scheduler.pull.failed" se emite para "SOL/USDT" con motivo "timeout"

  Scenario: Scheduler emite log estructurado con duracion y counters
    When scheduler.run_once() ejecuta un batch
    Then el log "scheduler.iteration.completed" se emite una vez
    And el log contiene scheduler_iteration_id, duration_ms,
      pulls_attempted, pulls_succeeded, pulls_failed, cache_hits

  Scenario: Connector sandbox flag correcto (live vs paper)
    When scheduler.run_once() ejecuta un batch en modo "live"
    Then cada pull usa sandbox=False
    When scheduler.run_once() ejecuta un batch en modo "paper"
    Then cada pull usa sandbox=True

  Scenario: Backtest usa source synthetic sin connector
    Given runtime.mode = "backtest"
    When scheduler.run_once() ejecuta un batch
    Then el OHLCVFetcher invocado es un mock synthetic (no connector real)
    And el connector real no se invoca
    And cada pull retorna velas sinteticas del mock

  Scenario: Research usa source synthetic sin connector
    Given runtime.mode = "research"
    When scheduler.run_once() ejecuta un batch
    Then el OHLCVFetcher invocado es un mock synthetic (no connector real)
    And el connector real no se invoca

  Scenario: Scheduler skip si universe vacio
    Given el universo contiene 0 pares
    When scheduler.run_once() ejecuta un batch
    Then retorna SchedulerResult con pulls_attempted=0
    And el log "scheduler.universe.empty" se emite una vez
    And no se invoca el OHLCVFetcher

  Scenario: Scheduler usa default 0-23 si active_hours falta
    Given active_hours_start no esta en config
    And active_hours_end no esta en config
    When scheduler.run_once() ejecuta un batch
    Then current_time check usa default 0..23
    And el batch procede normalmente sin skip por horario

  Scenario: Scheduler.run() idempotente en quick succession
    Given un scheduler activo
    When scheduler.run() se llama por segunda vez sin que la primera termine
    Then la segunda llamada retorna inmediatamente sin invocar el fetcher
    And solo una ejecucion de batch esta activa

  Scenario: Exchange rate limit (HTTP 429) reintenta con backoff y Retry-After
    Given el par "ETH/USDT" retorna HTTP 429 con Retry-After=2 en el primer intento
    And retorna OK en el segundo intento (tras respetar Retry-After=2s)
    When scheduler.run_once() ejecuta un batch
    Then se invoca pull para "ETH/USDT" dos veces
    And el counter pulls_succeeded es 1 para "ETH/USDT"
    And el log "scheduler.pull.retry" se emite una vez con backoff_ms=2000

  Scenario: HTTP 429 con 3 reintentos agotados reporta pull_failed
    Given el par "ETH/USDT" retorna HTTP 429 en todos los intentos (sin Retry-After)
    When scheduler.run_once() ejecuta un batch
    Then se invoca pull para "ETH/USDT" 4 veces (1 + 3 retries)
    And el counter pulls_failed es 1 para "ETH/USDT"
    And el log "scheduler.pull.failed" se emite con motivo "rate_limit_exhausted"
    And el log "scheduler.pull.retry" se emite 3 veces con backoff_ms jittered

  Scenario: Batch mixto cache_hit + cache_miss + timeout
    Given el par "BTC/USDT" tiene vela de 1 min en OHLCVStore (cache hit)
    And el par "ETH/USDT" no tiene vela en OHLCVStore (cache miss)
    And el par "SOL/USDT" levanta OHLCVFetcherTimeoutError
    When scheduler.run_once() ejecuta un batch
    Then el pull para "BTC/USDT" se omite (cache hit)
    And el pull para "ETH/USDT" se ejecuta (cache miss)
    And el pull para "SOL/USDT" falla (timeout)
    And los counters son: cache_hits=1, pulls_succeeded=1, pulls_failed=1
    And los 3 pares reciben su evento structlog correspondiente

  Scenario: Cambio de modo en runtime de paper a live requiere re-inyeccion del connector
    Given el scheduler arranca en modo "paper" con un connector CCXTExchangeConnector (sandbox=True)
    And runtime.mode se cambia a "live" durante el batch
    And el caller re-inyecta el connector con sandbox=False via DI
    When scheduler.run_once() ejecuta el siguiente batch
    Then el batch actual (paper, conector viejo) usa sandbox=True
    And el batch siguiente (live, conector nuevo) usa sandbox=False
    And el log "scheduler.mode.changed" se emite una vez con old_mode=paper, new_mode=live, old_sandbox=True, new_sandbox=False
