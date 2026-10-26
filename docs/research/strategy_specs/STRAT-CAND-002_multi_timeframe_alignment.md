# STRAT-CAND-002

## Source
SRC-BOOK-001 — *Trading Room: La especulación inteligente*, printed pp. 97-99.

## Source Claim
Trades may perform better when execution, intermediate and higher timeframe trends are aligned; defer entry when they disagree.

## Project Interpretation
This is a research candidate only. Explicit source rules are preserved; missing rules are marked `UNSPECIFIED_BY_SOURCE`. Any later alternatives must be labeled `PROJECT_DERIVED_VARIANT`.

## Market Hypothesis
Trades may perform better when execution, intermediate and higher timeframe trends are aligned; defer entry when they disagree.

## Economic / Behavioral Mechanism
Source proposes repeatable price/positioning behavior; mechanism is not independently validated by this book.

## Assets
multi-asset

## Timeframes
Source examples: 15m + 1h + 1d; 1h + 1d + 1w; 1d + 1w + 1mo

## Required Data
OHLCV across synchronized timeframes

## Features
deterministic trend labels per timeframe

## Long Entry
Allow long only if all configured timeframes are bullish under the chosen deterministic trend label.

## Short Entry
Allow short only if all configured timeframes are bearish.

## Exit
This is a filter, so exit belongs to the base strategy.

## Stop
Inherited from base strategy.

## Take Profit
Inherited from base strategy.

## Invalidation
Any required timeframe is neutral/conflicting/stale

## Regime Applicability
Trend filter applicable; may cause no-trade in disagreement

## Expected Mechanism
Same as Market Hypothesis; must be validated against an explicit baseline.

## Holding Period
Inherited

## Cost Sensitivity
May reduce trade frequency and alter cost profile

## PIT Requirements
All features and higher-timeframe bars must satisfy `data_time <= decision_time`; no completed future bar may leak into an earlier decision. Signal confirmation must use only closed/available source-time data unless the rule explicitly models intrabar execution.

## Look-Ahead Risks
HTF future-bar leak is primary risk; only last fully available higher-timeframe bar may be used.

## Data Leakage Risks
Parameter selection, pattern detection thresholds, asset filtering and regime labeling must be fitted on DEV only and frozen before VALIDATION/OOS.

## Minimum History
Enough data for all HTFs and base strategy

## Benchmark
Base strategy without alignment filter

## Baseline Strategy
Same signal strategy on execution timeframe only

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
Source trend definition can be chart-based; project must define a deterministic trend label as PROJECT_DERIVED_VARIANT and never attribute it to source.

## Current Status
`STRATEGY_CANDIDATE`
