# E14-03 — CONDITIONAL_EXTREME_MEAN_REVERSION

*Priority 3. Source SRC-03 @ `7a8768de9784dda35a7b261a7ade1dbfbff50919`.*

## Hypothesis

a mean reversion entered only after an extreme displacement beyond a volatility-scaled band, and only when the short-horizon trend is not persistent, reverts enough to cover the round trip

## Locked parameters

- `band_sigma`: 2.5
- `sigma_lookback_bars`: 96
- `persistence_filter`: abs(1h return) < 1.5x atr
- `exit`: revert to the band mean or 4-bar timeout

## Test plan

OOS held out; spread-sensitivity sweep; explicit persistent-trend failure analysis before any acceptance

## Duplicate scan

- judgement: **DUPLICATE_REJECT**
- token coverage: 0.6
- named overlap families present: ['mean_reversion_family']
- families carrying a token: ['alpha_recovery', 'mean_reversion_family', 'volatility_family']

Research only: no orders, no credentials, no capital.
