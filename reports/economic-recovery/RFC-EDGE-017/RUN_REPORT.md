# WP-EDGE-017F — run report

Issue: <https://github.com/Extr3sao/bot_crypto/issues/10>
Branch: `agent/edge-recovery/WP-EDGE-00-baseline`
Baseline of this round: `5c81aad` (validated against `origin` before touching anything).

Every number below comes from a command in this file executed on this tree. Nothing is
copied from the earlier run report, and the earlier 146/110/67 fills are explicitly
superseded.

## 1. What was executed

| # | command | result |
| --- | --- | --- |
| 1 | `pytest tests/unit/risk/test_edge17_weekly_window.py -q` | **FAIL first** (11 failed, 3 passed): no `weekly_start_ms`, no rollover |
| 2 | same, after ADR-017F-01 | **14 passed** |
| 3 | `pytest tests/unit/research/test_edge17_drawdown.py -q` | **12 passed** (curve arithmetic, `UNKNOWN` paths, old bug as regression) |
| 4 | `pytest tests/unit/research/test_edge17_capture.py -q` | **19 passed** (append-only, pagination, ladder, dedupe, atomicity, single writer) |
| 5 | `edge16_paper_lane.py --cost-mode net --cost-multiplier {1,2,3}` | three real re-runs; see §3 |
| 6 | `edge15_oos_preregistration.py --capture` | **24 rows** (9 → 24), 0 conflicts, 0 missing |
| 7 | `edge17_capture.py` | provenance per bar; 6 at close, 18 recovered, 0 absent |
| 8 | `edge17_reports.py` | regenerated `NET_RISK_REPLAY`, `ECONOMIC_RESULTS`, drawdown, weekly evolution |
| 9 | `edge17_verify.py` | **VERIFIED: 31/31 checks, 14/14 faults** |
| 10 | `edge15_verify.py` | **35/35 VERIFIED** (V34 first failed until the capture was committed) |
| 11 | `pytest tests/unit` | see §6: recorded as PASS/FAIL/BLOCKED |
| 12 | `edge16_verify.py` | **42/44**; V57/V58 classified in §7, not converted to PASS |

## 2. P0.1 — the weekly window

**Defect reproduced first.** `weekly_pnl` was accumulated by `record_trade_result` and reset
by nothing: `reset_daily` deliberately left it alone. The replay reset daily 84 times and
weekly never, so a bad week vetoed every later entry. Written as failing tests before the
fix: 11 of 14 failed.

**Fix (ADR-017F-01).** UTC Monday 00:00 → Monday 00:00, anchored in `weekly_start_ms`,
rolled from the injectable clock in `check_signal`, `record_trade_result` and `reset_daily`,
persisted through `extract_state`/`restore_state`. Backwards clock: no reset. Legacy
snapshot without anchor: keeps its loss but anchors now, so it cannot veto forever.

**Verified cases**: Monday midnight exactly, Sunday accumulation, weekend with no trades
(day boundary observes Monday), three-week gap, restart inside the week, restart in a later
week, legacy snapshot, backwards clock, daily limit untouched, 3.01 % inside a new week
still vetoes.

**Replay evidence**: **12 week boundaries per run**, `weekly_pnl` cleared to 0 at every one,
10 of them with a non-zero week loss before the reset. Weekly vetoes that fired:
**0 at 1×/2×/3×** — the worst week (−120.13 USDT at 2×, 1.2 % of equity) never reaches the
3 % limit. The rule is enforced but not binding on this dataset; it is not inert evidence,
because the unit test pins the exact 3.01 % veto.

Weekly P&L before each reset (1×): −22.05, −14.50, −8.12, −39.89, −4.35, −25.10, +3.76,
−14.64, −33.42, −78.76 USDT. 2× and 3× are in `NET_RISK_REPLAY.runs.*.weekly_risk`.

## 3. P0.2 — regenerated replay (real executions)

