# SOURCE REVIEW — SRC-BOOK-001

## Metadata

- Title: *Trading Room: La especulación inteligente*
- Author: Alejandro de Luis
- Edition: RA-MA e-book, 2014; ISBN 978-84-9964-360-1
- Type: BOOK
- Evidence level: C overall; many numerical claims are D/E because no empirical source or replication is supplied.
- Domain: technical/discretionary trading, process, risk, chart patterns, indicators, money management.

## Coverage

- PDF pages total: 162
- PDF pages reviewed: 162
- Chapters total: 6 plus introduction/index
- Chapters reviewed: 6/6 plus introduction and final advice
- Coverage percent: 100% of supplied PDF pages visually scanned; text layer extracted for all pages; figure-heavy strategy/exam pages visually checked against the extracted text.
- Review status: SOURCE_REVIEW_COMPLETE for the source itself. Project-runtime equivalence remains separately unverified because repository source code was not supplied.

## Thesis

The book argues that successful trading requires a predefined process, strict loss control, alignment with market trend/regime, technical setups that wait for confirmation, and disciplined review. It also proposes several concrete technical strategies and many fixed numeric thresholds. For Trading Agentic Portable, the useful material is split into process/risk mechanisms and strategy hypotheses; the fixed thresholds and broad market statistics are not treated as operational truth.

## Relevant Claims

### CLAIM-TR-001
- Type: `PROCESS_CLAIM`
- Evidence location: printed pp. 17-18 (PDF pp. 18-19)
- SOURCE: Automating/mechanizing entry and exit rules is recommended to reduce emotion-driven deviation.
- Source-extraction confidence: high
- Source evidence class for this claim: C
- PROJECT INTERPRETATION: Translate human discipline into deterministic contracts, traceability, rule-conformance and post-trade evidence; do not anthropomorphize agents.
- CURRENT PROJECT: supplied VNext notes already define deterministic risk, evidence, verifier, decision tracing/memory and strategy/regime concepts at architecture level; runtime implementation is not proven by those notes.
- GAP: source-code/runtime evidence was not supplied, so duplication can only be checked against architecture/RFC notes.
- DECISION: see INSIGHT_REGISTRY and linked SPEC/EXPERIMENT; no direct runtime adoption.

### CLAIM-TR-002
- Type: `REGIME_CLAIM`
- Evidence location: printed pp. 24-25 (PDF pp. 25-26)
- SOURCE: Market “climate”/trend should be identified before trading; lateral conditions are treated differently from strong trends.
- Source-extraction confidence: high
- Source evidence class for this claim: C
- PROJECT INTERPRETATION: Treat as a testable research hypothesis/strategy candidate. Preserve source rules where explicit; mark missing definitions as UNSPECIFIED_BY_SOURCE.
- CURRENT PROJECT: supplied VNext notes already define deterministic risk, evidence, verifier, decision tracing/memory and strategy/regime concepts at architecture level; runtime implementation is not proven by those notes.
- GAP: source-code/runtime evidence was not supplied, so duplication can only be checked against architecture/RFC notes.
- DECISION: see INSIGHT_REGISTRY and linked SPEC/EXPERIMENT; no direct runtime adoption.

### CLAIM-TR-003
- Type: `DATA_CLAIM`
- Evidence location: printed pp. 26-27 (PDF pp. 27-28)
- SOURCE: Different markets have different characteristics and risk; a method should fit the market/terrain.
- Source-extraction confidence: high
- Source evidence class for this claim: C
- PROJECT INTERPRETATION: Record as source claim; require independent empirical evidence before adoption.
- CURRENT PROJECT: supplied VNext notes already define deterministic risk, evidence, verifier, decision tracing/memory and strategy/regime concepts at architecture level; runtime implementation is not proven by those notes.
- GAP: source-code/runtime evidence was not supplied, so duplication can only be checked against architecture/RFC notes.
- DECISION: see INSIGHT_REGISTRY and linked SPEC/EXPERIMENT; no direct runtime adoption.

### CLAIM-TR-004
- Type: `PROCESS_CLAIM`
- Evidence location: printed pp. 29-30 (PDF pp. 30-31)
- SOURCE: A trader should operate from a defined system with entry and exit rules rather than improvisation.
- Source-extraction confidence: high
- Source evidence class for this claim: C
- PROJECT INTERPRETATION: Translate human discipline into deterministic contracts, traceability, rule-conformance and post-trade evidence; do not anthropomorphize agents.
- CURRENT PROJECT: supplied VNext notes already define deterministic risk, evidence, verifier, decision tracing/memory and strategy/regime concepts at architecture level; runtime implementation is not proven by those notes.
- GAP: source-code/runtime evidence was not supplied, so duplication can only be checked against architecture/RFC notes.
- DECISION: see INSIGHT_REGISTRY and linked SPEC/EXPERIMENT; no direct runtime adoption.

