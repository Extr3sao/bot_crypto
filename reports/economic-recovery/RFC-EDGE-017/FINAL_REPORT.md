# WP-EDGE-017 — final report (as closed by WP-EDGE-017F)

> This document describes the code at the commit that carries it. It supersedes the
> 13:51Z version, whose replay numbers (146/110/67) were produced by a risk engine whose
> weekly loss accumulator never reset, and whose `drawdown_pct` was a USDT balance.

## 1. Why 017F exists

The EDGE-017 branch was published while the checkpoint claimed it already was: the remote
sat at `2536928` with six commits local-only. That was fixed in the previous session. 017F
closes the defects that survived that publication:

1. **The weekly loss window never rolled over.** `record_trade_result` accumulated
   `weekly_pnl`; `reset_daily` explicitly did not reset it, and nothing else did either. One
   bad week vetoed every later signal for the whole run — including the replay that
   produced 110 and 67 fills.
2. **The published drawdown was not a drawdown.** `edge17_reports.py` wrote
   `drawdown_pct = risk_state_at_end.peak_equity` — `10 000.0`, a balance with no trough.
3. **The economic replay had to be regenerated**, not re-attributed.
4. **The full suite had never been re-run** on the published tree.
5. **Prospective provenance was coarse**: a bar captured five minutes after its close was
   counted the same as one recovered six hours later.

## 2. What was repaired

**A weekly window with a causal clock.** `RiskManager` anchors the window in
`weekly_start_ms` (UTC Monday 00:00 to Monday 00:00), rolls it from the injectable clock in
`check_signal`, `record_trade_result` and `reset_daily`, and carries the anchor through
`extract_state`/`restore_state`, so a restart keeps the current week and drops a stale one.
A clock that moves backwards never resets the loss. A legacy snapshot without an anchor
keeps its loss but anchors it to the restore week, so it cannot veto forever. The replay
emits `WEEK_BOUNDARY / RISK_RESET_WEEKLY` with `weekly_pnl_before_reset`. No limit, reserve
or weekend flag changed (ADR-017F-01 in `tasks/decisions.md`).

**Drawdown from a curve.** The lane writes `EQUITY_CURVE.jsonl`, one mark-to-market point
per bar timestamp. `trading_bot.research.equity_drawdown` computes the peak-to-trough fall
and returns `UNKNOWN` when fewer than two finite marks exist. `edge17_reports.py` derives
the published value from that file; `edge17_verify.py` re-implements the calculation
without importing the module and injects the old `peak_equity`-as-percentage value as a
fault (M13/M14).

**The replay was re-executed** at 1×, 2× and 3× from this code, with the same historical
data and the same policy, through `edge16_paper_lane.py --cost-mode net --cost-multiplier
{1,2,3}`.

**Provenance per bar.** Every ladder row now carries `capture_class`:
`RECEIVED_AT_CLOSE` (first ledger record within `[close, close + 1 h)`),
`RECOVERED_LATER` (at or after `close + 1 h`), or `ABSENT`. `FIRST_SEEN_BEFORE_CLOSE` is
counted separately as an integrity failure.

## 3. The numbers (regenerated, not carried over)

| quantity | 017 (old) | 017F (this report) |
| --- | --- | --- |
| fills at 1× | 146 | **146** |
| fills at 2× | 110 | **146** |
| fills at 3× | 67 | **121** |
| net realised at 1× | −238.7705 USDT | **−238.7705 USDT** |
| net realised at 2× | −293.0325 USDT | **−425.6923 USDT** |
| net realised at 3× | −294.0563 USDT | **−500.5718 USDT** |
| drawdown at 1× | `10 000.0` (a level) | **2.3877 %** (238.7705 USDT) |
| drawdown at 2× | `10 000.0` | **4.2569 %** (425.6923 USDT) |
| drawdown at 3× | `10 000.0` | **5.0057 %** (500.5718 USDT) |
| weekly resets in the replay | 0 | **12 per run** |
| fill rejections at 1×/2× | — | 3 × `consecutive_loss_cooldown` |
| fill rejections at 3× | — | 43 × `max_drawdown`, 1 × `consecutive_loss_cooldown` |

The 2×/3× differences are the point: the old numbers were produced after the never-resetting
weekly accumulator had tripped, so the book stopped trading for the rest of the run. With
the window rolling, 2× keeps all 146 fills and 3× loses 25 to the *(total)* drawdown rule,
not to a phantom weekly veto.

**Weekly risk evolution at 1×** (`weekly_pnl` immediately before each Monday reset):

| week starting (UTC) | weekly P&L before reset (USDT) |
| --- | --- |
| 2026-08-10 | −22.05 |
| 2026-08-17 | −14.50 |
| 2026-08-24 | −8.12 |
| 2026-08-31 | −39.89 |
| 2026-09-07 | −4.35 |
| 2026-09-14 | −25.10 |
| 2026-09-21 | +3.76 |
| 2026-09-28 | −14.64 |
| 2026-10-05 | −33.42 |
| 2026-10-12 | −78.76 |

