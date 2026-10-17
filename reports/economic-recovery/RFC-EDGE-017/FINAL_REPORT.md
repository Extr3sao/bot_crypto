# WP-EDGE-017 — final report

## What was wrong

WP-EDGE-016 certified its own runtime while four operational defects sat outside the
checks it ran:

1. **The holdout collector was destructive.** `_write_slice` opened the slice with `w`,
   so every `--capture` truncated it and rewrote it with one unpaginated page anchored at
   the freeze instant. A growing history would eventually stall while silently destroying
   what earlier runs had captured. The runbook called it "append-only/idempotent"; the
   code did the opposite.
2. **The coverage counter could not count.** `scripts/edge16_capture.py` reduced the slice
   to `{symbol: last_timestamp}`, so `captured_bars_per_symbol` was always 0 or 1, and its
   duplicate test compared a dict's keys with their own set. `OBSERVED`/`MISSING` and the
   "7/7 monitoring" were therefore unreliable by construction.
3. **Risk decided on gross and cost was booked after the decisions.** The lane ran the
   broker with `commission_bps=0, slippage_bps=0`; `record_trade_result(trade.pnl)` fed a
   frictionless number, and the venue cost was subtracted in a report afterwards. 146
   fills were approved against −53.38 USDT gross while the same fills cost −239.75 USDT
   net. The risk engine had real code paths and no economic parity.
4. **Four declared blocks were never read.** `excessive_spread_bps`,
   `extreme_atr_pct`, `high_latency_ms` and `weekend_trading` existed in
   `config/risk.yaml` and in no runtime branch.

## What was repaired

**Capture is now a contract, not a promise.** `src/trading_bot/research/oos_capture.py`
merges rows by `(symbol, open_ms)`, keeps the first captured value of a bar, records any
conflicting re-fetch instead of dropping it, writes through a temporary sibling with
`os.replace`, resumes from the newest held bar, paginates, confirms a short page with a
second request, and refuses a bar whose close has not happened. An independent
append-only ledger records what every capture attempt saw, so coverage can be re-derived
without trusting the file the collector writes.

**Coverage is one row per `(symbol, hour)`**, with `expected = observed + missing` checked
per symbol and in total. Missing hours are `MISSING_NO_COLLECTOR`, never a quiet market.
Each row also records whether it was captured at its close or backfilled later.

**The book pays before risk decides.** `PaperBroker` accepts a per-symbol `BrokerCost`
(commission, half spread, slippage) and every `ClosedTrade` carries the exact
decomposition `pnl = reference_gross − execution_cost − entry_commission −
exit_commission`. `RiskManager.mark_equity` assigns the broker's net mark-to-market and
the lane marks it before every `check_signal`, so daily loss, weekly loss, both drawdowns
and the sizing all read net equity. `record_trade_result` now documents that its input
must be net.

**The declared blocks are evaluated, fail closed.** `risk/defensive_blocks.py` runs the
four rules in order; a condition that was not measured blocks (`spread_unknown`,
`atr_unknown`, `latency_unknown`), and the weekend rule reads the calendar rather than
the caller. It is wired on the canonical paper path (`start_paper_trading` →
`PaperCycleEngine.run_cycle_sync`) from the runtime's own policy object.

## What the numbers say

| quantity | result |
| --- | --- |
| capture, first fixed run | 3 → 9 rows (+6), 0 conflicts |
| capture, immediate re-run | 0 added, 0 lost, byte-identical |
| coverage in the frozen window | 9 expected, 9 observed, 9 evaluated, **0 missing** |
| longest consecutive evaluated run | 3 h per symbol (08:00Z–10:00Z, 2026-10-17) |
| all nine bars | **backfilled** by the fixed collector, max lag 2.648 h |
| measured collector cost | 9 576.3 B/h ≈ 0.0096 MB/h |
| the fallback it replaced | 240 MB/h — overstated by **25 061.8x** |
| guard decision | **COHERENT** for 24 h, its reserves and stress untouched |
| net book at 1x | 146 fills, −238.7705 USDT (commissions 146.00 + execution 40.334) |
| net book at 2x | 110 fills, −293.0325 USDT; **55 entries refused by the weekly loss limit** |
| net book at 3x | 67 fills, −294.0563 USDT; **105 entries refused by the weekly loss limit** |
| gross-gated baseline | 146 fills, −53.3845 frictionless / −239.7503 restated |
| equivalence with costs off | 146/146 fills identical to WP-EDGE-016 |

At the central cost the fills do not change: −238.77 is a 2.39% drawdown against a 5%
limit, and the weekly limit (−292.8) is not reached. Under the adverse multipliers the
weekly limit binds, and the engine refuses entries gross risk had approved — 36 fills at
2x and 79 at 3x. That is the defect made visible: not a different dataset, the same data
and the same policy with the cost where it belongs.

**Verdicts:** `CAPTURE_APPEND_ONLY_VERIFIED`, `COVERAGE_IDENTITY_HOLDS`,
`NET_RISK_PARITY_VERIFIED`, `DEFENSIVE_BLOCKS_ENFORCED`, `ECONOMIC_RESULTS_NET_NEGATIVE
(NO_RESTATED_EDGE_SURVIVES)`, `PROSPECTIVE_CAPTURE_MANUAL_NOT_SCHEDULED`,
`INDEPENDENT_VERIFIED`.

## What is still true

- **The collector is not scheduled.** The guard no longer blocks it — that was a
  misdiagnosis produced by pricing this writer with another lane's 240 MB/h — but a
  Windows scheduled task needs administrator privileges, and a GitHub cron cannot reach a
  local holdout. Every hour nobody runs the manual command is `MISSING_NO_COLLECTOR`.
- **No strategy is admitted.** `config/strategy_admission.json` admits nothing for paper
  execution, so the runtime path has nothing to trade; the experimental lane bypasses
  admission by design and says so.
- **Nine prospective bars is not evidence.** They were post-freeze data the protocol never
  saw, and they were backfilled rather than observed live. No proposal fired on them, so
  there is still zero prospective trading evidence.
- **The host volume is 99% full.** The collector costs ~9.6 KB/h, but the volume is not
  healthy and this package did not reclaim anything.

## What was not run

The clean-clone rehearsal (needs a second working tree on a volume with ~4.7 GB free), the
multi-engine Jesse/VeighNa re-verification, and the scheduler creation. None of them is
reported as passing.

## Limitations

- A stop still fills at its level: optimistic for a gap through it. No execution latency is
  modelled in the bar replay.
- The replay has no order book and no data-age clock, so the spread and latency blocks are
  enforced on the runtime entrypoint and declared `NOT_MEASURED_IN_A_BAR_REPLAY`.
- The 2x/3x nets belong to their own re-runs; only the 1x net is what the book realized.
- Reference gross is computed at the costed quantity, so it differs from the frictionless
  baseline's gross by ~0.95 USDT at 1x; the net difference is 0.98 USDT and both are
  explained by the smaller position the spread buys.
