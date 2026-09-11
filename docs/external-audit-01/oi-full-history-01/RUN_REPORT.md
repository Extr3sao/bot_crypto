# RUN REPORT — OI-FULL-HISTORY-FREEZE-01 + H6-HYPOTHESIS-SELECTION-AND-PREREG-ONLY + R2-SHADOW-CONTINUATION

2026-09-11 · buffy-agent (Freebuff) · branch `feat/ma-2-specialist-opportunity-swarm` · Machine-readable: `RUN_REPORT.json`

## Commits (P0-I two-stage freeze)

| Commit | Scope |
| --- | --- |
| `256bd5e` | **OI_FREEZE_COMMIT** — full OI archive, normalizer, causal eligibility helpers, ledger, quality, determinism evidence, whitelist |
| `e683e04` | **H6_PREREG_COMMIT** — H6_SPEC.json, H6_MANIFEST.json, selection rationale, collision review, mechanism evidence, consistency audit |
| `c6b25f4` | verification — self-verification script + result, external verifier package, post-commit record |

## Data freeze

| Item | Value |
| --- | --- |
| Files (zip + CHECKSUM) | **5,691/5,691 verified** (BTC 2,201 · ETH 1,745 · SOL 1,745), 0 checksum failures, 0 missing |
| Valid days / rows | **5,596 / 1,611,648** (95 invalid days, all classified in the validity ledger) |
| Quality | **`PASS_WITH_EXPLICIT_GAPS`** — all common-window gaps isolated single days; 0 drift, 0 invalid values |
| Common window | **2021-12-01 → 2026-09-10** frozen; 1,732/1,745 days valid for all three symbols |
| Price authority | committed frozen 1h klines cover the whole window — no extension required |
| Dataset fingerprint | **`OI_FULL_HISTORY_DATASET_SHA256 = 16779b7d…`** (cross-run A==B; synthetic mutation C≠A) |

## H6 preregistration (exactly one hypothesis)

**`H6-OI-POSITION-STOCK-01` — OI_CONFIRMED_CONTINUATION**: significant position-stock expansion (robust `z_oi ≥ +1.0`, median/1.4826·MAD over trailing 720 completed hourly changes, min 336 obs) confirms the completed decision-hour price direction and predicts continuation over the next hour. Entry next-hour OPEN, exit same-hour CLOSE, 1h horizon, **no stop, no cooldown**, expansion-only (contraction ⇒ NO_TRADE), `BASE_TOTAL_ROUND_TRIP_COST_BPS = 10` (sensitivities 0/10/20/40 diagnostic), funding `EXCLUDED_WITH_LIMITATION` + materiality gate, orthogonality `|r| ≤ 0.50` vs preregistered ROC(24h) proxy, N ≥ 30/asset and ≥ 100 pooled, gates: P(Sharpe>0) ≥ 0.90, permutation p ≤ 0.05, Sharpe CI excludes 0, halves/thirds/walk-forward.

- P0-C consistency audit: **30/30 dimensions resolved, `UNRESOLVED_FIELDS = []`**
- P0-J: no commit self-reference inside frozen artifacts; `H6_PREREG_COMMIT_RECORD.json` proves byte-immutability (`git diff` vs prereg commit EMPTY)
- **`H6_EXECUTIONS = 0` · `H6_BACKTESTS = 0` · `PERFORMANCE_OBSERVED = false`**

## Verification

| Layer | Result |
| --- | --- |
| Self-verification (Track Q) | **`H6_SELF_VERIFICATION = PASS`** — 57/57 checks (`H6_SELF_VERIFICATION.json`) |
| Independent verification (Track Q2) | **`PENDING_EXTERNAL_VERIFIER`** — package + prompt ready (`H6_EXTERNAL_VERIFIER_PACKAGE.{json,md}`, `H6_EXTERNAL_VERIFIER_PROMPT.md`); per P0-A, the builder cannot certify its own prereg |

## Governance

- Failed-memory collision review **PASS** (12 terminal families analyzed; trade-flow M-A **DEFERRED** with reasons — H5 collision + cost).
- Mechanism evidence: CME official education (OFFICIAL_EXCHANGE_DOC), corroborating reference, peer-reviewed perp-futures literature. No repository returns inspected at any point (`ALPHA_LEAKAGE = 0`).
- Causality (P0-B/H): `ARCHIVE_DAY_VALIDITY` ≠ `DECISION_ELIGIBILITY_AT_T`; adversarial tests prove future-gap-after-T invariance (PAST gap may matter, FUTURE gap never does).

## Tests

- OI freeze tests: **28/28** · data admission: **22/22** · dependency closure: PASS · H5 hash guards: PASS
- **FULL HERMETIC: 1287 passed / 0 failed / 0 skipped** (env neutralized, no exclusions)

## Tracks R/S

- **Shadow:** runtime UTC 17:56:25Z < earliest maturity 21:15Z → 11 captures, **0 mature, 0 resolved** (mature-only rule held).
- **Confirmation:** `CONF-EDGE-002-001` `consumed=false, executions=0`, closes 2026-09-22 — untouched.
- `RISK_CHANGED=0 · PAPER_PROMOTIONS=0 · LIVE_TRADING_CALLS=0 · FALSE_SUCCESS=0`

**STATUS: `PENDING_INDEPENDENT_VERIFICATION`** (all builder work complete and green; independent verifier verdict outstanding — correct governance, not a failure)
