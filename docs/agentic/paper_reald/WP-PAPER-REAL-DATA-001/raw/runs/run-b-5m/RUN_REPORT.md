# RUN run-b-5m

```text
run_id:      run-b-5m
commit:      e67194e79a42aef2a2ded3aca21ac4a0ea3689c5
environment: ccxt:binance
mode:        paper
assets:      BTC, ETH, SOL
timeframe:   5m
cycles:      3
started:     1792858541852
ended:       1792859150673
```

## Cycle 1 — session 6b3adab2670b4970

### BTC/USDT

```text
Regime: LOW_VOLATILITY
Strategies evaluated: 6
Selected: momentum@5m
Expected gross: -1.88 bps
Expected cost:  22.79 bps
Expected net:   -24.67 bps
Decision: NO_TRADE
Reason: NO_GROSS_EDGE (gross_edge_not_positive:-1.8800bps)
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
Selected: momentum@5m
Expected gross: -1.88 bps
Expected cost:  22.83 bps
Expected net:   -24.71 bps
Decision: NO_TRADE
Reason: NO_GROSS_EDGE (gross_edge_not_positive:-1.8800bps)
NO_TRADE kind: NO_TRADE_STRATEGIC
Verifier: PASS
Risk: PASS (state=APPROVED, evaluated=YES, rule=all_limits_pass)
DecisionTrace persisted: YES
Order created: NO
```

### SOL/USDT

```text
Regime: RANGE
Strategies evaluated: 6
Selected: momentum@5m
Expected gross: -1.88 bps
Expected cost:  23.79 bps
Expected net:   -25.67 bps
Decision: NO_TRADE
Reason: NO_GROSS_EDGE (gross_edge_not_positive:-1.8800bps)
NO_TRADE kind: NO_TRADE_STRATEGIC
Verifier: PASS
Risk: PASS (state=APPROVED, evaluated=YES, rule=all_limits_pass)
DecisionTrace persisted: YES
Order created: NO
```

## Cycle 2 — session 0a996f26483b4f7d

### BTC/USDT

```text
Regime: LOW_VOLATILITY
Strategies evaluated: 6
Selected: ema_crossover@5m
Expected gross: -4.56 bps
Expected cost:  22.79 bps
Expected net:   -27.35 bps
Decision: NO_TRADE
Reason: NO_GROSS_EDGE (gross_edge_not_positive:-4.5600bps)
NO_TRADE kind: NO_TRADE_STRATEGIC
Verifier: PASS
Risk: PASS (state=APPROVED, evaluated=YES, rule=all_limits_pass)
DecisionTrace persisted: YES
Order created: NO
```

### ETH/USDT

```text
Regime: RANGE
Strategies evaluated: 6
Selected: momentum@5m
Expected gross: -1.88 bps
Expected cost:  22.83 bps
Expected net:   -24.71 bps
Decision: NO_TRADE
Reason: NO_GROSS_EDGE (gross_edge_not_positive:-1.8800bps)
NO_TRADE kind: NO_TRADE_STRATEGIC
Verifier: PASS
Risk: PASS (state=APPROVED, evaluated=YES, rule=all_limits_pass)
DecisionTrace persisted: YES
Order created: NO
```

### SOL/USDT

```text
Regime: RANGE
Strategies evaluated: 6
Selected: momentum@5m
Expected gross: -1.88 bps
Expected cost:  23.79 bps
Expected net:   -25.67 bps
Decision: NO_TRADE
Reason: NO_GROSS_EDGE (gross_edge_not_positive:-1.8800bps)
NO_TRADE kind: NO_TRADE_STRATEGIC
Verifier: PASS
Risk: PASS (state=APPROVED, evaluated=YES, rule=all_limits_pass)
DecisionTrace persisted: YES
Order created: NO
```

## Cycle 3 — session 59e0723f9f9a4409

### BTC/USDT

```text
Regime: LOW_VOLATILITY
Strategies evaluated: 6
Selected: ema_crossover@5m
Expected gross: -4.56 bps
Expected cost:  22.79 bps
Expected net:   -27.35 bps
Decision: NO_TRADE
Reason: NO_GROSS_EDGE (gross_edge_not_positive:-4.5600bps)
NO_TRADE kind: NO_TRADE_STRATEGIC
Verifier: PASS
Risk: PASS (state=APPROVED, evaluated=YES, rule=all_limits_pass)
DecisionTrace persisted: YES
Order created: NO
```

### ETH/USDT

```text
Regime: RANGE
Strategies evaluated: 6
Selected: trend@5m
Expected gross: -1.65 bps
Expected cost:  22.83 bps
Expected net:   -24.48 bps
Decision: NO_TRADE
Reason: NO_GROSS_EDGE (gross_edge_not_positive:-1.6500bps)
NO_TRADE kind: NO_TRADE_STRATEGIC
Verifier: PASS
Risk: PASS (state=APPROVED, evaluated=YES, rule=all_limits_pass)
DecisionTrace persisted: YES
Order created: NO
```

### SOL/USDT

```text
Regime: RANGE
Strategies evaluated: 6
Selected: ema_crossover@5m
Expected gross: -4.56 bps
Expected cost:  23.79 bps
Expected net:   -28.35 bps
Decision: NO_TRADE
Reason: NO_GROSS_EDGE (gross_edge_not_positive:-4.5600bps)
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
| outcomes_resolved | 3 |
| outcomes_pending | 6 |
| performance_updates | 3 |
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
By status: {"FULL": 3, "PARTIAL": 6}
Market data accessed: False

`PARTIAL` means the decision was fully reconstructed but its horizon had not closed, so there is no outcome to replay yet.

## Outcomes pending at end of run (6)

- 0a996f26483b4f7d-BTC
- 0a996f26483b4f7d-ETH
- 0a996f26483b4f7d-SOL
- 59e0723f9f9a4409-BTC
- 59e0723f9f9a4409-ETH
- 59e0723f9f9a4409-SOL

## Outcomes resolved

| decision_id | strategy | asset | mode | gross bps | cost bps | net bps | correct |
| --- | --- | --- | --- | ---: | ---: | ---: | --- |
| 6b3adab2670b4970-BTC | momentum@5m | BTC | NO_TRADE | -29.4107 | 22.7918 | -52.2025 | False |
| 6b3adab2670b4970-ETH | momentum@5m | ETH | NO_TRADE | -47.2930 | 22.8339 | -70.1269 | False |
| 6b3adab2670b4970-SOL | momentum@5m | SOL | NO_TRADE | -56.9260 | 23.7894 | -80.7154 | False |

## Strategy performance (experience learning — INSUFFICIENT_SAMPLE)

These cells are realised observation, not validated edge: an `n=1` cell says nothing about future profitability.

| strategy | asset | regime | n | shadow n | paper n | no-trade n | gross bps | net bps | hit rate | PF | max DD bps | recent net bps |
| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| momentum@5m | BTC | LOW_VOLATILITY | 1 | 0 | 0 | 1 | -29.4107 | -52.2025 | 0.0000 | 0.0000 | 52.2025 | -52.2025 |
| momentum@5m | ETH | TREND_DOWN | 1 | 0 | 0 | 1 | -47.2930 | -70.1269 | 0.0000 | 0.0000 | 70.1269 | -70.1269 |
| momentum@5m | SOL | RANGE | 1 | 0 | 0 | 1 | -56.9260 | -80.7154 | 0.0000 | 0.0000 | 80.7154 | -80.7154 |

