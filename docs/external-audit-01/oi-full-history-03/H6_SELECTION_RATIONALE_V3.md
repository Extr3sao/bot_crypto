# H6 SELECTION RATIONALE V3 — H6-OI-CONFIRMED-CONTINUATION-03

Checkpoint: `H6-V3-REPAIR-PREREG` · 2026-09-12 · **prereg-only: `H6_EXECUTIONS=0`, `H6_BACKTESTS=0`, `PERFORMANCE_OBSERVED=false`**

## Decision

**Selected: exactly one hypothesis — `H6-OI-CONFIRMED-CONTINUATION-03`** (OI_CONFIRMED_CONTINUATION: position-stock conditioning on 1h decision buckets; BTCUSDT/ETHUSDT/SOLUSDT; common window 2021-12-01 → 2026-09-10; expansion-only mechanism — contraction yields NO_TRADE).

## What changed V2 → V3 (governance only; economics untouched)

| Area | V2 defect (external verifier) | V3 repair |
|---|---|---|
| Feature whitelist | `H6FieldAccess({"unadmitted_metric": 7})` accessed `.get()`/`[]` of unadmitted fields | Fail-closed accessor on ALL paths (`[]`, `.get()`, `.get(default)`, `keys/values/items`, iteration, `in`, attribute, `len`); `H6ForbiddenFeatureAccess`; `WHITELIST_BYPASS_PATHS=0` adversarially tested |
| Manifest hashes | 71-char malformed OI ledger hash (manual copy-paste root cause) | All hashes generated programmatically from actual bytes; strict `^[0-9a-f]{64}$` validator; generation aborts before serialization on any invalid hash |
| Data authority portability | Clean worktree could not access raw OI authority, normalized authority, price authority | `H6_DATA_AUTHORITY_V3.json` + portable resolution (`--data-root` → `TRADING_AGENTIC_DATA_ROOT` → shared main-repo root → bounded official retrieval); runtime reader resolves the same chain; large data stays external-but-addressable |
| Dataset fingerprint | Committed to ledger claims, not actual file bytes | Fingerprint recomputation derives per-file hashes from ACTUAL canonical bytes; adversarial mutation test: `MUTATED_SHA != ORIGINAL_SHA` proven |
| Determinism | Not proven from clean context | Independent full A/B re-normalization from official raw sidecar-checked files: `A == B == committed`; ledger bytes equal |
| BTC 2024-06-05 | Contamination case | Official checksum verified; re-normalization byte-identical to canonical V2 file |
| Test isolation | Not proven | Write attacks against V1+V2 canonical roots FAIL CLOSED on every resolvable authority root; fingerprint BEFORE == AFTER |
| Dynamic PIT | Only `PASS_STATIC` | Synthetic-fixture dynamic suite: future gap/mutation/file-addition/conflicting-duplicate all invisible at T (byte-invariance incl. feature state + history window + signal input); past gap <T → ineligible; `NON_VACUOUS_BASELINE=PASS` |
| Confirmation authority | `conf_lock.py` referenced absent file; no ledger enforcement | `confirmation_state()` reducer derives all state from `CONFIRMATION_LEDGER_V2.jsonl`; missing/invalid ledger fails closed; exactly-once attempt_id semantics |
| Shadow | Invalid 11/11 claim; maturity==capture bug | Claim invalidated and preserved (`SHADOW_V2_INVALIDATION_RECORD`); correct 48h maturity authority; resolution explicitly `AWAITING_REDERIVATION`/`EXPLICIT_UNRESOLVED` — no forced outcomes |
| Price overlap | `LIMITATION_PARTIAL` (single-timestamp check) | Full overlap verification: 169,724 shared rows across 3 assets, 0 mismatches, 0 tail gaps → `PRICE_OVERLAP=PASS` |
| Dashboard flake | EXT-DASHBOARD-002 | `test_non_get_methods_are_405` 20/20 independent runs, durable record |

## Why this mechanism (unchanged from V2 — decision basis is not re-derived)

1. **New information axis, not a retry.** Open interest (position stock) appears in none of the 12 terminal failed families; collision review V3 re-verified → `VERDICT=PASS`.
2. **Ex-ante mechanism evidence at official tier** (CME education material E-1; corroborated by E-2/E-3) — no profitability claim is made.
3. **Cost structure is design-compatible.** `BASE_TOTAL_ROUND_TRIP_COST_BPS=10` TOTAL RT (sensitivities 0/10/20/40 diagnostic-only; gross reporting mandatory) — carried unchanged per spec 33/34; the separate execution-realism workstream (6aea4a3, frozen, NOT MERGED) is future promotion evidence only and must not retune discovery.
4. **Thresholds frozen, no sweep.** Trailing 30d/720h window, `min_observations=336`, center=median, scale=1.4826×MAD, expansion-only `delta_oi > 0 AND robust_z_oi >= 1.0`, MAD==0 ⇒ NO_TRADE. No alternative parameterizations were evaluated on returns — `PERFORMANCE_OBSERVED=false`.

## Falsifiability (unchanged)

PASS requires ALL of: N minimums (per-asset 30, pooled 100; `INSUFFICIENT_SAMPLE` is FAIL-class), net expectancy > 0 at 10 bps TOTAL RT, `P(Sharpe>0) ≥ 0.90`, permutation `p ≤ 0.05`, Sharpe CI excluding 0, halves+thirds+walk-forward consistent, `|daily corr vs ROC(24h) momentum proxy| ≤ 0.50`, funding `EXCLUDED_WITH_LIMITATION` + `funding_materiality_gate_before_promotion=true`. Any unmet gate ⇒ terminal `DISCOVERY_FAIL` in failed-memory register.

## Isolation guarantees

- `H6_SHADOW_DATA_DEPENDENCY = NONE` (Shadow outcomes feed nothing in V3 hypothesis/features/threshold/assets/cost).
- `H6_CONFIRMATION_DATA/RESULT/PERFORMANCE_DEPENDENCY = NONE`.
- `PRE_LEDGER_CONFIRMATION_HISTORY = NOT_INDEPENDENTLY_PROVEN` → `LIMITATION_EXPLICIT_NON_BLOCKING` (V3 decisions depend on no prior confirmation results).

## Status

`PENDING_EXTERNAL_VERIFICATION_V3` — supersession of V2 (`FAILED_EXTERNAL_VERIFICATION_V2`) occurs only after independent external verification in a clean worktree.
