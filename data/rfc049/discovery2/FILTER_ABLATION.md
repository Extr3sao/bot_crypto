# RFC-049 DISCOVERY 2 — FILTER ABLATION (DIAGNOSTIC)

- generated: `2026-10-10T16:39:53Z` · head `2d113a0ae82f`
- classification: **DIAGNOSTIC / non-confirmatory**. Nothing is adopted. H-049-001 and H-049-002 are not modified.
- base: the declared 200-day trend state machine; arms conjunctive with the liquidity states.

| arm | partition | round trips | net sum (bps) | expectancy (bps) | PF | max DD | sub-windows positive |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| base | development | 11 | 38696.7 | 3517.9 | 6.583 | 0.426 | 2/3 |
| base | validation | 6 | 1124.8 | 187.5 | 1.390 | 0.189 | 2/2 |
| base+stablecoin | development | 12 | 25409.7 | 2117.5 | 5.264 | 0.515 | 2/3 |
| base+stablecoin | validation | 8 | -246.3 | -30.8 | 0.949 | 0.257 | 2/3 |
| base+macro | development | 18 | 25822.8 | 1434.6 | 3.516 | 0.484 | 2/3 |
| base+macro | validation | 15 | 663.1 | 44.2 | 1.119 | 0.318 | 2/3 |
| base+both | development | 12 | 12082.4 | 1006.9 | 3.401 | 0.361 | 3/3 |
| base+both | validation | 15 | -481.3 | -32.1 | 0.907 | 0.295 | 2/3 |

## Deltas versus the base

A conjunctive filter is not a subset: gating can split one base position into several shorter ones, so the trip count can move either way. `reshaped or dropped` counts base trips whose entry/exit pair is not preserved exactly.

| arm | partition | trips (base → arm) | preserved exactly | reshaped or dropped | net delta (bps) | DD delta |
| --- | --- | --- | ---: | ---: | ---: | ---: |
| base+stablecoin | development | 11 → 12 | 0 | 11 | -13287.0 | +0.088 |
| base+stablecoin | validation | 6 → 8 | 1 | 5 | -1371.0 | +0.068 |
| base+macro | development | 11 → 18 | 4 | 7 | -12873.9 | +0.058 |
| base+macro | validation | 6 → 15 | 1 | 5 | -461.7 | +0.129 |
| base+both | development | 11 → 12 | 0 | 11 | -26614.3 | -0.066 |
| base+both | validation | 6 → 15 | 1 | 5 | -1606.0 | +0.106 |

## Base arm by liquidity regime at entry

| regime | round trips | net sum (bps) | mean net (bps) |
| --- | ---: | ---: | ---: |
| both_long | 3 | 36470.2 | 12156.7 |
| stablecoin_only | 3 | 3768.9 | 1256.3 |
| macro_only | 4 | -5000.0 | -1250.0 |
| neither | 7 | 4582.3 | 654.6 |

## Adoption

**NOT_ADOPTED.** no ACTIVE strategy exists as an adoption target today (paper ledger: 0 admitted, PAPER_ACTIVE=0) all numbers are RESEARCH_EXPOSED and non-confirmatory the operator's adoption rule requires reproducible improvement outside the data used to select the filter (forward evidence), which does not exist yet

A future decision requires: a new admitted hypothesis with its own budget and frozen rules; forward (post-selection) data showing the improvement survives.

- base reproduces the engine's trend comparator: **PASS** (dev 5.467491597291395 vs 5.467491597291395; val 0.06480066532079909 vs 0.06480066532079909)
