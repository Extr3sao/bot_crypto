# H5 ORTHOGONALITY RECONCILIATION — DEF-H5-ORTHO-001

Checkpoint: H5-RESULT-INTEGRITY-RECONCILIATION-02 · Date: 2026-09-11
**H5 NOT rerun. No trades regenerated. `H5_RESULT.json` byte-identical (sha256 `2427310d...`, ledger-anchored).**

Status: **CORRECTED_PEARSON_R_DERIVED_FROM_PERSISTED_OUTPUTS**

## 1. Trace of the invalid observation (61.9157)

| Item | Value |
| --- | --- |
| Field | `H5_RESULT.json → orthogonality_vs_roc_proxy → daily_pnl_correlation = 61.91569544528234` |
| Module | `scripts/h5_run_exactly_once.py` |
| Function | `compute_orthogonality_diagnostics(...)` → inner `daily_r` + manual Pearson block (lines ~180–235) |
| Input arrays | daily-aggregated `net_r` sums for H5 trades and ROC(24) proxy trades on common exit days |
| Date alignment | `day = exit_ts // 86_400_000`; `common = sorted(set(d1) & set(d2))`; `len(common) = 102` (persisted in result) |
| Normalization | **DEFECT** — numerator `np.sum((xs-mx)*(ys-my))` is a raw SUM; denominator `np.std(xs)*np.std(ys)` is population-std product |

## 2. Root cause (proven, not assumed)

The buggy quantity is algebraically

```
sum((x-mx)*(y-my)) / (std(x)*std(y)) = n · Pearson_r
```

because `Pearson_r = sum((x-mx)*(y-my)) / (n · std(x) · std(y))`.

Independent verifier evidence (`evidence/PEARSON_VERIFIER_SELFTEST.json`):

- `buggy_formula_is_n_times_pearson: true` (n=5 → exactly 5.0)
- buggy form reproduces out-of-range values (`buggy_formula_value = 4.9999…` for r=1, n=5)
- proper-Pearson invariants PASS with tolerance 1e-12: r(X,X)=1, r(X,−X)=−1,
  constant series guarded (None), −1 ≤ r ≤ 1, scale invariance
- classification: **STD_NORMALIZATION_ERROR** (missing 1/n on the covariance term),
  matching the classification pre-registered in DEF_H5_ORTHO_001_INVALID_PEARSON_CORRELATION.md

## 3. Corrected value — exact algebraic inversion from persisted outputs

Both inputs required by the inversion are persisted immutable outputs of the frozen,
ledger-anchored `H5_RESULT.json`:

```
CORRECTED_PEARSON_R = published_invalid_value / common_days
                    = 61.91569544528234 / 102
                    = 0.6070166220125719
```

- `0.6070166220125719 ∈ [−1, 1]` ✓
- The inversion is deterministic and parameter-free: the buggy code multiplies the true
  Pearson r of exactly the same 102 aligned daily pairs by n = 102 (the array length it
  operates on). Dividing by 102 recovers r exactly.
- Consistency: any valid n must satisfy `published/n ≤ 1` → n ≥ 62; the persisted
  `common_days = 102` satisfies this with margin.

## 4. Corrected orthogonality block (diagnostic, NOT a rerun)

| Field | Published (invalid) | Corrected |
| --- | --- | --- |
| daily_pnl_correlation | 61.91569544528234 | **0.6070166220125719** |
| common_days | 102 | 102 (unchanged) |
| trade_time_overlap | 0.9158878504672897 | 0.9158878504672897 (unchanged) |
| redundant (frozen rule: overlap>0.6 AND corr>0.7) | true (via invalid corr) | **false** (0.607 < 0.7) |

Interpretation: H5 daily PnL is moderately correlated (~0.61) with the ROC(24) momentum
proxy, and 91.6% of H5 entries occur within ±3 bars of a proxy entry. H5 is *not*
independent of existing momentum exposure by the trade-overlap criterion, even though the
corrected correlation alone no longer trips the frozen 0.7 redundancy threshold.

## 5. Evidence constraint honored

Per-day PnL series were NOT persisted as a standalone artifact, so a from-scratch
recomputation over raw arrays is impossible without regeneration (forbidden). The
correction above uses only persisted immutable outputs plus the code-identity proof of
the defect. This is exact, not an estimate.

## 6. Required outcome

- `CORRECTED_PEARSON_R = 0.6070166220125719` with invariant checks satisfied ✓
- `H5_ORTHOGONALITY = CORRECTED (0.607, derived from persisted outputs)`
- Final H5 classification remains **DISCOVERY_FAIL** (see TRACK_D — failure is carried by
  P(Sharpe>0), permutation p, halves/thirds, walk-forward; orthogonality cannot promote).
