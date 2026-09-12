# RUN_REPORT — H6-PREREG-REPAIR-01 + OI-DATASET-REFREEZE-02 + PRICE/CONFIRMATION REPAIR

```
CHECKPOINT:
H6-PREREG-REPAIR-01 + OI-DATASET-REFREEZE-02 + PRICE-AUTHORITY-REPAIR-01 + PIT-CAUSALITY-REPAIR-01 + CONFIRMATION-AUTHORITY-REPAIR-01

OLD_H6_PREREG V1:
e683e04e5df39d0f2f5feb6097664536b93cc636 = FAILED_EXTERNAL_VERIFICATION IMMUTABLE (8 defects proven by independent Codex verifier 2026-09-12; preserved in H6_PREREG_V1_EXTERNAL_FAILURE_RECORD.json)
OLD OI FREEZE V1:
256bd5ec6b82242c0b52e70a96dcd19edda61aa7
SPEC V1 SHA: f514fecf42b52d2e1c2946cac9dee94b2570d485cb236b9a6c663f46f5bbf148
MANIFEST V1 SHA: 345334c3107860a5adcc753f5b34976d2b4df9061de34a94507d2bd8f58752dc
OI declared 16779b7d... vs actual 5e2a10f7... mismatch + 47h price gap + PIT future leak + 8 contradictions + wrong package hash + z>=1 allows contraction + no ledger + hermetic 1 timeout

OI_DATA_FREEZE_V2_COMMIT:
3f2e9c7715db0dedf51a63d71bac1a3f65a87605
PRICE_AUTHORITY_COMMIT:
440d7e55f7efeb7838aab30cb0e17bb86f437b53
H6_PREREG_COMMIT_V2:
ee58c7a5a0a46cf6af17dc9606118ef0f1fcd335

H6_SPEC_SHA256_V2:
221cfa1d6eb3dae30948e9605f258075c0cd69e8f38187da4959c3e696b8b000  (git show ee58c7a:<H6_SPEC_V2.json> bytes)
H6_MANIFEST_SHA256_V2:
5f9aba446686a32b94238cd5f7285742e53c4db551f0c2135df37837ac5fcf0d

OI_FULL_HISTORY_DATASET_SHA256_V2:
16779b7d2eff0dc9e56015c444c2dbe7b67ef083e6cf1877a024a6de74098d99
OI_MANIFEST_SHA256: 24160d1c8eb42dc6feaaddabed469916898f27814c34d567b5533e54f15532ac
OI_LEDGER_SHA256:   bb2b43c27a88bf9fe3ec22573903a61007f046ddc1256b5caa3e788cba15e714 (5691 lines, VALID 5596 / invalid 95)
OI_DETERMINISM:     A==B per-file + global PASS; C!=A sensitivity PASS (representative 7-day A/B + global)
OI_RAW_AUTHORITY:   5691 official Binance metrics archives (BTC 2201 ETH 1745 SOL 1745) checksum-verified
BTC 2024-06-05:     clean bytes sha bcd3d849... (not 6a30f5... contaminated 100.0 temp-path payload); determinism proves non-contamination
PIT_CAUSALITY_V2:   PASS — oi_state_at causal (record_time <= T), forensic ledger only, non-vacuous 12/12 adversarial suite
PRICE_AUTHORITY_SHA256_V2:
e1c2462a6aa9ba0c921154d259a28c49be1e2fc58a544dbd97af8ecabef52168
PRICE_EXPECTED_HOURS: 41880 per asset (2021-12-01T00:00Z..2026-09-10T23:00Z)
PRICE_MISSING_HOURS: 0 BTCUSDT / 0 ETHUSDT / 0 SOLUSDT (47 missing repaired from official klines_1h_ext, overlap PASS)
PRICE_V2_SHARDS:    BTC 58680 ETH 58680 SOL 52505 rows; h1 58633/58633/52458; common coverage true

H6_IDENTITY_V2:
H6-OI-CONFIRMED-CONTINUATION-02 spec_version 2
H6_MECHANISM_V2:
OI_CONFIRMED_CONTINUATION — delta_oi>0 AND z>=1.0 (median/1.4826*MAD 30d trailing 720h min336) + price direction; else NO_TRADE; MAD==0 => NO_TRADE
H6_HOLDING:         exactly next 1h (open->close)  STOP:NONE  COOLDOWN:NONE  spacing ONE DECISION PER COMPLETED ASSET-HOUR
H6_COST:            10 bps TOTAL RT (sensitivities 0/10/20/40 diagnostic, gross required)
H6_FUNDING:         EXCLUDED_WITH_LIMITATION + FUNDING_MATERIALITY_GATE_BEFORE_PROMOTION=true (carry-funding-deep-01 audited)
H6_CONSISTENCY:     PASS — h6_v2_consistency_audit.py 60/60 CONTRADICTIONS_FOUND=0 UNRESOLVED=[]
H6_EXECUTIONS:      0
H6_BACKTESTS:       0
PERFORMANCE_OBSERVED: false  (no PnL/Sharpe/PF/future-return inspected; only contracts/data/authority/consistency/tests)
FALSE_SUCCESS:      0

CONFIRMATION_AUTHORITY:
CONF-EDGE-002-001 pre-ledger NOT_INDEPENDENTLY_PROVEN (LIMITATION_EXPLICIT, honest); forward ledger CONFIRMATION_LEDGER_V2.jsonl append-only LOCK_CHECK 2026-09-12 until 2026-09-22 consumed=false executions=0
CONFIRMATION_CONSUMED: false
CONFIRMATION_EXECUTIONS: 0 (locked until 2026-09-22T00:00:00Z)
SHADOW:             11 total / 11 mature (earliest 2026-09-09T21:15Z latest 2026-09-10T11:25Z) / 11 resolved append-only, INSPECTED but SHADOW_ONLY/COUNTERFACTUAL (EXCLUDED_FROM_PAPER_PNL/FREQUENCY); mature-only resolution respected; no Risk change; SHADOW_POLICY=INSUFFICIENT_SAMPLE (N=11 small, gathering only)
H5_STATE:           H5 DISCOVERY_FAIL RERUNS 0 — untouched; H5_RESULT 2427310d... H5_MANIFEST 29ececb7... H5_SPEC c743fba4... verified
H5_RERUNS:          0

FOCUSED_TESTS:
- tests/unit/research/test_oi_full_history.py: 28 passed
- tests/unit/research/test_oi_full_history_v2_pit.py: 12 passed (non-vacuous A-G)
- scripts/h6_v2_consistency_audit.py: PASS 60/60
- scripts/verify_h6_prereg + H6_SELF_VERIFICATION_V2 32/32 PASS
- whitelist / sign-rule / cost / funding / ledger paths exercised within above

DASHBOARD_FLAKE_REPETITION:
20/20 PASS isolated (test_non_get_methods_are_405) after fix (timeout 2s, drain, join)
FULL_HERMETIC:
1299 passed 78 warnings 0 failed — proven TWICE (108s and 134s); no hidden skips; OI 28 + PIT 12 included

VERIFICATION:
BUILDER_SELF_VERIFICATION_V2: PASS (32/32, H6_SELF_VERIFICATION_V2.json; H6_INDEPENDENT_VERIFICATION = PENDING_EXTERNAL_VERIFIER — builder cannot certify itself)
EXTERNAL_VERIFICATION_V1:     FAIL (historical, at e683e04; 8 defects preserved)
EXTERNAL_VERIFICATION_V2:     PENDING — package at docs/external-audit-01/oi-full-history-02/H6_EXTERNAL_VERIFIER_PACKAGE_V2.{json,md} + H6_EXTERNAL_VERIFIER_PROMPT_V2.md

RISK_CHANGED:       0
PAPER_PROMOTIONS:   0
LIVE_CALLS:        0

STATUS:
PENDING_EXTERNAL_REVERIFICATION
(builder-side: OI_DATA_FREEZE_V2 PASS, PRICE_AUTHORITY_V2 PASS, PIT_CAUSALITY_V2 PASS, H6_PREREG_CONSISTENCY_V2 PASS, H6_SELF_VERIFICATION_V2 PASS, FULL_HERMETIC PASS; external V2 pending second independent verification)

NEXT_GATE:
External Verification Round 2 with V2 package
  → PASS: H6-INDEPENDENT-IMPLEMENTATION-AND-DISCOVERY-01 (exactly ONE economic H6 experiment under frozen V2 prereg)
  → FAIL: repair only newly proven defects (do NOT execute H6)
  → until then: H6_EXECUTION_ENABLED=false, no backtest, continue R2 diagnostics / shadow mature-only / confirmation wait
```

