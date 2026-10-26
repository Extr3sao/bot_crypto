# RFC-STRAT-014 — Champion/Challenger Strategy Selection & Portfolio Allocation

- Status: DRAFT FOR INDEPENDENT VERIFICATION
- Depends on: RFC-STRAT-013
- Verdict ceiling without independent verification: `IMPLEMENTED_WITH_PENDING_VERIFICATION`

## CONTEXT

RFC-STRAT-013 gives strategies a lifecycle. This RFC defines how a *newer*
strategy challenges an incumbent, and how several eligible strategies coexist
without becoming one hidden oversized bet.

## PROBLEM

1. A challenger that beats the champion in a single short window is noise, not
   evidence.
2. Three strategies that all say "BUY BTC" are not three independent bets; naive
   stacking triples the same risk.

## EVIDENCE

- Runtime already has `SHADOW_TRADE` semantics (`contracts.ShadowTradeDecision`)
  and the admission ledger's `SHADOW_ELIGIBLE_STATUSES`.
- Runtime has no correlation/overlap logic; `paper/portfolio_manager.py` and
  `paper/strategy_selector.py` are ORPHAN.

## GOALS

- A deterministic comparison model and a `PROMOTION_CANDIDATE` outcome that is
  **not** an automatic promotion.
- Shadow execution on identical inputs (same data/timestamps/costs/regime).
- Portfolio arbitration over correlation, overlap, direction and concentration.
- Explicit provenance so shadow numbers never mix with executed PnL.

## NON_GOALS

Same as RFC-STRAT-013: no LIVE, no LLM decisions, no execution authority.

## DESIGN

```
same context ──► CHAMPION (ACTIVE)      ──► metrics
             └─► CHALLENGERS (SHADOW)   ──► metrics
ChampionChallenger.compare(...) ──► CHAMPION_RETAINED | PROMOTION_CANDIDATE
eligible set ──► StrategyPortfolioManager.arbitrate(...) ──► PortfolioDecision
             ──► RiskManager (final veto)
```

## COMPARISON MODEL

A challenger must beat the champion on **all** of: `sample_count ≥
minimum_samples`, `net_expectancy ≥ champion + minimum_challenger_edge_bps`,
`profit_factor ≥ champion + minimum_profit_factor_advantage`, and win
`required_window_wins` (default 3) rolling windows. One good window never
promotes.

## SHADOW EXECUTION

`ParallelShadowRuntime.evaluate_all` runs every pod over the SAME context and
tags results `ExecutionMode.SHADOW`. `guard_not_executable` refuses any
non-PAPER result at an execution sink.

## PROMOTION RULES

`PROMOTION_CANDIDATE` (ELIGIBLE) still requires the RFC-STRAT-013 evidence gate
and IndependentVerifier before ACTIVE. A champion losing one window is NOT
demoted (health/persistence hysteresis governs that).

## PORTFOLIO CORRELATION

Pearson correlation over aligned net-return series; same asset + corr ≥
threshold → reject with `CORRELATION_CONFLICT`. Per-asset and total exposure
budgets and a same-direction cap are enforced; the manager can only REDUCE what
risk would allow.

## DUPLICATE EXPOSURE

`merged_exposure` reports the aggregate notional per asset after arbitration, and
`concentration_flags` / `correlation_flags` name why a proposal was dropped.

## GATES

`strategy_activation_churn` (activations/pauses/reactivations/reversals/time in
state) is measured; cooldown and dwell make activation harder than degradation.

## ROLLBACK

Additive modules `champion.py` / `portfolio.py`; removing them leaves RFC-STRAT-013
intact.

## EVIDENCE

`reports/strategy-lifecycle/STRATEGY_CHAMPION_CHALLENGER_REPORT.md`,
`EXP-STRAT-DYNAMIC-001` (champion/challenger + portfolio under identical
economics).
