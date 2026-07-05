Feature: Backtesting
  Los backtests deben ser reproducibles, honestos (sin lookahead) e
  incluir comisiones y slippage.

  Background:
    Given TRADING_MODE = "backtest"
    And datos OHLCV sintéticos deterministas (semilla fija)
    And una estrategia con estado en paper o research

  Scenario: Backtest reproducible
    When se ejecuta un backtest con seed = 42
    Then el resultado debe ser idéntico si se vuelve a ejecutar con seed = 42

  Scenario: Evitar lookahead bias
    Given una estrategia basada en indicador EMA(21)
    When el backtest evalúa la vela en t
    Then solo debe usar información con timestamp <= t

  Scenario: Incluir comisiones
    Given commission_pct = 0.001
    When el motor calcula el PnL
    Then debe descontar la comisión por cada fill

  Scenario: Incluir slippage
    Given slippage_bps = 5
    When el motor simula un fill
    Then debe aplicar slippage en contra del trader

  Scenario: Exportar informe
    When el backtest termina
    Then debe existir reports/backtests/<estrategia>-<symbol>-<fecha>.md
    And debe incluir todas las métricas exigidas

  Scenario: Walk-forward
    Given datos de 6 meses
    When se ejecuta walk-forward con ventana 1 mes y avance 1 semana
    Then debe haber N ejecuciones out-of-sample
    And las métricas globales deben ser robustas (no una sola ventana)

  Scenario: Métricas mínimas exigidas
    When se evalúa un backtest
    Then el informe debe contener como mínimo win rate, profit factor, expectancy, max drawdown, Sharpe aprox., Sortino aprox., nº trades, tiempo medio, mejor trade, peor trade, racha máxima pérdidas, ratio beneficio/riesgo, coste total comisiones y slippage estimado
