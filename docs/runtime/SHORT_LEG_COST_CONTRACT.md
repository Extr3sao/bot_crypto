# SHORT_LEG_COST_CONTRACT

Implemented in `src/trading_bot/research/pair/costs.py`.

## The rule that matters

A short leg is **not free**. The cost model refuses to invent a cost that is not
observed. If the short instrument declares `borrow_required=True` and no authoritative
borrow evidence is supplied, the short cost is **`UNKNOWN`** — never `0`.

```
borrow_required=True, borrow_rate=None
  → short.total_short_cost = None
  → CostKnowledge.UNKNOWN
  → breakdown.economically_executable = False
  → blocked_reason = "SHORT_LEG_UNCOSTED"
  → simulator downgrades a would-be BOTH_FILLED to PAIR_FAILED
```

`zero_borrow_forbidden = true` is carried from the frozen EXP-ARP-023 manifest.

## Components (each an independent economic line)

| component | source | knowledge |
| --- | --- | --- |
| `long_cost` | COST_MODEL_V3 (23.559016994374947 bps RT) | OBSERVED/CONFIGURED |
| `short_fees` | venue fee schedule | CONFIGURED |
| `short_spread` | observed spread | OBSERVED |
| `short_slippage` | execution model | ESTIMATED |
| `borrow` | margin borrow rate × days | OBSERVED/UNKNOWN |
| `funding` | perpetual funding (signed) | OBSERVED/UNKNOWN |
| `basis` | futures-spot basis | OBSERVED/UNKNOWN |

`funding` and `basis` default to `0.0` **only** when the instrument declares them
non-applicable (`funding_applicable=False` / `basis_applicable=False`). Otherwise a
missing value is `UNKNOWN`.

## PIT safety

Every `ShortLegCost` carries `source_timestamp` and `availability_timestamp`. A cost
whose `availability_timestamp > decision_time` raises `ShortLegCostError` ("not
PIT-safe") — a future cost can never be used to make a past decision look viable.

## No single-cost shortcut

The long leg and the short leg are priced independently. There is no scalar
"pair cost". A test asserts that changing only the short cost changes only the short
components and never the long cost, and that each cost is charged exactly once.
