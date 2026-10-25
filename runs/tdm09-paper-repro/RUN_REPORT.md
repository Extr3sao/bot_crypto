# RUN tdm09-paper-repro

```text
run_id:      tdm09-paper-repro
commit:      e67194e79a42aef2a2ded3aca21ac4a0ea3689c5
environment: ccxt:binance
mode:        paper
assets:      BTC, ETH
timeframe:   5m
cycles:      2
started:     1792860574489
ended:       1792860586164
```

## Cycle 1 — session 584381b59b0c4bb6

### BTC/USDT

```text
Regime: LOW_VOLATILITY
Strategies evaluated: 6
Selected: None
Decision: NO_TRADE
Reason: NO_ALPHA (no_candidate_emitted_an_alpha)
NO_TRADE kind: NO_TRADE_STRATEGIC
Verifier: NOT_RUN
Risk: NOT_APPLICABLE (state=NOT_APPLICABLE, evaluated=NO)
DecisionTrace persisted: YES
Order created: NO
```

### ETH/USDT

```text
Regime: LOW_VOLATILITY
Strategies evaluated: 6
Selected: None
Decision: NO_TRADE
Reason: NO_ALPHA (no_candidate_emitted_an_alpha)
NO_TRADE kind: NO_TRADE_STRATEGIC
Verifier: NOT_RUN
Risk: NOT_APPLICABLE (state=NOT_APPLICABLE, evaluated=NO)
DecisionTrace persisted: YES
Order created: NO
```

## Cycle 2 — session 644ee77eee5a4fcc

### BTC/USDT

```text
Regime: LOW_VOLATILITY
Strategies evaluated: 6
Selected: None
Decision: NO_TRADE
Reason: NO_ALPHA (no_candidate_emitted_an_alpha)
NO_TRADE kind: NO_TRADE_STRATEGIC
Verifier: NOT_RUN
Risk: NOT_APPLICABLE (state=NOT_APPLICABLE, evaluated=NO)
DecisionTrace persisted: YES
Order created: NO
```

### ETH/USDT

```text
Regime: LOW_VOLATILITY
Strategies evaluated: 6
Selected: None
Decision: NO_TRADE
Reason: NO_ALPHA (no_candidate_emitted_an_alpha)
NO_TRADE kind: NO_TRADE_STRATEGIC
Verifier: NOT_RUN
Risk: NOT_APPLICABLE (state=NOT_APPLICABLE, evaluated=NO)
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
| outcomes_pending | 0 |
| performance_updates | 0 |
| no_trade_NO_TRADE_STRATEGIC | 4 |
| no_trade_NO_TRADE_RISK | 0 |
| no_trade_NO_TRADE_DATA | 0 |
| no_trade_NO_TRADE_CONFLICT | 0 |
| risk_APPROVED | 0 |
| risk_VETOED | 0 |
| risk_NOT_APPLICABLE | 4 |
| risk_NOT_EVALUATED | 0 |

`no_trades` counts NO_TRADE DECISIONS only; an operational failure (`runtime_failures`) is an incident, never a trading decision, and is never counted as a NO_TRADE hypothesis.

Trace chain: `{"broken_at": null, "detail": "hash chain intact", "ok": true, "records": 4}`

Production actions: 0

## Deterministic risk (one review per decision that carried a proposal)

- APPROVED: 0
- VETOED: 0
- NOT_APPLICABLE: 4
- NOT_EVALUATED: 0

An ADVISORY review (SHADOW / NO_TRADE) is informative only: it can neither authorise nor block an order. `NOT_EVALUATED` is never a PASS.

## Replay (from the persisted trace only)

Attempted: 4
Reconstructed OK: 4
Failed: 0
By status: {"PARTIAL": 4}
Market data accessed: False

`PARTIAL` means the decision was fully reconstructed but its horizon had not closed, so there is no outcome to replay yet.

## Outcomes pending at end of run (0)

- none