| multiplier | fills | net realised (USDT) | drawdown | drawdown USDT | rejections |
| --- | --- | --- | --- | --- | --- |
| 1× | **146** | **−238.770489** | **2.387705 %** | 238.770489 | 3 × consecutive-loss cooldown |
| 2× | **146** | **−425.692312** | **4.256923 %** | 425.692312 | 3 × consecutive-loss cooldown |
| 3× | **121** | **−500.571772** | **5.005718 %** | 500.571772 | 43 × max drawdown, 1 × cooldown |

Frictionless equivalence still holds fill for fill against WP-EDGE-016 (146 identical
fills, prices, quantities, reasons and ids), so the cost model and the gating are the only
differences from the baseline.

The old 110 and 67 were an artefact of the non-resetting weekly veto: 2× and 3× stopped
trading for the rest of the window. They are not comparable and are withdrawn.

## 4. P0.3 — drawdown from a verifiable curve

`EQUITY_CURVE.jsonl` (2 000 mark-to-market points per run) is written by the lane. The
published `drawdown_pct` is now the maximum peak-to-trough fall of that curve, computed by
`trading_bot.research.equity_drawdown`, and it is `UNKNOWN` (never a number) when there are
fewer than two finite marks. `edge17_verify.py` recomputes it without importing the module
and injects two faults: M13 publishes `peak_equity` as a percentage again, M14 claims a
drawdown with no curve. Both are detected.

At 1× the curve never makes a new high after its first mark, so max drawdown equals the
final loss; at 3× the trough (2026-10-05) precedes the last week's additional loss.

## 5. P1 — prospective capture

| quantity | value |
| --- | --- |
| expected closed bars, 2026-10-17T08:00Z..15:00Z | 24 (8 per symbol) |
| observed | 24 |
| missing | **0** |
| received at close (`RECEIVED_AT_CLOSE`) | **6** |
| recovered later (`RECOVERED_LATER`) | **18** |
| first seen before close (integrity failure) | 0 |
| duplicates / conflicts | 0 / 0 |
| evaluated by the lane | 9 |
| proposals / fills on prospective bars | 0 / 0 |
| collector rate | 9 787 B/h (fallback 240 MB/h, overstatement 24 522×) |
| disk guard | `COHERENT`; reserve 2 GB, 1.5×, 64 MiB valve unchanged |

The collector remains append-only with its single-writer lock; the frozen protocol was not
touched. `NO_SIGNAL` means the lane evaluated the bar and proposed nothing, not a quiet
market; `ABSENT` would mean no collector.

## 6. P0.4 — full suite on this tree

Command:

```bash
./.venv/Scripts/python -m pytest tests/unit -q --tb=short -rf -p no:cacheprovider \
  > reports/economic-recovery/RFC-EDGE-017/FULL_UNIT_SUITE.log 2>&1; echo "EXIT=$?"
```

Result: **4070 passed, 14 failed in 1313.64 s (21:53)**, `exit status 1`.

Every failure is named with its owner and its evidence. **None is converted to PASS** and none
belongs to WP-EDGE-017F:

