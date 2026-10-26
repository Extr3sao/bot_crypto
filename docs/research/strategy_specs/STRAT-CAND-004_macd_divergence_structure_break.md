# STRAT-CAND-004

## Source
SRC-BOOK-001 — *Trading Room: La especulación inteligente*, printed pp. 111-113.

## Source Claim
MACD/price divergence followed by break of an important support/resistance or trend line may precede reversal.

## Project Interpretation
This is a research candidate only. Explicit source rules are preserved; missing rules are marked `UNSPECIFIED_BY_SOURCE`. Any later alternatives must be labeled `PROJECT_DERIVED_VARIANT`.

## Market Hypothesis
MACD/price divergence followed by break of an important support/resistance or trend line may precede reversal.

## Economic / Behavioral Mechanism
Source proposes repeatable price/positioning behavior; mechanism is not independently validated by this book.

## Assets
multi-asset

## Timeframes
configurable

## Required Data
OHLCV

## Features
MACD extrema, price extrema, deterministic structural level

## Long Entry
Bullish divergence: price lower low while MACD higher low; enter only after bullish break of defined important level.

## Short Entry
Bearish divergence: source wording contains an apparent typo; concept is price strength vs MACD weakness. Must be formalized from source figures/definition without inventing. Enter only after bearish structural break.

## Exit
Source: close on subsequent MACD recross in examples; exact exit rule not fully specified in divergence section.

## Stop
Beyond recent swing; source says normally within last five periods.

## Take Profit
UNSPECIFIED_BY_SOURCE

## Invalidation
Divergence invalidated / stop hit

## Regime Applicability
Counter-trend exception; elevated risk

## Expected Mechanism
Same as Market Hypothesis; must be validated against an explicit baseline.

## Holding Period
Short-to-medium reversal

## Cost Sensitivity
Potentially sensitive to delay and swing definition

## PIT Requirements
All features and higher-timeframe bars must satisfy `data_time <= decision_time`; no completed future bar may leak into an earlier decision. Signal confirmation must use only closed/available source-time data unless the rule explicitly models intrabar execution.

## Look-Ahead Risks
Divergence extrema are highly look-ahead-prone; pivots must be defined with confirmation delay.

## Data Leakage Risks
Parameter selection, pattern detection thresholds, asset filtering and regime labeling must be fitted on DEV only and frozen before VALIDATION/OOS.

## Minimum History
Enough history for MACD/pivots and many reversals

## Benchmark
Simple structure-break reversal

## Baseline Strategy
Structure break without MACD divergence

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
Reject the source “85%” claim as evidence. Define pivot confirmation and bearish-divergence semantics before any test.

## Current Status
`STRATEGY_CANDIDATE`
