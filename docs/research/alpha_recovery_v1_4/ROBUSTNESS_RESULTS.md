# ARP-005 — ROBUSTNESS RESULTS (§13)

ROBUSTNESS is only reached after DEV PASS, COST PASS **and** VALIDATION PASS.

**No experiment reached ROBUSTNESS.** `EXP-ARP-012` is the only candidate that passed
DEV and COST, and it failed VALIDATION, so the pipeline short-circuits before the
parameter-neighbourhood test (`VALIDATION fail → ROBUSTNESS NOT_REACHED`).

| experiment | DEV | COST | VALIDATION | ROBUSTNESS |
| --- | --- | --- | --- | --- |
| EXP-ARP-009 | INSUFFICIENT_EVIDENCE | NOT_REACHED | NOT_REACHED | NOT_REACHED |
| EXP-ARP-011 | INSUFFICIENT_EVIDENCE | NOT_REACHED | NOT_REACHED | NOT_REACHED |
| EXP-ARP-012 | PASS | PASS | REJECT_VALIDATION | NOT_REACHED |

The declared perturbation grids (`scripts/alpha_recovery_v1_4.py::ROBUSTNESS`,
frozen before results) were therefore not executed for any candidate — running them on
a VALIDATION-failed mechanism would be exactly the "search for best parameters" the
regime forbids, and a robustness pass could not rescue a failed unseen split.

`ROBUSTNESS survivors = 0`.
