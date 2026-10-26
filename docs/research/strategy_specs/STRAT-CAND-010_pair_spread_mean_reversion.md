# STRAT-CAND-010

## Source
SRC-BOOK-001 — *Trading Room: La especulación inteligente*, printed pp. 127-128.

## Source Claim
Historically related/correlated assets that temporarily diverge may reconverge; source proposes long one leg/short the other and gives a 4% deviation-stop example.

## Project Interpretation
This is a research candidate only. Explicit source rules are preserved; missing rules are marked `UNSPECIFIED_BY_SOURCE`. Any later alternatives must be labeled `PROJECT_DERIVED_VARIANT`.

## Market Hypothesis
Historically related/correlated assets that temporarily diverge may reconverge; source proposes long one leg/short the other and gives a 4% deviation-stop example.

## Economic / Behavioral Mechanism
Source proposes repeatable price/positioning behavior; mechanism is not independently validated by this book.

## Assets
Pairs of related assets; example BBVA/Santander

## Timeframes
UNSPECIFIED_BY_SOURCE

## Required Data
synchronized pair prices + corporate actions + borrow/short costs

## Features
relationship/spread metric UNSPECIFIED_BY_SOURCE

## Long Entry
When source-defined relationship diverges, buy A and sell B expecting reconvergence. Exact direction rule depends on historical relative ordering.

## Short Entry
Symmetric pair position, not standalone directional short.

## Exit
Close on reconvergence: implied by source but exact threshold UNSPECIFIED_BY_SOURCE.

## Stop
Source gives 4% deviation as example, not invariant.

## Take Profit
UNSPECIFIED_BY_SOURCE

## Invalidation
Relationship breakdown / stop

## Regime Applicability
Relative-value; intended market-direction-neutral

## Expected Mechanism
Same as Market Hypothesis; must be validated against an explicit baseline.

## Holding Period
UNSPECIFIED_BY_SOURCE

## Cost Sensitivity
Very sensitive to borrow, financing, spread, slippage, corporate actions

## PIT Requirements
All features and higher-timeframe bars must satisfy `data_time <= decision_time`; no completed future bar may leak into an earlier decision. Signal confirmation must use only closed/available source-time data unless the rule explicitly models intrabar execution.

## Look-Ahead Risks
Pair selection/correlation must not use future data; relationship estimation window must be causal.

## Data Leakage Risks
Parameter selection, pattern detection thresholds, asset filtering and regime labeling must be fitted on DEV only and frozen before VALIDATION/OOS.

## Minimum History
Long enough to estimate stable relationship across regimes

## Benchmark
Dollar-neutral naive pair

## Baseline Strategy
Cointegration/z-score PROJECT_DERIVED_VARIANT only

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
Source does not define correlation window, spread normalization, entry/exit threshold, hedge ratio or relationship-break test. These cannot be filled as source rules.

## Current Status
`STRATEGY_CANDIDATE`
