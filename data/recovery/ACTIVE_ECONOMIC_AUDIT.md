# ACTIVE ECONOMIC AUDIT (WP-3)

- generated `2026-10-12T18:40:43Z` · head `90cee7327e69` · branch `agent/edge-recovery/WP-EDGE-00-baseline`
- tracked admission ledger + primary research artefacts + the live registry code path + the paper lane's own reports; the runtime cost plane is re-derived from COST_MODEL_V3, never typed
- mode: offline read-only; no process started, nothing executed

## 1. What the pipeline is

| entrypoint | composes ledger | composes paper broker | ema/rsi/atr-only precompute | canonical |
| --- | --- | --- | --- | --- |
| `scripts/autonomous_paper.py` | yes | yes | no | yes |
| `scripts/start_paper_trading.py` | yes | yes | yes (DEF-206) | no |
| `scripts/paper_lab_research.py` | yes | no | no | no |
| `scripts/rfc010_baseline_replay.py` | yes | yes | no | no |
| `scripts/rfc021_ledger_pit.py` | yes | yes | no | no |

- ledger: **24 strategies, 0 admitted for paper** ({'COST_KILLED': 7, 'NO_GROSS_EDGE': 17}).
- live registry: paper-executable 5m/15m/1h = {'5m': [], '15m': [], '1h': []}; paper candidates [].

## 2. The cost plane (re-derived)

- scenario `BINANCE_SPOT_STANDARD_TAKER`: **23.353553391 bps** at 200 USDT (frozen value 23.353553391; reproduced: True); 1.5x stress 35.030330086 bps.
- research contract used by STRATEGY-DISCOVERY-V3: BASE 12.0 bps, 2x 24.0 bps, stressed 32.0 bps.
- components at 200 USDT: exchange_fee_entry 10.0 bps (KNOWN), exchange_fee_exit 10.0 bps (KNOWN), spread 1.0 bps (ESTIMATED), slippage 2.2828 bps (ESTIMATED), market_impact 0.0707 bps (ESTIMATED)

## 3. Every strategy, reconstructed

