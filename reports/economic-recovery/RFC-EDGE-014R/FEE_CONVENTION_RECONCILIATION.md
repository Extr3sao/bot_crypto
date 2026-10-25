# WP-EDGE-14R/P4 — fee convention and unit reconciliation

*Every cost in this package, in one unit system, with each residual reproduced from the primitive numbers.*

## Units

| unit | meaning |
| --- | --- |
| `bps_per_side` | the declared commission on one leg, as a fraction x 1e4 |
| `bps_per_round_trip` | 2 x bps_per_side, the figure the admission barrier uses |
| `price_space_bps` | slippage is applied to the price, not to the notional, so it is a price-space cost and is not interchangeable with a commission |
| `per_leg_notional` | each leg's commission charged on that leg's own notional |
| `entry_notional` | both legs' commission charged on the entry notional |

## The two commission conventions

- `ADDITIVE`: net_bps = gross_bps - 2 * fees_bps_per_side
- `COMPOUNDED`: net_bps = ((1 + gross_bps/1e4) * (1 - f)^2 - 1) * 1e4
- `closed_form_gap`: COMPOUNDED(g) - ADDITIVE(g) = 1e4 * ((1 - f)^2 - 1) * (1 + g/1e4) + 2f*1e4 = 2f*1e4 - 1e4*(2f - f^2)*(1 + g/1e4)

## External engines

| engine | declared (bps/side) | matched | identity holds | max identity error (bps) | max gap recomputed (bps) |
| --- | ---: | --- | --- | ---: | ---: |
| `freqtrade` | 10.0 | COMPOUNDED | True | 8.563e-07 | 1.169343 |
| `vnpy_ctastrategy` | 10.0 | ADDITIVE | True | 4.919e-07 | 1.169343 |
| `jesse` | 10.0 | COMPOUNDED | True | 8.425e-07 | 1.169343 |

The identity checked for every matched trade is
`net_diff_additive - net_diff_compounded == COMPOUNDED(g) - ADDITIVE(g)` — the
convention gap is a function of the gross move alone, so it can be predicted and
not merely observed. The published `convention_difference_bps` is the difference of
two max-of-abs residuals, which is *not* the per-trade gap; both are reported.

## Paper broker

- commission 5.0 bps per fill = 10.0 bps per round trip;
- slippage 1.0 bps per side, applied in price space (buy: price * (1 + bps/1e4), sell: price / (1 + bps/1e4)) before sizing, so the traded notional is unchanged and the cost is ~1.0 bps of the reference price per side;
- 347 closed fills audited against the broker's own rule;
- max residual against that rule: 8.882e-16 (entry-notional reference) and 5.171e-03 (own-leg reference);
- the broker charges the exit commission on the entry notional; charging it on each leg's own notional instead is the difference the parity harness's COMPOUNDED convention models. The residual between the two grows with the move: commission_bps * |g| / 1e4 of the entry notional per round trip. The small remaining difference against the broker's own rule is the rounding of the recorded quantity and price, and it is published rather than absorbed.

## What is left unexplained

- nothing in the engines' rows: the identity holds to machine precision on every matched trade;
- the paper broker's rounding residual is 8.882e-16 in quote currency and is published as a residual rather than folded into the charged amount.
