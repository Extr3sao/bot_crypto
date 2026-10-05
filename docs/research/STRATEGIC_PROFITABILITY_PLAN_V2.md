# RFC-035 STRATEGIC PROFITABILITY PLAN V2

as_of_commit = d940b532c09c4bb81ceed7132ace8830b33736ce
generated_at = 2026-10-05T13:50:03Z
branch = main
phase_1_status = CLOSED
phase_2_status = REENTRY_APPROVED
g_reentry = PASS

## Current state
- platform_status = RESEARCH_CAPABLE
- economic_status = NO_VALIDATED_EXECUTABLE_EDGE
- profitability_research_status = REENTRY_APPROVED
- entry_next_alpha_rfc_allowed = False
- next_alpha_rfc_allowed = True

## Why Phase 1 closed
Crypto-centric, intraday, indicator/price-driven lines were all rejected at a gate under realistic costs (RFC-010B..RFC-033).  See PROJECT_ECONOMIC_STATUS.md.

## What changes in Phase 2
External, multi-asset, lower-turnover, evidence-first.  EDGE FIRST, FREQUENCY SECOND.  Crypto is one possible sleeve, not the whole business.

## Markets considered
futures, equities, ETFs, FX, commodities, rates/bonds, indices, crypto.

## Strategies considered (12)
- MANAGED_FUTURES_TREND: Multi-asset managed-futures trend (time-series momentum)
- CROSS_SECTIONAL_MOMENTUM: Cross-sectional equity momentum (winners minus losers)
- EQUITY_FACTOR_MOMENTUM: Equity factor momentum (timing factor premia)
- VALUE_QUALITY: Value / quality factor portfolio
- LOW_VOL_BAB: Low-volatility / defensive (betting-against-beta)
- MULTI_ASSET_CARRY: Multi-asset carry (cross-asset carry factor)
- FX_CARRY: FX carry trade (high-yield vs low-yield currencies)
- FUTURES_CURVE_CARRY: Futures curve / term-structure carry
- RELATIVE_VALUE_PAIRS: Relative-value / pairs / spread mean-reversion
- VOLATILITY_RISK_PREMIUM: Volatility / variance risk premium
- COMMODITY_MOMENTUM: Cross-sectional commodity futures momentum
- COUNTRY_EQUITY_MOMENTUM: Cross-country equity index momentum (via liquid ETFs)

## Evidence standards
>= 2 independent sources per finalist where they exist; source authority ladder; post-publication survival; contradictory evidence mandatory.

## Economic standards
mechanism required; realistic cost floor; HEADROOM_RATIO bands; net-evidence exception allowed only with net-of-cost external evidence.

## Shortlist (top-5)
1. MANAGED_FUTURES_TREND
2. VALUE_QUALITY
3. FUTURES_CURVE_CARRY
4. COMMODITY_MOMENTUM
5. FX_CARRY

## Finalists (max 3)
1. MANAGED_FUTURES_TREND
2. VALUE_QUALITY
3. FUTURES_CURVE_CARRY

## Authorized reproductions (max 2)
1. MANAGED_FUTURES_TREND
2. FUTURES_CURVE_CARRY

## G_REENTRY = PASS
## Stop conditions
VALIDATION FAIL -> stop, no retuning; a finalist may remain RESEARCHABLE but NOT AUTHORIZED.

## Path to Validation
REPRODUCTION -> DISCOVERY -> VALIDATION (pre-registered spec, unseen data).
## Path to Paper
VALIDATION -> ROBUSTNESS -> HOLDOUT -> CERTIFICATION -> FORWARD PAPER.
## Path to Live
forward success -> CANARY -> explicit human approval -> LIVE.

## Economic marker
executable_validated_edge_count = 0; all execution counters remain 0.

## Provenance
SOURCE_COMMIT = d940b532c09c4bb81ceed7132ace8830b33736ce
FINAL_COMMIT = the RFC-035 build commit (this commit).
