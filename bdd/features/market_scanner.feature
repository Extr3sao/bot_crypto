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
