# FINAL REPORT — INTELLIGENCE-AND-EXECUTION-HARDENING-01

Date: 2026-09-08
BASE: `814f0e4` (EXECUTION-RELIABILITY-01)
Tracks: EXECUTION-RELIABILITY-RUNTIME-01 + STRATEGY-HEALTH-01 + REGIME-INTELLIGENCE-V2 + STAT-VALIDATION-01

## CHECKPOINT

INTELLIGENCE-AND-EXECUTION-HARDENING-01

## EXECUTION_RUNTIME_REACHABILITY

PASS (as FOUNDATION). Runtime-reachable adapters audited: BinanceConnector,
BybitConnector (CCXT), BitunixSpotConnector, BitunixFuturesConnector. OKX and
Kraken: NOT_RUNTIME_REACHABLE (no adapter exists; whitelist excludes them by
design, ADR-required to add). See `runtime_execution_authority_map.md`.

## OKX_CONFORMANCE

NOT_RUNTIME_REACHABLE — no adapter; conformance suite V1 ready to apply when
one exists.

## KRAKEN_CONFORMANCE

NOT_RUNTIME_REACHABLE — no adapter; conformance suite V1 ready to apply when
one exists.

## ECONOMIC_ORDERS_PER_INTENT

<= 1 — enforced by `IdempotentSubmitGate` + post-submit short-circuit +
gate-governed controlled retries in `ExecutionGateway`. Proven under retry
N-times, ACK lost/late/duplicate, orphan, restart, cancel ambiguity (A1/A2
tests). Fake/simulated venue only.

## ACK_UNKNOWN_E2E

PASS — venue-accepted + client-timeout -> ACK_UNKNOWN -> query by stable
identity -> ADOPT (ECONOMIC_ORDERS=1); definitely-absent -> controlled retry
(same identity, gate-governed); uncertain -> BLOCK (no economic order).

## DUPLICATE_FILL_E2E

PASS — duplicate + partial + out-of-order fills through the gateway apply
position/fee/PnL/journal deltas exactly once (FillLedger by venue_fill_id).

## STARTUP_RECONCILIATION

PASS — `execution_ready()` fail-closed gate lists missing prerequisites
(instrument metadata, account, positions, open orders, recent fills);
`reconcile()` adopts-or-closes, never auto-resubmits. No real venue orders.

## EXECUTION_STATUS

FOUNDATION_ONLY — exact missing integration for RUNTIME_CERTIFIED:
1. `app.py`/`paper_cycle.py` order paths do not construct ExecutionGateway.
2. No adapter passes `derive_client_order_id(intent_id)` as cloid.
3. `ExecutionJournal(path=...)` JSONL persistence not mounted in runtime.
4. No OKX/Kraken connector exists.
5. Adapter `cancel_order` returns None — no confirmation payload for real
   CANCELLED transitions.
LIVE remains DISABLED either way.

## STRATEGY_HEALTH

PASS — `strategies/health.py`: conditional cells (strategy x version x asset
x timeframe x regime x window), deterministic thresholds, sample gate,
consecutive-window hysteresis, proposals-only transitions, LEGACY_PAPER_BASELINE
preserved.

## HEALTH_STATES

HEALTHY / MONITORING / DEGRADED / QUARANTINED / RETIRED (+ LEGACY_PAPER_BASELINE,
INSUFFICIENT_EVIDENCE). No single-trade flips; recovery requires research ->
revalidation -> MONITORING (never auto-HEALTHY); RETIRED terminal.

## HEALTH_VERIFIER

PASS — `StrategyHealthVerifier` (BUILDER != VERIFIER): sample adequacy,
metric domains, window identity, PIT-bounded window, baseline binding, regime
binding, hysteresis citation, transition legality.

## REGIME_INTELLIGENCE

PASS — existing `RegimeEngine` audited and EXTENDED (composition, not
duplication): `research/regime_v2.py` derives the canonical state.

## REGIME_DIMENSIONS

trend_direction (BULL/BEAR/NEUTRAL), trend_strength (WEAK/MEDIUM/STRONG),
volatility (LOW/NORMAL/HIGH/EXTREME), market_structure (TREND/RANGE/BREAKOUT/
TRANSITION), stress (NORMAL/CORRECTION/SHOCK), correlation_regime
(NORMAL/FUSED, populated by Track D at runtime; NORMAL default).

