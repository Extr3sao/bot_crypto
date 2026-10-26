# STRAT-CAND-001

## Source
SRC-BOOK-001 — *Trading Room: La especulación inteligente*, printed pp. 99-105.

## Source Claim
In an established MA20>MA40>MA200 trend (inverse for short), the first pullback to MA20 after MA20/40 cross may continue the trend; source exits on MA40 break.

## Project Interpretation
This is a research candidate only. Explicit source rules are preserved; missing rules are marked `UNSPECIFIED_BY_SOURCE`. Any later alternatives must be labeled `PROJECT_DERIVED_VARIANT`.

## Market Hypothesis
In an established MA20>MA40>MA200 trend (inverse for short), the first pullback to MA20 after MA20/40 cross may continue the trend; source exits on MA40 break.

## Economic / Behavioral Mechanism
Source proposes repeatable price/positioning behavior; mechanism is not independently validated by this book.

## Assets
UNSPECIFIED_BY_SOURCE; examples are market price series

## Timeframes
configurable; source uses “sessions/periods”

## Required Data
OHLCV sufficient for source rule

## Features
SMA20, SMA40, SMA200, swing highs/lows, candle touch/break

## Long Entry
After MA20 crosses above MA40 and ordered trend is established, wait for first pullback touching MA20; buy when the next criterion specified by source is met: break above the relevant candle; optional source filter is prior swing-high break.

## Short Entry
Symmetric: MA20 below MA40, first pullback to MA20, sell on break below relevant candle; optional prior swing-low break.

## Exit
Source: exit when price breaks MA40. Exact breakout confirmation variant is not fixed by source.

## Stop
Source: below pullback candle low or below MA40; source offers alternatives, therefore experiment arms must not mix them silently.

## Take Profit
UNSPECIFIED_BY_SOURCE beyond MA40 exit

## Invalidation
Ordered MA structure fails / MA40 exit condition

## Regime Applicability
Trending only

## Expected Mechanism
Same as Market Hypothesis; must be validated against an explicit baseline.

## Holding Period
From entry until MA40 exit

## Cost Sensitivity
Potentially high on shorter timeframes; must stress spread/slippage/fees

## PIT Requirements
All features and higher-timeframe bars must satisfy `data_time <= decision_time`; no completed future bar may leak into an earlier decision. Signal confirmation must use only closed/available source-time data unless the rule explicitly models intrabar execution.

## Look-Ahead Risks
Do not identify “first pullback” using future knowledge; swing-break must be confirmed in real time.

## Data Leakage Risks
Parameter selection, pattern detection thresholds, asset filtering and regime labeling must be fitted on DEV only and frozen before VALIDATION/OOS.

## Minimum History
At least enough history for SMA200 plus independent regime samples

## Benchmark
Buy/hold or simple MA crossover

## Baseline Strategy
MA20/40 crossover without pullback filter

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
Source permits multiple stop/entry variants. They must be separated into explicit experiment arms.

## Current Status
`STRATEGY_CANDIDATE`
