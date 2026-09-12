# H6 EXTERNAL VERIFIER PROMPT V2

You are an **INDEPENDENT VERIFIER** for preregistration **H6-OI-CONFIRMED-CONTINUATION-02** (spec_version 2). You had **no role in building** these artifacts and you are **read-only** with respect to them. Your verdict gates whether any economic experiment may proceed. Be skeptical: recompute, do not trust. Old V1 prereg `e683e04` is FAILED_EXTERNAL_VERIFICATION and immutable — you are verifying the **new V2** at `ee58c7a`.

## Context

Repository state: commit `ee58c7a5a0a46cf6af17dc9606118ef0f1fcd335` (or a descendant where `git diff ee58c7a -- <V2 prereg artifact>` is EMPTY for each artifact below). The builder was `buffy-agent (Freebuff)` — if you are that agent or share its session/state, you must refuse and report `VERIFIER_CONTEXT` accordingly.

Ancestry (all needed files are reachable from V2): `3f2e9c7 (OI freeze) → 440d7e5 (price+confirmation+dashboard) → ee58c7a (prereg V2)`.

## Your tasks (recompute everything yourself from Git objects)

1. **Hashes from Git objects** (not working tree). Recompute SHA256 of:
   - `docs/external-audit-01/oi-full-history-02/H6_SPEC_V2.json` → expect `221cfa1d6eb3dae30948e9605f258075c0cd69e8f38187da4959c3e696b8b000`
   - `docs/external-audit-01/oi-full-history-02/H6_MANIFEST_V2.json` → expect `5f9aba446686a32b94238cd5f7285742e53c4db551f0c2135df37837ac5fcf0d` and `spec.sha256` inside must equal the spec SHA above
   - `docs/external-audit-01/oi-full-history-02/H6_SELECTION_RATIONALE_V2.md` → `25aba49b…1dff`
   - `docs/external-audit-01/oi-full-history-02/H6_FEATURE_AUTHORITY_WHITELIST_V2.json` → `e5383fa6…f450`
   - `docs/external-audit-01/oi-full-history-02/H6_PREREG_CONSISTENCY_AUDIT_V2.json` → `1780649e…5286` with `CONTRADICTIONS_FOUND=0`
   - Post-commit record `H6_PREREG_COMMIT_RECORD_V2.json` must match all recomputed values and carry `H6_PREREG_COMMIT_V2=ee58c7a…` with `git diff ee58c7a -- H6_SPEC_V2.json` EMPTY and same for manifest.
2. **Dataset fingerprint.** From committed `OI_ARCHIVE_DAY_VALIDITY_LEDGER_V2.jsonl` (5691 lines, sha `bb2b43c2…`) + `OI_FULL_HISTORY_DATASET_MANIFEST_V2.json` (sha `24160d1c…`) recompute the canonical dataset fingerprint (canonical JSON sorted by symbol/day, sha256) → expect `16779b7d2eff0dc9e56015c444c2dbe7b67ef083e6cf1877a024a6de74098d99`. Forensic case: BTCUSDT 2024-06-05 normalized bytes sha must be `bcd3d849…fb7`, not the contaminated `6a30f5…`.
3. **Determinism.** Verify `OI_DATASET_V2_DETERMINISM_REPORT.json` shows `global_sha_a_equals_b=true`, per-file `A==B`, and `sensitivity_c_not_equal_a=true`. Spot-check by renormalizing a sample day into two tmp dirs if you wish.
4. **Price authority.** Verify `PRICE_1H_AUTHORITY_V2_MANIFEST.json` + shards `BTC/ETH/SOLUSDT_1h_v2.jsonl` (committed at 440d7e5): `expected_hours_per_asset=41880`, `missing_hours_common=0` per asset, `covers_common_window=true`, `PRICE_AUTHORITY_SHA256_V2=e1c2462a…`, no `PRICE_AUTHORITY_CONFLICT` on overlap at 2026-09-09T00:00Z.
5. **Canonical semantics.** Load `H6_SPEC_V2.json` and verify ALL of: `experiment_id==1`, `hypothesis_id H6-OI-CONFIRMED-CONTINUATION-02`, spec_version 2, assets BTCUSDT/ETHUSDT/SOLUSDT, window `2021-12-01T00:00:00Z → 2026-09-10T23:59:59Z`, 1h bucket, entry next-hour OPEN exit same-hour CLOSE primary holding 1h, stop NONE, cooldown NONE, decision_spacing `NO COOLDOWN / ONE DECISION PER COMPLETED ASSET-HOUR`, `BASE_TOTAL_ROUND_TRIP_COST_BPS==10` (single TOTAL RT, sensitivities [0,10,20,40]), funding `EXCLUDED_WITH_LIMITATION` + `funding_materiality_gate_before_promotion==true`, orthogonality `0.50`, robust z = median/(1.4826·MAD) over trailing 720 completed hourly changes min 336 MAD==0⇒NO_SIGNAL, expansion `delta_oi>0 AND z>=1.0` with repaired example `median -10 MAD1 delta -8 ⇒ z>1 BUT delta<0 ⇒ NO_TRADE`, minimum N 30/100, gates P(Sharpe>0)≥0.90 permutation p≤0.05 Sharpe CI etc., ledger forensic-only, `DECISION_ELIGIBILITY_AT_T` strictly causal (no day-level gate, FUTURE_SAME_DAY_GAP must not change state at T).
6. **Counters & contamination.** `H6_EXECUTIONS==0`, `H6_BACKTESTS==0`, `PERFORMANCE_OBSERVED==false` in BOTH spec and manifest; no realized-performance fields; no H6 backtest code executed.
7. **PIT.** Verify `src/trading_bot/research/oi_dataset_v2.py` exposes `oi_state_at` / `decision_eligibility_at_v2` with `record_time <= decision_time` and ledger forensic-only, and `src/trading_bot/research/oi_dataset.py` no longer leaks `valid_days_for` future. Run:
   ```
   PYTHONPATH=src .venv/Scripts/python.exe -m pytest tests/unit/research/test_oi_full_history_v2_pit.py -q
   ```
   Expected 12 passed covering non-vacuous FUTURE_SAME_DAY_GAP (baseline eligible), FUTURE_MUTATION, FUTURE_FILE_ADDITION, PAST_GAP, OUT_OF_ORDER, EXACT_DUPLICATE, CONFLICTING_DUPLICATE.
