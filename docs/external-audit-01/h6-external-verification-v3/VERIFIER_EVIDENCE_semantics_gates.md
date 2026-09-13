# VERIFIER_EVIDENCE — V2→V3 Economic Drift, Contamination, H5, Skip Audit, Defect Matrix

**Audited target:** `a5487164803fb601f87f2cd4c865929c30da274e`
**Machine-readable:** `VERIFIER_EVIDENCE_semantics_gates.json`
**Script:** `verifier_semantics_gates.py` (run with `PYTHONPATH=<verifier>/src`)
All artifacts read from **Git blob bytes**, never working-tree copies.

| gate | verdict |
|---|---|
| `V2_TO_V3_ECONOMIC_SEMANTIC_DRIFT` | **FAIL** |
| `CONTROL_PLANE_V1_BINDING` | **FAIL** |
| `PERFORMANCE_CONTAMINATION` | PASS |
| `H5_IMMUTABILITY` | PASS |
| `SKIP_AUDIT` | REVIEW_REQUIRED |
| `DEFECT_REGRESSION_MATRIX_PRESENCE` | PASS |

---

## 1. `V2_TO_V3_ECONOMIC_SEMANTIC_DRIFT` — **FAIL**

Method: every one of the **24** V2 top-level economic fields was compared against the *same key* inside
`V3_SPEC["economics"]`. No hand-written key mapping was applied — a mapping would have hidden exactly
the omissions this gate exists to catch. (An earlier pass of this verifier used a hand-written map and
wrongly reported "0 absent"; that was corrected and the corrected result is below.)

| | count |
|---|---|
| V2 economic fields | 24 |
| carried **byte-identically** into `V3.economics` | **20** |
| carried with a **changed value** | **0** |
| **absent from `V3.economics`** | **4** |

The 20 carried fields are identical byte-for-byte:
`assets, common_window_utc, decision_timeframe, oi_field_whitelist, feature_transformations,
rolling_windows, threshold_rule, direction_semantics, entry_timing, exit_timing,
primary_holding_horizon, decision_spacing, cost_model, funding_accounting, minimum_N,
robustness_gates, orthogonality_gates, insufficient_sample_policy, pass_fail_semantics,
experiment_invalidation`.

**Cost model is carried unchanged**: `BASE_TOTAL_ROUND_TRIP_COST_BPS = 10`,
`COST_SENSITIVITY_BPS = [0, 10, 20, 40]` — the "10 bps TOTAL RT kept" claim in the prereg commit
message is **confirmed**. No retune of any carried parameter was found.

### The four dropped fields

| V2 field | V2 value (abridged) | relocated in V3? |
|---|---|---|
| `statistical_gates` | `{P_Sharp_greater_0_min: 0.9, permutation: "sign-flip permutation on hourly trade returns, 10,000 draws, fixed seed 20260911", permutation_p_max: 0.05, sharpe_ci_excludes_zero: true}` | **NO** |
| `pit_rules` | `{oi, price, features, future_mutation, archive_validity_role}` | **NO** (2 of 5 sub-strings appear), see below |
| `stop_invalidation` | `"NONE in the primary H6 discovery test …"` | **NO** |
| `cooldown` | `"NONE required: fixed 1h non-overlapping per-asset outcome definition …"` | **NO** |

Section 1-a: **these four keys are exactly the keys the runtime contract loader requires.**

`src/trading_bot/research/h6/frozen_contract_snapshot.py` reads `spec["…"]` for:
`assets, common_window_utc, cooldown, cost_model, decision_timeframe, direction_semantics,
entry_timing, exit_timing, feature_transformations, funding_accounting, hypothesis_id,
insufficient_sample_policy, mechanism, oi_field_whitelist, orthogonality_gates, pass_fail_semantics,
pit_rules, rolling_windows, statistical_gates, stop_invalidation, threshold_rule`.

**All four dropped fields are on that list.** A V3 economics block therefore **cannot satisfy the
runtime contract loader**: `statistical_gates`, `pit_rules`, `stop_invalidation` and `cooldown` would
each raise `KeyError`. Independently confirmed in the other direction: `load_frozen_h6_snapshot()`
executed from the verifier worktree **fails** (it resolves the V1 spec and then dies with
`FileNotFoundError: data\processed\oi_full_history\OI_FULL_HISTORY_DATASET_MANIFEST.json`).

