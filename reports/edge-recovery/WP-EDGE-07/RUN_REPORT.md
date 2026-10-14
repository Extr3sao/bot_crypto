# WP-EDGE-07 — RUN_REPORT

*One reading at `2026-10-14T09:42:28Z` on `DESKTOP-4CHO695`, from branch `agent/edge-recovery/WP-EDGE-00-baseline` at `ebdafc32a34a`. Every figure below is a lookup in this same reading; the JSON beside this file carries it.*

## 1. The volume, and what this work package removed from it

- Free: **3.083 GiB** of 237.5 GiB — `ABOVE_CRITICAL_BELOW_HEALTHY` (the lane refuses below 2.0 GiB and the heavy publication waits below 5.0 GiB).
- Reclaim history: **8 invocations**, 4 dry run(s) and **4 applied**; **2,261,922,757 bytes (2.11 GiB)** removed in total.
- The latest applied sweep is `2026-10-14T08:50:23Z`; it moved the volume from 2,824,138,752 bytes (2.63 GiB) to 3,955,908,608 bytes (3.68 GiB) free.
- Every removal is recorded and none was faked: **193 paths** recorded as removed, **0** of them still on disk.
- Named but *not* deleted: **12 neighbour entries** and 4 kept path(s) — the volume's other writers are the volume owner's to clean.

## 2. The lane

- Runs recorded: 98, of which 51 observed.
- Last observing tick: `2026-10-14T09:30Z` (started 2026-10-14T09:40:57Z, 3 new bars).
- Ticks refused for disk, over the whole log: 41 (the last one on `2026-10-14T08:30Z`).
- Scheduled observing ticks **after the reclaim** (`2026-10-14T08:50:23Z`): 4

  - `2026-10-14T08:45Z` started 2026-10-14T08:55:56Z: 18 new bars, 7 market request(s)
  - `2026-10-14T09:00Z` started 2026-10-14T09:10:58Z: 6 new bars, 7 market request(s)
  - `2026-10-14T09:15Z` started 2026-10-14T09:25:57Z: 3 new bars, 4 market request(s)
  - `2026-10-14T09:30Z` started 2026-10-14T09:40:57Z: 3 new bars, 4 market request(s)

## 3. Track B — the trend book on a window nobody had read

- Book `edge07_trend_fixed`, run `EDGE07-VALIDATION-20261014T090256Z`; the parameters are the registered bytes (`EDGE07-PREREG-20261014T085354Z`, `2026-10-14T08:53:54Z`): `params_hash` `9ceb20fc7d4500c334e2d58f6ff4cd6d26c6b228c4f8ef93f3c709082e44e8ad` — matches the registration: True.
- The new window: `2026-03-01T00:00:00Z` … `2026-10-14T07:00:00Z` (end exclusive), 1363 4h bars on each of BTC, ETH, SOL, **0 gaps**, minimum required 300 — enough coverage: True; fetched `2026-10-14T08:56:16Z`.
- **Verdict `REJECT`** on the new window: decisive criterion failed on NEW_HOLDOUT: P2, P3, P4, P5, P6, R1, R2. Powered: True.
- Net -140.3041 USDT over 65 trades at BASE — gross -63.0744, fees 64.9246, expectancy -2.1585 USDT/trade, win rate 20.0 %, profit factor 0.671, max drawdown 2.1413 %.
- The registered readings: expectancy 90 % CI [-5.1501, 1.0015] (point -2.1585) USDT/trade, net 90 % CI [-334.7546, 65.097] (point -140.3041) USDT, 1 of 3 time blocks positive, and serial dependence lag-1 0.5073 against a ±0.2481 band (11 runs against 21.8 expected, z -4.2574).
- The comparison arm, same window and costs: the frozen trailing exit earned 61.0046 USDT over 28 trades (largest trade 223.7 % of the net) against the fixed target's -140.3041 USDT over 65 trades. Neither arm clears its own criteria on this window.

### The book on every window it was read on, at BASE

| Window | Read before this work package | Trades | Net (USDT) | Net at 2x fees | Expectancy | Sharpe | PF | DD % | Largest share | Cost bps |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `DEV` | True | 584 | **1056.2895** | 104.2169 | 1.8087 | 0.7219 | 1.1966 | 4.0367 | 7.4 % | 23.8579 |
| `VAL` | True | 136 | **-146.1493** | -281.5418 | -1.0746 | -0.575 | 0.869 | 3.5367 | — | 23.7887 |
| `OOS_CONSULTED` | True | 113 | **230.0174** | 116.674 | 2.0356 | 0.9585 | 1.321 | 1.5329 | 22.2 % | 23.8629 |
| `NEW_HOLDOUT` | False | 65 | **-140.3041** | -205.2287 | -2.1585 | -1.2461 | 0.671 | 2.1413 | — | 23.763 |

