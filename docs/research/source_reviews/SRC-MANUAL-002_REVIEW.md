# SOURCE REVIEW — SRC-MANUAL-002

## Metadata
- Title: Escuela de Traders — Las 101 preguntas que cambiarán tu trading para siempre
- Author: not stated in supplied PDF
- Year: circa 2017 based on internal temporal references; publication year not stated
- Type: TRADING_MANUAL
- Reliability: C/D practitioner manual; E for unsupported percentages/universal statistics
- File: `/mnt/data/101 preguntas y respuestas.pdf`

## Coverage
- Pages total: 136 PDF pages
- Pages reviewed: all PDF page objects
- Pages unreadable: 0 material pages; image-only content visually reviewed where applicable
- Figures/tables/charts reviewed: yes, via full-page renders/contact-sheet scan; chart-heavy sources received visual interpretation
- Coverage status: SOURCE_REVIEW_COMPLETE

## Source Thesis
Trading consistency is framed as a combination of a tested system, market/regime context, disciplined execution, money management and detailed review.

## Methodology
Practitioner Q&A/manual with textbook definitions, discretionary Mini S&P system rules, examples and personal experience. Many assertions lack citations.

## Markets / Assets
futures/day trading; risk/process/technical strategies

## Timeframes
As source-defined per claim/spec. No missing timeframe is invented.

## Source Evidence
Primarily practitioner narrative/examples unless otherwise noted. Evidence classification does not equal project validation.

## Source Limitations
Full 136-page visual scan. Numeric recommendations are quarantined. UI-specific volatility heuristics are not portable project rules.

## Relevant Claims
| CLAIM | LOCATION | TYPE | NORMALIZED CLAIM | RULE CLASS |
|---|---|---|---|---|
| CLAIM-Q1-001 | pp.20-27 | REGIME_CLAIM | Trend and range are treated as distinct regimes, and trend-following systems should avoid lateral markets. | SOURCE_EXPLICIT |
| CLAIM-Q1-002 | pp.76-78 | PROCESS_CLAIM | The manual decomposes a trading system into investment rules, psychotrading/process discipline and money management. | SOURCE_EXPLICIT |
| CLAIM-Q1-003 | pp.76-78 | RESEARCH_CLAIM | A trading method should have positive expectancy and be tested rather than adopted on description alone. | SOURCE_EXPLICIT |
| CLAIM-Q1-004 | pp.78-81 | PROCESS_CLAIM | An opening protocol/checklist uses economic calendar, multi-timeframe charting and context before allowing entries. | SOURCE_EXPLICIT |
| CLAIM-Q1-005 | pp.82-83 | REGIME_CLAIM | “Batidora” is a range-bound opening condition in which the presented trend-following system explicitly says NO_TRADE. | SOURCE_EXPLICIT |
| CLAIM-Q1-006 | p.84 | REGIME_CLAIM | “Conejito Duracell” describes a strongly directional opening regime. | SOURCE_EXPLICIT |
| CLAIM-Q1-007 | pp.85-86 | STRATEGY_CLAIM | “No Name” describes a fast move to preidentified support/resistance, a false break/test and reversal. | SOURCE_EXPLICIT |
| CLAIM-Q1-008 | p.87 | STRATEGY_CLAIM | “Juan Tamariz” describes sequential false breaks on both sides of a range before later movement. | SOURCE_EXPLICIT |
| CLAIM-Q1-009 | pp.88-89 | DATA_CLAIM | The Speed indicator is used as a volume/acceleration cue, especially near open/close. | SOURCE_EXPLICIT |
| CLAIM-Q1-010 | pp.90-91 | STRATEGY_CLAIM | S1 fades an aggressive early opening move when a 3-minute subrange is 6-10 points, open is near its middle, move occurs in first 15-20 minutes and Speed exceeds 3000. | SOURCE_EXPLICIT |
| CLAIM-Q1-011 | pp.92-94 | STRATEGY_CLAIM | S2 enters with the trend on a pullback after breakout/impulse, using a roughly 25%-61% retracement zone. | SOURCE_EXPLICIT |
| CLAIM-Q1-012 | pp.95-96 | RISK_CLAIM | Entry/stop distance should adapt to market volatility rather than stay fixed. | SOURCE_EXPLICIT |
| CLAIM-Q1-013 | pp.95-96 | RISK_CLAIM | The source proposes a chart-axis increment heuristic to choose stops/retracement levels. | SOURCE_EXPLICIT |
| CLAIM-Q1-014 | pp.32-33 | STRATEGY_CLAIM | Pivot levels are proposed both for quick countertrend fades on first contact and for breakout continuation after a level is crossed. | SOURCE_EXPLICIT |
| CLAIM-Q1-015 | pp.38-39 | EXECUTION_CLAIM | Protective stops limit adverse movement; bracket orders atomically pair entry with stop and profit target, canceling the remaining exit when one fills. | SOURCE_EXPLICIT |
| CLAIM-Q1-016 | p.37 | RISK_CLAIM | Position size should only be increased when price has moved favorably; averaging down a losing position is strongly discouraged for novices. | SOURCE_EXPLICIT |
| CLAIM-Q1-017 | pp.105-107 | RISK_CLAIM | Money management is treated as the mechanism that determines how much risk to take and as necessary for survival. | SOURCE_EXPLICIT |
| CLAIM-Q1-018 | p.106 | RISK_CLAIM | The author suggests 1%-3% maximum daily loss, closer to 1% preferred, while acknowledging generalization is difficult and others use larger values. | SOURCE_EXPLICIT |
| CLAIM-Q1-019 | pp.108-110 | OBSERVABILITY_CLAIM | Drawdown should be measured against prior equity peak and investigated by cause, duration, execution quality, slippage and risk sizing. | SOURCE_EXPLICIT |
| CLAIM-Q1-020 | pp.110-113 | RISK_CLAIM | During an abnormal losing streak, the manual recommends reducing exposure and, if necessary, stopping trading to analyze the cause. | SOURCE_EXPLICIT |
| CLAIM-Q1-021 | p.114 | RISK_CLAIM | Recovery from percentage drawdown is asymmetric: the required gain exceeds the loss percentage as drawdown grows. | SOURCE_EXPLICIT |
| CLAIM-Q1-022 | pp.115-116 | FAILURE_CLAIM | Overleverage, overtrading and lack of journaling are presented as major failure modes. | SOURCE_EXPLICIT |
| CLAIM-Q1-023 | pp.116-121 | OBSERVABILITY_CLAIM | A trading journal should record why trades were opened/closed and whether the process was followed. | SOURCE_EXPLICIT |
| CLAIM-Q1-024 | pp.118-121 | BEHAVIOR_CLAIM | Human failures include moving stops, holding losers, taking profits prematurely, averaging down, oversizing, changing horizon to avoid a stop and increasing leverage after wins. | SOURCE_EXPLICIT |
| CLAIM-Q1-025 | pp.118-121 | PROCESS_CLAIM | Correct process and losing outcome can coexist; focus should be on controllable execution rather than any single trade result. | SOURCE_EXPLICIT |
| CLAIM-Q1-026 | multiple; incl. intro, pp.20,116 | RESEARCH_CLAIM | Unreferenced statistics such as survival rates or percentage of time in ranges are source assertions, not project evidence. | PROJECT_INTERPRETATION |
| CLAIM-Q1-027 | pp.39,118-121 | EXECUTION_CLAIM | Precommitted stop/target OCO semantics can reduce unauthorized post-entry drift if enforced by deterministic execution. | PROJECT_INTERPRETATION |
| CLAIM-Q1-028 | pp.102-103 | PROCESS_CLAIM | A checklist of observable rule adherence can be updated from repeated errors and reviewed one behavior at a time. | SOURCE_EXPLICIT |

