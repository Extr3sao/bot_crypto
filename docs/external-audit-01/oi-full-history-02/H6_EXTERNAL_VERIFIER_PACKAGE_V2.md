# H6 EXTERNAL VERIFIER PACKAGE V2 — Track Q2 (Round 2)

**Purpose:** enable a genuinely independent verifier (different agent/model/session, no builder role) to certify the **new clean preregistration V2** `H6-OI-CONFIRMED-CONTINUATION-02`. The builder (`buffy-agent (Freebuff)`) cannot certify its own prereg: `H6_SELF_VERIFICATION_V2 = PASS` is **self**-verification only. Until an external verdict arrives, checkpoint status is `PENDING_EXTERNAL_REVERIFICATION` (correct governance, not a failure).

Old round-1 prereg `e683e04` is **FAILED_EXTERNAL_VERIFICATION** and immutable — never rewritten.

## Key identities

| Artifact | Value |
|---|---|
| **H6_PREREG_COMMIT_V2** | `ee58c7a5a0a46cf6af17dc9606118ef0f1fcd335` |
| **OI_DATA_FREEZE_V2_COMMIT** | `3f2e9c7715db0dedf51a63d71bac1a3f65a87605` |
| **PRICE_AUTHORITY_COMMIT** | `440d7e55f7efeb7838aab30cb0e17bb86f437b53` |
| **H6_SPEC_V2 SHA256** | `221cfa1d6eb3dae30948e9605f258075c0cd69e8f38187da4959c3e696b8b000` |
| **H6_MANIFEST_V2 SHA256** | `5f9aba446686a32b94238cd5f7285742e53c4db551f0c2135df37837ac5fcf0d` |
| **OI_DATASET_SHA256_V2** | `16779b7d2eff0dc9e56015c444c2dbe7b67ef083e6cf1877a024a6de74098d99` |
| **PRICE_AUTHORITY_SHA256_V2** | `e1c2462a6aa9ba0c921154d259a28c49be1e2fc58a544dbd97af8ecabef52168` |
| **H6_EXECUTIONS / H6_BACKTESTS / PERFORMANCE_OBSERVED** | `0 / 0 / false` |

Ancestry is linear: `3f2e9c7 → 440d7e5 → ee58c7a`. Verify against `ee58c7a` (or a descendant whose `git diff ee58c7a -- <V2 prereg artifact>` is EMPTY for every V2 artifact below).

## Contents (all hashes from **Git object bytes**, not worktree)

| File | Git derivation |
|---|---|
| `H6_SPEC_V2.json` | `git show ee58c7a:docs/external-audit-01/oi-full-history-02/H6_SPEC_V2.json \| sha256sum` → `221cfa1d…b000` |
| `H6_MANIFEST_V2.json` | `git show ee58c7a:…/H6_MANIFEST_V2.json \| sha256sum` → `5f9aba44…cf0d` |
| `H6_SELECTION_RATIONALE_V2.md` | `git show ee58c7a:…/H6_SELECTION_RATIONALE_V2.md \| sha256sum` → `25aba49b…1dff` |
| `H6_FAILED_MEMORY_COLLISION_REVIEW_V2.md` | `git show ee58c7a:…/H6_FAILED_MEMORY_COLLISION_REVIEW_V2.md \| sha256sum` → `1a4f134e…84a` |
| `H6_MECHANISM_EVIDENCE_V2.md` | `git show ee58c7a:…/H6_MECHANISM_EVIDENCE_V2.md \| sha256sum` → `803549ce…77f5` |
| `H6_FEATURE_AUTHORITY_WHITELIST_V2.json` | `git show ee58c7a:…/H6_FEATURE_AUTHORITY_WHITELIST_V2.json \| sha256sum` → `e5383fa6…f450` |
| `H6_PREREG_CONSISTENCY_AUDIT_V2.json` | `git show ee58c7a:…/H6_PREREG_CONSISTENCY_AUDIT_V2.json \| sha256sum` → `1780649e…5286` (verdict PASS, CONTRADICTIONS_FOUND=0) |
| `H6_PREREG_COMMIT_RECORD_V2.json` | post-commit evidence (outside prereg); carries commit identity, tree/parent/timestamp, all SHAs recomputed from git objects |
| `OI_FULL_HISTORY_DATASET_MANIFEST_V2.json` | `24160d1c…32ac` (tracked at 3f2e9c7/ee58c7a ancestry) |
| `OI_ARCHIVE_DAY_VALIDITY_LEDGER_V2.jsonl` | `bb2b43c2…15e714` line-count 5691 (FORENSIC ONLY) |
| `PRICE_1H_AUTHORITY_V2_MANIFEST.json` | `c7726cc1…c75f18c1e2` (committed at 440d7e5) |
| `BTC/ETH/SOLUSDT_1h_v2.jsonl` | frozen 1h klines 2021-12-01..2026-09-10 (440d7e5) |
| `H6_EXTERNAL_VERIFIER_PACKAGE_V2.json` | machine-readable inputs: exact paths, SHAs, 8 defects to re-verify, test commands, forbidden outcomes, verdict schema |
| `H6_EXTERNAL_VERIFIER_PROMPT_V2.md` | ready-to-run verifier instructions (copy into independent agent) |

