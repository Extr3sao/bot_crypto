# H6 FAILED-MEMORY COLLISION REVIEW V3 — H6-OI-CONFIRMED-CONTINUATION-03

Checkpoint: `H6-V3-REPAIR-PREREG` · **VERDICT: PASS (no collision with terminal failed families)**

## Method (unchanged from V2 review)

Every terminal entry in `docs/external-audit-01/FAILED_RESEARCH_MEMORY.md` (12 families) was compared against the H6 mechanism, features, assets, timeframe, and cost model. A collision exists if a prior terminal failure already falsified the same mechanism on the same decision variables. Re-run for V3 with the same conclusion, re-recorded so the V3 prereg stands on its own review rather than inheriting V2's.

## Result matrix

| # | Failed family (terminal) | Decision variable falsified | H6 V3 overlap |
|---|---|---|---|
| 1 | Momentum/breakout (price-only) | price-derived entries without confirmation | NONE — H6 requires OI expansion confirmation; price only sets direction |
| 2 | Volume/flow confirmation | volume-based confirmation of price moves | NONE — OI (position stock) is not volume (flow) |
| 3 | Funding/basis carry | funding-rate-conditioned entries | NONE — funding EXCLUDED_WITH_LIMITATION in H6 |
| 4 | Order-flow imbalance (H5) | top-of-book/trade-flow imbalance | NONE — H6 uses no L2/tape data |
| 5 | Mean-reversion (intraday) | counter-trend entries | NONE — H6 is expansion-continuation only |
| 6 | Volatility-regime timing | regime-conditioned exposure | NONE — no regime gate in H6 |
| 7 | Multi-timeframe trend stack | higher-TF alignment filters | NONE — single 1h decision bucket |
| 8 | Event/window seasonality | calendar/time-of-day edges | NONE |
| 9 | Legacy retro strategies | pre-governance unpinned configs | NONE — H6 is PIT-frozen prereg |
| 10 | High-frequency hourly churn (cost-killed) | gross edges destroyed by costs at high decision rate | MANAGED — H6 conditions on OI expansion precisely to cut decision count; 10 bps TOTAL RT frozen; sensitivity 0/10/20/40 diagnostic-only |
| 11 | MAX_POSITIONS/portfolio-size tuning | sizing from rejected-cohort performance | NONE — and H6 consumes NO rejected-cohort performance (H6_SHADOW_DATA_DEPENDENCY=NONE) |
| 12 | M-A event-level trade flow (deferred) | event-window trade flow with severe storage/cost profile | NONE — remains DEFERRED with reasons, not silently absorbed |

## Collision verdict

`CONTRADICTIONS_FOUND = 0`. No terminal failure falsified OI-confirmed continuation on 1h buckets for BTCUSDT/ETHUSDT/SOLUSDT. The mechanism is a genuinely new information axis relative to the failed register, and the two nearest families (#2 flow, #10 churn) are addressed by the OI-vs-flow distinction and the decision-count/cost design respectively.

## Governance note

This review uses only the failed-memory register and mechanism definitions — no performance observation of H6 V3 exists (`PERFORMANCE_OBSERVED=false`), so no entry here can be tuned by outcomes.