### Why `statistical_gates` matters most

The statistical acceptance criteria are the *pass/fail* rule of the experiment:

- `P_Sharp_greater_0_min = 0.9`
- `permutation_p_max = 0.05`
- `sharpe_ci_excludes_zero = true`
- permutation: sign-flip, 10,000 draws, **fixed seed 20260911**

`gate_config.py` hard-codes `p_sharp_gt_0_min=0.90`, `permutation_p_max=0.05`,
`sharpe_ci_excludes_zero=True` — so three of the four values survive **in code**. But:

- `permutation_seed` and `permutation_draws` (seed `20260911`, 10,000 draws) are **absent from the V3
  authority AND absent from `gate_config.py`** — verified by search. The permutation test's seed and
  draw count therefore have **no live frozen authority at all**.
- Code is not the frozen authority. A future execution judged against `gate_config.py` instead of the
  frozen spec has no preregistered acceptance criterion behind it.

### On the `retune: "NONE (spec 33/34)"` and carried-hash claims

- `economics_carried_forward_unchanged_from.spec_sha256_of_carried_block` =
  `221cfa1d6eb3dae30948e9605f258075c0cd69e8f38187da4959c3e696b8b000`.
  **Independently reproduced**: it equals `sha256` of the **whole** `H6_SPEC_V2.json` blob bytes.
  The declared label says "of_carried_block"; the value is the entire V2 spec. Reproducible, but the
  label is imprecise. Not counted as drift.
- The `retune: NONE (spec 33/34)` claim implies 33 of 34 fields carried. Observed: **20 of 24**
  comparable fields carried, **4 absent**. The "33/34" accounting could not be reproduced from the
  artifacts.

---

## 2. `CONTROL_PLANE_V1_BINDING` — **FAIL** (18 bindings / 11 files)

A repo-wide scan of `src/` and `scripts/` for the V1 identity constants
(`e683e04e…`, `f514fecf…`, `345334c3…`, `oi-full-history-01`) found the H6 control plane is still
**entirely bound to V1**, while the live frozen authority is V3.

| file | binding |
|---|---|
| `src/trading_bot/research/h6/contracts.py` | `SPEC_SHA256` = V1 |
| `src/trading_bot/research/h6/feature_engine.py` | `SPEC_SHA256` = V1 |
| `src/trading_bot/research/h6/execution_harness.py` | `PREREG_COMMIT` + `SPEC_SHA256` + `MANIFEST_SHA256` = V1 |
| `src/trading_bot/research/h6/gate_config.py` | `SPEC_SHA256` + `MANIFEST_SHA256` = V1 |
| `src/trading_bot/research/h6/frozen_contract_snapshot.py` | spec path + manifest path + 2 hashes → V1 |
| `src/trading_bot/research/h6/external_verifier_report.py` | report path → `oi-full-history-01` |
| `src/trading_bot/research/h6/contamination_scan.py` | scans `oi-full-history-01` |
| `scripts/download_oi_full_history.py`, `scripts/normalize_oi_full_history.py`, `scripts/run_h6_exactly_once.py`, `scripts/verify_h6_prereg.py` | V1 output/evidence dirs |

This supersedes/extends `FIND-XART-01` (which found the same class of problem in
`execution_harness.py` only). The direction remains **fail-closed in practice** — H6 execution is
gated off and cannot load a V3 spec — but the runtime authority binding is wrong across the whole
package, and the V3 freeze did not re-point it.

---

## 3. `PERFORMANCE_CONTAMINATION` — **PASS**

- Scanned every H6-related `.json` / `.jsonl` / `.md` artifact and every H6 `.py` at the audited commit.
- Structured walk of all `RESULT` / `RUN_REPORT` JSON artifacts: **0** numeric metric keys matching
  performance vocabulary (`sharpe`, `pnl`, `cagr`, `max_drawdown`, `hit_rate`, `expectancy`, …).
- Token occurrences exist in prose/rule text (`sharpe` ×41, `expectancy` ×23, `pnl` ×18, …) but
  **never as a measured value**. These are gate definitions, e.g. `P_Sharpe_gt_0_min`,
  `H5_PNL_CORRELATION`, "sharpe_ci_excludes_zero".
- Frozen governance agrees: `H6_EXECUTIONS = 0`, `H6_BACKTESTS = 0`, `PERFORMANCE_OBSERVED = false`
  (V3 spec `governance` block and V3 manifest `governance` block both).