### CLAIM-TR-005
- Type: `RISK_CLAIM`
- Evidence location: printed pp. 30-33 (PDF pp. 31-34)
- SOURCE: Stop-loss discipline is presented as a protection against a single large loss overwhelming many winners.
- Source-extraction confidence: high
- Source evidence class for this claim: C
- PROJECT INTERPRETATION: Translate human discipline into deterministic contracts, traceability, rule-conformance and post-trade evidence; do not anthropomorphize agents.
- CURRENT PROJECT: supplied VNext notes already define deterministic risk, evidence, verifier, decision tracing/memory and strategy/regime concepts at architecture level; runtime implementation is not proven by those notes.
- GAP: source-code/runtime evidence was not supplied, so duplication can only be checked against architecture/RFC notes.
- DECISION: see INSIGHT_REGISTRY and linked SPEC/EXPERIMENT; no direct runtime adoption.

### CLAIM-TR-006
- Type: `STRATEGY_CLAIM`
- Evidence location: printed pp. 39-40 (PDF pp. 40-41)
- SOURCE: Put/call ratio is proposed as a sentiment/contrarian indicator; fixed 1.1 and 0.7 thresholds are suggested.
- Source-extraction confidence: high
- Source evidence class for this claim: D
- PROJECT INTERPRETATION: Treat as a testable research hypothesis/strategy candidate. Preserve source rules where explicit; mark missing definitions as UNSPECIFIED_BY_SOURCE.
- CURRENT PROJECT: supplied VNext notes already define deterministic risk, evidence, verifier, decision tracing/memory and strategy/regime concepts at architecture level; runtime implementation is not proven by those notes.
- GAP: source-code/runtime evidence was not supplied, so duplication can only be checked against architecture/RFC notes.
- DECISION: see INSIGHT_REGISTRY and linked SPEC/EXPERIMENT; no direct runtime adoption.

### CLAIM-TR-007
- Type: `MARKET_CLAIM`
- Evidence location: printed pp. 41-52 (PDF pp. 42-53)
- SOURCE: The book attributes repeatable price patterns to crowd psychology and presents technical analysis as a way to exploit them.
- Source-extraction confidence: high
- Source evidence class for this claim: D
- PROJECT INTERPRETATION: Record as source claim; require independent empirical evidence before adoption.
- CURRENT PROJECT: supplied VNext notes already define deterministic risk, evidence, verifier, decision tracing/memory and strategy/regime concepts at architecture level; runtime implementation is not proven by those notes.
- GAP: source-code/runtime evidence was not supplied, so duplication can only be checked against architecture/RFC notes.
- DECISION: see INSIGHT_REGISTRY and linked SPEC/EXPERIMENT; no direct runtime adoption.

### CLAIM-TR-008
- Type: `STRATEGY_CLAIM`
- Evidence location: printed pp. 58-60 (PDF pp. 59-61)
- SOURCE: Trend direction is defined through rising/falling swings; volume is proposed as a trend-strength confirmation.
- Source-extraction confidence: high
- Source evidence class for this claim: C
- PROJECT INTERPRETATION: Treat as a testable research hypothesis/strategy candidate. Preserve source rules where explicit; mark missing definitions as UNSPECIFIED_BY_SOURCE.
- CURRENT PROJECT: supplied VNext notes already define deterministic risk, evidence, verifier, decision tracing/memory and strategy/regime concepts at architecture level; runtime implementation is not proven by those notes.
- GAP: source-code/runtime evidence was not supplied, so duplication can only be checked against architecture/RFC notes.
- DECISION: see INSIGHT_REGISTRY and linked SPEC/EXPERIMENT; no direct runtime adoption.

### CLAIM-TR-009
- Type: `STRATEGY_CLAIM`
- Evidence location: printed pp. 61-62 (PDF pp. 62-63)
- SOURCE: Multiple timeframes should be coordinated; higher-order trend is expected eventually to dominate lower-order moves.
- Source-extraction confidence: high
- Source evidence class for this claim: C
- PROJECT INTERPRETATION: Treat as a testable research hypothesis/strategy candidate. Preserve source rules where explicit; mark missing definitions as UNSPECIFIED_BY_SOURCE.
- CURRENT PROJECT: supplied VNext notes already define deterministic risk, evidence, verifier, decision tracing/memory and strategy/regime concepts at architecture level; runtime implementation is not proven by those notes.
- GAP: source-code/runtime evidence was not supplied, so duplication can only be checked against architecture/RFC notes.
- DECISION: see INSIGHT_REGISTRY and linked SPEC/EXPERIMENT; no direct runtime adoption.

