# RFC-035S2 — rejection log

Rejection first: every candidate was attacked before promotion. The checks applied are: missing fees, look-ahead, future bars, optimised period, parameter mining, unavailable data, unrealistic fills, tiny sample, single-regime dependence, contradictory source results, abandoned repository, results not matching code.

- log_hash (sha256): `b466532f2251b527a58ea77397d35a4609844bcb3320e3787eba16017a99b78a`
- entries: 16
- promoted past the filter: C-02, C-07

## Reason counts

- COST_FLOOR_HEADROOM_NOT_ESTABLISHED: 9
- RULES_INCOMPLETE_MATERIAL_FIELDS: 8
- SOURCE_READ_LEVEL_INSUFFICIENT: 8
- NO_CODE: 7
- INSTRUMENT_OR_UNIVERSE_MISMATCH: 4
- NO_FIXED_PARAMETERS_RETRAINING_REQUIRED: 4
- NO_CANONICAL_PERIOD_OR_RESULTS: 3
- OVERFIT_RISK_PARAMETER_SEARCH: 2
- REPRODUCIBILITY_LLM_OR_HARDWARE: 2
- FORECAST_ONLY_NOT_A_STRATEGY: 1
- SAMPLE_TOO_SHORT: 1

## Entries

| CANDIDATE | CLASS | RULES | GRADE | PRIMARY REASON | CODES |
| --- | --- | --- | --- | --- | --- |
| C-01 | WATCH | 6/21 | E1 | RULES_INCOMPLETE_MATERIAL_FIELDS | RULES_INCOMPLETE_MATERIAL_FIELDS, NO_CANONICAL_PERIOD_OR_RESULTS, COST_FLOOR_HEADROOM_NOT_ESTABLISHED |
| C-03 | RESEARCH_HYPOTHESIS | 10/21 | E1 | RULES_INCOMPLETE_MATERIAL_FIELDS | RULES_INCOMPLETE_MATERIAL_FIELDS, NO_CANONICAL_PERIOD_OR_RESULTS, INSTRUMENT_OR_UNIVERSE_MISMATCH |
| C-04 | RESEARCH_HYPOTHESIS | 12/21 | E1 | RULES_INCOMPLETE_MATERIAL_FIELDS | RULES_INCOMPLETE_MATERIAL_FIELDS, NO_CODE, OVERFIT_RISK_PARAMETER_SEARCH, COST_FLOOR_HEADROOM_NOT_ESTABLISHED |
| C-05 | INSUFFICIENT_EVIDENCE | 0/21 | E1 | SOURCE_READ_LEVEL_INSUFFICIENT | SOURCE_READ_LEVEL_INSUFFICIENT, NO_CODE |
| C-06 | REJECT | 16/21 | E3 | INSTRUMENT_OR_UNIVERSE_MISMATCH | INSTRUMENT_OR_UNIVERSE_MISMATCH, COST_FLOOR_HEADROOM_NOT_ESTABLISHED |
| C-08 | REJECT | 9/21 | E3 | FORECAST_ONLY_NOT_A_STRATEGY | FORECAST_ONLY_NOT_A_STRATEGY, RULES_INCOMPLETE_MATERIAL_FIELDS, COST_FLOOR_HEADROOM_NOT_ESTABLISHED |
| C-09 | REJECT | 5/21 | E1 | COST_FLOOR_HEADROOM_NOT_ESTABLISHED | COST_FLOOR_HEADROOM_NOT_ESTABLISHED, SOURCE_READ_LEVEL_INSUFFICIENT, NO_FIXED_PARAMETERS_RETRAINING_REQUIRED |
| C-10 | INSUFFICIENT_EVIDENCE | 4/21 | E1 | SOURCE_READ_LEVEL_INSUFFICIENT | SOURCE_READ_LEVEL_INSUFFICIENT, NO_CODE, COST_FLOOR_HEADROOM_NOT_ESTABLISHED |
| C-11 | REJECT | 1/21 | E1 | REPRODUCIBILITY_LLM_OR_HARDWARE | REPRODUCIBILITY_LLM_OR_HARDWARE, RULES_INCOMPLETE_MATERIAL_FIELDS |
| C-12 | REJECT | 4/21 | E1 | OVERFIT_RISK_PARAMETER_SEARCH | OVERFIT_RISK_PARAMETER_SEARCH, NO_FIXED_PARAMETERS_RETRAINING_REQUIRED, NO_CODE, COST_FLOOR_HEADROOM_NOT_ESTABLISHED |
| C-13 | RESEARCH_HYPOTHESIS | 11/21 | E2 | NO_FIXED_PARAMETERS_RETRAINING_REQUIRED | NO_FIXED_PARAMETERS_RETRAINING_REQUIRED, RULES_INCOMPLETE_MATERIAL_FIELDS, COST_FLOOR_HEADROOM_NOT_ESTABLISHED, SAMPLE_TOO_SHORT |
| C-14 | WATCH | 5/21 | E3 | SOURCE_READ_LEVEL_INSUFFICIENT | SOURCE_READ_LEVEL_INSUFFICIENT, NO_CODE, RULES_INCOMPLETE_MATERIAL_FIELDS |
| C-15 | INSUFFICIENT_EVIDENCE | 5/21 | E1 | SOURCE_READ_LEVEL_INSUFFICIENT | SOURCE_READ_LEVEL_INSUFFICIENT, NO_CANONICAL_PERIOD_OR_RESULTS, COST_FLOOR_HEADROOM_NOT_ESTABLISHED |
| C-16 | REJECT | 3/21 | E1 | NO_FIXED_PARAMETERS_RETRAINING_REQUIRED | NO_FIXED_PARAMETERS_RETRAINING_REQUIRED, NO_CODE, INSTRUMENT_OR_UNIVERSE_MISMATCH, SOURCE_READ_LEVEL_INSUFFICIENT |
| C-17 | REJECT | 1/21 | E0 | REPRODUCIBILITY_LLM_OR_HARDWARE | REPRODUCIBILITY_LLM_OR_HARDWARE, RULES_INCOMPLETE_MATERIAL_FIELDS, SOURCE_READ_LEVEL_INSUFFICIENT |
| C-18 | INSUFFICIENT_EVIDENCE | 1/21 | E1 | SOURCE_READ_LEVEL_INSUFFICIENT | SOURCE_READ_LEVEL_INSUFFICIENT, NO_CODE, INSTRUMENT_OR_UNIVERSE_MISMATCH |