| strategy | status | trades | oos n | zero-cost gross bps | base net $ | base PF | expectancy bps | DEV gross bps | VAL gross bps | OOS gross bps | primary |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| `breakout@15m` | NO_GROSS_EDGE | 2042 | 227 | -1.822 | -1414.98 | 0.6847 | -13.858 | -2.002 | -1.076 | -4.1 | NO_ALPHA |
| `breakout@1h` | NO_GROSS_EDGE | 710 | 92 | -0.222 | -428.44 | 0.752 | -12.068 | -4.892 | 6.218 | 7.634 | NO_ALPHA |
| `breakout@30m` | NO_GROSS_EDGE | 1281 | 142 | -1.792 | -837.03 | 0.7201 | -13.068 | -3.16 | 1.206 | -3.914 | NO_ALPHA |
| `breakout@5m` | NO_GROSS_EDGE | 2426 | 233 | -0.084 | -1427.46 | 0.6612 | -12.544 | -0.6525 | None | -1.9107 | NO_ALPHA |
| `ema_crossover@15m` | NO_GROSS_EDGE | 2913 | 296 | -1.122 | -1934.45 | 0.6782 | -13.282 | -2.642 | 1.116 | -1.14 | NO_ALPHA |
| `ema_crossover@1h` | NO_GROSS_EDGE | 2620 | 337 | -0.964 | -1655.56 | 0.7385 | -12.638 | -1.856 | -2.724 | 5.152 | NO_ALPHA |
| `ema_crossover@30m` | NO_GROSS_EDGE | 3214 | 388 | -0.726 | -1956.55 | 0.729 | -12.176 | -2.596 | 1.296 | 2.32 | NO_ALPHA |
| `ema_crossover@5m` | NO_GROSS_EDGE | 1725 | 174 | -4.5608 | -1266.16 | 0.5017 | -16.222 | -5.3406 | None | -6.5966 | NO_ALPHA |
| `mean_reversion@15m` | COST_KILLED | 1579 | 199 | 2.714 | -703.12 | 0.7801 | -8.906 | 2.738 | 1.976 | 3.192 | EXECUTION_COST |
| `mean_reversion@1h` | NO_GROSS_EDGE | 448 | 56 | -2.226 | -322.53 | 0.7231 | -14.398 | -5.12 | -0.244 | 5.704 | NO_ALPHA |
| `mean_reversion@30m` | COST_KILLED | 934 | 118 | 5.472 | -274.77 | 0.8619 | -5.884 | 7.772 | 5.106 | -5.602 | EXECUTION_COST |
| `mean_reversion@5m` | COST_KILLED | 3190 | 351 | 1.4854 | -1514.34 | 0.6746 | -10.586 | -0.4083 | None | 0.3214 | EXECUTION_COST |
| `momentum@15m` | NO_GROSS_EDGE | 3003 | 378 | -3.972 | -2354.24 | 0.6544 | -15.68 | -6.116 | -2.466 | 2.054 | NO_ALPHA |
| `momentum@1h` | NO_GROSS_EDGE | 2304 | 282 | -2.334 | -1615.75 | 0.7231 | -14.026 | -4.776 | -0.182 | 4.694 | NO_ALPHA |
| `momentum@30m` | NO_GROSS_EDGE | 2957 | 351 | -2.612 | -2146.2 | 0.6972 | -14.516 | -3.876 | -2.32 | 1.65 | NO_ALPHA |
| `momentum@5m` | NO_GROSS_EDGE | 2526 | 289 | -1.8835 | -1679.33 | 0.6462 | -13.788 | -3.4413 | None | -4.2145 | NO_ALPHA |
| `trend@15m` | COST_KILLED | 1616 | 179 | 1.284 | -871.9 | 0.7831 | -10.79 | -1.984 | 10.212 | 2.082 | EXECUTION_COST |
| `trend@1h` | NO_GROSS_EDGE | 1405 | 136 | -1.252 | -895.07 | 0.7633 | -12.742 | -3.112 | 1.758 | 3.338 | NO_ALPHA |
| `trend@30m` | COST_KILLED | 1562 | 172 | 2.206 | -738.71 | 0.811 | -9.458 | -0.81 | 13.282 | -1.846 | EXECUTION_COST |
| `trend@5m` | NO_GROSS_EDGE | 1291 | 137 | -1.6448 | -876.83 | 0.7226 | -13.616 | -4.2023 | None | 7.4759 | NO_ALPHA |
| `volatility@15m` | NO_GROSS_EDGE | 277 | 42 | -7.064 | -261.88 | 0.6175 | -18.908 | -11.228 | -2.546 | -1.432 | NO_ALPHA |
| `volatility@1h` | COST_KILLED | 96 | 17 | 6.276 | -36.04 | 0.8441 | -7.508 | 15.242 | -12.556 | -4.518 | EXECUTION_COST |
| `volatility@30m` | COST_KILLED | 194 | 34 | 8.912 | -24.62 | 0.9402 | -2.538 | 21.326 | -14.236 | 3.116 | EXECUTION_COST |
| `volatility@5m` | NO_GROSS_EDGE | 520 | 62 | -4.7354 | -428.79 | 0.6175 | -16.524 | -5.134 | None | -6.8065 | NO_ALPHA |

Partition gross edges are `ZERO_COST` at 15m/30m/1h (the 2x arm was not run there) and `BASE_AFTER_SLIPPAGE` at 5m (the matrix publishes DEV and OOS slices only, no validation slice).

`null` means the artefact does not publish the value; it is listed per strategy in `missing_metrics` and is never estimated here.

## 4. Failure taxonomy

| category | primary | strategies flagged | examples |
| --- | ---: | ---: | --- |
| NO_ALPHA | 17 | 17 | breakout@15m, breakout@1h, breakout@30m, breakout@5m, ema_crossover@15m, ema_crossover@1h, ema_crossover@30m, ema_crossover@5m |
| EXECUTION_COST | 7 | 24 | breakout@15m, breakout@1h, breakout@30m, breakout@5m, ema_crossover@15m, ema_crossover@1h, ema_crossover@30m, ema_crossover@5m |
| DATA_QUALITY | 0 | 24 | breakout@15m, breakout@1h, breakout@30m, breakout@5m, ema_crossover@15m, ema_crossover@1h, ema_crossover@30m, ema_crossover@5m |
| INSUFFICIENT_SAMPLE | 0 | 1 | volatility@1h |
| REGIME_MISMATCH | 0 | 17 | breakout@1h, breakout@30m, ema_crossover@15m, ema_crossover@1h, ema_crossover@30m, mean_reversion@1h, mean_reversion@30m, mean_reversion@5m |
| ROBUSTNESS_FAILURE | 0 | 4 | ema_crossover@15m, ema_crossover@1h, ema_crossover@30m, ema_crossover@5m |
| IMPLEMENTATION_DEFECT | 0 | 20 | breakout@15m, breakout@1h, breakout@30m, breakout@5m, mean_reversion@15m, mean_reversion@1h, mean_reversion@30m, mean_reversion@5m |
| GOVERNANCE_BLOCK | 0 | 24 | breakout@15m, breakout@1h, breakout@30m, breakout@5m, ema_crossover@15m, ema_crossover@1h, ema_crossover@30m, ema_crossover@5m |

