# ALPHA-003 — CLOSURE DECISION

`DEVELOPMENT COMPLETE = NO_ALPHA` · do not retune

## Result

- hypotheses_tested: 3
- A3-H01: REJECT
- A3-H02: REJECT
- A3-H03: REJECT
- cells: 36 (36 POWERED)
- oos_candidates: 0
- holdout_read: False · validation_read: False
- rows available but unused: validation 56561, holdout 56563
- false_success: 0
- verifier: PASS 272/272
- preregistration_hash: db43ad5283cad875ac014a622dc7acae423d0e44c5f64c473a039e3f9ed1c4c8
- design_n: 127264 · hurdle: 40.056845 bps · cost: 23.790569 bps
- best gross: 1.865037 bps (`A3-H01|BTCUSDT->ETHUSDT|L1|15m`) · best net: -21.925532 bps
- best incremental delta: 1.839842 bps · median 0.063337 bps
- raw_positive 11 · incrementally_positive 20 · statistically_supported 0 · economically_admissible 0
- BH survivors 0 · Holm survivors 0 · cells with p_raw < 0.05: ['A3-H01|BTCUSDT->ETHUSDT|L1|15m']

## Cause

- binding_constraint: the cross-asset term added nothing over what the target's own history already explained
- note: the best cell's cross-asset arm grossed +1.865037 bps while its own-history baseline grossed +0.025195 bps, so the external information was worth +1.839842 bps against a frozen hurdle of 40.056845 bps and a round-trip cost of 23.790569 bps
- selection null: an equally sized random signal of the same shape reached +3.524387 bps at the 95th percentile of the best-of-N null, above the +1.865037 bps actually observed
- mechanism reading: the universe's trailing correlation with the equal-weight market is 0.89-0.92 with betas of 0.67 (BTC), 1.02 (ETH) and 1.19 (SOL): co-movement dominates, which is why knowing the leader's move adds nothing once the target's own move is controlled

## Recorded research hypotheses (not pursued here)

- a target that has already repriced at least as much as the leader (the declared A3-NT-02 subset) may behave differently from the lagging side, which is where the frozen rule trades — `BTCUSDT->XRPUSDT` 15m n=847 4.471396 bps
- OI contraction may outperform OI expansion (carried forward from ALPHA-002) — recorded for a future campaign, not pursued here

## Recommended next family (evidence-based)

- this closure opens no ALPHA-004 and authorises no retune of ALPHA-003 thresholds, lags, pairs, timeframes, direction or cost model
- volatility structure: the best cell's gross lived in the CONTRACTING regime (2.336564 bps over 1123 decisions) against EXPANDING (0.731936 over 574), so volatility state is measured to matter more than cross-asset information and is the cheapest next question to preregister
- microstructure / order-book: the repository already holds captured book_ticker segments under reports/microstructure-forward*, so the data side of this family is already instrumented
- cross-exchange: needs a second venue's history, a data-acquisition decision first
- seasonality / calendar: cheapest to preregister, weakest mechanism

## Environment constraint (measured)

- free space: 7.026 GiB of 237.53 GiB (0.9704 used); lowest observed today 0.25 GiB
- persistent occupancy: reports/cap004 = 20.688 GiB inside reports/ = 24.165 GiB
- research datasets: 0.1095 GiB combined; steady-state growth 0.0 GiB/day
- days until the 2.0 GiB threshold at the measured CAP-004 write scale: 0.72
- action: nothing deleted: reports/cap004 is a protected campaign artifact (CAP-004) and no deletion is authorised; reported as a blocker with a recommendation

## Evidence

- preregistration: `docs/research/alpha003/ALPHA003_PREREGISTRATION.{md,json}`
- development_results: `reports/alpha003/ALPHA003_DEVELOPMENT_RESULTS.{md,json}`
- baseline_comparison: `reports/alpha003/ALPHA003_BASELINE_COMPARISON.{md,json}`
- lead_lag_matrix: `reports/alpha003/ALPHA003_LEAD_LAG_MATRIX.{md,json}`
- regime_report: `reports/alpha003/ALPHA003_REGIME_REPORT.{md,json}`
- verification: `reports/alpha003/ALPHA003_VERIFICATION.{md,json}`
- disk_analysis: `reports/alpha003/ALPHA003_DISK_ANALYSIS.{md,json}`
- commit: `71dd6fa`
- source_head: `ea4d488`

## Prohibited

- retuning thresholds, horizons, pairs, lags or the cost model on this family
- reading the ALPHA-003 holdout for an ALPHA-003 question
- adding a pair, lag or timeframe after seeing a result
- promoting a cell that only replicates own-asset momentum
- introducing machine learning into this family to rescue a relation that is not there

## Reopen requires

- a new campaign with its own frozen preregistration and a different information source; the holdout of ALPHA-003 stays locked until such a campaign declares how it will read it
- ALPHA-001's closure sits in docs/research/alpha002 and ALPHA-002's in docs/research/alpha003, each beside its successor's preregistration. There is no successor campaign yet, so this closure is filed in the campaign's own directory instead of creating an empty ALPHA-004 one.
