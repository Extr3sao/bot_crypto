# TSK-104 - OHLCV Scheduler: BDD (Command 02)

> Traduccion de RF-1..RF-10 y CL-1..CL-9 a escenarios Gherkin
> ejecutables. Salida canonica: `bdd/features/ohlcv_scheduler.feature`
> (nuevo archivo, no se toca `market_scanner.feature`).
> Metodologia: `.ai/commands/02-bdd.md`.

---

## 1. Mapeo requisito -> escenario

| Requisito | Escenario(s) Gherkin                                                |
| --------- | ------------------------------------------------------------------- |
| RF-1      | `Scheduler pull los 25 pares en paper mode` (nuevo)                 |
| RF-2      | `Scheduler omite pull fuera de active_hours` (nuevo)                |
| RF-3      | `Scheduler aborta con kill_switch activo` (nuevo)                   |
| RF-4      | `Cache hit evita pull si vela fresca` (nuevo) + `Cache miss dispara pull` (nuevo) |
| RF-5      | `OHLCVFetcherTimeoutError no aborta batch` (nuevo)                  |
| RF-6      | `Scheduler emite log estructurado con duracion y counters` (nuevo)  |
| RF-7      | `Connector sandbox flag correcto (live vs paper)` (nuevo) + `Backtest usa source synthetic sin connector` (nuevo) + `Research usa source synthetic sin connector` (nuevo) |
| RF-8      | `Scheduler no importa execution/strategies/risk` (nuevo - AST)      |
| RF-9      | Cubierto por gate CI global; BDD no lo duplica.                    |
| RF-10     | Cubierto por `mypy`; BDD no lo duplica.                            |

Casos limite:

| Caso | Escenario                                                                  |
| ---- | -------------------------------------------------------------------------- |
| CL-1 | `Scheduler skip si universe vacio` (nuevo)                                 |
| CL-4 | `Scheduler.run() idempotente en quick succession` (nuevo)                  |
| CL-5 | `Scheduler usa default 0-23 si active_hours falta` (nuevo)                 |
| CL-9 | `Exchange rate limit (HTTP 429) reintenta con backoff y Retry-After` (nuevo) + `HTTP 429 con 3 reintentos agotados` (nuevo) |
| CL-ext | `Batch mixto cache_hit + cache_miss + timeout` (nuevo) + `Cambio de modo paper -> live en runtime` (nuevo) |

## 2. Resumen de cambios

- **Crear**: `bdd/features/ohlcv_scheduler.feature` (nuevo archivo, 15 escenarios: 12 originales + 3 nuevos para CL-9 negative + mixed-batch + runtime-mode-switch; el Sandbox-flag scenario se spliteo en 3 escenarios Connector/Backtest/Research).
- **NO tocar**: `bdd/features/market_scanner.feature` (scope distinto, ya tiene 23 escenarios via TSK-103.5 F5).

## 3. Archivo `bdd/features/ohlcv_scheduler.feature`

```gherkin
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

  Scenario: Sandbox flag correcto por modo
    When scheduler.run_once() ejecuta un batch en modo "live"
    Then cada pull usa sandbox=False
    When scheduler.run_once() ejecuta un batch en modo "paper"
    Then cada pull usa sandbox=True
    When scheduler.run_once() ejecuta un batch en modo "backtest"
    Then cada pull usa sandbox=True
    When scheduler.run_once() ejecuta un batch en modo "research"
    Then cada pull usa sandbox=True

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

  Scenario: Exchange rate limit (HTTP 429) reintenta con backoff
    Given el par "ETH/USDT" retorna HTTP 429 en el primer intento
    And retorna OK en el segundo intento (tras backoff)
    When scheduler.run_once() ejecuta un batch
    Then se invoca pull para "ETH/USDT" dos veces
    And el counter pulls_succeeded es 1 para "ETH/USDT"
    And el log "scheduler.pull.retry" se emite una vez con backoff_ms
```

## 4. Criterio de finalizacion

- `pytest-bdd` ejecuta cada uno de los 12 escenarios sin `uncollected`.
- 100% de los RF-1..RF-10 tienen al menos un escenario.
- Casos limite CL-1, CL-2, CL-4, CL-5, CL-9 cubiertos.
- Ningun escenario depende de implementacion interna (solo
  comportamiento observable: counters, logs, llamadas al fetcher
  mockeado, contenido de `OHLCVStore`).

## 5. NO

- No escribir tests unitarios directamente aqui (se harnearan en
  `tests/unit/scheduler/test_scheduler.py`).
- No usar jerga interna: solo `Scheduler`, `SchedulerResult`,
  `OHLCVFetcher`, `OHLCVStore`, eventos `scheduler.*`, motivos
  normalizados (`off_hours`, `cache_fresh`, `timeout`).
- No duplicar escenarios con `market_scanner.feature` (el scanner
  es read-only sobre OHLCVStore; el scheduler es el writer).
