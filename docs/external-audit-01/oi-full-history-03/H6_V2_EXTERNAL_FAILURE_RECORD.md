# H6 V2 External Failure Record

Status: **FAILED_EXTERNAL_VERIFICATION_V2 — IMMUTABLE**

V2 prereg commit: `ee58c7a5a0a46cf6af17dc9606118ef0f1fcd335`
V2 evidence package commit: `0941082fc875a66287d2b09159112963141bcf27`

| Artifact | SHA256 | Source |
|---|---|---|
| `H6_SPEC_V2.json` | `221cfa1d6eb3dae30948e9605f258075c0cd69e8f38187da4959c3e696b8b000` | `git show ee58c7a:docs/external-audit-01/oi-full-history-02/H6_SPEC_V2.json` |
| `H6_MANIFEST_V2.json` | `5f9aba446686a32b94238cd5f7285742e53c4db551f0c2135df37837ac5fcf0d` | `git show ee58c7a:docs/external-audit-01/oi-full-history-02/H6_MANIFEST_V2.json` |
| `H6_MANIFEST_V2` ledger claim | `bb2b43c27a88bf9ff334fa5adcc753f5b34976d2b4df9061de34a94507d2bd8f58752dc` (71 chars, **malformed**) | inside `H6_MANIFEST_V2.json` |
| `OI_ARCHIVE_DAY_VALIDITY_LEDGER_V2.jsonl` actual | `bb2b43c27a88bf9fe3ec22573903a61007f046ddc1256b5caa3e788cba15e714` (64 chars, correct) | `sha256sum` of ledger bytes |

## Verdict

`FINAL_VERDICT = FAIL` by Codex independent verifier at `0941082` (context `PROFITABILITY_DIAGNOSTICS_ONLY`).

## Defects (8)

1. **EXT-FEATURE-WHITELIST-001** — `H6FieldAccess({"unadmitted_metric": 7}).get("unadmitted_metric")` returns `7`; not fail-closed. — **BLOCKING_FOR_H6**.
2. **EXT-MANIFEST-HASH-001** — manifest contains 71-char ledger hash (`bb2b43c...ff334fa5adcc...` 71) differing from actual `bb2b43c...e3ec225739...` 64. — **BLOCKING_FOR_H6**.
3. **EXT-CONF-002** — `conf_lock.py` references absent `docs/external-audit-01/confirmations/CONF-EDGE-002-001.json` and does not enforce `CONFIRMATION_LEDGER_V2.jsonl`. — **BLOCKING_FOR_H6**.
4. **EXT-PORTABLE-DATA-001** — `data/raw/binance_um/metrics/` (5691) and `data/processed/oi_full_history_v2/` are gitignored; clean verifier worktree could not re-derive `DATASET_SHA`, determinism, PIT adversarial tests, test isolation. — **BLOCKING_FOR_H6** until `PORTABLE_RESEARCH_DATA_AUTHORITY_V1`.
5. **EXT-SHADOW-002** — 11 Shadow resolutions show `maturity_time == decision_time`; frozen protocol requires 48h horizon. `SHADOW_MATURITY_RECONCILIATION=FAIL`, `SHADOW_11_OF_11=REJECTED`. Correct range `2026-09-11T21:15Z..2026-09-12T11:25Z`; builder claimed `2026-09-09T21:15Z..2026-09-10T11:25Z`.
6. **EXT-HERMETIC-002** — full hermetic result `INCONCLUSIVE_TOOL_OUTPUT`; no durable `FULL_HERMETIC_RESULT.json`.
7. **EXT-DASHBOARD-002** — only 7 dashboard repeats evidenced, not 20/20.
8. **EXT-PRICE-LIMIT-001** — `PRICE_AUTHORITY=PASS`, `PRICE_CONTINUITY=PASS`, `PRICE_OVERLAP=LIMITATION_PARTIAL` (zip checksums + economic overlap not independently rederived).

## Governance

- V1 `e683e04` remains `FAILED_EXTERNAL_VERIFICATION V1` immutable.
- V2 `ee58c7a` is now `FAILED_EXTERNAL_VERIFICATION_V2` immutable — never rewritten.
- `H6_EXECUTIONS=0`, `H6_BACKTESTS=0`, `PERFORMANCE_OBSERVED=false`, `FALSE_SUCCESS=0`.

## Next

Repair all 8 proven defects into a new `H6 V3` preregistration (`H6-OI-CONFIRMED-CONTINUATION-03`) under `docs/external-audit-01/oi-full-history-03/` and prepare External Verification Round 3.
