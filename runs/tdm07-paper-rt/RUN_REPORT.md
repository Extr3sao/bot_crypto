# RUN tdm07-paper-rt

```text
run_id:      tdm07-paper-rt
commit:      e67194e79a42aef2a2ded3aca21ac4a0ea3689c5
environment: ccxt:binance
mode:        paper
assets:      BTC, ETH
timeframe:   5m
cycles:      1
started:     1792843901426
ended:       1792843906574
```

## Cycle 1 — session af8ec209a12c48b4

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
Regime: LOW_VOLATILITY
Strategies evaluated: 6
Selected: ema_crossover@5m
Expected gross: -4.56 bps
Expected cost:  22.83 bps
Expected net:   -27.39 bps
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
| asset_cycle_evaluations | 2 |
| paper_trades | 0 |
| shadow_trades | 0 |
| no_trades | 2 |
| runtime_failures | 0 |
| orders_created | 0 |
| traces_persisted | 2 |
| outcomes_resolved | 0 |
| outcomes_pending | 2 |
| performance_updates | 0 |
| no_trade_NO_TRADE_STRATEGIC | 2 |
| no_trade_NO_TRADE_RISK | 0 |
| no_trade_NO_TRADE_DATA | 0 |
| no_trade_NO_TRADE_CONFLICT | 0 |
| risk_APPROVED | 2 |
| risk_VETOED | 0 |
| risk_NOT_APPLICABLE | 0 |
| risk_NOT_EVALUATED | 0 |

`no_trades` counts NO_TRADE DECISIONS only; an operational failure (`runtime_failures`) is an incident, never a trading decision, and is never counted as a NO_TRADE hypothesis.

Trace chain: `{"broken_at": null, "detail": "hash chain intact", "ok": true, "records": 2}`

Production actions: 0

## Deterministic risk (one review per decision that carried a proposal)

- APPROVED: 2
- VETOED: 0
- NOT_APPLICABLE: 0
- NOT_EVALUATED: 0

An ADVISORY review (SHADOW / NO_TRADE) is informative only: it can neither authorise nor block an order. `NOT_EVALUATED` is never a PASS.

## Replay (from the persisted trace only)

Attempted: 2
Reconstructed OK: 2
Failed: 0
By status: {"PARTIAL": 2}
Market data accessed: False

`PARTIAL` means the decision was fully reconstructed but its horizon had not closed, so there is no outcome to replay yet.

## Outcomes pending at end of run (2)

- af8ec209a12c48b4-BTC
- af8ec209a12c48b4-ETH