| # | test | state | owner / cause | evidence |
| --- | --- | --- | --- | --- |
| 1 | `test_active_recovery_wp.py::test_state_view_is_deterministic` | **BLOCKED** | WP-8 line: the committed view is stale (`re-run scripts/campaign_state_view.py`); its inputs `evidence/real_decisions/*.jsonl` were already dirty when this session opened | recomputed `51ef35aa…` vs committed `25e35d0b…` |
| 2–4 | `test_cost_barrier_adversarial.py` (3) | **BLOCKED** | cost-barrier / WP-3 economy line: the gate pins audit `023b66ff…` while the committed audit payload is `c6ea3438…` — inconsistent at `HEAD` before any 017F change | `COST_BARRIER_EXPLORER.json` line 10632 `state_sha256 023b66ff…`; `HEAD:ACTIVE_ECONOMIC_AUDIT.json` `payload_sha256 c6ea3438…` |
| 5 | `test_cost_barrier_explorer.py::test_payload_hash_reproduces_and_matches_the_committed_artefact` | **BLOCKED** | same pin drift | same |
| 6–10 | `test_cost_barrier_gate.py` (5) | **BLOCKED** | same pin drift: the gate returns `INTEGRITY_FAILURE` instead of `FULL_REPRODUCTION_PASS` | gate stdout: `data/recovery/ACTIVE_ECONOMIC_AUDIT.json state drift (pin 023b66ffd1213b06…)` |
| 11–12 | `test_recovery_determinism.py` (2, including the clean-checkout rehearsal) | **BLOCKED** | WP-8 line: reproduces from the foreign dirty `evidence/real_decisions/*.jsonl` | `51ef35aa…` vs `25e35d0b…` |
| 13–14 | `test_st6_forward_regime.py` (2) | **BLOCKED** | ST6 line: accumulated forward data now contradicts the test's "a single window cannot complete coverage" assertion | `coverage_complete` is `True`, test line 815 |

**No test was skipped, weakened or renamed to make the suite green.** The audit files that the
gate run rewrote during the suite were restored to `HEAD` (`data/recovery/ACTIVE_ECONOMIC_AUDIT.*`)
because they are not this package's to change; only the report and log produced by this session
remain modified.

## 7. EDGE-016 V57/V58 (reviewed, not hidden)

| check | state | owner / cause | evidence |
| --- | --- | --- | --- |
| V57 artifact hashes | **BLOCKED** | foreign uncommitted edit: `reports/economic-recovery/RFC-EDGE-016/INDEPENDENT_VERIFICATION.json` was already modified when this session opened, and its hash in `EVIDENCE_INDEX.json` no longer matches | `git status` at session start; `edge16_verify.py` V57 message |
| V58 authority line | **BLOCKED (package-caused, frozen evidence)** | EDGE-017 moved `def check_positions_ohlc` from line 398 to **490** and `broker.py`'s sha from `0250fc47…` to `4366809a…`; the EDGE-016 map still records the old pair | `RUNTIME_AUTHORITY_MAP.json` row `ohlc_simulator` |

Neither is repaired by rewriting EDGE-016's frozen evidence: that artifact states it
describes `2536928`, and editing its line/hash would make it describe code it does not
claim. The mechanical regeneration belongs to EDGE-016, and until then both checks are
reported as failures with their exact cause.

## 8. Not run (declared)

- Scheduler creation: requires administrator privileges; not attempted.
- Strategy admission: not forced; `config/strategy_admission.json` untouched.
- Live trading: disabled; no credentials, no orders.
- Multi-engine re-verification (Jesse/VeighNa): not executed.

## 9. Reproduce

```bash
./.venv/Scripts/python -m pytest tests/unit/risk/test_edge17_weekly_window.py -q
./.venv/Scripts/python -m pytest tests/unit/research/test_edge17_drawdown.py -q
./.venv/Scripts/python scripts/edge15_oos_preregistration.py --capture
./.venv/Scripts/python scripts/edge16_paper_lane.py --cost-mode net --cost-multiplier 1 --out reports/economic-recovery/RFC-EDGE-017/scratch/net_1x
./.venv/Scripts/python scripts/edge16_paper_lane.py --cost-mode net --cost-multiplier 2 --out reports/economic-recovery/RFC-EDGE-017/scratch/net_2x
./.venv/Scripts/python scripts/edge16_paper_lane.py --cost-mode net --cost-multiplier 3 --out reports/economic-recovery/RFC-EDGE-017/scratch/net_3x
./.venv/Scripts/python scripts/edge17_capture.py
./.venv/Scripts/python scripts/edge17_reports.py
./.venv/Scripts/python scripts/edge17_verify.py      # 31/31, 14/14
./.venv/Scripts/python scripts/edge15_verify.py      # 35/35 after the capture is committed
```
