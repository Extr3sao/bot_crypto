# WP-9E — ACTIVE economic blockers

> generated `2026-10-11T20:53:15Z` · OFFLINE READ-ONLY AUDIT — nothing run, no threshold changed, no campaign started

## 1. Which kind of obstacle is which

24 registered strategies, 24 primary classification(s) (a strategy has one reason it failed, and any number of things present alongside it).

| bucket | primary | flagged | what it means |
| --- | ---: | ---: | --- |
| `NO_ECONOMIC_ADVANTAGE` | **17** | 0 | no gross alpha to begin with, before any cost is applied |
| `EXECUTION_COSTS` | **7** | 17 | a gross edge that does not survive the round trip |
| `INSUFFICIENT_DATA` | **0** | 24 | evidence the audit could not measure (no published drawdown, no observed spread) or a sample below the pre-registered bar |
| `ROBUSTNESS` | **0** | 18 | sign or magnitude that does not survive a regime change or a parameter neighbourhood |
| `RUNTIME_FAILURE` | **0** | 20 | a defect in the pipeline itself rather than in the hypothesis |
| `GOVERNANCE` | **0** | 24 | nothing may be promoted: the ledger admits no strategy and paper promotion is NOT_AUTHORIZED |

primary = the reason the strategy failed; flagged = present and not what decided it. A category that flags everything and decides nothing describes the pipeline rather than the strategies.

## 2. The arithmetic that decides it

* frozen round-trip cost plane: **23.354 bps** at 200 USDT (stress 35.030 bps), reproduced from the model: True
* best measured gross edge: **8.912 bps** (`volatility@30m`) — a shortfall of **14.442 bps** per trip
* cells with positive gross at zero cost: **7**; cells clearing the plane: **0**; net-positive cells: **0**
* the objective: 3 operations/day = 1095 round trips/year = **25572 bps** = **255.7 % of stake** per year at the frozen plane
* assessment: `NOT_ACHIEVABLE_FROM_CURRENT_REGISTERED_FAMILIES` — the objective is not a quota: no operation may be generated to satisfy a frequency target

| cell | timeframe | ledger status | gross (0 cost) | net | gap to plane | clears? |
| --- | --- | --- | ---: | ---: | ---: | --- |
| `volatility@30m` | 30m | COST_KILLED | 8.912 | — | 14.442 | no |
| `volatility@1h` | 1h | COST_KILLED | 6.276 | — | 17.078 | no |
| `mean_reversion@30m` | 30m | COST_KILLED | 5.472 | — | 17.882 | no |
| `mean_reversion@15m` | 15m | COST_KILLED | 2.714 | — | 20.640 | no |
| `trend@30m` | 30m | COST_KILLED | 2.206 | — | 21.148 | no |
| `mean_reversion@5m` | 5m | COST_KILLED | 1.485 | — | 21.868 | no |
| `trend@15m` | 15m | COST_KILLED | 1.284 | — | 22.070 | no |
| `breakout@5m` | 5m | NO_GROSS_EDGE | -0.084 | — | 23.438 | no |
| `breakout@1h` | 1h | NO_GROSS_EDGE | -0.222 | — | 23.576 | no |
| `ema_crossover@30m` | 30m | NO_GROSS_EDGE | -0.726 | — | 24.080 | no |
| `ema_crossover@1h` | 1h | NO_GROSS_EDGE | -0.964 | — | 24.318 | no |
| `ema_crossover@15m` | 15m | NO_GROSS_EDGE | -1.122 | — | 24.476 | no |
| `trend@1h` | 1h | NO_GROSS_EDGE | -1.252 | — | 24.606 | no |
| `trend@5m` | 5m | NO_GROSS_EDGE | -1.645 | — | 24.998 | no |
| `breakout@30m` | 30m | NO_GROSS_EDGE | -1.792 | — | 25.146 | no |
| `breakout@15m` | 15m | NO_GROSS_EDGE | -1.822 | — | 25.176 | no |
| `momentum@5m` | 5m | NO_GROSS_EDGE | -1.883 | — | 25.237 | no |
| `mean_reversion@1h` | 1h | NO_GROSS_EDGE | -2.226 | — | 25.580 | no |
| `momentum@1h` | 1h | NO_GROSS_EDGE | -2.334 | — | 25.688 | no |
| `momentum@30m` | 30m | NO_GROSS_EDGE | -2.612 | — | 25.966 | no |
| `momentum@15m` | 15m | NO_GROSS_EDGE | -3.972 | — | 27.326 | no |
| `ema_crossover@5m` | 5m | NO_GROSS_EDGE | -4.561 | — | 27.914 | no |
| `volatility@5m` | 5m | NO_GROSS_EDGE | -4.735 | — | 28.089 | no |
| `volatility@15m` | 15m | NO_GROSS_EDGE | -7.064 | — | 30.418 | no |

## 3. The evidence worth buying, in order

