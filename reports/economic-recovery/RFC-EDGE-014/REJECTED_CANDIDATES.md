# WP-EDGE-14D — rejected candidates

3 of 4 hypotheses were rejected as duplicates of families already in the tree. A duplicate is never renamed to look new.

## Rejected

| id | family | duplicated of | reason |
| --- | --- | --- | --- |
| E14-01 | REGIME_CONDITIONED_VOL_BREAKOUT | breakout_family, volatility_family | shares mechanism tokens with ['breakout_family', 'volatility_family'] (token coverage 1.0) |
| E14-02 | LIQUID_SPOT_CROSS_SECTIONAL_ROTATION | cross_sectional, diversified_xsec, diversified_xsec_riskadj | shares mechanism tokens with ['cross_sectional', 'diversified_xsec', 'diversified_xsec_riskadj'] (token coverage 1.0) |
| E14-03 | CONDITIONAL_EXTREME_MEAN_REVERSION | mean_reversion_family | shares mechanism tokens with ['mean_reversion_family'] (token coverage 0.6) |

## Retained

| id | family | status | hypothesis |
| --- | --- | --- | --- |
| E14-04 | CROSS_ASSET_LEAD_LAG_TRANSMISSION | STRATEGY_CANDIDATE | when a large BTC move has not yet propagated to a correlated liquid alt, the un-propagated residual carries a net move that covers the round trip; the edge is the timing gap between assets, not the direction of either |
