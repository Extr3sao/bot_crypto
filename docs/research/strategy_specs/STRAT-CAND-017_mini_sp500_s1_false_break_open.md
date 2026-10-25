# STRAT-CAND-017 — Mini Sp500 S1 False Break Open

## Source
SRC-MANUAL-002

## Source Location
pp.90-91

## Source Claim
Fade an aggressive early Mini S&P opening move under a tightly specified source context.

## Source Explicit Rules
SOURCE_EXPLICIT: 6-10 point subrange; open near midpoint; aggressive move to S/R 1-3; Speed >3000; fade toward opposite side.

## Source Implied Rules
None are promoted automatically. Any plausible but unstated rule remains `SOURCE_IMPLIED` and must be documented before testing.

## Missing Rules
Speed formula unavailable; stop definition incomplete; time-zone and contract/tick details must be frozen; thresholds quarantined.

## Project-Derived Variants
Allowed only in a later experiment and must be labeled `PROJECT_DERIVED_VARIANT`; never attributed to the source.

## Market Hypothesis
Fade an aggressive early Mini S&P opening move under a tightly specified source context.

## Expected Mechanism
Source narrative is preserved but not accepted as causal truth. The experiment must test the observable price/data pattern separately from any causal story.

## Assets
Mini S&P 500 futures

## Timeframes
3m context; first 15-20m after US cash open

## Required Data
Point-in-time OHLCV plus any explicitly required cross-asset, calendar/session, economic-event or proprietary feature data. Missing data blocks source-faithful testing.

## Features
Only source-explicit features are eligible for the source-faithful arm. Derived detectors require an ablation arm and provenance label.

## Long Entry
To be encoded from source rules only after all missing conditions are resolved. No implementation in ingestion phase.

## Short Entry
Symmetric only when the source explicitly supports symmetry; otherwise unresolved.

## Exit
Source-defined where available; otherwise `UNDERSPECIFIED`.

## Initial Stop
Source-defined where available; otherwise `UNDERSPECIFIED`. No source value becomes project Risk policy.

## Take Profit
Source-defined where available; otherwise `UNDERSPECIFIED`.

## Trailing Logic
Not assumed unless explicitly specified.

## Invalidation
At minimum: stale/PIT-invalid data; unresolved source rules; wrong regime; unavailable required feature; contradiction with source-defined condition.

## Regime Applicability
Must be evaluated explicitly and point-in-time. Source regime labels are hypotheses, not future-known truth.

## Cost Model
BASE_COST first. Only survivors may proceed to 2X_COST / STRESSED_COST; ZERO_COST diagnostic cannot support promotion.

## PIT Requirements
`data_time <= decision_time`; closed-bar availability; legal HTF close; session/DST correctness; cross-asset synchronization; event-calendar publication time where relevant.

## Look-Ahead Risks
Pattern labels based on future reversal, swing confirmation using future bars, post-hoc Order Block selection, future daily high/low, future regime classification, event data unavailable at decision time.

## Baseline
Simpler observable baseline without source-specific confluence, plus no-trade where applicable.

## Test Dataset
Pre-register assets, period, costs and regimes. DEV -> freeze -> VALIDATION -> freeze -> OOS. OOS unavailable for tuning.

## DEV
Determine whether source-explicit rules can be implemented without leakage and whether basic expectancy survives costs.

## VALIDATION
Frozen configuration only.

## OOS
Locked until candidate and selection criteria are frozen.

## Robustness
Parameter perturbation, alternate assets, adjacent periods, session/DST stress, cost/slippage stress, regime split.

## Multi-Regime
Required before any paper admission.

## Paper Admission Criteria
Not defined by this source ingestion. Requires separate governance and independent verification.

## Kill Criteria
PIT violation; source-faithful rules cannot be reconstructed; negative gross expectancy across validation; edge disappears under plausible costs; performance depends on post-hoc labels; fragility to minor parameter changes.

## Source-Faithfulness Criteria
SOURCE_FAITHFUL_EXPERIMENT = **FALSE** at ingestion time. Critical `PROJECT_DERIVED` or `MISSING` components must be resolved before any claim about the source hypothesis.

## Evidence Required
Source-location mapping, frozen code/config hash, dataset fingerprint, PIT checks, costs, full trade list, DEV/VALIDATION separation, independent verifier.

## Current Status
STRATEGY_CANDIDATE — NEEDS_SPEC_BEFORE_SOURCE_FAITHFUL_TEST

## Experiment
EXP-026
