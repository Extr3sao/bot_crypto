# FINAL REPORT — POC01-RECOVERY-AND-EVIDENCE-01

BASE: `31fd5d2` · LIVE: DISABLED · LIVE_CALLS: 0 · FALSE_SUCCESS: 0

## Executive status: PASS

| Field | Result |
| --- | --- |
| POC01_RUNTIME | **ACTIVE (RESUMED)** — was DOWN at checkpoint start (heartbeat 2026-09-08T17:12:49Z); recovered via the existing resume contract at **2026-09-09T08:28:07Z**. No new campaign created. |
| POC01_API_8766 | FAIL (down at checkpoint start; external tooling — recovery of the API process is an operational action outside repo scope) |
| FRONTEND_8767 | FAIL (same as above) |
| CAMPAIGN_ID | `POC-01-paper-observation-01` — **CAMPAIGN_ID_BEFORE == CAMPAIGN_ID_AFTER** (proven by resume-path determinism + sha256 state diff showing only heartbeat + new 09-09 daily report) |
| CONTINUITY | **PASS** — decision lineage intact (1 decision, no duplicates); 2026-09-08 artifacts byte-identical after recovery |
| DOWNTIME_HOURS | **15.25 h** (54,918 s: 2026-09-08T17:12:49Z → 2026-09-09T08:28:07Z) |
| DEF_POC01_OBS_006 | **CONFIRMED + REPAIRED** — validity was implicitly trade-coupled ("D1_VALID=true but COMPLETED_VALID_DAYS=0 because 0 trades"). Repair: `paper/observation_metrics.py` canonicalizes COMPLETED_VALID_DAYS = count(FINALIZED ∧ COUNTED ∧ VALID), trade-independent; DAYS_GE_3 / PERCENT_DAYS_GE_3 computed separately; zero-trade valid days count. Observation/reporting semantics only — trading behavior untouched, raw observations immutable. |
| COMPLETED_VALID_DAYS | **1** (2026-09-08: finalized, counted, valid, 0 trades — counts under repaired semantics) |
| DAYS_GE_3 | 0 |
| PERCENT_DAYS_GE_3 | 0.0 |
| DAILY_COVERAGE | Per-day in `POC01_CANONICAL_DAILY_TABLE.json`: 09-06 BURN_IN (excluded) · 09-07 **NOT_OBSERVED** (no artifact — see correction below) · 09-08 COUNTED valid, coverage 0.717 (407.2 min outage) · 09-09 PARTIAL, coverage 0.647 (508.1 min) |
| POC01_TRADES | 0 (TOTAL_TRADES across valid days) |
| POC01_PNL | 0.0 realized |
| LEGACY_RETRO_PROTOCOL | **PASS** — fingerprint `d2f17f91…` re-derived and verified EQUAL to the `31fd5d2` frozen value BEFORE execution; thresholds/cost model/regime rules untouched after results |
| RETRO_EXECUTIONS | **30 real-data cells** (5 strategies × BTC/ETH/SOL × 5m/1h; binanceusdm public PIT data, dataset fp `68778ce1…`) |
| MOMENTUM | LEGACY_VALIDATION_FAIL (all evaluated cells FAILED_CELL under composed gates) |
| TREND | INSUFFICIENT_EVIDENCE (insufficient sample in evaluated cells) |
| BREAKOUT | LEGACY_VALIDATION_FAIL |
| MEAN_REVERSION | LEGACY_VALIDATION_FAIL |
| VOLATILITY | INSUFFICIENT_EVIDENCE |
| VALIDATED_REGIME_CELLS | 0 |
| FAILED_REGIME_CELLS | 14 |
| INSUFFICIENT_REGIME_CELLS | 16 |
| HEALTH_BASELINES_PROPOSED | **0** (correct fail-closed: baselines require VALIDATED cells; none qualified — no baseline manufactured) |
| NEW_STRATEGY_CANDIDATES | 6 accepted to Lab (RESEARCH ONLY) |
| CANDIDATE_FAMILIES | carry_funding, cross_sectional, session_time, liquidity_flow, volatility_structure, multi_timeframe_context (regime-first: FUSED_CORRELATION, RANGE, TRANSITION, BEAR, CORRECTION, HIGH_VOL targets) |
| PAPER_PROMOTIONS | 0 |
| SHADOW_V2_PREPARATION | **PASS** — `shadow/integration.py` ShadowCaptureHook (Risk-REJECT arm → immutable capture → PIT resolution); isolation AST-proven (no paper/demo/risk/portfolio imports; execution imports limited to canonical cost model); capture/outcome ledgers separate + persistent |
| BYBIT_CONFORMANCE | **PASS** — full `ExchangeAdapterConformanceSuite` through the REAL `BybitConnector` call path (simulated transport); identity stable under retry, ECONOMIC_ORDERS ≤ 1 |
| CONFIRMATION_CONSUMED | **false** (re-verified from `39578a6` manifest; window 2026-09-08→2026-09-22) |
| CONFIRMATION_EXECUTIONS | 0 |
| POC01_TRADING_BEHAVIOR_CHANGED | 0 |
| LIVE_CALLS | 0 |
| FALSE_SUCCESS | 0 |
| NEW_TESTS | 3 files · 17 functions (observation_metrics 9, shadow integration 5, bybit binding 2, + runtime-path continuation) |
| HERMETIC_REGRESSION | **964 passed / 0 failed — exit 0** (947 prior + 17 new; closure guard green) |
| RUFF / MYPY | CLEAN / CLEAN (7 source files in scope) |
| STATUS | **PASS** |

