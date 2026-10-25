# SOURCE REVIEW — SRC-MANUAL-001

## Metadata
- Title: Market Makers Method (Order Blocks)
- Author: Luis Riesco
- Year: not stated; examples concentrate on 2015-2017
- Type: TRADING_MANUAL / COURSE NOTES
- Reliability: D overall; C for explicit methodological cautions; E for unsupported causal manipulation claims
- File: `/mnt/data/1_5175147553993261137[1](1).pdf`

## Coverage
- Pages total: 161 PDF objects; 159 numbered/content pages + 2 trailing blank pages
- Pages reviewed: all PDF page objects
- Pages unreadable: 0 material pages; image-only content visually reviewed where applicable
- Figures/tables/charts reviewed: yes, via full-page renders/contact-sheet scan; chart-heavy sources received visual interpretation
- Coverage status: SOURCE_REVIEW_COMPLETE

## Source Thesis
FX price action can be organized around HTF directional premise, liquidity sweeps, session timing, Order Blocks/OTE and related-pair divergence, but the note repeatedly acknowledges failures and hindsight ambiguity.

## Methodology
Course-note synthesis with many chart examples, discretionary interpretation, some self-critique/backtesting suggestions, no controlled statistical study.

## Markets / Assets
FX discretionary technical/macro trading; research hypotheses

## Timeframes
As source-defined per claim/spec. No missing timeframe is invented.

## Source Evidence
Primarily practitioner narrative/examples unless otherwise noted. Evidence classification does not equal project validation.

## Source Limitations
Full 161-page visual scan. Source itself contains strong counter-evidence, hindsight warnings and admissions that several concepts do not work consistently.

## Relevant Claims
| CLAIM | LOCATION | TYPE | NORMALIZED CLAIM | RULE CLASS |
|---|---|---|---|---|
| CLAIM-M1-001 | p.2; pp.20-23 | REGIME_CLAIM | The manual frames price as alternating between directional expansion/movement and ranges/consolidation. | SOURCE_EXPLICIT |
| CLAIM-M1-002 | p.2; p.20 | REGIME_CLAIM | Consolidations are presented as precursors to later expansion. | SOURCE_EXPLICIT |
| CLAIM-M1-003 | pp.2-3; pp.73-75 | STRATEGY_CLAIM | A Directional Premise from higher-timeframe trend/fundamentals is a prerequisite for many lower-timeframe setups. | SOURCE_EXPLICIT |
| CLAIM-M1-004 | pp.8-13 | MARKET_CLAIM | Prior highs/lows and range edges are treated as likely liquidity targets for short-lived stop-sweep moves. | SOURCE_EXPLICIT |
| CLAIM-M1-005 | pp.8-10; pp.28-34 | REGIME_CLAIM | London/New York active hours are claimed to concentrate reversals/stop-hunt opportunities, though the source also says such moves can occur at other times. | SOURCE_EXPLICIT |
| CLAIM-M1-006 | p.2; pp.64-75 | STRATEGY_CLAIM | An Order Block is operationally associated with the opposite candle/area immediately preceding a sustained directional move. | SOURCE_EXPLICIT |
| CLAIM-M1-007 | pp.69-75 | STRATEGY_CLAIM | Order Blocks are intended primarily as pullback entries in an already established or anticipated trend. | SOURCE_EXPLICIT |
| CLAIM-M1-008 | p.2; pp.64,73-75,138-139 | STRATEGY_CLAIM | The 61%-79% Fibonacci retracement zone, especially 79%, is used as an Optimal Trade Entry confluence area. | SOURCE_EXPLICIT |
| CLAIM-M1-009 | p.2 | STRATEGY_CLAIM | Entering nearer 61% is described as producing more opportunities and more drawdown; 79% fewer opportunities and smaller drawdown. | SOURCE_EXPLICIT |
| CLAIM-M1-010 | p.3; pp.70-72; pp.149-152 | FAILURE_CLAIM | The manual explicitly states that Order Blocks/79% do not work consistently across pairs or periods and may not be distinguishable ex ante. | SOURCE_EXPLICIT |
| CLAIM-M1-011 | pp.3-8; pp.120-123 | STRATEGY_CLAIM | Relative-strength/SMT divergence across correlated FX pairs or DXY is proposed as a directional signal. | SOURCE_EXPLICIT |
| CLAIM-M1-012 | p.3 | STRATEGY_CLAIM | M15 is presented from author experience as a productive timeframe for relative-strength divergence. | SOURCE_EXPLICIT |
| CLAIM-M1-013 | pp.8-10 | STRATEGY_CLAIM | Judas Swing combines Directional Premise, an abrupt counter-direction move and a London-morning time window before reversal. | SOURCE_EXPLICIT |
| CLAIM-M1-014 | p.9; pp.145-146 | STRATEGY_CLAIM | The source gives numeric intraday projections such as 30-50 pips, ADR-derived targets and fixed session windows. | SOURCE_EXPLICIT |
| CLAIM-M1-015 | pp.10-13 | MARKET_CLAIM | Clusters of repeated highs/lows are treated as liquidity pools likely to be swept. | SOURCE_EXPLICIT |
| CLAIM-M1-016 | pp.20-24; p.143 | PROCESS_CLAIM | The manual warns against chasing price after a strong move and prefers waiting for pullback/congestion. | SOURCE_EXPLICIT |
| CLAIM-M1-017 | p.23 | MARKET_CLAIM | Directional moves are described as alternating impulse/expansion and pullback/contraction phases. | SOURCE_EXPLICIT |
| CLAIM-M1-018 | pp.28-34; pp.81-83 | STRATEGY_CLAIM | Kill Zones are specified time windows where reversals are claimed to be more frequent. | SOURCE_EXPLICIT |
| CLAIM-M1-019 | pp.116-118 | STRATEGY_CLAIM | A 50% “fair value” mean-reversion concept is presented mainly for ranges rather than strong trends. | SOURCE_EXPLICIT |
| CLAIM-M1-020 | pp.70-72 | RESEARCH_CLAIM | The manual criticizes Order Block labels that change after seeing the outcome and states a predictive theory should give the same prediction from the same pre-event signals. | SOURCE_EXPLICIT |
| CLAIM-M1-021 | pp.70-72 | RESEARCH_CLAIM | The source recommends right-edge-hidden backtesting and emphasizes research over post-hoc chart explanation. | SOURCE_EXPLICIT |
| CLAIM-M1-022 | pp.138-139 | STRATEGY_CLAIM | A concrete OTE/Order-Block setup combines macro direction, deep retracement, prior-liquidity sweep, Order Block/session confluence, entry about 5 pips from the block, stop about 10 pips beyond it and take-profit at prior high/low. | SOURCE_EXPLICIT |
| CLAIM-M1-023 | pp.73-75; p.143 | REGIME_CLAIM | Higher timeframes H4/D1/W1 are used to determine dominant order flow/direction before lower-timeframe execution. | SOURCE_EXPLICIT |
| CLAIM-M1-024 | p.148 | DATA_CLAIM | High-impact events such as NFP/FOMC are described as capable of invalidating ordinary intraday technical models. | SOURCE_EXPLICIT |
| CLAIM-M1-025 | multiple; esp. pp.70-72 | RESEARCH_CLAIM | The observable OHLC pattern can be tested independently from the source narrative that institutions intentionally manipulate price to hunt stops. | PROJECT_INTERPRETATION |
| CLAIM-M1-026 | pp.149-152 | FAILURE_CLAIM | The note author reports checking examples and finding some advertised frequency/probability claims unsupported or below the stated rate. | SOURCE_EXPLICIT |