### C-01 — NostalgiaForInfinity — multi-pair 5m Freqtrade strategy

- classification: WATCH (rules 6/21, E1)
- reason codes: RULES_INCOMPLETE_MATERIAL_FIELDS, NO_CANONICAL_PERIOD_OR_RESULTS, COST_FLOOR_HEADROOM_NOT_ESTABLISHED
- counter-evidence: the README's own recommendations leave the universe and the number of open trades to the user
- counter-evidence: results are published as commit comments, so the 'original result' is not a stable artifact
- counter-evidence: the bundled auto-updater (nfi-updater) keeps changing the strategy, which breaks any frozen replication
- counter-evidence: a 5m strategy with a long tail (-stoploss in config) faces the project's 23.791 bps round trip on every round turn

### C-03 — Crypto and Stock Momentum (QuantConnect Quant League 2024-Q4)

- classification: RESEARCH_HYPOTHESIS (rules 10/21, E1)
- reason codes: RULES_INCOMPLETE_MATERIAL_FIELDS, NO_CANONICAL_PERIOD_OR_RESULTS, INSTRUMENT_OR_UNIVERSE_MISMATCH
- counter-evidence: the entry is marked 'pending review' and carried no readable metrics when it was fetched
- counter-evidence: half of the universe (US equities) cannot be traded by this project's crypto runtime
- counter-evidence: an explicit EMA100 + RSI + dual Supertrend + TWAP stack on a self-selected universe is a candidate for overfitting rather than a published result

### C-04 — Bitcoin MAX/Min breakout — Quantpedia's 2024 revisit (buy at the 10-day maximum)

- classification: RESEARCH_HYPOTHESIS (rules 12/21, E1)
- reason codes: RULES_INCOMPLETE_MATERIAL_FIELDS, NO_CODE, OVERFIT_RISK_PARAMETER_SEARCH, COST_FLOOR_HEADROOM_NOT_ESTABLISHED
- counter-evidence: the out-of-sample test was run by the same author as the in-sample study
- counter-evidence: the MIN leg did not survive out of sample, which is the direction the article had previously recommended as a combination
- counter-evidence: no position rule means the published result cannot be turned into trades without our own choices

### C-05 — Trend-following and Mean-reversion in Bitcoin (Quantpedia, 2022) — the earlier study

- classification: INSUFFICIENT_EVIDENCE (rules 0/21, E1)
- reason codes: SOURCE_READ_LEVEL_INSUFFICIENT, NO_CODE
- counter-evidence: only a search snippet was available for this round, so it is registered for completeness and not used as evidence

### C-06 — pysystemtrade / Carver's diversified trend-following system

- classification: REJECT (rules 16/21, E3)
- reason codes: INSTRUMENT_OR_UNIVERSE_MISMATCH, COST_FLOOR_HEADROOM_NOT_ESTABLISHED
- counter-evidence: reproducing it exactly requires a futures account, margin and 100 markets — none of which this project can trade
- counter-evidence: keeping only the trend component on BTC spot would be a new strategy, and the mission forbids relabelling our own design as an external replication

### C-08 — G-Research Crypto Forecasting (Kaggle 2022) — winning forecasting solutions

- classification: REJECT (rules 9/21, E3)
- reason codes: FORECAST_ONLY_NOT_A_STRATEGY, RULES_INCOMPLETE_MATERIAL_FIELDS, COST_FLOOR_HEADROOM_NOT_ESTABLISHED
- counter-evidence: strong evidence for a forecasting model, zero evidence for a tradable rule set
- counter-evidence: the winning solutions are trained models with per-competitor pipelines, so no single external strategy exists to replicate

### C-09 — bitcoin-momentum-trading — 5-minute ML momentum direction model

