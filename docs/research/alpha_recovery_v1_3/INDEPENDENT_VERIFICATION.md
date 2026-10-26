# ARP-004 — INDEPENDENT VERIFICATION (§26)

## §26 trigger check

§26 requires independent verification (builder ≠ verifier) for any experiment reaching
**`OOS_GATE_ELIGIBLE`** or **`PROMOTION_CANDIDATE`**.

| experiment | reached OOS gate / promotion? |
| --- | --- |
| `EXP-ARP-007` | No — `REJECT_COSTS` before the validation gate |
| `EXP-ARP-010` | No — `INSUFFICIENT_EVIDENCE` at DEV |

**No experiment triggered §26 independent verification.** No `PROMOTION_CANDIDATE` and
no `OOS_SURVIVOR` exists, so there is nothing to hand to an external verifier. The
manifests' `verifier` field appropriately remains `UNASSIGNED`.

## Reproducibility evidence produced anyway

Even without a promotion claim, the run's reproducibility was checked by the builder:

* the driver was run **twice**; every generated JSON hashed identically
  (`DETERMINISTIC_OK` over `reports/alpha-recovery-v1-3/**/*.json`);
* frozen ARP-003 manifests re-verified against the live config hash
  (`6c4dd0be…`), dataset fingerprint (`9d51385d…`), cost model (23.559 bps), splits and
  OOS-lock — all match (`MANIFEST_VALIDATION.json`, `all_valid: true`);
* `dataset_fingerprint`, `config_hash`, `code_hash` and `cost_bps_rt` are recorded in
  `ENVIRONMENT.json`;
* PIT invariants are covered by adversarial unit tests in
  `tests/unit/research/test_alpha_recovery_daily.py`.

## CAVEAT (`FALSE_SUCCESS` guard)

This document is **builder self-check, not independent verification** and must not be
read as such. Any future experiment that reaches the OOS gate must be reproduced by a
separate verifier before any promotion claim (§26). `FALSE_SUCCESS = 0`.
