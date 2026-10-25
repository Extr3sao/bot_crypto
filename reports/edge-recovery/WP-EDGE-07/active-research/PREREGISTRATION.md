# WP-EDGE-07 Track C — pre-registration of the ACTIVE candidates, written before they were run

*Registered at `2026-10-14T09:20:00Z` (`EDGE07-ACTIVE-PREREG-20261014T092000Z`). The commit that
carries this file precedes the commit that carries any figure of it.*

## 1. The question, and the two books that answer it

The mission's Track C asks for a multi-asset ACTIVE book that aims at **three or more trades a
day**, with net expectancy taking precedence over frequency, no forced trades, no relaxed risk
limits, and candidates that lose before costs rejected on the spot. The frozen trend book stays
where it is, as a separate low-frequency module; nothing here touches it, `config/risk.yaml` or
any other lane.

Two books, registered here, no others. Multiplicity is **2** and is reported.

| Book | Idea | Why it might survive the cost wall |
| --- | --- | --- |
| `edge07_active_thrust` | A-1: half a day's high broken by a bar that itself travelled ≥ 0.5 ATR, with the close above EMA(48). Stop 1 ATR, target 1.5 ATR. | The thrust filter is what a 1h trend-continuation book needs: a drift through the level is refused before the cost gate is even reached |
| `edge07_active_fade` | A-2: buy a bar that fell ≥ 0.75 ATR and closed ≥ 2 ATR below EMA(24); exit at the mean. Stop 1 ATR. | A two-ATR dislocation is a *priced* move, not a drift; the mean is a target the cost gate accepts only when it is ≥ 1.25 ATR away |

**The cost wall, stated before any result.** `COST_MODEL_V3` at a one-hour horizon is
**23.79 bps per round trip** (20 bps fee + 1 bps spread + 2.63 bps slippage + 0.16 bps impact,
`BINANCE_SPOT_STANDARD_TAKER`). Three trades a day is therefore ~71 bps a day of cost. A book at
this frequency has to earn more than 23.79 bps *gross* per trade, on average, before it earns
anything at all. Both candidates carry `cost_margin: 1.25`, so the instrument itself refuses any
setup whose own objective does not clear 1.25 × that cost.

Registered parameters (`edge07.active.DECLARED_PARAMS`, the machine-readable copy):

```json
{
  "edge07_active_thrust": {"ema_period": 48, "breakout_lookback": 12, "atr_period": 14,
                            "thrust_atr": 0.5, "stop_atr": 1.0, "target_atr": 1.5,
                            "min_rr": 1.5, "cost_margin": 1.25},
  "edge07_active_fade":   {"ema_period": 24, "atr_period": 14, "stretch_atr": 2.0,
                            "down_bar_atr": 0.75, "stop_atr": 1.0, "min_rr": 0.5,
                            "cost_margin": 1.25}
}
```

Both are long only, like every other lane here: this is spot, and a fade is a purchase of a
stretched move. One position per asset, `config/risk.yaml` decides the size
(`max_trades_per_day: 20` does **not** constrain a three-a-day book, so the frequency target is a
design aim, never a reason to force an entry).

## 2. Windows, costs, fills — unchanged from the campaign

| | |
| --- | --- |
| Timeframe | 1h native (no aggregation), BTC / ETH / SOL |
| Development | `DEV` 2019-01-01…2023-12-31 and `VAL` 2024-01-01…2024-12-31, from the frozen 1h corpora — **read before** by the trend book, and labelled as such |
| Independent | `NEW_HOLDOUT` 2026-03-01…2026-10-14, the window WP-EDGE-07 fetched from public Binance REST, unread by any book — 5.4 days of it is not covered by any other corpus |
| Costs | `COST_MODEL_V3` through `edge01.costs.cost_plane`; scenarios BASE, 2X_FEES, ADVERSE |
| Sizing, caps, cooldowns | `config/risk.yaml` through the campaign's `RiskPolicy`; no arm may size, relax a limit or add a cooldown |
| Fills | the campaign's simulator, unchanged |
| Metrics | the campaign's `_metrics` (with `1h` added to its declared `BARS_PER_YEAR` for Sharpe; the addition is additive and moves no frozen lane) plus the same four added readings Track B declared: block bootstrap, three time blocks, per-asset breakdown, serial dependence |

## 3. The rules, fixed before measuring

| # | Criterion | Where |
| --- | --- | --- |
| C0 | **Screen**: a candidate whose DEV **gross expectancy ≤ 0** is `REJECT_NO_GROSS_EDGE` and does not get to read the independent window at all | DEV |
| C1 | trades ≥ 3 per day on `NEW_HOLDOUT` (the mission's frequency aim; a miss is *not* a pass) | independent |
| C2 | net > 0 at BASE | independent |
| C3 | expectancy > 0 at BASE | independent |
| C4 | net > 0 at 2X fees | independent |
| C5 | largest single trade ≤ 50 % of the net | independent |
| C6 | net > 0 in ≥ 2 of the 3 equal consecutive time blocks | independent |
| R | per-asset, per-context and bootstrap readings: reported, never decisive | independent |

| Verdict | Means |
| --- | --- |
| `ADMIT_PAPER` | C1–C6 all pass on `NEW_HOLDOUT`. Paper only: no live trading, no capital, and the risk-manager's and release gate's own conditions still apply |
| `REJECT` | C0 failed, or a decisive criterion failed with power (net ≤ 0 with ≥ 30 trades, or the cost-stress arm, or the time blocks) |
| `INSUFFICIENT_EVIDENCE` | the sample is too small to decide, or one trade carries the net, or the frequency target is missed while everything else is non-negative (a book that cannot reach three trades a day has not answered this mission's question) |

Nothing is tuned on the independent window; it is read once. A candidate that fails is reported
with its numbers and is not retried here, and no candidate is ever given a second parameter set to
flatter it. `promotion: NONE`, `order_sent: false`, no capital, no orders.
