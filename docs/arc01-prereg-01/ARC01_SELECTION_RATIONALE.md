# ARC-01 SELECTION RATIONALE

**Hypothesis:** `ARC-01-FUNDING-CROWDING-UNWIND-01` · **Checkpoint:** `ARC01-PREREG-001`
**Rule observed:** every value below was chosen **before any economic observation** and is justified by
mechanism, data cadence, estimator statistics or the registered failure memory. No value was selected
by looking at returns, PnL, Sharpe, profit factor, expectancy, win rate, trade outcomes, per-asset
performance, or by sweeping parameters. `ARC01_BACKTESTS = 0`, `ARC01_EXECUTIONS = 0`,
`ARC01_PERFORMANCE_OBSERVED = false`.

---

## 1. Why ARC-01 exists at all

ARC-01 is rank-2 of the frozen research queue (`docs/alpha-research-universe-01/09_NEXT_RESEARCH_QUEUE.json`,
frozen at `e7f470d`) with class `ADOPT_P0`, proposed mechanism *"leveraged crowded holders unwind after
failed continuation"*, payer *"crowded perpetual traders"*, PIT posture `PIT_SAFE_WITH_CARE`.

Its data prerequisite is now satisfied: the funding authority (`6e42dd9`), plus the reused OI and price
authorities, are all certified `PASS`. ARC-01 is the only queued candidate whose **primary information
axis (funding)** was previously unavailable as full-history authority.

## 2. Decision cadence = funding settlement instants

| Candidate | Rejected because |
| --- | --- |
| 1h calendar grid | funding information only changes every 8h; a 1h grid would emit up to 8 decisions per new funding observation — duplicate decisions that inflate N without adding information |
| 5m calendar grid | OI has 5m resolution but funding information has 8h resolution; 5m decisions are funding-blind |
| **funding settlement instants (chosen)** | the exact set of instants at which the signal's primary input (a new funding observation) enters the information set; provider-native, and it respects the SOL 2022-11 2h/4h schedule without assuming an 8h calendar |

This is the only cadence that is derived from the data's own information structure. It also keeps the
decision count bounded (~1 settlement/8h/asset), which matters for the cost hurdle (below).

## 3. Why the funding transform is a robust z-score over a 60-day trailing window

- **Relative, not absolute.** Funding scale is not comparable across assets or eras (the certified rows
  are quantized 8-decimal rates with asset-specific typical magnitudes). An absolute bps threshold would
  implicitly encode one asset's 2021 regime as the definition of "extreme" for all three assets in all
  years.
- **Robust, not mean/std.** Funding rates are quantized, frequently exactly zero, and heavy-tailed.
  Location `median` and scale `1.4826*MAD` are the standard robust pair for exactly this kind of series,
  and MAD's breakdown point (50%) means a few outsized settlements cannot inflate the scale and mask the
  very extremes being detected. `1.4826` is the normal-consistency constant folded into the scale, so the
  numeric threshold keeps a familiar interpretation.
- **60 days.** Long enough for a stable robust scale (≈180 settlements at 8h cadence, i.e. 2× the frozen
  minimum), short enough that the reference distribution is regime-local rather than spanning years of
  changing market structure. 60d = 15 funding weeks, the natural multi-week holding-regime horizon of
  levered books.
- **Minimum 90 observations** (≈30 days at 8h). Below half the window the robust scale is not trustworthy,
  so the decision fails closed rather than being computed on a thin sample.
- **MAD = 0 → sample stdev → else NO_SIGNAL.** MAD = 0 means >50% of the window shares one value (a pinned
  funding regime). Falling back to the sample stdev over the *same* frozen window preserves the decision
  set in quiet regimes while remaining fully deterministic; if the window is degenerate (stdev = 0) the
  decision is a genuine no-information case and yields `NO_SIGNAL / SCALE_NONPOSITIVE`.
- **Threshold ±2.0, inclusive.** Under a light-tailed reference, |z| ≥ 2 lies outside ~95.4% of the central
  mass. 2.0 was preferred over 2.5/3.0 on an **event-budget** argument only: with ~5.2k settlements per
  asset in the common window and a one-sided ~2.3% tail, the expected candidate pool is tens to hundreds
  per asset *before* the OI conjunction, which is what the frozen minimum-N of 40/asset and 120 pooled
  requires. 2.0 was preferred over 1.5 because the conjunctive OI leg already narrows the set and the
  claim under test is about *extreme* funding. The inequality is inclusive so the boundary behaviour is
  unambiguous and testable.
