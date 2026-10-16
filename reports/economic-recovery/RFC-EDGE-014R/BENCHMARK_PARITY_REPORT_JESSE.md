# WP-EDGE-14R/P2 — engine parity report

*Engine `jesse`. Rule `NEUTRAL_MA_CROSS_1H`. Dataset `sha256:d79ed2c56bf50226…`. Verdict **DIVERGENT**.*

## Fixed before the run

- rule: long while ema(12) > ema(26) on the previous closed 1h bar, flat otherwise; no fitted parameter
- fill timing: a signal observed at the close of bar i fills at the open of bar i+1, on entry and on exit alike
- costs: 10.0 bps per side on both legs (declared parity commission: 10 bps per side, the same order of magnitude the admission scenario BINANCE_SPOT_STANDARD_TAKER charges; both engines receive it identically)
- slippage: zero on both sides: slippage is a model input, not an engine behaviour, and giving the two engines different slippage models would confound the measurement
- indicator parity: SAME_FORMULA_IMPLEMENTED_INSIDE_THE_ENGINE (max abs diff None)

## Result

| side | trades | net bps sum | equity multiple | max drawdown (bps) |
| --- | ---: | ---: | ---: | ---: |
| trading_agentic | 44 | -1069.28556 | 0.89226664 | 1383.193618 |
| jesse | 44 | -1073.440243 | 0.89187911 | 1389.852756 |

- trade count gap: **0**
- max per-trade **gross** difference: **6.985523** bps
- max per-trade difference under the matched fee convention (`COMPOUNDED`): **7.021359** bps
- the same difference under the other convention: **6.925772** bps, so the fee convention alone is worth **-0.095587** bps
- equity relative difference: **0.00043452**
- trades matched by entry timestamp: **44** (only here: **0**, only in the external engine: **0**)
- exit timestamp mismatches among matched trades: **2**

## Divergence

- `COMPOUNDED_residual=7.021359`
- `gross_residual=6.985523`

## Limitations

- one rule on one timeframe over one window: agreement here is evidence about the engines' accounting, not about any strategy's edge
- Jesse consumes 1-minute source rows and generates the 1h candles inside the backtest; the frozen dataset is 1h, so the 1m source for the same window was fetched separately and audited to aggregate onto those bars exactly
- the frozen dataset's final bar was captured mid-hour and is excluded from both sides of this comparison rather than being silently kept
- one route per run: a single run over two symbols shares one spot balance, so the first symbol's entry leaves the second unfunded — the other engines are given one independent account per symbol, and this run matches that
- slippage is zero on both sides: it is a model input, and Jesse has no native slippage parameter to give it
- commission is a declared parity input (10 bps a side); Jesse's realised per-side rate is derived from its published fee field and reported
