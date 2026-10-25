# STRAT-CAND-005

## Source
SRC-BOOK-001 — *Trading Room: La especulación inteligente*, printed pp. 114-119.

## Source Claim
In MA20/40/200 trend, a 3-6 candle counter-trend pullback into MA20-to-MA40 zone followed by prior-candle breakout may resume trend.

## Project Interpretation
This is a research candidate only. Explicit source rules are preserved; missing rules are marked `UNSPECIFIED_BY_SOURCE`. Any later alternatives must be labeled `PROJECT_DERIVED_VARIANT`.

## Market Hypothesis
In MA20/40/200 trend, a 3-6 candle counter-trend pullback into MA20-to-MA40 zone followed by prior-candle breakout may resume trend.

## Economic / Behavioral Mechanism
Source proposes repeatable price/positioning behavior; mechanism is not independently validated by this book.

## Assets
multi-asset

## Timeframes
configurable

## Required Data
OHLCV

## Features
SMA20/40/200, candle sequence, prior candle range

## Long Entry
Trend bullish; 3-6 bearish candles pull back to MA20 or MA20-40 zone, never beyond MA40 per source; buy above prior candle high plus source 1/9 range filter.

## Short Entry
Symmetric bearish trend; 3-6 bullish candles recover to MA20/40 zone; sell below prior candle low using source 1/9 filter.

## Exit
Target source: previous swing extreme; no trailing rule specified.

## Stop
Source: beyond lower/higher of reference/current candle by 1/9 of prior candle range.

## Take Profit
Source: prior swing extreme adjusted by 1/18; trade selected only if source 3:1 reward/risk condition holds.

## Invalidation
Pullback exceeds MA40 zone / stop

## Regime Applicability
Strong trend; source says more effective on volatile assets

## Expected Mechanism
Same as Market Hypothesis; must be validated against an explicit baseline.

## Holding Period
Until prior swing target or stop

## Cost Sensitivity
Very sensitive to spread/slippage around breakout and to gap execution

## PIT Requirements
All features and higher-timeframe bars must satisfy `data_time <= decision_time`; no completed future bar may leak into an earlier decision. Signal confirmation must use only closed/available source-time data unless the rule explicitly models intrabar execution.

## Look-Ahead Risks
3-6 sequence and prior swing must be defined without future-known extrema.

## Data Leakage Risks
Parameter selection, pattern detection thresholds, asset filtering and regime labeling must be fitted on DEV only and frozen before VALIDATION/OOS.

## Minimum History
SMA200 + sufficient pullback samples

## Benchmark
Trend pullback without 1/9 and 3:1 filters

## Baseline Strategy
Same pattern with simpler ATR-normalized project-derived controls

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
1/9, 1/18 and 3:1 are source thresholds, not project defaults; compare them to normalized variants.

## Current Status
`STRATEGY_CANDIDATE`
