# ARC-01 MECHANISM EVIDENCE

**Hypothesis:** `ARC-01-FUNDING-CROWDING-UNWIND-01`
**Checkpoint:** `ARC01-PREREG-001`
**Status:** evidence for the **informational and mechanical content** of the two inputs only.

> **No-edge disclaimer.** Nothing in this document asserts that ARC-01 is profitable, or that
> extreme funding or OI expansion predicts returns in either direction. The cited sources establish
> only (a) what the funding rate mechanically is, (b) what open interest mechanically is, and (c) that
> the two are economically distinct information axes. The direction claim of ARC-01 is a **falsifiable
> hypothesis with a frozen control plan**, not an established result. No source consulted here
> contained an ARC-01-style measured outcome, and no performance quantity was computed for this prereg.

---

## E-1. The funding rate is a periodic cash flow whose sign identifies the paying side

| Field | Value |
| --- | --- |
| Claim | In a perpetual swap, a periodic funding cash flow is exchanged between long and short holders; its sign and size are set by the contract's premium relative to the underlying, so a persistently positive rate means longs are paying shorts to maintain exposure |
| Source | Binance USD-M futures funding-rate documentation (`https://developers.binance.com/docs/derivatives/usds-margined-futures/market-data`); observed directly in the certified funding authority rows (`rate_type`, `funding_interval_hours`, `funding_rate`) |
| Source type | OFFICIAL_EXCHANGE_DOC + DIRECT_DATA_CONTRACT |
| Use in ARC-01 | The **sign** of an extreme funding observation identifies which side of the book is paying to stay positioned, i.e. the crowded side |

## E-2. Peer-reviewed / preprint theory of perpetual funding as a positioning price

| Field | Value |
| --- | --- |
| Claim | Perpetual futures are anchored to spot by a funding mechanism, and the funding rate is the price that equilibriates long and short demand; the rate therefore carries information about the imbalance of positioning rather than about fundamentals |
| Sources | He, Manela, Ross, von Beschwitz, *Fundamentals of Perpetual Futures*, arXiv:2212.06888 (`https://arxiv.org/html/2212.06888v5`) — "the funding rate, which is the cash exchanged between the long and short counterparties"; Ackerer, Hugonnier, Jermann, *Perpetual Futures Pricing* (`https://finance.wharton.upenn.edu/~jermann/AHJ-main-10.pdf`) — periodic payments anchor futures to spot |
| Source type | PEER_REVIEWED / WORKING_PAPER (theory of the mechanism) |
| Use in ARC-01 | Justifies reading funding as a **positioning-imbalance** variable, which is what makes a contrarian unwind hypothesis mechanically coherent |
| Non-use | Neither source is used to justify a threshold, a lookback, a holding period or an expected sign of returns |

## E-3. Open interest is a position *stock*, not a flow

| Field | Value |
| --- | --- |
| Claim | Open interest is the number of outstanding (unsettled) derivative contracts; it changes only when new positions are created or existing positions are closed, which makes it a stock measure of participation, distinct from volume which counts activity |
| Sources | Binance official metrics archive definition of the `sum_open_interest` field (`https://data.binance.vision/`, metrics/daily); CME Group open-interest educational material; Investopedia, *Open Interest* |
| Source type | OFFICIAL_EXCHANGE_DOC + INDUSTRY_REFERENCE |
| Use in ARC-01 | Expansion of the position stock (`oi_change_24h > 0`) is the crowding-confirmation leg; contraction never confirms crowding |
| Non-use | No magnitude floor was invented, precisely because no source supports a specific "large" threshold; the frozen rule is sign-based and unit-free |

## E-4. Funding and open interest are economically distinct axes

| Field | Value |
| --- | --- |
| Claim | The funding rate is a *price of carry* (who pays whom), while open interest is a *quantity of outstanding positions*. The same funding level is economically different when the position stock is expanding (new leveraged exposure being added) versus contracting (positions being closed) |
| Basis | E-1/E-2 (price) + E-3 (quantity); this distinction is also the registered lesion of `FAILED_RESEARCH_MEMORY` #8, where a funding-only (price-of-carry) test failed and the standing lesson recorded was that *any basis hypothesis must add a conditioning variable* |
| Source type | MECHANISM_SYNTHESIS |
| Use in ARC-01 | The conjunction `extreme funding AND OI expanding` is the minimum construction that separates "someone is being paid to hold" from "the crowded side is growing"; the pre-registered OI_CONTROL tests exactly whether that second leg is load-bearing |

## E-5. Crowded leveraged positioning can unwind (the falsifiable part)

| Field | Value |
| --- | --- |
| Claim under test | When one side of a perpetual book is simultaneously (i) paying funding at an extreme rate relative to its own recent history and (ii) increasing its outstanding position stock, that side is exposed to a self-reinforcing unwind: the carry cost and the margin pressure of a leveraged crowd are both larger than for the un-crowded side, and the unwind, if it happens, moves price **against** the crowded side |
| Status | **HYPOTHESIS — NOT ESTABLISHED BY THIS PREREGISTRATION** |
| Source type | EX_ANTE_MECHANISM_CLAIM |
| Falsification instruments | `DIRECTION_CONTROL` (trading with the crowd), `TIMING_CONTROL` (breaking the alignment), `OI_CONTROL` (dropping the crowding leg), `NULL_CONTROL` (direction-less null); see `ARC01_CONTROL_PLAN.json` |
| Known counter-mechanism | A crowded side can also be *correct*: if the crowd is positioned in the direction of a persisting trend, the contrarian trade loses. This is the registered failure mode of `FAILED_RESEARCH_MEMORY` #10 (fading shocks inside a secular trend) and is why the held hypothesis must clear the frozen direction control and the ex-funding-cashflow gate |

## E-6. Explicitly *rejected* mechanism extensions

| Extension | Why rejected before observation |
| --- | --- |
| Price-rejection / failed-continuation candle leg | imports the OHLCV family that `FAILED_RESEARCH_MEMORY` #1/#3/#4/#10/#12 already refute; would convert ARC-01 into a momentum/mean-reversion hybrid, which the ARC-01 mission forbids |
| Magnitude floor on OI expansion | no independent source supports a specific numeric floor; inventing one would be a parameter choice without mechanism justification |
| Percentile-based funding extremeness | adds a second free choice (percentile level) with no mechanism advantage over a robust standardized distance |
| Mark/index/basis series as a third leg | `RESEARCH_ONLY` in the certified inventory; not admitted, therefore forbidden |

## Evidence sufficiency verdict

`ARC01_MECHANISM_EVIDENCE_STATUS = SUFFICIENT_FOR_PREREGISTRATION` — the inputs' mechanical meaning and
their distinctness are established from official exchange documentation and theory literature, and the
directional claim is registered as a falsifiable hypothesis with four frozen controls. No economic
performance was consulted in producing this document (`ARC01_PERFORMANCE_OBSERVED = false`).
