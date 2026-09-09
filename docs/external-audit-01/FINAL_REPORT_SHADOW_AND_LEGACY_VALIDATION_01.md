# FINAL REPORT — SHADOW-AND-LEGACY-VALIDATION-01

BASE: `e07352d` · LIVE: DISABLED · LIVE_CALLS: 0 · FALSE_SUCCESS: 0

## Executive status: PASS

| Field | Result |
| --- | --- |
| POC01_STATUS | DOWN at checkpoint time (heartbeat 2026-09-08T17:12:49Z, 12.7h stale; no listener on 876x). Durable state intact and resumable under existing contract. **No restart performed.** |
| POC01_CAMPAIGN_ID | `POC-01-paper-observation-01` (identity stable) |
| POC01_CONTINUITY | **PASS (structural)** — resume path deterministic; no new campaign; run/decision lineage preserved; candidate IDs unique; artifacts **byte-identical** before/after checkpoint (sha256 manifest diff = empty) |
| POC01_DOWNTIME | ≥ 45,756 s (12.7 h) — classified **MATERIAL_OBSERVATION_GAP**, NOT day-invalidating (D1 closed before gap; D2 never eligible) |
| D1_FINALIZED | **true** (2026-09-07; burn-in 2026-09-06 excluded; verifier VERIFIED ×1, NO_TRADE ×1) |
| D1_VALID | **true** (observation integrity; trades_day=0 → contributes 0 to COMPLETED_VALID_DAYS; not alpha) |
| D1_TRADES / D1_PNL | 0 / 0.0 |
| D1_RISK_REASONS | n/a (risk_accepts=0, risk_rejects=0) |
| COMPLETED_VALID_DAYS | **0** |
| CURRENT_PARTIAL_DAY | 2026-09-08 — PARTIAL_DAY, excluded from all KPIs |
| API_8766 | **FAIL — API_SERVICE_DOWN** (connection refused; service code not in repo) |
| FRONTEND_8767 | **FAIL — UI_SERVICE_DOWN** (connection refused) |
| SHADOW_NEXT_CAMPAIGN | **PASS** — `shadow/` package (capture → outcome → metrics), zero imports from POC01 runtime (grep-verified) |
| SHADOW_CAPTURE | **PASS** — deterministic `shadow_candidate_id` (economic identity only), immutable canonical labels (SHADOW_ONLY / COUNTERFACTUAL / EXCLUDED_FROM_PAPER_PNL / EXCLUDED_FROM_PAPER_FREQUENCY), append-only JSONL ledger, full B1 field set incl. refs, fingerprints, regime/health/correlation context |
| SHADOW_ACCOUNTING_ISOLATED | **PASS** — PIT outcome engine (strictly post-decision bars; adverse-first intrabar; append-after-resolution stable); separate `ShadowOutcomeLedger` store; **PaperBroker calls from shadow: 0**; no Risk/Portfolio/campaign mutation |
| HEALTH×REGIME×RISK attribution (SH-07) | **PASS** — per-reason metrics with strategy/regime/health-state distributions; GOOD_CANDIDATE_BLOCKED vs LOW_QUALITY_CANDIDATE_CORRECTLY_BLOCKED classification with fail-closed INSUFFICIENT_EVIDENCE |
| LEGACY_RETRO_PROTOCOL | **PASS** — C1 protocol frozen with SHA-256 fingerprint (sensitivity-tested); walk-forward, purged CV, temporal holdout declared ex-ante |
| LEGACY_STRATEGIES_INCLUDED | 5 (momentum, trend, breakout, mean_reversion, volatility) |
| RETRO_EXECUTIONS | 30-cell matrix executed via harness in tests (synthetic PIT series) — mechanics proven; **real-data executions: 0** (historical data provisioning pending; harness + protocol ready) |
| REGIME_CELLS_VALIDATED | Cell classes exercised (VALIDATED / FAILED / INSUFFICIENT_SAMPLE / NOT_APPLICABLE); declared-fallback legal + labeled; opportunistic merge rejected |
| HEALTH_BASELINES_CREATED | 0 real (mechanism proven; requires real VALIDATED cells — no baseline manufactured from POC01 partials) |
| EXECUTION_ADAPTER_WIRING | **PASS** — `GatewayDrivenVenue` binds REAL `CCXTExchangeConnector` through the certified gateway path; additive `fetch_order_query` / `fetch_recent_fills` on the CCXT base (inherited by all concrete adapters); cancel returns canonical state (never assumed confirmed) |
| BINANCE | **PARTIALLY_INTEGRATED → runtime-tested**: full conformance suite PASSES through the real connector code path with simulated transport (no network, no real orders) |
| BYBIT | PARTIALLY_INTEGRATED — inherits additive surface (same CCXT base); independent E2E not exercised this checkpoint |
| BITUNIX | NOT_COMPATIBLE_WITH_CCXT_BINDING — standalone client stack; requires its own VenuePort binding (recorded, not claimed) |
| OKX / KRAKEN | ABSENT (no adapters exist; not claimed) |
| EXCHANGE_CONFORMANCE | **PASS** — `ExchangeAdapterConformanceSuite` green over the real-connector binding (identity, metadata, account, positions, orders, fills, submit, query, cancel, ambiguity, reconnect, reconciliation inputs, staleness) |
| ECONOMIC_ORDERS_PER_INTENT | **≤ 1** — same intent retried → same cloid → ONE venue order; ACK-lost → adopt; pre-accept failure → ABSENT → controlled retry (1 order); query failure → BLOCK |
| STRATEGY_LAB_INTAKE | **PASS** — ExternalStrategyIdea → StrategyCandidate with frozen spec fingerprint; REJECTED_DUPLICATE / REJECTED_NO_REGIME_HYPOTHESIS / REJECTED_INCOMPLETE_SPEC fail-closed gates |
| NEW_STRATEGY_IDEAS | 0 submitted (contract + categories ready; orthogonality + regime-first enforced; no quantity padding) |
| CONFIRMATION_EXECUTIONS | **0** |
| CONFIRMATION_CONSUMED | **false** — manifest verified immutable at commit `39578a6` (window 2026-09-08→2026-09-22, `consumed:false`, manifest_sha256 `db4ad2c3…`); no working-tree mutable copy exists |
| HOST_REGRESSION | 946 passed / 1 failed (`test_load_settings_happy_path` — host exports `EXCHANGE_ID=bybit`; pydantic-settings honors real env over file defaults; repo default is NOT wrong) |
| HERMETIC_REGRESSION | **947 passed / 0 failed — exit 0 (GOV-05 MET)** via `scripts/run_regression_hermetic.py` (strips EXCHANGE_/POC01_/CAMPAIGN_/TRADING_ env prefixes; TZ=UTC) |
| NEW_TESTS | 4 files · 50 functions · 0 parametrized · 50 collected items (shadow 20, adapter binding 8, legacy retro 14, lab intake 8) — 897 + 50 = 947 reconciled |
| FULL_REGRESSION (hermetic) | collected=947, passed=947, failed=0, skipped=0, xfailed=0, xpassed=0, errors=0 |
| DEPENDENCY_CLOSURE | PASS (closure guard green after staging) |
| RUFF / MYPY | CLEAN / CLEAN (17 source files in scope) |
| POC01_RUNTIME_CHANGED | 0 |
| POC01_PNL_CHANGED | 0 |
| POC01_TRADE_COUNT_CHANGED | 0 |
| LIVE_CALLS | 0 |
| FALSE_SUCCESS | 0 |
| STATUS | **PASS** |

