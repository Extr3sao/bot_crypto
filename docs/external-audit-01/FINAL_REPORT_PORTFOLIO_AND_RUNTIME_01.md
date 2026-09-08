# FINAL REPORT — PORTFOLIO-AND-RUNTIME-INTEGRATION-01

**BASE:** `01f7792` · **LIVE:** DISABLED · **LIVE_CALLS:** 0 · **FALSE_SUCCESS:** 0

---

## Evidence Reconciliation (Phase 0)

**PASS** — see `EVIDENCE_RECONCILIATION.md`.

- `NEW_TESTS_CANONICAL` (previous checkpoint): TEST_FILES_ADDED=8,
  TEST_FUNCTIONS_ADDED=72, TEST_CASES_COLLECTED=72, PARAMETRIZED_CASES=0,
  TOTAL_NEW_PYTEST_ITEMS=72 (reported "58" was a transcription error; ADR-0025
  and FINAL_REPORT_HARDENING_01 corrected, nothing silently changed).
- Previous FULL_REGRESSION decomposed exactly: collected=839, passed=838,
  failed=1 (pre-existing; **proven at BASE in a detached worktree** —
  environment-driven `.env` `EXCHANGE_ID=bybit`, not a checkpoint defect).

---

## Track A — Portfolio Intelligence V1: PASS

`src/trading_bot/portfolio/intelligence.py` + 20 tests.

- `PortfolioIntelligenceSnapshot`: gross/net exposure, long/short,
  exposure by asset/strategy/family/**correlation cluster** (dynamic, from
  `portfolio.correlation` — no static constants), concentrations, drawdown,
  regime binding, health summary, evidence refs.
- A1 cluster-aware exposure: physical positions ≠ effective independent risk
  count (FUSED regime merges clusters). A2 strategy correlation separated from
  asset correlation / signal overlap. A3 marginal portfolio value (evidence
  only, no auto risk decisions). A4 regime embedded. A5 read-only projection.

## Track B — StrategyRegimeEligibility: PASS

`src/trading_bot/research/regime_eligibility.py` + 12 tests.

- RE-01 identity (strategy×version×asset×timeframe×regime_signature) + metrics
  + status ELIGIBLE/NOT_ELIGIBLE/SHADOW_ONLY/INSUFFICIENT_EVIDENCE.
- RE-02 evidence binding to canonical regime dimensions. RE-03 fail-closed on
  insufficient sample. RE-04 **pre-declared fallback only** (GLOBAL class
  fallback decided before seeing results; no opportunistic merging).
  Not activated in POC01 (evidence for a future StrategyRouter).

## Track C — Execution Runtime Wiring: PASS (PARTIALLY_INTEGRATED terminologically)

`src/trading_bot/execution/service.py` (+ journal replay in `journal.py`,
recovery/gateway hardening) + 20 tests.

- EX-01/EX-03 runtime `TradeIntent` propagation, stable identity across 10
  restarted services on one durable journal. EX-02 journal mounted (CREATED →
  SUBMITTING → ACCEPTED observed; JSONL reload validated with chain checks).
- EX-04 ACK_UNKNOWN runtime E2E: adopted after venue-accept+timeout (1 order),
  controlled retry when definitively absent, BLOCK when uncertain; late/dup
  ACK idempotent. EX-05 duplicate/out-of-order fills apply exactly once.
  EX-06 startup reconciliation fail-closed (`execution_ready` requires all 5
  prerequisites). EX-07 ECONOMIC_ORDERS_PER_INTENT ≤ 1 (retry ×10, restart
  with open order, cancel ambiguity, orphan).
- C3 adapter classification: **BINANCE: PARTIALLY_INTEGRATED (CCXT wrapper, no
  primitive wiring)** · **BYBIT: PARTIALLY_INTEGRATED (CCXT wrapper, no
  primitive wiring)** · **BITUNIX: PARTIALLY_INTEGRATED (spot+futures clients,
  no primitive wiring)** · **OKX: ABSENT** · **KRAKEN: ABSENT**.
- C5 **EXECUTION_STATUS = PARTIALLY_INTEGRATED**: primitives are mounted and
  runtime-reachable through `ExecutionService` with durable restart recovery,
  but no real adapter call-site consumes them yet (deliberately: POC01 frozen,
  LIVE disabled). Not RUNTIME_CERTIFIED; not FOUNDATION_ONLY.

## Track D — Strategy Health UI contract: PASS

`src/trading_bot/paper/health_view.py` + 6 tests.

- UI-01 read-only rows (state, N, rolling/baseline expectancy & Sharpe, PF,
  DD, last transition, reason, next action). UI-02 strategy × regime matrix
  (pre-declared columns TREND/RANGE/HIGH_VOL/SHOCK). UI-03 every cell
  evidence-backed (max-N row decides; no green/red by intuition). UI-04 honest
  empty cells: `INSUFFICIENT_EVIDENCE` with `no_evidence=true`; no
  family-name inference; structurally read-only (`read_only` flags).

## Track E — POC01 Observation: PASS

`POC01_OBSERVATION_PORTFOLIO_AND_RUNTIME_01.md` (read-only snapshot:
campaign_id, day 2026-09-08, valid days 0, scans 1, selected 0, risk 0/0,
paper 0/0, PnL 0.0, provider failures 0, health OK, RESUMED).
DEF-POC01-OBS-005: observation-layer only; no campaign code modified.

## Track F — HEALTH × RISK analysis contract: PASS

`src/trading_bot/risk/reject_analysis.py` + 9 tests. Append-only ledger of
risk REJECTs with strategy/asset/regime/health/correlation context + later
shadow attachment; deterministic classification into
`GOOD_CANDIDATE_BLOCKED_BY_RISK` vs `LOW_QUALITY_CANDIDATE_CORRECTLY_BLOCKED`
(min shadow N=20, pre-declared). RiskManager untouched.

---

## Validation

| Gate | Result |
| --- | --- |
| FULL_REGRESSION | collected=897, passed=896, failed=1, skipped=0, xfailed=0, xpassed=0, errors=0 — the 1 is the pre-existing environment failure (`.env` bybit vs `binance`), reproduced at BASE `01f7792` |
| NEW_TESTS (this checkpoint) | 35 functions (service 20, health view 6, reject analysis 9), 0 parametrized |
| DEPENDENCY_CLOSURE | PASS (guard green with staged modules) |
| RUFF | CLEAN (all checkpoint files) |
| MYPY | CLEAN (all checkpoint modules) |
| POC01 validator | 9/9 PASS |
| POC01_RUNTIME_CHANGED | 0 |
| POC01_PNL_CHANGED | 0 |
| POC01_TRADE_COUNT_CHANGED | 0 |
| LIVE_CALLS | 0 |
| FALSE_SUCCESS | 0 |

## STATUS: PASS

## NEXT
CONTINUE_POC01 + SHADOW_NEXT_CAMPAIGN_INTEGRATION + LEGACY_STRATEGY_RETRO_VALIDATION + FUTURE_CONFIRMATION_WAIT
