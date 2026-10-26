# ST-6 — forward cost regime validation

Generated 2026-10-09T04:03:24Z at `9eb1e464cf8b090af222127153e33f6ea6e1e949`.

## Period

Declared for 14 natural days, 6 windows per day maximum, one per declared UTC slot:

`2026-10-08T16:21:20Z` → `2026-10-22T16:21:20Z`.

Slots: `00:00-04:00 UTC`, `04:00-08:00 UTC`, `08:00-12:00 UTC`, `12:00-16:00 UTC`, `16:00-20:00 UTC`, `20:00-24:00 UTC`.

Windows planned 84, observed 4, days covered 2.

## Regimes identified

Sessions: {'asia': 2, 'europe': 0, 'us': 2}. Slots seen: ['00:00-04:00 UTC', '04:00-08:00 UTC', '16:00-20:00 UTC', '20:00-24:00 UTC']. Volatility bands: ['HIGH']. Liquidity bands: ['DEEP', 'THIN']. Day types: ['weekday'].

## Comparison with COST_MODEL_V3

| threshold | value | source |
| --- | --- | --- |
| spread | 1.0 bps | `docs\COST_MODEL_V3.json` |
| impact | 0.25 bps | `docs\COST_MODEL_V3.json` |

Measured spread: median 0.378596 bps, mean 0.42033 bps, extreme 0.918738 bps. Measured 200 USDT impact: extreme 0.713428 bps. Observations above the model: 0 of 48 spread readings and 1 of 96 impact readings.

| asset | observations | median spread | worst spread | worst impact | over model |
| --- | --- | --- | --- | --- | --- |
| BTCUSDT | 12 | 0.001223 | 0.001229 | 0.015344 | 0 |
| ETHUSDT | 12 | 0.040475 | 0.041091 | 0.0 | 0 |
| SOLUSDT | 12 | 0.915542 | 0.918738 | 0.713428 | 0 |
| XRPUSDT | 12 | 0.725483 | 0.737327 | 0.0 | 0 |

Depth available per side, median bid/ask notional at 100 sampled levels: BTCUSDT 1145533.154884 USDT, ETHUSDT 1013313.66693 USDT, SOLUSDT 3649177.471415 USDT, XRPUSDT 1911138.290415 USDT. Median book age when the window closed: 8000.0 ms, extreme 15000.0 ms (observation freshness, not execution latency).

## Drift

ST-6 verdict over 4 window(s): **DRIFT_WIDER_THAN_MODELLED**, components {'spread': 'WITHIN', 'impact': 'DRIFT', 'depth': 'WITHIN'}. Breaches recorded: 1 (1 beyond the boundary multiple, 0 at the boundary).

| asset | kind | value bps | x model | when | context |
| --- | --- | --- | --- | --- | --- |
| SOLUSDT | impact_over_model_buy | 0.713427697 | 2.853711 | 2026-10-08T16:22:15.903079Z | us 16:00-20:00 UTC HIGH |

## Coverage rule

| condition | observed | required | satisfied |
| --- | --- | --- | --- |
| days_covered >= declared minimum | 2 | 10 | no |
| windows_total >= declared minimum | 4 | 42 | no |
| each session >= declared minimum | 0 | 8 | no |
| weekday windows >= declared minimum | 4 | 20 | no |
| weekend windows >= declared minimum | 0 | 4 | no |
| distinct slots >= declared minimum | 4 | 6 | no |
| distinct volatility bands >= declared minimum | 1 | 2 | no |
| every asset present in >= declared fraction of windows | 1.0 | 0.9 | yes |
| rejected fraction <= declared maximum | 0.0 | 0.2 | yes |

Coverage token: **REGIME_COVERAGE_INSUFFICIENT**. the pass/fail rule is the one declared when the period was activated and is not adjusted after seeing a window; the liquidity bands actually observed are reported beside it rather than turned into a condition afterwards.

## Corrections to derived readings

- 2026-10-08T16:34:23Z: book ages, the window reference instant, the slot and the per-window aggregates were re-derived from each raw snapshot's own local_finished_utc; the age had been measured against the instant the process started and came out below zero. Why: a negative observation age is impossible and is a defect, not evidence Raw hashes re-checked: 1; evidence unchanged: True. Fields changed: not recorded for that run; observations changed: not recorded for that run.
- 2026-10-08T16:35:56Z: book ages, the window reference instant, the slot and the per-window aggregates were re-derived from each raw snapshot's own local_finished_utc; the age had been measured against the instant the process started and came out below zero. Why: a negative observation age is impossible and is a defect, not evidence Raw hashes re-checked: 1; evidence unchanged: True. Fields changed: not recorded for that run; observations changed: not recorded for that run.

## Insufficient data and errors

Incomplete windows: 0. Rejected observations: 0 of 48. Evidence failures: 0.

- missing: days_covered >= declared minimum (observed 2, required 10)
- missing: windows_total >= declared minimum (observed 4, required 42)
- missing: each session >= declared minimum (observed 0, required 8)
- missing: weekday windows >= declared minimum (observed 4, required 20)
- missing: weekend windows >= declared minimum (observed 0, required 4)
- missing: distinct slots >= declared minimum (observed 4, required 6)
- missing: distinct volatility bands >= declared minimum (observed 1, required 2)

## Decision

**INSUFFICIENT_REGIME_COVERAGE** — the declared coverage rule is not yet satisfied: the period is open; a drift breach has already been measured and is reported in this artefact rather than hidden behind the open period.

A drift breach has been measured in the observed windows: **True**. When it is true it is reported here and in the breach table below, with the asset and the instant named, while the period is still open; the model is not adjusted and no strategy is touched because of it.

ECO-1: OPEN — the declared coverage rule is not yet satisfied: the period is open; a drift breach has already been measured and is reported in this artefact rather than hidden behind the open period.

ECO-2: UNKNOWN_NOT_RESOLVABLE_OFFLINE.

## Tests and verification

Independent verifier: `scripts/st6_forward_regime_verify.py` → `data/st6/ST6_INDEPENDENT_VERIFICATION.json`. Unit suite: `tests/unit/research/test_st6_forward_regime.py`. FALSE_SUCCESS target 0; recorded 0.

## Standing state

```text
DISCOVERY_CAMPAIGN_FAILED = True
NEXT_CAMPAIGN = NOT_AUTHORIZED
TRADES_AUTHORIZED = 0
LIVE_TRADING = DISABLED
PROFITABILITY_VERIFIED = False
ECO_2 = UNKNOWN_NOT_RESOLVABLE_OFFLINE
```

Orders sent: 0. Credentials used: 0. Observations recorded: 48 (0 rejected and written down as such).

## What this does not say

- It does not certify future or unobserved regimes, only compatibility with the conditions actually observed.
- It does not measure realised slippage, fill quality or maker queue position: those stay `UNKNOWN`.
- It does not license a campaign, a hypothesis, a strategy, capital or live trading.

Storage: 71930 compressed bytes of raw evidence for 725529 uncompressed. Scheduler: none: ST-6 was not scheduled, so this phase adds an idempotent --due command instead of a second scheduler.
