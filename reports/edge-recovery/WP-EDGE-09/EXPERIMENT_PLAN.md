# WP-EDGE-09C — experiment plan (frozen before any measurement)

*Registered at `None`, before the panel was read. This document renders the registration; the registration is the contract.*

## 1. Grid, horizons and tracks

- Grid: 1 s. Decision horizons: 1, 5, 60 s.
- Frequency horizons: 1, 5, 60, 900, 3600 s.
- Universe: BTCUSDT, ETHUSDT, SOLUSDT over spot, perp.
- ACTIVE keeps the objective of **3.0 executed trades a day** across the aggregate universe; no trade is forced to reach it.
- QUALITY is judged separately, floor 0.05 trades/day.

## 2. Thresholds

| Threshold | Value |
| --- | ---: |
| `min_observations` | 500 |
| `min_abs_ic` | 0.01 |
| `admission_safety_multiple` | 1.5 |
| `active_frequency_target_trades_per_day` | 3.0 |
| `quality_frequency_floor_trades_per_day` | 0.05 |

## 3. Filter ladder, applied in this order

| # | Filter | Rule |
| --- | --- | --- |
| F0 | information | the feature must order the forward return (|Spearman IC| >= 0.01, n >= 500) |
| F1 | gross edge | mean gross move in bps must be positive on the pooled sample |
| F2 | cost survival | mean gross >= the measured round-trip cost of the venue/asset, in bps |
| F3 | admission margin | mean gross >= 1.5 x round-trip cost (the frozen safety multiple) |
| F4 | capacity | the measured book must absorb the order size inside the barrier; failing it is CAPACITY_KILLED |
| F5 | frequency | the structure must offer >= 3 executed opportunities per day (ACTIVE); failing it is FREQUENCY_KILLED |

## 4. Cost scenarios compared (all authoritative V3 specs)

| Scenario |
| --- |
| `BINANCE_SPOT_STANDARD_TAKER` |
| `MEXC_SPOT_TAKER` |
| `OKX_SPOT_TAKER` |
| `KRAKENPRO_SPOT_TAKER` |

## 5. Windows this plan may read

- **DEV**: the forward capture this repository already holds, declared in the window ledger; it is *not* a fresh holdout.
- **VAL**: only for a hypothesis that survives F3; the cost gate stopped every arm, so VAL was never opened.
- **FRESH_OOS / FORWARD**: never read by this package; the 60-day forward count never started.
- Holdouts consumed by WP-EDGE-07 and WP-EDGE-08 stay blocked and are listed in `WINDOW_LEDGER.jsonl` with `read_by_this_package: false`.

## 6. Stop rules

- `E-01` — quote imbalance is big enough to pay a taker round trip: **stops if** the best measured mean gross move at any horizon is below the measured round-trip cost for that asset
- `E-02` — the fee schedule is the binding constraint, not the signal: **stops if** no compared venue brings the round-trip cost at or below the measured gross move, including the venue with the lowest researched taker fee
- `E-03` — the measured book can absorb our order size inside the barrier: **stops if** the notional available within the barrier-implied price band is below the runtime's minimum order notional
- `E-04` — open interest with price is exploitable on a slower clock: **stops if** no quadrant cell reaches a positive mean gross move at or above the round-trip cost, or the sample is below the registered floor
- `E-05` — three executed trades a day is reachable by a positive structure: **stops if** the measured count of barrier-clearing opportunities per day is below the registered 3.0, no trade being forced to reach it
- `E-06` — a taker entry pays no more than the measured spread and impact: **stops if** the measured execution shortfall exceeds the modelled spread+impact component by more than the published tolerance
- `E-07` — negative control: the pipeline does not manufacture an edge: **stops if** the negative control reaches the positive classification, which would invalidate every other result in this package

## 7. Decision vocabulary

`ADMIT_RESEARCH`, `COST_KILLED`, `FREQUENCY_KILLED`, `CAPACITY_KILLED`, `NO_GROSS_EDGE`, `NO_INFORMATION`, `INSUFFICIENT_SAMPLE`, `LIMITED_HISTORY`, `NO_VIABLE_DATA`, `NON_EXECUTABLE_UNDER_RUNTIME`, `OBSERVED`.

## 8. Negative control

E-07 runs the identical pipeline on a feature destroyed by a deterministic shuffle; if it is classified positive, every other result of this package is void