## Defects repaired this checkpoint

| Defect | Status |
|---|---|
| EXT-DATA-001 | PASS — isolated V2 root, normalizer guard, 5691 rebuild, bcd3d8 clean bytes, determinism A==B C!=A |
| EXT-PRICE-001 | PASS — 47 hours repaired, MISSING 0, overlap PASS |
| EXT-PIT-001 | PASS — causal reader, non-vacuous 12/12 |
| EXT-CONS-001 | PASS — 60/60 zero contradictions |
| EXT-CONS-002 | PASS — package from Git objects |
| EXT-CONS-004 | PASS — delta>0 & z>=1 + MAD==0 guard |
| EXT-CONF-001 | LIMITATION_EXPLICIT_FORWARD_ENFORCEMENT — pre-ledger not proven; forward ledger locked until 2026-09-22 |
| FULL-HERMETIC-001 | PASS — 20/20 + 1299/0 ×2 |

## Artifacts produced

- `EXT_DATA_001_FORENSIC_REPORT.{md,json}` — BTC 2024-06-05 root cause (test pollution via default out_dir)
- `OI_FULL_HISTORY_DATASET_MANIFEST_V2.json` + `OI_ARCHIVE_DAY_VALIDITY_LEDGER_V2.jsonl` (5691) — V2 dataset
- `OI_DATASET_V2_DETERMINISM_REPORT.{md,json}` — A==B / C!=A
- `src/trading_bot/research/oi_dataset_v2.py` — causal reader
- `tests/unit/research/test_oi_full_history_v2_pit.py` — non-vacuous A–G
- `PRICE_1H_AUTHORITY_V2_MANIFEST.json` + `BTC/ETH/SOLUSDT_1h_v2.jsonl` + `PRICE_AUTHORITY_V2_REPORT.{md,json}`
- `H6_SPEC_V2.json` / `H6_MANIFEST_V2.json` + `H6_*V2.md` + `H6_FEATURE_AUTHORITY_WHITELIST_V2.json`
- `H6_PREREG_CONSISTENCY_AUDIT_V2.{md,json}` — 60/60
- `H6_PREREG_V1_EXTERNAL_FAILURE_RECORD.json` + `H6_PREREG_REPAIR_DEFECT_REGISTER.{md,json}` + `H6_EXTERNAL_DEFECT_REGRESSION_MATRIX_V2.json`
- `CONFIRMATION_AUTHORITY_REPORT_V2.{md,json}` + `CONFIRMATION_LEDGER_V2.jsonl`
- `server.py` teardown fix (timeout, drain, join)
- `H6_SELF_VERIFICATION_V2.json` — 32/32 PASS
- `H6_EXTERNAL_VERIFIER_PACKAGE_V2.{json,md}` + `H6_EXTERNAL_VERIFIER_PROMPT_V2.md` — for independent round-2 verifier
