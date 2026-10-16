# E14-01 — REGIME_CONDITIONED_VOL_BREAKOUT

*Priority 1. Source SRC-03 @ `7a8768de9784dda35a7b261a7ade1dbfbff50919`.*

## Hypothesis

a range breakout sized to realised volatility, entered only when a regime filter says the market is trending, carries a net move that covers the admission round trip on 1h/4h bars

## Locked parameters

- `range_lookback_bars`: 20
- `vol_atr_lookback_bars`: 14
- `breakout_multiple`: 1.0
- `regime_filter`: close > ema200 and ema50 > ema200
- `exit`: opposite range boundary or 3-bar hold, whichever first

## Test plan

frozen train/validation/OOS split; walk-forward with purged folds; null and CURRENT comparators; nominal and 2x variable-cost stress

## Duplicate scan

- judgement: **DUPLICATE_REJECT**
- token coverage: 1.0
- named overlap families present: ['breakout_family', 'volatility_family']
- families carrying a token: ['alpha_recovery', 'breakout_family', 'cross_sectional', 'diversified_xsec', 'diversified_xsec_riskadj', 'ema_crossover_family', 'mean_reversion_family', 'momentum_family', 'trend_family', 'volatility_family']

Research only: no orders, no credentials, no capital.
