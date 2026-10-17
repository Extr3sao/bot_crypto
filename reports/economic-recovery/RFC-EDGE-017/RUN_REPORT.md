# WP-EDGE-017 — run report

*agent/edge-recovery/WP-EDGE-00-baseline, generated 2026-10-17T11:10Z. Issue: [#10](https://github.com/Extr3sao/bot_crypto/issues/10).*

Statuses (orthogonal — one passing does not confer another):

- `CAPTURE_APPEND_ONLY_VERIFIED` — **holds**
- `CAPTURE_IDEMPOTENT_RERUN_VERIFIED` — **holds**
- `COVERAGE_IDENTITY_HOLDS` — **holds**
- `COLLECTOR_RATE_MEASURED` — **holds**
- `DISK_GUARD_UNCHANGED` — **holds**
- `NET_COST_BEFORE_RISK_VERIFIED` — **holds**
- `NET_RISK_PARITY_VERIFIED` — **holds**
- `DEFENSIVE_BLOCKS_ENFORCED` — **holds**
- `WEEKEND_POLICY_CHANGED` — does not hold
- `RISK_LIMITS_CHANGED` — does not hold
- `LIVE_TRADING_ENABLED` — does not hold
- `PROSPECTIVE_CAPTURE_SCHEDULED` — does not hold
- `CLEAN_CLONE_REHEARSAL_RUN` — does not hold (not attempted; not counted as passing)
- `INDEPENDENT_VERIFIED` — **holds** (27/27, 11/11 injected faults detected)
- `FALSE_SUCCESS` — **0**

## Headline

The four runtime defects the issue names are closed, each with a test that reproduces
the failure and an artifact that measures the fix:

| defect | before | after |
| --- | --- | --- |
| the collector truncated the holdout on every run | `_write_slice` opened the slice with `w`; one unpaginated page | append-only merge, atomic `os.replace`, resumable `since`, paginated, closed-bar only |
| coverage could never count more than one bar per symbol | `{symbol: last_timestamp}`, dedupe compared a dict's keys with their own set | one ladder row per `(symbol, hour)`, `expected = observed + missing` per symbol |
| risk decided on gross, cost was booked afterwards | 146 fills at −53.38 gross / −239.75 restated net | the book pays −238.77 net and RiskManager is marked to it before every decision |
| the four defensive blocks were declared, not read | no runtime reader for spread, ATR, latency, weekend | fail-closed evaluator on the canonical paper path, policy untouched |

## A — capture: append-only, resumable, idempotent

`src/trading_bot/research/oos_capture.py` + `scripts/edge15_oos_preregistration.py`.

| evidence | value |
| --- | --- |
| slice before the first fixed capture | 3 rows, 1 per symbol, sha `e246b396…a120040` |
| first fixed capture (resumable from the newest held bar) | 9 rows, **+6**, 0 conflicts, 0 duplicates |
| two re-runs afterwards | **0 added, 0 lost, byte-identical sha `983944ba…d34a6b66`** (the third asked for nothing: the next hour had not closed) |
| pagination | one page per symbol, short page confirmed with a second request (`retried_short_pages=1`) |
| independent ledger | `RFC-EDGE-015/scratch/OOS_CAPTURE_LEDGER.jsonl`, 3 entries, every slice key recorded |
| current-hour bar | excluded by `is_closed`; 0 partial bars admitted |

Regression tests: `tests/unit/research/test_edge17_capture.py` (15) — repeated capture,
2500-bar pagination, truncated retry, stalled page, page-limit truncation, multi-bar
coverage, missing-hour classification, duplicate conflicts, partial bar, failed
`os.replace` leaving the old bytes, corrupt-slice raise.

## B — storage: the guard was pricing a different collector

| quantity | measured |
| --- | ---: |
| slice bytes / rows | 1 255 B / 9 |
| bytes per bar | 139.4 |
| rate (3 symbols, hourly) | 418.3 B/h |
| overhead (ledger lines + manifest rewrite) | 9 158.0 B/h |
| effective | **9 576.3 B/h** |
| declared fallback it replaced | 240 000 000 B/h |
| overstatement factor | **25 061.8x** |
| guard state, 24 h at 1.5x, 64 MiB valve, 2 GB reserve, 4.67 GB free | **COHERENT** |

The guard was not touched: same stress multiplier, same reserve, same valve, same
`plan_window`. What changed is the input. `CAPTURE_BLOCKED_DISK` was a misdiagnosis:
the 240 MB/h figure belonged to a different capture lane. Disk is no longer the reason
the collector is not scheduled; a manual runbook is (`PROSPECTIVE_COVERAGE.md`).

## C — net risk: the cost is in the book before the decision

`PaperBroker` now takes a per-symbol `cost_schedule` (`BrokerCost`: commission, half
spread, slippage) and every `ClosedTrade` publishes the decomposition

```
pnl = reference_gross_pnl − execution_cost_usdt − entry_commission − exit_commission
```

`RiskManager.mark_equity` assigns the broker's net mark-to-market (it does not add), and
the lane marks it before every `check_signal`, so daily loss, weekly loss, both drawdowns
and sizing all read net equity.

| run | fills | commissions | execution cost | net | rejections |
| --- | ---: | ---: | ---: | ---: | --- |
| WP-EDGE-016 (gross decisions) | 146 | 0 | 0 | −53.3845 (frictionless) | 3 cooldown |
| EDGE-017, 1x net | **146** | 146.000 | 40.334 | **−238.7705** | 3 cooldown |
| EDGE-017, 2x net | **110** | 220.000 | 60.918 | **−293.0325** | 1 cooldown, **55 weekly loss limit** |
| EDGE-017, 3x net | **67** | 201.000 | 54.058 | **−294.0563** | 1 cooldown, **105 weekly loss limit** |

At 1x the fills do not change: −238.77 is a 2.39% drawdown against a 5% limit and the
weekly limit (−292.8) is not reached. At 2x and 3x the weekly loss limit binds and the
risk engine refuses entries it had previously approved — 36 and 79 fills that gross risk
took and net risk does not. That difference is the defect made visible, not a data change.

**Equivalence:** with `--cost-mode frictionless` the repaired engine reproduces the
WP-EDGE-016 ledger fill for fill — 146/146 identical trade ids, prices, quantities and
PnLs. The fix changes what risk sees, not what the machines decide.

## D — defensive blocks

`src/trading_bot/risk/defensive_blocks.py` evaluates all four declared rules, in order,
before `RiskManager.check_signal`:

| rule | input | missing input |
| --- | --- | --- |
| `weekend_trading` | calendar | n/a |
| `excessive_spread_bps` | scanner `spread_bps` | blocks (`spread_unknown`) |
| `extreme_atr_pct` | scanner `atr_pct` | blocks (`atr_unknown`) |
| `high_latency_ms` | decision instant − snapshot instant | blocks (`latency_unknown`) |

Wired at `scripts/start_paper_trading.py:build_cycle_engine` →
`PaperCycleEngine.run_cycle_sync`, with the policy object built by the runtime's own
loader. `config/risk.yaml` is byte-identical (weekend still `false`); `config/runtime.yaml`
still disables live trading. In the replay the ATR rule was evaluated on 201 proposals
(max observed 2.973% against a declared 8%) and the weekend rule refused 52 entries;
spread and latency are declared `NOT_MEASURED_IN_A_BAR_REPLAY` and evaluated on the
runtime entrypoint.

Regression tests: `tests/unit/risk/test_edge17_defensive_blocks.py` (12) and
`tests/unit/paper/test_edge17_net_risk.py` (10).

## The five questions

1. **Consecutive prospective bars captured, validated and evaluated:** 3 per symbol
   (9 total), 2026-10-17T08:00Z–10:00Z, all validated and evaluated by the lane. All
   nine were **backfilled** by the first fixed run (max lag 2.648 h), not observed live at
   their close; the ledger records that. Proposals on them: 0. Fills: 0.
2. **How many are missing and why:** 0 in the frozen window (9 expected, 9 observed).
   The resumable fetch backfilled every closed hour since the freeze. Hours with no run
   in the future are `MISSING_NO_COLLECTOR`.
3. **What paper trades net risk actually allows:** 146 at 1x, 110 at 2x, 67 at 3x, against
   146 under gross gating. The 2x/3x losses are the weekly loss limit firing.
4. **Do broker net, RiskManager equity and reconciliation agree:** yes — per trade, per
   book and per run (`risk_equity_equals_broker_net=true`, `all_trades_reconcile=true` in
   all three runs).
5. **What still blocks continuous prospective paper:** no authorized scheduler; a manual
   collector; no admitted strategy in `config/strategy_admission.json` (the runtime paper
   path therefore has nothing to execute; the experimental lane bypasses admission by
   design); and a host volume at 99% that is no longer the collector's constraint but is
   not healthy either.

## Verification

`scripts/edge17_verify.py` does not import any builder module. It re-derives the guard's
arithmetic, the coverage identity, the trade decomposition, the equity parity and the
block wiring from the published JSON and the source text, then injects 11 faults into
copies (dropped bar, duplicated bar, rewritten digest, a missing hour called quiet,
inflated PnL, zero cost, reversed fill ladder, a huge rate claimed to fit, unwired
blocks, live enabled, broken equivalence). **27/27 checks VERIFIED, 11/11 faults detected.**

Targeted regressions: `tests/unit/paper tests/unit/risk` plus the EDGE-016 causality and
PIT suites → **257 passed**. Full unit suite: **4048 passed, 5 failed in 21:56**
(`FULL_UNIT_SUITE.log`). None of the five belongs to this package: three are the WP-8
audit lane, whose committed audit is stale against `evidence/real_decisions/*.jsonl` —
files another lane had already modified when this session opened and this package never
touched — and two are the ST6 failures WP-EDGE-016 already recorded. A clean worktree of
this commit is used to show the audit is clean there (see `CLEAN_CHECKOUT_REHEARSAL.json`).

## Not run (declared, not counted as passing)

- Clean-clone rehearsal: the host volume has ~4.7 GB free and the rehearsal needs a
  second working tree. Not attempted.
- Multi-engine re-verification (Jesse/VeighNa): not executed in this package.
- Scheduler creation: needs administrator privileges; not authorized, not attempted.

## Limitations

- The nine prospective bars are post-freeze data the protocol never saw, but they were
  not observed live at their close. The honest claim is "backfilled by the fixed
  collector", not "live capture".
- The bar replay has no order book and no data-age clock, so two of the four blocks are
  enforced on the runtime entrypoint and declared unmeasured in the replay.
- A stop still fills at its level, which is optimistic for a gap through it.
- The 2x/3x nets are projections over their own re-run fills; only the 1x net is what the
  book itself realized.