- classification: REJECT (rules 5/21, E1)
- reason codes: COST_FLOOR_HEADROOM_NOT_ESTABLISHED, SOURCE_READ_LEVEL_INSUFFICIENT, NO_FIXED_PARAMETERS_RETRAINING_REQUIRED
- counter-evidence: 5-minute crypto horizons are the regime the project's admission cost already killed internally
- counter-evidence: the model is retrained, so the 'same strategy' cannot be evaluated twice

### C-10 — Adaptive Regime-Based Trading on Bitcoin (15-minute, walk-forward)

- classification: INSUFFICIENT_EVIDENCE (rules 4/21, E1)
- reason codes: SOURCE_READ_LEVEL_INSUFFICIENT, NO_CODE, COST_FLOOR_HEADROOM_NOT_ESTABLISHED
- counter-evidence: a 15-minute cadence is structurally at odds with this project's measured cost floor
- counter-evidence: the claim could not be inspected beyond the abstract

### C-11 — Reflective LLM-based agent for zero-shot cryptocurrency trading

- classification: REJECT (rules 1/21, E1)
- reason codes: REPRODUCIBILITY_LLM_OR_HARDWARE, RULES_INCOMPLETE_MATERIAL_FIELDS
- counter-evidence: an LLM-dependent system cannot be re-run identically: the model version and prompt are part of the strategy and are not frozen artifacts

### C-12 — CGA-Agent — genetic-algorithm optimisation of crypto strategy parameters

- classification: REJECT (rules 4/21, E1)
- reason codes: OVERFIT_RISK_PARAMETER_SEARCH, NO_FIXED_PARAMETERS_RETRAINING_REQUIRED, NO_CODE, COST_FLOOR_HEADROOM_NOT_ESTABLISHED
- counter-evidence: an optimiser that adapts parameters to recent data guarantees look-ahead risk in any replication that reuses its fitted values
- counter-evidence: returns of +550% on one asset over an unspecified window are not comparable with anything this project measures

### C-13 — Daily ML direction trading on Bitcoin with a real unseen-period test (Crone, Brophy, Ward)

- classification: RESEARCH_HYPOTHESIS (rules 11/21, E2)
- reason codes: NO_FIXED_PARAMETERS_RETRAINING_REQUIRED, RULES_INCOMPLETE_MATERIAL_FIELDS, COST_FLOOR_HEADROOM_NOT_ESTABLISHED, SAMPLE_TOO_SHORT
- counter-evidence: the same paper documents that a widely cited benchmark in this literature trained on its own test data and mis-applied PCA — a reminder that this literature's reported numbers need auditing
- counter-evidence: a three-month test window cannot separate skill from a lucky regime

### C-14 — Karaptic Research — published-strategy replication series net of fees and slippage

- classification: WATCH (rules 5/21, E3)
- reason codes: SOURCE_READ_LEVEL_INSUFFICIENT, NO_CODE, RULES_INCOMPLETE_MATERIAL_FIELDS
- counter-evidence: the site's own honest-timestamp re-run cut the headline win rate from 85-100% to 63%, which is precisely the kind of correction this project's methodology demands
- counter-evidence: it is a venue for replications rather than an external strategy: the notes describe the author's own detector as well

### C-15 — Multi-Band Comparison Strategy (CRYPTO) — published Pine Script strategy

- classification: INSUFFICIENT_EVIDENCE (rules 5/21, E1)
- reason codes: SOURCE_READ_LEVEL_INSUFFICIENT, NO_CANONICAL_PERIOD_OR_RESULTS, COST_FLOOR_HEADROOM_NOT_ESTABLISHED
- counter-evidence: TradingView strategies are commonly tuned to one symbol and period, and the tester's default cost settings are optimistic relative to this project's 23.791 bps floor

### C-16 — Deep Momentum Networks (Lim/Zohren/Roberts and successors)

- classification: REJECT (rules 3/21, E1)
- reason codes: NO_FIXED_PARAMETERS_RETRAINING_REQUIRED, NO_CODE, INSTRUMENT_OR_UNIVERSE_MISMATCH, SOURCE_READ_LEVEL_INSUFFICIENT
- counter-evidence: a trained network is a pipeline, not a rule set: two runs are not the same strategy

### C-17 — An Adaptive Multi-Agent Bitcoin Trading System (LLM-driven)

- classification: REJECT (rules 1/21, E0)
- reason codes: REPRODUCIBILITY_LLM_OR_HARDWARE, RULES_INCOMPLETE_MATERIAL_FIELDS, SOURCE_READ_LEVEL_INSUFFICIENT
- counter-evidence: the system's decision layer is a proprietary model, so its behaviour cannot be frozen or audited

### C-18 — Momentum Trading in Cryptocurrencies: time-series vs cross-sectional (comparative study)

- classification: INSUFFICIENT_EVIDENCE (rules 1/21, E1)
- reason codes: SOURCE_READ_LEVEL_INSUFFICIENT, NO_CODE, INSTRUMENT_OR_UNIVERSE_MISMATCH
- counter-evidence: long/short cross-sectional momentum cannot be expressed in a long/cash spot runtime without inventing a long-only variant
