# WP-EDGE-14R/P2 — engine parity report

*Engine `vnpy_ctastrategy`. Rule `NEUTRAL_MA_CROSS_1H`. Dataset `sha256:d79ed2c56bf50226…`. Verdict **AGREE_ON_MATCHED_TRADES_WITH_DECLARED_EXTRA**.*

## Fixed before the run

- rule: long while ema(12) > ema(26) on the previous closed 1h bar, flat otherwise; no fitted parameter
- fill timing: a signal observed at the close of bar i fills at the open of bar i+1, on entry and on exit alike
- costs: 10.0 bps per side on both legs (declared parity commission: 10 bps per side, the same order of magnitude the admission scenario BINANCE_SPOT_STANDARD_TAKER charges; both engines receive it identically)
- slippage: zero on both sides: slippage is a model input, not an engine behaviour, and giving the two engines different slippage models would confound the measurement
- indicator parity: SAME_FORMULA_IMPLEMENTED_INSIDE_THE_ENGINE (max abs diff None)

## Result

| side | trades | net bps sum | equity multiple | max drawdown (bps) |
| --- | ---: | ---: | ---: | ---: |
| trading_agentic | 44 | -1073.410276 | 0.8918944 | 1389.239836 |
| vnpy_ctastrategy | 42 | -1011.506748 | 0.89742999 | 1330.461549 |

- trade count gap: **2**
- max per-trade **gross** difference: **0.0** bps
- max per-trade difference under the matched fee convention (`ADDITIVE`): **0.0** bps
- the same difference under the other convention: **1.169343** bps, so the fee convention alone is worth **1.169343** bps
- equity relative difference: **0.00616827**
- trades matched by entry timestamp: **42** (only here: **2**, only in the external engine: **0**)
- exit timestamp mismatches among matched trades: **0**

## Divergence

- `trade_count_gap=2`

## Limitations

- VeighNa publishes fills rather than round trips and no per-fill commission field, so the net is derived from the gross under the declared convention while the engine's own aggregate accounting is carried alongside
- VeighNa 4.5 carries no crypto venue in its Exchange enum, so the run declares its venue rather than borrowing a code that means something else
- slippage is zero on both sides for the same reason as the other arm: it is a model input, not an engine behaviour
