# RFC-STRAT-013 — Dynamic Strategy Lifecycle & Strategy Pods

- Status: DRAFT FOR INDEPENDENT VERIFICATION
- Authority chain: SOURCE → INSIGHT → REQ → ACC → ARCH → RFC (this) → WP-STRAT-* → IMP → TEST → EXEC → EVID
- Implements: dynamic strategy management request §2–§9, §13–§17, §21–§27
- Verdict ceiling without independent verification: `IMPLEMENTED_WITH_PENDING_VERIFICATION`

## CONTEXT

The runtime today is *multi-strategy*: the admission ledger admits a fixed set of
alpha families for PAPER, and `StrategyRouter.route` returns the single best
match per cycle. There is no notion of a strategy whose *eligibility changes
over time* based on its own contextual evidence, and no explicit lifecycle
beyond `AdmissionStatus` (`RESEARCH_REQUIRED → PAPER_CANDIDATE → PAPER_ACTIVE →
PAPER_RETIRED/REJECTED`).

## PROBLEM

A multi-strategy system that never re-evaluates its strategies is fragile:
strategies degrade silently, correlated strategies stack unnoticed, and
"recent profit" is the only signal anyone has for promoting or retiring one.
Conversely, a system that re-evaluates *naively* overfits: it chases the last N
trades and churns.

## EVIDENCE

- `src/trading_bot/research/strategy_router.py` selects a single strategy and
  has no lifecycle awareness.
- `src/trading_bot/autonomous/strategy_state.py` already encodes a **closed**
  transition graph and refuses LIVE; the dynamic lifecycle must extend this
  vocabulary without widening execution authority.
- `src/trading_bot/autonomous/experience.py` already stores context-keyed
  performance but only reorders router priority (bounded ±0.25).
- GATE 2 found `DEF-RISK-EXPOSURE-001` (P0) and `DEF-RISK-INERT-002`: building
  automatic activation on a risk engine with inert limits would be unsound, so
  this RFC is gated behind fixing them (see §RISK).

## GOALS

1. A first-class **StrategyPod** contract: a deterministic runtime plus metadata,
   evaluation, health, performance, evidence, lifecycle and an OPTIONAL research
   agent that can only emit `RESEARCH_HYPOTHESIS`.
2. A **context-keyed** performance model: strategy × asset × timeframe × regime,
   with rolling windows.
3. A deterministic **StrategyHealthMonitor** that names degradation.
4. A deterministic **StrategyLifecycleController** whose transitions are a closed
   graph and which can never promote on "recent profit" alone.
5. A **StrategyRegistry** that is the versioned, append-only source of truth and
   emits canonical events.
6. All of the above reachable from the router through a new
   `select_eligible_strategies` entry point.

## NON_GOALS

- No LIVE, no real capital, no credentials.
- No LLM may change a state, size a trade, set leverage or promote to production.
- This RFC does not give the dynamic plane execution authority. Execution stays
  behind AdmissionLedger + IndependentVerifier + RiskManager.
- No UI.

## DESIGN

```
MarketContext/AssetContext → Regime → StrategyPods (parallel)
  → DynamicStrategyRegistry → StrategyHealthMonitor → StrategyLifecycleController
  → StrategyRouter.select_eligible_strategies → StrategyPortfolioManager
  → TradeProposal → Agent review → Decision → IndependentVerifier
  → RiskManager → PaperBroker → DecisionTrace → Outcomes → health/experience
```

Package: `src/trading_bot/strategy_lifecycle/` (contracts, config, performance,
health, lifecycle, portfolio, champion, registry, pods, ecosystem).

## CONTRACTS

- `LifecycleState` (DISCOVERED…RETIRED), `STATE_TRANSITIONS` (closed graph),
  `EVIDENCE_REQUIRED_EDGES` = {(SHADOW,ELIGIBLE),(ELIGIBLE,ACTIVE)}.
- `StrategyDescriptor` — id/version/family/assets/timeframes/regimes/runtime/
  validation/permits/provenance/timestamps. `deterministic` defaults True and is
  refused otherwise.
- `PerformanceCell`, `HealthReport`, `LifecycleDecision`, `PromotionRecord`,
  `StrategyEvent`, `PortfolioDecision`.
- `ExecutionMode` includes LIVE only so it can be **refused** at construction
  (`FORBIDDEN_EXECUTION_MODES`).

## LIFECYCLE

Closed graph (self-edges omitted): DISCOVERED→{CANDIDATE,RETIRED};
CANDIDATE→{VALIDATING,RETIRED}; VALIDATING→{PAPER,SHADOW,CANDIDATE,RETIRED};
PAPER→{SHADOW,RETIRED}; SHADOW→{ELIGIBLE,PAPER,PAUSED,RETIRED};
ELIGIBLE→{ACTIVE,SHADOW,PAUSED,RETIRED}; ACTIVE→{DEGRADED,PAUSED,RETIRED};
DEGRADED→{ACTIVE,THROTTLED,PAUSED,SHADOW,RETIRED};
THROTTLED→{ACTIVE,DEGRADED,PAUSED,SHADOW,RETIRED}; PAUSED→{SHADOW,RETIRED};
RETIRED→{}.

**Forbidden by construction:** `PAUSED → ACTIVE`, `CANDIDATE → ACTIVE`,
anything → LIVE.

## RUNTIME FLOW

Observation only (phases B–F). Router integration (phase G) is the last gate.
The dynamic plane never calls the broker.

## STATE TRANSITIONS

Applied only by `DynamicStrategyRegistry.apply(decision)`, which re-checks the
edge and the evidence requirement; a stale decision (computed from another
state) is refused.

## FAILURE MODES

- Pod runtime raises → non-emission (never a crash, never an order).
- Missing/insufficient evidence → refusal, not promotion.
- Shadow result offered to execution → `ShadowLeakError`.
- Stale/future context → `STALE_DATA` / PIT violation.

## SECURITY

No credentials, no exchange path, no LIVE. Pod signals cannot carry leverage/
sizing/risk fields (`FORBIDDEN_ADVISORY_KEYS`).

## RISK

`DEF-RISK-EXPOSURE-001` (P0) and `DEF-RISK-INERT-002` MUST be fixed before any
automatic activation capability is trusted; otherwise a promotion could activate
a strategy against an exposure budget that is not actually enforced. This RFC is
implemented only after those fixes (see WP-RISK-EXPOSURE-001).

## TESTS

Unit (contracts, performance, health, lifecycle, registry, portfolio, pods),
integration (context→pods→router→portfolio→risk), adversarial (§22 mandatory
list), regression (full suite).

## ACCEPTANCE

`FALSE_SUCCESS = 0`; every transition traceable; no LIVE reachable; shadow
isolated; promotion refuses on "last N trades"; independent verification package
produced.

## ROLLBACK

Additive package + additive router method. Removing the package and the
`select_eligible_strategies` method restores the previous behaviour; `route()` is
unchanged.

## OBSERVABILITY

Events (append-only), `STRATEGY_STATUS_REPORT`, `STRATEGY_HEALTH_REPORT`,
`STRATEGY_REGIME_MATRIX`, `STRATEGY_LIFECYCLE_HISTORY`, `STRATEGY_ACTIVATION_CHURN`.
