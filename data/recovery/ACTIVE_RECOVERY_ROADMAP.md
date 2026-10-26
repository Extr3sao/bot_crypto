# ACTIVE RECOVERY ROADMAP (WP-4)

> Derived from `data/recovery/ACTIVE_ECONOMIC_AUDIT.json` (WP-3) and
> `data/recovery/CAMPAIGN_STATE_VIEW.json` (WP-2). Every number below is traceable to a
> source artefact; nothing here launches a campaign, and nothing here is authorized.

```text
PROFITABILITY_VERIFIED = FALSE
LIVE_TRADING = DISABLED
TRADES_AUTHORIZED = 0
PAPER_PROMOTION = NOT_AUTHORIZED
NEXT_CAMPAIGN = NOT_AUTHORIZED
FALSE_SUCCESS = 0
```

## 1. What the evidence actually says

Three causes are measured, in this order of importance.

**Cause 1 — the entries have no edge (NO_ALPHA).** Five of the six registered families have a
*negative* gross expectancy before any cost is charged (`docs/STRATEGY_DISCOVERY_V3_RESULTS.json`,
5m zero-cost diagnostics). The independent ARP-001 recomputation goes further and localises the
failure in the entry itself: the direction-adjusted forward return is negative at +1, +3, +6, +12
and +24 bars in every family, and no asset or volatility regime hides a positive cell. An exit
redesign cannot repair a trade that is on the wrong side of the next move at entry.

**Cause 2 — the cost plane is larger than the best available gross edge (EXECUTION_COST).**
The audit re-derives the runtime admission round trip from COST_MODEL_V3 through the class the
runtime uses: **23.353553391 bps** at the 200 USDT stake (fees 20 bps KNOWN + spread 1 bps
ESTIMATED + slippage 2.28 bps ESTIMATED + impact 0.07 bps ESTIMATED), 35.03 bps under the
pre-registered 1.5x stress. The research plane used by STRATEGY-DISCOVERY-V3 was cheaper
(12 bps BASE). Measured against both lines:

| measure | value |
| --- | ---: |
| best gross edge in the whole registry (`volatility@30m`) | **8.912 bps/trade** |
| cells with a positive zero-cost gross edge (of 24) | **7** |
| cells clearing the 12 bps research barrier | **0** |
| cells clearing the 23.353553391 bps admission floor | **0** |
| strategies with a positive net expectancy | **0** |
| strategies admitted for paper | **0** |

At the operator's stated cadence of three operations a day the arithmetic is unforgiving:
1,095 round trips a year at 23.353553391 bps is **25,572 bps — 255.7 % of the stake per year** in
costs alone. Frequency cannot be the fix, because frequency *multiplies* the per-trip cost
requirement. The same cadence at a USD-M perpetual venue is 13.79 bps instead of 23.79 bps
(`docs/COST_MODEL_V3.md` §5), which is the single largest available reduction in the whole model.

**Cause 3 — the evidence base and the runtime are incomplete (DATA_QUALITY / IMPLEMENTATION_DEFECT).**
These do not cause the losses; they block promotion and they hide information:

* no per-timeframe admission verdict exists (criteria c1..c9 were applied at 5m only) — all 24
  cells carry `max_drawdown = null` and no observed spread, so `missing_metrics` is non-empty for
  every strategy (DEF-ACT-02);
* the ledger's own `edge_evidence.sample_trades` is `0` for the 18 non-5m entries while the primary
  artefact publishes real counts for every one of them (DEF-ACT-01);
* the legacy entrypoint `scripts/start_paper_trading.py` precomputes only ema_fast/ema_slow/rsi/atr,
  so the five families that read other keys generate no signal there (DEF-206); the canonical
  entrypoint composes the registry map instead, and its per-family indicator supply is *not*
  established by this audit — an open question, not a claim;
