# E14-04 — CROSS_ASSET_LEAD_LAG_TRANSMISSION

*Priority 2. Source SRC-02 @ `5e642997f9623d67b63543962eab46caca30e613`.*

## Hypothesis

when a large BTC move has not yet propagated to a correlated liquid alt, the un-propagated residual carries a net move that covers the round trip; the edge is the timing gap between assets, not the direction of either

## Locked parameters

- `signal_asset`: BTC/USDT
- `shock_threshold_sigma`: 1.5
- `sigma_lookback_bars`: 48
- `propagation_window_bars`: 2
- `entry`: alt still below its own expected co-move after the shock
- `exit`: the residual closes or 3 bars elapse

## Test plan

synchronised multi-asset OOS held out; residual measured on closed bars only; co-move expectation estimated on the training window and frozen; compared against own-asset momentum and buy-and-hold

## Duplicate scan

- judgement: **NOT_DUPLICATE_RETAINED**
- token coverage: 0.0
- named overlap families present: none
- families carrying a token: none

Research only: no orders, no credentials, no capital.