The worst single week at 1× is −78.76 USDT (0.79 % of equity), at 2× −120.13, at 3×
−97.19: no week reaches the 3 % (≈288 USDT) weekly limit, so the weekly rule is **enforced
but not binding on this dataset** (`weekly_blocks_total = 0` in all three runs). That is a
measurement, not an absence of the rule: the 14 weekly-window tests exercise the veto,
including the exact 3.01 % case.

At 1× the equity curve never makes a new high after its first mark, so the max drawdown
equals the total net loss (2.3877 %). At 3× the trough is reached on 2026-10-05, before the
last week's further loss, which is why its drawdown (5.0057 %) and its final loss (5.01 %)
coincide only in magnitude.

## 4. Prospective capture

The collector was run again against the venue after the fix; the slice grew from 9 to 24
rows without touching the frozen protocol:

| quantity | value |
| --- | --- |
| expected closed bars (window 2026-10-17T08:00Z .. 15:00Z) | 8 per symbol, 24 total |
| observed | 24 |
| missing (`ABSENT`) | **0** |
| received at close | **6** (2 per symbol) |
| recovered later | **18** (6 per symbol) |
| duplicates / conflicts | 0 / 0 |
| ledger entries | 4 (append-only, independent of the slice) |
| measured collector rate | 9 787 B/h (fallback overstatement 24 522×) |
| disk guard | `COHERENT`, reserve 2 GB, 1.5×, 64 MiB valve — unchanged |

`evaluated = 9`, `bars_with_a_proposal = 0`, `bars_with_a_fill = 0`: no strategy is
admitted, so `NO_SIGNAL` here means "the lane evaluated the bar and proposed nothing", not
"a quiet market". Missing bars are `MISSING_NO_COLLECTOR`, never a quiet market.

## 5. Verification

- `scripts/edge17_verify.py`: **VERIFIED, 31/31 checks, 14/14 injected faults**. New this
  round: three drawdown checks (one per multiplier) recomputed from the curves without
  importing the metric module, plus M13 (publish `peak_equity` as a percentage) and M14
  (claim a drawdown with no curve).
- `tests/unit/risk/test_edge17_weekly_window.py`: **14 passed** — Monday boundary, Sunday
  accumulation, weekend without trades, multi-week gap, restart inside/outside the week,
  legacy snapshot, backwards clock, daily-limit isolation.
- `tests/unit/research/test_edge17_drawdown.py`: **12 passed** — including the regression
  that a peak level cannot be a percentage and four `UNKNOWN` paths.
- `tests/unit/research/test_edge17_capture.py`: **19 passed** (append-only, pagination,
  coverage ladder, dedupe, atomicity, single-writer lock).
- `scripts/edge17_prefix_replay.py`: **9/9** capture defects reproduced from `2536928` and
  from four re-introduced mutants plus a no-lock variant.
- Full `pytest tests/unit` on this tree: see section 6 (recorded, with owner, PASS/FAIL/
  BLOCKED — no failure is converted into a pass).

## 6. What is still blocked

1. **No scheduler.** A Windows scheduled task needs administrator privileges; not
   attempted. Consecutive live capture therefore depends on someone running the collector.
2. **No admitted strategy.** `config/strategy_admission.json` is untouched; the runtime
   paper path has nothing to execute. The experimental lane bypasses admission by design.
3. **Spread and latency blocks are `NOT_MEASURED` in a bar replay** — they are enforced on
   the runtime entrypoint, where the scanner measures them.
4. **The host volume is ~99 % full** (≈4.2 GB free). The collector needs ~9.8 KB/h, so disk
   is no longer the blocker, but the volume is not healthy.
5. Full-suite failures owned by other lines are recorded in `RUN_REPORT.md` as `BLOCKED`
   with their owner; they are not attributed to this package and not counted as passing.

## 7. Verdict

`CAPTURE_APPEND_ONLY_VERIFIED` · `COVERAGE_IDENTITY_HOLDS` · `PROVENANCE_PER_BAR` ·
`NET_RISK_PARITY_VERIFIED` · `WEEKLY_WINDOW_ROLLS` (ADR-017F-01) ·
`DRAWDOWN_MEASURED_FROM_CURVE` · `DEFENSIVE_BLOCKS_ENFORCED` ·
`ECONOMIC_RESULTS_NET_NEGATIVE` · `PROSPECTIVE_CAPTURE_MANUAL_NOT_SCHEDULED` ·
`INDEPENDENT_VERIFIED` · `LIVE_TRADING_DISABLED`.

The economic conclusion does not improve with the corrected accounting: the book loses more
money once every cost is charged inside the book and the weekly veto stops masking the
strategy behind a single permanent block. `NO_RESTATED_EDGE_SURVIVES`.