## Acceptance matrix

- **POC-01..05**: campaign identity stable, D1 finalized, burn-in excluded, partial day excluded ✅
- **SH-01..07**: capture, immutable records, PIT outcomes, separate ledger, no PaperBroker, no Risk mutation, attribution ✅
- **LV-01..06**: preregistered protocol, 5 strategies, PIT safety, modern stats (bootstrap CI + P>0 + permutation composed — no single-gate certification), regime-conditioned evidence, no POC01 behavior changes ✅ (real-data runs pending, recorded)
- **EX-01..08**: Binance real-call-path wiring (simulated transport), Bybit classified, Bitunix classified, reusable conformance suite, ACK_UNKNOWN, duplicate fill, restart, economic orders ≤1 ✅
- **RS-01..03**: intake contract, orthogonality requirement, regime-first hypotheses ✅
- **GOV-01..05**: POC01 unchanged (byte-identical), confirmation unconsumed, LIVE 0, FALSE_SUCCESS 0, hermetic regression evidence ✅

## Track A detail — continuity certification

See `POC01_CONTINUITY_CERTIFICATION.md`. Key facts: campaign_id equality
proven structurally (deterministic ID derivation + durable-state reload);
D1 finalized with full field set; D2 recorded as PARTIAL_DAY; API/UI down
classified as distinct operational facts; runtime DOWN ≠ campaign state
corruption — durable state intact, resume contract proven, restart not
performed per checkpoint rules.

## Next

CONTINUE_POC01 · POST_POC01_ANALYSIS · SHADOW_CAMPAIGN_V2 · CONFIRMATION_WAIT
