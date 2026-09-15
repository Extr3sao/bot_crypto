# ARC-01 PRIMARY DISCOVERY 01 — result

- **FINAL_STATUS**: `DISCOVERY_FAIL`
- **ARC01_STATE**: `KILLED_FOR_THIS_HYPOTHESIS_ID`
- **experiment_id**: `ARC01_PRIMARY_DISCOVERY_01`
- **prereg_commit**: `fa15fb4f300815f56bf14e503d1a147cb73f27a6`
- **data_authority_commit**: `6e42dd9d4c19800925fd555999686d1e2b4ef47e`
- **execution_implementation_commit**: `063c1de89c87d2275c03a9d576cd8a4bde688afa`
- **PREREG_DRIFT / DATA_AUTHORITY_DRIFT**: 0 / 0
- **ECONOMIC_EXPERIMENTS**: 1

## Critical gates

| gate | pass | value | requirement |
| --- | --- | --- | --- |
| G1_SAMPLE | PASS | N=347 {'BTCUSDT': 103, 'ETHUSDT': 111, 'SOLUSDT': 133} | >= 120 total AND >= 40 per asset |
| G2_NET_EXPECTANCY | PASS | 0.001197 | > 0 |
| G3_NET_EXPECTANCY_EX_FUNDING | FAIL | -0.000298 | > 0 |
| G4_PROFIT_FACTOR | FAIL | 1.0498 | >= 1.15 |
| G5_SHARPE | FAIL | 0.1447 | >= 0.5 |
| G6_BOOTSTRAP_CI | FAIL | CI=[-0.006285038898561406, 0.008634101545691794] P>0=0.6228 | 95% CI lower bound of mean net return > 0 |
| G7_PERMUTATION | FAIL | p=0.3766 | p <= 0.05 |
| G8_TEMPORAL_STABILITY | FAIL | halves=['0.005186', '-0.002768'] quarters=['-0.005238', '0.015490', '-0.007759', '0.002223'] | both halves > 0 AND >= 3/4 quartiles > 0 |
| G9_ASSET_STABILITY | PASS | 2/3 positive | >= 2 of 3 assets > 0 |
| G10_CONCENTRATION | FAIL | asset=1.3644294304455915 month=1.1919095863387563 trade=0.7156815760670594 | max asset <= 60% AND max month <= 40% AND max single trade <= 25% |
| G11_COST_SENSITIVITY | FAIL | 20bps=0.000197 40bps=-0.001803 | > 0 at 20bps AND >= 0 at 40bps |

**ALL_CRITICAL_GATES_PASS**: False · failed: ['G3_NET_EXPECTANCY_EX_FUNDING', 'G4_PROFIT_FACTOR', 'G5_SHARPE', 'G6_BOOTSTRAP_CI', 'G7_PERMUTATION', 'G8_TEMPORAL_STABILITY', 'G10_CONCENTRATION', 'G11_COST_SENSITIVITY']

## Controls

| control | n | all gates pass | failed gates |
| --- | --- | --- | --- |
| DIRECTION_CONTROL | 347 | False | ['G2_NET_EXPECTANCY', 'G3_NET_EXPECTANCY_EX_FUNDING', 'G4_PROFIT_FACTOR', 'G5_SHARPE', 'G6_BOOTSTRAP_CI', 'G7_PERMUTATION', 'G8_TEMPORAL_STABILITY', 'G9_ASSET_STABILITY', 'G10_CONCENTRATION', 'G11_COST_SENSITIVITY'] |
| TIMING_CONTROL_PLUS_8H | 187 | False | ['G2_NET_EXPECTANCY', 'G3_NET_EXPECTANCY_EX_FUNDING', 'G4_PROFIT_FACTOR', 'G5_SHARPE', 'G6_BOOTSTRAP_CI', 'G7_PERMUTATION', 'G8_TEMPORAL_STABILITY', 'G10_CONCENTRATION', 'G11_COST_SENSITIVITY'] |
| TIMING_CONTROL_MINUS_8H | 201 | False | ['G4_PROFIT_FACTOR', 'G5_SHARPE', 'G6_BOOTSTRAP_CI', 'G7_PERMUTATION', 'G8_TEMPORAL_STABILITY', 'G9_ASSET_STABILITY', 'G10_CONCENTRATION'] |
| OI_CONTROL | 469 | False | ['G2_NET_EXPECTANCY', 'G3_NET_EXPECTANCY_EX_FUNDING', 'G4_PROFIT_FACTOR', 'G5_SHARPE', 'G6_BOOTSTRAP_CI', 'G7_PERMUTATION', 'G8_TEMPORAL_STABILITY', 'G9_ASSET_STABILITY', 'G10_CONCENTRATION', 'G11_COST_SENSITIVITY'] |
| NULL_CONTROL | 347 | False | ['G2_NET_EXPECTANCY', 'G3_NET_EXPECTANCY_EX_FUNDING', 'G4_PROFIT_FACTOR', 'G5_SHARPE', 'G6_BOOTSTRAP_CI', 'G7_PERMUTATION', 'G8_TEMPORAL_STABILITY', 'G9_ASSET_STABILITY', 'G10_CONCENTRATION', 'G11_COST_SENSITIVITY'] |

**ANY_CONTROL_PASSES_ALL_GATES**: False

## Reconciliation

- ACCOUNTING_RECONCILIATION: `PASS`
- TRADE_LEDGER_RECONCILIATION: `PASS`
- PIT_EXECUTION_AUDIT: `PASS` (347 trades, 40 future-mutation probes)
- trades: 347 {'BTCUSDT': 103, 'ETHUSDT': 111, 'SOLUSDT': 133}

## Decision funnel

- funding_settlements_evaluated: 15780
- outside_window: 0
- insufficient_funding_history: 0
- scale_nonpositive: 0
- funding_not_extreme: 13891
- oi_missing_or_stale: 3
- oi_reference_missing_or_stale: 5
- oi_reference_invalid: 2
- oi_not_expanding: 957
- position_already_open: 574
- forward_price_unavailable: 1
- long_signals: 260
- short_signals: 87
- executed_trades: 347

## Cost curve (identical trade set)

| bps | mean net return | n |
| --- | --- | --- |
| 0bps | 0.002197 | 347 |
| 10bps | 0.001197 | 347 |
| 20bps | 0.000197 | 347 |
| 40bps | -0.001803 | 347 |

## Pooled decomposition

- gross expectancy: 0.000702
- funding cashflow expectancy: 0.001496
- net expectancy @10bps: 0.001197
- net expectancy ex-funding @10bps: -0.000298
- net expectancy @20bps / @40bps: 0.000197 / -0.001803
- profit factor @10bps: 1.0498
- win rate @10bps: 0.515850144092219
- long / short trades: 260 / 87
- mean holding hours: 72.0
- mean funding settlements applied: 9.121037463976945

## Non-gating diagnostics

- max drawdown (diagnostic only, NOT a gate): -1.186175
- equal-duration quartile expectancies (non-gating): [-4.333703722714768e-05, 0.0064802508967570244, -0.005130811724927226, 0.0026656270036183936]
- convention sensitivity: {"sharpe_window_days_primary": 1745.0, "sharpe_window_days_alternative": 1744.9583333333333, "sharpe_alternative": 0.14473347387089228, "month_attribution_primary": "TRADE_ENTRY_MONTH", "max_month_share_exit_attribution_alternative": 1.1705044821253652}
