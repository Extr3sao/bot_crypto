# WP-10 E-2 — FORWARD DRIFT ENTRY SCREEN · PRE-REGISTRATION `E2-PREREG-V1`

> `2026-10-11T22:43:38Z` · **E-2 = SPEC_ONLY** · gate **CLOSED** · authorized `False` · campaign started `False`

Nothing in this document has been run on market data, and nothing authorises a run. It exists so that when the gate opens the hypothesis, the partitions, the cost plane and the decision rule are already on the record.

## 1. Why the gate is closed

* RFC-050 registry state: registered = `False` (registry's next free number above 046: `048`)
* RFC-050 draft: exists = `True`, declares DRAFT = `True`, declares AUTHORIZED = false = `True`, campaign started = `False`
* the only campaign authorization on record: next_campaign = `AUTHORIZED`, scope = `OFFLINE_DEV_VAL_ONLY` — the only campaign authorization on record is RFC-049's, scoped to offline development and validation of its own two hypotheses; it does not authorise a new campaign, and E-2 is a new campaign

**Gate verdict: CLOSED** — RFC-050 is not registered, the draft states AUTHORIZED = false and CAMPAIGN_STARTED = false, and no governance instrument authorises a new campaign.

Allowed while closed:
* write the pre-registration
* synthetic contract tests of the decision rule
* viability analysis on already-read periods
* prepare the runtime contract the screen would need

Forbidden while closed:
* run the screen on any window
* open RFC-049's sealed OOS window or reuse its partitions as validation
* authorise paper promotion
* change any frozen threshold, criterion or cost

## 2. Hypothesis (one, falsifiable)

at a 30-minute horizon, requiring a positive direction-adjusted forward-drift estimate at the moment of entry raises the net expectancy of the registered families that already show positive gross edge at that horizon, by enough to clear the frozen round-trip cost plane.

*Falsified when:* the screen reduces the trade count without raising net expectancy, or raises it by less than the plane, or the improvement does not hold in the validation partition — each of which is a published NOT_PROMOTE, not a failed run.

*Why only one candidate:* the brief forbids creating a family to increase candidate count; E-2 is one screen over already-named families, and the pre-registration names them below.

## 3. Universe

* families: `volatility@30m`, `mean_reversion@30m`, `trend@30m` — the only 30m cells with a positive zero-cost gross edge in the rebuilt baseline; the list is taken from the phase-1 rebuild, not from a search
* assets: BTCUSDT, ETHUSDT; timeframe 30m
* runtime contract: Strategy.evaluate(candles, indicators, config) -> Signal | None (src/trading_bot/strategies/protocols.py): the screen is an indicator computed from candles up to and including the decision bar plus a filter on the returned signal. No new runtime layer, no exchange access, no order path

## 4. Reserved windows, and the windows already spent

* E-2 reserves forward data from **2026-10-12T00:00:00Z**
* partition rule: decision instants are split by calendar index — the first 60 % are development, the remainder validation — fixed now, before any observation exists, so no boundary can be moved after seeing a result
* PIT rule: every input of a decision at instant T is available at or before T; the screen uses no candle whose close is after T, and the verification re-derives this with a point-in-time check rather than trusting the implementation

| already spent | period |
| --- | --- |
| research period | `W1-W7 2026-03-01..2026-09-24` |
| excluded paper day | `2026-09-25` |
| RFC-049 sealed OOS (never read, licensed, not to be spent here) | `2026-10-11T00:00:00Z` onward |
| sealed book window measured by E-1 | `paper-lab-continuous-02` 2026-09-29T22:59:18.288000+00:00 → 2026-09-30T03:08:51.773000+00:00 |

## 5. Cost plane the result will be judged against

* `BINANCE_SPOT_STANDARD_TAKER` = **23.353553391 bps** per round trip, stress 1.5x = 35.030330086 bps, frozen
* knowledge mix: exchange_fee_entry=KNOWN, exchange_fee_exit=KNOWN, spread=ESTIMATED, slippage=ESTIMATED, market_impact=ESTIMATED

## 6. Metrics

* net expectancy bps per round trip, net of the frozen plane
* lower 95 % confidence bound of that expectancy
* sign of the net expectancy in the development partition and in the validation partition
* trade count achieved against the pre-registered requirement
* hit rate, payoff and exit mix, for the record
* exposure and trades per day, compared with the 3-operations-per-day objective
* cost under the 1.5x stress envelope, reported beside the headline

## 7. The decision rule, fixed now

`decide(net_bps, dev_size, target_bps) in scripts/wp10_e2_preregistration.py`

PROMOTE requires all of:
* mean net expectancy > 0
* lower 95 % confidence bound > 0
* net expectancy positive in both development and validation
* trade count >= required_trades(sd of the development partition, 23.3536 bps, 80 % power)

* minimum detectable effect: **23.353553391 bps** — an edge smaller than one round trip at the frozen plane cannot be net positive, so a sample that cannot resolve the plane cannot separate success from noise

Kill criteria:
* the screen cannot be expressed without reading an input from the future
* the trade count after screening falls below the requirement within the reserved window, and the window may not be extended to reach it
* the measured cost layer shows the plane is not the binding constraint, in which case the next experiment is the one E-1 names, not this one
* any promotion would require changing a frozen threshold

## 8. Synthetic contract tests (executed)

9/9 passed. synthetic series only: these test the decision rule, not the market. A rule that cannot be shown to reject what it should reject is not pre-registered, it is a hope.

| test | expected | got | passed |
| --- | --- | --- | --- |
| a strong, well-sampled positive edge is promoted | PROMOTE | `PROMOTE` | yes |
| a positive but noisy small sample is not promoted | NOT_PROMOTE, confidence bound fails | `NOT_PROMOTE` | yes |
| a series whose sign flips between partitions is not promoted even with a positive pooled bound | NOT_PROMOTE by the sign rule while the pooled bound is positive | `NOT_PROMOTE` | yes |
| a net-negative series is not promoted | NOT_PROMOTE | `NOT_PROMOTE` | yes |
| a sample below the pre-registered requirement is not promoted | NOT_PROMOTE, sample requirement | `NOT_PROMOTE` | yes |
| the verdict depends on the numbers, not on the order they arrive in | the same verdict and the same mean | `PROMOTE` | yes |
| sorting the series does not change the verdict | same verdict (the rule reads values, not position) | `PROMOTE` | yes |
| negative control: 200 random series never promote with a bound at or below zero | 0 violations | `None` | yes |
| a zero-dispersion series neither crashes nor divides by zero | a verdict with sd 0 | `PROMOTE` | yes |

## 9. What was deliberately not done

* no window was read: the market data for E-2 does not exist yet and none was fabricated
* no candidate was run, no threshold was fitted, no result is reported
* the RFC-049 sealed window was not opened

