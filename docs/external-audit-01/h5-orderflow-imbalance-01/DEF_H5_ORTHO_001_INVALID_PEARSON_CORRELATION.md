# DEF-H5-ORTHO-001 — INVALID_PEARSON_CORRELATION

Status: **CONFIRMED**

## Invalid observation

- Field: `H5_RESULT.json → orthogonality_vs_roc_proxy → daily_pnl_correlation`
- Observed value: `61.91569544528234`
- Invariant violated: `-1 <= r <= 1`
- Redundancy flag in same block: `true`
- Common days reported: `102`
- Trade-time overlap reported: `0.9158878504672897`

## Source location

- Module: `scripts/h5_run_exactly_once.py`
- Function: `compute_orthogonality_diagnostics(...)`
- Code family in that file: manual Pearson using `np.sum((xs-mx)*(ys-my))` divided by `np.std(xs)*np.std(ys)`

## Root cause classification

- Category: `STD_NORMALIZATION_ERROR`
- Detail: numerator and denominator were built from different normalizations. The covariance term was accumulated as an unnormalized sum around the means, while the denominator used default `np.std`, which is population standard deviation. That combination is not constrained to the `[-1,1]` range and is not a correct Pearson correlation.

## Note on the published frozen result block

The same `H5_RESULT.json` block already contains `daily_pnl_correlation = 61.9...` as published. For reconciliation purposes, treat that published value as the invalid observation under investigation, not as a corrected value.

Independent correct recomputation must use a proper Pearson implementation with aligned common dates and explicit NaN / constant-guard handling. It must also reproduce the invariant checks:

- `-1 <= r <= 1`
- `r(X, X) = 1`
- `r(X, -X) = -1`
- `r(X, const)` guarded/undefined

## Evidence constraint

Per Track C1, no trades are regenerated. Recomputation must use only persisted immutable outputs:

- H5 trade list or daily H5 PnL series
- comparison strategy daily PnL series
- aligned common dates

If those persisted inputs are insufficient, the orthogonality field must be set to `UNKNOWN_INSUFFICIENT_PERSISTED_EVIDENCE` rather than guessed.

## Required reconciliation outcome

One of:

- `CORRECTED_PEARSON_R = <valid number>` with invariant checks satisfied, or
- `H5_ORTHOGONALITY = UNKNOWN_INSUFFICIENT_PERSISTED_EVIDENCE`

Either way, the final H5 classification must remain `DISCOVERY_FAIL`.

---

## RESOLUTION — H5-RESULT-INTEGRITY-RECONCILIATION-02 (2026-09-11)

**Outcome: `CORRECTED_PEARSON_R = 0.6070166220125719`** (first branch satisfied)

- Root cause refined beyond `STD_NORMALIZATION_ERROR`: the accumulated covariance was a
  raw SUM while the denominator used population std, so the computed quantity is exactly
  **n · Pearson_r**. Proven by construction in `evidence/PEARSON_VERIFIER_SELFTEST.json`
  (`buggy_formula_is_n_times_pearson = true`) and consistent with the published value:
  `61.91569544528234 / 102 common_days = 0.6070166220125719`.
- The correction uses only persisted immutable outputs (`H5_RESULT.json`, ledger-anchored
  sha256 `2427310d...`) — no trades regenerated, H5 not rerun.
- Corrected value is bounded: `−1 ≤ 0.607 ≤ 1` ✓.
- Under the frozen redundancy rule (overlap > 0.6 AND corr > 0.7): overlap stays 0.916,
  corrected corr 0.607 < 0.7 → rule no longer fires; but trade-time overlap alone keeps
  H5 non-independent of the ROC(24) momentum proxy for research-diversification purposes.
- Full derivation: `H5_ORTHOGONALITY_RECONCILIATION.md`.
- **Final H5 classification remains `DISCOVERY_FAIL`** (unchanged; see TRACK_D).
