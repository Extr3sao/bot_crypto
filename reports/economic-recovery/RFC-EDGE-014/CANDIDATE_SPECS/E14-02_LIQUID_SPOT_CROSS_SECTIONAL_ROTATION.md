# E14-02 — LIQUID_SPOT_CROSS_SECTIONAL_ROTATION

*Priority 2. Source SRC-02 @ `5e642997f9623d67b63543962eab46caca30e613`.*

## Hypothesis

rotating into the top-k liquid spot assets by relative 4h/1d return, with a concentration cap and a minimum-notional floor, carries a net cross-sectional return above the rebalance friction

## Locked parameters

- `top_k`: 2
- `rebalance`: daily_00utc
- `weighting`: equal
- `max_weight`: 0.5
- `min_notional_usdt`: 20.0

## Test plan

asset-level OOS held out; rebalance friction charged per name; compare against the diversified cross-section and against buy-and-hold

## Duplicate scan

- judgement: **DUPLICATE_REJECT**
- token coverage: 1.0
- named overlap families present: ['cross_sectional', 'diversified_xsec', 'diversified_xsec_riskadj']
- families carrying a token: ['alpha_recovery', 'cross_sectional', 'diversified_xsec', 'diversified_xsec_riskadj']

Research only: no orders, no credentials, no capital.
