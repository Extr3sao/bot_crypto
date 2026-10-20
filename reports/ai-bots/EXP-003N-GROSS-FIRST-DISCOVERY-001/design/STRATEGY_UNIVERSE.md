# STRATEGY UNIVERSE — EXP-003N

Computed from `9800925` at 2026-10-20T18:38:47Z.
A class counts as wired where an import or an instantiation exists, not where a name
appears in prose. `scripts/exp_003n_preregister.py` derives every row.

## Counts

| classification | classes |
| --- | ---: |
| `EXPERIMENTAL` | 3 |
| `RESEARCH_ONLY` | 6 |
| `RUNTIME_REACHABLE` | 6 |
| `TEST_ONLY` | 1 |

## Classes

| module | class | classification | screened here | references |
| --- | --- | --- | --- | --- |
| `src/trading_bot/research/economic_recovery/pit15.py` | `BreakoutMachine` | `RESEARCH_ONLY` | no | scripts=2, tests=2 |
| `src/trading_bot/research/economic_recovery/pit15.py` | `MeanReversionMachine` | `RESEARCH_ONLY` | no | scripts=2, tests=2 |
| `src/trading_bot/research/economic_recovery/pit15.py` | `PullbackMachine` | `RESEARCH_ONLY` | no | scripts=2, tests=2 |
| `src/trading_bot/research/experimental/cand_001_ma_pullback.py` | `MaPullbackFamily` | `EXPERIMENTAL` | no | research=3 |
| `src/trading_bot/research/experimental/cand_002_mtf_alignment.py` | `MtfAlignedMaPullbackFamily` | `EXPERIMENTAL` | no | research=2, scripts=1, tests=1 |
| `src/trading_bot/research/experimental/cand_003_macd_regime_crossover.py` | `MacdRegimeCrossoverFamily` | `EXPERIMENTAL` | no | research=2 |
| `src/trading_bot/research/families/breakout_family.py` | `BreakoutFamily` | `RUNTIME_REACHABLE` | yes | adapter=1, research=1, scripts=5 |
| `src/trading_bot/research/families/ema_crossover_family.py` | `EmaCrossoverFamily` | `RUNTIME_REACHABLE` | yes | adapter=1, research=1, scripts=5, tests=3 |
| `src/trading_bot/research/families/mean_reversion_family.py` | `MeanReversionFamily` | `RUNTIME_REACHABLE` | yes | adapter=1, research=1, scripts=5 |
| `src/trading_bot/research/families/momentum_family.py` | `MomentumFamily` | `RUNTIME_REACHABLE` | yes | adapter=1, research=1, scripts=5 |
| `src/trading_bot/research/families/trend_family.py` | `TrendFamily` | `RUNTIME_REACHABLE` | yes | adapter=1, research=1, scripts=5 |
| `src/trading_bot/research/families/volatility_family.py` | `VolatilityFamily` | `RUNTIME_REACHABLE` | yes | adapter=1, research=1, scripts=5 |
| `src/trading_bot/research/managed_futures_v1.py` | `ManagedFuturesV1` | `RESEARCH_ONLY` | no | scripts=2 |
| `src/trading_bot/research/small_capital_dual_momentum_v1.py` | `SmallCapitalDualMomentumV1` | `RESEARCH_ONLY` | no | scripts=1 |
| `src/trading_bot/research/small_capital_v1.py` | `SmallCapitalV1` | `RESEARCH_ONLY` | no | research=4, scripts=2 |
| `src/trading_bot/strategies/ema_crossover.py` | `EmaCrossoverStrategy` | `TEST_ONLY` | no | tests=1 |

## WP-EDGE-015 families (configuration, not classes)

| family | status | screened here | why it differs |
| --- | --- | --- | --- |
| `cross_sectional_rotation` | `TESTED` | no | lead_lag |
| `maker_only_spread_capture` | `DEFER_NO_FILL_MODEL` | no | — |
| `mean_reversion_vol_liq` | `TESTED` | yes | breakout@5m, ema_crossover@5m, lead_lag |
| `trend_pullback` | `TESTED` | yes | ema_crossover@5m |
| `vol_regime_breakout` | `TESTED` | yes | breakout@5m, ema_crossover@5m |
