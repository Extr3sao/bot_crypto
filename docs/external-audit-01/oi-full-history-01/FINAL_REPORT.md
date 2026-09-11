# FINAL REPORT — OI-FULL-HISTORY-FREEZE-01 + H6-HYPOTHESIS-SELECTION-AND-PREREG-ONLY

```
CHECKPOINT:
OI-FULL-HISTORY-FREEZE-01 + H6-HYPOTHESIS-SELECTION-AND-PREREG-ONLY + R2-SHADOW-CONTINUATION

OI_FULL_FILES:
5691 / 5691 (checksums 100% PASS; BTCUSDT 2201, ETHUSDT 1745, SOLUSDT 1745)

OI_FULL_ROWS:
1,611,648 (5,596 VALID days; 95 invalid days all classified in the ledger)

BTC_RANGE:
2020-09-01T00:00:00Z -> 2026-09-10T23:55:00Z

ETH_RANGE:
2021-12-01T00:00:00Z -> 2026-09-10T23:55:00Z

SOL_RANGE:
2021-12-01T00:00:00Z -> 2026-09-10T23:55:00Z

COMMON_RESEARCH_WINDOW:
2021-12-01 -> 2026-09-10 (FROZEN; USE_COMMON_WINDOW=true; 1,732/1,745 days valid across all three symbols)

OI_VALID_DAYS:
5596

OI_INVALID_DAYS:
95 (INVALID_GAP 94 + INVALID_VALUE 1; none silently dropped)

OI_SOURCE_GAPS:
0 missing dates; 95 provider-side gap days; all common-window gaps isolated single days (no multi-day runs)

OI_NATIVE_CADENCE:
5m (288 rows/complete UTC day)

OI_SCHEMA_UNIT_AUTHORITY:
sum_open_interest = BASE_ASSET_UNITS; sum_open_interest_value = USDT_NOTIONAL (OI_SCHEMA_SEMANTICS.md, schema 2.0.1; provider string create_time documented; DEF-DATA-OI-002 exact-duplicate collapse)

OI_FULL_HISTORY_DATASET_SHA256:
16779b7d2eff0dc9e56015c444c2dbe7b67ef083e6cf1877a024a6de74098d99

OI_PIT:
PASS (DECISION_ELIGIBILITY_AT_T strictly causal; 12-snapshot hour completeness; trailing-only windows)

OI_FUTURE_MUTATION:
PASS (FUTURE_SAME_DAY_GAP_MUTATION: state at T byte-identical; PAST_GAP_BEFORE_T may change eligibility; FUTURE_GAP_AFTER_T never)

ALPHA_LEAKAGE:
0

H6_SELECTED:
true

H6_MECHANISM:
OI_CONFIRMED_CONTINUATION (position-stock expansion-only conditioning; contraction => NO_TRADE)

FAILED_MEMORY_COLLISION:
PASS (12 terminal families analyzed; trade-flow M-A DEFERRED with reasons)

EXTERNAL_MECHANISM_EVIDENCE:
PASS (CME official education = OFFICIAL_EXCHANGE_DOC; corroborating reference; MDPI peer-reviewed perp-futures paper; no repository returns inspected)

H6_PREREG_COMMIT:
e683e04e5df39d0f2f5feb6097664536b93cc636 (OI_FREEZE_COMMIT 256bd5ec6b82242c0b52e70a96dcd19edda61aa7; two-stage per P0-I)

H6_SPEC_SHA256:
f514fecf42b52d2e1c2946cac9dee94b2570d485cb236b9a6c663f46f5bbf148
(H6_MANIFEST_SHA256 345334c3107860a56fcbc8b2ec04a01e70b81b09ee551a54eeaf4a566b2cb29d; H6_PREREG_CONSISTENCY: PASS, UNRESOLVED_FIELDS=[]; immutability proven via H6_PREREG_COMMIT_RECORD.json — git diff vs prereg commit EMPTY for spec and manifest)

H6_PREREG_VERIFICATION:
SELF-VERIFICATION PASS (57/57 checks); H6_INDEPENDENT_VERIFICATION = PENDING_EXTERNAL_VERIFIER

H6_EXECUTIONS:
0

H6_BACKTESTS:
0

PERFORMANCE_OBSERVED:
false

SHADOW_CAPTURES:
11

SHADOW_MATURE:
0 (runtime UTC 2026-09-11T17:56:25Z < earliest maturity 2026-09-11T21:15Z; runtime clock used, not memory)

SHADOW_RESOLVED:
0 (mature-only rule held)

CONFIRMATION_CONSUMED:
false

CONFIRMATION_EXECUTIONS:
0 (CONF-EDGE-002-001 closes 2026-09-22T00:00:00Z; untouched)

RISK_CHANGED:
0

LIVE_TRADING_CALLS:
0

FALSE_SUCCESS:
0

FULL_HERMETIC:
1287 passed / 0 failed / 0 skipped (OI freeze 28/28; data admission 22/22; no exclusions)

STATUS:
PENDING_INDEPENDENT_VERIFICATION
(all builder work complete and green; H6_INDEPENDENT_VERIFICATION requires a genuinely independent verifier per P0-A — builder self-verification does NOT qualify; FALSE_SUCCESS=0 forbids claiming PASS without it)
```

## Frozen H6 design (single canonical semantics, P0-C 30/30)

- **Mechanism:** significant position-stock **expansion** (`z_oi ≥ +1.0`, robust median / 1.4826·MAD over trailing 720 completed hourly OI changes, min 336 obs, MAD=0 ⇒ NO_SIGNAL) confirms the completed decision-hour price direction and predicts continuation over the next hour.
- **Execution:** 1h decision buckets (bucket close), entry next-hour OPEN, exit same-hour CLOSE; **no stop, no cooldown**; expansion-only (contraction ⇒ NO_TRADE).
- **Economics:** `BASE_TOTAL_ROUND_TRIP_COST_BPS = 10` (single canonical TOTAL RT; sensitivities 0/10/20/40 diagnostic; gross mandatory); funding `EXCLUDED_WITH_LIMITATION` + materiality gate before promotion; N ≥ 30/asset, ≥ 100 pooled.
- **Gates:** P(Sharpe>0) ≥ 0.90 · permutation p ≤ 0.05 · Sharpe CI excludes 0 · halves/thirds/walk-forward · `|daily corr vs preregistered ROC(24h) momentum proxy| ≤ 0.50` (H5 comparator: `NOT_EVALUABLE_FROM_PERSISTED_EVIDENCE`).
- **Causality:** `ARCHIVE_DAY_VALIDITY ≠ DECISION_ELIGIBILITY_AT_T`; a gap after T can never change eligibility or state at T (adversarially tested).

## NEXT

- `H6_INDEPENDENT_VERIFICATION = PASS` (external verifier, see `H6_EXTERNAL_VERIFIER_PROMPT.md`) ⇒ next checkpoint **`H6-INDEPENDENT-IMPLEMENTATION-AND-DISCOVERY-01`** (exactly ONE economic H6 experiment under the frozen prereg).
- Otherwise: do NOT execute H6; return the verifier's findings for repair.
- Always continue: R2 diagnostic · shadow mature-only (maturities begin 2026-09-11T21:15Z) · confirmation wait (2026-09-22T00:00Z).