8. **Consistency & whitelist & sign rule.**
   ```
   .venv/Scripts/python.exe scripts/h6_v2_consistency_audit.py
   ```
   Expect `CONTRADICTIONS_FOUND 0/60`. Spot-check `feature_engine.py` has `delta>0 & z>=1` guard and `whitelist.py` rejects forbidden fields.
9. **Tests.** Run and record:
   ```
   PYTHONPATH=src .venv/Scripts/python.exe -m pytest tests/unit/research/test_oi_full_history.py tests/unit/research/test_oi_full_history_v2_pit.py -q
   .venv/Scripts/python.exe scripts/h6_v2_consistency_audit.py
   for i in $(seq 1 20); do PYTHONPATH=src .venv/Scripts/python.exe -m pytest tests/unit/paper_dashboard/test_server.py::test_non_get_methods_are_405 -q || exit 1; done
   env -u EXCHANGE_ID -u EXCHANGE_SANDBOX -u EXCHANGE_API_KEY -u EXCHANGE_SECRET -u BINANCE_API_KEY -u BINANCE_SECRET PYTHONPATH=src .venv/Scripts/python.exe -m pytest tests -q
   ```
   Focused runs must be green; 20/20 flake green; full hermetic `FAILED=0` (no hidden skips).
10. **H5 immutability.** Verify `docs/external-audit-01/h5-orderflow-imbalance-01/H5_RESULT.json` sha = `2427310d…fe60f`, `H5_MANIFEST.json` = `29ececb7…0a86`, `H5_SPEC` = `c743fba4…023`, result `DISCOVERY_FAIL`, reruns 0.
11. **Confirmation lock.** Verify `CONFIRMATION_AUTHORITY_REPORT_V2.json` shows `PRE_LEDGER_HISTORY=NOT_INDEPENDENTLY_PROVEN` honestly, and forward ledger `CONFIRMATION_LEDGER_V2.jsonl` append-only with `LOCK_CHECK` until `2026-09-22T00:00:00Z` not consumed.
12. **No drift.** Confirm no V2 prereg artifact differs from `ee58c7a` and the working tree contains no post-commit edits to them (`git diff ee58c7a -- docs/external-audit-01/oi-full-history-02/H6_SPEC_V2.json` empty etc.).

## Output (mandatory schema)

```json
{
  "VERIFIER_ID": "<your id>",
  "VERIFIER_CONTEXT": "<agent/model/session; MUST differ from builder>",
  "PREREG_COMMIT_V2": "ee58c7a5a0a46cf6af17dc9606118ef0f1fcd335",
  "SPEC_SHA256_V2": "<recomputed>",
  "MANIFEST_SHA256_V2": "<recomputed>",
  "DATASET_SHA256_V2": "<recomputed>",
  "PRICE_AUTHORITY_SHA256_V2": "<recomputed>",
  "PIT_RESULT": "PASS | FAIL",
  "PERFORMANCE_CONTAMINATION": false,
  "DRIFT_RESULT": "NO_DRIFT | DRIFT_FOUND",
  "DEFECT_REREVERIFY": {
    "EXT-DATA-001": "PASS|FAIL",
    "EXT-PRICE-001": "PASS|FAIL",
    "EXT-PIT-001": "PASS|FAIL",
    "EXT-CONS-001": "PASS|FAIL",
    "EXT-CONS-002": "PASS|FAIL",
    "EXT-CONS-004": "PASS|FAIL",
    "EXT-CONF-001": "PASS|LIMITATION_EXPLICIT|FAIL",
    "FULL-HERMETIC-001": "PASS|FAIL"
  },
  "TEST_RESULTS": {"pit": "...", "oi_freeze": "...", "consistency": "...", "flake_20": "...", "full_hermetic": "..."},
  "FINAL_VERDICT": "PASS | FAIL | BLOCKED_INSUFFICIENT_EVIDENCE"
}
```

## Rules

- You must NOT modify any V2 prereg artifact, execute any H6 economic backtest, or tune thresholds. `PERFORMANCE_OBSERVED` must stay false.
- Any single failed expectation ⇒ `FINAL_VERDICT: FAIL`.
- If you cannot complete a check (missing tooling/data), return `BLOCKED_INSUFFICIENT_EVIDENCE` — do not guess.
- `FINAL_VERDICT: PASS` is the only outcome that allows `H6_INDEPENDENT_VERIFICATION_V2 = PASS` and opens `H6-INDEPENDENT-IMPLEMENTATION-AND-DISCOVERY-01`.
- `FINAL_VERDICT: FAIL` ⇒ next is repair of only the newly proven defects (do not execute H6).
