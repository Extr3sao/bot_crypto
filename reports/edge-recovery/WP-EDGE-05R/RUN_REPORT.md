# WP-EDGE-05R — recovery and reporting integrity

*One reading, taken at `2026-10-14T06:57:22Z`, snapshot `EDGE05R-READ-20261014T065722Z`, digest `eb91c3e2ad584861…`. Every figure in this report was read at that instant and says so; the Markdown, the JSON and the executive summary are three renderings of that one file.*

## 0. The bottom line

**Work package verdict: `CLOSED_WITH_OPEN_ITEMS`** — every row that could be measured is PASS, with 2 declared not tested: ACC-08, ACC-14.

**Ingest state: `INGEST_RESUMED`.** The lane refused 35 tick(s) on disk and has observed again since: the refusal was real and is over.

The volume is above the critical floor but under the healthy one (4.013 GiB free): the lane ingests and the heavy publication waits. One more consumer on this volume ends the window.

| Question | Answer, as of this reading |
| --- | --- |
| Free space | 4.013 GiB (`ABOVE_CRITICAL_BELOW_HEALTHY`) |
| Lane ticks | 85 total, 41 observed, 35 refused on disk |
| Newest tick | `OBSERVED` at 2026-10-14T06:57:08Z |
| Watchdog readings | 53, newest `WATCH_DEGRADED` / `RESOURCE_PRESSURE` |
| Forward days | 0 of 60 prospectively observed; 228 days carry data, 227 of them backfilled |
| Reconciliation | `RECONCILIATION_INCOMPLETE` / `HISTORICAL_ONLY` at 2026-10-14T06:24:45Z |
| Independent verification | `VERIFY_PASS 13/13` · `SELF_TEST_PASS 16/16` |

## 1. Storage: what was wrong, what was returned, and what was left alone

| | |
| --- | --- |
| Repository size | 5724066394 bytes |
| Proven safe to reclaim | 20771371 bytes of tool cache |
| Actually reclaimed | 45461012 bytes |
| Free after the reclaim | 5907402752 bytes (`HEALTHY`) |
| Free at this reading | 4308934656 bytes |

The reclaim removed tool caches and nothing else: each path was checked, at the moment it was removed, for being a cache by name, untracked by git and named in `.gitignore`. Market data, evidence, other workstreams' artefacts, source and the environment's own files were sized and left alone. The sweep's own reading recorded `HEALTHY` and this reading records `ABOVE_CRITICAL_BELOW_HEALTHY`: the lane ingests and the heavy publication waits, and the repository cannot close that gap out of its own caches. What is left is the volume owner's decision, planned in `VOLUME_NEIGHBOURS.md` rather than executed here.

## 2. The lane, after the refusal

| | |
| --- | --- |
| Tick count by outcome | `already_observed`=4, `already_running`=2, `disk_budget_exceeded`=35, `no_new_data`=3, `observed`=41 |
| First disk refusal | 2026-10-13T20:25:56Z |
| Newest tick | `OBSERVED` with 3 new bar(s), parity `PARITY_PASS` |
| Stored bars | 18318 across 6 series |
| Sealed slots | 43 |
| Ingest attempts | 552, 291 bars appended in total |

## 3. The watchdog, and the cause it now names

| | |
| --- | --- |
| Readings by verdict | `watch_alarm`=4, `watch_blocked`=35, `watch_degraded`=5, `watch_ok`=9 |
| Categories seen | `HEALTHY`=9, `MARKET_QUIET`=1, `RESOURCE_PRESSURE`=35, `SCHEDULER_FAILURE`=8 |
| Newest reading | `WATCH_DEGRADED` / `RESOURCE_PRESSURE`, schema `EDGE05_WATCHDOG_V2` |
| Newest cause | *(no failure class: what the category names is pressure, not a fault)* |
| Alerts | 55 rows |
| Detection latency (rehearsal) | 6.0 s |

The reading schema is now V2: a non-zero scheduler result caused by the lane's own resource guard is filed as `RESOURCE_PRESSURE` with a `TICK_REFUSED_RESOURCE` alert, and the scheduler is explicitly cleared. The verifier checks that claim for itself, and the sabotage matrix now contains a row that files a resource refusal as a scheduler failure.

### The two labels on the same instant, repaired rather than paraphrased

The newest reading publishes its scheduler instants in the form they were derived in: `2026-10-14T06:55:53.0000000Z` with the platform's own spelling kept beside it as `10/14/2026 08:55:53`. Until this work package, that spelling was what the `_utc` field carried: the reading of `2026-10-14T05:32:32Z` printed `10/14/2026 07:40:53` under `next_run_utc` while the same instant read `2026-10-14T05:40:53.0000000Z` two fields away — one instant, two hours apart, in one row.