### CLAIM-TR-010
- Type: `STRATEGY_CLAIM`
- Evidence location: printed pp. 63-66 (PDF pp. 64-67)
- SOURCE: Support/resistance zones strengthen with repeated tests and time; broken resistance may act as support.
- Source-extraction confidence: high
- Source evidence class for this claim: C
- PROJECT INTERPRETATION: Treat as a testable research hypothesis/strategy candidate. Preserve source rules where explicit; mark missing definitions as UNSPECIFIED_BY_SOURCE.
- CURRENT PROJECT: supplied VNext notes already define deterministic risk, evidence, verifier, decision tracing/memory and strategy/regime concepts at architecture level; runtime implementation is not proven by those notes.
- GAP: source-code/runtime evidence was not supplied, so duplication can only be checked against architecture/RFC notes.
- DECISION: see INSIGHT_REGISTRY and linked SPEC/EXPERIMENT; no direct runtime adoption.

### CLAIM-TR-011
- Type: `STRATEGY_CLAIM`
- Evidence location: printed pp. 68-73 (PDF pp. 69-74)
- SOURCE: Head-and-shoulders reversal is entered after neckline confirmation; target is measured from head to neckline; stop beyond right shoulder; volume is used as confirmation.
- Source-extraction confidence: high
- Source evidence class for this claim: C
- PROJECT INTERPRETATION: Treat as a testable research hypothesis/strategy candidate. Preserve source rules where explicit; mark missing definitions as UNSPECIFIED_BY_SOURCE.
- CURRENT PROJECT: supplied VNext notes already define deterministic risk, evidence, verifier, decision tracing/memory and strategy/regime concepts at architecture level; runtime implementation is not proven by those notes.
- GAP: source-code/runtime evidence was not supplied, so duplication can only be checked against architecture/RFC notes.
- DECISION: see INSIGHT_REGISTRY and linked SPEC/EXPERIMENT; no direct runtime adoption.

### CLAIM-TR-012
- Type: `STRATEGY_CLAIM`
- Evidence location: printed pp. 73-89 (PDF pp. 74-90)
- SOURCE: Several chart patterns are treated probabilistically; breakout direction and volume confirmation matter more than pattern label alone.
- Source-extraction confidence: high
- Source evidence class for this claim: C
- PROJECT INTERPRETATION: Treat as a testable research hypothesis/strategy candidate. Preserve source rules where explicit; mark missing definitions as UNSPECIFIED_BY_SOURCE.
- CURRENT PROJECT: supplied VNext notes already define deterministic risk, evidence, verifier, decision tracing/memory and strategy/regime concepts at architecture level; runtime implementation is not proven by those notes.
- GAP: source-code/runtime evidence was not supplied, so duplication can only be checked against architecture/RFC notes.
- DECISION: see INSIGHT_REGISTRY and linked SPEC/EXPERIMENT; no direct runtime adoption.

### CLAIM-TR-013
- Type: `STRATEGY_CLAIM`
- Evidence location: printed pp. 89-90 (PDF pp. 90-91)
- SOURCE: A pullback to the breakout zone, preferably on lower volume, is treated as confirmation.
- Source-extraction confidence: high
- Source evidence class for this claim: C
- PROJECT INTERPRETATION: Treat as a testable research hypothesis/strategy candidate. Preserve source rules where explicit; mark missing definitions as UNSPECIFIED_BY_SOURCE.
- CURRENT PROJECT: supplied VNext notes already define deterministic risk, evidence, verifier, decision tracing/memory and strategy/regime concepts at architecture level; runtime implementation is not proven by those notes.
- GAP: source-code/runtime evidence was not supplied, so duplication can only be checked against architecture/RFC notes.
- DECISION: see INSIGHT_REGISTRY and linked SPEC/EXPERIMENT; no direct runtime adoption.

### CLAIM-TR-014
- Type: `STRATEGY_CLAIM`
- Evidence location: printed pp. 90-93 (PDF pp. 91-94)
- SOURCE: Patterns should not be anticipated; a breakout should be confirmed. The book suggests a universal 3% filter and/or two closes.
- Source-extraction confidence: high
- Source evidence class for this claim: D
- PROJECT INTERPRETATION: Treat as a testable research hypothesis/strategy candidate. Preserve source rules where explicit; mark missing definitions as UNSPECIFIED_BY_SOURCE.
- CURRENT PROJECT: supplied VNext notes already define deterministic risk, evidence, verifier, decision tracing/memory and strategy/regime concepts at architecture level; runtime implementation is not proven by those notes.
- GAP: source-code/runtime evidence was not supplied, so duplication can only be checked against architecture/RFC notes.
- DECISION: see INSIGHT_REGISTRY and linked SPEC/EXPERIMENT; no direct runtime adoption.

