# RUN tdm08-paper-rt2

```text
run_id:      tdm08-paper-rt2
commit:      e67194e79a42aef2a2ded3aca21ac4a0ea3689c5
environment: ccxt:binance
mode:        paper
assets:      BTC, ETH
timeframe:   5m
cycles:      2
started:     1792858310475
ended:       1792858321254
```

## Cycle 1 — session fc78db574e544d8f

### BTC/USDT

```text
Regime: HIGH_VOLATILITY
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

## Cycle 2 — session 116de81f662f492c

### BTC/USDT

```text
Regime: HIGH_VOLATILITY
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

## Totals

| Metric | Value |
| --- | ---: |
| asset_cycle_evaluations | 4 |
| paper_trades | 0 |
| shadow_trades | 0 |
| no_trades | 4 |
| runtime_failures | 0 |
| orders_created | 0 |
| traces_persisted | 4 |
| outcomes_resolved | 0 |
| outcomes_pending | 4 |
| performance_updates | 0 |
| no_trade_NO_TRADE_STRATEGIC | 4 |
| no_trade_NO_TRADE_RISK | 0 |
| no_trade_NO_TRADE_DATA | 0 |
| no_trade_NO_TRADE_CONFLICT | 0 |
| risk_APPROVED | 4 |
| risk_VETOED | 0 |
| risk_NOT_APPLICABLE | 0 |
| risk_NOT_EVALUATED | 0 |

`no_trades` counts NO_TRADE DECISIONS only; an operational failure (`runtime_failures`) is an incident, never a trading decision, and is never counted as a NO_TRADE hypothesis.

Trace chain: `{"broken_at": null, "detail": "hash chain intact", "ok": true, "records": 4}`

Production actions: 0

## Deterministic risk (one review per decision that carried a proposal)

- APPROVED: 4
- VETOED: 0
- NOT_APPLICABLE: 0
- NOT_EVALUATED: 0

An ADVISORY review (SHADOW / NO_TRADE) is informative only: it can neither authorise nor block an order. `NOT_EVALUATED` is never a PASS.

## Replay (from the persisted trace only)

Attempted: 4
Reconstructed OK: 4
Failed: 0
By status: {"PARTIAL": 4}
Market data accessed: False

`PARTIAL` means the decision was fully reconstructed but its horizon had not closed, so there is no outcome to replay yet.

## Outcomes pending at end of run (4)

- 116de81f662f492c-BTC
- 116de81f662f492c-ETH
- fc78db574e544d8f-BTC
- fc78db574e544d8f-ETH

