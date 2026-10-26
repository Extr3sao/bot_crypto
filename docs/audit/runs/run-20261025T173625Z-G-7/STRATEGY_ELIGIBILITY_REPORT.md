# G-7 — Strategy eligibility report

**Authority:** `config/strategy_admission.json` (`strategy-admission-ledger-v1`)  
**Registry:** `StrategyRegistry.from_ledger`  
**Router:** `StrategyRouter.select_eligible_strategies` with `RouterGates(timeframe="5m")`  
**Assets:** BTC/USDT, ETH/USDT, SOL/USDT  
**Evaluation instants:** `2026-10-25T16:55Z`, `17:00Z`, `17:05Z` (replay), `17:19:46.823Z` (forward)

## 1. Ledger inventory

| Metric | Value |
|---|---:|
| Known entries | 24 |
| `admitted_for_paper=true` | **0** |
| `PAPER_CANDIDATE` | 0 |
| `PAPER_ACTIVE` | 0 |
| `COST_KILLED` | 7 |
| `NO_GROSS_EDGE` | 17 |

The ledger says, in its own `_claim`:

> no strategy is admitted for PAPER execution unless a committed research
> artifact places it under paper_candidates with measured positive gross edge

No committed research artifact does. G-7 therefore did not modify the ledger
and did not promote anything to make the vertical look complete.

## 2. Full ledger

| strategy_id | timeframe | status | admitted | expected gross bps |
|---|---|---:|---:|---:|
| `breakout@5m` | 5m | NO_GROSS_EDGE | false | -0.11 |
| `ema_crossover@5m` | 5m | NO_GROSS_EDGE | false | -4.56 |
| `mean_reversion@5m` | 5m | COST_KILLED | false | 1.49 |
| `momentum@5m` | 5m | NO_GROSS_EDGE | false | -1.88 |
| `trend@5m` | 5m | NO_GROSS_EDGE | false | -1.65 |
| `volatility@5m` | 5m | NO_GROSS_EDGE | false | -4.73 |
| `breakout@15m` | 15m | NO_GROSS_EDGE | false | -1.82 |
| `ema_crossover@15m` | 15m | NO_GROSS_EDGE | false | -1.12 |
| `mean_reversion@15m` | 15m | COST_KILLED | false | 2.71 |
| `momentum@15m` | 15m | NO_GROSS_EDGE | false | -3.97 |
| `trend@15m` | 15m | COST_KILLED | false | 1.28 |
| `volatility@15m` | 15m | NO_GROSS_EDGE | false | -7.06 |
| `breakout@1h` | 1h | NO_GROSS_EDGE | false | -0.22 |
| `ema_crossover@1h` | 1h | NO_GROSS_EDGE | false | -0.96 |
| `mean_reversion@1h` | 1h | NO_GROSS_EDGE | false | -2.23 |
| `momentum@1h` | 1h | NO_GROSS_EDGE | false | -2.33 |
| `trend@1h` | 1h | NO_GROSS_EDGE | false | -1.25 |
| `volatility@1h` | 1h | COST_KILLED | false | 6.28 |
| `breakout@30m` | 30m | NO_GROSS_EDGE | false | -1.79 |
| `ema_crossover@30m` | 30m | NO_GROSS_EDGE | false | -0.73 |
| `mean_reversion@30m` | 30m | COST_KILLED | false | 5.47 |
| `momentum@30m` | 30m | NO_GROSS_EDGE | false | -2.61 |
| `trend@30m` | 30m | COST_KILLED | false | 2.21 |
| `volatility@30m` | 30m | COST_KILLED | false | 8.91 |

`COST_KILLED` with a positive gross edge (for example `volatility@30m` at
8.91 bps) is still **not** an admission: the committed research verdict is
that the edge does not survive the cost model. It cannot be routed to PAPER.

## 3. Router verdicts (representative replay instant)

Regime at all three instants: `LOW_VOLATILITY`. The same verdicts repeat for
the other two replay instants and the forward instant.

