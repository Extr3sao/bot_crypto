# SOURCE DEPENDENCY MAP — EXP-003O

Generated from the files' own AST, not from prose. Every row is what `ast.parse`
found in the file named in the first column. A module that does not exist yet is
listed as absent rather than guessed.

## Producer chain (EXP-003N, frozen, read-only)

| module | imports (as written) |
| --- | --- |
| `scripts/exp_003n_screen.py` | `__future__`, `argparse`, `dataclasses`, `datetime`, `gzip`, `hashlib`, `json`, `numpy`, `numpy.typing`, `pathlib`, `sys`, `trading_bot.market_data.types`, `trading_bot.research.economic_recovery.alpha15`, `trading_bot.research.economic_recovery.experiments`, `trading_bot.research.economic_recovery.pit15`, `trading_bot.vision.signal_sources`, `typing` |
| `src/trading_bot/vision/signal_sources.py` | `__future__`, `collections.abc`, `dataclasses`, `datetime`, `hashlib`, `inspect`, `json`, `pathlib`, `trading_bot.indicators.builtin`, `trading_bot.indicators.exceptions`, `trading_bot.indicators.types`, `trading_bot.market_data.types`, `trading_bot.research.families.breakout_family`, `trading_bot.research.families.ema_crossover_family`, `trading_bot.research.families.mean_reversion_family`, `trading_bot.research.families.momentum_family`, `trading_bot.research.families.trend_family`, `trading_bot.research.families.volatility_family`, `trading_bot.vision.clock`, `trading_bot.vision.prospective`, `trading_bot.vision.provider`, `typing` |
| `src/trading_bot/research/families/ema_crossover_family.py` | `..types`, `__future__`, `collections.abc`, `trading_bot.indicators.builtin`, `trading_bot.indicators.types`, `trading_bot.market_data.types` |
| `src/trading_bot/research/families/momentum_family.py` | `..types`, `__future__`, `collections.abc`, `trading_bot.indicators.builtin`, `trading_bot.indicators.types`, `trading_bot.market_data.types` |
| `src/trading_bot/research/families/breakout_family.py` | `..types`, `__future__`, `collections.abc`, `trading_bot.indicators.builtin`, `trading_bot.indicators.types`, `trading_bot.market_data.types` |
| `src/trading_bot/research/families/mean_reversion_family.py` | `..types`, `__future__`, `collections.abc`, `trading_bot.indicators.builtin`, `trading_bot.indicators.types`, `trading_bot.market_data.types` |
| `src/trading_bot/research/families/trend_family.py` | `..types`, `__future__`, `collections.abc`, `trading_bot.indicators.builtin`, `trading_bot.indicators.types`, `trading_bot.market_data.types` |
| `src/trading_bot/research/families/volatility_family.py` | `..types`, `__future__`, `collections.abc`, `trading_bot.indicators.builtin`, `trading_bot.indicators.types`, `trading_bot.market_data.types` |
| `src/trading_bot/indicators/builtin.py` | `.exceptions`, `__future__`, `collections.abc`, `itertools`, `math`, `statistics`, `trading_bot.market_data.types`, `typing` |
| `src/trading_bot/research/economic_recovery/pit15.py` | `.experiments`, `__future__`, `collections`, `collections.abc`, `dataclasses`, `math`, `statistics`, `typing` |
| `src/trading_bot/research/economic_recovery/alpha15.py` | `.experiments`, `.pit15`, `__future__`, `collections.abc`, `dataclasses`, `itertools`, `math`, `statistics`, `typing` |
| `src/trading_bot/research/economic_recovery/experiments.py` | `.costs`, `.evidence`, `__future__`, `dataclasses`, `datetime`, `hashlib`, `json`, `pathlib`, `typing` |

## Independent rebuilder (EXP-003O)

| module | imports (as written) |
| --- | --- |
| `scripts/exp_003o_rebuilder.py` | **not written yet at baseline time** |
