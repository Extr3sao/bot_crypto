# ARC03_FAILED_MEMORY_COLLISION_REVIEW.md

> Read **before** the preregistration was frozen. Purpose: prove ARC-03 is not a failed
> mechanism repackaged under a new name, and record — honestly — where the residual
> collision risk actually lies.
>
> `ARC03_BACKTESTS = 0` · `ARC03_EXECUTIONS = 0` · `ARC03_PERFORMANCE_OBSERVED = false`

Sources: `docs/external-audit-01/FAILED_RESEARCH_MEMORY.md` (Track G register),
`docs/alpha-research-universe-01/04_FAILED_MEMORY_COLLISION_MATRIX.json` (ARU matrix),
`ARC03_MECHANISM_AUTHORITY.md`.

---

## 1. ARU-declared collision class

The ARU fixes `ARC-03: { H1: LOW, H3: LOW, H5: MEDIUM, H6: LOW }`. The ARU kill rule is
*distinct from* the collision class: **"net ≤ 0 or collision with H5"**. The matrix class is
the starting point, not the conclusion — it is re-derived below.

## 2. Structural anti-collision (why ARC-03 is field-disjoint by construction)

| Axis | ARC-03 | Prior hypothesis | Disjoint because |
| --- | --- | --- | --- |
| information family | 5m **base volume** + 5m OHLC | H5: 1h **taker-side** imbalance; H6: open interest; ARC-01: funding; ARC-02: cross-asset | ARC-03 never reads taker fields, OI, funding or another asset |
| cadence | 5m bar, 12-bar hold | H1/H3/H5/H6: 1h (or 48/336-bar) | different decision cadence and horizon |
| direction | **against** the failing push | H5: **with** the aggressive flow | opposite-signed on any shared window |
| conditioning | a 100th-percentile **event** + rejection geometry | H1: a regime **state**; H5: an imbalance **level** | event vs state/level |
| time-of-day | used only to **remove** seasonality from the reference set | #9 traded session time **as** the edge | the opposite use |

## 3. Register-by-register review

