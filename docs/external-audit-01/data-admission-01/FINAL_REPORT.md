# FINAL REPORT — ALPHA-DATA-ADMISSION-01

```
CHECKPOINT:
ALPHA-DATA-ADMISSION-01

PREVIOUS_CHECKPOINT_STATUS_CORRECTED:
REPAIR_REQUIRED  (prior "PASS with 1235/2" was not PASS under FALSE_SUCCESS=0; root-caused, repaired and re-proven in this checkpoint)

BASELINE_COMMIT:
cb3de4f2e03d5ff51f2fdfb557af5392e29dd0dc

HERMETIC_FIX_COMMIT:
692286b

DATA_ADMISSION_COMMIT:
ec2483ff78d6ab39bf59e48cf5c609f68dba4804

SETTINGS_TEST_ROOT_CAUSE:
HOST_ENVIRONMENT_CONTAMINATION
(host EXCHANGE_ID=bybit overrode the Binance fixture through flat env aliases; test made hermetic; 26/26 under unset/binance/bybit/garbage)

DEPENDENCY_CLOSURE_ROOT_CAUSE:
UNTRACKED_IMPORTED_H5_SOURCE
(src/trading_bot/research/h5_orderflow.py imported but not git-tracked; guard was CORRECT — not a test-ordering artifact; fixed by tracking the H5 code family in 692286b; guard not weakened)

FINAL_HERMETIC:
1259 passed / 0 failed / 0 skipped @ ec2483f (no exclusions, no skips)

H5_RESULT:
DISCOVERY_FAIL

H5_EXECUTED_SOURCE_TEXT_AUTHORITY:
INCOMPLETE (executed .py not recovered byte-exact; current source edited 39 s AFTER execution)

H5_EXECUTED_FORMULA_AUTHORITY:
PROVEN_FROM_COMPILED_ARTIFACT — execution-era pyc (compiled 22:56:52Z, pre-execution) preserves executed bytecode: hand-rolled sum/std form ≡ n × Pearson_r; no np.corrcoef

H5_EXECUTED_PYC_SHA256:
28adcf70059df3cfbbbd9f93bd9fe336cab8972611cb6ebfe737bf35385ef3f8

H5_DERIVED_PEARSON:
0.6070166220125719  (= 61.91569544528234 / 102)

H5_DERIVED_PEARSON_CLASS:
NOT_INDEPENDENT_RAW_RECOMPUTATION (input arrays never persisted; exact algebraic inversion of the published statistic; usable as forensic reconciliation evidence only)

H5_RESULT_SHA256_UNCHANGED:
true  (2427310dbed8445b1e39b1feaba7a8289918ab79a258f66b065da7cf2b7fe60f)

H5_SPEC_SHA256_UNCHANGED:
true  (c743fba4a2a589dc1c3a15c7cd48b1b6ddf80255b8a157ea4f7ef19cc2f81023)

H5_MANIFEST_SHA256_UNCHANGED:
true  (29ececb759aff059282a0324b3b94b4bcd13b35b51060c6c742f2eaa48db0a86; git diff vs c426b35 EMPTY)

TRADE_FLOW_SAMPLE_FILES:
21

TRADE_FLOW_SAMPLE_ROWS:
16269514

TRADE_FLOW_SAMPLE_RANGE:
2026-09-01/2026-09-07

TRADE_FLOW_CHECKSUM:
PASS (21/21 official .CHECKSUM sha256)

TRADE_FLOW_COVERAGE:
BTCUSDT 2019-12-31→2026-09-10 · ETHUSDT 2019-12-31→2026-09-10 · SOLUSDT 2020-09-14→2026-09-10; 0 missing files; ~101 GB compressed full backfill → COST_REVIEW_REQUIRED

TRADE_FLOW_ADMISSION:
ADMIT_WITH_LIMITATIONS

OPEN_INTEREST_SAMPLE_FILES:
21

OPEN_INTEREST_SAMPLE_ROWS:
6048

OPEN_INTEREST_NATIVE_CADENCE:
5m (DEF-DATA-OI-001 corrected from 15m)

OPEN_INTEREST_EXPECTED_ROWS_PER_COMPLETE_DAY:
288

OPEN_INTEREST_CHECKSUM:
PASS (21/21 official .CHECKSUM sha256)

OPEN_INTEREST_COVERAGE:
BTCUSDT 2020-09-01→2026-09-10 · ETHUSDT 2021-12-01→2026-09-10 · SOLUSDT 2021-12-01→2026-09-10; 0 missing files; REST_HISTORY_LIMIT ≈ 30 days (empirically verified, error -1130); full archive ≈ 66 MB

OPEN_INTEREST_ADMISSION:
ADMIT

DATA_ADMISSION_TESTS:
22 passed / 0 failed (plus settings matrix 26/26 ×4 environments, dependency guard 3/3)

FINGERPRINT_DETERMINISM:
PASS (A==B across independent full-sample runs 42/42; one-record perturbation C≠A; input-order independence D==A)

ALPHA_LEAKAGE:
0

ADMITTED_DATA_FAMILIES:
2  (TRADE_FLOW: ADMIT_WITH_LIMITATIONS · OPEN_INTEREST: ADMIT)

H6_CREATED:
false

SHADOW_CAPTURES:
11

SHADOW_MATURE:
0 (earliest maturity 2026-09-11T21:15Z > checkpoint activity window; mature-only rule enforced)

SHADOW_RESOLVED:
0

CONFIRMATION_CONSUMED:
false

CONFIRMATION_EXECUTIONS:
0  (CONF-EDGE-002-001 closes 2026-09-22T00:00Z; untouched)

RISK_CHANGED:
0

PAPER_PROMOTIONS:
0

LIVE_TRADING_CALLS:
0

FALSE_SUCCESS:
0

STATUS:
PASS
```

