# ARC03_SELECTION_RATIONALE.md

> Every choice below was made **before any economic observation** and is justified from the
> frozen ARU authority, the data cadence, or a statistical/mechanistic argument.
> **No return, PnL, Sharpe, profit factor, expectancy, win rate, threshold search, lookback
> search, holding search or best-asset selection informed any of them.**

`ARC03_BACKTESTS = 0` · `ARC03_EXECUTIONS = 0` · `ARC03_PERFORMANCE_OBSERVED = false`

---

## 1. Why ARC-03, and what the ARU actually fixed

ARC-03 was not invented here. The Alpha Research Universe already contained, before this
worktree existed:

```json
{ "id": "ARC-03", "name": "Participation shock reversal", "data": "5m volume and returns",
  "mechanism": "liquidity-taker overshoot after abnormal participation",
  "who_pays": "urgent liquidity takers", "pit": "PIT_SAFE_EASY", "collision": "MEDIUM with H5",
  "class": "EXPERIMENT" }
```

```json
{ "rank": 3, "id": "ARC-03", "test": "fixed abnormal-volume percentile, one reversal hold, 10bps",
  "kill": "net<=0 or collision with H5" }
```

The ARU therefore fixes: the data family (**5m volume and returns**), the mechanism
(**liquidity-taker overshoot after abnormal participation**), the test shape (**fixed
abnormal-volume percentile, ONE reversal hold**), the cost (**10 bps**), the PIT class, and
the kill rule. What it does **not** fix is the concrete definition of "abnormal participation
percentile", the exhaustion condition, the direction mapping and the horizon — those are the
implementation-level decisions frozen in `ARC03_MECHANISM_AUTHORITY.md` §5 and
`ARC03_SPEC_V1.json`.

**The ARU sentence is not a sufficient specification on its own**, and it was not treated as
one.

## 2. Why the data path is 5m and why the existing authorities were NOT reused

The ARU says *5m volume and returns*. Every committed kline authority in the repository is
**1h or coarser**: the ARC-01 V2 price authority (`price_1h_v2`), the H1/H5 committed dataset
(`docs/external-audit-01/h1-regime-transition-01/dataset`), and the per-trade
`trade_flow` sample (a handful of recent days). The reuse audit
(`ARC03_EXISTING_DATA_REUSE_ASSESSMENT.json`) inspected the **actual frozen bytes/schema** of
each candidate rather than assuming that "Binance klines normally carry these fields".

Verdict: **no reusable authority exists.** 1h bars cannot be disaggregated — volume is not
additive across the missing 5m slots, and the exhaustion geometry (`range`, `body`, wick
fraction) is destroyed. So ARC-03 acquired its own **official** Binance USD-M 5m archives
(`data.binance.vision`, CHECKSUM-verified) rather than splicing a 5m study out of 1h data.
Only `volume` is required beyond OHLC, and OHLC is re-derived from the **same** official 5m
bytes, so no cross-cadence splice exists anywhere in the authority.

## 3. Why the participation shock is a *same-slot* record and not a z-score

| Choice | Rejected alternative | Reason |
| --- | --- | --- |
| Compare against the **same 5m time-of-day slot** on each of the previous 30 days | a rolling 30-bar window | a rolling window is dominated by the intraday activity cycle: crypto volume has a strong deterministic time-of-day shape, so a "high volume" bar is usually just a busy hour. Same-slot comparison removes that seasonal component, so a record is genuinely abnormal. |
| Require **strictly more than all 30** references | a percentile below 100 | this *is* the ARU's "fixed abnormal-volume percentile", read literally as the 100th percentile of a 30-sample reference set. It is an **event**, not a level, and it needs no threshold constant. |
| An **order statistic** | a robust z-score (`median`, `1.4826·MAD`, `|z| ≥ 2`) | a z-score introduces four unforced constants (lookback, minimum N, scale estimator, threshold) and a scale-degeneracy branch. The order-statistic form has **no** scale parameter, so it has no zero-scale branch and no tuning surface. Of the two defensible mechanisms, the one with fewer free parameters was chosen **before** seeing data. |
| **30** days | 10 / 20 / 60 | 30 days is the smallest window that spans a full month of regime and day-of-week variation per slot while remaining short enough that the reference distribution is locally relevant; it is also the ARU-typical reference depth. It is **not** chosen from returns, and the frozen robustness plan probes 10/20/60 without ever moving the primary. |

**Why this identifies transient participation rather than persistent information:**

1. *Same-slot reference* removes the dominant source of spurious "abnormal volume".
2. *Extremeness* (strictly above all 30) makes the signal an event rather than a level.
3. *Rejection is required* — persistent information moves price and **keeps** it, so a bar
   that gives back more than half of its excursion is, by construction, one where the flow
   was absorbed rather than followed.

## 4. Why the excursion must also be a record

The ARU mechanism is an **overshoot**. A participation record alone is compatible with a
quiet, informative bar. Requiring the bar's own `high − low` to be a record against the same
30 same-slot references is the minimal way to state "the price response was disproportionate".
It reuses the reference set already required by the participation condition, so it adds **no
new parameter and no new data**.

## 5. Why exhaustion is "strictly more than half the range"

