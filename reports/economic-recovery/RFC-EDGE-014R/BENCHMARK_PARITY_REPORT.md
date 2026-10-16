# WP-EDGE-14R/P2 — engine parity report

*Engine `freqtrade`. Rule `NEUTRAL_MA_CROSS_1H`. Dataset `sha256:d79ed2c56bf50226…`. Verdict **AGREE_WITHIN_TOLERANCE**.*

## Fixed before the run

- rule: long while ema(12) > ema(26) on the previous closed 1h bar, flat otherwise; no fitted parameter
- fill timing: a signal observed at the close of bar i fills at the open of bar i+1, on entry and on exit alike
- costs: 10.0 bps per side on both legs (declared parity commission: 10 bps per side, the same order of magnitude the admission scenario BINANCE_SPOT_STANDARD_TAKER charges; both engines receive it identically)
- slippage: zero on both sides: slippage is a model input, not an engine behaviour, and giving the two engines different slippage models would confound the measurement
- indicator parity: SAME_DEFINITION (max abs diff 5.820766091346741e-11)

## Result

| side | trades | net bps sum | equity multiple | max drawdown (bps) |
| --- | ---: | ---: | ---: | ---: |
| trading_agentic | 44 | -1073.410276 | 0.8918944 | 1389.239836 |
| freqtrade | 44 | -1072.971349 | 0.89193364 | 1388.938454 |

- trade count gap: **0**
- max per-trade **gross** difference: **0.0** bps
- max per-trade difference under the matched fee convention (`COMPOUNDED`): **0.010569** bps
- the same difference under the other convention: **1.158774** bps, so the fee convention alone is worth **1.148205** bps
- equity relative difference: **4.4e-05**
- trades matched by entry timestamp: **44** (only here: **0**, only in the external engine: **0**)
- exit timestamp mismatches among matched trades: **0**

## Limitations

- one rule on one timeframe over one window: agreement here is evidence about the engines' accounting, not about any strategy's edge
- slippage is held at zero on both sides because the external engine has no native slippage parameter; a fill model cannot be invented for it
- the external engine runs in its own environment outside the checkout and is invoked as a subprocess; no external code enters this project
- commission is a declared parity input (10 bps a side) applied identically by both engines, not a measured venue fee