- **Fallback refused:** no percentile variant, no "best" threshold, no window sweep. Those exist only in
  the frozen robustness neighbourhood, and results there can never redefine the primary.

## 4. Why the OI confirmation is a strict same-time-of-day 24h expansion

- **Stock, not flow.** Crowding is growth of the outstanding position stock, so the signal uses
  `sum_open_interest` (base-asset units) and not the notional field (which double-counts price moves).
- **Same time of day (24h) rather than an arbitrary delta.** The OI dataset is 5m and has intraday
  structure (funding-cycle churn, session effects). Comparing the latest eligible snapshot with the
  latest eligible snapshot ≤ T − 24h cancels the time-of-day component and needs no seasonal model.
- **24h = 3 settlements** at the nominal 8h cadence: the shortest window in which a crowd can be shown to
  be *adding* positions rather than merely holding them, and it stays inside a single trading day so the
  state is comparable across decisions.
- **Sign-based, strict (`> 0`).** No magnitude floor is invented (see E-3: no source supports a specific
  "large" OI change), so the rule cannot smuggle in a tuned constant. Neutral (`== 0`) and contraction
  (`< 0`) both fail closed: contraction is *de-crowding* and belongs to a different, not-yet-registered
  hypothesis.
- **Staleness 600s on both endpoints.** Inherited from the H6 V2 causal contract (`MAX_STALE_SECONDS`), a
  2-bucket tolerance on a 5m series; it converts a data gap into an explicit `NO_SIGNAL` instead of a
  silently stale comparison.

## 5. Why `PRICE_CONTEXT = NONE`

The ARC-01 candidate design left the price-rejection leg explicitly `UNFROZEN_PENDING_PREREG_DESIGN`, so
the prereg must decide it. Decision: **no price feature is used for signal generation.**

1. **Information-family argument.** Every registered failure in `FAILED_RESEARCH_MEMORY` is price/OHLCV
   derived (#1 momentum, #3 breakout, #4 mean reversion, #10 regime labels on 1h OHLCV, #12 order-flow
   aggregates over 1h bars). The standing lesson of #12 is that a successor must use a genuinely new
   information family. Funding + position-stock OI *is* that family; a rejection-candle leg would pull
   ARC-01 back into the refuted family and re-test it under a new name.
2. **Mechanism argument.** The claimed payer is the crowded perpetual holder, and the forcing variables are
   carry cost and leverage, not price geometry. Price appears only where it must: as the execution anchor.
3. **Selectivity discipline.** The mission states filters must not be added to make the hypothesis look
   more selective. A price filter would raise apparent selectivity while adding a fourth parameter class
   (shape, lookback, aggregation) with no independent mechanism justification.
4. **Consequence accepted.** Dropping the price leg removes the "failed continuation" trigger from the ARU
   candidate sketch. That narrowing is registered here, is reflected in `hypothesis_id`
   (`ARC-01-FUNDING-CROWDING-UNWIND-01`), and is reviewed in
   `ARC01_FAILED_MEMORY_COLLISION_REVIEW.md`. If ARC-01 fails, a price-conditioned successor would be a
   **new hypothesis id with a new preregistration**, never a retune of this one.

## 6. Why next-bar-open entry and a 72h unconditional hold

- **Entry anchor = first 1h bar whose open is strictly after the decision instant.** Funding settles at
  exact instants (00:00/08:00/16:00 UTC), so this is normally the immediately following hour. Anchoring on
  the bar OPEN (not close) is the only anchor that is fully inside the post-decision information set and
  requires no intrabar assumption.
- **72h = 3 days = 9 consecutive settlements.** The unwind of a levered crowd is a multi-settlement
  process: the hold must be long enough for the crowded side to be *repeatedly* charged the extreme carry
  and to face repeated margin pressure, which is the mechanism's forcing quantity. One day (3
  settlements) is arguably too short for a regime to discharge; one week would turn the test into an
  unregistered regime bet. Three days is the smallest horizon on which the mechanism has bitten 9 times
  while remaining event-driven. The **crossing of settlements is deliberate**, which is why funding
  cashflow must be accounted for (section 8).
