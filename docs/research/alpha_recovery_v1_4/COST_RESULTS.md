# ARP-005 — COST RESULTS (§9)

Only `EXP-ARP-012` reached the COST stage (the other two failed DEV). Gross expectancy
is unchanged by cost; only net moves.

Canonical cost = 23.559016994374947 bps; gross kill threshold = 23.559 bps.

## EXP-ARP-012 — cost stress (DEV)

| multiple | cost bps | gross bps | net bps | PF | verdict |
| --- | --- | --- | --- | --- | --- |
| 0.5× | 11.780 | +27.610 | **+15.831** | 1.056 | survive |
| 1.0× | 23.559 | +27.610 | **+4.051** | 1.014 | survive |
| 1.25× | 29.449 | +27.610 | **−1.839** | 0.994 | fail |
| 1.5× | 35.339 | +27.610 | **−7.728** | 0.974 | fail |
| 2.0× | 47.118 | +27.610 | **−19.508** | 0.935 | fail |

- **break-even cost = 27.610 bps** (the gross expectancy).
- Cost/trade = 23.56 bps; gross-edge/cost ratio ≈ **1.17**.
- COST stage result: **PASS** — the frozen criterion is `gross > 23.559 bps` and the
  base-cost net is positive.

## Honest fragility note

The candidate **survives only at ≤ 1.0× canonical cost** and is negative at 1.25×.
A gross-edge/cost ratio of 1.17 is a razor-thin margin. This is *not* a
`REJECT_COSTS` under the frozen rule (gross > threshold), but it is a strong
`REJECT_FRAGILE`/`REJECT_VALIDATION` risk, and it is flagged as such for the next
stage. (The frozen rules are not edited after seeing results.)

## Not reached

- `EXP-ARP-009` — COST NOT_REACHED (DEV INSUFFICIENT_EVIDENCE).
- `EXP-ARP-011` — COST NOT_REACHED (DEV INSUFFICIENT_EVIDENCE).

`COST survivors = 1` (EXP-ARP-012) → proceeds to VALIDATION.
