# WP-EDGE-07 — FINAL REPORT

*Read at `2026-10-14T09:24:49Z` from `196deb49475e` on branch `agent/edge-recovery/WP-EDGE-00-baseline`. One reading, three reports: the run record, the verification and this one are renderings of the same frozen dictionary.*

## 1. In one line

**`CLOSED_WITH_OPEN_ITEMS`** — the volume was recovered far enough to bring the lane back, the trend book and both ACTIVE books were rejected by criteria registered before their windows were read, the frequency question was answered by measurement, and the independent verifier passes 13/13 with 14 of 14 sabotages caught.

## 2. Track A — the volume, the lane, and the criterion that was missing

| Item | What was done | Evidence |
| --- | --- | --- |
| Branch, remote, commits | Published: `edd4ef2..196deb4` fast-forwarded the existing remote branch (no force), and the remote was read back to confirm it holds this reading's `head`: True | `GITHUB_STATE.json` |
| Recovery | 4 applied sweeps totalling **2,261,922,757 bytes (2.11 GiB)** of this repository's own tool caches, every removal re-checked at the instant it was made (193 recorded paths, 0 still present) | `STORAGE_RECLAIM.md` |
| The lane resumed | 2 real scheduled observing ticks after the reclaim, the first on `2026-10-14T08:45Z` | `RUN_REPORT.md` §2 |
| The volume today | 3.365 GiB free — `ABOVE_CRITICAL_BELOW_HEALTHY`, above the 2.0 GiB the lane refuses under | `RUN_REPORT.json` |
| Who else grows it | 12 neighbouring entries named and left alone; the writers table is the volume owner's to act on | `GROWTH_EVIDENCE.md` |

## 3. Track B — the trend book, on a window nobody had read

The frozen parameters were registered at `2026-10-14T08:53:54Z` (`EDGE07-PREREG-20261014T085354Z`, committed before the corpus was fetched) and the window (`2026-03-01T00:00:00Z` … `2026-10-14T07:00:00Z`, 1363 4h bars on each of BTC, ETH, SOL, 0 gaps) was read once, with the criteria already written down.

**The verdict is `REJECT`** — decisive criterion failed on NEW_HOLDOUT: P2, P3, P4, P5, P6, R1, R2. Net -140.3041 USDT over 65 trades at BASE, expectancy -2.1585 USDT/trade, 1 of 3 time blocks positive, and the sample is powered (True): this is a rejection, not an absence of evidence.

What did *not* fail is worth keeping: trades >= 30 (65) and DEV gross > 0 (1746.0725) both hold, and the lag-1 autocorrelation of trade returns is 0.5073 against a ±0.2481 band — the losses are not independent draws, which is one more reason the fixed target needed a new window rather than a re-read of the old one.

The comparison arm was declared before the window was read and is reported with it: the frozen trailing exit earned 61.0046 USDT over 28 trades — positive, but on fewer trades than the registered floor of 30 and with the largest single trade at 223.7 % of the net, so it is `INSUFFICIENT_EVIDENCE` and not a pass. Multiplicity is declared at 2 arms — this primary book and that comparison — and both readings are reported.

## 4. Track C — the ACTIVE books, and why frequency is closed by arithmetic

