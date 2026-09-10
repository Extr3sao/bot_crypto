# H5 — NEXT HYPOTHESIS SELECTION (Track F, PERFORMANCE-BLIND)

Checkpoint: H3-GOVERNANCE-RECONCILIATION-AND-H5-SELECTION-01 · Date: 2026-09-10
**No signal statistic, no backtest, and no performance number was computed or observed
during this selection.** Data-authority checks were limited to field PRESENCE in the
frozen committed datasets (12-field klines confirmed for BTC/ETH/SOL).

## Candidate ranking (9 criteria, scored 1–5; no performance input)

| Candidate family | Mechanism | Orthogonality | Data authority | PIT feas. | Opportunity freq. | Cost hurdle | Sample depth | Regime gap | Complexity | TOTAL | Verdict |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| **Order-flow imbalance continuation (taker-flow extremes + participation)** | Aggressive one-sided taker flow at elevated participation marks directional pressure that persists over the next bars (flow autocorrelation; condition on WHO traded — a variable absent from #1–#11) | 5 — flow conditioning orthogonal to price-shape/state families | **5 — proven in frozen committed 12-field klines (takerBuyBaseVolume, numberOfTrades; 58,633/58,633/52,458 rows)** | 5 — bar-t aggregates, trailing normalization | 4 — flow extremes occur across all regimes | 4 — 10 bps RT on ONE leg (single-asset futures, unlike H3's two legs) | 5 — 5.5–6.6 years × 3 assets | order-flow regimes: INSUFFICIENT_OBSERVATION (largest remaining gap) | 5 — trivial aggregation | **38** | **SELECTED as H5** |
| Volatility term structure (H2) | vol-state gate — premise undercut by #10 (state variable alone carried zero gross edge) | 3 | 5 | 5 | 3 | 3 | 5 | partial | 3 | 27* | NOT selected — blocked by memory #10 absent new evidence (no automatic execution) |
| Session / time-of-day (H4) | timing overlay on failed families | 2 | 5 | 5 | 4 | 1 — identical cost mechanism to #9 | 4 | none new | 5 | 22* | NOT selected — cost-blocked (#9) |
| Cross-asset lead-lag | lags arbitraged; adjacent to #11's refuted cross-asset normalization | 3 | 4 | 4 | 3 | 2 — two legs | 4 | adjacent to refuted row | 3 | 23 | NOT selected |
| Cross-venue dislocation | same asset, two venues | 4 | **1 — no second-venue data in any frozen dataset** | 3 | 3 | 3 | — | — | 2 | 16 | REJECTED — no data authority |
| Liquidation / stress-flow | forced-flow cascades | 4 | **1 — no liquidation feed in frozen datasets** | 3 | 2 | 3 | — | — | 2 | 15 | REJECTED — no data authority |

\* H2/H4 remain registered IDEAs with their blockers unchanged.

## Selected: H5 = ORDER-FLOW IMBALANCE CONTINUATION (exactly ONE)

Economic statement (pre-result): bars where aggressive taker flow is strongly one-sided
(|OFI| ≥ 0.30) while market participation is elevated (trade count ≥ 1.5× its trailing
norm) mark directional pressure from impatient/informed traders that tends to PERSIST
into the following bars; entering WITH the flow side at the next bar open and holding a
fixed short horizon monetizes that persistence. This is a **continuation** mechanism —
deliberately distinct from H3's refuted reversion premise — and conditions on order flow
(a microstructure variable), which no hypothesis in failed-memory #1–#11 used.

- Gap authority: REGIME_COVERAGE_GAP_REPORT.md REFRESH row "order-flow imbalance regimes"
  (INSUFFICIENT_OBSERVATION — never discovered, data authority proven in already-frozen
  committed files).
- Failed-memory check (E1): #1–#4 are price-shape families, #5/#6 volatility, #7 cross-sectional
  price ranks, #8 funding basis, #9 time-of-day, #10 regime-state labels, #11 trailing-z spread
  reversion — none conditions on taker-flow aggregates. Mechanism is NOT a repackaging.
- Cost realism: single-asset futures (one leg), 10 bps RT — the same hurdle H1 cleared
  arithmetically; the hypothesis needs only |gross| > cost on a sparser signal set.
- Thresholds (0.30 / 1.5) are EX ANTE round design constants frozen in the spec; any
  post-result change is forbidden (H1-10/H3-13 precedent).