No hypothesis performance was observed. `H6_BACKTESTS = 0`, `H6_EXECUTIONS = 0`,
`PERFORMANCE_OBSERVED = false` are independently corroborated.

---

## 4. `H5_IMMUTABILITY` — **PASS**

`git diff --name-only 0941082 a548716 -- docs/external-audit-01/h5-orderflow-imbalance-01` →
**empty**. None of the 34 H5 artifacts present at the audited commit were touched by the V3 repair
commits. H5 evidence is immutable across the audited range.

---

## 5. `SKIP_AUDIT` — REVIEW_REQUIRED (6 markers, none currently vacuous)

Conditional skips found in the 13 scanned H6/Shadow/confirmation/PIT/OI test files:

| file | line | marker |
|---|---|---|
| `tests/unit/research/test_h6_v3_test_isolation.py` | 84 | `pytest.skip("AUTHORITY_UNREACHABLE: canonical V2 data root not found (portable resolution failed)")` |
| `tests/unit/research/test_h6_v3_test_isolation.py` | 100 | same |
| `tests/unit/research/test_oi_full_history.py` | 73 | `pytest.skip("raw sample not present on this machine")` |
| `tests/unit/research/test_oi_full_history.py` | 289 | `skipif` on V1 `H6_SPEC.json` presence |
| `tests/unit/research/test_oi_full_history.py` | 342 | `skipif` on frozen OI dataset presence |
| `tests/unit/research/test_oi_full_history.py` | 386 | `skipif` on price authority presence |

**Risk assessed and partially cleared:** `test_h6_v3_test_isolation.py` was run in the verifier
worktree (whose own `data/` tree is empty) and reported **`2 passed`** — the tests did **not** skip, so
the isolation evidence is not vacuous there. The `test_oi_full_history.py` skips remain conditional on
machine-local data presence and were not exercised in this gate; a skip there would produce a green
run that tested nothing. Carried forward as an open item, not a defect.

---

## 6. `DEFECT_REGRESSION_MATRIX_PRESENCE` — **PASS**

- Defect register `H6_V3_REPAIR_DEFECT_REGISTER.json`: 8 defect entries, ids
  `EXT-CONF-002, EXT-DASHBOARD-002, EXT-FEATURE-WHITELIST-001, EXT-HERMETIC-002,
  EXT-MANIFEST-HASH-001, EXT-PORTABLE-DATA-001, EXT-PRICE-LIMIT-001, EXT-SHADOW-002`.
- Regression matrix `H6_V3_DEFECT_REGRESSION_MATRIX.json`: 16 entries.
- **Every register id is present in the matrix** (`ids_in_register_missing_from_matrix = []`).

Presence and coverage verified here. Independently *re-running* each defect's reproduction is a
separate gate and remains open.

---

## Findings register (this batch)

| id | gate | severity | title | status |
|---|---|---|---|---|
| `FIND-DRIFT-01` | V2_TO_V3_ECONOMIC_SEMANTIC_DRIFT | **HIGH** | V3 economics drops `statistical_gates`, `pit_rules`, `stop_invalidation`, `cooldown`; all four are required by the runtime contract loader, so the V3 spec cannot satisfy it | OPEN, unrepaired |
| `FIND-DRIFT-02` | V2_TO_V3_ECONOMIC_SEMANTIC_DRIFT | **HIGH** | Permutation seed `20260911` and draw count `10,000` have **no live frozen authority** (absent from V3 spec and from `gate_config.py`) | OPEN, unrepaired |
| `FIND-DRIFT-03` | V2_TO_V3_ECONOMIC_SEMANTIC_DRIFT | LOW | `spec_sha256_of_carried_block` is actually the sha256 of the whole V2 spec, not of a block; `33/34` accounting not reproducible (20/24 observed) | OPEN, informational |
| `FIND-CTRL-01` | CONTROL_PLANE_V1_BINDING | **HIGH** | H6 runtime control plane bound to V1 across 11 files / 18 bindings while the live frozen authority is V3 | OPEN, unrepaired |

No file under `src/` was modified by this verifier.

Because `V2_TO_V3_ECONOMIC_SEMANTIC_DRIFT` and `CONTROL_PLANE_V1_BINDING` fail, the final verdict of
this audit cannot be `PASS`.
