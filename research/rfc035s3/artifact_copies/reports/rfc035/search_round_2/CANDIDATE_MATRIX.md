# RFC-035S2 — candidate matrix

Every candidate below was extracted from a source actually read, and every material field carries its own status. `rule_completeness` is derived from that table, never hand-written.

- matrix_hash (sha256): `86eef61fbcc457ccc4146d6dfba45c9c6d7d75e3b20aa024a90d9890da3acb7f`
- candidates: 18
- hard invariant: UNKNOWN_MATERIAL_RULES > 0 -> REPLICATE_P0 FORBIDDEN

| CANDIDATE | KIND | CLASS | RULES | GRADE | TITLE |
| --- | --- | --- | --- | --- | --- |
| C-01 | EXTERNAL_STRATEGY | WATCH | 6/21 | E1 | NostalgiaForInfinity — multi-pair 5m Freqtrade strategy |
| C-02 | EXTERNAL_STRATEGY | REPLICATE_P1 | 15/21 | E1 | Strategy001 (freqtrade-strategies) — EMA20/50 cross with Heikin-Ashi confirmation on 5m |
| C-03 | EXTERNAL_STRATEGY | RESEARCH_HYPOTHESIS | 10/21 | E1 | Crypto and Stock Momentum (QuantConnect Quant League 2024-Q4) |
| C-04 | EXTERNAL_STRATEGY | RESEARCH_HYPOTHESIS | 12/21 | E1 | Bitcoin MAX/Min breakout — Quantpedia's 2024 revisit (buy at the 10-day maximum) |
| C-05 | RESEARCH_HYPOTHESIS | INSUFFICIENT_EVIDENCE | 0/21 | E1 | Trend-following and Mean-reversion in Bitcoin (Quantpedia, 2022) — the earlier study |
| C-06 | EXTERNAL_STRATEGY | REJECT | 16/21 | E3 | pysystemtrade / Carver's diversified trend-following system |
| C-07 | EXTERNAL_STRATEGY | REPLICATE_P1 | 15/21 | E2 | Q24 Crypto Guide Strategy (Quantiacs) — SMA15/34 + RSI14 long-only crypto daily |
| C-08 | RESEARCH_TASK | REJECT | 9/21 | E3 | G-Research Crypto Forecasting (Kaggle 2022) — winning forecasting solutions |
| C-09 | EXTERNAL_STRATEGY | REJECT | 5/21 | E1 | bitcoin-momentum-trading — 5-minute ML momentum direction model |
| C-10 | RESEARCH_HYPOTHESIS | INSUFFICIENT_EVIDENCE | 4/21 | E1 | Adaptive Regime-Based Trading on Bitcoin (15-minute, walk-forward) |
| C-11 | RESEARCH_HYPOTHESIS | REJECT | 1/21 | E1 | Reflective LLM-based agent for zero-shot cryptocurrency trading |
| C-12 | EXTERNAL_STRATEGY | REJECT | 4/21 | E1 | CGA-Agent — genetic-algorithm optimisation of crypto strategy parameters |
| C-13 | EXTERNAL_STRATEGY | RESEARCH_HYPOTHESIS | 11/21 | E2 | Daily ML direction trading on Bitcoin with a real unseen-period test (Crone, Brophy, Ward) |
| C-14 | RESEARCH_TASK | WATCH | 5/21 | E3 | Karaptic Research — published-strategy replication series net of fees and slippage |
| C-15 | EXTERNAL_STRATEGY | INSUFFICIENT_EVIDENCE | 5/21 | E1 | Multi-Band Comparison Strategy (CRYPTO) — published Pine Script strategy |
| C-16 | EXTERNAL_STRATEGY | REJECT | 3/21 | E1 | Deep Momentum Networks (Lim/Zohren/Roberts and successors) |
| C-17 | RESEARCH_HYPOTHESIS | REJECT | 1/21 | E0 | An Adaptive Multi-Agent Bitcoin Trading System (LLM-driven) |
| C-18 | RESEARCH_HYPOTHESIS | INSUFFICIENT_EVIDENCE | 1/21 | E1 | Momentum Trading in Cryptocurrencies: time-series vs cross-sectional (comparative study) |

## C-01 — NostalgiaForInfinity — multi-pair 5m Freqtrade strategy

- sources: S2-04, S2-01
- kind / classification / evidence: EXTERNAL_STRATEGY · WATCH · E1
- rule completeness: 6/21 (defined 6 of 21)
- unknown material fields: assets, data_fields, entry_long, entry_short, exit_stop, exit_target, exit_time, exit_signal, parameters, sizing_rule, execution_assumption, warmup, transaction_costs, original_period, original_metrics
- evidence basis: the repository's own description: rules live in code, results in commit comments
- economic claim: no stable metric is published; the authoring community reports the strategy as live-traded, which is a claim rather than a measurable original result
- frequency: {'trades_per_day': 'UNKNOWN', 'holding_period': 'minutes to days (ROI ladder)', 'historical_trade_count': 'UNKNOWN', 'cadence': '5m'}
- cost floor: NOT_ESTABLISHED: the README states no win rate, no average trade and no turnover, so the claimed edge cannot be compared with the 23.791 bps round trip
- replication risk: {'DATA_DEPENDENCY': 'LOW', 'TIMESTAMP_AMBIGUITY': 'LOW', 'EXECUTION_AMBIGUITY': 'HIGH', 'PARAMETER_AMBIGUITY': 'HIGH', 'SURVIVORSHIP_RISK': 'LOW', 'LOOKAHEAD_RISK': 'LOW', 'OVERFIT_RISK': 'HIGH', 'CAPACITY_RISK': 'LOW', 'MARKET_DECAY_RISK': 'MEDIUM'}
- gaps to P0: read and pin the strategy file at a release tag; fix a pairlist and a stake rule (the source leaves both to the user); locate a canonical period and result set instead of per-commit comments; establish turnover so the 5m cadence can be compared with the cost floor
- reason codes: RULES_INCOMPLETE_MATERIAL_FIELDS, NO_CANONICAL_PERIOD_OR_RESULTS, COST_FLOOR_HEADROOM_NOT_ESTABLISHED
- counter-evidence: the README's own recommendations leave the universe and the number of open trades to the user; results are published as commit comments, so the 'original result' is not a stable artifact; the bundled auto-updater (nfi-updater) keeps changing the strategy, which breaks any frozen replication; a 5m strategy with a long tail (-stoploss in config) faces the project's 23.791 bps round trip on every round turn
- material fields: market=DEFINED; assets=UNKNOWN; timeframe=DEFINED; data_source=DEFINED; data_fields=UNKNOWN; entry_long=UNKNOWN; entry_short=UNKNOWN; exit_stop=UNKNOWN; exit_target=UNKNOWN; exit_time=UNKNOWN; exit_signal=UNKNOWN; parameters=UNKNOWN; sizing_rule=UNKNOWN; execution_assumption=UNKNOWN; session_rules=DEFINED; warmup=UNKNOWN; transaction_costs=UNKNOWN; original_period=UNKNOWN; original_metrics=UNKNOWN; implementation_source=DEFINED; source_version=DEFINED
- field notes: market: crypto spot, stablecoin pairs preferred (README); assets: the README recommends 40-80 user-selected pairs; the strategy declares no universe; timeframe: 5m — the README says the timeframe must not be overridden; data_source: exchange OHLCV downloaded by freqtrade; data_fields: the indicator set lives in the strategy file, which was not read this round; entry_long: code exists and is versioned, but the file was not read here; entry_short: same; exit_stop: same; exit_target: same; exit_time: same; exit_signal: same; parameters: the repository ships an auto-updater; parameters must be pinned to a release tag before they are fixed; sizing_rule: 'between 6 and 12 open trades, with unlimited stake' is a range, not a rule; execution_assumption: not stated; session_rules: none declared (24/7 market); warmup: not stated; transaction_costs: not stated; original_period: the README points at backtest results in per-commit comments; original_metrics: same; implementation_source: the repository; source_version: releases and commits exist and can be pinned
- note: registered as a real external strategy whose rule file was not read in this round; the next round must read and pin it

## C-02 — Strategy001 (freqtrade-strategies) — EMA20/50 cross with Heikin-Ashi confirmation on 5m