### CLAIM-TR-015
- Type: `PROCESS_CLAIM`
- Evidence location: printed pp. 96-97 (PDF pp. 97-98)
- SOURCE: A trading system should explicitly answer when to enter, exit and do nothing; the exit should remain governed by the system that generated the entry.
- Source-extraction confidence: high
- Source evidence class for this claim: C
- PROJECT INTERPRETATION: Translate human discipline into deterministic contracts, traceability, rule-conformance and post-trade evidence; do not anthropomorphize agents.
- CURRENT PROJECT: supplied VNext notes already define deterministic risk, evidence, verifier, decision tracing/memory and strategy/regime concepts at architecture level; runtime implementation is not proven by those notes.
- GAP: source-code/runtime evidence was not supplied, so duplication can only be checked against architecture/RFC notes.
- DECISION: see INSIGHT_REGISTRY and linked SPEC/EXPERIMENT; no direct runtime adoption.

### CLAIM-TR-016
- Type: `STRATEGY_CLAIM`
- Evidence location: printed pp. 97-99 (PDF pp. 98-100)
- SOURCE: For a chosen execution timeframe, higher timeframes are used to align trend; trading is deferred when timeframes disagree.
- Source-extraction confidence: high
- Source evidence class for this claim: C
- PROJECT INTERPRETATION: Treat as a testable research hypothesis/strategy candidate. Preserve source rules where explicit; mark missing definitions as UNSPECIFIED_BY_SOURCE.
- CURRENT PROJECT: supplied VNext notes already define deterministic risk, evidence, verifier, decision tracing/memory and strategy/regime concepts at architecture level; runtime implementation is not proven by those notes.
- GAP: source-code/runtime evidence was not supplied, so duplication can only be checked against architecture/RFC notes.
- DECISION: see INSIGHT_REGISTRY and linked SPEC/EXPERIMENT; no direct runtime adoption.

### CLAIM-TR-017
- Type: `STRATEGY_CLAIM`
- Evidence location: printed pp. 99-105 (PDF pp. 100-106)
- SOURCE: 20/40/200 moving averages are used to define trend; entries use first pullback to MA20 after MA20/40 cross, optional prior swing break; exit on MA40 break.
- Source-extraction confidence: high
- Source evidence class for this claim: C
- PROJECT INTERPRETATION: Treat as a testable research hypothesis/strategy candidate. Preserve source rules where explicit; mark missing definitions as UNSPECIFIED_BY_SOURCE.
- CURRENT PROJECT: supplied VNext notes already define deterministic risk, evidence, verifier, decision tracing/memory and strategy/regime concepts at architecture level; runtime implementation is not proven by those notes.
- GAP: source-code/runtime evidence was not supplied, so duplication can only be checked against architecture/RFC notes.
- DECISION: see INSIGHT_REGISTRY and linked SPEC/EXPERIMENT; no direct runtime adoption.

### CLAIM-TR-018
- Type: `STRATEGY_CLAIM`
- Evidence location: printed pp. 105-113 (PDF pp. 106-114)
- SOURCE: MACD strategy: trade with zero-line regime, use base/signal cross, require three-bar persistence, exit on recross; zero-line cross is another signal.
- Source-extraction confidence: high
- Source evidence class for this claim: C
- PROJECT INTERPRETATION: Treat as a testable research hypothesis/strategy candidate. Preserve source rules where explicit; mark missing definitions as UNSPECIFIED_BY_SOURCE.
- CURRENT PROJECT: supplied VNext notes already define deterministic risk, evidence, verifier, decision tracing/memory and strategy/regime concepts at architecture level; runtime implementation is not proven by those notes.
- GAP: source-code/runtime evidence was not supplied, so duplication can only be checked against architecture/RFC notes.
- DECISION: see INSIGHT_REGISTRY and linked SPEC/EXPERIMENT; no direct runtime adoption.

### CLAIM-TR-019
- Type: `STRATEGY_CLAIM`
- Evidence location: printed pp. 111-113 (PDF pp. 112-114)
- SOURCE: MACD divergence may justify counter-trend trade only after structural break with stop beyond recent swing; the book claims ~85% eventual move without empirical support shown.
- Source-extraction confidence: high
- Source evidence class for this claim: D/E
- PROJECT INTERPRETATION: Treat as a testable research hypothesis/strategy candidate. Preserve source rules where explicit; mark missing definitions as UNSPECIFIED_BY_SOURCE.
- CURRENT PROJECT: supplied VNext notes already define deterministic risk, evidence, verifier, decision tracing/memory and strategy/regime concepts at architecture level; runtime implementation is not proven by those notes.
- GAP: source-code/runtime evidence was not supplied, so duplication can only be checked against architecture/RFC notes.
- DECISION: see INSIGHT_REGISTRY and linked SPEC/EXPERIMENT; no direct runtime adoption.

