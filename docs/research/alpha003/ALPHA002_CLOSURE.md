# ALPHA-002 — CLOSURE DECISION

`DEVELOPMENT COMPLETE = NO_ALPHA_WITH_UNTESTED_HYPOTHESES` · do not retune

## Result

- hypotheses_tested: 3
- A2-H01: REJECT
- A2-H03: REJECT
- A2-H02: INCONCLUSIVE
- oos_candidates: 0
- holdout_read: False
- false_success: 0
- verifier: PASS 61/61
- preregistration_hash: 8b09f608256a31722b366f10e52513e9a347405d078138a9c350df1ad2439f6b

## Cause

- binding_constraint: the derivatives confirmation subtracted value
- baseline_delta_bps: {'A2-H01': -1.228127, 'A2-H03': -1.22444, 'A2-H02': -0.127502}
- note: against the same rule with the derivatives confirmation removed, every fully-exercised mechanism did worse, i.e. participant data added nothing over the price condition it was built on
- untested_reason: A2-H02's frozen threshold (funding > 1e-4) was never strictly exceeded in the discovery slice — the maximum observed was exactly 1e-4 across all four assets — so it produced zero decisions and is recorded as INCONCLUSIVE, not negative

## Recorded research hypotheses (not pursued here)

- OI contraction may outperform OI expansion (the declared non-traded exhaustion contrast out-returned the expansion subset; recorded for a future campaign, not pursued here)

## Evidence

- `preregistration`: docs/research/alpha002/ALPHA002_PREREGISTRATION.{md,json}
- `development_results`: reports/alpha002/ALPHA002_DEVELOPMENT_RESULTS.{md,json}
- `verification`: reports/alpha002/ALPHA002_VERIFICATION.{md,json}
- `commit`: ea4d488

## Prohibited

- retuning thresholds, horizons or the cost model on this family
- promoting an UNDERPOWERED cell to a candidate
- re-reading the ALPHA-002 holdout for an ALPHA-002 question
