"""Motor de backtesting determinista.

Fase objetivo: 6.

Componentes:
- ``Engine``: itera velas y emite órdenes simuladas.
- ``Commissions``: fee model configurable.
- ``Slippage``: modelo configurable.
- ``Metrics``: win rate, profit factor, expectancy, drawdown,
  Sharpe aprox., Sortino aprox., nº trades, mejor/peor trade,
  racha máx pérdidas, ratio B/R, etc.
- ``WalkForward``: separación train/test con avance.
"""