- sources: S2-03, S2-01
- kind / classification / evidence: EXTERNAL_STRATEGY · REPLICATE_P1 · E1
- rule completeness: 15/21 (defined 15 of 21)
- unknown material fields: assets, sizing_rule, warmup, transaction_costs, original_period, original_metrics
- evidence basis: the strategy source read in full (rules, ROI, stoploss, order types)
- economic claim: no result is claimed anywhere: the file is a rule set without a published period, trade count or return
- frequency: {'trades_per_day': 'UNKNOWN', 'holding_period': 'minutes (ROI ladder is intraday)', 'historical_trade_count': 'UNKNOWN', 'cadence': '5m'}
- cost floor: NOT_ESTABLISHED: the first ROI bucket (1%) is about 42x the 23.791 bps round trip, but with an unknown hit rate, an unknown trade count and a -10% stop the source supports no headroom claim either way
- replication risk: {'DATA_DEPENDENCY': 'LOW', 'TIMESTAMP_AMBIGUITY': 'LOW', 'EXECUTION_AMBIGUITY': 'LOW', 'PARAMETER_AMBIGUITY': 'LOW', 'SURVIVORSHIP_RISK': 'LOW', 'LOOKAHEAD_RISK': 'MEDIUM', 'OVERFIT_RISK': 'HIGH', 'CAPACITY_RISK': 'LOW', 'MARKET_DECAY_RISK': 'HIGH'}
- gaps to P0: no published original period or metrics exist to replicate; universe and stake rule must be chosen by us (material invention); no transaction-cost model in the source; the 5m cadence must be tested against the cost floor before any claim
- counter-evidence: the corpus README itself calls these strategies starting points and warns that results depend on the user's pairs and period; the file's own comment notes that minimal_roi and stoploss are overridden by the user's config; no backtest is published with the file, so there is no external result to reproduce — only an external rule set
- material fields: market=DEFINED; assets=UNKNOWN; timeframe=DEFINED; data_source=DEFINED; data_fields=DEFINED; entry_long=DEFINED; entry_short=UNSUPPORTED_BY_SOURCE; exit_stop=DEFINED; exit_target=DEFINED; exit_time=DEFINED; exit_signal=DEFINED; parameters=DEFINED; sizing_rule=UNKNOWN; execution_assumption=DEFINED; session_rules=DEFINED; warmup=UNKNOWN; transaction_costs=UNKNOWN; original_period=UNKNOWN; original_metrics=UNKNOWN; implementation_source=DEFINED; source_version=DEFINED
- field notes: market: crypto spot pairs traded through freqtrade; assets: the file declares no pairlist; the README says results depend on the user's pairs, timeframe and timerange; timeframe: 5m (timeframe = '5m' in the file); data_source: exchange OHLCV (freqtrade download-data); data_fields: OHLCV plus EMA20/EMA50/EMA100 and Heikin-Ashi open/close derived from it; entry_long: enter when EMA20 crosses above EMA50, the Heikin-Ashi bar is green and ha_close > EMA20; entry_short: the file defines enter_long only (interface version 3); exit_stop: stoploss = -0.10; exit_target: minimal_roi ladder {60: 0.01, 30: 0.03, 20: 0.04, 0: 0.05}; exit_time: the ROI ladder's time buckets (1% if closed within 60 min, 3% within 30, 4% within 20, 5% at any time); exit_signal: exit when EMA50 crosses above EMA100 with ha_close < EMA20 and a red Heikin-Ashi bar, use_exit_signal = True; parameters: every parameter is a literal in the file (EMA 20/50/100, 5m, stoploss -0.10, the ROI ladder); sizing_rule: stake amount and tradable balance come from the user's config, which the source does not fix; execution_assumption: order_types entry=limit, exit=limit, stoploss=market, stoploss_on_exchange=False; process_only_new_candles=True; session_rules: none declared (24/7 market); warmup: the file never declares startup_candle_count, so the warm-up is implicit in EMA100 rather than stated; transaction_costs: no fee or slippage model; freqtrade applies whatever the user's config says; original_period: nothing is published with the file; original_metrics: the corpus README shows results as links/images, not as numbers; implementation_source: this exact file in freqtrade/freqtrade-strategies; source_version: the blob itself is the version (pin the file hash)
- note: the most complete rule set read this round; it is a replicable *rule set*, not a replicable *result*

## C-03 — Crypto and Stock Momentum (QuantConnect Quant League 2024-Q4)

- sources: S2-06, S2-05, S2-40
- kind / classification / evidence: EXTERNAL_STRATEGY · RESEARCH_HYPOTHESIS · E1
- rule completeness: 10/21 (defined 10 of 21)
- unknown material fields: assets, exit_stop, exit_target, sizing_rule, execution_assumption, session_rules, warmup, transaction_costs, original_period, original_metrics, source_version
- evidence basis: the entry's own write-up (rules stated in prose), no readable results
- economic claim: no measurable claim is published with the entry
- frequency: {'trades_per_day': 'UNKNOWN', 'holding_period': 'days to weeks (Supertrend exit)', 'historical_trade_count': 'UNKNOWN', 'cadence': 'daily'}
- cost floor: NOT_ESTABLISHED: no turnover or return is published, so no comparison with the 23.791 bps round trip is possible
- replication risk: {'DATA_DEPENDENCY': 'MEDIUM', 'TIMESTAMP_AMBIGUITY': 'LOW', 'EXECUTION_AMBIGUITY': 'HIGH', 'PARAMETER_AMBIGUITY': 'HIGH', 'SURVIVORSHIP_RISK': 'MEDIUM', 'LOOKAHEAD_RISK': 'MEDIUM', 'OVERFIT_RISK': 'HIGH', 'CAPACITY_RISK': 'LOW', 'MARKET_DECAY_RISK': 'MEDIUM'}
- gaps to P0: no published result, period or trade count; the asset universe is self-selected rather than specified; no sizing, stop or cost model; the stock sleeve is outside this project's crypto universe
- reason codes: RULES_INCOMPLETE_MATERIAL_FIELDS, NO_CANONICAL_PERIOD_OR_RESULTS, INSTRUMENT_OR_UNIVERSE_MISMATCH
- counter-evidence: the entry is marked 'pending review' and carried no readable metrics when it was fetched; half of the universe (US equities) cannot be traded by this project's crypto runtime; an explicit EMA100 + RSI + dual Supertrend + TWAP stack on a self-selected universe is a candidate for overfitting rather than a published result
- material fields: market=DEFINED; assets=UNKNOWN; timeframe=DEFINED; data_source=DEFINED; data_fields=DEFINED; entry_long=DEFINED; entry_short=UNSUPPORTED_BY_SOURCE; exit_stop=UNKNOWN; exit_target=UNKNOWN; exit_time=DEFINED; exit_signal=DEFINED; parameters=DEFINED; sizing_rule=UNKNOWN; execution_assumption=UNKNOWN; session_rules=UNKNOWN; warmup=UNKNOWN; transaction_costs=UNKNOWN; original_period=UNKNOWN; original_metrics=UNKNOWN; implementation_source=DEFINED; source_version=UNKNOWN
- field notes: market: crypto (BTC, ETH) and US large-cap equities, long only; assets: 'selected stocks among the top 1000 companies ... based on best-fitted market structure' — a self-selected universe, not a rule; timeframe: daily decisions executed at the end of the day; data_source: QuantConnect market data (platform); data_fields: daily bars sufficient for EMA100, RSI10, Supertrend(10, 2.5/3) and a weekly TWAP; entry_long: price > 100-day EMA and 10-day RSI > 50 and both Supertrend indicators flipped bullish and price > 20% below the weekly TWAP for BTC/ETH (4% for stocks); entry_short: the write-up describes long entries only; exit_stop: no stop is stated; exit_target: no target is stated; exit_time: trades are executed at the end of any day on which the conditions are met; exit_signal: exit on the Supertrend bend ('confirming the bend of the trend at the exit'); parameters: EMA100, RSI10 > 50, Supertrend 10-day with multipliers 2.5 and 3, weekly TWAP with 20%/4% thresholds; sizing_rule: not stated; execution_assumption: not stated (platform defaults); session_rules: not stated; the equity sleeve implies market hours; warmup: not stated (EMA100 implies 100 days); transaction_costs: none stated; original_period: not stated; original_metrics: the page exposes an 'Update Backtest' widget; no numbers were readable; implementation_source: cloneable inside QuantConnect; source_version: a live competition page marked 'pending review', with no version or commit
- note: the prose gives entry conditions but the entry is not a frozen, measurable external system

## C-04 — Bitcoin MAX/Min breakout — Quantpedia's 2024 revisit (buy at the 10-day maximum)

