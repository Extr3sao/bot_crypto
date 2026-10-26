# ALPHA-001 — CLOSURE DECISION

`CLOSED = ACCEPT NO ALPHA` · do not retune

## Result

- families_tested: 6
- hypotheses_tested: 12
- admitted: 0
- gross_positive: 6
- net_positive_at_certified_cost: 0
- bh_fdr_survivors_q10: 0
- holm_survivors_alpha10: 0
- p_null_best_ge_observed: 0.765
- best_hypothesis: A1-H09
- best_gross_bps: 18.575939
- frozen_hurdle_bps: 55.380903
- holdout_read: False
- false_success: 0
- verifier: PASS 56/56

## Cause

- binding_constraint: EFFECT_SIZE_NOT_COST
- best_gross_bps: 18.575939
- non_cost_bar_bps: 25.642692
- admission_break_even_cost_bps: -5.653402
- note: even at zero cost the frozen bar needs 25.64 bps of gross and the best cell reached 18.58; the certified cost would have to become a rebate of 5.65 bps per round trip for the frozen rule to admit anything

## What it tells the system

under those twelve hypotheses and that methodology, the price signals tested do not contain enough edge on their own. This is information, not a failure: it removes a family from the search space without burning capital.

## Evidence

- `cost_frontier`: reports/alpha001/COST_FRONTIER.{md,json}
- `final_report`: reports/alpha001/FINAL_REPORT.{md,json}
- `verification`: reports/alpha001/ALPHA001_VERIFICATION.{md,json}
- `gates`: reports/alpha001/GATES.json
- `commits`: ['040f6fc', 'cb26974']

## Reopening requires

- a genuinely new information source, not a new parameter on the same series
- a preregistered hypothesis whose expected gross exceeds the frozen hurdle ex ante
- no re-use of the ALPHA-001 holdout for an ALPHA-001 question

## Prohibited

- retuning thresholds, horizons or the cost model on this family
- promoting an UNDERPOWERED cell to a candidate
- presenting a raw p-value as corrected evidence
