# ARP-004 — COST-COMPATIBLE EDGE CAMPAIGN — FINAL

```
ARP-004 — COST-COMPATIBLE EDGE CAMPAIGN FINAL

START_SHA:  d4cd26da3e77ad508e3f50b0cb5a74bdc3815c5f
EXPERIMENT_SHA: c4f82a052b507282fb7321264dca03963588a580
END_SHA:    eae4c27e8254303c30ddf42abebb4ddaecf10716
COMMITS:    c4f82a052b507282fb7321264dca03963588a580,
            eae4c27e8254303c30ddf42abebb4ddaecf10716

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

## END_SHA RECONCILIATION (ARP-005 §0)

This report originally declared `END_SHA = c4f82a0…`. That SHA is the commit that
*executed* the experiments; a later documentation-only commit `eae4c27…`
(`ARP-004: stamp END_SHA into the tracked final/run reports`) is the actual final
commit of the ARP-004 lineage. `git merge-base --is-ancestor c4f82a0 eae4c27`
confirms `c4f82a0` is an ancestor of `eae4c27`.

The authoritative `END_SHA` is therefore **`eae4c27e8254303c30ddf42abebb4ddaecf10716`**.
The experiment-results commit is retained above as `EXPERIMENT_SHA`. This is a
transparent correction, not a silent rewrite: no git object was altered, the
original `c4f82a0` value remains recorded, and the change is explained here.