### CLAIM-TR-020
- Type: `STRATEGY_CLAIM`
- Evidence location: printed pp. 114-119 (PDF pp. 115-120)
- SOURCE: Candle pullback strategy in MA20/40/200 trend: 3-6 counter-trend candles into MA20-40 zone, break prior candle with 1/9 filter, stop 1/9 beyond swing, target prior swing, source requires 3:1 reward/risk.
- Source-extraction confidence: high
- Source evidence class for this claim: D
- PROJECT INTERPRETATION: Treat as a testable research hypothesis/strategy candidate. Preserve source rules where explicit; mark missing definitions as UNSPECIFIED_BY_SOURCE.
- CURRENT PROJECT: supplied VNext notes already define deterministic risk, evidence, verifier, decision tracing/memory and strategy/regime concepts at architecture level; runtime implementation is not proven by those notes.
- GAP: source-code/runtime evidence was not supplied, so duplication can only be checked against architecture/RFC notes.
- DECISION: see INSIGHT_REGISTRY and linked SPEC/EXPERIMENT; no direct runtime adoption.

### CLAIM-TR-021
- Type: `STRATEGY_CLAIM`
- Evidence location: printed pp. 119-122 (PDF pp. 120-123)
- SOURCE: Trend support/resistance pullbacks are filtered with Fibonacci 38%/50% retracements.
- Source-extraction confidence: high
- Source evidence class for this claim: D
- PROJECT INTERPRETATION: Treat as a testable research hypothesis/strategy candidate. Preserve source rules where explicit; mark missing definitions as UNSPECIFIED_BY_SOURCE.
- CURRENT PROJECT: supplied VNext notes already define deterministic risk, evidence, verifier, decision tracing/memory and strategy/regime concepts at architecture level; runtime implementation is not proven by those notes.
- GAP: source-code/runtime evidence was not supplied, so duplication can only be checked against architecture/RFC notes.
- DECISION: see INSIGHT_REGISTRY and linked SPEC/EXPERIMENT; no direct runtime adoption.

### CLAIM-TR-022
- Type: `REGIME_CLAIM`
- Evidence location: printed pp. 122-125 (PDF pp. 123-126)
- SOURCE: A separate range strategy is proposed for lateral markets using support/resistance plus RSI, stochastic and CCI consensus; CCI ±100 is used as trigger.
- Source-extraction confidence: high
- Source evidence class for this claim: D
- PROJECT INTERPRETATION: Treat as a testable research hypothesis/strategy candidate. Preserve source rules where explicit; mark missing definitions as UNSPECIFIED_BY_SOURCE.
- CURRENT PROJECT: supplied VNext notes already define deterministic risk, evidence, verifier, decision tracing/memory and strategy/regime concepts at architecture level; runtime implementation is not proven by those notes.
- GAP: source-code/runtime evidence was not supplied, so duplication can only be checked against architecture/RFC notes.
- DECISION: see INSIGHT_REGISTRY and linked SPEC/EXPERIMENT; no direct runtime adoption.

### CLAIM-TR-023
- Type: `RISK_CLAIM`
- Evidence location: printed pp. 125-126 (PDF pp. 126-127)
- SOURCE: The book proposes fixed 1-5-15 and intraday 1-15-45 position/market exposure rules.
- Source-extraction confidence: high
- Source evidence class for this claim: D/E
- PROJECT INTERPRETATION: Map to a deterministic Risk/Portfolio spec. Source thresholds/examples are hypotheses, never production limits.
- CURRENT PROJECT: supplied VNext notes already define deterministic risk, evidence, verifier, decision tracing/memory and strategy/regime concepts at architecture level; runtime implementation is not proven by those notes.
- GAP: source-code/runtime evidence was not supplied, so duplication can only be checked against architecture/RFC notes.
- DECISION: see INSIGHT_REGISTRY and linked SPEC/EXPERIMENT; no direct runtime adoption.

### CLAIM-TR-024
- Type: `STRATEGY_CLAIM`
- Evidence location: printed pp. 127-128 (PDF pp. 128-129)
- SOURCE: Pair trade: when historically correlated assets diverge, buy the relatively weak/cheap leg and short the other expecting reconvergence; source gives 4% deviation stop example.
- Source-extraction confidence: high
- Source evidence class for this claim: D
- PROJECT INTERPRETATION: Treat as a testable research hypothesis/strategy candidate. Preserve source rules where explicit; mark missing definitions as UNSPECIFIED_BY_SOURCE.
- CURRENT PROJECT: supplied VNext notes already define deterministic risk, evidence, verifier, decision tracing/memory and strategy/regime concepts at architecture level; runtime implementation is not proven by those notes.
- GAP: source-code/runtime evidence was not supplied, so duplication can only be checked against architecture/RFC notes.
- DECISION: see INSIGHT_REGISTRY and linked SPEC/EXPERIMENT; no direct runtime adoption.

### CLAIM-TR-025
- Type: `PORTFOLIO_CLAIM`
- Evidence location: printed pp. 128-129 (PDF pp. 129-130)
- SOURCE: Hedging with an opposite derivative position is presented as offsetting portfolio price movement.
- Source-extraction confidence: high
- Source evidence class for this claim: D
- PROJECT INTERPRETATION: Map to a deterministic Risk/Portfolio spec. Source thresholds/examples are hypotheses, never production limits.
- CURRENT PROJECT: supplied VNext notes already define deterministic risk, evidence, verifier, decision tracing/memory and strategy/regime concepts at architecture level; runtime implementation is not proven by those notes.
- GAP: source-code/runtime evidence was not supplied, so duplication can only be checked against architecture/RFC notes.
- DECISION: see INSIGHT_REGISTRY and linked SPEC/EXPERIMENT; no direct runtime adoption.