* one published gross edge is internally inconsistent at the source (`breakout@5m`: −0.11 bps
  published vs −0.084 bps implied by the same artefact's gross_usd and trades), registered as
  DEF-ACT-03 with a 0.05 bps materiality bound rather than smoothed away.

## 2. What is *not* the problem

Stated because it narrows the search space:

* **Data and PIT.** The corpus is integrity-clean (84/84 files, 0 duplicates, 0 gaps, 0 OHLC
  inconsistencies) and the campaigns report 0 PIT violations. This is an edge failure, not an
  infrastructure failure.
* **The paper lane.** 337 cycles, 0 runtime failures, 0 risk vetoes, 0 duplicate decisions, 0
  shadow trades, state unchanged — and `NO_TRADE_STRATEGIC` every cycle is the *correct* output of
  0 admitted strategies. A healthy lane with nothing to execute is not a lost opportunity.
* **The risk plane.** RFC-048V recertified the futures risk engine with 41/41 economic integrity
  checks and 0 false approvals after the fixes. Capital protection is not the constraint on
  getting to paper; admission is.

## 3. Candidate experiments (evidence-derived, none authorized)

Each candidate is a **new hypothesis with a new id, a new budget and its own freeze**. None of them
re-tunes, re-opens or re-labels a closed candidate: the RFC-049 hypotheses (stablecoin and net-liquidity
growth) stay closed, and the six registered families stay rejected unless a genuinely different
mechanism is proposed under a new id.

### E-1 — Measured cost plane (measurement, not a strategy) — **first, because it binds everything**

* **Hypothesis.** The achievable round-trip cost for this account at its real size and order types is
  materially below the 23.353553391 bps taker/taker model, and the difference is large enough to
  change which strategies are viable.
* **Why the evidence supports it.** The gap between the USD-M perp scenario (13.79 bps) and the spot
  standard scenario (23.79 bps) is 10 bps — larger than the entire best gross edge in the registry
  (8.912 bps). Maker legs, fee tiers and venue choice are modelled, never measured: the model
  declares its own maker path `EXECUTION_MODEL_REQUIRED` for lack of `FillEvidence`.
* **Falsifiable rule.** On the forward book data the campaign already collects, measure the realised
  fill price of a pre-declared order-placement policy (post-only entry, IOC exit) against the mid at
  decision time, and report the cost distribution (p50/p90) with the adverse-selection and
  non-fill rates. Refuted if the measured p50 round trip is not below 20 bps net of non-fills.
* **Preregistration.** Order types, venue, size ladder, decision cadence, the fill-probability
  estimator and the reporting statistics are frozen before the first measurement.
* **Kill criterion.** If the measured cost plane does not fall below the best measured gross edge,
  no strategy in the current families can pass and the correct output is to stop — not to search for
  a cheaper model.

### E-2 — Entry quality: a forward-drift screen at 30m — the strongest *signal* lead

* **Hypothesis.** At the 30m horizon a family whose entry is conditional on a *positive* measured
  forward drift is positively expectant gross of costs. (The observed peak of gross edge is 15m–30m:
  `volatility@30m` +8.912, `mean_reversion@30m` +5.472, `trend@30m` +2.206 bps; at 1h the sign flips
  for two of them.)
* **Why the evidence supports it.** ARP-001 measured forward expectancy per family at five horizons,
  which is a *testable property of the entry*, not a parameter to fit; and the 30m horizon both
  raises the gross edge and lowers turnover.
* **Falsifiable rule.** Pre-register one candidate that (a) enters only when the entry's own
  direction-adjusted forward-drift estimate is positive on the development partition, and (b) is
  otherwise identical to a named registered family. It passes only if the *net* expectancy after the
  frozen cost plane is positive, with an LCB above zero, a stable sign across DEV/VAL, and no
  reliance on a single window.
* **Preregistration.** Rule, universe (BTC/ETH/SOL), periods, partitions, cost plane (E-1's measured
  plane if adopted), thresholds and the multiple-testing correction are frozen before any run.
* **Kill criterion.** Negative net at DEV/VAL closes it at that stage, per the existing policy.

### E-3 — Funding/basis carry at the perpetual — the only mechanism that does not need per-trade alpha

* **Hypothesis.** A carry position (perp vs spot, or funding-aware directional exposure) held for
  hours to days is net-positive after costs, because the edge accrues from the funding/basis term
  rather than from predicting the next move.
* **Why the evidence supports it.** COST_MODEL_V3 already models `funding_carry` and the long-hold
  case, and the collector records funding samples; per-trade cost is amortised over a much longer
  hold, so the binding constraint (cost per trip) shrinks with holding time instead of growing.
* **Blocking prerequisite.** History. The forward collector reached 4.16 h of a 24 h target
  (17.33 % coverage) and stopped on its own disk budget; 488 funding samples exist, which is not a
  DEV/VAL/OOS corpus. E-3 cannot be tested until the collection gate passes.
* **Falsifiable rule.** Net carry return per unit of risk after the measured cost plane and the 1.5x
  stress must be positive in every partition, with the sign stable across the funding-regime cells.
* **Kill criterion.** If carry does not exceed the cost plane net of the funding sign changes, it
  closes like any other candidate — the mechanism being "structural" is not an exemption.

### E-4 — Microstructure family on the forward book (second-order, needs M-03/M-07)

* **Hypothesis.** Order-flow imbalance / book-pressure features from the forward book data carry a
  per-trade edge larger than the taker cost at a cadence of minutes.
* **Why the evidence supports it.** This is the only family in the repository whose frequency can
  plausibly reach several operations a day, and it is the only one whose information set is not
  already consumed (the RFC-049 and strategy-discovery families used daily/weekly price and
  flow series).
* **Blocking prerequisite.** The M-03/M-07 gates (≥24 h of clean depth and OI at ≥95 % coverage,
  ≥3 non-overlapping segments). Currently `NOT_READY`.
* **Kill criterion.** As above, and additionally: a microstructure candidate that only works with
  taker execution at ≥3 ops/day must clear the *measured* taker plane, not a modelled one.

### E-5 — Exit asymmetry for `trend` (lowest priority, evidence is explicitly unsupportive)

* **Hypothesis.** `trend` wins often (55.4 %) but small (payoff 0.58); an asymmetric exit could turn
  its gross expectancy positive.
* **Why it is lowest.** ARP-001 states the entry drift is −2.26 bps, so a better exit would be
  harvesting a negative-drift stream: the evidence does not support the hypothesis, it only shows
  where an asymmetry could be tested. Recorded for completeness, not recommended as a first move.

## 4. Sequencing and gates

| step | entry criterion | exit criterion |
| --- | --- | --- |
| 0. Registry reconciliation | none | `docs/roadmap/RFC_REGISTRY.json` agrees with the tree; next free number recomputed (view derives **050**) |
| 1. E-1 measured cost plane | operator authorization (ADR) | cost distribution reported with knowledge classes; adoption decision recorded |
| 2. E-2 entry-quality candidate | E-1 adopted or explicitly waived in writing | net-positive LCB at DEV/VAL, sign-stable, no single-window dependence; otherwise closed at the stage it fails |
| 3. Runtime enablement (router N-select, portfolio policy, DEF-206 fix) | **≥1 admitted strategy exists** | enablement verified without changing any admission threshold |
| 4. Paper gate | admission + a clean 24 h window (M-03/M-07) | paper run with real decisions and independent verification |
| 5. E-3 / E-4 | collection gate passed | as above |

Non-negotiable rules carried forward: builder ≠ verifier; no promotion of a statistically
insufficient sample (`INSUFFICIENT_OOS_SAMPLE` is never PASS and never REJECT on power); no threshold
or cost change after seeing results; a failed candidate is closed, never re-tuned; a new campaign
brings its own freeze timestamp and its own sealed window.

## 5. The independent line: `R6 P2 QUALITY`

The operator's label `R6 P2 QUALITY` **has no artefact in this repository** (`git grep` for
`R6 P2 QUALITY`, `R6_P2`, `P2 QUALITY` over tracked files returns no match; the only `R6` token in
the codebase is an unrelated robustness check, `R6_param_non_fragility`, in
`scripts/sprint033_run.py`). It is therefore recorded here as an **operator-defined independent
lane**, and this roadmap does not merge it into the 3-ops/day objective, does not infer its rules,
and does not claim its strategy is the RFC-049 liquidity line. To become testable it needs the same
treatment as everything else: an id, a preregistered rule from a citable source, a universe, a cost
plane, a partition policy and its own freeze. Until then it stays independent and unchanged.

## 6. Authorization state

Nothing in this document is authorized. `NEXT_CAMPAIGN = NOT_AUTHORIZED` (ADR-0026 consumed the
ADR-0025 offline scope), `PAPER_PROMOTION = NOT_AUTHORIZED` and the sealed OOS window of RFC-049
Discovery 2 is `CANCELLED_NOT_OPENED` and may not be claimed by any new campaign. The first step of
any recovery is a governance act by the operator — an ADR that names the campaign, its budget, its
partitions and its stop rules — after which the registry must be reconciled with the tree (step 0)
before a number is used.

```text
PROFITABILITY_VERIFIED = FALSE
```
