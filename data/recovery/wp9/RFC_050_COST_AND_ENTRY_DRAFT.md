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

