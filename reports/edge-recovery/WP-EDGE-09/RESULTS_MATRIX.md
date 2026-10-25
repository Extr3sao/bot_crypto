# WP-EDGE-09E — results matrix

*`2026-10-15T05:16:16Z`. Every registered hypothesis appears here, rejected ones included.*

| Hypothesis | Track | Registered criterion | Measured | Classification |
| --- | --- | --- | --- | --- |
| `E-01` | ACTIVE | the best measured mean gross move at any horizon is below the measured round-trip cost for that asset | best measured cell perp/SOLUSDT h=60s gross 1.582703 bps vs 24.0731 bps barrier — gross 1.5827 bps is below the measured round trip 24.0731 bps (cells: {'COST_KILLED': 30}) | **COST_KILLED** |
| `E-02` | CROSS-VENUE | no compared venue brings the round-trip cost at or below the measured gross move, including the venue with the lowest researched taker fee | the cheapest registered schedule (MEXC_SPOT_TAKER at 12.9866 bps) still exceeds the best measured gross (1.582703 bps): the fee schedule is not the only constraint | **COST_KILLED** |
| `E-03` | ACTIVE | the notional available within the barrier-implied price band is below the runtime's minimum order notional | spot depth snapshots are rare in this capture, so a spot capacity claim rests on a small number of observations and is reported as such | **OBSERVED** |
| `E-04` | QUALITY | no quadrant cell reaches a positive mean gross move at or above the round-trip cost, or the sample is below the registered floor | PRICE_DOWN_OI_UP n=14 mean=-8.015351 bps against a barrier of 23.1512 bps | **INSUFFICIENT_SAMPLE** |
| `E-05` | ACTIVE | the measured count of barrier-clearing opportunities per day is below the registered 3.0, no trade being forced to reach it | the tape clears the barrier at h=60s at 144.061 long-only opportunities/day (upper bound, long-only, extrapolated from 1.999-4.155 h of capture), so the ACTIVE frequency target is not what blocks the book at those horizons | **OBSERVED** |
| `E-06` | EXECUTION | the measured execution shortfall exceeds the modelled spread+impact component by more than the published tolerance | median measured taker shortfall 0.0187 bps against the modelled spread+impact components | **OBSERVED** |
| `E-07` | GUARD | the negative control reaches the positive classification, which would invalidate every other result in this package | negative control verdicts: ['COST_KILLED', 'NO_GROSS_EDGE', 'NO_INFORMATION'] | **NO_GROSS_EDGE** |

## CURRENT vs PROPOSED

Status: **NOT_PRODUCIBLE** — no arm reached simulation: the registered F2/F3 cost filters rejected every hypothesis before a backtest, so there is no PROPOSED trade list and therefore no paired CURRENT/PROPOSED PnL to publish. Producing one would require inventing trades the gate forbade.

the measured cost barrier against the measured best gross and against the tape's own frequency bound, all on the same panel and the same cost model

Negative control: ['COST_KILLED', 'NO_GROSS_EDGE', 'NO_INFORMATION'], `false_success = 0`.
