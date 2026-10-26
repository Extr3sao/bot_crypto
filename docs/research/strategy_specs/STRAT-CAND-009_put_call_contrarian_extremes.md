# STRAT-CAND-009

## Source
SRC-BOOK-001 — *Trading Room: La especulación inteligente*, printed pp. 39-40.

## Source Claim
Extreme put/call positioning may have contrarian predictive value; source suggests >1.1 bullish and <0.7 bearish sentiment.

## Project Interpretation
This is a research candidate only. Explicit source rules are preserved; missing rules are marked `UNSPECIFIED_BY_SOURCE`. Any later alternatives must be labeled `PROJECT_DERIVED_VARIANT`.

## Market Hypothesis
Extreme put/call positioning may have contrarian predictive value; source suggests >1.1 bullish and <0.7 bearish sentiment.

## Economic / Behavioral Mechanism
Source proposes repeatable price/positioning behavior; mechanism is not independently validated by this book.

## Assets
Source references S&P 500 / CBOE put-call activity

## Timeframes
Source context appears daily/aggregate; exact timing UNSPECIFIED

## Required Data
point-in-time put/call series + target market returns + publication timestamps

## Features
put/call ratio; rolling distribution/quantiles as project-derived variants

## Long Entry
Source rule arm: ratio > 1.1 -> bullish stance/signal; actual entry/exit is UNSPECIFIED_BY_SOURCE.

## Short Entry
Source rule arm: ratio < 0.7 -> bearish stance/signal; entry/exit UNSPECIFIED_BY_SOURCE.

## Exit
UNSPECIFIED_BY_SOURCE

## Stop
UNSPECIFIED_BY_SOURCE

## Take Profit
UNSPECIFIED_BY_SOURCE

## Invalidation
Signal extreme decays / opposite extreme; project-derived only

## Regime Applicability
Sentiment-extreme hypothesis; regime dependence unknown

## Expected Mechanism
Same as Market Hypothesis; must be validated against an explicit baseline.

## Holding Period
UNSPECIFIED_BY_SOURCE

## Cost Sensitivity
Low signal frequency; options-data latency/licensing important

## PIT Requirements
All features and higher-timeframe bars must satisfy `data_time <= decision_time`; no completed future bar may leak into an earlier decision. Signal confirmation must use only closed/available source-time data unless the rule explicitly models intrabar execution.

## Look-Ahead Risks
Publication timestamp and revisions are critical; use only data available at decision time.

## Data Leakage Risks
Parameter selection, pattern detection thresholds, asset filtering and regime labeling must be fitted on DEV only and frozen before VALIDATION/OOS.

## Minimum History
Multiple market regimes including structural changes in options participation

## Benchmark
No-signal / contemporaneous market return

## Baseline Strategy
Fixed source thresholds vs rolling-quantile project-derived variant

## Test Dataset
Multi-asset data with source-appropriate market microstructure and realistic costs. Exact universe/timeframe must be fixed before experiment execution.

## DEV
Define deterministic signal semantics and unit tests. No optimization on OOS.

## VALIDATION
Freeze rules after DEV; compare to baseline on unseen validation period.

## OOS
Mandatory independent out-of-sample period and asset/venue transfer where applicable.

## Robustness
Parameter perturbation, cost/slippage stress, delayed execution, missing-data/stale-data tests, bootstrap/re-sampling where appropriate.

## Multi-Regime
Report performance by trend/range, volatility, liquidity and market condition instead of aggregate-only metrics.

## Paper Admission Criteria
Not defined in this ingestion phase. Must be derived from project Strategy Admission policy and empirical evidence, not from the book.

## Kill Criteria
No net improvement vs baseline after realistic costs; unstable across OOS/regimes; look-ahead/PIT failure; excessive parameter sensitivity; insufficient trade count; or evidence cannot be independently reproduced.

## Evidence Required
Backtest configuration + data fingerprints + code/version + costs + metrics + robustness + OOS + independent verification.

## Open Questions / Underspecification
Entry, exit, horizon and exact CBOE series are underspecified. Do not invent them as SOURCE_RULE.

## Current Status
`STRATEGY_CANDIDATE`
