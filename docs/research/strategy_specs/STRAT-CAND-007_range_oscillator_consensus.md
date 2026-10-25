# STRAT-CAND-007

## Source
SRC-BOOK-001 — *Trading Room: La especulación inteligente*, printed pp. 122-125.

## Source Claim
In lateral markets bounded by support/resistance, simultaneous RSI/Stochastic/CCI extremes with CCI ±100 turn may support mean-reversion entries.

## Project Interpretation
This is a research candidate only. Explicit source rules are preserved; missing rules are marked `UNSPECIFIED_BY_SOURCE`. Any later alternatives must be labeled `PROJECT_DERIVED_VARIANT`.

## Market Hypothesis
In lateral markets bounded by support/resistance, simultaneous RSI/Stochastic/CCI extremes with CCI ±100 turn may support mean-reversion entries.

## Economic / Behavioral Mechanism
Source proposes repeatable price/positioning behavior; mechanism is not independently validated by this book.

## Assets
multi-asset

## Timeframes
configurable

## Required Data
OHLCV

## Features
range detector, support/resistance, RSI, stochastic, CCI

## Long Entry
Range/no-trend; price near support; all three indicators oversold; source trigger when CCI turns from around -100.

## Short Entry
Price near resistance; all three overbought; CCI turns from around +100.

## Exit
Target opposite range boundary.

## Stop
Beyond support/resistance.

## Take Profit
Opposite range boundary.

## Invalidation
Range breakout / stop

## Regime Applicability
Lateral/range only

## Expected Mechanism
Same as Market Hypothesis; must be validated against an explicit baseline.

## Holding Period
Within range swing

## Cost Sensitivity
Likely turnover/cost-sensitive

## PIT Requirements
All features and higher-timeframe bars must satisfy `data_time <= decision_time`; no completed future bar may leak into an earlier decision. Signal confirmation must use only closed/available source-time data unless the rule explicitly models intrabar execution.

## Look-Ahead Risks
Range boundary must be established only from past data; no future-defined channel.

## Data Leakage Risks
Parameter selection, pattern detection thresholds, asset filtering and regime labeling must be fitted on DEV only and frozen before VALIDATION/OOS.

## Minimum History
Many range episodes

## Benchmark
S/R mean reversion

## Baseline Strategy
S/R-only mean reversion

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
Source says use platform defaults for indicators but does not define RSI/Stochastic thresholds here. Must preserve as UNSPECIFIED_BY_SOURCE until exact source defaults/context are established.

## Current Status
`STRATEGY_CANDIDATE`