Two structurally different ACTIVE books were registered before any of them was screened (`2026-10-14T09:20:00Z`, multiplicity 2, 3 trades a day declared as the mission's target). Both were stopped by their own registered screen — `edge07_active_fade` REJECT_NO_GROSS_EDGE; `edge07_active_thrust` REJECT_NO_GROSS_EDGE — and neither read the independent window.

The durable result is the ceiling they ran into: at a one-hour clock a book must capture 58 to 86 % of the whole open-to-open move just to pay the 23.7906 bps round trip, while a daily clock (one trade per asset per day, 3 across the universe) needs 11 to 16 %. The mission's frequency target is not closed — it is affordable at the daily clock and closed at the hourly one.

## 5. What this work package does NOT declare

- Not `CERTIFIED`, not `READY_FOR_PAPER`, not `PRODUCTION_READY`, and no profitability. `promotion: NONE`, `order_sent: False`.
- **No forward day is shortened or added**: the 60-day gate is untouched.
- The volume is above the floor the lane refuses under and **below the 5.0 GiB** the heavy publication waits for: the shortfall is named, not hidden.
- `NEW_HOLDOUT` was read once by the frozen parameters. It may not be re-run, tuned or re-read; a structure that would have helped is a new registration, not an edit.
- Two candidates is two candidates. Track C does not establish that no ACTIVE book can work, only that these two lose before costs and that the hourly clock cannot pay for itself.
- The reclaim removed this repository's own tool caches only. The volume's other writers were named and left untouched — they are the volume owner's decision.
- No credential was read, stored or printed; no risk limit, sizing rule, gate or promotion path was modified, and the frozen bytes are the registered ones (`9ceb20fc7d4500c3…`).

## 6. What stays open, and who can close it

- The volume is 3.365 GiB free: above the 2.0 GiB the lane refuses under and below the 5.0 GiB the heavy publication waits for, so the lane ingests while the heavier export still waits — *The volume's owner: clear temporary files older than a day*
- The trend book with the fixed target was rejected on a window nobody had read, so 'would a different exit have saved it' is unanswered — the trailing arm on the same window is positive but under-powered — *A new pre-registration, on a window that has not been read*
- Both ACTIVE books were stopped by their own registered screen before the independent window, so the hourly frequency target rests on the measured ceiling rather than on a candidate — *A new registration at a clock the barrier table says is affordable*

### The next actions, in order of what unblocks the most

1. **Clear temporary files older than a day** in `%LOCALAPPDATA%\Temp`: it is the only thing between the lane and the healthy floor, and it is the volume owner's call, not a repository cleanup.
2. **Open the daily clock as its own registration** — `P-ACTIVE-DAILY` in `active-research/FINDINGS.md` — where the barrier is 11 to 16 % instead of 58 to 86 %: it answers 'is there enough edge to pay 23.79 bps', which is the question the hourly books could not.
3. **Give the fixed-target trend entry a window that has not been read** if the exit question is worth another pre-registration: `NEW_HOLDOUT` is spent for it.

---

### The reading this report was rendered from

| Figure | Value |
| --- | --- |
| `as_of_utc` | `2026-10-14T09:24:49Z` |
| `head` | `196deb49475e171c4a4ef3b0a21620e0f4a8be39` |
| `branch` | `agent/edge-recovery/WP-EDGE-00-baseline` |
| `worktree_dirty_entries` | `137` |
| `worktree_dirty_entries_of_this_work_package` | `1` |
| `volume.free_bytes` | `3612786688` |
| `volume.free_gib` | `3.365` |
| `volume.verdict` | `ABOVE_CRITICAL_BELOW_HEALTHY` |
| `storage.applied_runs` | `4` |
| `storage.reclaimed_bytes_total` | `2261922757` |
| `storage.paths_recorded_as_removed` | `193` |
| `storage.latest_applied_utc` | `2026-10-14T08:50:23Z` |
| `lane.runs_total` | `96` |
| `lane.runs_observing` | `49` |
| `lane.refusals_for_disk` | `41` |
| `lane.scheduled_observing_ticks_after_the_reclaim_count` | `2` |
| `validation.verdict` | `REJECT` |
| `validation.powered` | `True` |
| `validation.new_window.trades` | `65` |
| `validation.new_window.net_usdt` | `-140.3041` |
| `validation.registered_at_utc` | `2026-10-14T08:53:54Z` |
| `validation.coverage_4h_bars` | `1363` |
| `validation.gaps` | `0` |
| `active.verdicts` | `{'edge07_active_fade': 'REJECT_NO_GROSS_EDGE', 'edge07_active_thrust': 'REJECT_NO_GROSS_EDGE'}` |
| `barrier.declared_cost_wall_bps` | `23.7906` |
| `verification.result` | `PASS` |
| `verification.checks_passed` | `13` |
| `verification.failing` | `0` |
| `verification.sabotages_detected` | `14` |
| `tests.owned_summary` | `26 passed in 2.11s` |
| `tests.owned_exit_code` | `0` |
