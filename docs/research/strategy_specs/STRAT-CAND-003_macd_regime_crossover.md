# STRAT-CAND-003

## Source
SRC-BOOK-001 — *Trading Room: La especulación inteligente*, printed pp. 105-111.

## Source Claim
MACD zero-line regime plus base/signal crossover and three-bar persistence may capture trend continuation.

## Project Interpretation
This is a research candidate only. Explicit source rules are preserved; missing rules are marked `UNSPECIFIED_BY_SOURCE`. Any later alternatives must be labeled `PROJECT_DERIVED_VARIANT`.

## Market Hypothesis
MACD zero-line regime plus base/signal crossover and three-bar persistence may capture trend continuation.

## Economic / Behavioral Mechanism
Source proposes repeatable price/positioning behavior; mechanism is not independently validated by this book.

## Assets
multi-asset

## Timeframes
configurable

## Required Data
OHLCV

## Features
MACD base, signal, zero-line; bar counter

## Long Entry
MACD above zero; base crosses signal upward; after three subsequent closed bars the lines remain in bullish relation, enter long. Source also describes zero-line upward cross as another signal arm.

## Short Entry
MACD below zero; base crosses signal downward; after three closed bars remain bearish, enter short. Zero-line downward cross is another signal arm.

## Exit
Exit when base/signal cross reverses after entry.

## Stop
UNSPECIFIED_BY_SOURCE for crossover variant.

## Take Profit
UNSPECIFIED_BY_SOURCE

## Invalidation
Opposite recross / regime invalidation

## Regime Applicability
Trending; source warns lateral markets create false signals

## Expected Mechanism
Same as Market Hypothesis; must be validated against an explicit baseline.

## Holding Period
Until recross

## Cost Sensitivity
Turnover can be high; three-bar delay changes slippage/opportunity cost

## PIT Requirements
All features and higher-timeframe bars must satisfy `data_time <= decision_time`; no completed future bar may leak into an earlier decision. Signal confirmation must use only closed/available source-time data unless the rule explicitly models intrabar execution.

## Look-Ahead Risks
Three-bar persistence must wait for three closed bars; no peeking at third-bar close.

## Data Leakage Risks
Parameter selection, pattern detection thresholds, asset filtering and regime labeling must be fitted on DEV only and frozen before VALIDATION/OOS.

## Minimum History
MACD warmup + multiple regimes

## Benchmark
Standard MACD crossover

## Baseline Strategy
MACD crossover without zero-line and persistence filters

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
Source does not give MACD parameter values in the reviewed rule; platform defaults are mentioned elsewhere for other indicators, not safely attributable here.

## Current Status
`STRATEGY_CANDIDATE`
