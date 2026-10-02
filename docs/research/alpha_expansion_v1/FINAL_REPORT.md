# ARP-005 — ALPHA EXPANSION FINAL

```
ARP-005 — ALPHA EXPANSION FINAL

START_SHA:  f861251544f18f2fb0fdc33e27276fdbcfbd70c6
END_SHA:    (stamped by the final documentation commit)
COMMITS:    (recorded on commit)

ARP-004 END_SHA RECONCILED: YES
  authoritative = eae4c27e8254303c30ddf42abebb4ddaecf10716 (actual final ARP-004 commit)
  previously recorded = c4f82a052b507282fb7321264dca03963588a580 (results-freezing commit)
  correction is additive and explained; no git object rewritten

HISTORICAL DATA:
  BEFORE: ~209 days/asset 5m (baseline) / 390 days (with extended), 1d max
  AFTER:  2616 days/asset 1h (BTC/ETH), 2028 (SOL), 4h/8h/1d constructible
  DEV: 1806 (BTC/ETH) / 1227 (SOL) 1d days   VALIDATION: 547   OOS_LOCK: 243
  expansion fingerprint: 2ce6e6b5ff1c84d6b365934ab9fbcb0b2ee987a4f041354c454ec6aca952e04a

EXP-ARP-006:  READINESS = READY            (DEV 1806 days ≫ band 230-330; not executed)
EXP-ARP-008:  READINESS = READY            (DEV 1806 days ≥ band 830-1230; not executed)

CROSS_SECTIONAL ENGINE:  legacy = BROKEN / ORPHAN (left untouched);
  minimal fail-closed CrossSectionalSnapshot contract implemented + verified

EXP-ARP-009:  READINESS = EXPERIMENT_READY (infra verified; not executed, superseded
  by the better-specified EXP-ARP-013 on the same family)

CANONICAL CANDIDATES: 21
UNMERGED FOUND:       3 (D-02_vol_z_rev, D-03_squeeze_breakout, D-04_rel_momo; all rejected)
NEWLY CANONICALIZED:  0
DUPLICATES:           0

SELECTED EXPERIMENTS:
  1. EXP-ARP-013  H-XSEC-MOM-LONG-001     cross-sectional momentum (90d)
  2. EXP-ARP-014  H-XSEC-REV-001          cross-sectional reversal (7d)
  3. EXP-ARP-015  H-XSEC-LOWVOL-001       cross-sectional low-volatility (60d)

DEV SURVIVORS:          EXP-ARP-014  (only)
COST SURVIVORS:         EXP-ARP-014  (break-even 35.31 bps > 23.559)
VALIDATION SURVIVORS:   none
ROBUSTNESS SURVIVORS:   none

OOS OPENED:     NO
OOS SURVIVORS:  none

PROMOTION_CANDIDATES:   none

REJECT_NO_EDGE:         0
REJECT_COSTS:           0
REJECT_VALIDATION:      1   (EXP-ARP-014)
REJECT_FRAGILE:         1   (EXP-ARP-013)
INSUFFICIENT_EVIDENCE:  1   (EXP-ARP-015)

TESTS:  1555 passed / 0 failed / 0 skipped
RUFF:   clean
MYPY:   Success: no issues found in 431 source files

INDEPENDENT VERIFICATION: NOT_TRIGGERED (no experiment reached
  ROBUSTNESS_SURVIVOR / OOS_GATE_ELIGIBLE)

FALSE_SUCCESS:  0

VERDICT: ARP-005 ALPHA EXPANSION = COMPLETE. The data deficit is closed (multi-
  regime 2019-2026 history), the cross-sectional infrastructure is verified, and
  the research backlog is reconciled with zero new canonical candidates. Three
  genuinely orthogonal cross-sectional factor experiments were pre-registered and
  executed; none found a cost-compatible edge. EXP-ARP-013 (momentum) is one-trade
  concentrated; EXP-ARP-014 (reversal) cleared DEV+COST but failed out-of-sample at
  canonical cost; EXP-ARP-015 (low-vol) is sample-starved on a 3-asset universe.
  OOS remains sealed and unseen; no runtime, Risk, lifecycle or promotion state was
  touched.

NEXT AUTHORIZED STEP: (not executed here) either widen the cross-sectional universe
  beyond three assets to give slow factors a usable sample, or pre-register a new,
  distinct mechanism; any survivor must be independently verified before a PAPER
  SHADOW consideration.
```