## 5. The paper lane

- run `paper-lab-continuous-02`: PAPER_24H_DATA_FAILED (false_success 0), 337 cycles, 0 paper trades, 0 shadow trades, 0 risk vetoes, every cycle `NO_TRADE_STRATEGIC`.
- window: 4.16 h usable of 24 h (17.33% coverage); M-03 NOT_READY, M-07 NOT_READY.
- why: The collector reached its own 800 MB disk budget after 4.16 h and stopped cleanly. The 24 h clean continuous window was not achieved; usable coverage against the 24 h objective is ~17.3%.
- cross-check against the lab report: {"claims_false_success_zero": true, "claims_lifecycle_histogram": false, "claims_zero_admitted": true, "claims_zero_trades": true, "source": "docs/PAPER_CONTINUOUS_STRATEGY_LAB_FINAL.md"}

## 6. Objective: three operations a day

- current: **0 operations/day**; requirement at the measured cost plane: 1095 round trips/year at 23.353553 bps = **25,572 bps** (255.7% of stake) per year.
- best measured gross edge: **8.912 bps/trade**; assessment **NOT_ACHIEVABLE_FROM_CURRENT_REGISTERED_FAMILIES**.
- the objective is not a quota: no operation may be generated to satisfy a frequency target

## 7. Defects

| id | status | summary |
| --- | --- | --- |
| DEF-ACT-01 | open (recorded here; the ledger is generated by scripts/build_strategy_admission.py) | the admission ledger publishes edge_evidence.sample_trades=0 for the 18 non-5m entries, while the primary artefact reports real trade counts for every one of those cells |
| DEF-206 | open, documented in MULTI_STRATEGY_ROUTING_AUDIT.md | the legacy paper entrypoint precomputes only ema_fast/ema_slow/rsi/atr, so the five families that read other keys return no signal there |
| DEF-ACT-02 | open | no per-timeframe admission matrix artefact exists: criteria c1..c9 were applied at 5m only, so the 15m/30m/1h cells carry no admission verdict of their own |
| DEF-ACT-03 | open (source artefact retained unmodified) | STRATEGY-DISCOVERY-V3 publishes breakout@5m gross_bps_per_trade = -0.11 while the same artefact's gross_usd and trades imply -0.084 bps; the other 23 cells agree exactly |
| RFC049C-DEF-01 | corrected | two stale FINAL_ADMISSION_REPORT hashes in RFC-049B's committed verifier artefact |

### Declared source discrepancies

| strategy | ledger bps | recomputed bps | delta bps | bound bps | defect |
| --- | ---: | ---: | ---: | ---: | --- |
| `breakout@5m` | -0.11 | -0.084 | 0.026 | 0.05 | DEF-ACT-03 |

## 8. Answers

### Q1_why_never_paper

Because no strategy ever satisfied the pre-registered admission criteria, and the ledger is fail-closed: 0 of 24 are admitted_for_paper, the runtime registry refuses all 24 before a proposal exists, and every paper cycle therefore ends NO_TRADE_STRATEGIC.

- 0/24 admitted; statuses {'COST_KILLED': 7, 'NO_GROSS_EDGE': 17}
- c2 (net>0), c3 (PF>1), c4 (OOS>0) and c7 (2x cost) fail for every family tested at 5m
- paper run paper-lab-continuous-02: 337 cycles, 0 trades, kind NO_TRADE_STRATEGIC

### Q2_how_many_positive_net_with_sample

Zero. No strategy has a positive net expectancy after the research cost line, with or without the sample test.

- 7 of 24 cells are gross-positive at zero cost (best 8.912 bps/trade) and every one of them is below both cost lines, so none becomes net-positive.

### Q3_dominant_limiter

The cost plane, on top of a weak entry. Two failures stack: five of six families have no gross edge at all (NO_ALPHA), and the one surviving family plus the best timeframes produce a gross edge that is smaller than the round trip they must pay (EXECUTION_COST). No cell clears either cost line, so the binding constraint is the cost plane and the ceiling is the gross edge.


```json
{
 "best_measured_gross_bps_per_trade": 8.912,
 "cells_clearing_admission_floor": 0,
 "cells_clearing_research_barrier": 0,
 "cells_gross_positive": 7,
 "research_base_rt_bps": 12.0,
 "runtime_admission_rt_bps": 23.353553390593273
}
```

### Q4_families_worth_new_experiments

