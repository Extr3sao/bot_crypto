# RFC-035S2 — final report

- status: **CONTINUE_SEARCH** (RFC-035 stays OPEN; RFC-036 NOT_OPEN)
- sources reviewed this round: 44 (round-1 registry retained: 20)
- candidates extracted: 18 (strategies 11, hypotheses 5, research tasks 2)
- rejected: 7
- REPLICATE_P0: NONE
- REPLICATE_P1: C-02, C-07
- next gate: RFC-035 = CONTINUE_SEARCH

## Why there is no P0 this round

- no source read this round defines every material field of a trading strategy: the two closest (C-02, C-07) have 15 of 21 required fields defined, and the missing ones are costs, execution and (for C-02) the original period and metrics
- no candidate combines a complete rule set with E2-or-better evidence and a declared cost model
- the strongest independently evaluated crypto result found (G-Research, E3) has no trading layer at all
- promoting any candidate to REPLICATE_P0 would require inventing the fields the mission forbids inventing

## Closest candidates


### C-02 — Strategy001 (freqtrade-strategies) — EMA20/50 cross with Heikin-Ashi confirmation on 5m

- source: S2-03 · code: DEFINED this exact file in freqtrade/freqtrade-strategies
- rule completeness: 15/21 (unknown: assets, sizing_rule, warmup, transaction_costs, original_period, original_metrics)
- data: DEFINED exchange OHLCV (freqtrade download-data)
- original period: UNKNOWN nothing is published with the file
- original trade count: UNKNOWN
- original metrics: UNKNOWN the corpus README shows results as links/images, not as numbers
- cost model: UNKNOWN no fee or slippage model; freqtrade applies whatever the user's config says
- evidence level: E1
- counter-evidence: the corpus README itself calls these strategies starting points and warns that results depend on the user's pairs and period
- counter-evidence: the file's own comment notes that minimal_roi and stoploss are overridden by the user's config
- counter-evidence: no backtest is published with the file, so there is no external result to reproduce — only an external rule set

### C-07 — Q24 Crypto Guide Strategy (Quantiacs) — SMA15/34 + RSI14 long-only crypto daily

- source: S2-08 · code: DEFINED the published example, cloneable in the platform (the code is in the page)
- rule completeness: 15/21 (unknown: exit_stop, exit_target, execution_assumption, transaction_costs, original_metrics, source_version)
- data: DEFINED Quantiacs cryptodaily dataset (qnt.data.cryptodaily_load_data, min_date 2015-01-01) plus the is_liquid field
- original period: DEFINED in-sample from 2016-01-01 (earlier data may be used for testing/training)
- original trade count: UNKNOWN
- original metrics: UNKNOWN the page shows the statistics call but not its output; the contest requires an in-sample Sharpe above 1.0 for validity
- cost model: UNKNOWN the page states no cost assumption; the statistics function decides what is charged
- evidence level: E2
- counter-evidence: the contest's own gate is in-sample Sharpe, which selects for overfitting and says nothing about costs
- counter-evidence: the page's benchmark download raised an HTTP 404 while being read, so even the benchmark call is currently broken
- counter-evidence: long-only by rule, so the strategy has no way to express a negative view
- counter-evidence: nothing about the example's realised live paper performance is public

## Top rejection reasons

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

## What round 3 must find

- a source that states, or ships as code, every material field: entry, exit (including stop and target), sizing, execution assumptions and a transaction-cost model
- a published original period with a trade count and metrics, so success or failure is objectively measurable
- a turnover profile compatible with the project's 23.791 bps round trip, or an explicit cost model that shows why it is not
- candidates already on this list to be read at full-text level: C-01 (NostalgiaForInfinity code, pinned to a release), C-07 (Quantiacs cost model), C-14 (Karaptic notes), C-15 (Pine source and tester settings)

## Freeze

- freeze taken: False — RFC-035S2 section 15 freezes a candidate only when one is selected as REPLICATE_P0. This round selected none, so there is nothing to freeze and no local backtest was run.

## Verification

- verifier: scripts/rfc035s2_verify.py
- artifact: reports/rfc035/search_round_2/INDEPENDENT_VERIFICATION.json
- status and FALSE_SUCCESS are written by the verifier into that artifact and into this block
- verification status: **PASS** (863/863 checks, FALSE_SUCCESS = 0)

## Limitations

- nothing in this round is a profitability claim: the mission only asked whether a strategy exists that could be reproduced exactly
- several sources were read at listing level because they are bot-blocked or paywalled; each one is marked and none of them was promoted
- no candidate was backtested locally: RFC-035S2 section 15 forbids letting a local test influence selection
