# EXP-019 — Order Block Ote Pullback Fx

## Hypothesis
HYP-018: Compare source-faithful Order Block/OTE pullback arm against simpler trend-pullback baselines with identical data/costs.

## Source
SRC-MANUAL-001

## Type
STRATEGY

## Source-Faithfulness
Source-explicit rules are frozen separately from project-derived variants. If any critical component is missing, this experiment cannot reject the source hypothesis.

## Dataset Requirements
PIT FX OHLCV + session calendar + HTF bars

## Assets
As explicitly supported by the source/spec; broaden only in a separately labeled robustness phase.

## Timeframe
As source-defined where available. Derived alternatives must be separate arms.

## Market Regimes
Pre-register and classify point-in-time; no future-known labels.

## Features
No feature may use future bars, future daily high/low, post-event labels or retrospectively selected pivots.

## Entry / Exit
Must be frozen before execution. Source rules and project-derived exit/stop variants remain separate.

## Cost Model
BASE_COST -> survivor gate -> 2X_COST / STRESSED_COST; ZERO_COST diagnostic only.

## Baseline
Simpler mechanism-matched baseline plus no-trade where relevant.

## DEV
Build/fix only from DEV. Record every parameter decision.

## VALIDATION
Frozen candidate only. Failure ends promotion path unless a new hypothesis/version is registered.

## OOS_LOCKED
OOS cannot influence tuning, filtering or candidate selection.

## Robustness
Adjacent periods, parameter perturbation, assets, regimes, costs, session/DST and data-source sensitivity where relevant.

## Ablation
Remove each source-specific confluence separately to measure incremental value.

## Kill Criteria
Look-ahead/PIT violation; non-reproducibility; hidden exception; negative gross expectancy across validation; cost fragility; post-hoc pattern selection; dependence on unavailable/proprietary feature; no incremental value over baseline.

## Success Criteria
Pre-registered, project-specific and evidence-based. No threshold from the source is automatically a pass criterion.

## Required Evidence
Dataset fingerprints; code/config commit/hash; tests; trade/event outputs; cost breakdown; metrics by regime; independent verification.

## Status
NEEDS_RULE_FREEZE
