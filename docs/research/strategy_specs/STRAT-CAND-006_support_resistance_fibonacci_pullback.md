# STRAT-CAND-006

## Source
SRC-BOOK-001 — *Trading Room: La especulación inteligente*, printed pp. 119-122.

## Source Claim
In an MA-defined trend, entries at support/resistance that coincide with 38% or 50% Fibonacci retracement may improve pullback timing.

## Project Interpretation
This is a research candidate only. Explicit source rules are preserved; missing rules are marked `UNSPECIFIED_BY_SOURCE`. Any later alternatives must be labeled `PROJECT_DERIVED_VARIANT`.

## Market Hypothesis
In an MA-defined trend, entries at support/resistance that coincide with 38% or 50% Fibonacci retracement may improve pullback timing.

## Economic / Behavioral Mechanism
Source proposes repeatable price/positioning behavior; mechanism is not independently validated by this book.

## Assets
multi-asset

## Timeframes
configurable

## Required Data
OHLCV

## Features
MA20/40/200, deterministic S/R, swing anchor, Fib 38/50

## Long Entry
Bullish trend; price reaches support coincident with 38%/50% retracement; buy.

## Short Entry
Bearish trend; price reaches resistance coincident with 38%/50%; short.

## Exit
Source target: previous extreme / opposite S/R.

## Stop
Below support for long; above resistance for short.

## Take Profit
Previous swing extreme / resistance-support

## Invalidation
Trend invalidation / level break

## Regime Applicability
Trending only

## Expected Mechanism
Same as Market Hypothesis; must be validated against an explicit baseline.

## Holding Period
Swing to swing

## Cost Sensitivity
Moderate; entries at levels may be limit/market-sensitive

## PIT Requirements
All features and higher-timeframe bars must satisfy `data_time <= decision_time`; no completed future bar may leak into an earlier decision. Signal confirmation must use only closed/available source-time data unless the rule explicitly models intrabar execution.

## Look-Ahead Risks
Fibonacci anchors are look-ahead-prone if swing points are not confirmed.

## Data Leakage Risks
Parameter selection, pattern detection thresholds, asset filtering and regime labeling must be fitted on DEV only and frozen before VALIDATION/OOS.

## Minimum History
Multiple swing cycles

## Benchmark
S/R pullback without Fibonacci filter

## Baseline Strategy
S/R-only pullback

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
How are S/R and swing anchors detected? Source is discretionary. Deterministic definitions must be PROJECT_DERIVED_VARIANT.

## Current Status
`STRATEGY_CANDIDATE`
