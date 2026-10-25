# ARP-004 — COST ANALYSIS (§9–§10)

Cost authority: `COST_MODEL_V3` / `BINANCE_SPOT_STANDARD_TAKER` from the live
`CostEngine` — **23.559016994374947 bps** round trip. Never hardcoded.

## EXP-ARP-007 (the only DEV survivor)

DEV combined, gross expectancy **+0.776 bps**. Break-even round-trip cost = **0.776 bps**
(the cost at which net hits zero). At the canonical 1.0× cost the net is **−22.783 bps**.

`COST_MODEL_V3` stress (DEV):

| multiple | cost (bps) | gross (bps) | net (bps) | profit factor |
| --- | --- | --- | --- | --- |
| 0.5× | 11.780 | +0.776 | −11.004 | 0.9056 |
| 1.0× | **23.559** | +0.776 | **−22.783** | 0.8137 |
| 1.25× | 29.449 | +0.776 | −28.673 | 0.7709 |
| 1.5× | 35.339 | +0.776 | −34.563 | 0.7301 |
| 2.0× | 47.118 | +0.776 | −46.342 | 0.6540 |

**Gate result: `REJECT_COSTS`.** Net ≤ 0 at the canonical 1.0× cost (§10), and gross
(0.776 bps) is ~30× below the frozen `gross ≤ 23.559 bps → REJECT_COSTS` criterion. The
result is not merely cost-fragile (`REJECT_COST_FRAGILE`) — it does not clear cost even
at 0.5× (net −11.0 bps). 0.5× is robustness context only; the canonical 1.0× decides.

## EXP-ARP-010

Not applicable — the experiment stopped at the DEV sample gate (`INSUFFICIENT_EVIDENCE`,
6 trades), so no cost stage was run and no cost claim is made. Its DEV gross was
−75.059 bps (already negative before any cost).

## Context from ARP-003

The ARP-003 feasibility frontier placed the 1-day opportunity/cost ratio at ≈8.2. That
is the ceiling a *perfect* capture could reach, not a mechanism's realized edge.
`EXP-ARP-007` captured **0.39 %** of the available daily move. A favourable frontier
ratio is necessary but nowhere near sufficient.
