# WP-EDGE-07 Track C — the frequency target's arithmetic: cost, ceiling, and what was captured

*Read at `2026-10-14T09:11:52Z`. Cost wall: **23.79 bps** per round trip (COST_MODEL_V3 / BINANCE_SPOT_STANDARD_TAKER at a one-hour horizon).*

## 1. The ceiling, per holding horizon

A perfect direction call that enters at the next bar's open and leaves `H` bars later captures the whole open-to-open move and pays the same round trip every real book pays. It is an upper bound: it is never wrong and never exits early.

| Window | H (hours) | Trades/day (3 assets) | Mean abs. move | Cost | Ceiling net | Moves below cost |
| --- | --- | --- | --- | --- | --- | --- |
| DEV | 1 | 72.0 | 65.19 bps | 23.79 bps | **+41.39 bps** | 36.3% |
| DEV | 2 | 36.0 | 92.55 bps | 23.79 bps | **+68.76 bps** | 27.8% |
| DEV | 4 | 18.0 | 131.26 bps | 23.79 bps | **+107.47 bps** | 20.6% |
| DEV | 8 | 9.0 | 187.70 bps | 23.79 bps | **+163.91 bps** | 14.8% |
| DEV | 24 | 3.0 | 343.76 bps | 23.79 bps | **+319.97 bps** | 7.8% |
| VAL | 1 | 72.0 | 49.91 bps | 23.79 bps | **+26.12 bps** | 39.0% |
| VAL | 2 | 36.0 | 69.70 bps | 23.79 bps | **+45.91 bps** | 29.3% |
| VAL | 4 | 18.0 | 98.40 bps | 23.79 bps | **+74.61 bps** | 21.7% |
| VAL | 8 | 9.0 | 140.36 bps | 23.79 bps | **+116.57 bps** | 15.3% |
| VAL | 24 | 3.0 | 254.08 bps | 23.79 bps | **+230.29 bps** | 8.1% |
| NEW_HOLDOUT | 1 | 72.0 | 34.72 bps | 23.79 bps | **+10.93 bps** | 52.2% |
| NEW_HOLDOUT | 2 | 36.0 | 49.74 bps | 23.79 bps | **+25.95 bps** | 39.8% |
| NEW_HOLDOUT | 4 | 18.0 | 70.79 bps | 23.79 bps | **+47.00 bps** | 29.7% |
| NEW_HOLDOUT | 8 | 9.0 | 101.90 bps | 23.79 bps | **+78.11 bps** | 20.6% |
| NEW_HOLDOUT | 24 | 3.0 | 188.92 bps | 23.79 bps | **+165.13 bps** | 10.7% |

## 2. Which horizons can even carry the target

- H=1 h (72.0 trades/day across the three assets): ceiling +10.93 bps per trade after cost.
- H=2 h (36.0 trades/day across the three assets): ceiling +25.95 bps per trade after cost.
- H=4 h (18.0 trades/day across the three assets): ceiling +47.00 bps per trade after cost.
- H=8 h (9.0 trades/day across the three assets): ceiling +78.11 bps per trade after cost.
- H=24 h (3.0 trades/day across the three assets): ceiling +165.13 bps per trade after cost.

## 3. What the registered candidates actually captured

| Book | DEV trades | Per day | Gross bps/trade | Net USDT | Avg duration | Exit mix |
| --- | --- | --- | --- | --- | --- | --- |
| `edge07_active_fade` | 255 | 0.1397 | -15.761 | -503.9857 | 461.65 min | {'stop_loss': 192, 'target': 63} |
| `edge07_active_thrust` | 338 | 0.1852 | -5.3873 | -492.9215 | 173.61 min | {'stop_loss': 206, 'target': 132} |

## 4. What this bounds

- A **negative ceiling** would bound every strategy on these assets away from that horizon,
  and none of the measured horizons above is negative: the cost wall does not, by itself,
  forbid the mission's three trades a day.
- A **positive ceiling is not an edge.** It is what an oracle earns; a real book keeps a
  small fraction of the move and pays the whole cost. The candidates' own captured
  fraction, measured in §3, is the number to compare with §1.
