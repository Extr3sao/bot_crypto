# WP-EDGE-14R/P2 — external engine execution

*Three engines were installed in their own environments, fed the same frozen rule and
window, and run. All three executed. This file is the three-engine summary; each engine's
detail is in its own file, and the earlier freqtrade-only content under this name is
preserved verbatim as `EXTERNAL_ENGINE_EXECUTION_FREQTRADE.json`.*

| engine | outcome | version | trades | matched | count gap | max gross diff (bps) | matched residual (bps) | verdict |
| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | --- |
| `freqtrade` | **EXECUTED** | unknown | 44 | 44 | 0 | 0.0 | 0.010569 | AGREE_WITHIN_TOLERANCE |
| `jesse` | **EXECUTED** | 3.3.5 | 44 | 44 | 0 | 6.985523 | 7.021359 | DIVERGENT |
| `vnpy_ctastrategy` | **EXECUTED** | unknown | 42 | 42 | 2 | 0.0 | 0.0 | AGREE_ON_MATCHED_TRADES_WITH_DECLARED_EXTRA |

## The dataset is one dataset

- the frozen 1-hour export `sha256:d79ed2c56bf50226…` is what freqtrade and VeighNa read;
- Jesse consumes **1-minute** source rows and generates the 1h candles inside its own
  backtest — that is an engine constraint, not a setting: its aggregation release is keyed
  on a source row at `bucket_end - 60_000`, which a 1h-spaced series does not have;
- the 1-minute source was therefore fetched for the same window from the same venue and
  audited against the frozen bars: every closed bar aggregates to exactly the frozen OHLC
  (`JESSE_1M_SOURCE_AUDIT.json`, `identical_to_frozen_1h: true`);
- the frozen dataset's **final** bar was captured while its hour was still forming; it is
  excluded from the Jesse comparison on both sides and named in
  `closed_window.excluded_final_bar` rather than quietly kept.

## Environment locks

- `freqtrade`: `ENVIRONMENT_LOCKS/freqtrade.txt`
- `jesse`: `ENVIRONMENT_LOCKS/jesse.txt`
- `vnpy_ctastrategy`: recorded in `EXTERNAL_ENGINE_EXECUTION_VNPY.json`

## What each engine needed

- `freqtrade` ran from its own venv as `python -m freqtrade backtesting`, one invocation
  per pair, exporting its trades as JSON.
- `veighna` ran its CTA strategy engine via `scripts/edge14r_vnpy_backtest.py`; it
  publishes fills, not round trips, and has no crypto venue, both of which are declared
  rather than papered over.
- `jesse` needed three real fixes before it would run, each recorded rather than hidden:
  its project bootstrap (`coordination_runtime`) had to be started the way its own CLI
  does; its candle rows are `[timestamp, open, close, high, low, volume]`, not OHLC; and
  **Jesse 3.3.5 has no `should_exit` hook** — exits belong in `update_position()` and a
  strategy that defines `should_exit` has a method the engine never calls. Two further
  funding artefacts were fixed rather than worked around: one route per run (a shared spot
  balance leaves the second symbol unfunded) and a fee reserve on entry sizing.

## Divergence

Jesse matched 44/44 entries and agreed to within 1 bps on 42 trades (11 exactly). The two
material differences are the positions still open at the window's end, where neither
engine has an exit signal and the trailing close is a convention: this project closes at
the final bar's open, Jesse closes at the final bar's close. That is a model difference in
the forced exit, and it is why its verdict is DIVERGENT rather than AGREE.

## Limitations

- agreement between engines is evidence about their accounting, not about any strategy's edge;
- slippage is held at zero on every arm, because it is a model input and not an engine
  behaviour, and giving the engines different slippage models would confound the measurement;
- no engine's code is imported by the runtime or copied into the tree: each runs in its own
  environment outside the checkout;
- an environment manifest is a lockfile, not the environment.
