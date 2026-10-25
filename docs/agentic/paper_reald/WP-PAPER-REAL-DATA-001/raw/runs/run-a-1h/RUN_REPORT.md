# RUN run-a-1h

```text
run_id:      run-a-1h
commit:      e67194e79a42aef2a2ded3aca21ac4a0ea3689c5
environment: ccxt:binance
mode:        paper
assets:      BTC, ETH, SOL
timeframe:   1h
cycles:      3
started:     1792858466076
ended:       1792858475243
```

## Cycle 1 — session 59143eb79b6c471d

### BTC/USDT

```text
Regime: LOW_VOLATILITY
Strategies evaluated: 6
Selected: breakout@1h
Expected gross: -0.22 bps
Expected cost:  22.79 bps
Expected net:   -23.01 bps
Decision: NO_TRADE
Reason: NO_GROSS_EDGE (gross_edge_not_positive:-0.2200bps)
NO_TRADE kind: NO_TRADE_STRATEGIC
Verifier: PASS
Risk: PASS (state=APPROVED, evaluated=YES, rule=all_limits_pass)
DecisionTrace persisted: YES
Order created: NO
```

### ETH/USDT

```text
Regime: TREND_DOWN
Strategies evaluated: 6
Selected: breakout@1h
Expected gross: -0.22 bps
Expected cost:  22.83 bps
Expected net:   -23.05 bps
Decision: NO_TRADE
Reason: NO_GROSS_EDGE (gross_edge_not_positive:-0.2200bps)
NO_TRADE kind: NO_TRADE_STRATEGIC
Verifier: PASS
Risk: PASS (state=APPROVED, evaluated=YES, rule=all_limits_pass)
DecisionTrace persisted: YES
Order created: NO
```

### SOL/USDT

```text
Regime: TREND_DOWN
Strategies evaluated: 6
Selected: ema_crossover@1h
Expected gross: -0.96 bps
Expected cost:  23.79 bps
Expected net:   -24.75 bps
Decision: NO_TRADE
Reason: NO_GROSS_EDGE (gross_edge_not_positive:-0.9600bps)
NO_TRADE kind: NO_TRADE_STRATEGIC
Verifier: PASS
Risk: PASS (state=APPROVED, evaluated=YES, rule=all_limits_pass)
DecisionTrace persisted: YES
Order created: NO
```

## Cycle 2 — session e81a3bbc59b9404f

### BTC/USDT

```text
Regime: LOW_VOLATILITY
Strategies evaluated: 6
Selected: breakout@1h
Expected gross: -0.22 bps
Expected cost:  22.79 bps
Expected net:   -23.01 bps
Decision: NO_TRADE
Reason: NO_GROSS_EDGE (gross_edge_not_positive:-0.2200bps)
NO_TRADE kind: NO_TRADE_STRATEGIC
Verifier: PASS
Risk: PASS (state=APPROVED, evaluated=YES, rule=all_limits_pass)
DecisionTrace persisted: YES
Order created: NO
```

### ETH/USDT

```text
Regime: TREND_DOWN
Strategies evaluated: 6
Selected: breakout@1h
Expected gross: -0.22 bps
Expected cost:  22.83 bps
Expected net:   -23.05 bps
Decision: NO_TRADE
Reason: NO_GROSS_EDGE (gross_edge_not_positive:-0.2200bps)
NO_TRADE kind: NO_TRADE_STRATEGIC
Verifier: PASS
Risk: PASS (state=APPROVED, evaluated=YES, rule=all_limits_pass)
DecisionTrace persisted: YES
Order created: NO
```

### SOL/USDT

```text
Regime: TREND_DOWN
Strategies evaluated: 6
Selected: ema_crossover@1h
Expected gross: -0.96 bps
Expected cost:  23.79 bps
Expected net:   -24.75 bps
Decision: NO_TRADE
Reason: NO_GROSS_EDGE (gross_edge_not_positive:-0.9600bps)
NO_TRADE kind: NO_TRADE_STRATEGIC
Verifier: PASS
Risk: PASS (state=APPROVED, evaluated=YES, rule=all_limits_pass)
DecisionTrace persisted: YES
Order created: NO
```