## Quantitative Claims
See `docs/research/claims/SOURCE_THRESHOLD_REGISTRY_V2_BATCH2.md`. Every external number is quarantined.

## Source Thresholds
No source threshold is Risk/production policy.

## Qualitative Claims
Preserved as claims with evidence class and ambiguity; not converted to truth.

## Strategy Claims
Four direct candidates (S1, S2, pivot fade, pivot breakout) plus an opening-regime/no-trade filter hypothesis.

## Entry Claims
Captured only where source explicit. Missing entry semantics remain `UNDERSPECIFIED`.

## Exit Claims
Captured only where source explicit. No project exit is silently substituted.

## Risk Claims
Two new specs: daily-loss circuit breaker validation and drawdown deleveraging/halt. Source percentages remain quarantined.

## Portfolio Claims
No new portfolio contract is adopted from this source batch.

## Execution Claims
Only the 101-questions bracket/OCO semantics generated an execution improvement spec; runtime status remains UNKNOWN.

## Regime Claims
Preserved as hypotheses requiring ex-ante point-in-time regime classification.

## Process Claims
Opening checklist, journal/conformance checks, process-vs-outcome separation, no-trade discipline.

## Behavioral Claims
Human psychology is translated only to observable system mechanisms. No agent is described as feeling fear, ego, greed or anxiety.

## Governance Claims
Protective OCO/bracket semantics suggest an execution-safety audit, not automatic implementation.

## Failure Modes
Hindsight labeling; threshold copying; causal-story substitution; stale/HTF look-ahead; source/project rule mixing; outcome-based reclassification; cost blindness; post-entry rule drift.

## Unsupported Claims
10% survival, 70% range share, fixed risk/stop values and UI-axis volatility heuristics are not accepted as evidence.

## Contradictions
Recorded rather than resolved by authority. Where the same source both promotes and criticizes a technique, the counter-evidence is preserved in the experiment design.

## Existing Project Capabilities
Only architecture/design notes were supplied in this ingestion environment. Runtime implementation/reachability is therefore `UNKNOWN`, even when a source insight aligns with TradeProposal, DecisionTrace, StrategyRouter, Risk, PostTrade or Verification concepts.

## Project Gaps
Determination deferred to SOURCE-RUNTIME RECONCILIATION. No `ALREADY_IMPLEMENTED` status is claimed from docs alone.

## Strategy Candidates
STRAT-CAND-017..020; IMP-SPEC-008; RISK-SPEC-005..006; EXP-026..034.

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
Useful mixed manual: strongest project value is risk/process discipline and several testable Mini S&P/pivot candidates. Numeric advice requires project validation.
