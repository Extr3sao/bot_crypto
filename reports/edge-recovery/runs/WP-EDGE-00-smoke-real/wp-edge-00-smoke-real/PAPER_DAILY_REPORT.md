# PAPER DAILY REPORT — 2026-10-12

```text
run_id:        wp-edge-00-smoke-real
mode:          PAPER (no live path)
timeframe:     5m
assets:        BTC, ETH, SOL
runtime_hours: 0.006629
cycles:        2
decisions:     6
NO_TRADE:      6
SHADOW:        0
PAPER trades:  0
orders:        0
failures:      0
candidates:    NONE
```

_No strategy is admitted for PAPER, so the correct behaviour is NO_TRADE with zero trades._

## Why NO_TRADE

- `no_trade_NO_TRADE_DATA`: 2
- `no_trade_NO_TRADE_STRATEGIC`: 4

## Strategy attribution

- `ema_crossover@5m`: decisions=4 paper=0 shadow=0 no_trade=4 vetoes=0

## Errors

- SOL/USDT: context_error AssetContextError: no bars at or before ts 1791795395133 for SOL
- SOL/USDT: context_error AssetContextError: no bars at or before ts 1791795415745 for SOL
