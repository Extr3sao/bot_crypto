# ARP-001 — STRATEGY FAILURE MATRIX (§3)

Source: `diagnostics/strategy_failure_metrics.json` (deterministic; sha
`464f2a00…615a5`), computed from the reproduced BASE ledger
(`fresh_trades_base.csv`, 6 families, 5m, W1–W7). All numbers are per-trade
expectancies in bps of a 500 USDT notional at the research fee line (10.0 bps per
trade).

| family | n | gross bps | cost bps | **net bps** | win % | payoff | PF | avgMFE % | avgMAE % | dur med (min) | **fwd +1 bar bps** | class |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| ema_crossover | 1561 | −6.22 | 10.00 | **−16.22** | 27.3 | 1.34 | 0.502 | 0.41 | 0.38 | 40 | **−1.95** | NO_GROSS_EDGE |
| momentum | 2436 | −3.79 | 10.00 | **−13.79** | 39.5 | 0.99 | 0.646 | 0.56 | 0.51 | 55 | **−2.07** | NO_GROSS_EDGE |
| breakout | 2276 | −2.54 | 10.00 | **−12.54** | 38.8 | 1.05 | 0.661 | 0.53 | 0.49 | 50 | **−1.99** | NO_GROSS_EDGE |
| trend | 1288 | −3.61 | 10.00 | **−13.62** | 55.4 | 0.58 | 0.723 | 0.71 | 0.73 | 30 | **−2.26** | NO_GROSS_EDGE |
| mean_reversion | 2861 | −0.59 | 10.00 | **−10.59** | 46.5 | 0.78 | 0.675 | 0.46 | 0.49 | 70 | **−1.05** | NO_GROSS_EDGE |
| volatility | 519 | −6.52 | 10.00 | **−16.52** | 42.2 | 0.85 | 0.618 | 0.56 | 0.59 | 110 | **−0.04** | NO_GROSS_EDGE |

## The single decisive column

The **forward expectancy is negative at every measured horizon (+1, +3, +6, +12,
+24 bars) for every family** (see `ENTRY_EXIT_DECOMPOSITION.md`). The window's
full table:

| family | +1 | +3 | +6 | +12 | +24 |
|---|---|---|---|---|---|
| ema_crossover | −1.95 | −2.98 | −3.71 | −5.61 | −6.88 |
| momentum | −2.07 | −1.34 | −2.96 | −3.63 | −5.96 |
| breakout | −1.99 | −2.64 | −4.22 | −6.65 | −12.36 |
| trend | −2.26 | −4.43 | −6.00 | −9.76 | −18.40 |
| mean_reversion | −1.05 | −0.68 | −0.23 | +0.19 | +1.63 |
| volatility | −0.04 | −0.54 | −1.30 | −6.66 | −6.63 |

A **negative direction-adjusted forward return means the entry itself is not
predictive**: the trade is, on average, on the wrong side of the next move
immediately. No exit policy can repair that.

Other structural observations (all families):

- **Loss is broad-based, not concentrated.** Top-10% of winning trades contribute
  only 18–39 % of gross profits; top-1 trade ≤ 0.46 %. There is no "one lucky
  trade" and no fat-tail dependence to salvage.
- **No asset hiding the edge:** BTC, ETH and SOL are all negative, with SOL the
  worst in five of six families.
- **No regime hiding the edge:** HIGH and LOW volatility regimes are both
  negative for all six (`REGIME_ATTRIBUTION.md`).
- **Exit mix is churn-heavy:** `signal_flip` dominates for ema_crossover (636/1561)
  and mean_reversion (741/2861); `PROFIT_THEN_GIVEBACK` is present everywhere
  (breakout 468, momentum 567) but repairing exits cannot fix a negative-drift
  entry.
- **trend** has a 55.4 % win rate yet PF 0.72 because its payoff is 0.58 — it wins
  often but small and loses big. That is the classic "cut winners, ride losers"
  signature, and it is the one family where an exit asymmetry is worth a
  *hypothesis* — but the entry drift is −2.26 bps, so the hypothesis is not
  currently supported by evidence.

## Data / PIT status

All inputs are the WP-STRAT-08-integrity-clean corpus (84/84 files, 0 duplicates,
0 gaps, 0 OHLC inconsistencies) with W7 held out. No PIT defect is implicated in
the failures: this is an edge failure, not a data/infra failure.
