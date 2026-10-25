# Point-in-time reconciliation

*100% of 7081 pre-repair exits were filled at their own signal bar; 0 violations remain after the repair.*

## The rule the old rows break

every exit test read the current bar's close and filled at that same bar's open, a price that had already happened before the close existed

## What the repair changes

the repair moves the fill instant and nothing else: the rules fire on the same signal bars, entries are unchanged, and the exits that a rule would have taken at the signal bar are now taken at the next executable bar or marked if the window ends first

## The contract every row is held to

| field | meaning |
| --- | --- |
| `decision_clock` | once per closed bar, at data_available_at (the bar's close time) |
| `entry_signal` | signal read off bar t fills at the open of bar t+1 |
| `exit_signal` | signal read off bar t fills at the open of bar t+1, never at bar t's open |
| `intrabar` | not resolved here: these rules act on closes only |
| `same_instant_reentry` | an entry filling at the same instant as the previous exit is dropped |
| `schema_version` | EDGE16_PIT_CONTRACT_V1 |
| `terminal_mark` | an open position at the last closed bar is marked at that close, is_mark=true |
| `undefined_indicator` | NaN; every gate that reads it is False |

## Before and after, on the window the tests run on

| symbol | pre-PIT trades | pre-PIT exits at their own signal bar | post-PIT trades | post-PIT violations | entries matched | exits moved one bar |
| --- | --- | --- | --- | --- | --- | --- |
| BTCUSDT | 31 | 31 | 29 | 0 | 29 | 29 |
| ETHUSDT | 37 | 37 | 34 | 0 | 32 | 32 |
| SOLUSDT | 30 | 30 | 30 | 0 | 30 | 30 |

## Per lane, over both corpora

| corpus | symbol | family | pre-PIT trades | share exploited | post-PIT trades | marks | violations |
| --- | --- | --- | --- | --- | --- | --- | --- |
| EDGE08_ALTS_1H | AAVE/USDT | vol_regime_breakout | 106 | 100% | 106 | 0 | 0 |
| EDGE08_ALTS_1H | AAVE/USDT | trend_pullback | 556 | 100% | 524 | 0 | 0 |
| EDGE08_ALTS_1H | AAVE/USDT | mean_reversion_vol_liq | 391 | 100% | 370 | 1 | 0 |
| EDGE08_ALTS_1H | CRV/USDT | vol_regime_breakout | 147 | 100% | 147 | 0 | 0 |
| EDGE08_ALTS_1H | CRV/USDT | trend_pullback | 503 | 100% | 476 | 0 | 0 |
| EDGE08_ALTS_1H | CRV/USDT | mean_reversion_vol_liq | 482 | 100% | 462 | 1 | 0 |
| EDGE08_ALTS_1H | KSM/USDT | vol_regime_breakout | 151 | 100% | 151 | 0 | 0 |
| EDGE08_ALTS_1H | KSM/USDT | trend_pullback | 500 | 100% | 476 | 0 | 0 |
| EDGE08_ALTS_1H | KSM/USDT | mean_reversion_vol_liq | 499 | 100% | 485 | 1 | 0 |
| EDGE08_ALTS_1H | SNX/USDT | vol_regime_breakout | 155 | 100% | 155 | 0 | 0 |
| EDGE08_ALTS_1H | SNX/USDT | trend_pullback | 475 | 100% | 452 | 0 | 0 |
| EDGE08_ALTS_1H | SNX/USDT | mean_reversion_vol_liq | 537 | 100% | 518 | 1 | 0 |
| EDGE08_ALTS_1H | SUSHI/USDT | vol_regime_breakout | 161 | 100% | 161 | 0 | 0 |
| EDGE08_ALTS_1H | SUSHI/USDT | trend_pullback | 518 | 100% | 487 | 0 | 0 |
| EDGE08_ALTS_1H | SUSHI/USDT | mean_reversion_vol_liq | 515 | 100% | 504 | 0 | 0 |
| EDGE08_ALTS_1H | UNI/USDT | vol_regime_breakout | 107 | 100% | 107 | 0 | 0 |
| EDGE08_ALTS_1H | UNI/USDT | trend_pullback | 546 | 100% | 517 | 0 | 0 |
| EDGE08_ALTS_1H | UNI/USDT | mean_reversion_vol_liq | 448 | 100% | 437 | 0 | 0 |
| EDGE07_HOLDOUT_1H | BTC/USDT | vol_regime_breakout | 14 | 100% | 14 | 0 | 0 |
| EDGE07_HOLDOUT_1H | BTC/USDT | trend_pullback | 59 | 100% | 56 | 0 | 0 |
| EDGE07_HOLDOUT_1H | BTC/USDT | mean_reversion_vol_liq | 31 | 100% | 30 | 0 | 0 |
| EDGE07_HOLDOUT_1H | ETH/USDT | vol_regime_breakout | 12 | 100% | 12 | 0 | 0 |
| EDGE07_HOLDOUT_1H | ETH/USDT | trend_pullback | 62 | 100% | 57 | 0 | 0 |
| EDGE07_HOLDOUT_1H | ETH/USDT | mean_reversion_vol_liq | 26 | 100% | 26 | 0 | 0 |
| EDGE07_HOLDOUT_1H | SOL/USDT | vol_regime_breakout | 9 | 100% | 9 | 0 | 0 |
| EDGE07_HOLDOUT_1H | SOL/USDT | trend_pullback | 45 | 100% | 44 | 0 | 0 |
| EDGE07_HOLDOUT_1H | SOL/USDT | mean_reversion_vol_liq | 26 | 100% | 26 | 0 | 0 |

## Reading

The repair moves the fill instant and nothing else: the rules fire on the same signal bars, the entries are unchanged, and every exit that a rule would have taken at the signal bar is taken at the next executable bar instead. Terminal marks are the only exits that are not fills, and they are labelled.
