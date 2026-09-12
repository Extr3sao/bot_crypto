# H6 V3 Repair Defect Register

Builder worktree: `.worktrees/h6-v3-repair` (`repair/h6-v3-repair`) base `0941082`
Failed V2 prereg: `ee58c7a` → `FAILED_EXTERNAL_VERIFICATION_V2`
New V3 identity: `H6-OI-CONFIRMED-CONTINUATION-03` (`docs/external-audit-01/oi-full-history-03/`, spec_version 3)

| Defect | Claim | Root cause | Repair | Status |
|---|---|---|---|---|
| **EXT-FEATURE-WHITELIST-001** | `H6FieldAccess` fail-closed | permissive passthrough for non-whitelisted `.get`/subscript; leakage via iter/views | harden `whitelist.py` to whitelist-closed gate on all accessors; `H6ForbiddenFeatureAccess` for `FIELD_NOT_ADMITTED` | IN_PROGRESS |
| **EXT-MANIFEST-HASH-001** | ledger hash must be 64 hex matching ledger bytes | manual 71-char `bb2b43c..ff334fa5adcc...` (prefix 16 совпадает, suffix diverges); no `validate_sha256` | `hash_validator.py` + programmatic `hashlib.sha256(bytes)` derivation for every hash; malformed fails construction | IN_PROGRESS |
| **EXT-CONF-002** | `conf_lock` must enforce `CONFIRMATION_LEDGER_V2.jsonl` | pointed at absent `docs/external-audit-01/confirmations/CONF-EDGE-002-001.json` | ledger-backed lock: reducer from `CONFIRMATION_LEDGER_V2.jsonl` events; `LOCKED until 2026-09-22T00:00Z` with exactly-once; `PRE_LEDGER_HISTORY=NOT_INDEPENDENTLY_PROVEN` honest | IN_PROGRESS |
| **EXT-PORTABLE-DATA-001** | clean verifier must reconstruct dataset | `data/raw/*` + `data/processed/*` gitignored; authority only on builder filesystem | `PORTABLE_RESEARCH_DATA_AUTHORITY_V1`: `H6_DATA_AUTHORITY_V3.json` locator + `verify_h6_data_authority.py` + shared read-only mount contract + clean-worktree smoke proof | IN_PROGRESS |
| **EXT-SHADOW-002** | 11 resolutions invalid (48h horizon violated) | `maturity_time == decision_time` (zero horizon) instead of `+48h` | `SHADOW_V2_INVALIDATION_RECORD` (11/11 → INVALIDATED) + superseding `SHADOW_RESOLUTION_LEDGER_V2` with correct `capture+48h` horizon; `H6_SHADOW_ISOLATION_REPORT=NONE` | IN_PROGRESS |
| **EXT-HERMETIC-002** | full hermetic must be durable | no `FULL_HERMETIC_RESULT.json` → `INCONCLUSIVE` | `run_regression_hermetic.py` durable harness always writes `FULL_HERMETIC_RESULT.json` + second run | IN_PROGRESS |
| **EXT-DASHBOARD-002** | 20/20 dashboard repeats | only 7 evidenced | `run_dashboard_repeat_20.py` → `DASHBOARD_REPEAT_20_RESULT.json` 20/20 PASS | IN_PROGRESS |
| **EXT-PRICE-LIMIT-001** | overlap `LIMITATION_PARTIAL` adjudicate | zip checksum + economic overlap not rederived | `PRICE_OVERLAP_V3_REPORT` re-derives zip checksum + byte equality at `2026-09-09T00:00Z` per asset → `PASS` or `LIMITATION_EXPLICIT_NON_BLOCKING` | IN_PROGRESS |

> All economics unchanged until new prereg V3 passes self-verification and external independent verification.
> `H6_EXECUTIONS=0`, `H6_BACKTESTS=0`, `PERFORMANCE_OBSERVED=false` maintained.