- sources: S2-10, S2-11
- kind / classification / evidence: EXTERNAL_STRATEGY · RESEARCH_HYPOTHESIS · E1
- rule completeness: 12/21 (defined 12 of 21)
- unknown material fields: exit_stop, exit_target, exit_time, exit_signal, sizing_rule, execution_assumption, transaction_costs, original_metrics, implementation_source
- evidence basis: a research house's own study with an explicit out-of-sample section, no code and no numeric capture
- economic claim: the article states both legs were effective in sample; out of sample the MAX leg 'remains alive and well' while buying at the MIN 'has not performed well'
- frequency: {'trades_per_day': '<1 (only on new extremes)', 'holding_period': 'UNKNOWN', 'historical_trade_count': 'UNKNOWN', 'cadence': 'daily'}
- cost floor: PLAUSIBLE_BUT_UNVERIFIED: a daily breakout that exits on a signal could turn over slowly enough to clear the 23.791 bps round trip, but the source states neither an exit nor a trade count
- replication risk: {'DATA_DEPENDENCY': 'LOW', 'TIMESTAMP_AMBIGUITY': 'LOW', 'EXECUTION_AMBIGUITY': 'MEDIUM', 'PARAMETER_AMBIGUITY': 'HIGH', 'SURVIVORSHIP_RISK': 'LOW', 'LOOKAHEAD_RISK': 'MEDIUM', 'OVERFIT_RISK': 'MEDIUM', 'CAPACITY_RISK': 'LOW', 'MARKET_DECAY_RISK': 'MEDIUM'}
- gaps to P0: exit, sizing and execution assumptions are absent, so the object is not yet a strategy; the lookback is the best of five tested values; no cost model; no code, so the signal computation would be re-implemented by us
- reason codes: RULES_INCOMPLETE_MATERIAL_FIELDS, NO_CODE, OVERFIT_RISK_PARAMETER_SEARCH, COST_FLOOR_HEADROOM_NOT_ESTABLISHED
- counter-evidence: the out-of-sample test was run by the same author as the in-sample study; the MIN leg did not survive out of sample, which is the direction the article had previously recommended as a combination; no position rule means the published result cannot be turned into trades without our own choices
- material fields: market=DEFINED; assets=DEFINED; timeframe=DEFINED; data_source=DEFINED; data_fields=DEFINED; entry_long=DEFINED; entry_short=UNSUPPORTED_BY_SOURCE; exit_stop=UNKNOWN; exit_target=UNKNOWN; exit_time=UNKNOWN; exit_signal=UNKNOWN; parameters=DEFINED; sizing_rule=UNKNOWN; execution_assumption=UNKNOWN; session_rules=DEFINED; warmup=DEFINED; transaction_costs=UNKNOWN; original_period=DEFINED; original_metrics=UNKNOWN; implementation_source=UNKNOWN; source_version=DEFINED
- field notes: market: BTC daily spot, long only; assets: BTC; timeframe: daily; data_source: Gemini daily BTC prices at 0:00, published on the article's data page; data_fields: daily open price series; entry_long: buy when the price prints the maximum of the previous x days (MAX); the MIN leg buys at the x-day minimum; entry_short: the study is long-only; exit_stop: no stop is stated; exit_target: no target is stated; exit_time: the article measures forward returns; no holding period or exit date is stated; exit_signal: no exit signal is stated; parameters: x ∈ {10, 20, 30, 40, 50}; 10 is nominated as the most effective, i.e. the parameter comes from a five-point sweep; sizing_rule: not stated; execution_assumption: not stated; session_rules: daily bars (0:00 prices), no session constraint; warmup: x days of history (x = lookback); transaction_costs: no fee or slippage is mentioned; original_period: in-sample 2015-11-11..2024-08-20; the article's own out-of-sample 2022-02-04..2024-08-20; original_metrics: the tables and graphs were not captured numerically at this read level; implementation_source: no code is published; source_version: the article is dated 2024-09-12 at a stable URL
- note: the strongest research hypothesis of this round and the closest thing to an externally published signal with a genuine unseen-period test

## C-05 — Trend-following and Mean-reversion in Bitcoin (Quantpedia, 2022) — the earlier study

- sources: S2-11
- kind / classification / evidence: RESEARCH_HYPOTHESIS · INSUFFICIENT_EVIDENCE · E1
- rule completeness: 0/21 (defined 0 of 21)
- unknown material fields: market, assets, timeframe, data_source, data_fields, entry_long, entry_short, exit_stop, exit_target, exit_time, exit_signal, parameters, sizing_rule, execution_assumption, session_rules, warmup, transaction_costs, original_period, original_metrics, implementation_source, source_version
- evidence basis: search-result summary only; superseded by S2-10 for this round's purposes
- economic claim: the 2024 revisit states the original strategies are 'slightly less effective' on the longer sample
- frequency: {'trades_per_day': 'UNKNOWN', 'holding_period': 'UNKNOWN', 'historical_trade_count': 'UNKNOWN', 'cadence': 'daily'}
- cost floor: NOT_ASSESSED: nothing was read beyond the summary
- replication risk: {'DATA_DEPENDENCY': 'MEDIUM', 'TIMESTAMP_AMBIGUITY': 'MEDIUM', 'EXECUTION_AMBIGUITY': 'MEDIUM', 'PARAMETER_AMBIGUITY': 'HIGH', 'SURVIVORSHIP_RISK': 'LOW', 'LOOKAHEAD_RISK': 'MEDIUM', 'OVERFIT_RISK': 'MEDIUM', 'CAPACITY_RISK': 'LOW', 'MARKET_DECAY_RISK': 'HIGH'}
- gaps to P0: read the underlying study before it can be treated as a candidate; no code
- reason codes: SOURCE_READ_LEVEL_INSUFFICIENT, NO_CODE
- counter-evidence: only a search snippet was available for this round, so it is registered for completeness and not used as evidence
- material fields: market=UNKNOWN; assets=UNKNOWN; timeframe=UNKNOWN; data_source=UNKNOWN; data_fields=UNKNOWN; entry_long=UNKNOWN; entry_short=UNKNOWN; exit_stop=UNKNOWN; exit_target=UNKNOWN; exit_time=UNKNOWN; exit_signal=UNKNOWN; parameters=UNKNOWN; sizing_rule=UNKNOWN; execution_assumption=UNKNOWN; session_rules=UNKNOWN; warmup=UNKNOWN; transaction_costs=UNKNOWN; original_period=UNKNOWN; original_metrics=UNKNOWN; implementation_source=UNKNOWN; source_version=UNKNOWN
- field notes: market: read at listing level; assets: read at listing level; timeframe: read at listing level; data_source: read at listing level; data_fields: read at listing level; entry_long: read at listing level; entry_short: read at listing level; exit_stop: UNKNOWN; exit_target: UNKNOWN; exit_time: UNKNOWN; exit_signal: UNKNOWN; parameters: UNKNOWN; sizing_rule: UNKNOWN; execution_assumption: UNKNOWN; session_rules: UNKNOWN; warmup: UNKNOWN; transaction_costs: UNKNOWN; original_period: only the search summary was seen; original_metrics: UNKNOWN; implementation_source: UNKNOWN; source_version: UNKNOWN
- note: registered so the round's source count is honest; no candidate is built on it

## C-06 — pysystemtrade / Carver's diversified trend-following system

- sources: S2-14, S2-13
- kind / classification / evidence: EXTERNAL_STRATEGY · REJECT · E3
- rule completeness: 16/21 (defined 16 of 21)
- unknown material fields: market, assets, exit_target, exit_time, original_metrics
- evidence basis: a long-lived open-source implementation of a published system with decades of public discussion
- economic claim: the system targets a modest risk-adjusted return from diversified futures trend following, not a per-trade edge
- frequency: {'trades_per_day': 'UNKNOWN', 'holding_period': 'weeks', 'historical_trade_count': 'UNKNOWN', 'cadence': 'daily'}
- cost floor: NOT_COMPARABLE: the system's edge is a diversified risk premium measured over years, while this project's admission bar is a 23.791 bps round trip on spot crypto trades
- replication risk: {'DATA_DEPENDENCY': 'LOW', 'TIMESTAMP_AMBIGUITY': 'LOW', 'EXECUTION_AMBIGUITY': 'LOW', 'PARAMETER_AMBIGUITY': 'LOW', 'SURVIVORSHIP_RISK': 'LOW', 'LOOKAHEAD_RISK': 'LOW', 'OVERFIT_RISK': 'LOW', 'CAPACITY_RISK': 'HIGH', 'MARKET_DECAY_RISK': 'LOW'}
- gaps to P0: the instrument class is wrong for this runtime (futures, leverage, shorting); a spot-crypto long/cash version would be our own design, not this external strategy
- reason codes: INSTRUMENT_OR_UNIVERSE_MISMATCH, COST_FLOOR_HEADROOM_NOT_ESTABLISHED
- counter-evidence: reproducing it exactly requires a futures account, margin and 100 markets — none of which this project can trade; keeping only the trend component on BTC spot would be a new strategy, and the mission forbids relabelling our own design as an external replication
- material fields: market=UNKNOWN; assets=UNKNOWN; timeframe=DEFINED; data_source=DEFINED; data_fields=DEFINED; entry_long=DEFINED; entry_short=DEFINED; exit_stop=DEFINED; exit_target=UNKNOWN; exit_time=UNKNOWN; exit_signal=DEFINED; parameters=DEFINED; sizing_rule=DEFINED; execution_assumption=DEFINED; session_rules=DEFINED; warmup=DEFINED; transaction_costs=DEFINED; original_period=DEFINED; original_metrics=UNKNOWN; implementation_source=DEFINED; source_version=DEFINED
- field notes: market: for this project: the system trades leveraged futures across ~100 markets by default; assets: a configured futures instrument list; no crypto spot sleeve by default; timeframe: daily; data_source: user-supplied futures data (a free sample source is included with the engine); data_fields: daily OHLC plus the engine's derived volatility and forecast inputs; entry_long: in the engine: EWMAC/breakout/carry forecast combination above the configured threshold; entry_short: the system is symmetric and shorts futures; exit_stop: via position sizing and forecast scaling rather than a price stop; exit_target: no target is used; exit_time: not applicable; exit_signal: forecast decay/sign change; parameters: in the engine's configuration files and the book; sizing_rule: volatility targeting with forecast scaling and a fixed risk budget; execution_assumption: the engine models spreads, rolls and slippage; session_rules: daily rebalance, no session constraint; warmup: derived from the longest lookback; transaction_costs: the engine carries explicit cost assumptions; original_period: the book and blog cover multiple decades of futures data; original_metrics: at this read level (book results, not captured here); implementation_source: pysystemtrade (open source); source_version: the repository is versioned and pin-able
- note: excellent evidence, wrong runtime

