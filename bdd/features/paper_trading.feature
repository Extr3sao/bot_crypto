Feature: Paper trading
  El modo paper trading simula órdenes con comisiones y slippage, sin
  enviar órdenes reales al exchange.

  Background:
    Given TRADING_MODE = "paper"
    And LIVE_TRADING_ENABLED = false
    And PAPER_INITIAL_BALANCE_USDT = 10000
    And commission_pct = 0.001
    And simulated_slippage_bps = 5

  Scenario: Crear orden simulada
    Given una señal aprobada por el risk-manager
    When el execution-engineer procesa la señal en modo paper
    Then debe crear una orden simulada con client_order_id único
    And debe devolver el fill_price con slippage aplicado

  Scenario: Aplicar comisión simulada
    Given una orden de tamaño 100 USDT ejecutada a 100.00
    When el sistema registra el fill
    Then debe descontar 0.10 USDT como comisión
    And debe actualizar el balance simulado

  Scenario: Aplicar slippage simulado
    Given una orden BUY a precio esperado 100.00
    And slippage_bps = 5
    When la orden se ejecuta
    Then el precio fill debe ser 100.05
    And debe documentar el slippage aplicado en el evento

  Scenario: Actualizar balance simulado después de un fill SELL
    Given balance simulado = 1000 USDT y 0.1 BTC
    When se ejecuta un SELL de 0.05 BTC a 102.00 con slippage 3 bps
    Then el nuevo balance debe reflejar el cobro neto
    And debe registrar la posición actualizada

  Scenario: Reporte diario generado
    Given el día cierra con 4 fills
    When se ejecuta el cierre de día
    Then debe existir reports/paper/<fecha>.md con métricas y fills

  Scenario: Detectar desviación respecto al backtest
    Given el backtest esperaba PnL = 1.0% del capital
    And el paper trading ha cerrado con PnL = 1.7% del capital
    When el observability-engineer compara
    Entonces debe alertar "deviation_over_threshold"