**1. EXECUTION_COSTS** — E-1: a measured round trip on the forward book with a frozen order policy, reported as a distribution rather than a model
   * cost: uses data already captured (the book is being collected); no new data window
   * unblocks: the ranking of every registered family at once
**2. NO_ECONOMIC_ADVANTAGE** — E-2: a forward-drift entry screen at 30m, where the best gross edge lives (volatility@30m 8.912 bps)
   * cost: one pre-registered candidate against the existing partitions
   * unblocks: whether any entry-side variant is net-positive at all
**3. INSUFFICIENT_DATA** — a sealed 24 h capture window that survives the disk preflight, then the M-03 / M-07 history their gates demand (WP-9D)
   * cost: 72 h for a three-segment M-03, 7 days for M-07 per the pre-registration
   * unblocks: the microstructure and open-interest hypotheses entirely
**4. RUNTIME_FAILURE** — the routing defect DEF-206, which flags 20 strategies without deciding any of them
   * cost: a code change with contract tests, no new data
   * unblocks: nothing economically on its own, and everything if the map order is why the wrong candidate is ranked first
**5. GOVERNANCE** — an admitted strategy (0 exist) plus explicit operator authorisation for paper promotion (currently NOT_AUTHORIZED)
   * cost: operator decision, not data
   * unblocks: paper trading, and nothing before it

## 4. The independent cost-and-entry RFC

* registry says next free: `048` — **not trusted**: it calls 048 free while 048 and 049 are occupied;
* derived from tree occupancy: **RFC-050**
* does an independent cost-and-entry campaign already exist? ABSENT — no independent cost-and-entry campaign is registered, so preparing one is not duplicating an existing line of work

The draft below is prepared and **not authorised**. It is a plan; running it requires the operator.

---

# RFC-050 — Measured cost plane and entry quality  ·  **DRAFT, NOT AUTHORIZED**

> `STATUS = DRAFT` · `AUTHORIZED = false` · `CAMPAIGN_STARTED = false`
> Prepared by WP-9E. Nothing in this file has been run, and nothing here authorises a run.
> The operator authorises campaigns; an audit only prepares one.

Number derived from tree occupancy (43, 44, 46, 47, 48, 49) and
not from the registry's stale `next_free_number_above_046 = 048`.

## Why this campaign, and not a strategy search

The registered families are exhausted as a source of net edge, and the arithmetic is not
close:

| quantity | value |
| --- | ---: |
| frozen round-trip cost plane at 200 USDT | **23.354 bps** |
| best measured gross edge in the registry | **8.912 bps** |
| shortfall per trip | **14.442 bps** |
| cells above the plane | **0 of 24** |
| net-positive cells | **0** |

The objective of 3 operations/day is 1095 round trips a
year, which at the frozen plane is **25572 bps**
(255.7 % of stake). the objective is not a quota: no operation may be generated to satisfy a frequency target

## Two stages, in this order

1. **E-1 — measure the cost plane** (a measurement, not a hypothesis). The model's maker path
   is declared `EXECUTION_MODEL_REQUIRED` for want of fill evidence, and the spread between
   the perp and spot scenarios (10 bps) is larger than the best gross edge in the registry.
   Measure the realised fill of a frozen order-placement policy against the mid at decision
   time from the forward book already being captured, and report the cost distribution with
   adverse selection and non-fill rates. **Kill criterion:** if the measured p50 does not fall
   below the best measured gross edge, no strategy in the current families can pass and the
   correct output is to stop, not to look for a cheaper model.
2. **E-2 — entry quality at 30m.** The gross edge peaks at 15-30m, so pre-register a single
   candidate differentiated from a named registered family only by requiring a positive
   direction-adjusted forward-drift estimate on the development partition. It passes only on
   *net* expectancy with a lower confidence bound above zero and a sign that holds across
   DEV and VAL.

## What this campaign may not do

* start before the operator authorises it;
* change a frozen threshold, the cost model, or the admission criteria;
* substitute a synthetic sample for the forward history that M-03 and M-07 are waiting for
  (see WP-9D);
* be reported as a result: this file is a plan.

---

## 5. Governance

* admitted strategies: **0**; paper candidates: []; ledger entries: 24
* `PAPER_PROMOTION = NOT_AUTHORIZED`, `LIVE_TRADING = DISABLED`, `TRADES_AUTHORIZED = 0`
* frozen criteria changed: False
* R6 P2 QUALITY: kept separate and not used as evidence: the label does not exist in this repository, so it is an operator-side lane and is neither mapped nor inferred (WP-4 recorded the same)

## 6. Checks

| check | result |
| --- | --- |
| the ledger's status counts reconcile with the per-strategy records | `PASS` |
| primary and flagged taxonomy roles are not collapsed | `PASS` |
| the cost plane reproduces its frozen value | `PASS` |
| every net-positive cell is counted from the artefact, not asserted | `PASS` |
| no frozen criterion was modified by this audit | `PASS` |
| a cost-and-entry RFC is either found or prepared as a draft that cannot run | `PASS` |

