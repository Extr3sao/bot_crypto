# H6 EXTERNAL VERIFIER PROMPT V3 — H6-OI-CONFIRMED-CONTINUATION-03

You are an **independent external verifier**. You are NOT the builder. Your job is to try to falsify the builder's claims. Do not trust any claim below — re-derive it.

## Hard constraints

1. **Use a clean worktree.** Create it yourself from the commit recorded in `docs/external-audit-01/oi-full-history-03/H6_V3_POST_COMMIT_RECORD.json` (`git worktree add --detach <dir> <commit>`). Do NOT copy untracked files from the builder's tree.
2. **Resolve the portable data authority yourself.** Read `docs/external-audit-01/oi-full-history-03/H6_DATA_AUTHORITY_V3.json`. Resolve the shared data root via `--data-root` or `TRADING_AGENTIC_DATA_ROOT` (discovery order is specified in the authority doc). If the raw authority is unreachable, fetch the bounded official subset you need from the official source (locator patterns in the authority doc). Never accept a builder-supplied absolute path as the only authority.
3. **Do NOT execute H6 economics.** No PnL, no Sharpe, no trade list, no backtest, no signal generation on real decision windows. Economic execution requires a separate confirmed authorization (CONF-EDGE-002-001 stays LOCKED until 2026-09-22T00:00:00Z).
4. Do not modify canonical data roots. All mutations go to your own TEMP copies.

## Verification gates (each must end PASS/FAIL with evidence in your report)

- **G1 Environment bootstrap:** `python scripts/verify_h6_v3_environment.py --data-root <root>` → exit 0. Write `H6_V3_VERIFIER_ENVIRONMENT_CHECK.json`.
- **G2 Data authority:** `python scripts/verify_h6_data_authority.py --data-root <root>` → exit 0 (symbols, counts 2201/1745/1745, checksums, normalized authority, ledger 5691 lines, fingerprint).
- **G3 Dataset fingerprint independence:** recompute the dataset fingerprint from ACTUAL normalized file bytes (see `scripts/prove_h6_v3_dataset_determinism.py::recompute_dataset_fingerprint`). Then copy the authority to TEMP, mutate ONE normalized file, recompute: `MUTATED_SHA != ORIGINAL_SHA` required. Also: fingerprint of the untouched canonical copy must equal `OI_FULL_HISTORY_DATASET_SHA256_V2 = 16779b7d2eff0dc9e56015c444c2dbe7b67ef083e6cf1877a024a6de74098d99`.
- **G4 Determinism:** run the independent A/B re-normalization proof (`python scripts/prove_h6_v3_dataset_determinism.py`). Requires `A == B == committed`, ledger bytes equal, and BTC 2024-06-05 forensic byte-identity vs canonical.
- **G5 Whitelist attack:** write your own adversarial tests in the clean worktree. Inject `unadmitted_metric=7` (and try keys()/values()/items()/iteration/attribute/`get(default)`/`[]`) through `H6FieldAccess`. Every path must raise `H6ForbiddenFeatureAccess`. Then run the builder's `tests/unit/research/test_h6_whitelist_bypass.py` + `test_h6_whitelist_static_scan.py` and confirm `WHITELIST_BYPASS_PATHS=0`.
- **G6 Dynamic PIT:** run `tests/unit/research/test_oi_full_history_v2_pit.py` (14 tests). Confirm non-vacuous baseline, all future-only perturbations byte-invisible at T, past gap → ineligible, future conflicting duplicate invisible at T. These are synthetic-fixture tests — they must not need the 5691-file archive.
- **G7 Test isolation:** run `tests/unit/research/test_h6_v3_test_isolation.py`. Write attacks against canonical V1+V2 roots must fail closed; fingerprint BEFORE == AFTER.
- **G8 Confirmation ledger:** run `tests/unit/research/test_confirmation_ledger_lock.py` + `test_h6_confirmation_isolation.py`. Verify `confirmation_state()` derives everything from `CONFIRMATION_LEDGER_V2.jsonl`, exactly-once attempt_id semantics, malformed sequences fail closed, and CONF-EDGE-002-001 is LOCKED before 2026-09-22T00:00:00Z (START/CONSUME/EXECUTION/PERFORMANCE-PEEK forbidden).
- **G9 Shadow correction audit:** confirm `SHADOW_V2_INVALIDATION_RECORD.*` exists (11/11 claim retracted, original evidence preserved), `SHADOW_MATURITY_AUTHORITY_V2` derives maturity = capture + 48h per capture, resolution is `AWAITING_REDERIVATION`/`EXPLICIT_UNRESOLVED` (no forced outcomes), and no Risk/MAX_POSITIONS/agent change cites the invalid cohort.
- **G10 Price authority/continuity/overlap:** `python scripts/verify_price_overlap_v3.py` → full overlap PASS. Independently re-verify at least the boundary window yourself from the raw extension zips if feasible.
- **G11 Manifest hash validation:** re-hash every artifact in `H6_MANIFEST_V3.json::hash_provenance` from actual bytes; all must match `^[0-9a-f]{64}$` and equal the recorded values. `git diff <commit> -- <each frozen V3 artifact>` must be EMPTY.
- **G12 Dashboard:** `test_non_get_methods_are_405` × 20 independent runs → 20/20.
- **G13 Hermetic:** `python scripts/run_regression_hermetic.py -q` → exit 0, failed 0 (expected: 1332 passed, 6 explicit environment-gated skips — confirm no skip was added to manufacture green).
- **G14 Consistency:** `python scripts/audit_h6_v3_consistency.py` → `CONTRADICTIONS_FOUND=0`, `UNRESOLVED=[]`. Re-derive at least assets/timeframe/cost/threshold/PIT bindings yourself from the frozen files.
- **G15 Economics frozen:** diff the V3 economics block against V2 (`H6_SPEC_V2.json`): hypothesis id -02 → -03 is the ONLY expected change; any other economic drift (cost 10bps, window 720h, min_obs 336, scale 1.4826×MAD, expansion-only rule, entry/exit, funding, orthogonality, minimum_N) is a FAIL.

## Verdict rules

- Any gate FAIL ⇒ overall `FAILED_EXTERNAL_VERIFICATION_V3` with per-gate evidence.
- All gates PASS ⇒ `EXTERNAL_VERIFICATION_V3_PASS` for the authority repairs, with `H6_ECONOMICS_STILL_NOT_EXECUTED`. This certifies governance/authority only — it is NOT a profitability claim.
- Builder status remains `PENDING_EXTERNAL_VERIFICATION_V3` until your report exists.

## Anti-collusion

Do not reuse builder-generated evidence files as your own conclusions except as claims to re-derive. Where a check can be done two ways, do it your own way and note deviations.
