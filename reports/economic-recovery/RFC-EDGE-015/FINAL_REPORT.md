# WP-EDGE-015 — final report

*2026-10-17T07:40Z against `a6943c4`. Every figure is reproducible from the artifacts in this
directory; the verification that re-derives them is `INDEPENDENT_VERIFICATION.json` (32/32, verdict
`VERIFIED`), and it shares no code with the builder.*

## The short answer

**`NO_ECONOMIC_EDGE_FOUND`.** No family survives its own costs with enough trades to be adopted.
That is the finding, not the failure: four hypotheses were measured under a per-venue cost model
that never prices a trade at zero cost, one of them is a genuine but cost-fragile structure worth
watching, one was rejected for being carried by five trades out of 171, and the maker hypothesis is
declared untestable rather than approximated. Nothing is promoted, no limit was touched, and the
prospective slice that would let any of this be confirmed is frozen, committed, and accruing.

## 1. The defects that were repaired

**The holdout could not show its own order.** 14R recorded `order_check:
"preregistration_frozen_at_utc < captured_at_utc: False"` — two second-resolution timestamps taken
in the same run. A preregistration written in the same breath as its capture is a description, not a
commitment. The protocol is now frozen by one commit and captured by a later process, and the
ordering is checkable three independent ways: the nanosecond instants, the committed blob the
working file still hashes to (`cea0be8934…`, LF-normalised), and the commit time
(`b4ff588`, 07:15:28Z → 07:20:21Z). Meanwhile the 14R slice and the consumed corpora are kept as
**descriptive** evidence and labelled as such.

**The verifier was the builder.** `edge14r_verify.py` called back into
`research.economic_recovery.engine_parity`, the module that produced the artifacts it judged. The
import is gone rather than narrowed: the rule, the indicator, the two fee conventions and the
compounding equity path are re-implemented in the verifier from their published specification, and
a structural check fails if a builder import ever returns. `BUILDER != VERIFIER` is now a property
of the code, not a claim about it.

**Identification was inferred from a wall-clock field.** Openings were identified from outside by
`(symbol, opened_at, entry_price)`; two fills in one clock tick could share it, and a deduplicating
reconciler then dropped real positions. The broker now mints its own `position_id`, order ids and
`trade_id` per book (which is why the experimental lane uses one book per symbol), continues the
sequence across `restore()`, and refuses to reuse an identifier after recovery.

**One number could not say which quantity moved.** `accounting_snapshot()` keeps realised PnL,
unrealised PnL, cash and mark-to-market equity apart, carries the accrued entry commission as its
own term instead of hiding it, and returns four identity checks rather than a single figure.

**Two parity divergences were quantified but not explained.** Both are now re-derived from the
published rows. Jesse's 7.021359 bps is exactly three terms — 6.985523 bps of *price* on the two
trades open at the window's end (open vs close of the final bar), +0.095587 bps of our own
fee-convention gap, −0.059751 bps because the engine's realised charge is 19.940259 rather than the
declared 20 — with a decomposition error of 0.0 and every other trade inside the 1 bps tolerance
that was frozen before the run. VeighNa's two extra trades are the rule's last two entries, still
open when the window ends.

## 2. What the alpha search actually found

The corpora are consumed, so nothing here is an out-of-sample claim; the numbers are what a family
would have earned *after* a per-venue cost model that charges fee, half spread, slippage and impact
on both legs.

| family | held-out trades | gross/trade | net @1× | net @2× | decision |
| --- | ---: | ---: | ---: | ---: | --- |
| `mean_reversion_vol_liq` | 811 | +54.84 bps | +21 075 bps | −2 326 bps | **EXPERIMENT** (cost-fragile) |
| `vol_regime_breakout` | 171 | +223.79 bps | +33 367 bps | +28 465 bps | **REJECT** (outlier-driven) |
| `trend_pullback` | 895 | −37.04 bps | −58 809 bps | −84 464 bps | **REJECT** |
| `cross_sectional_rotation` | 355 | −35.63 bps | −11 465 bps | −16 605 bps | **REJECT** |
| `maker_only_spread_capture` | — | — | — | — | **DEFER** (no fill model) |

The two decisive readings:

* `vol_regime_breakout` looks spectacular and is not. Its top five trades are **1.31× its entire
  gross** and its median trade loses money: five lucky rides out of 171. That is a lottery ticket,
  not an expectation a position can be sized on, so it is rejected on the concentration number
  rather than on its mean.
* `mean_reversion_vol_liq` is the only family whose gross per trade repeats across the two segments
  (+54.84 and +54.76) — where it was not chosen, which is weak evidence for structure rather than
  overfit — and it is *one cost-doubling from zero*: +26 bps/trade at 1× cost, −2.87 bps/trade at
  2×. It survives only until costs double, so it is carried as an experiment, not as a candidate.

The arithmetic that keeps killing these hypotheses: the alt tiers cost 25–29 bps a round trip at the
200 USDT stake, so a family must earn ~30 bps gross per trade at the central cost and ~58 bps at the
adverse one. Almost nothing in this corpus does both.

## 3. The prospective lane

A separate lane drives the **real** `PaperBroker` and the **real** risk policy over new bars:
210 cycles, 182 `NO_TRADE`, 14 fills, 14 protective exits, realised −12.81 USDT, accounting
identities holding in all three books, and the authoritative admission ledger's sha256 unchanged
before and after. Every cycle carries `EXPERIMENTAL_PROSPECTIVE_PAPER`; rejected families are
recorded as refusals with their reason, not silently dropped; no exchange order was sent.

The lane's own economic result is a risk-policy observation: the default stops (0.5 % / 0.75 %) are
far tighter than the horizon the surviving family needs, so every position was stopped out before
its thesis could play out. Altering those limits is the risk-manager's call under its own RFC.

## 4. What is not claimed

* **No out-of-sample economic inference.** The corpora are consumed, and the prospective slice has
  **0 bars**: the first hourly bar to open after the freeze had not closed when the capture ran (it
  fetched what existed and reported zero rather than inventing a window).
* **No adoption, and no ADOPT verdict is possible yet.** `ADOPT` requires every threshold on data
  the selection never touched; the only such data has not accrued.
* **The ATR-percentile gate is a 50-bucket approximation** (declared in the artifact). That is why
  the published per-trade evidence exists: the verifier re-derives each decision against the bars
  that existed when it was taken instead of demanding an identical trade list from a second
  approximation.
* **The disk guard still reports `INSUFFICIENT_FREE_SPACE`** (5.9 GiB free). It was not relaxed.
* The external engines (Freqtrade, VeighNa, Jesse) were **not re-run**; their published rows were
  re-derived instead.

## 5. The next hypothesis

The tail says the binding constraint is the cost model, not the signal, so the next thing to look
for is explicit: **a family whose gross expectancy per trade exceeds its own tier's round trip by a
margin** — roughly ≥ 24 bps for a tier-1 pair and ≥ 29 bps for a thin alt at the central cost, with
the adverse multiplier budgeted for. Two concrete directions the evidence points at, both testable
with what exists:

1. **Fewer, larger trades in the tier-1 pairs.** The families that lost did so through frequency:
   the tier-1 round trip is 23.35 bps and BTC/ETH were not where the search spent its trades.
2. **A maker arm, once — and only once — a fill model exists.** The brief's own condition: a
   recorded order-book or trade-print source plus a queue model validated against real fills. Until
   that exists, the maker family stays `DEFER_NO_FILL_MODEL` rather than being approximated into a
   favourable backtest.

The lane stays in place, the protocol stays frozen, and the prospective slice is the only place
either direction can be confirmed.