## C-07 — Q24 Crypto Guide Strategy (Quantiacs) — SMA15/34 + RSI14 long-only crypto daily

- sources: S2-08, S2-07, S2-09, S2-41
- kind / classification / evidence: EXTERNAL_STRATEGY · REPLICATE_P1 · E2
- rule completeness: 15/21 (defined 15 of 21)
- unknown material fields: exit_stop, exit_target, execution_assumption, transaction_costs, original_metrics, source_version
- evidence basis: the example's source code read verbatim, with the contest's own backtester as the evaluation harness
- economic claim: the contest ranks on in-sample Sharpe above 1.0 and runs qualifying strategies in daily live paper trading; no per-strategy number is public
- frequency: {'trades_per_day': 'UNKNOWN; daily rebalance of a top-10 long-only book', 'holding_period': 'days to weeks (signal persistence)', 'historical_trade_count': 'UNKNOWN', 'cadence': 'daily'}
- cost floor: PLAUSIBLE_BUT_UNVERIFIED: a daily-rebalanced top-10 book with a slow SMA filter can keep turnover low enough to clear the 23.791 bps round trip, but the example states no cost model and no turnover, so nothing about net edge can be asserted from the source
- replication risk: {'DATA_DEPENDENCY': 'HIGH', 'TIMESTAMP_AMBIGUITY': 'LOW', 'EXECUTION_AMBIGUITY': 'MEDIUM', 'PARAMETER_AMBIGUITY': 'LOW', 'SURVIVORSHIP_RISK': 'MEDIUM', 'LOOKAHEAD_RISK': 'LOW', 'OVERFIT_RISK': 'MEDIUM', 'CAPACITY_RISK': 'LOW', 'MARKET_DECAY_RISK': 'MEDIUM'}
- gaps to P0: no stop and no target: the exit is only the signal flipping; no cost model is published, so the 23.791 bps floor cannot be applied from the source; the data source is platform-bound (contest rule: only Quantiacs data may be used); original metrics are not quoted in the page
- counter-evidence: the contest's own gate is in-sample Sharpe, which selects for overfitting and says nothing about costs; the page's benchmark download raised an HTTP 404 while being read, so even the benchmark call is currently broken; long-only by rule, so the strategy has no way to express a negative view; nothing about the example's realised live paper performance is public
- material fields: market=DEFINED; assets=DEFINED; timeframe=DEFINED; data_source=DEFINED; data_fields=DEFINED; entry_long=DEFINED; entry_short=UNSUPPORTED_BY_SOURCE; exit_stop=UNKNOWN; exit_target=UNKNOWN; exit_time=DEFINED; exit_signal=DEFINED; parameters=DEFINED; sizing_rule=DEFINED; execution_assumption=UNKNOWN; session_rules=DEFINED; warmup=DEFINED; transaction_costs=UNKNOWN; original_period=DEFINED; original_metrics=UNKNOWN; implementation_source=DEFINED; source_version=UNKNOWN
- field notes: market: crypto daily spot, long only (contest rule); assets: top-10 crypto by market capitalisation, recomputed monthly from coinmarketcap data, stablecoins excluded; the platform exposes it as the is_liquid field and hand-picking is forbidden; timeframe: daily; data_source: Quantiacs cryptodaily dataset (qnt.data.cryptodaily_load_data, min_date 2015-01-01) plus the is_liquid field; data_fields: close price and the liquidity flag; entry_long: weight 1 where SMA(close,15) > SMA(close,34) AND is_liquid AND (RSI(close,14) < 34 OR RSI(close,14) > 68); entry_short: the contest allows long positions only ('The strategy can open only long positions'); exit_stop: no stop is defined anywhere in the example; exit_target: no profit target is defined; exit_time: positions are re-evaluated every day; an asset that no longer satisfies the signal gets weight 0; exit_signal: the signal flipping to zero, i.e. either SMA condition or RSI condition failing; parameters: SMA 15/34, RSI 14 with thresholds 34 and 68, daily rebalance; sizing_rule: weight 1 on every qualifying liquid asset, normalised by the platform's cleaner (qnout.clean, competition_type='crypto_daily_long') into a long-only allocation; execution_assumption: no order type, fill or slippage assumption is stated; session_rules: daily bars, no session constraint; warmup: the longest lookback (SMA34/RSI14) plus the platform's multi-pass lookback_period=365; transaction_costs: the page states no cost assumption; the statistics function decides what is charged; original_period: in-sample from 2016-01-01 (earlier data may be used for testing/training); original_metrics: the page shows the statistics call but not its output; the contest requires an in-sample Sharpe above 1.0 for validity; implementation_source: the published example, cloneable in the platform (the code is in the page); source_version: the documentation page carries no version or commit; a replication must pin the retrieved content
- note: the highest rule-completeness of the round, from source code read verbatim; the missing pieces are exactly the ones this project insists on (costs and execution)

## C-08 — G-Research Crypto Forecasting (Kaggle 2022) — winning forecasting solutions

- sources: S2-28, S2-29, S2-30, S2-31, S2-32
- kind / classification / evidence: RESEARCH_TASK · REJECT · E3
- rule completeness: 9/21 (defined 9 of 21)
- unknown material fields: entry_long, entry_short, exit_stop, exit_target, exit_time, exit_signal, parameters, sizing_rule, execution_assumption, warmup, transaction_costs, source_version
- evidence basis: a public competition with a genuinely held-out evaluation and independent participants
- economic claim: a correlation metric, not an economic claim
- frequency: {'trades_per_day': 'n/a', 'holding_period': 'n/a', 'historical_trade_count': '0', 'cadence': 'minute'}
- cost floor: NOT_APPLICABLE: with no trading layer there is no turnover to charge against the 23.791 bps floor
- replication risk: {'DATA_DEPENDENCY': 'LOW', 'TIMESTAMP_AMBIGUITY': 'LOW', 'EXECUTION_AMBIGUITY': 'HIGH', 'PARAMETER_AMBIGUITY': 'MEDIUM', 'SURVIVORSHIP_RISK': 'LOW', 'LOOKAHEAD_RISK': 'LOW', 'OVERFIT_RISK': 'MEDIUM', 'CAPACITY_RISK': 'LOW', 'MARKET_DECAY_RISK': 'HIGH'}
- gaps to P0: there is no entry, exit, sizing or cost layer to reproduce
- reason codes: FORECAST_ONLY_NOT_A_STRATEGY, RULES_INCOMPLETE_MATERIAL_FIELDS, COST_FLOOR_HEADROOM_NOT_ESTABLISHED
- counter-evidence: strong evidence for a forecasting model, zero evidence for a tradable rule set; the winning solutions are trained models with per-competitor pipelines, so no single external strategy exists to replicate
- material fields: market=DEFINED; assets=DEFINED; timeframe=DEFINED; data_source=DEFINED; data_fields=DEFINED; entry_long=UNKNOWN; entry_short=UNKNOWN; exit_stop=UNKNOWN; exit_target=UNKNOWN; exit_time=UNKNOWN; exit_signal=UNKNOWN; parameters=UNKNOWN; sizing_rule=UNKNOWN; execution_assumption=UNKNOWN; session_rules=DEFINED; warmup=UNKNOWN; transaction_costs=UNKNOWN; original_period=DEFINED; original_metrics=DEFINED; implementation_source=DEFINED; source_version=UNKNOWN
- field notes: market: 14 crypto assets in the competition universe; assets: the 14 competition assets; timeframe: minute bars with a short-horizon return target; data_source: the public Kaggle competition dataset; data_fields: OHLCV plus engineered features in the solutions; entry_long: the competition scores correlation, not trades; no trading rule exists; entry_short: no trading rule exists; exit_stop: UNKNOWN; exit_target: UNKNOWN; exit_time: UNKNOWN; exit_signal: UNKNOWN; parameters: solutions were trained; notebooks are public but are search artefacts, not fixed rule sets; sizing_rule: UNKNOWN; execution_assumption: there is no trading simulation; session_rules: none (minute bars, 24/7); warmup: UNKNOWN; transaction_costs: no trading, therefore no costs; original_period: the 2022 competition train/validation windows; original_metrics: the scoring metric is a correlation on a held-out period; no PnL is reported; implementation_source: public winner notebooks and repositories; source_version: many derived forks; no canonical version
- note: recorded because it is the most credible independently-evaluated crypto result found this round, and it still is not a strategy