*`OOS_CONSULTED` is the window earlier work packages had already read, shown here so the comparison with `NEW_HOLDOUT` is explicit rather than implied; the three cost scenarios, per-asset and per-regime breakdowns live in `validation/VALIDATION.md` §3 and §4.*

| # | Criterion | Passed | Value |
| --- | --- | --- | --- |
| P1 | trades >= 30 | True | `65` |
| P2 | net > 0 at BASE | False | `-140.3041` |
| P3 | expectancy > 0 at BASE | False | `-2.1585` |
| P4 | net > 0 at 2X_FEES | False | `-205.2287` |
| P5 | largest single trade <= 50% of the net | False | `None` |
| P6 | at least one positive regime | False | `0` |
| R1 | net still > 0 with the largest winner removed | False | `-170.085` |
| R2 | net > 0 in at least 2 of 3 time blocks | False | `1` |
| S1 | DEV gross > 0 | True | `1746.0725` |

*The campaign's own frozen gate, re-expressed on this window for comparability, says `REJECT` for the same reasons: oos net -140.30 USDT <= 0 after costs; oos expectancy -2.1585 USDT/trade <= 0; oos has 0 profitable regime(s), fewer than the required 1; oos net turns negative under 2x fees (-205.23 USDT): no cost margin.*

## 4. Track C — the ACTIVE books, and the ceiling they run into

Registered `2026-10-14T09:20:00Z` (`EDGE07-ACTIVE-20261014T091124Z`) at `1h`, multiplicity 2, targeting 3.0 trades/day; the declared wall is **23.790569 bps** round trip.

| Book | DEV trades | Trades/day | Gross/trade (bps) | Net (DEV USDT) | Avg duration | Verdict |
| --- | --- | --- | --- | --- | --- | --- |
| `edge07_active_fade` | 255 | 0.1397 | -15.761 | -503.9857 | 461.65 min | **REJECT_NO_GROSS_EDGE** |
| `edge07_active_thrust` | 338 | 0.1852 | -5.3873 | -492.9215 | 173.61 min | **REJECT_NO_GROSS_EDGE** |

Both verdicts come from the registered screen: `edge07_active_thrust` — the setup loses money before any fee on DEV (-0.2694 USDT/trade over 338 trades), which no cost change can repair; `edge07_active_fade` — the setup loses money before any fee on DEV (-0.788 USDT/trade over 255 trades), which no cost change can repair.
Neither book read the independent window: `holdout_read` is False for both, as the registration required.

The ceiling, measured on the same bars: a book must capture this fraction of the open-to-open move merely to break even on a 23.7906 bps round trip.

| Horizon | Trades/day (universe) | BTC capture needed | ETH capture needed | SOL capture needed |
| --- | --- | --- | --- | --- |
| H = 1 h | 72 | 86 % | 67 % | 58 % |
| H = 2 h | 36 | 60 % | 47 % | 40 % |
| H = 4 h | 18 | 43 % | 33 % | 28 % |
| H = 8 h | 9 | 30 % | 23 % | 20 % |
| H = 24 h | 3 | 16 % | 12 % | 11 % |

The mission's own target — 3 trades a day — is reachable at: H = 1 h (72 trades/day across the universe, 52.2 % of moves below the cost); H = 2 h (36 trades/day across the universe, 39.8 % of moves below the cost); H = 4 h (18 trades/day across the universe, 29.7 % of moves below the cost); H = 8 h (9 trades/day across the universe, 20.6 % of moves below the cost); H = 24 h (3 trades/day across the universe, 10.7 % of moves below the cost).

## 5. Tests and verification

| What | Result | Command |
| --- | --- | --- |
| this work package's own suites | exit `0` — 26 passed in 2.46s (3.46s) | `C:\Users\GVLLFR0035\Downloads\bot freebuff\.venv\Scripts\python.exe -m pytest -q tests/unit/research/test_edge07_scheduler_evidence.py tests/unit/research/test_edge06_cadence.py tests/unit/research/test_wp9_disk_budget.py` |
| the linter | exit `0` — All checks passed! (0.16s) | `C:\Users\GVLLFR0035\Downloads\bot freebuff\.venv\Scripts\python.exe -m ruff check scripts/edge07_report.py scripts/edge07_verify.py scripts/edge07_validate.py scripts/edge07_active.py scripts/edge07_active_barrier.py scripts/edge07_fetch_holdout.py scripts/edge07_growth_evidence.py scripts/edge07_reclaim.py src/trading_bot/research/edge07 tests/unit/research/test_edge07_scheduler_evidence.py` |
| the formatter | exit `0` — 12 files already formatted (0.15s) | `C:\Users\GVLLFR0035\Downloads\bot freebuff\.venv\Scripts\python.exe -m ruff format --check scripts/edge07_report.py scripts/edge07_verify.py scripts/edge07_validate.py scripts/edge07_active.py scripts/edge07_active_barrier.py scripts/edge07_fetch_holdout.py scripts/edge07_growth_evidence.py scripts/edge07_reclaim.py src/trading_bot/research/edge07 tests/unit/research/test_edge07_scheduler_evidence.py` |
| the type checker | exit `0` — Success: no issues found in 11 source files (0.71s) | `C:\Users\GVLLFR0035\Downloads\bot freebuff\.venv\Scripts\python.exe -m mypy scripts/edge07_report.py scripts/edge07_verify.py scripts/edge07_validate.py scripts/edge07_active.py scripts/edge07_active_barrier.py scripts/edge07_fetch_holdout.py scripts/edge07_growth_evidence.py scripts/edge07_reclaim.py src/trading_bot/research/edge07` |