### CLAIM-TR-026
- Type: `RISK_CLAIM`
- Evidence location: printed pp. 129-130 (PDF pp. 130-131)
- SOURCE: Leverage magnifies both gains and losses; the book cautions inexperienced traders against it.
- Source-extraction confidence: high
- Source evidence class for this claim: C
- PROJECT INTERPRETATION: Map to a deterministic Risk/Portfolio spec. Source thresholds/examples are hypotheses, never production limits.
- CURRENT PROJECT: supplied VNext notes already define deterministic risk, evidence, verifier, decision tracing/memory and strategy/regime concepts at architecture level; runtime implementation is not proven by those notes.
- GAP: source-code/runtime evidence was not supplied, so duplication can only be checked against architecture/RFC notes.
- DECISION: see INSIGHT_REGISTRY and linked SPEC/EXPERIMENT; no direct runtime adoption.

### CLAIM-TR-027
- Type: `PROCESS_CLAIM`
- Evidence location: printed pp. 131-149 (PDF pp. 132-150)
- SOURCE: Exercises repeatedly reinforce waiting for confirmation, respecting the original stop/system, and distinguishing textbook-looking patterns from unknown future data.
- Source-extraction confidence: high
- Source evidence class for this claim: C
- PROJECT INTERPRETATION: Record as source claim; require independent empirical evidence before adoption.
- CURRENT PROJECT: supplied VNext notes already define deterministic risk, evidence, verifier, decision tracing/memory and strategy/regime concepts at architecture level; runtime implementation is not proven by those notes.
- GAP: source-code/runtime evidence was not supplied, so duplication can only be checked against architecture/RFC notes.
- DECISION: see INSIGHT_REGISTRY and linked SPEC/EXPERIMENT; no direct runtime adoption.

### CLAIM-TR-028
- Type: `PROCESS_CLAIM`
- Evidence location: printed p. 151 (PDF p. 152)
- SOURCE: Maintain a trading journal recording asset, entry, stop, target, strategy modifications, reason, result and mistakes.
- Source-extraction confidence: high
- Source evidence class for this claim: C
- PROJECT INTERPRETATION: Translate human discipline into deterministic contracts, traceability, rule-conformance and post-trade evidence; do not anthropomorphize agents.
- CURRENT PROJECT: supplied VNext notes already define deterministic risk, evidence, verifier, decision tracing/memory and strategy/regime concepts at architecture level; runtime implementation is not proven by those notes.
- GAP: source-code/runtime evidence was not supplied, so duplication can only be checked against architecture/RFC notes.
- DECISION: see INSIGHT_REGISTRY and linked SPEC/EXPERIMENT; no direct runtime adoption.

### CLAIM-TR-029
- Type: `BEHAVIOR_CLAIM`
- Evidence location: printed pp. 152-154 (PDF pp. 153-155)
- SOURCE: A profitable rule-breaking trade can reinforce future protocol violations; the book warns that process deviation can escalate risk-taking.
- Source-extraction confidence: high
- Source evidence class for this claim: C
- PROJECT INTERPRETATION: Translate human discipline into deterministic contracts, traceability, rule-conformance and post-trade evidence; do not anthropomorphize agents.
- CURRENT PROJECT: supplied VNext notes already define deterministic risk, evidence, verifier, decision tracing/memory and strategy/regime concepts at architecture level; runtime implementation is not proven by those notes.
- GAP: source-code/runtime evidence was not supplied, so duplication can only be checked against architecture/RFC notes.
- DECISION: see INSIGHT_REGISTRY and linked SPEC/EXPERIMENT; no direct runtime adoption.

### CLAIM-TR-030
- Type: `BEHAVIOR_CLAIM`
- Evidence location: printed p. 154 (PDF p. 155)
- SOURCE: The book claims a routine generally forms after about one month of conscious repetition.
- Source-extraction confidence: high
- Source evidence class for this claim: E
- PROJECT INTERPRETATION: Record as source claim; require independent empirical evidence before adoption.
- CURRENT PROJECT: supplied VNext notes already define deterministic risk, evidence, verifier, decision tracing/memory and strategy/regime concepts at architecture level; runtime implementation is not proven by those notes.
- GAP: source-code/runtime evidence was not supplied, so duplication can only be checked against architecture/RFC notes.
- DECISION: see INSIGHT_REGISTRY and linked SPEC/EXPERIMENT; no direct runtime adoption.