## C-09 — bitcoin-momentum-trading — 5-minute ML momentum direction model

- sources: S2-34
- kind / classification / evidence: EXTERNAL_STRATEGY · REJECT · E1
- rule completeness: 5/21 (defined 5 of 21)
- unknown material fields: market, data_fields, entry_long, entry_short, exit_stop, exit_target, exit_time, exit_signal, parameters, sizing_rule, execution_assumption, warmup, transaction_costs, original_period, original_metrics, source_version
- evidence basis: listing-level read of a repository that claims a 5-minute directional model
- economic claim: none measurable was read
- frequency: {'trades_per_day': 'potentially many', 'holding_period': 'minutes', 'historical_trade_count': 'UNKNOWN', 'cadence': '5m'}
- cost floor: NOT_ESTABLISHED: a 5-minute horizon must clear the 23.791 bps round trip on every round turn, and the source reports no per-trade magnitude
- replication risk: {'DATA_DEPENDENCY': 'LOW', 'TIMESTAMP_AMBIGUITY': 'LOW', 'EXECUTION_AMBIGUITY': 'HIGH', 'PARAMETER_AMBIGUITY': 'HIGH', 'SURVIVORSHIP_RISK': 'LOW', 'LOOKAHEAD_RISK': 'HIGH', 'OVERFIT_RISK': 'HIGH', 'CAPACITY_RISK': 'LOW', 'MARKET_DECAY_RISK': 'HIGH'}
- gaps to P0: read the repository, the feature set and any published test; no cost model; retraining rather than fixed parameters
- reason codes: COST_FLOOR_HEADROOM_NOT_ESTABLISHED, SOURCE_READ_LEVEL_INSUFFICIENT, NO_FIXED_PARAMETERS_RETRAINING_REQUIRED
- counter-evidence: 5-minute crypto horizons are the regime the project's admission cost already killed internally; the model is retrained, so the 'same strategy' cannot be evaluated twice
- material fields: market=UNKNOWN; assets=DEFINED; timeframe=DEFINED; data_source=DEFINED; data_fields=UNKNOWN; entry_long=UNKNOWN; entry_short=UNKNOWN; exit_stop=UNKNOWN; exit_target=UNKNOWN; exit_time=UNKNOWN; exit_signal=UNKNOWN; parameters=UNKNOWN; sizing_rule=UNKNOWN; execution_assumption=UNKNOWN; session_rules=DEFINED; warmup=UNKNOWN; transaction_costs=UNKNOWN; original_period=UNKNOWN; original_metrics=UNKNOWN; implementation_source=DEFINED; source_version=UNKNOWN
- field notes: market: read at listing level; the repository frames it as BTC 5-minute momentum; assets: BTC; timeframe: 5-minute bars; data_source: exchange OHLCV; data_fields: the feature set was not read; entry_long: model-driven, not stated at this read level; entry_short: UNKNOWN; exit_stop: UNKNOWN; exit_target: UNKNOWN; exit_time: UNKNOWN; exit_signal: UNKNOWN; parameters: the model is trained, so the 'parameters' are weights rather than a frozen rule set; sizing_rule: UNKNOWN; execution_assumption: UNKNOWN; session_rules: none (24/7); warmup: UNKNOWN; transaction_costs: UNKNOWN; original_period: UNKNOWN; original_metrics: UNKNOWN; implementation_source: the repository; source_version: UNKNOWN
- note: rejected on cadence economics and on the absence of a fixed rule set

## C-10 — Adaptive Regime-Based Trading on Bitcoin (15-minute, walk-forward)