- Independent verification: **PASS**, 13/13 checks, self-test `PASS` with 14 sabotages and 0 undetected.
- The verifier's own exit status: `0` (`scripts/edge07_verify.py --self-test`).

| # | Claim re-derived | Passed |
| --- | --- | --- |
| A-1 | the volume is above the runtime's 2 GiB critical floor | True |
| A-2 | every path the reclaim recorded as removed is gone, and at least one sweep was applied | True |
| A-3 | at least two real scheduled ticks observed after the reclaim | True |
| A-4 | every scheduled tick after the wiring has a durable receipt, and its ran/not-ran follows the tick's own outcome | True |
| A-5 | every scheduled slot WP-EDGE-06 published is still in the lane's log, in order, never replayed, and its store still holds every series | True |
| B-1 | every holdout shard still hashes to the digest its manifest recorded | True |
| B-2 | the parameters read on the new window are the registered bytes, and the run says so | True |
| B-3 | the runner reproduced every published consulted-window figure it re-derived | True |
| B-4 | the trend verdict follows from its own checks by the registered mapping | True |
| B-5 | nothing was promoted, no order was sent, every reading is hypothetical | True |
| B-6 | the new window begins after the last bar of every frozen corpus | True |
| C-1 | each ACTIVE verdict follows from its own checks, and a screened-out book read no independent window | True |
| C-2 | the published one-hour ceiling for BTC on the new window recomputes from the bars | True |

## 6. Acceptance matrix

| ACC | Requirement | Result | Figures |
| --- | --- | --- | --- |
| ACC-01 | Branch, remote, commits and working tree verified and published | **PASS** | `branch`, `head`, `github.remote_matches_head`, `github.commits_total`, `worktree_dirty_entries_of_this_work_package` |
| ACC-02 | Only this repository's own tool caches were removed, and every removal is recorded | **PASS** | `storage.applied_runs`, `storage.paths_recorded_as_removed`, `storage.paths_that_still_exist` |
| ACC-03 | The volume clears the floor the lane refuses below, and the shortfall to healthy is stated | **PASS** | `volume.free_gib`, `volume.verdict`, `storage.reclaimed_bytes_total` |
| ACC-04 | The volume's other writers are named, and none of their files was deleted | **PASS** | `storage.neighbours_named_not_deleted`, `storage.eligible_entries`, `growth.writers` |
| ACC-05 | A tick that consumed its slot re-runs the integrated reconciliation and carries its receipt | **PASS** | `lane.receipts_total`, `lane.last_receipt`, `lane.last_receipt.reconciliation_artifacts` |
| ACC-06 | Ingestion resumed through real scheduled ticks after the reclaim | **PASS** | `lane.scheduled_observing_ticks_after_the_reclaim`, `lane.runs_observing`, `lane.refusals_for_disk` |
| ACC-07 | The trend parameters are the registered bytes, and the run says so | **PASS** | `validation.params_hash`, `validation.registered_params_hash` |
| ACC-08 | The new window is unread by the frozen corpora, complete, and its coverage declared | **PASS** | `validation.coverage_4h_bars`, `validation.gaps`, `validation.requested_range` |
| ACC-09 | The registered criteria decided the trend verdict, with power | **PASS** | `validation.verdict`, `validation.failed`, `validation.new_window.trades` |
| ACC-10 | The comparison arm is reported from the same window, costs and risk policy | **PASS** | `validation.comparison.trailing_net_usdt`, `validation.comparison.fixed_target_net_usdt` |
| ACC-11 | ACTIVE candidates registered before screening, with the frequency target and multiplicity | **PASS** | `active.registered_at_utc`, `active.multiplicity`, `active.frequency_target_per_day` |
| ACC-12 | The screen decided both ACTIVE books, and neither read the independent window | **PASS** | `active.readings`, `active.holdout_read_by_any_candidate` |
| ACC-13 | The cost barrier is measured on the new window, per asset and per horizon | **PASS** | `barrier.rows`, `barrier.declared_cost_wall_bps` |
| ACC-14 | The frequency target is answered numerically, with the clock that can pay for it named | **PASS** | `barrier.reachable_at`, `barrier.pooled` |
| ACC-15 | Nothing promoted, no order sent, no parameter changed after seeing a result | **PASS** | `promotion`, `order_sent`, `validation.instrument_check_all_equal` |
| ACC-16 | Independent verification passes, with the self-test catching every sabotage | **PASS** | `verification.checks_passed`, `verification.sabotages_detected`, `verification.exit_code` |
| ACC-17 | The owned suites and the linter ran here, with their own exit status | **PASS** | `tests.owned.summary`, `tests.lint.summary`, `tests.format.summary`, `tests.types.summary` |

