# WP-10 PHASE 5 — ACTIVE RECOVERY MATRIX

> `2026-10-12T06:08:55Z` · head `90ed615b1b2514682bbf9a85834fdd81c45f0774` · **PARTIAL**

Each family goes through an ordered chain and fails at exactly one stage:

* **ADOPT_FOR_NEW_EXPERIMENT** — a pre-registered rule returned PROMOTE on a reserved forward window
* **RESEARCH_MORE** — an edge exists and is resolvable, but it is short of the plane, or it has not yet passed the forward test
* **INSUFFICIENT_EVIDENCE** — a positive edge is claimed but cannot be believed yet: the interval is wider than the edge or the sign does not hold across partitions
* **REJECT** — no cell of the family shows a positive zero-cost gross edge

## 1. The matrix

| family | cells | positive cells | best cell | best gross bps | trades/day | verdict | blocking stage |
| --- | ---: | ---: | --- | ---: | ---: | --- | --- |
| `breakout` | 4 | 0 | `breakout@5m` | -0.084007 | 31.319 | **REJECT** | NO_EDGE |
| `ema_crossover` | 4 | 0 | `ema_crossover@30m` | -0.726 | 52.004 | **REJECT** | NO_EDGE |
| `mean_reversion` | 4 | 3 | `mean_reversion@30m` | 5.472 | 29.841 | **RESEARCH_MORE** | COST_GAP |
| `momentum` | 4 | 0 | `momentum@5m` | -1.883531 | 53.165 | **REJECT** | NO_EDGE |
| `trend` | 4 | 2 | `trend@30m` | 2.206 | 28.493 | **INSUFFICIENT_EVIDENCE** | UNRESOLVED |
| `volatility` | 4 | 2 | `volatility@30m` | 8.912 | 5.261 | **INSUFFICIENT_EVIDENCE** | UNRESOLVED |

Why each family stops where it stops:

* `breakout` → **REJECT**: the zero-cost gross edge is not positive: there is nothing for costs to eat
* `ema_crossover` → **REJECT**: the zero-cost gross edge is not positive: there is nothing for costs to eat
* `mean_reversion` → **RESEARCH_MORE**: the edge is resolvable but 17.881553 bps short of the frozen round trip
* `momentum` → **REJECT**: the zero-cost gross edge is not positive: there is nothing for costs to eat
* `trend` → **INSUFFICIENT_EVIDENCE**: the 95 % interval half width (4.771974 bps) is wider than the edge itself (2.206 bps)
* `volatility` → **INSUFFICIENT_EVIDENCE**: the 95 % interval half width (12.009576 bps) is wider than the edge itself (8.912 bps)

Verdict counts: INSUFFICIENT_EVIDENCE = 2, REJECT = 3, RESEARCH_MORE = 1.

## 2. Frequency is not what is missing

* objective: 3.0 operations/day
* trades/day across all 24 cells: 200.083
* trades/day across the cells with positive gross: 44.547

| cell | trades/day | gross bps | net vs the plane bps |
| --- | ---: | ---: | ---: |
| `ema_crossover@30m` | 15.618 | -0.726 | -24.0796 |
| `mean_reversion@5m` | 15.411 | 1.485392 | -21.8682 |
| `ema_crossover@15m` | 15.295 | -1.122 | -24.4756 |
| `momentum@15m` | 15.28 | -3.972 | -27.3256 |
| `momentum@30m` | 14.498 | -2.612 | -25.9656 |
| `ema_crossover@1h` | 12.758 | -0.964 | -24.3176 |

frequency is not the binding constraint: several cells already trade far above the objective's daily rate, and every one of them is net-negative. The objective is unmet because the net expectancy is, not because opportunities are rare — and no entry may be manufactured to close the gap.

## 3. The hurdle a new hypothesis must beat

* frozen round trip: **23.353553391 bps**
* best zero-cost gross edge in the register: 8.912 bps
* shortfall: 14.441553 bps
* a signal has to capture a price move larger than 23.354 bps per round trip before it can be net positive at the frozen plane; that is the number a new hypothesis must beat, and no threshold in this repository may be lowered to make it easier

## 4. What the measured execution cost changes (E-1)

* state: `PLANE_OVERSTATES_MICROSTRUCTURE`; observed round-trip microstructure 0.024697 bps versus 20.0 bps of KNOWN fees
* the best gross edge clears the fee legs alone: `False`
* cheaper execution narrows the bar; it does not clear it. The fee legs alone already exceed the best gross edge in the register

## 5. The forward gate (stage 4)

* E-2 state `SPEC_ONLY`, gate `CLOSED`, reserved window from `2026-10-12T00:00:00Z`
* stage 4 of the chain above: nothing may be ADOPT_FOR_NEW_EXPERIMENT until a pre-registered rule returns PROMOTE on the reserved forward window

## 6. Lines kept separate

* **R6_P2_QUALITY** — kept separate and not used as evidence: the label does not exist in this repository, so it is an operator-side lane and is neither mapped nor inferred (the WP-4 roadmap recorded the same)
* **RFC049_DISCOVERY2** — its two hypotheses were rejected at the development/validation stage on sign decay, drawdown over the limit and failure to beat the baselines; they are new hypotheses and are not members of the 24-strategy register, so they are neither re-opened nor counted as families
* **M03_M07_MICROSTRUCTURE** — gated behind the forward-history requirements in config/microstructure_preregistration.json; not a family and not scorable until the history exists

## 7. Checks

* [x] every one of the 24 registered cells is classified
* [x] no family is classified ADOPT without a forward PROMOTE
* [x] the plane quoted is the rebuilt one, not a copy
* [x] the low-frequency operator line is kept separate and unmapped
* [x] frequency is reported next to expectancy so the two are not confused
* [x] no frozen criterion, threshold or cost is modified

Nothing was admitted, no threshold moved: admitted 0, thresholds changed 0, live trading `DISABLED`, trades authorized 0.

