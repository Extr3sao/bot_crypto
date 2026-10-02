# ARP-004 — COST-COMPATIBLE EDGE CAMPAIGN — FINAL

```
ARP-004 — COST-COMPATIBLE EDGE CAMPAIGN FINAL

START_SHA:  d4cd26da3e77ad508e3f50b0cb5a74bdc3815c5f
END_SHA:    (stamped after commit)
COMMITS:    (stamped after commit)

EXP-ARP-007:
  DEV:             PASS  (153 trades)
  GROSS EXPECTANCY: +0.776 bps
  NET EXPECTANCY:   -22.783 bps
  COST:            REJECT_COSTS  (canonical 23.559 bps; break-even 0.776 bps)
  VALIDATION:      NOT_REACHED
  ROBUSTNESS:      NOT_REACHED
  OOS:             NOT_OPENED
  DECISION:        REJECT_COSTS

EXP-ARP-010:
  DEV:             INSUFFICIENT_EVIDENCE  (6 trades)
  GROSS EXPECTANCY: -75.059 bps
  NET EXPECTANCY:   n/a (no cost stage)
  COST:            NOT_REACHED
  VALIDATION:      NOT_REACHED
  ROBUSTNESS:      NOT_REACHED
  OOS:             NOT_OPENED
  DECISION:        INSUFFICIENT_EVIDENCE

DEV SURVIVORS:          EXP-ARP-007
COST SURVIVORS:         none
VALIDATION SURVIVORS:   none
ROBUSTNESS SURVIVORS:   none

OOS OPENED:     NO
OOS SURVIVORS:  none

PROMOTION_CANDIDATES:   none

EXP-ARP-006:
  DATA STATUS:   DATA_SHORT_FOR_HORIZON — 5-day holds; needs ≈230-330 DEV days/symbol (gap ≈110-210)

EXP-ARP-008:
  DATA STATUS:   DATA_SHORT_FOR_HORIZON — 20-day holds; needs ≈830-1230 DEV days/symbol (gap ≈2-3 years)

EXP-ARP-009:
  INFRA STATUS:  INFRASTRUCTURE_BLOCKED — CrossSectionalEngine orphan, no-op ranks, no asset-sync guard, no tests

REJECT_NO_EDGE:         0
REJECT_COSTS:           1   (EXP-ARP-007)
REJECT_VALIDATION:      0
REJECT_FRAGILE:         0
INSUFFICIENT_EVIDENCE:  1   (EXP-ARP-010)

TESTS:  1503 passed / 0 failed / 0 skipped
RUFF:   clean
MYPY:   Success: no issues found in 413 source files

INDEPENDENT VERIFICATION: NOT TRIGGERED (no experiment reached OOS_GATE_ELIGIBLE / PROMOTION_CANDIDATE)

FALSE_SUCCESS:  0

VERDICT: ARP-004 = COMPLETE. No cost-compatible edge found in either authorized
         experiment. EXP-ARP-007 (daily pivot fade) is cost-dominated (+0.776 bps
         gross vs 23.559 bps cost); EXP-ARP-010 (vol-spike reversion) is sample-starved
         (6 DEV trades, threshold not loosened). OOS remains unopened and unseen; no
         runtime, Risk, lifecycle or promotion state was touched.

NEXT AUTHORIZED STEP: (not executed here) obtain additional daily history to reach the
         adequacy band, or pre-register a new, distinct hypothesis; any survivor must be
         independently verified before a PAPER SHADOW consideration.
```
