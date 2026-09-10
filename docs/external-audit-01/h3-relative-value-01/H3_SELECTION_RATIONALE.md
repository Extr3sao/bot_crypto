# H3 RELATIVE-VALUE — HYPOTHESIS SELECTION (C1/C2, PRE-RESULT)

Checkpoint: H1-EVIDENCE-INTEGRITY-AND-H3-RELATIVE-VALUE-PREREG-01 · Date: 2026-09-10
**No backtest, no performance number, and no spread statistic was observed during this selection.**
Selection used only: REGIME_COVERAGE_GAP_REPORT.md, FAILED_RESEARCH_MEMORY.md #1–#10,
NEXT_RESEARCH_HYPOTHESES.md, dataset-depth facts (provider row counts), and economic reasoning.
Gate precedent honored: memory #7 requires orthogonality to be pre-declared BEFORE testing.

## C2 — Candidate ranking (criteria scored 1–5, higher = better; no performance input)

| Candidate | Econ. rationale | Orthogonality | PIT feas. | Data depth / sync | Cost realism | Freq. (natural) | Market-neutr. feas. | Regime relevance | Complexity | TOTAL | Notes |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| **BTC↔ETH beta-neutral log-spread reversion** | 5 — majors, persistent co-movement, divergence = relative mispricing | 5 — cross-asset, direction-neutral | 5 — trailing OLS/z, trivially PIT | 5 — both legs full frozen window (58,633 rows each), same provider, aligned 1h | 4 — two deepest books; still 2-leg cost hurdle | 3 — sparse by design (attacks cost hurdle, memory #1/#9/#10) | 4 — beta-neutral in return space, measurable | 4 — LOW_VOL RANGE ACTIVITY_WITHOUT_EDGE gap + correlation gate | 5 — rolling OLS + z only | **40** | SELECTED |
| BTC↔SOL displacement | 3 — sector mismatch weakens reversion rationale | 5 | 5 | 3 — SOL starts 2020-08 (52,458 rows) | 2 — SOL slippage worst of the three | 2 | 3 | 3 | 3 | 29 | rejected: cost + depth |
| ETH↔SOL displacement | 3 | 5 | 5 | 3 — same SOL depth limit | 2 | 2 | 3 | 3 | 3 | 29 | rejected: cost + depth |
| Basket market-neutral spread (3 legs) | 4 | 5 | 4 | 3 | 2 — three-leg cost | 2 | 4 | 3 | 2 — sizing matrix | 29 | rejected: complexity × cost |
| Cross-asset lead/lag | 2 — lags are arbitraged; weak mechanism | 4 | 4 | 4 | 2 — high turnover | 4 | 2 | 2 | 3 | 27 | rejected: rationale + turnover |
| BTC↔ETH plain ratio reversion (no hedge) | 3 — unhedged directional leak | 3 | 5 | 5 | 3 | 3 | 1 — NOT neutral | 3 | 5 | 33 | rejected: fails C6 neutrality claim |

## C1 — Selected hypothesis (exactly ONE)

**H3 = BTC↔ETH beta-neutral log-price spread mean reversion.**
Economic statement: when the BTC–ETH pair co-moves (rolling correlation gate), temporary
divergences of the beta-adjusted log spread represent relative mispricing between the two
majors and tend to revert toward the rolling mean; the strategy monetizes the *relative*
displacement, holding no directional view on either asset.

- NOT simple directional momentum under another name: entry is |z|≥2.5 against the recent
  spread trend, both legs always opposite, beta-hedged.
- Gap authority: REGIME_COVERAGE_GAP_REPORT.md — LOW_VOL/RANGE `ACTIVITY_WITHOUT_EDGE`,
  and the cross-asset family is absent from the current legacy universe (orthogonality 5).
- Memory check: #7 (cross_sectional) honored via pre-declared orthogonality gate;
  #10/#1/#9 cost lessons honored via sparse entries + explicit two-leg cost model;
  #8 (carry/funding) not reused — no funding term in the mechanism.

## C8 — Orthogonality pre-declaration (before any execution)

Comparison families: momentum, trend, breakout, mean_reversion, volatility,
volatility_structure, cross_sectional, carry_funding, H1 transition defense.
Concrete measurables at execution: trade-time overlap vs the frozen ROC(24) legacy proxy
(deterministic replay of frozen code — technical, not an experiment), daily PnL
correlation on common days, H1 trade-time overlap (deterministic H1 replay), regime
activation overlap. REDUNDANT_CANDIDATE rule: trade-time overlap > 0.6 AND daily PnL
correlation > 0.7, even if raw PF is attractive.