The figure that was published as `host_clock_skew_seconds` was the same kind of mistake with the sign pointing the wrong way: the probe runs *after* the reading is stamped, so the difference between the two is elapsed time. It is now `watchdog_newest_probe_answer_lag_seconds` = `11.013` s, between the two instants the same check publishes (`reading_stamped_at_utc`, `probe_reported_now_utc`), and only a lag that points *backwards* — an instant older than the stamp it was taken after — is reported as the clock disagreement it would have to be.

The host's own offset is published two ways for the same reason: `120` minutes is the offset in force at the instant read, while the base offset the platform reports is 60 minutes — an hour short of the wall clock, and an hour of error for anyone who converts with it.

Every alert row that names the scheduler or a refused tick, taken from this same reading (`2026-10-14T06:57:22Z`), oldest first. The last two are the repair working on a real refusal:

| Instant | Alert (kind, state, severity) |
| --- | --- |
| `2026-10-13T18:43:44Z` | SCHEDULER_DISABLED ENABLED (INFO) |
| `2026-10-13T18:43:44Z` | SCHEDULER_TASK_FAILED CLEAR (INFO) |
| `2026-10-13T18:48:16Z` | SCHEDULER_DISABLED DISABLED (CRITICAL) |
| `2026-10-13T19:12:07Z` | SCHEDULER_DISABLED ENABLED (INFO) |
| `2026-10-13T20:32:33Z` | SCHEDULER_TASK_FAILED RESULT:DISK_BUDGET_EXCEEDED (CRITICAL) |
| `2026-10-13T21:17:33Z` | SCHEDULER_TASK_FAILED CLEAR (INFO) |
| `2026-10-13T21:32:33Z` | SCHEDULER_TASK_FAILED RESULT:DISK_BUDGET_EXCEEDED (CRITICAL) |
| `2026-10-13T22:02:33Z` | SCHEDULER_TASK_FAILED CLEAR (INFO) |
| `2026-10-13T22:02:33Z` | TICK_REFUSED_RESOURCE CLEAR (INFO) |
| `2026-10-13T22:17:33Z` | TICK_REFUSED_RESOURCE RESULT:DISK_BUDGET_EXCEEDED (CRITICAL) |
| `2026-10-14T05:47:32Z` | TICK_REFUSED_RESOURCE CLEAR (INFO) |

## 4. Reconciliation and the forward window

`RECONCILIATION_INCOMPLETE` here names an incompleteness of the *record*, not an unresolved defect: two ingest attempts (11:25:20Z and 15:02:10Z) have no run row that names them, both are closed episodes whose bars are all present, and every open defect count is zero. The reconciliation refuses to call that clean, and rightly.

| | |
| --- | --- |
| Verdict | `RECONCILIATION_INCOMPLETE` / `HISTORICAL_ONLY` |
| Chains holding | 6 of 6 series |
| Seals | 40, orphaned 0, missing 0 |
| Restart proof | 0 broken of 43 instants ingested twice |
| Defect counts | `chain_broken`=0, `claimed_but_absent`=0, `decision_divergence`=0, `double_claim`=0, `restart_proof_broken`=0, `seal_missing`=0, `seal_orphaned`=0, `unattributed_attempt`=2, `unattributed_bar`=0 |

## 5. The acceptance matrix, each row citing its own figures

| ACC | Requirement | Verdict | Evidence (figures) |
| --- | --- | --- | --- |
| ACC-01 | Runtime audit and a reproducible baseline | **PASS** | `runtime_authority_map_bytes`, `git_head` |
| ACC-02 | The scheduler really fires, with nobody running the command | **PASS** | `lane_ticks_observed`, `lane_ticks_total`, `watchdog_newest_at_utc` |
| ACC-03 | The watchdog detects an induced stop, with a measured latency | **PASS** | `watchdog_detection_latency_seconds`, `watchdog_alert_kinds` |
| ACC-04 | A stop after partial persistence duplicates no bar | **PASS** | `defect_chain_broken`, `defect_double_claim`, `restart_proof_broken`, `reconciliation_seals_orphaned` |
| ACC-05 | A stop during decision or seal leaves one logical decision per slot | **PASS** | `defect_seal_missing`, `defect_seal_orphaned`, `defect_decision_divergence`, `reconciliation_seals` |
| ACC-06 | A retry of the same slot is idempotent everywhere | **PASS** | `lane_ticks_already_observed`, `lane_ticks_already_running` |
| ACC-07 | A restart leaves no orphan lease and no crash | **PASS** | `restart_proof_broken`, `reconciliation_unattributed_bars`, `watchdog_newest_at_utc` |
| ACC-08 | A provider outage is classified, and no forward day is invented | **NOT_TESTED** | `defect_chain_broken` |
| ACC-09 | Disk pressure blocks before corruption and preserves evidence | **PASS** | `lane_ticks_disk_budget_exceeded`, `lane_first_disk_refusal_utc`, `volume_verdict`, `storage_reclaimed_bytes`, `storage_verdict_after` |
| ACC-10 | Forward eligibility excludes backfill and incomplete days | **PASS** | `forward_days_with_data`, `forward_days_densely_covered_but_backfilled`, `forward_days_prospectively_observed`, `forward_days_required` |
| ACC-11 | Risk limits and gates are unchanged | **PASS** | `lane_last_parity_verdict`, `lane_last_ruleset_params_hash` |
| ACC-12 | Independent verification, with the command's own exit code | **PASS** | `verification_verdict`, `verification_self_test`, `tests_chain_passed`, `tests_chain_exit_code`, `tests_chain_failed` |
| ACC-13 | Operation without orders | **PASS** | `lane_rows_claiming_an_order`, `watchdog_rows_claiming_an_order`, `reconciliation_market_requests` |
| ACC-14 | A long unattended window | **NOT_TESTED** | `forward_days_prospectively_observed`, `forward_days_required` |
| ACC-15 | Git and traceability | **PASS** | `git_head`, `git_commits_since_root`, `git_dirty_entries`, `github_push_state` |