## Honest corrections recorded this checkpoint

1. **DEF-POC01-OBS-006 (CONFIRMED)**: valid-day semantics were trade-coupled.
   Repaired in `paper/observation_metrics.py` with tests proving the
   canonical invariants (validity ≠ trade count; frequency separate;
   burn-in and partial days excluded; zero-trade valid days count).
2. **D1 date mapping corrected**: 2026-09-07 has **no daily-report
   artifact** — it was never observed, despite earlier reports treating
   it as the finalized D1. The canonical table records 09-07 as
   NOT_OBSERVED (PARTIAL) and treats **2026-09-08 as the first finalized,
   counted, valid (zero-trade) day**. Nothing hidden; artifact dates are
   the authority.
3. **Outage reported, not hidden**: the 15.25h downtime is split at UTC
   midnight across 09-08 (407.2 min) and 09-09 (508.1 min) in per-day
   coverage evidence. No new day-invalidation threshold was invented; the
   outage is recorded as coverage evidence only.

## Track B — retro execution detail

- Protocol fingerprint verified equal to the frozen value before any
  execution; dataset frozen post-fetch and fingerprinted.
- PIT discipline: signal at bar t uses candles ≤ t; entry at next bar
  open; adverse-first stop; no future leakage.
- Composed gates (expectancy + Sharpe + CI-excludes-negative + P(Sharpe>0)
  ≥ 0.5 + permutation p < 0.10) — no single statistic certifies.
- Result: honest negative — **0/30 cells validated** on the evaluated
  window. Momentum/breakout/mean_reversion FAIL; trend/volatility
  insufficient. This is evidence, not a runtime change: POC01 authority
  untouched; proposed statuses are future-decision inputs only.

## Track D — analysis target ready

Next campaign can produce exactly the checkpoint's target shape:
per-reason (CONSECUTIVE_LOSS_COOLDOWN, MAX_POSITIONS, …) candidate/wins/
losses/expectancy metrics conditioned by strategy, asset, regime,
StrategyHealth, correlation regime and PortfolioIntelligence context —
all fields are carried on the capture and flow into
`RejectReasonAnalysis`.

## NEXT

CONTINUE_POC01 · LEGACY_EVIDENCE_ANALYSIS · STRATEGY_DISCOVERY ·
SHADOW_CAMPAIGN_V2 · CONFIRMATION_WAIT