## 7. Artefacts, with the digest of each

| Artefact | sha256 |
| --- | --- |
| `reports/edge-recovery/WP-EDGE-07/active-research/ACTIVE_RESEARCH.json` | `6d36b816793e61cc64aad6fe5ec5968b…` |
| `reports/edge-recovery/WP-EDGE-07/active-research/ACTIVE_RESEARCH.md` | `68bca38e7759e719956c5a6a49ac88d4…` |
| `reports/edge-recovery/WP-EDGE-07/active-research/ACTIVE_TRADES.csv` | `4403c073e7868e41e81fca668cb3fd9b…` |
| `reports/edge-recovery/WP-EDGE-07/active-research/COST_BARRIER_ACTIVE.json` | `d7fcaee590aa0c7724b2a19786454805…` |
| `reports/edge-recovery/WP-EDGE-07/active-research/COST_BARRIER_ACTIVE.md` | `bbdb6ceccb514a63d7215ad0c348ab49…` |
| `reports/edge-recovery/WP-EDGE-07/active-research/FINDINGS.md` | `8f5cb021d65957eb9a75c5d3446c9ae9…` |
| `reports/edge-recovery/WP-EDGE-07/active-research/PREREGISTRATION.json` | `be680f480ea9de874d3a4b51b8572719…` |
| `reports/edge-recovery/WP-EDGE-07/active-research/PREREGISTRATION.md` | `94043a05d00b4d4a9ed7c267b5497a4d…` |
| `reports/edge-recovery/WP-EDGE-07/GITHUB_STATE.json` | `3bba0bc536437afe2fb98c9269153098…` |
| `reports/edge-recovery/WP-EDGE-07/GROWTH_EVIDENCE.json` | `2f630eff2dddffd7244916edf1cda668…` |
| `reports/edge-recovery/WP-EDGE-07/GROWTH_EVIDENCE.md` | `7150732b73c637323a1008e466d76b32…` |
| `reports/edge-recovery/WP-EDGE-07/INFORME_EJECUTIVO.md` | `58dcede3abfd2819d798dbbc52a4fab8…` |
| `reports/edge-recovery/WP-EDGE-07/PREREGISTRATION.json` | `6ded966cd78257140cc3b3d3f105307c…` |
| `reports/edge-recovery/WP-EDGE-07/PREREGISTRATION.md` | `296bd4e37d8932d0d0cfc2420dbe1a0d…` |
| `reports/edge-recovery/WP-EDGE-07/STORAGE_RECLAIM.json` | `f08f7954eb994a112c2cbe3deb4bbfba…` |
| `reports/edge-recovery/WP-EDGE-07/STORAGE_RECLAIM.md` | `459d31720f6a7ba4738f38d17fa111b7…` |
| `reports/edge-recovery/WP-EDGE-07/STORAGE_RECLAIM_HISTORY.jsonl` | `c82943db50b9323cf7754bb3edc311b0…` |
| `reports/edge-recovery/WP-EDGE-07/validation/VALIDATION.json` | `9a318e917bdf14189c971b08dcb9aa90…` |
| `reports/edge-recovery/WP-EDGE-07/validation/VALIDATION.md` | `89ca9c860cdddfdd23bd07c7aa6b9071…` |
| `reports/edge-recovery/WP-EDGE-07/validation/VALIDATION_TRADES.csv` | `20e0fa0631d8714849b137f737dbe087…` |
| `reports/edge-recovery/WP-EDGE-07/VERIFICATION.json` | `4707ec8dc70fcc9517cd5dbb313bbc91…` |
| `reports/edge-recovery/WP-EDGE-07/VERIFICATION.md` | `324d3823e9e72a32680a16293e049d94…` |

*`promotion: NONE`, `order_sent: False`, `hypothetical: True`. Informe ejecutivo en castellano, renderizado de esta misma lectura: `INFORME_EJECUTIVO.md`.*