### CLAIM-TR-031
- Type: `MARKET_CLAIM`
- Evidence location: printed pp. 11-12, 31-38
- SOURCE: The book repeatedly states that only ~5% of traders make money and uses this to support contrarian reasoning. No primary empirical source is provided in the book.
- Source-extraction confidence: high
- Source evidence class for this claim: E
- PROJECT INTERPRETATION: Record as source claim; require independent empirical evidence before adoption.
- CURRENT PROJECT: supplied VNext notes already define deterministic risk, evidence, verifier, decision tracing/memory and strategy/regime concepts at architecture level; runtime implementation is not proven by those notes.
- GAP: source-code/runtime evidence was not supplied, so duplication can only be checked against architecture/RFC notes.
- DECISION: see INSIGHT_REGISTRY and linked SPEC/EXPERIMENT; no direct runtime adoption.

### CLAIM-TR-032
- Type: `MARKET_CLAIM`
- Evidence location: printed pp. 37-38
- SOURCE: The book infers that doing the opposite of the losing majority could yield ~95% successful entries. This inference does not follow from the population statistic.
- Source-extraction confidence: high
- Source evidence class for this claim: E
- PROJECT INTERPRETATION: Record as source claim; require independent empirical evidence before adoption.
- CURRENT PROJECT: supplied VNext notes already define deterministic risk, evidence, verifier, decision tracing/memory and strategy/regime concepts at architecture level; runtime implementation is not proven by those notes.
- GAP: source-code/runtime evidence was not supplied, so duplication can only be checked against architecture/RFC notes.
- DECISION: see INSIGHT_REGISTRY and linked SPEC/EXPERIMENT; no direct runtime adoption.

### CLAIM-TR-033
- Type: `RESEARCH_CLAIM`
- Evidence location: printed pp. 90, 134-135
- SOURCE: The book acknowledges pattern labels are probabilistic and real-time right-edge uncertainty is materially harder than textbook examples.
- Source-extraction confidence: high
- Source evidence class for this claim: C
- PROJECT INTERPRETATION: Record as source claim; require independent empirical evidence before adoption.
- CURRENT PROJECT: supplied VNext notes already define deterministic risk, evidence, verifier, decision tracing/memory and strategy/regime concepts at architecture level; runtime implementation is not proven by those notes.
- GAP: source-code/runtime evidence was not supplied, so duplication can only be checked against architecture/RFC notes.
- DECISION: see INSIGHT_REGISTRY and linked SPEC/EXPERIMENT; no direct runtime adoption.

### CLAIM-TR-034
- Type: `PROCESS_CLAIM`
- Evidence location: printed pp. 31-33, 96-99, 152-154
- SOURCE: Losses are treated as normal; the process should constrain them and avoid improvisation rather than seek a no-loss system.
- Source-extraction confidence: high
- Source evidence class for this claim: C
- PROJECT INTERPRETATION: Translate human discipline into deterministic contracts, traceability, rule-conformance and post-trade evidence; do not anthropomorphize agents.
- CURRENT PROJECT: supplied VNext notes already define deterministic risk, evidence, verifier, decision tracing/memory and strategy/regime concepts at architecture level; runtime implementation is not proven by those notes.
- GAP: source-code/runtime evidence was not supplied, so duplication can only be checked against architecture/RFC notes.
- DECISION: see INSIGHT_REGISTRY and linked SPEC/EXPERIMENT; no direct runtime adoption.

## Quantitative Claims

- Fixed put/call levels 1.1 / 0.7: source threshold -> HYPOTHESIS_TO_VALIDATE, not adopted.
- Universal 3% breakout filter / two closes: experiment only; 3% is not portable across asset/timeframe/volatility.
- Three-bar MACD persistence: source rule retained only inside candidate spec.
- “85%” MACD-divergence success: unsupported in-book; REJECT as evidence, may still motivate an experiment without assuming the rate.
- 1/9 candle filter and stop; 3:1 reward/risk: source-specific thresholds, not risk policy.
- Fibonacci 38% / 50% filters: experiment only.
- 1-5-15 and 1-15-45 money-management rules: explicitly quarantined from Risk policy.
- 4% pairs deviation stop: example only, not universal.
- ~5% winning-trader statistic and inferred 95% contrarian success: unsupported / logically invalid for strategy efficacy.
- “one month” routine formation: unsupported human-behavior threshold and not relevant to autonomous runtime policy.

## Qualitative Claims

- Predefine entry, exit and no-action conditions.
- Preserve strategy/rule provenance from proposal through exit.
- Wait for confirmation instead of anticipating patterns.
- Treat trend/range and market type as applicability conditions.
- Separate disciplined process quality from single-trade outcome.
- Keep a structured journal/post-trade record.

## Strategy Ideas

See `docs/research/strategy_specs/`. Ten candidates are created; all remain `STRATEGY_CANDIDATE`; no promotion was performed.

## Risk Ideas