## Regression you must attack (all 8 prior defects)

1. **EXT-DATA-001** — dataset fingerprint mismatch + BTCUSDT 2024-06-05 bytes/ledger disagreement. Recompute fingerprint; verify `bcd3d849…fb7` bytes; check determinism A==B / C!=A; verify guard `TEST_DATASET_WRITE_FORBIDDEN`.
2. **EXT-PRICE-001** — missing 47 hours. Verify manifest shows 0 missing, 41880 expected, `covers_common_window=true`, no conflict on overlap.
3. **EXT-PIT-001** — `valid_days_for` future leak + vacuous harness. Verify `oi_dataset_v2.py` causal reader (`record_time <= T`) and non-vacuous PIT suite 12/12.
4. **EXT-CONS-001** — eight contradictions. Verify `h6_v2_consistency_audit.py` → 60/60 PASS.
5. **EXT-CONS-002** — package manifest SHA wrong. Verify all SHAs from Git objects, not worktree; `git diff ee58c7a -- H6_SPEC_V2.json` empty.
6. **EXT-CONS-004** — `z>=1` alone allowed contraction. Verify raw-sign rule `delta>0 AND z>=1`, MAD==0 NO_TRADE, regression case.
7. **EXT-CONF-001** — confirmation ledger missing. Verify `NOT_INDEPENDENTLY_PROVEN` pre-ledger + forward append-only `CONFIRMATION_LEDGER_V2.jsonl` LOCK_CHECK.
8. **FULL-HERMETIC-001** — `test_non_get_methods_are_405` timeout. Verify server fix + 20/20 repetition + full hermetic `FAILED=0`.

## Verifier checklist (summary)

1. recompute every SHA from `git show ee58c7a:<path>` and compare to `H6_PREREG_COMMIT_RECORD_V2.json`; both `git diff ee58c7a -- H6_SPEC_V2.json` and `…H6_MANIFEST_V2.json` EMPTY
2. recompute OI dataset fingerprint → `16779b7d…` and BTC 2024-06-05 bytes → `bcd3d849…fb7`
3. run `scripts/h6_v2_consistency_audit.py` → PASS 60/60
4. verify canonical semantics (expansion-only `delta>0 & z>=1`, 1h next-open→close, NONE stop/cooldown, 10 bps TOTAL RT, funding EXCLUDED_WITH_LIMITATION + gate, orthogonality 0.50, median/1.4826·MAD, 30d/336, causal PIT)
5. verify counters zero and no realized-performance fields
6. run focused tests (PIT 12, OI 28, audit) + 20× flake + full hermetic
7. verify H5 immutability `2427310d…fe60f` / `29ececb7…0a86`
8. return mandatory verdict JSON (`FINAL_VERDICT`: PASS | FAIL | BLOCKED_INSUFFICIENT_EVIDENCE)

Only `FINAL_VERDICT = PASS` allows `H6_INDEPENDENT_VERIFICATION_V2 = PASS` and opens `H6-INDEPENDENT-IMPLEMENTATION-AND-DISCOVERY-01`. Until then `H6_EXECUTION_ENABLED=false`, `H6_EXECUTIONS=0`, `PERFORMANCE_OBSERVED=false`.