Only as NEW preregistered hypotheses, never as a retune of the closed ones. The evidence supports exactly three lines: (a) the 30m horizon, where the gross edge peaks (volatility +8.91, mean_reversion +5.47, trend +2.21 bps) and turnover falls; (b) the entry itself, since the direction-adjusted forward return is negative at every horizon for every family, which points at signal construction rather than exits; (c) the cost plane, where the same cadence at a maker/futures venue is 13.79 bps instead of 23.79 bps.

- reports/strategy-baseline/TIMEFRAME_AUDIT.json: ZERO_COST cells with positive gross (volatility@30m, mean_reversion@30m, trend@30m, mean_reversion@15m, trend@15m, volatility@1h, mean_reversion@5m)
- reports/alpha-recovery-v1/STRATEGY_FAILURE_MATRIX.md: forward expectancy negative at +1/+3/+6/+12/+24 bars in every family
- docs/COST_MODEL_V3.json: BINANCE_USDM_PERP 13.79 bps vs BINANCE_SPOT_STANDARD 23.79 bps round trip

### Q5_what_is_missing_for_verifiable_paper

Four things, in this order.

- 1. At least one strategy that clears c1..c9 net of the runtime admission cost plane — nothing else in the list can be exercised before this exists.
- 2. A per-timeframe admission verdict and the missing metrics (max drawdown, observed spread) so the ledger is complete rather than partly unproven.
- 3. Runtime enablement behind admission: a router that can carry N eligible strategies, a portfolio policy for simultaneous signals, and the DEF-206 precompute fix — all only after (1).
- 4. Paper gate prerequisites: a clean continuous 24h window (last attempt 4.16h, 17.3% coverage, collector stopped on its own disk budget) and the M-03/M-07 history their gates require; plus the explicit operator authorization for paper promotion (currently NOT_AUTHORIZED).

### Q6_next_rfc

One work package is justified by the evidence: a cost-and-entry research campaign, to be registered as RFC-50 and to remain unauthorized until the operator amends the registry. Its first deliverable is not a strategy but a measured cost plane, because the evidence says the cost plane is what kills the edge.


## 9. Checks

| check | result | detail |
| --- | --- | --- |
| `sources:all_present` | PASS | ledger, V3 results, admission matrix, timeframe audit, criteria, cost model |
| `sources:tracked_or_declared` | PASS | the strategy evidence is tracked; the reports/ baselines are resolved from the evidence bundle |
| `inputs:every_external_input_resolves_from_the_commit` | PASS | 8 declared inputs resolve from the repository; resolved from: ['EVIDENCE_COPY', 'HEAD', 'LOCAL_MATERIALIZATION'] |
| `cost:reproduces_frozen_admission_round_trip` | PASS | derived 23.353553390593273 vs frozen 23.353553391 |
| `ledger:24_entries` | PASS | 24 entries |
| `ledger:zero_admitted` | PASS | admitted_for_paper=false everywhere |
| `registry:no_paper_executable` | PASS | {'5m': [], '15m': [], '1h': []} |
| `ledger:gross_edge_reproduces_from_primary_artefacts` | PASS | exact match 23/24; declared ['breakout@5m'] observed ['breakout@5m'] |
| `ledger:declared_mismatches_stay_immaterial` | PASS | breakout@5m delta 0.026 <= 0.05 bps |
| `economics:no_net_positive_strategy` | PASS | positive net expectancy: [] |
| `economics:no_gross_above_research_barrier` | PASS | max gross 8.912 bps vs 12.0 bps BASE round trip |
| `economics:no_gross_above_admission_floor` | PASS | max gross 8.912 bps vs 23.353553390593273 bps admission round trip |
| `taxonomy:every_strategy_classified` | PASS | categories used: ['EXECUTION_COST', 'NO_ALPHA'] |
| `taxonomy:no_invented_metric` | PASS | max_drawdown is null for every strategy and is named in missing_metrics |
| `paper:failure_recorded_honestly` | PASS | PAPER_24H_DATA_FAILED |
| `paper:no_trade_is_not_dressed_as_success` | PASS | trades=0 kind=NO_TRADE_STRATEGIC |
| `governance:closure_flags_respected` | PASS | NEXT_CAMPAIGN=NOT_AUTHORIZED, PAPER_PROMOTION=NOT_AUTHORIZED, LIVE_TRADING=DISABLED, TRADES_AUTHORIZED=0 |
| `governance:roadmap_assumes_no_authorization` | PASS | NEXT_CAMPAIGN=NOT_AUTHORIZED — the roadmap proposes; only the operator authorizes |
| `runtime:def206_evidence_verified` | PASS | scripts/start_paper_trading.py still carries the ema/rsi/atr-only precompute |

**19/19 checks pass; checks_failed = 0.**

