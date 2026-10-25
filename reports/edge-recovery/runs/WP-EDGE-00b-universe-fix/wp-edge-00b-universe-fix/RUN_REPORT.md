# RUN wp-edge-00b-universe-fix

```text
run_id:      wp-edge-00b-universe-fix
commit:      6a3a09047bdce13977e23b512dbe075dabaa75ee
environment: ccxt:binance
mode:        paper
assets:      BTC, ETH, SOL
timeframe:   5m
cycles:      2
started:     1791801579331
ended:       1791801602649
```

## Cycle 1 — session 6cc056a5ee704873

### BTC/USDT

```text
Regime: RANGE
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

### SOL/USDT

```text
Regime: None
Strategies evaluated: 6
Selected: None
Decision: NO_TRADE
Reason: UNIVERSE_FILTERED (scanner_rejected:volume_below_threshold)
NO_TRADE kind: NO_TRADE_UNIVERSE
Verifier: NOT_RUN
Risk: NOT_APPLICABLE (state=NOT_APPLICABLE, evaluated=NO)
DecisionTrace persisted: YES
Order created: NO
```

## Cycle 2 — session 55ad92b1d178472e

### BTC/USDT

```text
Regime: RANGE
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

### SOL/USDT

```text
Regime: None
Strategies evaluated: 6
Selected: None
Decision: NO_TRADE
Reason: UNIVERSE_FILTERED (scanner_rejected:volume_below_threshold)
NO_TRADE kind: NO_TRADE_UNIVERSE
Verifier: NOT_RUN
Risk: NOT_APPLICABLE (state=NOT_APPLICABLE, evaluated=NO)
DecisionTrace persisted: YES
Order created: NO
```

## Totals

| Metric | Value |
| --- | ---: |
| asset_cycle_evaluations | 6 |
| paper_trades | 0 |
| shadow_trades | 0 |
| no_trades | 6 |
| runtime_failures | 0 |
| orders_created | 0 |
| traces_persisted | 6 |
| outcomes_resolved | 0 |
| outcomes_pending | 0 |
| performance_updates | 0 |
| no_trade_NO_TRADE_STRATEGIC | 4 |
| no_trade_NO_TRADE_RISK | 0 |
| no_trade_NO_TRADE_DATA | 0 |
| no_trade_NO_TRADE_UNIVERSE | 2 |
| no_trade_NO_TRADE_CONFLICT | 0 |
| risk_APPROVED | 0 |
| risk_VETOED | 0 |
| risk_NOT_APPLICABLE | 6 |
| risk_NOT_EVALUATED | 0 |

`no_trades` counts NO_TRADE DECISIONS only; an operational failure (`runtime_failures`) is an incident, never a trading decision, and is never counted as a NO_TRADE hypothesis.

Trace chain: `{"broken_at": null, "detail": "hash chain intact", "ok": true, "records": 6}`

Production actions: 0

## Deterministic risk (one review per decision that carried a proposal)

- APPROVED: 0
- VETOED: 0
- NOT_APPLICABLE: 6
- NOT_EVALUATED: 0

An ADVISORY review (SHADOW / NO_TRADE) is informative only: it can neither authorise nor block an order. `NOT_EVALUATED` is never a PASS.

## Replay (from the persisted trace only)

Attempted: 6
Reconstructed OK: 6
Failed: 0
By status: {"PARTIAL": 6}
Market data accessed: False

`PARTIAL` means the decision was fully reconstructed but its horizon had not closed, so there is no outcome to replay yet.

## Outcomes pending at end of run (0)

- none