## Cycle 3 — session f562a2860b4f48d0

### BTC/USDT

```text
Regime: LOW_VOLATILITY
Strategies evaluated: 6
Selected: breakout@1h
Expected gross: -0.22 bps
Expected cost:  22.79 bps
Expected net:   -23.01 bps
Decision: NO_TRADE
Reason: NO_GROSS_EDGE (gross_edge_not_positive:-0.2200bps)
NO_TRADE kind: NO_TRADE_STRATEGIC
Verifier: PASS
Risk: PASS (state=APPROVED, evaluated=YES, rule=all_limits_pass)
DecisionTrace persisted: YES
Order created: NO
```

### ETH/USDT

```text
Regime: TREND_DOWN
Strategies evaluated: 6
Selected: breakout@1h
Expected gross: -0.22 bps
Expected cost:  22.83 bps
Expected net:   -23.05 bps
Decision: NO_TRADE
Reason: NO_GROSS_EDGE (gross_edge_not_positive:-0.2200bps)
NO_TRADE kind: NO_TRADE_STRATEGIC
Verifier: PASS
Risk: PASS (state=APPROVED, evaluated=YES, rule=all_limits_pass)
DecisionTrace persisted: YES
Order created: NO
```

### SOL/USDT

```text
Regime: TREND_DOWN
Strategies evaluated: 6
Selected: ema_crossover@1h
Expected gross: -0.96 bps
Expected cost:  23.79 bps
Expected net:   -24.75 bps
Decision: NO_TRADE
Reason: NO_GROSS_EDGE (gross_edge_not_positive:-0.9600bps)
NO_TRADE kind: NO_TRADE_STRATEGIC
Verifier: PASS
Risk: PASS (state=APPROVED, evaluated=YES, rule=all_limits_pass)
DecisionTrace persisted: YES
Order created: NO
```

## Totals

| Metric | Value |
| --- | ---: |
| asset_cycle_evaluations | 9 |
| paper_trades | 0 |
| shadow_trades | 0 |
| no_trades | 9 |
| runtime_failures | 0 |
| orders_created | 0 |
| traces_persisted | 9 |
| outcomes_resolved | 0 |
| outcomes_pending | 9 |
| performance_updates | 0 |
| no_trade_NO_TRADE_STRATEGIC | 9 |
| no_trade_NO_TRADE_RISK | 0 |
| no_trade_NO_TRADE_DATA | 0 |
| no_trade_NO_TRADE_CONFLICT | 0 |
| risk_APPROVED | 9 |
| risk_VETOED | 0 |
| risk_NOT_APPLICABLE | 0 |
| risk_NOT_EVALUATED | 0 |

`no_trades` counts NO_TRADE DECISIONS only; an operational failure (`runtime_failures`) is an incident, never a trading decision, and is never counted as a NO_TRADE hypothesis.

Trace chain: `{"broken_at": null, "detail": "hash chain intact", "ok": true, "records": 9}`

Production actions: 0

## Deterministic risk (one review per decision that carried a proposal)

- APPROVED: 9
- VETOED: 0
- NOT_APPLICABLE: 0
- NOT_EVALUATED: 0

An ADVISORY review (SHADOW / NO_TRADE) is informative only: it can neither authorise nor block an order. `NOT_EVALUATED` is never a PASS.

## Replay (from the persisted trace only)

Attempted: 9
Reconstructed OK: 9
Failed: 0
By status: {"PARTIAL": 9}
Market data accessed: False

`PARTIAL` means the decision was fully reconstructed but its horizon had not closed, so there is no outcome to replay yet.

## Outcomes pending at end of run (9)

- 59143eb79b6c471d-BTC
- 59143eb79b6c471d-ETH
- 59143eb79b6c471d-SOL
- e81a3bbc59b9404f-BTC
- e81a3bbc59b9404f-ETH
- e81a3bbc59b9404f-SOL
- f562a2860b4f48d0-BTC
- f562a2860b4f48d0-ETH
- f562a2860b4f48d0-SOL