See `docs/research/risk_specs/`. Stops, exposure, leverage and hedging are translated into deterministic validation specs; no source percentage is adopted.

## Process Ideas

- Rule conformance and decision-quality scoring independent of PnL.
- Structured post-trade journal mapped to DecisionTrace/Outcome/FailureMemory concepts.
- Entry/exit rule provenance to prevent strategy-switching after entry.
- Regime/asset applicability checks before strategy selection.

## Governance Ideas

- Human psychological advice is translated only into observable system invariants.
- Source claims never outrank runtime/test evidence.
- No automatic production promotion from book authority.

## Failure Modes

- Anticipating unconfirmed patterns.
- Switching systems mid-trade.
- Moving/omitting stops outside an explicit rule.
- Overexposure/leverage.
- Treating a lucky rule violation as good process.
- Applying trend strategies in ranges or vice versa.
- Fixed thresholds that ignore volatility/asset/timeframe.
- Backtest/right-edge hindsight bias illustrated by textbook chart examples.

## Unsupported Claims

- “95% of traders lose” as stated without source.
- Inference that acting opposite the majority produces ~95% winning entries.
- MACD described as the best medium-term predictor.
- Universal 85% divergence outcome.
- Technical analysis as indispensable dogma.
- Exact 1-month routine-formation rule.
- “Perfect” hedge with zero depreciation/revaluation without basis/cost/slippage considerations.

## Project Mapping

The strongest overlaps are with deterministic Risk, Strategy/Regime routing, DecisionTrace/Evidence, PostTrade/FailureMemory and independent verification already described in the supplied VNext architecture notes. Because repository source code is absent, these are marked `ARCH/RFC_MATCH_RUNTIME_UNVERIFIED`, not `ALREADY_IMPLEMENTED`.

## Existing Capabilities

Design-level only from supplied project notes: deterministic risk/execution boundary, specialist/regime/strategy concepts, evidence/trace, verifier, experience memory. No runtime assertion is made.

## Gaps

- No source repository/runtime authority map supplied for implementation equivalence.
- No empirical validation of the book strategies on target assets/timeframes/cost models.
- Many rules require formal, PIT-safe definitions before backtest.

## Strategy Candidates

- STRAT-CAND-001 MA20/40 pullback trend
- STRAT-CAND-002 multi-timeframe alignment filter
- STRAT-CAND-003 MACD regime crossover
- STRAT-CAND-004 MACD divergence + structure break
- STRAT-CAND-005 candle pullback 20/40/200
- STRAT-CAND-006 support/resistance + Fibonacci pullback
- STRAT-CAND-007 range oscillator consensus
- STRAT-CAND-008 H&S neckline breakout
- STRAT-CAND-009 put/call contrarian extremes
- STRAT-CAND-010 pair-spread mean reversion

## Improvement Specs

- IMP-SPEC-001 Decision/Process Quality Score
- IMP-SPEC-002 Structured Post-Trade Journal
- IMP-SPEC-003 Strategy Regime Applicability & Review Trigger
- IMP-SPEC-004 Entry/Exit Rule Provenance & Conformance
- IMP-SPEC-005 Source Threshold Quarantine

## Risk Specs

- RISK-SPEC-001 Immutable Risk Intent / stop modification audit
- RISK-SPEC-002 Exposure & concentration threshold validation
- RISK-SPEC-003 Leverage / margin stress contract
- RISK-SPEC-004 Hedging / basis-risk contract

## Experiments Required

Alpha candidates require DEV -> VALIDATION -> OOS -> robustness -> multi-regime -> paper admission evidence. Risk thresholds require deterministic offline/paper validation. No LIVE experiment is authorized by this phase.

## Rejected Ideas

- Adopt fixed 3% breakout, 5% position risk, 15% market exposure, 15% intraday position risk, 45% intraday market exposure, 4% pair stop, 1/9 filters, 3:1 R/R, 38/50 Fibonacci or put/call 1.1/0.7 as project defaults solely because the book states them.
- Treat crowd psychology narrative as empirical alpha evidence.
- Treat a hedge as perfectly riskless.
- Treat source popularity/author confidence as validation.

## Adoption Decisions

- ADOPT_P0 (spec-level): immutable risk intent/conformance; process-quality separate from outcome; source-threshold quarantine.
- ADOPT_P1 (spec-level): structured journal; strategy-regime applicability; rule provenance.
- EXPERIMENT: all alpha candidates and all numeric thresholds.
- REJECT: unsupported universal statistics/dogmatic claims as operational evidence.

## Evidence References

- Page locations are recorded per claim above; no page numbers are invented.
- SHA-256: `fb9350183932091991150fffa3636666ab13f3754b2a04bc64f16f37ff427845`.

## Final Assessment

High value as raw research material for process discipline, risk invariants and multiple testable technical hypotheses. Low authority for numeric thresholds and broad success-rate claims. Nothing is promoted to PAPER or production in this phase.