- **Unconditional exit, no stop, no cooldown.** Any stop or early exit is a new parameter with no
  mechanism justification at prereg and would re-introduce the possibility that the measured edge comes
  from risk management rather than the hypothesis. Signal invalidation intra-hold is also rejected: the
  claim is that the *entry condition* identifies a crowded side, not that the condition must persist.
- **Forward-data guard.** Because the hold is 72h, signals in the final 72h of the common window are not
  emitted. This is registered as deliberate truncation, not a defect.

## 7. Why the position policies are what they are

One position per asset, no pyramiding, new same-asset signals skipped rather than queued (a queue would
compute a second, different holding period and silently double N). Assets are independent so the
hypothesis is tested three times on three markets rather than being diluted by a portfolio overlay.
Unit notional per trade with equal-weighted pooling keeps the arithmetic identical across assets and
avoids volatility targeting, which would be a second, unregistered hypothesis.

## 8. Why funding cashflow is applied — and separated from funding information

A 72h hold necessarily crosses ≥9 settlements, so *not* applying funding cashflow would misprice the
strategy by a first-order term. Two distinct uses are frozen:

| Use | Window | Never mixed because |
| --- | --- | --- |
| SIGNAL INFORMATION | settlements with `funding_time <= decision_time` (trailing 60d) | ends at `decision_time < entry_time` |
| EXECUTION CASHFLOW | settlements with `entry_time < funding_time <= exit_time` | starts strictly after entry |

A contrarian short entered on extreme positive funding *receives* funding during the hold, so the
cashflow leg is systematically favourable to the hypothesis. That creates a real risk of "passing by
carry". Therefore `G3_NET_EXPECTANCY_EX_FUNDING > 0` is a **critical gate**: the disclosed mechanism is an
unwind, and if the edge exists only with the carry included, ARC-01 is a carry strategy — the family
already refuted by `FAILED_RESEARCH_MEMORY` #8 — and must fail. Cashflow is charged on the entry notional
(frozen simplification; the deviation is O(1e-4) relative, because settlement sizes are ~1e-4 and nine of
them are applied).

## 9. Why the cost model and the gates are these numbers

- **10 bps round trip total** is the ARU-frozen cost for this candidate class, carried over unchanged from
  the candidate design; it is a *given*, not a choice made here.
- **0/10/20/40 bps** are frozen *evaluation scenarios*, not optimization choices; 20 and 40 additionally
  serve as a critical cost-sensitivity gate, consistent with `FAILED_RESEARCH_MEMORY` #12's lesson that a
  cost-thin edge is not an edge.
- **Minimum N 40/asset, 120 pooled.** The unit of observation is the trade. 40 trades is the smallest
  count on which a per-asset sign is meaningful; 120 pooled gives usable power for the bootstrap CI and
  the permutation test at α = 0.05 while remaining far below the expected event budget of section 3.
  Fixing N before results is what prevents N-chasing later.
- **Sharpe ≥ 0.50 + CI lower bound > 0 + permutation p ≤ 0.05.** A point estimate alone is never
  sufficient (`no_single_metric_sufficient`); an annualized Sharpe floor of 0.5 is the conventional
  minimum for a strategy that must survive real-world friction, and the uncertainty gates ensure the
  outcome is not a small-sample artefact.
- **Halves + quartiles, per asset, concentration limits.** Inherited from the program's standing
  stability discipline (halves/thirds consistency was the explicit lesson of `FAILED_RESEARCH_MEMORY` #8
  and #12). Concentration limits (asset ≤ 60%, month ≤ 40%, single trade ≤ 25%) prevent a single episode
  from manufacturing a PASS.
- **Four controls.** Direction, timing, OI-removal and a deterministic null, because each answers a
  distinct "could this be something else?" question: the wrong sign, a calendar artefact, a missing second
  leg, or a mechanical carry/cost artefact.

## 10. What was deliberately NOT decided here

Robustness parameter cells (section 9 of the robustness plan), regime definitions, orthogonality numbers
against H5/H6/ARC-02 — all frozen as *plans* and explicitly not executed, because executing them before
the primary discovery would create exactly the selection pressure this preregistration exists to prevent.
