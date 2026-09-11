# TRACK D — H5 FINAL RESULT CONFIRMATION

Result: **DISCOVERY_FAIL**

This confirmation is independent of the orthogonality correction in Track C.

## Primary economic reasons

- Statistical significance insufficient:
  - `P_Sharpe_gt_0 = 0.8285`
  - `Sharpe_CI95 = [-0.1217, 0.2299]`
  - `permutation_p = 0.1838`
- Temporal instability:
  - `halves = [1, -1]`
  - `thirds = [1, 1, -1]`
- Negative walk-forward tail:
  - `walk_forward_last_third_net_R = -0.0858`

## Orthogonality status

- Raw published value in `H5_RESULT.json` is invalid (`61.9...`), registered as `DEF-H5-ORTHO-001`.
- Incorrect orthogonality cannot rescue the result.
- If corrected orthogonality is low: failure is economic/robustness.
- If corrected orthogonality is high: failure also includes redundancy.

## Promotion control

- No confirmation.
- `PAPER_PROMOTIONS = 0`.
- No H5.1, no H5 promotion, no post-hoc subgroup promotion.

---

## ADDENDUM — H5-RESULT-INTEGRITY-RECONCILIATION-02 (2026-09-11)

Orthogonality reconciliation completed WITHOUT rerunning H5: corrected
`daily_pnl_correlation = 0.6070166220125719` (the published 61.9 was exactly
102 × the true Pearson r — see `H5_ORTHOGONALITY_RECONCILIATION.md`). Under the frozen
redundancy rule the corrected correlation no longer trips the 0.7 threshold, but the
0.916 trade-time overlap keeps H5 non-independent of simple momentum.

This cannot promote H5: the failure is carried by P(Sharpe>0)=0.8285 < 0.90,
permutation p=0.1838 > 0.05, halves [1,−1], thirds [1,1,−1], and walk-forward −0.0858 R.

**H5_RESULT = DISCOVERY_FAIL — CANONICAL AND FINAL.** Prereg manifest restored
byte-identical to c426b35; `H5_RESULT.json` untouched (ledger-anchored sha256
`2427310d...`).
