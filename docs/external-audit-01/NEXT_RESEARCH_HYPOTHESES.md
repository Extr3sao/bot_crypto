# NEXT RESEARCH HYPOTHESES — F1/F2 (POC02-R2-GOVERNANCE-RECONCILIATION-AND-ALPHA-SEARCH-01)

Bounded, evidence-backed candidates only. Every hypothesis below cites its authorizing
gap in `REGIME_COVERAGE_GAP_REPORT.md` and is checked against `FAILED_RESEARCH_MEMORY.md`.
Ranked by the six required criteria (scored 1–5, higher = better/more feasible; total out of 30).
**Only the TOP hypothesis may proceed to preregistration now** (F2 pipeline); the rest wait.

## F1 — Ranked candidates

| Rank | Hypothesis (IDEA) | Target gap | Orthogonality | Data authority | Opportunity frequency | Implementation complexity | PIT feasibility | Cost realism | TOTAL | Memory conflicts |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | **Regime-transition defense (H1)**: condition any entry on a preregistered regime-transition state (realized-vol regime classifier on 5m/1h, PIT-computable); trade ONLY the post-transition window where legacy momentum was never evaluated | CORRECTION/transition — INSUFFICIENT_OBSERVATION (the largest structural gap) | 4 — conditions all families, adds a state variable not an overlapping signal | 4 — pure OHLCV public REST, same provider authority already frozen | 3 — transitions are episodic; expect enough 1h events for n≥15 per cell in deep data | 3 — classifier + state machine, no new infrastructure | 5 — realized-vol regimes are backward-looking by construction | 5 — fewer/larger trades directly attack the 0.0012/trade cost kill | **24** | None: legacy momentum was never evaluated conditionally on transitions; not a re-parameterization |
| 2 | Volatility term structure (H2): use 1h-vs-5m realized-vol ratio as regime gate for existing mechanism shapes | HIGH_VOL/TRENDING UNDER_COVERED | 3 — gate, not signal; partially overlapping vol family | 4 — OHLCV only | 3 | 2 — needs multi-timeframe pipeline | 5 | 3 | **20** | volatility_structure REFUTED — allowed only because this is a GATE on transitions, not a standalone vol signal; must pre-declare the difference |
| 3 | Relative-value pairs (H3): BTC/ETH/SOL spread mean-reversion conditioned on regime | LOW_VOL RANGE ACTIVITY_WITHOUT_EDGE | 5 — genuinely orthogonal (cross-asset) | 4 — OHLCV | 2 — pair signals are sparse | 1 — needs pair construction + hedge sizing | 4 | 2 — two legs double the cost hurdle | **18** | cross_sectional REDUNDANT lesson respected (orthogonality gate pre-declared); cost realism weak |
| 4 | Session effects (H4): time-of-day conditioning on existing families | Activity without edge (5m) | 2 — timing overlay, low orthogonality | 5 — timestamps | 4 | 4 | 5 | 1 — same cost kill as #9 in memory | **21\*\*** | session_time INSUFFICIENT-negative — ranked 2nd but blocked by cost-realism conflict; requires explicit new cost argument to activate |

\* H4 totals 21 but is **deprioritized**: FAILED_RESEARCH_MEMORY #9 shows the identical
cost mechanism. It may only be promoted if H1/H2 evidence changes the cost picture.

## F2 — Admission pipeline (binding, unchanged)

`IDEA → CANDIDATE → preregistered SPEC (fingerprinted) → TEST → BACKTEST → ROBUSTNESS
(halves/thirds + permutation) → DISCOVERY`

- H1 proceeds to **CANDIDATE** with a NEW preregistered spec; no confirmation shortcut;
  no PAPER promotion; DISCOVERY_FAIL is an allowed terminal outcome.
- H2/H3/H4 remain IDEAs — they do NOT advance until H1 resolves or an evidence-backed
  gap report update re-ranks them (no random proliferation, ALPHA-04).
- Confirmation lock CONF-EDGE-002-001 untouched; nothing in this plan reads or uses the
  confirmation window.