### Why each row reads the way it does

* **ACC-01 — PASS.** the authority map of this work package exists, and the commit it was taken at is recorded
* **ACC-02 — PASS.** ticks fired from the registered task with no hand running the command
* **ACC-03 — PASS.** an induced stop was alerted and closed by a named recovering tick; the latency is the one that rehearsal measured
* **ACC-04 — PASS.** bars already persisted when a process stopped are attributed once and nothing is duplicated
* **ACC-05 — PASS.** one logical decision per slot, strategy and asset, with every seal accounted for
* **ACC-06 — PASS.** a second pass over a slot that was already observed appends nothing
* **ACC-07 — PASS.** the lease is read as arithmetic rather than guessed from a pid, and no abandoned lease was found in the newest reading
* **ACC-08 — NOT_TESTED.** no live provider outage has occurred in this window, so the classification is exercised in tests and not in the field; declaring it PASS would be an assertion, not a measurement
* **ACC-09 — PASS.** the floors were crossed for real: the lane refused its own ticks before any request, deleted nothing, and resumed once space came back
* **ACC-10 — PASS.** backfilled days are counted and excluded; a day that is not prospectively complete is not added, so the honest count stays at zero
* **ACC-11 — PASS.** the newest tick's own parity verdict and the parameters hash it ran under; no limit, size or gate was touched by this work package
* **ACC-12 — PASS.** the verifier's own verdict and the chain suites' own exit code, both paid for by running the commands rather than by summarising them
* **ACC-13 — PASS.** no row in the lane's log, the watchdog's log or the reconciliation claims an order or a promotion
* **ACC-14 — NOT_TESTED.** the sixty-day gate is a later milestone, not a condition of this work package; the window measured here is hours, not days
* **ACC-15 — PASS.** the commit this reading was taken at, what is still uncommitted in the shared checkout, and the recorded result of the publication probe

## 6. Regression: what the tests said, and what the failures outside this chain are

| Run | Result | Exit code |
| --- | --- | --- |
| The forward chain's suites | 102 passed, 0 failed | `0` |
| The whole research suite | 2226 passed, 7 failed | `1` |
| Failures with no demonstrated cause | 0 | |

The failures that are not this chain's are attributed rather than waved at:

| Failing test | Cause demonstrated | Owner |
| --- | --- | --- |
| `tests/unit/research/test_active_recovery_wp.py::test_state_view_is_deterministic` | STALE_COMMITTED_ARTEFACT — the test's own message is the diagnosis: 'the committed view is stale'. | WP-8 / campaign state view |
| `tests/unit/research/test_cost_barrier_adversarial.py::test_the_certification_record_digests_content_not_a_checkout` | STALE_COMMITTED_ARTEFACT — the certification record pins a digest (51ef35aa…) that the file on disk no longer hashes to (3fb11fc9…): the record and the artefact it certifies have drifted apart. | cost barrier |
| `tests/unit/research/test_recovery_determinism.py::test_repeated_reproduction_is_byte_identical` | STALE_COMMITTED_ARTEFACT — re-running the documented reproduction moves data/recovery/CAMPAIGN_STATE_VIEW.json and CAMPAIGN_STATE_VIEW_REPORT.md: the committed view was generated from an older state than the one on disk. | WP-8 (recovery) |
| `tests/unit/research/test_recovery_determinism.py::test_the_clean_checkout_rehearsal_passes_on_this_commit` | STALE_COMMITTED_ARTEFACT — re-running the documented reproduction moves data/recovery/CAMPAIGN_STATE_VIEW.json and CAMPAIGN_STATE_VIEW_REPORT.md: the committed view was generated from an older state than the one on disk. | WP-8 (recovery) |
| `tests/unit/research/test_wp9_disk_budget.py::test_the_launcher_autoscales_only_when_asked_and_the_children_get_the_new_valve` | HOST_FREE_SPACE — the launcher's own preflight reads the real volume, so on a host under its floors it refuses with INSUFFICIENT_FREE_SPACE before the valve arithmetic the test is about. The same class of defect this work package removed from the forward chain's fixtures. | WP-9B (paper lab disk budget) |
| `tests/unit/research/test_wp9_disk_budget.py::test_the_launcher_costs_the_declared_window_before_starting` | HOST_FREE_SPACE — the launcher's own preflight reads the real volume, so on a host under its floors it refuses with INSUFFICIENT_FREE_SPACE before the valve arithmetic the test is about. The same class of defect this work package removed from the forward chain's fixtures. | WP-9B (paper lab disk budget) |
| `tests/unit/research/test_wp9_disk_budget.py::test_the_launcher_refuses_the_configuration_that_failed` | HOST_FREE_SPACE — the launcher's own preflight reads the real volume, so on a host under its floors it refuses with INSUFFICIENT_FREE_SPACE before the valve arithmetic the test is about. The same class of defect this work package removed from the forward chain's fixtures. | WP-9B (paper lab disk budget) |

