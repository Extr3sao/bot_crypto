# FAILED RESEARCH MEMORY — TRACK G (POC02-R2-GOVERNANCE-RECONCILIATION-AND-ALPHA-SEARCH-01)

Purpose: persistent memory of refuted/failing research so no future hypothesis repeats a
failed mechanism under a new name. Read BEFORE drafting any F1 hypothesis. This memory
never auto-tunes production; it only blocks redundant research and re-rolling refuted ideas.

## Register

| # | Hypothesis / family | Result | Failure mechanism (evidence) | Lesson for future hypotheses |
| --- | --- | --- | --- | --- |
| 1 | Legacy momentum (5m/1h cells) | FAILED | All cells NOT_SIGNIFICANT (permutation p ≥ 0.05); cost drag 0.0012/trade (0.0004 commission + 2bps slippage × both sides) kills 5m cells; 9/14 failed cells also negative net expectancy | A 5m-entry hypothesis must clear ≥ 0.12% per-trade cost hurdle by design (fewer, larger-edge trades), not assume costs away |
| 2 | Legacy trend (5m/1h cells) | INSUFFICIENT | n < 15 binding; no sign stability assessable | Trend hypotheses must define trade frequency compatible with n ≥ 15 per cell BEFORE running; pick timeframes/holding periods that generate enough independent trades |
| 3 | Legacy breakout (cells) | FAILED | NOT_SIGNIFICANT ×6, NEGATIVE_NET ×3, PF < 1 ×3, Sharpe CI entirely < 0 ×3 | Plain breakout on public OHLCV is refuted in tested cells; a new breakout variant needs a different entry filter (vol/state conditioning), not re-parameterization |
| 4 | Legacy mean_reversion (cells) | FAILED | NOT_SIGNIFICANT ×3, NEGATIVE_NET ×2, PF < 1 ×2 | Same as #3; MR refuted in tested coarse regimes |
| 5 | Legacy volatility (cells) | INSUFFICIENT | n < 15 binding | Data-depth problem, not refutation — may re-enter via deeper real data with preregistered spec |
| 6 | volatility_structure (Batch 01) | DISCOVERY_FAIL / REFUTED_BY_DEEPER_WINDOW | Lead PFs (BTC 1h 2.526, ETH 1h 3.042) collapsed under deeper window; below minimum n (8–11) | Single-asset vol-structure leads at 1h do not replicate; no re-run on same spec |
| 7 | cross_sectional (Batch 01) | DISCOVERY_FAIL / REDUNDANT_WITH_MOMENTUM | n=11 below minimum; 1h PF 1.616 recorded as lead only; redundant with existing momentum exposure | Cross-sectional rank hypotheses must demonstrate orthogonality to momentum BEFORE testing (correlation gate) |
| 8 | carry_funding (Batch 02 + CARRY-FUNDING-DEEP-01) | DISCOVERY_FAIL (deep: N=769, PF 1.062, halves/thirds INCONSISTENT, p=0.283) | Funding-carry edge absent net of costs on 7,670 real rows (2019-09-10→present); inconsistent across halves/thirds | Funding basis alone is not an edge net of costs; any basis hypothesis must add a conditioning variable and show halves/thirds consistency |
| 9 | session_time / liquidity_flow (Batch 01) | INSUFFICIENT / below minimum, consistently negative | n=12–82, negative net expectancy — costs dominate | Intraday timing hypotheses inherit the same cost hurdle; must show gross edge ≫ 0.12%/trade |

## Standing prohibitions

- No re-run of any registered hypothesis on the same spec (fingerprint change must
  reflect a mechanistic change, not a parameter sweep).
- No PAPER promotion from failed/insufficient lines (TRACK E/D2 governance).
- INSUFFICIENT ≠ refuted: these may re-enter ONLY with new real data depth
  (no synthetic fill) and a preregistered spec.