`(high − close) > range/2` (for an up-push) is the minimal scale-free statement of *"the push
failed to hold"*: more than half the excursion was given back before the bar closed. `0.5` is
the mechanism's own natural boundary — it is the point at which the bar's own close contradicts
its own push — not a tuned threshold. The inequality is **strict**, so a bar that closes exactly
at the midpoint is not a signal (a symmetric bar proves nothing about which side was absorbed).

Direction is then fixed by the mechanism, not chosen: the side that pushed and failed is the
side that pays, so the trade is **contrarian to the rejected push**. This was frozen in
`ARC03_MECHANISM_AUTHORITY.md` §3.1 before any label was constructed.

## 6. Why `PRICE_CONTEXT = NONE`

"Price context" would mean a *state* filter (trend, momentum, volatility, breakout level,
candle morphology, higher-timeframe regime) on top of the definition. None is required by the
mechanism, and each would (a) import the OHLCV-family information that the failed-research
memory already refutes, (b) add an unforced selection surface, and (c) blur the hypothesis
into "generic mean reversion". The OHLC that appears in the definition is **the definition**
(excursion and retracement), so it is explicitly distinguished from an added filter. No filter
was added to make the hypothesis look more selective.

## 7. Why the decision cadence is the 5m bar close

The entire signal (volume record, range record, exhaustion geometry) is a property of exactly
**one** 5m bar. Its close is therefore the first instant at which the signal is knowable.
Evaluating on a coarser grid would skip signal bars without adding information; a finer grid is
impossible because the provider cadence is 5m. `PIT_SAFE_EASY` follows directly: every input is
a completed-bar observation and every reference is at least 24 h older than the decision.

## 8. Why the holding period is exactly 12 bars (60 minutes)

The mechanism is **transient flow absorption**: participants who failed to hold the extreme
become the liquidity the reversion feeds on. The horizon must therefore be (a) long enough for
the reversion to express itself and (b) short enough that the position is not re-labeled as a
trend trade. 12 bars of 5m — one hour — is the coarsest horizon the 5m cadence supports while
remaining unambiguously "the aftermath of the shock". Crucially it is also the horizon at which
the funding question becomes forced rather than incidental: a 60-minute hold **can** straddle a
settlement, so funding accounting had to be frozen explicitly. The choice is derived from the
mechanism and the cadence, **not** from returns; the frozen robustness plan probes 6/24/36 bars
without moving the primary.

Exit is at the **open** of the bar exactly 12 slots later, so the exit price is a single
deterministic, causally-anchored observation with no intrabar assumptions. There is no stop, no
take-profit, no cooldown and no signal-invalidation exit: each of those would be an optimisation
surface.

## 9. Why costs are 10 bps with a frozen sensitivity curve

The ARU fixes `10bps`. The curve `0/10/20/40` is a **diagnostic** that separates *no gross
edge* from *edge killed by costs*, evaluated on the **identical** trade set — cost scenarios may
not regenerate signals. These are frozen evaluation scenarios, not optimisation choices.

## 10. Why funding is a cashflow leg and never a signal

Funding is not among ARC-03's ARU inputs (*5m volume and returns*), and ARC-01's failure was
precisely a carry-only edge. Reusing funding as an ARC-03 signal input would be mechanism
repackaging. But ignoring it entirely would misstate net performance, because a 60-minute hold
straddles a settlement for roughly one entry in eight. The freeze therefore separates the two
roles absolutely: **signal use = NONE**, **execution use = `sum(−direction_sign · funding_rate)`
over certified settlements in `(entry, exit]`**. The `G3` ex-funding gate subtracts that leg, so
a carry-only result cannot pass.

The settlement count is **never assumed** (the ARC-01 prose defect about "9 settlements" is
deliberately not repeated): the accounting iterates the actual certified rows in the window,
honouring SOL's historic 2h/4h schedule.

## 11. Why every statistical convention is written out

ARC-01 passed its independent verification only because its estimator conventions could be
back-solved from a pre-existing repository module and its own accepted H6 precedent. That is a
latent reproducibility debt. ARC-03 removes it: ddof, the annualization factor, the fixed window
span, the bootstrap statistic / resampling unit / index formula / draw count / seed, the
permutation statistic / sidedness / p-value formula / draw count / seed, the split boundaries,
and the concentration attribution (including its zero-denominator behaviour and UTC entry-month
convention) are all **stated in full** in `ARC03_STATISTICAL_GATES.json` and reproducible from
the frozen spec alone. The project module is cited only as corroboration, never as the source.

## 12. Why the H5 collision check is staged after discovery

The ARU kill rule names an H5 collision. Evaluating it requires constructing H5's and ARC-03's
performance series, which is an economic observation. Doing that before the primary discovery
would contaminate the preregistration. The freeze therefore keeps the primary performance-blind
and stages orthogonality immediately afterward (`ARC03_ROBUSTNESS_OOS_01`), where a failure is a
**terminal FAIL for ARC-03** rather than a redesign prompt. Structurally the two hypotheses are
already opposite-signed and field-disjoint.

## 13. Rejected candidates and why nothing else was tried

No alternative threshold, lookback, holding period, direction rule, asset set or price filter was
examined, estimated or compared — explicitly because doing so on real data would be an economic
observation. The design space was narrowed **only** by mechanism and cadence arguments of the
kind recorded above, and the frozen robustness plan is the sole place where alternatives exist
(it is not executed at discovery, and it cannot select a replacement).
