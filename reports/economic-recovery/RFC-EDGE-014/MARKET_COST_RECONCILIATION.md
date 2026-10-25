# WP-EDGE-14B — market cost reconciliation

*Primary source `C:\Users\GVLLFR0035\Downloads\bot freebuff\reports\edge-recovery\WP-EDGE-09\gates\COST_LIQUIDITY_CAPACITY.json` (`a48e106e16b2346a…`), untouched: True.*

**Verdict `ECONOMIC_INTEGRITY_RECONCILED`.**

## The legitimate same-population share

| scenario | n streams | mean fee (bps) | mean round trip (bps) | share |
| --- | --- | --- | --- | --- |
| BINANCE_SPOT_STANDARD_TAKER | 10 | 20.0 | 23.27783 | 85.92% |

## The published ratio, reproduced and explained

| side | value (bps) | population | n |
| --- | --- | --- | --- |
| numerator | 32.5 | all_registered_venue_schedules | 4 |
| denominator | 23.443933 | admission_scenario_only | 6 |

Reproduced `1.386286` — matches the published 1.3863: **True**.

Defect: `population_mismatch`. the published 1.3863 divides a cross-venue mean fee by an admission-only mean barrier; the fee was not double counted and no identity was broken in the gate, the identity was broken by the sentence at render time

Correct statement: the fee is 85.9% of the admission round trip (20 bps of 23.2778 bps); the 1.3863 ratio mixes four venue schedules with one admission scenario and must not be read as a cost share

## Per-scenario breakdowns

| scenario | mean fee | mean round trip | status |
| --- | --- | --- | --- |
| BINANCE_SPOT_STANDARD_TAKER | 10.0 | 23.27783 | RECONCILED |
| KRAKENPRO_SPOT_TAKER | 40.0 | 83.27783 | RECONCILED |
| MEXC_SPOT_TAKER | 5.0 | 13.27783 | RECONCILED |
| OKX_SPOT_TAKER | 10.0 | 23.27783 | RECONCILED |