The 3 `HOST_FREE_SPACE` failures are the same defect this work package removed from the forward chain's fixtures, in another workstream's launcher tests: their own launcher states the refusal it hit (`INSUFFICIENT_FREE_SPACE` — the declared window costs more than this volume's free space above its reserve). The fix is stated in `REGRESSION.json` and left to that workstream, because the file is theirs.
The 4 `STALE_COMMITTED_ARTEFACT` failures are a committed view and a certification record that no longer match the state they describe — also not this work package's to regenerate.

## 7. Every figure in this report, with its instant and its source

| Figure | Value | Unit | as_of_utc | Source digest | Scope |
| --- | --- | --- | --- | --- | --- |
| `defect_chain_broken` | 0 | count | 2026-10-14T06:57:22Z | `1f883dd5b673…` | closed defect counts from the reconciliation |
| `defect_claimed_but_absent` | 0 | count | 2026-10-14T06:57:22Z | `1f883dd5b673…` | closed defect counts from the reconciliation |
| `defect_decision_divergence` | 0 | count | 2026-10-14T06:57:22Z | `1f883dd5b673…` | closed defect counts from the reconciliation |
| `defect_double_claim` | 0 | count | 2026-10-14T06:57:22Z | `1f883dd5b673…` | closed defect counts from the reconciliation |
| `defect_restart_proof_broken` | 0 | count | 2026-10-14T06:57:22Z | `1f883dd5b673…` | closed defect counts from the reconciliation |
| `defect_seal_missing` | 0 | count | 2026-10-14T06:57:22Z | `1f883dd5b673…` | closed defect counts from the reconciliation |
| `defect_seal_orphaned` | 0 | count | 2026-10-14T06:57:22Z | `1f883dd5b673…` | closed defect counts from the reconciliation |
| `defect_unattributed_attempt` | 2 | count | 2026-10-14T06:57:22Z | `1f883dd5b673…` | closed defect counts from the reconciliation |
| `defect_unattributed_bar` | 0 | count | 2026-10-14T06:57:22Z | `1f883dd5b673…` | closed defect counts from the reconciliation |
| `forward_coverage_required` | 0.9 | ratio | 2026-10-14T06:57:22Z | `17831c89535a…` | the lane's own coverage file: what it counts and what it refuses |
| `forward_days_densely_covered_but_backfilled` | 227 | days | 2026-10-14T06:57:22Z | `17831c89535a…` | the lane's own coverage file: what it counts and what it refuses |
| `forward_days_observed_window` | 227 | days | 2026-10-14T06:57:22Z | `17831c89535a…` | the lane's own coverage file: what it counts and what it refuses |
| `forward_days_prospectively_observed` | 0 | days | 2026-10-14T06:57:22Z | `17831c89535a…` | the lane's own coverage file: what it counts and what it refuses |
| `forward_days_remaining` | 60 | days | 2026-10-14T06:57:22Z | `17831c89535a…` | the lane's own coverage file: what it counts and what it refuses |
| `forward_days_required` | 60 | days | 2026-10-14T06:57:22Z | `17831c89535a…` | the lane's own coverage file: what it counts and what it refuses |
| `forward_days_with_data` | 228 | days | 2026-10-14T06:57:22Z | `17831c89535a…` | the lane's own coverage file: what it counts and what it refuses |
| `forward_epoch_utc` | 2026-03-01T00:00:00Z | instant | 2026-10-14T06:57:22Z | `17831c89535a…` | the lane's own coverage file: what it counts and what it refuses |
| `forward_freeze` | frozen_15m_end_utc=2026-10-07T11:30:00Z, frozen_1h_end_utc=2026-02-28T23:00:00Z, params_hash=d073a2d686b9b198c36c9a3c6009d36130577ba247a2016c3f791813cb749d77, reading=the frozen corpora end at these instants; every stored bar is strictly later, and no day before the epoch is a forward observation day | label | 2026-10-14T06:57:22Z | `17831c89535a…` | the lane's own coverage file: what it counts and what it refuses |
| `git_branch` | agent/edge-recovery/WP-EDGE-00-baseline | label | 2026-10-14T06:57:22Z | `7c2818bac891…` | the branch the reading was taken on |
| `git_commits_since_root` | 399 | commits | 2026-10-14T06:57:22Z | `7c2818bac891…` | commits reachable from HEAD since the root commit |
| `git_dirty_entries` | 135 | paths | 2026-10-14T06:57:22Z | `7c2818bac891…` | lines of `git status --porcelain`: every change, whoever made it |
| `git_head` | f418619372e0eae0bbbdfaaebbd84f54804fdff1 | commit | 2026-10-14T06:57:22Z | `7c2818bac891…` | the commit the reading was taken at |
| `github_probe_exit_code` | 0 | exit code | 2026-10-14T06:57:22Z | `a857462e653f…` | the probe's own exit status |
| `github_push_state` | AVAILABLE_NOT_EXERCISED | label | 2026-10-14T06:57:22Z | `a857462e653f…` | the recorded result of the publication probe, not re-probed here |
| `ingest_appended_bars` | 291 | bars | 2026-10-14T06:57:22Z | `85abd4da3d44…` | the `appended` field summed over every ingest attempt |
| `ingest_ledger_rows` | 552 | attempts | 2026-10-14T06:57:22Z | `85abd4da3d44…` | every ingest attempt the lane recorded, one row per series and tick |
| `lane_first_disk_refusal_utc` | 2026-10-13T20:25:56Z | instant | 2026-10-14T06:57:22Z | `f032e803bd8c…` | the first row of the lane's run log that refused on disk, if any |
| `lane_health_last_observation_utc` | 2026-10-14T06:57:08Z | instant | 2026-10-14T06:57:22Z | `5c0ec59c33a4…` | the lane's own health file |
| `lane_health_status` | DEGRADED | label | 2026-10-14T06:57:22Z | `5c0ec59c33a4…` | the lane's own health file at this instant |
| `lane_last_exit_code` | 0 | exit code | 2026-10-14T06:57:22Z | `f032e803bd8c…` | the newest row of the lane's run log |
| `lane_last_health_status` | DEGRADED | label | 2026-10-14T06:57:22Z | `f032e803bd8c…` | the newest row of the lane's run log |
| `lane_last_market_requests` | 4 | requests | 2026-10-14T06:57:22Z | `f032e803bd8c…` | the newest row of the lane's run log |
| `lane_last_new_bars` | 3 | bars | 2026-10-14T06:57:22Z | `f032e803bd8c…` | the newest row of the lane's run log |
| `lane_last_outcome` | OBSERVED | label | 2026-10-14T06:57:22Z | `f032e803bd8c…` | the newest row of the lane's run log |
| `lane_last_parity_verdict` | PARITY_PASS | label | 2026-10-14T06:57:22Z | `f032e803bd8c…` | the newest row of the lane's run log |
| `lane_last_ruleset_params_hash` | d073a2d686b9b198c36c9a3c6009d36130577ba247a2016c3f791813cb749d77 | digest | 2026-10-14T06:57:22Z | `f032e803bd8c…` | the newest row of the lane's run log |
| `lane_last_tick_utc` | 2026-10-14T06:57:08Z | instant | 2026-10-14T06:57:22Z | `f032e803bd8c…` | the newest row of the lane's run log |
| `lane_rows_claiming_an_order` | 0 | rows | 2026-10-14T06:57:22Z | `f032e803bd8c…` | every lane run row, checked for a sent order or a promotion |
| `lane_slot_seals` | 43 | seals | 2026-10-14T06:57:22Z | `4f50a60e083b…` | sealed slots in the lane's slot ledger |
| `lane_ticks_already_observed` | 4 | ticks | 2026-10-14T06:57:22Z | `f032e803bd8c…` | rows of the lane's run log whose outcome is ALREADY_OBSERVED |
| `lane_ticks_already_running` | 2 | ticks | 2026-10-14T06:57:22Z | `f032e803bd8c…` | rows of the lane's run log whose outcome is ALREADY_RUNNING |
| `lane_ticks_disk_budget_exceeded` | 35 | ticks | 2026-10-14T06:57:22Z | `f032e803bd8c…` | rows of the lane's run log whose outcome is DISK_BUDGET_EXCEEDED |
| `lane_ticks_no_new_data` | 3 | ticks | 2026-10-14T06:57:22Z | `f032e803bd8c…` | rows of the lane's run log whose outcome is NO_NEW_DATA |
| `lane_ticks_observed` | 41 | ticks | 2026-10-14T06:57:22Z | `f032e803bd8c…` | rows of the lane's run log whose outcome is OBSERVED |
| `lane_ticks_total` | 85 | ticks | 2026-10-14T06:57:22Z | `f032e803bd8c…` | every row of the lane's run log |
| `reconciliation_chains_holding` | 6 | series | 2026-10-14T06:57:22Z | `1f883dd5b673…` | of 6 series, how many chains the recomputation holds for |
| `reconciliation_generated_at_utc` | 2026-10-14T06:24:45Z | instant | 2026-10-14T06:57:22Z | `1f883dd5b673…` | the newest reconciliation on file |
| `reconciliation_historical_defects` | 2 | defects | 2026-10-14T06:57:22Z | `1f883dd5b673…` | the newest reconciliation on file |
| `reconciliation_market_requests` | 0 | requests | 2026-10-14T06:57:22Z | `1f883dd5b673…` | the newest reconciliation on file |
| `reconciliation_open_defects` | 0 | defects | 2026-10-14T06:57:22Z | `1f883dd5b673…` | the newest reconciliation on file |
| `reconciliation_seals` | 40 | seals | 2026-10-14T06:57:22Z | `1f883dd5b673…` | sealed slots the reconciliation accounted for |
| `reconciliation_seals_missing_for_a_consuming_run` | 0 | seals | 2026-10-14T06:57:22Z | `1f883dd5b673…` | the reconciliation's own seal accounting |
| `reconciliation_seals_of_an_unrecorded_run` | 0 | seals | 2026-10-14T06:57:22Z | `1f883dd5b673…` | the reconciliation's own seal accounting |
| `reconciliation_seals_orphaned` | 0 | seals | 2026-10-14T06:57:22Z | `1f883dd5b673…` | the reconciliation's own seal accounting |
| `reconciliation_status` | HISTORICAL_ONLY | label | 2026-10-14T06:57:22Z | `1f883dd5b673…` | the newest reconciliation on file |
| `reconciliation_stored_bars` | 18309 | bars | 2026-10-14T06:57:22Z | `1f883dd5b673…` | stored bars summed over the per-series chains |
| `reconciliation_unattributed_bars` | 0 | bars | 2026-10-14T06:57:22Z | `1f883dd5b673…` | stored bars no recorded attempt claims, named rather than deleted |
| `reconciliation_verdict` | RECONCILIATION_INCOMPLETE | label | 2026-10-14T06:57:22Z | `1f883dd5b673…` | the newest reconciliation on file |
| `restart_proof_broken` | 0 | instances | 2026-10-14T06:57:22Z | `1f883dd5b673…` | instants where the second ingest pass appended a bar it should not have |
| `restart_proof_instants_with_two_passes` | 43 | instants | 2026-10-14T06:57:22Z | `1f883dd5b673…` | market instants the lane ingested twice, as its own design does |
| `runtime_authority_map_bytes` | 7058 | bytes | 2026-10-14T06:57:22Z | `c0cc7f25eed2…` | this work package's own runtime authority map, as written |
| `storage_free_bytes_after` | 5907402752 | bytes | 2026-10-14T06:57:22Z | `dc525c5201fd…` | free space after the reclaim, from the OS |
| `storage_reclaimed_bytes` | 45461012 | bytes | 2026-10-14T06:57:22Z | `dc525c5201fd…` | bytes removed by the reclaim, measured by the OS |
| `storage_repo_bytes` | 5724066394 | bytes | 2026-10-14T06:57:22Z | `63f987ca4ff4…` | every file under the repository root |
| `storage_safe_reclaimable_bytes` | 20771371 | bytes | 2026-10-14T06:57:22Z | `63f987ca4ff4…` | tool caches proven untracked and gitignored at that reading |
| `storage_verdict_after` | HEALTHY | label | 2026-10-14T06:57:22Z | `dc525c5201fd…` | the floor the volume stood at after the reclaim |
| `store_bars` | 18318 | bars | 2026-10-14T06:57:22Z | `4125028fd405…` | every stored closed bar, summed over the series |
| `store_series` | 6 | series | 2026-10-14T06:57:22Z | `4125028fd405…` | every series file in the forward store |
| `tests_chain_exit_code` | 0 | exit code | 2026-10-14T06:57:22Z | `53368382d1a9…` | the test command's own exit status, not a summary of it |
| `tests_chain_failed` | 0 | tests | 2026-10-14T06:57:22Z | `53368382d1a9…` | failures in the forward chain's suites |
| `tests_chain_passed` | 102 | tests | 2026-10-14T06:57:22Z | `53368382d1a9…` | the forward chain's three suites: the lane's, the watchdog's, the reconciliation's |
| `tests_full_exit_code` | 1 | exit code | 2026-10-14T06:57:22Z | `53368382d1a9…` | the whole-suite command's own exit status |
| `tests_full_failed` | 7 | tests | 2026-10-14T06:57:22Z | `53368382d1a9…` | failures anywhere in the research suite, this work package's or not |
| `tests_full_passed` | 2226 | tests | 2026-10-14T06:57:22Z | `53368382d1a9…` | every test under tests/unit/research, run in one invocation |
| `tests_unexplained_failures` | 0 | tests | 2026-10-14T06:57:22Z | `53368382d1a9…` | failures for which no cause was demonstrated |
| `verification_generated_at_utc` | None | instant | 2026-10-14T06:57:22Z | `ece67e5677c5…` | when the verifier read the state |
| `verification_self_test` | SELF_TEST_PASS 16/16 | label | 2026-10-14T06:57:22Z | `ece67e5677c5…` | how many sabotages the matrix caught |
| `verification_verdict` | VERIFY_PASS 13/13 | label | 2026-10-14T06:57:22Z | `ece67e5677c5…` | the independent verifier's own verdict on the latest state |
| `volume_change_bytes_per_hour` | -253106336.8 | bytes per hour | 2026-10-14T06:57:22Z | `87dff3a645e6…` | the change in free space between the first and the newest footprint of 12.01 h: negative means the volume is being consumed faster than it is being returned, and this window contains the reclaim |
| `volume_change_bytes_per_hour_recent` | -379837084.5 | bytes per hour | 2026-10-14T06:57:22Z | `87dff3a645e6…` | the same quantity over the newest three readings, after the reclaim |
| `volume_free_bytes` | 4308934656 | bytes | 2026-10-14T06:57:22Z | `83d072d27d0a…` | volume C: as seen from the repository root |
| `volume_free_bytes_first_watchdog_reading` | 7233032192 | bytes | 2026-10-14T06:57:22Z | `87dff3a645e6…` | the oldest watchdog reading on file that recorded free space |
| `volume_free_bytes_newest_watchdog_reading` | 4194103296 | bytes | 2026-10-14T06:57:22Z | `87dff3a645e6…` | the newest watchdog reading that recorded free space |
| `volume_free_gib` | 4.013 | GiB | 2026-10-14T06:57:22Z | `83d072d27d0a…` | volume C: |
| `volume_verdict` | ABOVE_CRITICAL_BELOW_HEALTHY | label | 2026-10-14T06:57:22Z | `83d072d27d0a…` | the two floors the lane's own guard declares (2 GiB and 5 GiB) |
| `watchdog_alert_kinds` | DISK_CRITICAL=1, DISK_RECOVERED=1, DISK_WARNING=4, EVIDENCE_CORRUPT=1, GROWTH_BUDGET_EXCEEDED=1, INGEST_STALLED=1, MARKET_QUIET=4, RECONCILIATION_REQUIRED=13 | map | 2026-10-14T06:57:22Z | `d2441a196dc3…` | alert rows grouped by kind |
| `watchdog_alerts` | 55 | alerts | 2026-10-14T06:57:22Z | `d2441a196dc3…` | every alert row the watchdog appended, one per transition |
| `watchdog_categories_seen` | HEALTHY=9, MARKET_QUIET=1, RESOURCE_PRESSURE=35, SCHEDULER_FAILURE=8 | map | 2026-10-14T06:57:22Z | `87dff3a645e6…` | how many readings were filed under each category, over the whole log |
| `watchdog_detection_latency_seconds` | 6.0 | seconds | 2026-10-14T06:57:22Z | `e7757ea1d5c3…` | the induced-outage rehearsal of 2026-10-13 18:48Z: the watchdog's own two readings around the stop, quoted from that evidence file |
| `watchdog_newest_at_utc` | 2026-10-14T06:47:33Z | instant | 2026-10-14T06:57:22Z | `87dff3a645e6…` | the newest reading on file |
| `watchdog_newest_category` | RESOURCE_PRESSURE | label | 2026-10-14T06:57:22Z | `87dff3a645e6…` | the newest reading on file |
| `watchdog_newest_cause` | None | label | 2026-10-14T06:57:22Z | `87dff3a645e6…` | the newest reading on file |
| `watchdog_newest_local_utc_offset_minutes` | 120 | minutes | 2026-10-14T06:57:22Z | `87dff3a645e6…` | the newest reading's own scheduler section |
| `watchdog_newest_operational_failure` | False | boolean | 2026-10-14T06:57:22Z | `87dff3a645e6…` | the newest reading on file |
| `watchdog_newest_probe_answer_lag_seconds` | 11.013 | seconds | 2026-10-14T06:57:22Z | `87dff3a645e6…` | the newest reading's own scheduler section |
| `watchdog_newest_scheduler_next_run_utc` | 2026-10-14T06:55:53.0000000Z | instant | 2026-10-14T06:57:22Z | `87dff3a645e6…` | the newest reading's own scheduler section |
| `watchdog_newest_scheduler_platform_spelling` | 10/14/2026 08:55:53 | label | 2026-10-14T06:57:22Z | `87dff3a645e6…` | the newest reading's own scheduler section |
| `watchdog_newest_schema` | EDGE05_WATCHDOG_V2 | label | 2026-10-14T06:57:22Z | `87dff3a645e6…` | the newest reading on file |
| `watchdog_newest_verdict` | WATCH_DEGRADED | label | 2026-10-14T06:57:22Z | `87dff3a645e6…` | the newest reading on file |
| `watchdog_readings` | 53 | readings | 2026-10-14T06:57:22Z | `87dff3a645e6…` | every reading the watchdog has on file |
| `watchdog_rows_claiming_an_order` | 0 | rows | 2026-10-14T06:57:22Z | `87dff3a645e6…` | every watchdog reading, checked for a sent order or a promotion |
| `watchdog_verdict_watch_alarm` | 4 | readings | 2026-10-14T06:57:22Z | `87dff3a645e6…` | readings whose verdict is WATCH_ALARM |
| `watchdog_verdict_watch_blocked` | 35 | readings | 2026-10-14T06:57:22Z | `87dff3a645e6…` | readings whose verdict is WATCH_BLOCKED |
| `watchdog_verdict_watch_degraded` | 5 | readings | 2026-10-14T06:57:22Z | `87dff3a645e6…` | readings whose verdict is WATCH_DEGRADED |
| `watchdog_verdict_watch_ok` | 9 | readings | 2026-10-14T06:57:22Z | `87dff3a645e6…` | readings whose verdict is WATCH_OK |

## 8. Sources, each with the digest it had at this reading

| Source | Path | Bytes | Rows | Digest |
| --- | --- | --- | --- | --- |
| `coverage` | `C:\Users\GVLLFR0035\Downloads\bot freebuff\data\forward\edge04\coverage.json` | 121602 | None | `17831c89535ae2b6…` |
| `git` | `C:\Users\GVLLFR0035\Downloads\bot freebuff\.git\HEAD` | 56 | None | `7c2818bac891262d…` |
| `github_state` | `reports\edge-recovery\WP-EDGE-05R\GITHUB_STATE.json` | 3312 | None | `a857462e653f8e63…` |
| `ingest_ledger` | `C:\Users\GVLLFR0035\Downloads\bot freebuff\data\forward\edge04\ledger\INGEST_LEDGER.jsonl` | 446718 | 552 | `85abd4da3d443cb3…` |
| `lane_health` | `C:\Users\GVLLFR0035\Downloads\bot freebuff\data\forward\edge04\health.json` | 4532 | None | `5c0ec59c33a4d1a4…` |
| `lane_runs` | `C:\Users\GVLLFR0035\Downloads\bot freebuff\data\forward\edge04\runs.jsonl` | 290123 | 85 | `f032e803bd8c0bfd…` |
| `lane_slots` | `C:\Users\GVLLFR0035\Downloads\bot freebuff\data\forward\edge04\slots.jsonl` | 10716 | 43 | `4f50a60e083b0a8e…` |
| `outage_detect` | `C:\Users\GVLLFR0035\Downloads\bot freebuff\reports\edge-recovery\WP-EDGE-05\evidence\OUTAGE_DETECT_1.txt` | 1583 | None | `e7757ea1d5c3fc59…` |
| `reconciliation` | `C:\Users\GVLLFR0035\Downloads\bot freebuff\data\forward\edge05\reconciliation\RECONCILIATION.json` | 15015 | None | `1f883dd5b6735837…` |
| `regression` | `reports\edge-recovery\WP-EDGE-05R\REGRESSION.json` | 7389 | None | `53368382d1a9d1b3…` |
| `runtime_authority_map` | `reports\edge-recovery\WP-EDGE-05R\runtime_authority_map.md` | 7058 | None | `c0cc7f25eed26094…` |
| `storage_inventory` | `reports\edge-recovery\WP-EDGE-05R\STORAGE_INVENTORY.json` | 127018 | None | `63f987ca4ff41aba…` |
| `storage_reclaim` | `reports\edge-recovery\WP-EDGE-05R\STORAGE_RECLAIM.json` | 140440 | None | `dc525c5201fdf9e0…` |
| `store` | `C:\Users\GVLLFR0035\Downloads\bot freebuff\data\forward\edge03` | 5671017 | 18318 | `4125028fd405de0a…` |
| `verification` | `reports\edge-recovery\WP-EDGE-05R\VERIFICATION.json` | 14789 | None | `ece67e5677c5f825…` |
| `volume` | `C:\Users\GVLLFR0035\Downloads\bot freebuff\pyproject.toml` | 7335 | None | `83d072d27d0a6b2e…` |
| `watchdog_alerts` | `C:\Users\GVLLFR0035\Downloads\bot freebuff\data\forward\edge05\watch_alerts.jsonl` | 65301 | 55 | `d2441a196dc3282e…` |
| `watchdog_readings` | `C:\Users\GVLLFR0035\Downloads\bot freebuff\data\forward\edge05\watchdog.jsonl` | 729772 | 53 | `87dff3a645e6d936…` |

## 9. How to reproduce

```bash
# one reading, frozen with its digest
python scripts/edge05r_snapshot.py

# the reports, rendered from that reading and from nothing else
python scripts/edge05r_report.py

# storage, read-only then applied
python scripts/edge05r_storage_inventory.py
python scripts/edge05r_storage_reclaim.py
python scripts/edge05r_storage_reclaim.py --apply

# the reconciliation and the independent verifier, in this order
python scripts/edge05_reconcile.py
python scripts/edge05_verify.py --self-test
```

A report rendered from a snapshot whose digest does not match its own contents is refused: `edge05r_report.py` exits non-zero and writes nothing.
