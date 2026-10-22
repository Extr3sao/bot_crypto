# WP-EDGE-14R — final report

*2026-10-16T21:20:55Z, `ee3922e9f8e8`. All figures are reproducible from the artifacts in this directory;
the verification that re-derives them is `INDEPENDENT_VERIFICATION.json`.*

## The five answers

### 1. Why are we not executing paper trades?

Because the committed admission ledger admits nothing, and it is the last gate before
sizing. Over 879 replay cycles the canonical path built
1758 symbol-contexts and the router was invoked
1758 times; every invocation returned
`NO_TRADE:no_strategy_passed_gates`. No signal was produced, so nothing reached risk and
nothing reached the broker.

That is not the same as "the path is broken": with one family placed in a declared sandbox
ledger, the same path produced 394 orders and
347 closed fills, ending at
9787.46 from 10000.
The second cause is ordinary: the broker refused
1134 of the
risk-accepted decisions with no fill.

### 2. Which corrections make the path executable without breaking the gates?

Three, all present in this package and none of them a loosened limit:

- **a strategy has to be admitted on evidence** — the ledger's own rule (a committed
  research artifact with positive measured gross edge under the cost model). Nothing here
  invents one, and the sandbox arm exists only to prove the downstream path works;
- **the ledger has to record every stage** — the CAP-004 real-decision path writes no
  intent, router or broker record, so its middle is unobservable. This package's arm
  records all eight stages, which is what made the stop localisable to the router;
- **capacity has to be there** — 1823182848 bytes were
  recovered from regenerable caches and scratch, which cleared the
  `NO_NEW_DECISION_DISK_CRITICAL` refusals without touching the guardian's thresholds or
  deleting evidence.

### 3. Which external frameworks were really executed?

All three, in their own environments outside the checkout:

| engine | outcome | trades | matched | count gap | matched residual (bps) | verdict |
| --- | --- | ---: | ---: | ---: | ---: | --- |
| `freqtrade` | EXECUTED | 44 | 44 | 0 | 0.010569 | AGREE_WITHIN_TOLERANCE |
| `jesse` | EXECUTED | 44 | 44 | 0 | 7.021359 | DIVERGENT |
| `vnpy_ctastrategy` | EXECUTED | 42 | 42 | 2 | 0.0 | AGREE_ON_MATCHED_TRADES_WITH_DECLARED_EXTRA |

Jesse needed four real fixes before it would run (project bootstrap, candle row order —
its layout is `[timestamp, open, close, high, low, volume]`, not OHLC — the fact that
**3.3.5 has no `should_exit` hook**, and two funding artefacts: one route per run, and a
fee reserve on entry sizing). The exact failures, dependencies and causes of the earlier
blocked attempt are preserved in `EXTERNAL_ENGINE_JESSE_ATTEMPT_BLOCKED.json`.

### 4. Which strategies show a positive net return with sufficient evidence?

**None.** The frozen rule loses on every engine:

| measurement | value |
| --- | ---: |
| trades on the closed window | 44 (this project), 44 (freqtrade), 44 (jesse), 42 (veighna) |
| net, this project's simulator | -1070.105581 bps (equity x0.89216878) over 41.5833 days |
| trades per day | 1.0581 — the ACTIVE target is 3 |
| zero-trade days | 18 of 41.5833 |
| net at 0 bps per side | -190.105581 bps |
| net at 20 bps per side | -1950.105581 bps |
| break-even fees | -2.160291 bps per side (gross is negative, so no fee rescues it) |
| expectancy per trade | -24.320581 bps; profit factor 0.674905 |
| buy and hold, same window | BTC/USDT 3.02%, ETH/USDT 0.30% |

Every arm's decision in `ECONOMIC_COMPARISON.csv` is REJECT (or DEFER for the runtime's
current no-trade state). The prospective holdout is `OOS_ACCRUING` with
8 captured bars and has not been scored, so it
supports no answer yet.

### 5. What exactly is missing to move forward?

1. **an admitted strategy** with a measured positive gross edge that survives the cost
   model — the one input that is not produced here on purpose;
2. **accrued prospective bars**: the holdout needs at least
   200 closed trades per strategy before it can accept or reject
   anything; it has one hour of bars so far;
3. **a ledger at the CAP-004 path's middle**, so that path's zeros stop being weak;
4. **the open recorder defect** below.

## Open items

- none

The recorder defect this package originally reported is closed:
`LEDGER_OPEN_CLOSE_RECONCILED` — the PAPER_REPLAY sandbox arm records 348 opened fills, 347 closed fills and 1 position still open when the replay ended.
How: an opening is identified by symbol, instant and execution price rather than by a timestamp two openings can share, and every close is drained from the broker's own closed-trades ledger, so the closes the engine performs inside its own cycle are recorded too.

## What this package does not claim

- it does not claim the paper path has an edge, only that it runs;
- it does not present the replay as prospective paper;
- it does not convert an absent ledger into a measured zero;
- it does not enable live trading, hold credentials, use leverage or change a risk limit.