## NEXT

Both data families admitted (≥ 1), therefore per protocol:

- **DO NOT execute H6.** Next checkpoint: **`H6-HYPOTHESIS-SELECTION-AND-PREREG-ONLY`** (`H6_EXECUTIONS = 0`).
- Candidate economic mechanisms enabled specifically by the newly admitted data, failed-memory collision analysis, expected frequency, cost hurdle, PIT feasibility and orthogonality against failed mechanisms are drafted in `NEXT_CHECKPOINT_PROPOSAL.md` (same directory).
- Plus: `CONTINUE_R2_DIAGNOSTIC` · `MATURE_SHADOW` (from 2026-09-11T21:15Z, mature-only) · `CONFIRMATION_WAIT` (until 2026-09-22T00:00Z).

## Evidence index

`docs/external-audit-01/data-admission-01/`: DATA_SOURCE_REGISTRY.json · DATA_SOURCE_AUTHORITY_REPORT.{md,json} · DATA_ARCHIVE_COVERAGE_MATRIX.{md,json} · TRADE_FLOW_DATA_ADMISSION_REPORT.{md,json} · OPEN_INTEREST_DATA_ADMISSION_REPORT.{md,json} · TRADE_FLOW_DATASET_MANIFEST.json · OPEN_INTEREST_DATASET_MANIFEST.json · TRADE_FLOW_DATA_QUALITY_REPORT.{md,json} · OPEN_INTEREST_DATA_QUALITY_REPORT.{md,json} · FINGERPRINT_DETERMINISM_REPORT.json · OI_CADENCE_RECONCILIATION.{md,json} · RUN_REPORT.{md,json} · NEXT_CHECKPOINT_PROPOSAL.md
`docs/external-audit-01/`: HERMETIC_BASELINE_RECONCILIATION.{md,json} · SHADOW_AND_CONFIRMATION_STATUS.json (in data-admission-01)
`docs/external-audit-01/h5-orderflow-imbalance-01/`: H5_ORTHOGONALITY_AUTHORITY_FINAL.{md,json} (+ prior-checkpoint evidence, untouched)