| strategy | asset | tf | regime | ledger status | router verdict | reason |
|---|---|---|---|---|---|---|
| `breakout@5m` | BTC | 5m | LOW_VOLATILITY | NO_GROSS_EDGE | NOT_APPLICABLE | status does not authorise PAPER |
| `ema_crossover@5m` | BTC | 5m | LOW_VOLATILITY | NO_GROSS_EDGE | NOT_APPLICABLE | status does not authorise PAPER |
| `mean_reversion@5m` | BTC | 5m | LOW_VOLATILITY | COST_KILLED | NOT_APPLICABLE | status does not authorise PAPER |
| `momentum@5m` | BTC | 5m | LOW_VOLATILITY | NO_GROSS_EDGE | NOT_APPLICABLE | status does not authorise PAPER |
| `trend@5m` | BTC | 5m | LOW_VOLATILITY | NO_GROSS_EDGE | NOT_APPLICABLE | status does not authorise PAPER |
| `volatility@5m` | BTC | 5m | LOW_VOLATILITY | NO_GROSS_EDGE | NOT_APPLICABLE | status does not authorise PAPER |
| `breakout@5m` | ETH | 5m | LOW_VOLATILITY | NO_GROSS_EDGE | NOT_APPLICABLE | status does not authorise PAPER |
| `ema_crossover@5m` | ETH | 5m | LOW_VOLATILITY | NO_GROSS_EDGE | NOT_APPLICABLE | status does not authorise PAPER |
| `mean_reversion@5m` | ETH | 5m | LOW_VOLATILITY | COST_KILLED | NOT_APPLICABLE | status does not authorise PAPER |
| `momentum@5m` | ETH | 5m | LOW_VOLATILITY | NO_GROSS_EDGE | NOT_APPLICABLE | status does not authorise PAPER |
| `trend@5m` | ETH | 5m | LOW_VOLATILITY | NO_GROSS_EDGE | NOT_APPLICABLE | status does not authorise PAPER |
| `volatility@5m` | ETH | 5m | LOW_VOLATILITY | NO_GROSS_EDGE | NOT_APPLICABLE | status does not authorise PAPER |
| `breakout@5m` | SOL | 5m | LOW_VOLATILITY | NO_GROSS_EDGE | NOT_APPLICABLE | status does not authorise PAPER |
| `ema_crossover@5m` | SOL | 5m | LOW_VOLATILITY | NO_GROSS_EDGE | NOT_APPLICABLE | status does not authorise PAPER |
| `mean_reversion@5m` | SOL | 5m | LOW_VOLATILITY | COST_KILLED | NOT_APPLICABLE | status does not authorise PAPER |
| `momentum@5m` | SOL | 5m | LOW_VOLATILITY | NO_GROSS_EDGE | NOT_APPLICABLE | status does not authorise PAPER |
| `trend@5m` | SOL | 5m | LOW_VOLATILITY | NO_GROSS_EDGE | NOT_APPLICABLE | status does not authorise PAPER |
| `volatility@5m` | SOL | 5m | LOW_VOLATILITY | NO_GROSS_EDGE | NOT_APPLICABLE | status does not authorise PAPER |

Counts per report: `{"NOT_APPLICABLE": 18}`. Across four reports:
**72 evaluations, 0 SELECTED, 0 REJECTED, 72 NOT_APPLICABLE**.

## 4. Selection record

No row produced `SELECTED`. Therefore there is no
`strategy_id, version, asset, timeframe, regime, validation_status,
eligibility_reason` record with a positive eligibility decision to execute.
The engine correctly recorded `router_no_trade=3` per session and
`NO_TRADE:no_strategy_passed_gates` per symbol.

## 5. Consequence

G-7's condition 3 (an existing eligible strategy really evaluated) is
**BLOCKED** by the admission data, not by the runtime. The correct next step
is research: produce a strategy that passes the admission criteria, record its
evidence, promote it through the ledger, and re-run this campaign. Until then,
any PAPER order would be an unauthorised trade.