## REGIME_TRANSITIONS

PASS — `RegimeTransition` attribution records + compact labels
(TREND->RANGE, BULL->CORRECTION, NORMAL->SHOCK, STABLE).

## REGIME_PERFORMANCE_MATRIX

PASS (contract) — `classify_regime_cell` canonical statuses ELIGIBLE /
NOT_ELIGIBLE / SHADOW_ONLY / INSUFFICIENT_SAMPLE with deterministic
thresholds. No regime filtering activated in frozen POC01.

## STATIC_CORRELATION

NOT_RUNTIME_REACHABLE — re-confirmed: no static 0.85/0.55 constants exist;
`CORRELATION_CLUSTER` is a declared-but-unimplemented enum (previous audit's
DEF-CORR-001 remains REJECTED; no defect manufactured).

## DYNAMIC_CORRELATION

PASS — `portfolio/correlation.py`: aligned PIT returns (no zero-return
forward fill), causal rolling correlation (trailing windows only), thresholded
edges, causal EMA smoothing, hysteresis NORMAL/FUSED. Context/risk evidence
only — no alpha exports, no POC01 behavior change.

## CORRELATION_CAUSALITY

PASS — critical test green: modifying ALL FUTURE observations leaves every
PAST correlation state byte-identical (states and smoothed series).

## STAT_VALIDATION_GAPS

Confirmed and implemented (no duplication of Monte Carlo/walk-forward):
bootstrap Sharpe CI, P(Sharpe>0), permutation significance. Reproducible with
explicit seed.

## SHARPE_CI

PASS — percentile bootstrap, seeded, confidence-level respected, tiny-N
fails closed, zero-variance -> degenerate record (no fabricated numbers).

## PERMUTATION_TEST

PASS — sign-flip null, seeded, positive-strategy SIGNIFICANT / random-strategy
NOT_SIGNIFICANT / negative edge NOT_SIGNIFICANT, zero-variance ->
INSUFFICIENT_EVIDENCE.

## ADMISSION_INTEGRATION

PASS — `research/admission_stats.py` exposes `compute_stat_evidence` as
multi-gate evidence for the admission path (existing AdmissionController
untouched; single p-value cannot promote — proven by test; runtime wiring
deferred to keep POC01 frozen).

## POC01_RUNTIME_CHANGED

0

## POC01_PNL_CHANGED

0

## LIVE_CALLS

0

## FALSE_SUCCESS

0

## NEW_TESTS

**CORRECTED (EVIDENCE-RECONCILIATION, PORTFOLIO-AND-RUNTIME-INTEGRATION-01):**
the originally reported "58" was a transcription error. Canonical counts
verified via `pytest --collect-only`:

- TEST_FILES_ADDED: 8
- TEST_FUNCTIONS_ADDED: 72
- TEST_CASES_COLLECTED: 72
- PARAMETRIZED_CASES: 0
- TOTAL_NEW_PYTEST_ITEMS: 72

Breakdown: execution 19 (gateway_e2e 16 + conformance 3), health 13,
regime_v2 9, correlation 9, stat_validation 12, admission_stats 6,
projection 4.

## FULL_REGRESSION

**CORRECTED (EVIDENCE-RECONCILIATION):** canonical tally: COLLECTED=839,
PASSED=838, FAILED=1, SKIPPED=0, XFAILED=0, XPASSED=0, ERRORS=0.
The single failure (`test_load_settings_happy_path`, binance-vs-bybit from
local `.env` `EXCHANGE_ID=bybit`) was **reproduced on clean BASE `01f7792`
in a detached git worktree** with the same environment -> pre-existing,
environment-driven, NOT a checkpoint defect. (The earlier "837 passed"
predated staging the new modules; with them tracked, the closure guard
passes, hence 838.) POC01 validator 9/9 PASS after all changes.

## DEPENDENCY_CLOSURE

PASS — closure guard green after staging all new modules (proven twice: the
guard correctly failed on untracked modules, then passed post-staging).

## RUFF

PASS — all new/modified files clean.

## MYPY

PASS — strict clean on all new modules (execution 9 files, health, regime_v2,
correlation, stat_validation, admission_stats, health_projection).

## STATUS

PASS

## NEXT

CONTINUE_POC01 + PORTFOLIO_INTELLIGENCE_01 + STRATEGY_HEALTH_UI +
EXCHANGE_CONFORMANCE_HARDENING