- sources: S2-35
- kind / classification / evidence: RESEARCH_HYPOTHESIS · INSUFFICIENT_EVIDENCE · E1
- rule completeness: 4/21 (defined 4 of 21)
- unknown material fields: market, data_source, data_fields, entry_long, entry_short, exit_stop, exit_target, exit_time, exit_signal, parameters, sizing_rule, execution_assumption, warmup, transaction_costs, original_metrics, implementation_source, source_version
- evidence basis: the abstract of a preprint record only
- economic claim: 'consistent profitability' under walk-forward evaluation, unquantified at this read level
- frequency: {'trades_per_day': 'UNKNOWN', 'holding_period': 'UNKNOWN', 'historical_trade_count': 'UNKNOWN', 'cadence': '15m'}
- cost floor: NOT_ESTABLISHED and doubtful: 15-minute trading on spot crypto faces the 23.791 bps round trip repeatedly
- replication risk: {'DATA_DEPENDENCY': 'MEDIUM', 'TIMESTAMP_AMBIGUITY': 'MEDIUM', 'EXECUTION_AMBIGUITY': 'HIGH', 'PARAMETER_AMBIGUITY': 'HIGH', 'SURVIVORSHIP_RISK': 'LOW', 'LOOKAHEAD_RISK': 'MEDIUM', 'OVERFIT_RISK': 'MEDIUM', 'CAPACITY_RISK': 'LOW', 'MARKET_DECAY_RISK': 'HIGH'}
- gaps to P0: obtain the full text and read the actual rules; no code; establish cost treatment
- reason codes: SOURCE_READ_LEVEL_INSUFFICIENT, NO_CODE, COST_FLOOR_HEADROOM_NOT_ESTABLISHED
- counter-evidence: a 15-minute cadence is structurally at odds with this project's measured cost floor; the claim could not be inspected beyond the abstract
- material fields: market=UNKNOWN; assets=DEFINED; timeframe=DEFINED; data_source=UNKNOWN; data_fields=UNKNOWN; entry_long=UNKNOWN; entry_short=UNKNOWN; exit_stop=UNKNOWN; exit_target=UNKNOWN; exit_time=UNKNOWN; exit_signal=UNKNOWN; parameters=UNKNOWN; sizing_rule=UNKNOWN; execution_assumption=UNKNOWN; session_rules=DEFINED; warmup=UNKNOWN; transaction_costs=UNKNOWN; original_period=DEFINED; original_metrics=UNKNOWN; implementation_source=UNKNOWN; source_version=UNKNOWN
- field notes: market: the record describes 15-minute Bitcoin data only; assets: BTC; timeframe: 15-minute bars; data_source: UNKNOWN; data_fields: UNKNOWN; entry_long: the rules were not readable; entry_short: UNKNOWN; exit_stop: UNKNOWN; exit_target: UNKNOWN; exit_time: UNKNOWN; exit_signal: UNKNOWN; parameters: UNKNOWN; sizing_rule: UNKNOWN; execution_assumption: UNKNOWN; session_rules: none (24/7); warmup: UNKNOWN; transaction_costs: UNKNOWN; original_period: January 2021 to August 2025 (per the record's abstract); original_metrics: the abstract claims consistent profitability without numbers at this read level; implementation_source: UNKNOWN; source_version: UNKNOWN
- note: registered for completeness; the next round would have to read the paper before any judgement

## C-11 — Reflective LLM-based agent for zero-shot cryptocurrency trading

- sources: S2-19
- kind / classification / evidence: RESEARCH_HYPOTHESIS · REJECT · E1
- rule completeness: 1/21 (defined 1 of 21)
- unknown material fields: market, assets, timeframe, data_source, data_fields, entry_long, entry_short, exit_stop, exit_target, exit_time, exit_signal, parameters, sizing_rule, execution_assumption, warmup, transaction_costs, original_period, original_metrics, implementation_source, source_version
- evidence basis: abstract-level read of a preprint
- economic claim: none measurable was read
- frequency: {'trades_per_day': 'UNKNOWN', 'holding_period': 'UNKNOWN', 'historical_trade_count': 'UNKNOWN', 'cadence': 'UNKNOWN'}
- cost floor: NOT_ASSESSED: no magnitude was read
- replication risk: {'DATA_DEPENDENCY': 'MEDIUM', 'TIMESTAMP_AMBIGUITY': 'MEDIUM', 'EXECUTION_AMBIGUITY': 'HIGH', 'PARAMETER_AMBIGUITY': 'HIGH', 'SURVIVORSHIP_RISK': 'LOW', 'LOOKAHEAD_RISK': 'MEDIUM', 'OVERFIT_RISK': 'HIGH', 'CAPACITY_RISK': 'LOW', 'MARKET_DECAY_RISK': 'HIGH'}
- gaps to P0: rules, sizing and costs are unspecified
- reason codes: REPRODUCIBILITY_LLM_OR_HARDWARE, RULES_INCOMPLETE_MATERIAL_FIELDS
- counter-evidence: an LLM-dependent system cannot be re-run identically: the model version and prompt are part of the strategy and are not frozen artifacts
- material fields: market=UNKNOWN; assets=UNKNOWN; timeframe=UNKNOWN; data_source=UNKNOWN; data_fields=UNKNOWN; entry_long=UNKNOWN; entry_short=UNKNOWN; exit_stop=UNKNOWN; exit_target=UNKNOWN; exit_time=UNKNOWN; exit_signal=UNKNOWN; parameters=UNKNOWN; sizing_rule=UNKNOWN; execution_assumption=UNKNOWN; session_rules=DEFINED; warmup=UNKNOWN; transaction_costs=UNKNOWN; original_period=UNKNOWN; original_metrics=UNKNOWN; implementation_source=UNKNOWN; source_version=UNKNOWN
- field notes: market: UNKNOWN; assets: multiple coins; timeframe: UNKNOWN; data_source: UNKNOWN; data_fields: UNKNOWN; entry_long: UNKNOWN; entry_short: UNKNOWN; exit_stop: UNKNOWN; exit_target: UNKNOWN; exit_time: UNKNOWN; exit_signal: UNKNOWN; parameters: the 'parameters' are a prompt and a proprietary model version; sizing_rule: UNKNOWN; execution_assumption: UNKNOWN; session_rules: none (24/7); warmup: UNKNOWN; transaction_costs: UNKNOWN; original_period: UNKNOWN; original_metrics: UNKNOWN; implementation_source: UNKNOWN; source_version: UNKNOWN
- note: recorded so the LLM-agent family is represented rather than silently ignored

## C-12 — CGA-Agent — genetic-algorithm optimisation of crypto strategy parameters

- sources: S2-17
- kind / classification / evidence: EXTERNAL_STRATEGY · REJECT · E1
- rule completeness: 4/21 (defined 4 of 21)
- unknown material fields: timeframe, data_source, data_fields, entry_long, entry_short, exit_stop, exit_target, exit_time, exit_signal, parameters, sizing_rule, execution_assumption, warmup, transaction_costs, original_period, implementation_source, source_version
- evidence basis: the preprint read in full at the abstract/introduction level
- economic claim: total-return improvements of 29%/550%/169% versus baselines, with no cost model read
- frequency: {'trades_per_day': 'UNKNOWN', 'holding_period': 'UNKNOWN', 'historical_trade_count': 'UNKNOWN', 'cadence': 'UNKNOWN'}
- cost floor: NOT_ESTABLISHED: no turnover and no cost treatment were read, so the 23.791 bps floor cannot be applied
- replication risk: {'DATA_DEPENDENCY': 'MEDIUM', 'TIMESTAMP_AMBIGUITY': 'MEDIUM', 'EXECUTION_AMBIGUITY': 'HIGH', 'PARAMETER_AMBIGUITY': 'HIGH', 'SURVIVORSHIP_RISK': 'LOW', 'LOOKAHEAD_RISK': 'HIGH', 'OVERFIT_RISK': 'HIGH', 'CAPACITY_RISK': 'LOW', 'MARKET_DECAY_RISK': 'HIGH'}
- gaps to P0: the artefact is a search procedure, so there is no frozen external rule set to replicate
- reason codes: OVERFIT_RISK_PARAMETER_SEARCH, NO_FIXED_PARAMETERS_RETRAINING_REQUIRED, NO_CODE, COST_FLOOR_HEADROOM_NOT_ESTABLISHED
- counter-evidence: an optimiser that adapts parameters to recent data guarantees look-ahead risk in any replication that reuses its fitted values; returns of +550% on one asset over an unspecified window are not comparable with anything this project measures
- material fields: market=DEFINED; assets=DEFINED; timeframe=UNKNOWN; data_source=UNKNOWN; data_fields=UNKNOWN; entry_long=UNKNOWN; entry_short=UNKNOWN; exit_stop=UNKNOWN; exit_target=UNKNOWN; exit_time=UNKNOWN; exit_signal=UNKNOWN; parameters=UNKNOWN; sizing_rule=UNKNOWN; execution_assumption=UNKNOWN; session_rules=DEFINED; warmup=UNKNOWN; transaction_costs=UNKNOWN; original_period=UNKNOWN; original_metrics=DEFINED; implementation_source=UNKNOWN; source_version=UNKNOWN
- field notes: market: crypto (BTC, ETH, BNB); assets: BTC, ETH, BNB; timeframe: UNKNOWN; data_source: UNKNOWN; data_fields: UNKNOWN; entry_long: the entry rules are the optimiser's output, not a fixed condition; entry_short: UNKNOWN; exit_stop: UNKNOWN; exit_target: UNKNOWN; exit_time: UNKNOWN; exit_signal: UNKNOWN; parameters: by construction: the paper's contribution is a search over parameters; sizing_rule: UNKNOWN; execution_assumption: UNKNOWN; session_rules: none (24/7); warmup: UNKNOWN; transaction_costs: UNKNOWN; original_period: UNKNOWN; original_metrics: author-reported total-return improvements of 29%, 550% and 169% across BTC, ETH and BNB versus baselines; implementation_source: no code was found; source_version: UNKNOWN
- note: parameter search, therefore outside the mission's definition of a strategy

## C-13 — Daily ML direction trading on Bitcoin with a real unseen-period test (Crone, Brophy, Ward)

- sources: S2-16
- kind / classification / evidence: EXTERNAL_STRATEGY · RESEARCH_HYPOTHESIS · E2
- rule completeness: 11/21 (defined 11 of 21)
- unknown material fields: data_fields, exit_stop, exit_target, parameters, sizing_rule, execution_assumption, warmup, transaction_costs, implementation_source, source_version
- evidence basis: the paper read in full: an explicit unseen-period trading test
- economic claim: +86% over Q1-2021 (equal to buy-and-hold) and +12.5% better than buy-and-hold after adding a confidence-based risk rule
- frequency: {'trades_per_day': '<=1', 'holding_period': '1 day (re-decided daily)', 'historical_trade_count': 'UNKNOWN', 'cadence': 'daily'}
- cost floor: NOT_ESTABLISHED: a daily long/cash rule clears the 23.791 bps floor per round turn in principle, but the paper models no fees at all and reports only a 3-month window
- replication risk: {'DATA_DEPENDENCY': 'MEDIUM', 'TIMESTAMP_AMBIGUITY': 'LOW', 'EXECUTION_AMBIGUITY': 'MEDIUM', 'PARAMETER_AMBIGUITY': 'HIGH', 'SURVIVORSHIP_RISK': 'LOW', 'LOOKAHEAD_RISK': 'HIGH', 'OVERFIT_RISK': 'HIGH', 'CAPACITY_RISK': 'LOW', 'MARKET_DECAY_RISK': 'HIGH'}
- gaps to P0: the classifier must be retrained, so no frozen parameter set exists; no cost model; a single three-month test window; the paper's own code is unavailable
- reason codes: NO_FIXED_PARAMETERS_RETRAINING_REQUIRED, RULES_INCOMPLETE_MATERIAL_FIELDS, COST_FLOOR_HEADROOM_NOT_ESTABLISHED, SAMPLE_TOO_SHORT
- counter-evidence: the same paper documents that a widely cited benchmark in this literature trained on its own test data and mis-applied PCA — a reminder that this literature's reported numbers need auditing; a three-month test window cannot separate skill from a lucky regime
- material fields: market=DEFINED; assets=DEFINED; timeframe=DEFINED; data_source=DEFINED; data_fields=UNKNOWN; entry_long=DEFINED; entry_short=UNSUPPORTED_BY_SOURCE; exit_stop=UNKNOWN; exit_target=UNKNOWN; exit_time=DEFINED; exit_signal=DEFINED; parameters=UNKNOWN; sizing_rule=UNKNOWN; execution_assumption=UNKNOWN; session_rules=DEFINED; warmup=UNKNOWN; transaction_costs=UNKNOWN; original_period=DEFINED; original_metrics=DEFINED; implementation_source=UNKNOWN; source_version=UNKNOWN
- field notes: market: BTC daily spot, long/cash; assets: BTC; timeframe: daily; data_source: on-chain network features plus external market features (paper); data_fields: the full feature list was not captured at this read level; entry_long: go long when the next-day direction classifier predicts up (a binary long/cash rule); entry_short: the trading rule is long/cash; exit_stop: no stop is stated; exit_target: no target is stated; exit_time: the position is re-decided every day; exit_signal: the prediction or the risk-tolerance score turning; parameters: the models are trained; hyper-parameters are not frozen in the paper; sizing_rule: a risk-tolerance score scales exposure, but the exact mapping was not read; execution_assumption: UNKNOWN; session_rules: none (24/7); warmup: UNKNOWN; transaction_costs: no fee or slippage model is mentioned; original_period: training periods up to 2019-2020 and an unseen test in Q1-2021; original_metrics: about +86% over the three-month test (matching buy-and-hold) and +12.5% relative with the confidence-based rule; implementation_source: the paper's own code was not published; a benchmark's code is on GitHub; source_version: UNKNOWN
- note: valuable both as a candidate and as counter-evidence about the quality of published crypto backtests

## C-14 — Karaptic Research — published-strategy replication series net of fees and slippage

- sources: S2-27
- kind / classification / evidence: RESEARCH_TASK · WATCH · E3
- rule completeness: 5/21 (defined 5 of 21)
- unknown material fields: market, assets, timeframe, entry_long, entry_short, exit_stop, exit_target, exit_time, exit_signal, parameters, sizing_rule, execution_assumption, warmup, original_period, implementation_source, source_version
- evidence basis: an independent replication venue that reports its own net-of-cost results and its own honest-timestamp correction
- economic claim: win rates of 85-100% before a timing correction and 63% after it, net of costs as described by the site
- frequency: {'trades_per_day': 'UNKNOWN', 'holding_period': 'UNKNOWN', 'historical_trade_count': 'UNKNOWN', 'cadence': 'event-driven'}
- cost floor: NOT_COMPARABLE_YET: the site's own cost assumptions are not the project's 23.791 bps floor, and no position-level data was read
- replication risk: {'DATA_DEPENDENCY': 'MEDIUM', 'TIMESTAMP_AMBIGUITY': 'MEDIUM', 'EXECUTION_AMBIGUITY': 'HIGH', 'PARAMETER_AMBIGUITY': 'HIGH', 'SURVIVORSHIP_RISK': 'MEDIUM', 'LOOKAHEAD_RISK': 'MEDIUM', 'OVERFIT_RISK': 'HIGH', 'CAPACITY_RISK': 'LOW', 'MARKET_DECAY_RISK': 'HIGH'}
- gaps to P0: read the notes themselves and their per-strategy rule sets; separate the venue's own system (Klines) from the strategies it replicates
- reason codes: SOURCE_READ_LEVEL_INSUFFICIENT, NO_CODE, RULES_INCOMPLETE_MATERIAL_FIELDS
- counter-evidence: the site's own honest-timestamp re-run cut the headline win rate from 85-100% to 63%, which is precisely the kind of correction this project's methodology demands; it is a venue for replications rather than an external strategy: the notes describe the author's own detector as well
- material fields: market=UNKNOWN; assets=UNKNOWN; timeframe=UNKNOWN; data_source=DEFINED; data_fields=DEFINED; entry_long=UNKNOWN; entry_short=UNKNOWN; exit_stop=UNKNOWN; exit_target=UNKNOWN; exit_time=UNKNOWN; exit_signal=UNKNOWN; parameters=UNKNOWN; sizing_rule=UNKNOWN; execution_assumption=UNKNOWN; session_rules=DEFINED; warmup=UNKNOWN; transaction_costs=DEFINED; original_period=UNKNOWN; original_metrics=DEFINED; implementation_source=UNKNOWN; source_version=UNKNOWN
- field notes: market: (Binance spot per the site description); assets: UNKNOWN; timeframe: UNKNOWN; data_source: Binance klines (the site's stated input); data_fields: klines plus the note's volume-spike detector; entry_long: only the summary was read; entry_short: UNKNOWN; exit_stop: the summary mentions triple-barrier and maximum-adverse-excursion exits in the literature review; exit_target: UNKNOWN; exit_time: UNKNOWN; exit_signal: UNKNOWN; parameters: UNKNOWN; sizing_rule: UNKNOWN; execution_assumption: UNKNOWN; session_rules: none (24/7); warmup: UNKNOWN; transaction_costs: the series states it evaluates net of fees, slippage and execution costs; original_period: eleven weekly walk-forward cohorts are mentioned; original_metrics: win rates of 85% (core tier) and 100% (narrow tier) on the pre-patch walk-forward sample, and 63% once detection timestamps were made honest; implementation_source: no code; source_version: UNKNOWN
- note: promoted to WATCH as the best candidate venue for round 3: an independent, net-of-cost replication source

## C-15 — Multi-Band Comparison Strategy (CRYPTO) — published Pine Script strategy

- sources: S2-37
- kind / classification / evidence: EXTERNAL_STRATEGY · INSUFFICIENT_EVIDENCE · E1
- rule completeness: 5/21 (defined 5 of 21)
- unknown material fields: assets, timeframe, entry_long, entry_short, exit_stop, exit_target, exit_time, exit_signal, parameters, sizing_rule, execution_assumption, warmup, transaction_costs, original_period, original_metrics, source_version
- evidence basis: listing-level read of a published script page
- economic claim: none read
- frequency: {'trades_per_day': 'UNKNOWN', 'holding_period': 'UNKNOWN', 'historical_trade_count': 'UNKNOWN', 'cadence': 'chart'}
- cost floor: NOT_ASSESSED: neither the rules nor the tester settings were read
- replication risk: {'DATA_DEPENDENCY': 'LOW', 'TIMESTAMP_AMBIGUITY': 'MEDIUM', 'EXECUTION_AMBIGUITY': 'HIGH', 'PARAMETER_AMBIGUITY': 'HIGH', 'SURVIVORSHIP_RISK': 'LOW', 'LOOKAHEAD_RISK': 'MEDIUM', 'OVERFIT_RISK': 'HIGH', 'CAPACITY_RISK': 'LOW', 'MARKET_DECAY_RISK': 'HIGH'}
- gaps to P0: read the Pine source and the published strategy-tester report, including commission settings; pin a symbol and a timeframe (the source leaves both to the user)
- reason codes: SOURCE_READ_LEVEL_INSUFFICIENT, NO_CANONICAL_PERIOD_OR_RESULTS, COST_FLOOR_HEADROOM_NOT_ESTABLISHED
- counter-evidence: TradingView strategies are commonly tuned to one symbol and period, and the tester's default cost settings are optimistic relative to this project's 23.791 bps floor
- material fields: market=DEFINED; assets=UNKNOWN; timeframe=UNKNOWN; data_source=DEFINED; data_fields=DEFINED; entry_long=UNKNOWN; entry_short=UNKNOWN; exit_stop=UNKNOWN; exit_target=UNKNOWN; exit_time=UNKNOWN; exit_signal=UNKNOWN; parameters=UNKNOWN; sizing_rule=UNKNOWN; execution_assumption=UNKNOWN; session_rules=DEFINED; warmup=UNKNOWN; transaction_costs=UNKNOWN; original_period=UNKNOWN; original_metrics=UNKNOWN; implementation_source=DEFINED; source_version=UNKNOWN
- field notes: market: crypto; assets: the script runs on whatever symbol the user charts; timeframe: the chart timeframe is the user's choice; data_source: TradingView chart data; data_fields: OHLC bars; entry_long: the code was not read at this level; entry_short: UNKNOWN; exit_stop: UNKNOWN; exit_target: UNKNOWN; exit_time: UNKNOWN; exit_signal: UNKNOWN; parameters: strategy properties were not read; sizing_rule: UNKNOWN; execution_assumption: UNKNOWN; session_rules: none (24/7); warmup: UNKNOWN; transaction_costs: the tester's commission and slippage settings were not read; original_period: UNKNOWN; original_metrics: UNKNOWN; implementation_source: the published script; source_version: UNKNOWN
- note: recorded because published Pine strategies are the largest single population of 'complete but unfrozen' crypto rules

## C-16 — Deep Momentum Networks (Lim/Zohren/Roberts and successors)

- sources: S2-22, S2-23
- kind / classification / evidence: EXTERNAL_STRATEGY · REJECT · E1
- rule completeness: 3/21 (defined 3 of 21)
- unknown material fields: market, assets, data_source, data_fields, entry_long, entry_short, exit_stop, exit_target, exit_time, exit_signal, parameters, execution_assumption, warmup, transaction_costs, original_period, original_metrics, implementation_source, source_version
- evidence basis: listing-level reads of a thesis and a peer-reviewed follow-up
- economic claim: the literature reports DMNs improving on standard time-series momentum; no number was captured here
- frequency: {'trades_per_day': '<=1', 'holding_period': 'days', 'historical_trade_count': 'UNKNOWN', 'cadence': 'daily'}
- cost floor: NOT_ASSESSED: the cost treatment was not read
- replication risk: {'DATA_DEPENDENCY': 'MEDIUM', 'TIMESTAMP_AMBIGUITY': 'MEDIUM', 'EXECUTION_AMBIGUITY': 'HIGH', 'PARAMETER_AMBIGUITY': 'HIGH', 'SURVIVORSHIP_RISK': 'LOW', 'LOOKAHEAD_RISK': 'HIGH', 'OVERFIT_RISK': 'HIGH', 'CAPACITY_RISK': 'MEDIUM', 'MARKET_DECAY_RISK': 'HIGH'}
- gaps to P0: locate a repository and a frozen training protocol; the reference universe is futures/ETFs, not spot crypto
- reason codes: NO_FIXED_PARAMETERS_RETRAINING_REQUIRED, NO_CODE, INSTRUMENT_OR_UNIVERSE_MISMATCH, SOURCE_READ_LEVEL_INSUFFICIENT
- counter-evidence: a trained network is a pipeline, not a rule set: two runs are not the same strategy
- material fields: market=UNKNOWN; assets=UNKNOWN; timeframe=DEFINED; data_source=UNKNOWN; data_fields=UNKNOWN; entry_long=UNKNOWN; entry_short=UNKNOWN; exit_stop=UNKNOWN; exit_target=UNKNOWN; exit_time=UNKNOWN; exit_signal=UNKNOWN; parameters=UNKNOWN; sizing_rule=DEFINED; execution_assumption=UNKNOWN; session_rules=DEFINED; warmup=UNKNOWN; transaction_costs=UNKNOWN; original_period=UNKNOWN; original_metrics=UNKNOWN; implementation_source=UNKNOWN; source_version=UNKNOWN
- field notes: market: futures and ETF universes in the reference work; assets: multi-asset; timeframe: daily; data_source: UNKNOWN; data_fields: UNKNOWN; entry_long: the trading rule is the neural network output; entry_short: UNKNOWN; exit_stop: UNKNOWN; exit_target: UNKNOWN; exit_time: UNKNOWN; exit_signal: UNKNOWN; parameters: the model is trained, so there is no frozen parameter file; sizing_rule: volatility scaling: positions are scaled to a target volatility, which is the framework's stated core; execution_assumption: UNKNOWN; session_rules: none; warmup: UNKNOWN; transaction_costs: at this read level; original_period: UNKNOWN; original_metrics: at this read level; implementation_source: no implementation was located in this round; source_version: UNKNOWN
- note: rejected on reproducibility rather than on quality

## C-17 — An Adaptive Multi-Agent Bitcoin Trading System (LLM-driven)

- sources: S2-18
- kind / classification / evidence: RESEARCH_HYPOTHESIS · REJECT · E0
- rule completeness: 1/21 (defined 1 of 21)
- unknown material fields: market, assets, timeframe, data_source, data_fields, entry_long, entry_short, exit_stop, exit_target, exit_time, exit_signal, parameters, sizing_rule, execution_assumption, warmup, transaction_costs, original_period, original_metrics, implementation_source, source_version
- evidence basis: abstract-level read of a preprint
- economic claim: none verifiable was read
- frequency: {'trades_per_day': 'UNKNOWN', 'holding_period': 'UNKNOWN', 'historical_trade_count': 'UNKNOWN', 'cadence': 'UNKNOWN'}
- cost floor: NOT_ASSESSED
- replication risk: {'DATA_DEPENDENCY': 'MEDIUM', 'TIMESTAMP_AMBIGUITY': 'MEDIUM', 'EXECUTION_AMBIGUITY': 'HIGH', 'PARAMETER_AMBIGUITY': 'HIGH', 'SURVIVORSHIP_RISK': 'LOW', 'LOOKAHEAD_RISK': 'HIGH', 'OVERFIT_RISK': 'HIGH', 'CAPACITY_RISK': 'LOW', 'MARKET_DECAY_RISK': 'HIGH'}
- gaps to P0: nothing beyond the abstract was readable
- reason codes: REPRODUCIBILITY_LLM_OR_HARDWARE, RULES_INCOMPLETE_MATERIAL_FIELDS, SOURCE_READ_LEVEL_INSUFFICIENT
- counter-evidence: the system's decision layer is a proprietary model, so its behaviour cannot be frozen or audited
- material fields: market=UNKNOWN; assets=UNKNOWN; timeframe=UNKNOWN; data_source=UNKNOWN; data_fields=UNKNOWN; entry_long=UNKNOWN; entry_short=UNKNOWN; exit_stop=UNKNOWN; exit_target=UNKNOWN; exit_time=UNKNOWN; exit_signal=UNKNOWN; parameters=UNKNOWN; sizing_rule=UNKNOWN; execution_assumption=UNKNOWN; session_rules=DEFINED; warmup=UNKNOWN; transaction_costs=UNKNOWN; original_period=UNKNOWN; original_metrics=UNKNOWN; implementation_source=UNKNOWN; source_version=UNKNOWN
- field notes: market: UNKNOWN; assets: BTC; timeframe: UNKNOWN; data_source: UNKNOWN; data_fields: UNKNOWN; entry_long: UNKNOWN; entry_short: UNKNOWN; exit_stop: UNKNOWN; exit_target: UNKNOWN; exit_time: UNKNOWN; exit_signal: UNKNOWN; parameters: prompts and model versions; sizing_rule: UNKNOWN; execution_assumption: UNKNOWN; session_rules: none (24/7); warmup: UNKNOWN; transaction_costs: UNKNOWN; original_period: UNKNOWN; original_metrics: UNKNOWN; implementation_source: UNKNOWN; source_version: UNKNOWN
- note: rejected as non-reproducible

## C-18 — Momentum Trading in Cryptocurrencies: time-series vs cross-sectional (comparative study)

- sources: S2-36, S2-20, S2-21
- kind / classification / evidence: RESEARCH_HYPOTHESIS · INSUFFICIENT_EVIDENCE · E1
- rule completeness: 1/21 (defined 1 of 21)
- unknown material fields: market, assets, timeframe, data_source, data_fields, entry_long, entry_short, exit_stop, exit_target, exit_time, exit_signal, parameters, sizing_rule, execution_assumption, warmup, transaction_costs, original_period, original_metrics, implementation_source, source_version
- evidence basis: abstract-level reads of three momentum papers, one of which points to the high-frequency cost problem
- economic claim: crypto momentum is reported as profitable in the literature, but the cross-sectional variants require shorting and the high-frequency variant (S2-21) sits in the cost regime this project has already rejected internally
- frequency: {'trades_per_day': 'UNKNOWN', 'holding_period': 'UNKNOWN', 'historical_trade_count': 'UNKNOWN', 'cadence': 'UNKNOWN'}
- cost floor: DOUBTFUL: the high-frequency variant's horizon is the one the project's 23.791 bps floor already killed, and the cross-sectional variants need shorting
- replication risk: {'DATA_DEPENDENCY': 'MEDIUM', 'TIMESTAMP_AMBIGUITY': 'MEDIUM', 'EXECUTION_AMBIGUITY': 'HIGH', 'PARAMETER_AMBIGUITY': 'HIGH', 'SURVIVORSHIP_RISK': 'MEDIUM', 'LOOKAHEAD_RISK': 'MEDIUM', 'OVERFIT_RISK': 'HIGH', 'CAPACITY_RISK': 'LOW', 'MARKET_DECAY_RISK': 'HIGH'}
- gaps to P0: read the papers, then decide whether a long/cash restatement is faithful or an invention
- reason codes: SOURCE_READ_LEVEL_INSUFFICIENT, NO_CODE, INSTRUMENT_OR_UNIVERSE_MISMATCH
- counter-evidence: long/short cross-sectional momentum cannot be expressed in a long/cash spot runtime without inventing a long-only variant
- material fields: market=UNKNOWN; assets=UNKNOWN; timeframe=UNKNOWN; data_source=UNKNOWN; data_fields=UNKNOWN; entry_long=UNKNOWN; entry_short=UNKNOWN; exit_stop=UNKNOWN; exit_target=UNKNOWN; exit_time=UNKNOWN; exit_signal=UNKNOWN; parameters=UNKNOWN; sizing_rule=UNKNOWN; execution_assumption=UNKNOWN; session_rules=DEFINED; warmup=UNKNOWN; transaction_costs=UNKNOWN; original_period=UNKNOWN; original_metrics=UNKNOWN; implementation_source=UNKNOWN; source_version=UNKNOWN
- field notes: market: UNKNOWN; assets: multi-coin; timeframe: UNKNOWN; data_source: UNKNOWN; data_fields: UNKNOWN; entry_long: read at abstract level; entry_short: UNKNOWN; exit_stop: UNKNOWN; exit_target: UNKNOWN; exit_time: UNKNOWN; exit_signal: UNKNOWN; parameters: (a multi-horizon EMA design is mentioned, without values); sizing_rule: UNKNOWN; execution_assumption: UNKNOWN; session_rules: none (24/7); warmup: UNKNOWN; transaction_costs: UNKNOWN; original_period: UNKNOWN; original_metrics: UNKNOWN; implementation_source: UNKNOWN; source_version: UNKNOWN
- note: grouped registration of the momentum literature reviewed this round
