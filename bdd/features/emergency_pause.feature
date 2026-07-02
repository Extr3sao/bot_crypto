Feature: Emergency pause and kill switch
  El sistema debe proveer un kill switch confiable y una pausa de
  emergencia accesible manualmente, sin importar el modo en el que esté
  ejecutándose (research, backtest, paper, shadow-live o live).

  Background:
    Given el bot está corriendo en cualquier modo != research
    And existe un canal de control registrado (CLI/API)

  Scenario: Comando manual de kill switch desde la CLI
    Given el operador ejecuta "trading-bot kill-switch on --reason 'volatilidad extrema'"
    When el sistema procesa el comando
    Then kill_switch debe quedar activo
    And debe persistirse el estado en logs/
    And el scanner no debe iniciar una nueva iteración
    And las señales pendientes deben quedar en cola (no enviadas)

  Scenario: Kill switch no se desactiva por accidente
    Given kill_switch = on
    When el sistema recibe el evento "mode_change" o "daily_reset"
    Then kill_switch debe seguir = on
    And debe requerir un comando explícito "kill-switch off" para desactivarse

  Scenario: Kill switch se desactiva solo bajo confirmación explícita
    Given kill_switch = on
    And existe motivo registrado "volatilidad extrema"
    When el operador confirma "trading-bot kill-switch off --confirm"
    Then debe requerir la palabra "confirm" en el comando
    Y debe requerir firma humana (registrada en logs)

  Scenario: Pausa de emergencia por drawdown total
    Given el equity cae al nivel max_total_drawdown_pct
    When el risk-manager evalúa la próxima señal
    Then debe activar kill_switch automáticamente
    And debe registrar el evento en logs/risk-decisions.log

  Scenario: Pausa de emergencia por latencia
    Given la latencia mediana excede high_latency_ms durante > 60 s
    When el health monitor evalúa el estado
    Then debe activar kill_switch
    Y debe registrar el motivo "high_latency_persisted"

  Scenario: Estado del kill switch es consultable
    Given el operador ejecuta "trading-bot status"
    When el sistema devuelve el estado
    Then debe mostrar explícitamente "kill_switch: on/off" y el motivo

  Scenario: Idempotencia del comando "kill-switch on"
    Given kill_switch ya está = on por una razón previa
    When se vuelve a ejecutar "kill-switch on --reason X"
    Then debe seguir = on sin lanzar excepción
    Y debe loggear la orden como "no-op"
