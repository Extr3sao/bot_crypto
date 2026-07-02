Feature: Risk manager
  Ninguna señal se convierte en orden sin pasar el risk-manager.
  El risk-manager tiene kill switch y veto sobre live trading.

  Background:
    Given TRADING_MODE = "paper"
    And una señal válida ha sido generada

  Scenario: Bloquear operación por riesgo superior al permitido
    Given la posición propuesta arriesga 1.5% del capital
    And max_risk_per_trade_pct = 0.25
    When el risk-manager evalúa la señal
    Then el veredicto debe ser REJECTED
    And el motivo debe ser "risk_per_trade_exceeded"

  Scenario: Bloquear operación por pérdida diaria máxima alcanzada
    Given la pérdida diaria acumulada es 1.2%
    And max_daily_loss_pct = 1.0
    When llega una nueva señal
    Then el veredicto debe ser REJECTED
    And el motivo debe ser "daily_loss_limit_hit"

  Scenario: Bloquear operación por racha de pérdidas
    Given tres pérdidas consecutivas
    And max_consecutive_losses = 3
    When llega una nueva señal
    Then el veredicto debe ser REJECTED
    And el motivo debe ser "loss_streak_cooldown"

  Scenario: Activar kill switch por drawdown total
    Given el drawdown total alcanza 5%
    And max_total_drawdown_pct = 5
    When se procesa cualquier señal
    Then el veredicto debe ser REJECTED
    And debe activarse kill_switch=on
    And debe registrarse el evento "kill_switch_activated"

  Scenario: Impedir live trading si no está habilitado
    Given LIVE_TRADING_ENABLED = false
    When se intenta iniciar el modo "live"
    Then el sistema debe rechazarlo
    And debe registrar el motivo "live_trading_not_unlocked"

  Scenario: Aprobar señal válida dentro de todos los límites
    Given todos los límites de riesgo respetados
    And la señal pasa todos los filtros
    When el risk-manager evalúa la señal
    Then el veredicto debe ser APPROVED
    And debe devolver el tamaño de posición recomendado
