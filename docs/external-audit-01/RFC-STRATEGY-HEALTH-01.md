# RFC-STRATEGY-HEALTH-01 — Strategy Health Lifecycle

Status: **DRAFT** (design only; no implementation in this checkpoint)
Checkpoint: EXTERNAL-AUDIT-RECONCILIATION-01
Audited HEAD: `a282fcc`

## 1. Problem

The external audit identified that strategies have no health lifecycle. Current
state at HEAD: `src/trading_bot/strategies/` exposes a `Strategy` Protocol,
`StrategyConfig`, and a pipeline; `paper/strategy_selector.py` has a config
registry; there is **no** `quarantine`/`retire`/`lifecycle` concept anywhere in
the strategies package. Each strategy is either selected or not — there is no
degradation signal between "working" and "disabled".

## 2. Goals / non-goals

Goals:
- Define lifecycle states and transitions for strategies.
- Integrate with existing `StrategyRegistry` (indicator registry pattern),
  the Admission Engine (`admission/`), and Regime context (`research/`).
- Define target health metrics and the data needed to compute them.

Non-goals (this checkpoint):
- No implementation. No runtime wiring. No change to POC01 strategies.

## 3. Lifecycle proposal

```
PAPER_ACTIVE -> MONITORING -> DEGRADED -> QUARANTINED -> RETIRED
```

- **PAPER_ACTIVE**: admitted and trading paper.
- **MONITORING**: healthy, metrics tracked.
- **DEGRADED**: metrics below thresholds (rolling expectancy/Sharpe baseline,
  elevated drawdown, win rate drop, slippage degradation).
- **QUARANTINED**: halted from new entries; requires research/revalidation to
  recover.
- **RETIRED**: permanently disabled; re-admission requires the full admission
  path again.

Recovery rule: **recovery must require research/revalidation**. No automatic
critical promotion from QUARANTINED/RETIRED back to PAPER_ACTIVE.

## 4. Target metrics

| Metric | Definition | Baseline |
| --- | --- | --- |
| Rolling expectancy | mean trade PnL over rolling window | vs strategy's own baseline |
| Rolling Sharpe | annualized Sharpe over rolling window | vs baseline |
| PF (profit factor) | gross profit / gross loss | >= 1.0 |
| Win rate | wins / total closed trades | vs baseline |
| Drawdown | peak-to-trough equity decline | vs max allowed |
| Slippage degradation | realized vs expected slippage | vs threshold |
| Sample size | closed trades in window | min sample gate |

Conditionable by: **asset**, **timeframe**, **regime**.

## 5. Integration points

- `StrategyRegistry` (indicators/registry.py pattern): register health state
  alongside strategy registration.
- Admission Engine: a strategy enters PAPER_ACTIVE only after admission.
- Regime context (`research/strategy_router.py`): health state may gate
  selection in a given regime.

## 6. Proposed module (future)

`src/trading_bot/strategies/health.py`:

```
StrategyHealthState(enum): PAPER_ACTIVE / MONITORING / DEGRADED / QUARANTINED / RETIRED
StrategyHealthSnapshot: metrics + sample_size + state
StrategyHealthTracker: update(metrics) -> state transitions (deterministic thresholds)
```

Transitions require explicit evidence; no transition without a recorded reason.

## 7. Open questions

- Where should the health store live (in-memory vs durable)?
- Should quarantine be per (strategy, asset, timeframe) or per strategy only?
- Who may promote out of QUARANTINED (human + research artifact required)?

## 8. Decision

RFC accepted as design input. Implementation deferred to a dedicated
implementation checkpoint; no code changes now.