| # | Prior failure | Collision with ARC-03 | Reasoning |
| --- | --- | --- | --- |
| 1 | **Legacy momentum/trend, 5m cells** — all cells `NOT_SIGNIFICANT`; **“a 5m-entry hypothesis must clear ≥ 0.12% per-trade cost hurdle by design (fewer, larger-edge trades)”** | **HIGH — the principal collision risk** | This is the single most load-bearing objection to ARC-03 and it is **not** dismissed. ARC-03 *is* a 5m-entry hypothesis. Its defence is not that costs are smaller (10 bps is a *frozen* scenario, not an assumption) but that the rule is conditioned on a **record event**: `v(t)` must exceed the same-slot volume on **all** of 30 prior days *and* the bar must give back more than half its excursion. That is exactly the “fewer, larger-edge trades” shape the lesson demands relative to a generic 5m momentum cell. The gates enforce the lesson rather than assume it away: `G2`/`G3` require positive expectancy *net* of the 10 bps, `G11` requires positivity at 20 bps and non-negativity at 40 bps, and `G1` requires ≥ 120 trades so the result cannot rest on a handful of events. **If ARC-03 fails on the cost hurdle it fails with evidence, not by assumption.** Frequency is a discovery-time unknown and is disclosed as such. |
| 2 | Legacy trend 5m/1h — `INSUFFICIENT` (n < 15) | LOW | ARC-03's frequency is event-driven and its `G1` minimum is 120 trades / 40 per asset, chosen before results. |
| 3 | **Legacy breakout** — FAILED; plain breakout on public OHLCV refuted | LOW | ARC-03 has **no level, no breakout, no channel**. The excursion must be an *abnormal* record, and the entry is *contrarian* to the push. |
| 4 | **Legacy mean-reversion** — FAILED (coarse regimes) | **MEDIUM — repackaging risk** | ARC-03 must not be “generic MR”. It is distinguished by the mandatory participation condition: without `v(t) > max(all 30 same-slot references)` there is no signal. This is not decoration — `PARTICIPATION_CONTROL` exists precisely to measure what the participation component contributes, and if the participation-free variant also passes, ARC-03 is declared `DISCOVERY_FAIL`. |
| 5 | Legacy volatility — `INSUFFICIENT` (data depth) | LOW | Range is used as the *excursion to be given back*, never as a tradable state; no volatility signal is emitted. |
| 6 | volatility_structure — lead PFs collapsed under a deeper window | LOW | ARC-03's window is the full certified common history (2020-09→2026-08), not a shallow sample. |
| 7 | cross_sectional — redundant with momentum | NONE | ARC-03 is single-asset, long/short-symmetric, no ranking. |
| 8 | **carry_funding** — FAILED (PF 1.062, p = 0.283) | **LOW — and structurally closed** | ARC-03 reads **no funding as a signal**. Funding enters only as an execution cashflow leg, and `G3` (ex-funding) removes that leg entirely, so ARC-03 cannot pass on carry. This also closes the exact hole that killed ARC-01. |
| 9 | **session_time / liquidity_flow** — costs dominate; intraday timing inherits the hurdle | LOW but **explicitly addressed** | ARC-03 uses time-of-day **only** to remove seasonality from the reference set. It never trades a session boundary. The cost-hurdle lesson is inherited from #1 and handled there. |
| 10 | **H1 regime-transition** — `DISCOVERY_FAIL`; dominant loss mechanism **`SHORT_ON_SHOCK`** (N=10,058) fading shocks inside a secular uptrend | **MEDIUM–HIGH on the SHORT leg** | ARC-03's SHORT leg is also a fade of an up-push, so this is the second principal risk and is disclosed as such. It differs in kind: H1 faded a **state label** (regime transition) at 1h with ≈6.5 qualifying events/day; ARC-03 requires a 100th-percentile same-slot **record** plus a strict-majority **retracement** on a 5m bar, which is an event, not a state. But the structural point stands: **a secular uptrend is an adverse environment for any short-fade**, and ARC-03 makes no claim to regime immunity. Consequence, frozen ex ante: `G9` requires ≥ 2/3 assets positive, and any single-direction or single-asset survivor of a failed primary is `POST_HOC_LEAD_ONLY`. |
| 11 | **H3 relative-value reversion** — `DISCOVERY_FAIL`; |z| ≥ 2.5 dislocations **continued** more often than they reverted | **MEDIUM** | The lesson is that a stretch alone is not a reversion claim. ARC-03's reversal component is therefore not a stretch: it is a contemporaneous **exhaustion** (close gives back more than half the bar’s own range against the body direction), which is a different mechanism from “extreme z reverts”. If ARC-03 fails the same way, the honest conclusion is that exhaustion geometry does not identify absorption either — recorded, not retried. |
| 12 | **H5 order-flow imbalance** — `DISCOVERY_FAIL`, `TERMINAL`; positive expectancy but `p = 0.1838`, `P(Sharpe>0) = 0.8285`, halves `[1,−1]`, redundancy 0.916 with ROC(24) momentum proxy. Lesson: *“order-flow aggregates are still OHLCV-family information … any successor must use a genuinely new information family, generate enough independent events, and enforce the orthogonality gate BEFORE reading economics”* | **MEDIUM (ARU-declared)** | This is the ARU's own MEDIUM and it is the sharpest methodological challenge: ARC-03's base volume **is** OHLCV-family data. Three responses are frozen rather than argued: (a) ARC-03 is *opposite-signed* to H5 (against the failing push vs with the aggressive flow) and reads a **disjoint field** (base volume vs taker-side volume), so it cannot be a parameter re-roll of H5; (b) `G1` demands ≥ 120 trades against H5's fatal N = 107; (c) the orthogonality gate (daily PnL correlation ≤ 0.5, trade-time Jaccard ≤ 0.5 vs H5) is **frozen with explicit thresholds** and is a terminal FAIL for ARC-03 if it collides. The one lesson ARC-03 deliberately does **not** adopt is “enforce the orthogonality gate before reading economics”: doing so would force an economic observation into the preregistration stage and contaminate it. The frozen resolution is therefore the stronger one — orthogonality is the *immediately following* authorized gate and its failure kills ARC-03. |

