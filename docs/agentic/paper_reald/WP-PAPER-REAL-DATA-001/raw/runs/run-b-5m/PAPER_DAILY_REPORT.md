# PAPER DAILY REPORT — 2026-10-24

```text
run_id:        run-b-5m
mode:          PAPER (no live path)
timeframe:     5m
assets:        BTC, ETH, SOL
runtime_hours: 0.169143
cycles:        3
decisions:     9
NO_TRADE:      9
SHADOW:        0
PAPER trades:  0
orders:        0
failures:      0
candidates:    NONE
```

_No strategy is admitted for PAPER, so the correct behaviour is NO_TRADE with zero trades._

## Why NO_TRADE

- `no_trade_NO_TRADE_STRATEGIC`: 9

## Strategy attribution

- `ema_crossover@5m`: decisions=3 paper=0 shadow=0 no_trade=3 vetoes=0
- `momentum@5m`: decisions=5 paper=0 shadow=0 no_trade=5 vetoes=0
- `trend@5m`: decisions=1 paper=0 shadow=0 no_trade=1 vetoes=0
