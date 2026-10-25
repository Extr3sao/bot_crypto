# ARP-005 — COST-AWARE PRE-FILTER (§6)

Purpose: **reject obviously cost-incompatible hypotheses before full backtesting.**
Never used to certify profitability. `available_move != strategy_edge` — ARP-004's
`EXP-ARP-007` proved this the hard way (capture ratio 0.0039 despite a favourable
1-day feasibility ratio).

Canonical round-trip cost: `COST_MODEL_V3` = **23.559016994374947 bps**.

## Available movement vs cost (measured, pooled BTC+ETH+SOL)

Mean absolute close-to-close move at horizon `H`, DEV split:

| H (days) | baseline pooled mean \|move\| | move/cost | extended pooled mean \|move\| | move/cost |
| --- | --- | --- | --- | --- |
| 1 | 198.4 bps | 8.42 | 226.4 bps | 9.61 |
| 5 | 430.0 bps | 18.25 | 496.5 bps | 21.07 |
| 10 | 648.6 bps | 27.53 | 736.1 bps | 31.24 |
| 30 | 1132.4 bps | 48.07 | 1282.3 bps | 54.43 |

(Method: pooled mean of `|close[i+H]/close[i] − 1| × 10000` over all symbol-days; a
*directional* strategy captures a fraction of this, which is why the ratio is only an
upper bound.)

## Pre-filter verdicts (declared before DEV)

| experiment | H | move/cost head-room | pre-filter | keep? |
| --- | --- | --- | --- | --- |
| `EXP-ARP-009` (30d-hold xsec) | ~30 | ≈54 | ample | KEEP |
| `EXP-ARP-011` (10d breakout) | 10 | ≈31 | ample | KEEP |
| `EXP-ARP-012` (5d reversal) | 5 | ≈21 | ≥ ~4× cost is the historical failure boundary | KEEP |

No candidate was rejected by the pre-filter — the mechanism families all operate on
horizons whose *available* move dwarfs the cost. The pre-filter is thus only a
screen; the actual cost survival is decided at the §9 COST stage, where it matters.

## What the DEV results then showed

The pre-filter was, correctly, **not** sufficient to certify anything:

- `EXP-ARP-009` available ratio ≈54 → realised gross **−100.1 bps** (negative edge).
- `EXP-ARP-011` available ratio ≈31 → realised gross **−63.3 bps** (2 trades; noise).
- `EXP-ARP-012` available ratio ≈21 → realised gross **+27.6 bps** (positive, survives
  1.0× cost with +4.05 bps net, fails at 1.25×).

**Lesson reinforced:** head-room ≠ edge. The pre-filter is retained only to discard
hypotheses whose horizon cannot possibly clear cost.