## 4. ARC-01 — immutable failed research memory

| Field | Value |
| --- | --- |
| experiment | `ARC01_PRIMARY_DISCOVERY_01` |
| final | `DISCOVERY_FAIL` |
| state | `KILLED_FOR_THIS_HYPOTHESIS_ID` |
| result commit | `70c2849534f2119b84a73238009d13f967398436` |
| reason | positive net expectancy was explained by funding carry; ex-funding price expectancy negative; multiple critical gates failed |
| BTC-positive subcell | `POST_HOC_LEAD_ONLY` — **do not adopt, do not retest as ARC-01** |

ARC-01 is **not** a design source for ARC-03 and may never be retested or retuned under its
`hypothesis_id`. Its only role here is as a negative constraint: ARC-01 died because the
funding leg carried the result, so ARC-03 (a) never reads funding as a signal and (b) carries
a frozen ex-funding gate `G3` that subtracts the funding leg completely.

## 5. Repackaging checks (explicit)

ARC-03 is **not**:

* a price-shape pattern (no Fibonacci levels, no candle names, no breakout level, no
  head-and-shoulders, no support/resistance);
* a regime-state conditioner (no H1-style regime label, no BULL/BEAR filter);
* relative value or cross-sectional (single asset, no pairs, no ranking, no beta);
* carry or funding (no funding input to the signal at all);
* an order-flow continuation (opposite direction, different field, different class of input);
* plain mean reversion (a mandatory abnormal-participation record is required, and the
  `PARTICIPATION_CONTROL` measures its contribution);
* time-of-day seasonality **as a strategy** (time-of-day is used only to **remove**
  seasonality from the reference set, which is its opposite);
* a trailing-z of price (nothing in the signal is a z-score of return);
* a re-parameterisation of any registered hypothesis (no threshold, lookback, holding or
  asset choice is shared with a failed spec).

## 6. Residual risk register (disclosed, not hidden)

| Risk | Severity | Frozen mitigation | Cannot be mitigated at prereg |
| --- | --- | --- | --- |
| 5m cost hurdle (#1) | HIGH | `G2`/`G3` net, `G11` at 20/40 bps, `G1` N ≥ 120 | whether the event frequency actually produces enough large-edge trades |
| secular-uptrend short-fade (#10) | HIGH | `G9` asset stability; `G8` halves/quartiles; single-direction survivors are `POST_HOC_LEAD_ONLY` | no regime immunity is claimed |
| OHLCV-family redundancy with H5 (#12) | MEDIUM | direction/field disjointness + frozen orthogonality gate immediately after discovery | the actual correlation cannot be measured without reading economics |
| MR repackaging (#4) | MEDIUM | mandatory participation condition + `PARTICIPATION_CONTROL` | whether participation actually adds edge |
| stretch ≠ reversion (#11) | MEDIUM | exhaustion is a distinct mechanism from a z-extreme | whether exhaustion identifies absorption |

## 7. Verdict

`COLLISION_REVIEW = PASS` **with two disclosed HIGH residual risks (#1, #10) and three MEDIUM
(#4, #11, #12)**. No prior failed mechanism is repackaged; the ARU-declared H5 collision is
carried as a frozen terminal gate rather than argued away. The residual risks are recorded so
that a future failure is attributed correctly instead of being re-explained after the fact.

`REPACKAGING_DETECTED = false` · `REVIEW_COMPLETE = true`
