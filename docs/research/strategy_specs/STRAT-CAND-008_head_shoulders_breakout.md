# STRAT-CAND-008

## Source
SRC-BOOK-001 — *Trading Room: La especulación inteligente*, printed pp. 68-74.

## Source Claim
Confirmed H&S neckline break with volume pattern may signal reversal; measured-move target and right-shoulder stop are specified.

## Project Interpretation
This is a research candidate only. Explicit source rules are preserved; missing rules are marked `UNSPECIFIED_BY_SOURCE`. Any later alternatives must be labeled `PROJECT_DERIVED_VARIANT`.

## Market Hypothesis
Confirmed H&S neckline break with volume pattern may signal reversal; measured-move target and right-shoulder stop are specified.

## Economic / Behavioral Mechanism
Source proposes repeatable price/positioning behavior; mechanism is not independently validated by this book.

## Assets
multi-asset

## Timeframes
configurable

## Required Data
OHLCV

## Features
deterministic H&S detector, neckline, volume pattern

## Long Entry
Inverse H&S: enter only after confirmed neckline break upward with required volume confirmation.

## Short Entry
H&S: enter only after confirmed neckline break downward; source treats volume rise as supportive but less critical on declines.

## Exit
Measured move equal to head-to-neckline distance projected from break.

## Stop
Beyond right shoulder.

## Take Profit
Measured move.

## Invalidation
Right shoulder stop / pattern failure

## Regime Applicability
Reversal after prior trend

## Expected Mechanism
Same as Market Hypothesis; must be validated against an explicit baseline.

## Holding Period
Pattern target horizon

## Cost Sensitivity
Breakouts can be cost/gap-sensitive

## PIT Requirements
All features and higher-timeframe bars must satisfy `data_time <= decision_time`; no completed future bar may leak into an earlier decision. Signal confirmation must use only closed/available source-time data unless the rule explicitly models intrabar execution.

## Look-Ahead Risks
Pattern recognition and neckline placement are severe hindsight risks; detector must be causal and frozen.

## Data Leakage Risks
Parameter selection, pattern detection thresholds, asset filtering and regime labeling must be fitted on DEV only and frozen before VALIDATION/OOS.

## Minimum History
Large sample of candidate patterns

## Benchmark
Plain neckline breakout

## Baseline Strategy
Breakout without shape/volume filter

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
Pattern geometry tolerances and volume thresholds are not quantitatively specified by source.

## Current Status
`STRATEGY_CANDIDATE`
