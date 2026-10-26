# ARP-006 — HYPOTHESIS REGISTRY

Frozen before any result. Hypothesis changes require a new `EXPERIMENT_ID`.

| id | experiment | statement | status |
| --- | --- | --- | --- |
| `H-DAILY-TSMOM-001` | `EXP-ARP-008` | Daily time-series momentum (`close > close[-30]`, next-open, long/flat) is cost-compatible on major crypto. | **ROBUSTNESS_SURVIVOR** (OOS sealed) |
| `H-LIQREV-DAILY-016B` | `EXP-ARP-006` | A fast one-sided daily move reverts into its void-origin band (fade). | **REJECTED** `REJECT_NO_EDGE` |
| `H-XSEC-MOM-LONG-002` | `EXP-ARP-016` | A broad PIT universe gives cross-sectional momentum enough dispersion to survive. | **REJECTED** `REJECT_VALIDATION` |
| `H-XSEC-REV-002` | `EXP-ARP-017` | Cross-sectional short-horizon reversal has a cost-compatible edge on a broad universe. | **REJECTED** `REJECT_COSTS` |
| `H-XSEC-LOWVOL-002` | `EXP-ARP-018` | The calmest assets outperform on a broad universe with enough independent episodes. | **REJECTED** `REJECT_VALIDATION` (sample) |

## Design principles applied

* The broader universe is a **measurement** change, not a parameter tune: a rank-1
  selection on 86-111 assets is a genuinely different test than on 3.
* Prior `EXP-ARP-013/014/015` configurations are frozen negative knowledge and were
  **not** re-run; the new experiments only share a mechanism family.
* `EXP-ARP-017` explicitly acknowledges the VALIDATION split already consumed by
  `EXP-ARP-014` and is capped at `VALIDATION_SURVIVOR`.