## Quantitative Claims
See `docs/research/claims/SOURCE_THRESHOLD_REGISTRY_V2_BATCH2.md`. Every external number is quarantined.

## Source Thresholds
No source threshold is Risk/production policy.

## Qualitative Claims
Preserved as claims with evidence class and ambiguity; not converted to truth.

## Strategy Claims
Six new candidates: Order Block/OTE, SMT divergence, Judas Swing, Asian-range sweep, range fair-value mean reversion, liquidity-void retest.

## Entry Claims
Captured only where source explicit. Missing entry semantics remain `UNDERSPECIFIED`.

## Exit Claims
Captured only where source explicit. No project exit is silently substituted.

## Risk Claims
No project Risk thresholds adopted. Many pip/percentage/time values quarantined.

## Portfolio Claims
No new portfolio contract is adopted from this source batch.

## Execution Claims
Only the 101-questions bracket/OCO semantics generated an execution improvement spec; runtime status remains UNKNOWN.

## Regime Claims
Preserved as hypotheses requiring ex-ante point-in-time regime classification.

## Process Claims
High-value ex-ante/right-edge methodology and explicit warning against changing interpretation after outcome.

## Behavioral Claims
Human psychology is translated only to observable system mechanisms. No agent is described as feeling fear, ego, greed or anxiety.

## Governance Claims
Separate observable OHLC patterns from causal “institutional manipulation” narrative.

## Failure Modes
Hindsight labeling; threshold copying; causal-story substitution; stale/HTF look-ahead; source/project rule mixing; outcome-based reclassification; cost blindness; post-entry rule drift.

## Unsupported Claims
Institutional intent, frequency/probability language, fixed OTE/session/pip values, some advertised 90% statements.

## Contradictions
Recorded rather than resolved by authority. Where the same source both promotes and criticizes a technique, the counter-evidence is preserved in the experiment design.

## Existing Project Capabilities
Only architecture/design notes were supplied in this ingestion environment. Runtime implementation/reachability is therefore `UNKNOWN`, even when a source insight aligns with TradeProposal, DecisionTrace, StrategyRouter, Risk, PostTrade or Verification concepts.

## Project Gaps
Determination deferred to SOURCE-RUNTIME RECONCILIATION. No `ALREADY_IMPLEMENTED` status is claimed from docs alone.

## Strategy Candidates
STRAT-CAND-011..016; IMP-SPEC-006..007; EXP-017..025.

## Improvement Specs
See candidate references above and updated INSIGHT_REGISTRY.

## Risk Specs
See candidate references above and updated INSIGHT_REGISTRY.

## Experiment Specs
Created as design-only artifacts. No experiment was executed in this ingestion phase.

## Negative Knowledge
See `docs/research/insights/NEGATIVE_KNOWLEDGE.md` additions NEG-016..NEG-025.

## Rejected Ideas
Literal transfer of human persuasion to agent confidence; post-hoc chart labeling; unsupported causal certainty; direct adoption of source thresholds; inferred rules for image-only patterns.

## Adoption Decisions
Alpha defaults to `EXPERIMENT` or `DEFER`. Platform/risk patterns may be `ADOPT_P0/P1` at SPEC level only; this is not implementation approval.

## Evidence References
Original supplied PDF + exact page locations in claim registry + deterministic SHA256 in run report/manifest.

## Final Assessment
High hypothesis density but low empirical authority. Best value is a combination of testable price-pattern candidates plus unusually strong negative knowledge about hindsight.
