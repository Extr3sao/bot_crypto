# WP-EDGE-016 — PIT defect map

*measured on the corpus as committed; 7081 pre-repair exits*

## The defect

Each family read the **current** bar's close (`closes[index]`, `bars[index].close`) to decide
an exit and then filled it at `bars[index].open` — an instant that precedes that close. A
decision cannot be executed before its own information exists, so those exit prices were not
obtainable.

**7081 of 7081 exits (100.0%) were filled that way.** Every
family and every symbol was affected, which is why the WP-EDGE-015 economic numbers are
labelled `HISTORICAL_DESCRIPTIVE_PRE_PIT_FIX` rather than corrected in place.

## The repair

| clause | rule |
| --- | --- |
| decision clock | once per closed bar, at data_available_at (the bar's close time) |
| entry | signal read off bar t fills at the open of bar t+1 |
| exit | signal read off bar t fills at the open of bar t+1, never at bar t's open |
| terminal | an open position at the last closed bar is marked at that close, is_mark=true |
| undefined indicator | NaN; every gate that reads it is False |

The rules are unchanged: the same signal bars fire, the same entries fill, and the only
difference is that an exit decided at bar *t* is filled at the open of bar *t+1*, or marked
at the window's last close if the series ends first.

| corpus | symbol | family | pre-PIT trades | exits filled at their own signal bar | post-PIT trades | filled one bar later | marks | violations |
| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| EDGE08_ALTS_1H | AAVE/USDT | vol_regime_breakout | 106 | 106 | 106 | 106 | 0 | 0 |
| EDGE08_ALTS_1H | AAVE/USDT | trend_pullback | 556 | 556 | 524 | 524 | 0 | 0 |
| EDGE08_ALTS_1H | AAVE/USDT | mean_reversion_vol_liq | 391 | 391 | 370 | 369 | 1 | 0 |
| EDGE08_ALTS_1H | CRV/USDT | vol_regime_breakout | 147 | 147 | 147 | 147 | 0 | 0 |
| EDGE08_ALTS_1H | CRV/USDT | trend_pullback | 503 | 503 | 476 | 476 | 0 | 0 |
| EDGE08_ALTS_1H | CRV/USDT | mean_reversion_vol_liq | 482 | 482 | 462 | 461 | 1 | 0 |
| EDGE08_ALTS_1H | KSM/USDT | vol_regime_breakout | 151 | 151 | 151 | 151 | 0 | 0 |
| EDGE08_ALTS_1H | KSM/USDT | trend_pullback | 500 | 500 | 476 | 476 | 0 | 0 |
| EDGE08_ALTS_1H | KSM/USDT | mean_reversion_vol_liq | 499 | 499 | 485 | 484 | 1 | 0 |
| EDGE08_ALTS_1H | SNX/USDT | vol_regime_breakout | 155 | 155 | 155 | 155 | 0 | 0 |
| EDGE08_ALTS_1H | SNX/USDT | trend_pullback | 475 | 475 | 452 | 452 | 0 | 0 |
| EDGE08_ALTS_1H | SNX/USDT | mean_reversion_vol_liq | 537 | 537 | 518 | 517 | 1 | 0 |
| EDGE08_ALTS_1H | SUSHI/USDT | vol_regime_breakout | 161 | 161 | 161 | 161 | 0 | 0 |
| EDGE08_ALTS_1H | SUSHI/USDT | trend_pullback | 518 | 518 | 487 | 487 | 0 | 0 |
| EDGE08_ALTS_1H | SUSHI/USDT | mean_reversion_vol_liq | 515 | 515 | 504 | 504 | 0 | 0 |
| EDGE08_ALTS_1H | UNI/USDT | vol_regime_breakout | 107 | 107 | 107 | 107 | 0 | 0 |
| EDGE08_ALTS_1H | UNI/USDT | trend_pullback | 546 | 546 | 517 | 517 | 0 | 0 |
| EDGE08_ALTS_1H | UNI/USDT | mean_reversion_vol_liq | 448 | 448 | 437 | 437 | 0 | 0 |
| EDGE07_HOLDOUT_1H | BTC/USDT | vol_regime_breakout | 14 | 14 | 14 | 14 | 0 | 0 |
| EDGE07_HOLDOUT_1H | BTC/USDT | trend_pullback | 59 | 59 | 56 | 56 | 0 | 0 |
| EDGE07_HOLDOUT_1H | BTC/USDT | mean_reversion_vol_liq | 31 | 31 | 30 | 30 | 0 | 0 |
| EDGE07_HOLDOUT_1H | ETH/USDT | vol_regime_breakout | 12 | 12 | 12 | 12 | 0 | 0 |
| EDGE07_HOLDOUT_1H | ETH/USDT | trend_pullback | 62 | 62 | 57 | 57 | 0 | 0 |
| EDGE07_HOLDOUT_1H | ETH/USDT | mean_reversion_vol_liq | 26 | 26 | 26 | 26 | 0 | 0 |
| EDGE07_HOLDOUT_1H | SOL/USDT | vol_regime_breakout | 9 | 9 | 9 | 9 | 0 | 0 |
| EDGE07_HOLDOUT_1H | SOL/USDT | trend_pullback | 45 | 45 | 44 | 44 | 0 | 0 |
| EDGE07_HOLDOUT_1H | SOL/USDT | mean_reversion_vol_liq | 26 | 26 | 26 | 26 | 0 | 0 |

## What the repair changes economically

See `ECONOMIC_RESTATEMENT.csv`: the deltas are per trade, per symbol and per family, and the
verdicts in `CURRENT_VS_PROPOSED.json` are recomputed on the repaired fills. A green number
that only exists because an exit was filled one bar early is not a number at all.
