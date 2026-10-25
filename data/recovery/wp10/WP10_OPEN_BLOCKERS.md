# WP-10 PHASE 6 — OPEN BLOCKERS

> `2026-10-11T22:43:08Z` · head `5348fcd55ab9ef404c676d8aada8daa8c85b9785` · branch `main`

**BLOCKED for the four operational items that need publication, a longer window, a bigger volume or an operator decision; OPEN for offline economic work on data already captured**

## 1. CI runner certification — `BLOCKED`

* remote `https://github.com/Extr3sao/bot_crypto.git`, upstream `origin/main`
* unpublished commits: **256** (1524 files) — nothing at this HEAD can have a run
* workflows tracked at HEAD: `.github/workflows/ci.yml`, `.github/workflows/cost-barrier-gate.yml`, `.github/workflows/recovery-determinism.yml`
* workflow files on disk but untracked: none (they are all committed)
* GitHub CLI present: `False`

Missing to certify:
* the workflows must reach the remote before GitHub can register or run them
* 256 commits are not published, so no run can exist for the current HEAD
* no GitHub CLI is installed here, and no token is configured for this checkout, so a run id cannot be read even if a run existed

Not certified by: the local execution of the workflow's steps, which WP-9 ran and recorded: a local rehearsal is a rehearsal, never a certification.

## 2. The window that ended without a record — `EXTERNAL_TERMINATION`

Run `reports/paper-lab/paper-lab-continuous-03`: plan duration `0.0` h (which the launcher reads as 'until stopped'), collector valve 7.0 GB

| when | what the record says |
| --- | --- |
| 2026-09-30T18:06:02Z | first monitor record |
| 2026-09-30T23:46:14Z | last monitor record: state `HEALTHY`, uptime 5.8866 h, children {"paper": "RUNNING", "collector": "RUNNING", "retention": "RUNNING", "strategy_lab": "RUNNING"}, restarts {"paper": 0, "collector": 0, "retention": 0, "strategy_lab": 0}, disk free 31.502 GB, collector stop reason `None` |
| 2026-09-30T23:47:05Z | final heartbeat: state `HEALTHY`, degraded `False`, storage_guard_stopped `[]`, heartbeat write failures 0 |
| 2026-09-30T23:47:04Z | collector state saved: stop reason `None`, events 12873668 |
| 2026-09-30T23:47:09Z | last segment written: `reports/microstructure-forward-continuous/segments/binance/perp/ETHUSDT/depth_diff/2026-09-30/234500.jsonl.gz` |

Each suspect, and the artefact that excludes it:

| suspect | excluded | evidence |
| --- | --- | --- |
| disk exhaustion or a storage guard | yes | free 31.509 GB at the last heartbeat, level NORMAL, storage_guard_stopped=[], and the collector had written 1.737 GB of its 7.0 GB valve |
| a stop request through the documented stop files | yes | no stop file at reports/microstructure-forward-continuous/state/paper-lab-continuous-03.stop and the collector state records stop_reason=None |
| a configured duration being reached | yes | the plan declares duration_hours=0.0 which the launcher turns into max_seconds=None, i.e. 'until stopped' |
| a crash inside the launcher | yes | the launcher writes its report, snapshot and a system daily report inside a try/except BaseException + finally block, so even a crash leaves them; {'LAB_RUN_REPORT.json': False, 'LAB_RUN_REPORT.md': False, 'LAB_RUN_SNAPSHOT.json': False} - none exists |
| an operator Ctrl+C (KeyboardInterrupt), which the same block catches | yes | same crash-survivable path; an interrupt would still have written the report |

**Finding:** EXTERNAL_TERMINATION — every in-lane suspect is excluded by an artefact, and the termination bypassed a crash-survivable exit path, so the actuator was outside the lane. It is not attributable from the repository: the candidate remains an operating-system or process-tree teardown on a shared host, and no evidence in this tree distinguishes it further

*Consequence:* the window's data cannot be used as evidence for M-03: no manifest was sealed, the collector state carries no stop reason, and the certification chain the repository requires (manifest + replay verification) was never completed.

## 3. The volume budget

* free now: **17.051 GB** of 255.042 GB (93.31 % used by everything on the host)
* measured capture rate: 192.252 MB/h
* that budget affords: **88.69 h** of this lane's capture

| horizon | needed GB | fits now | fits at 1.5x |
| ---: | ---: | --- | --- |
| 24 h | 4.614 | True | True |
| 48 h | 9.228 | True | True |
| 72 h | 13.842 | True | False |
| 168 h | 32.298 | False | False |

* do not launch a 72 h or 168 h window while the budget cannot pay for it: the arithmetic is done before the launch, not discovered during it

## 4. M-03 and M-07 — the history that does not exist yet

* sealed forward history: **4.159301 h** from 1 sealed run(s)
* hours added since WP-9: 0.0 — the unsealed window is not admissible: no manifest was sealed, so the window cannot be counted toward any pre-registered minimum; counting it would be the synthetic-history substitution the brief forbids

| hypothesis | verdict | met | not met | not measurable | cost to close |
| --- | --- | ---: | ---: | ---: | --- |
| M-03 | NOT_READY | 3 | 2 | 1 | 72.0 h / 13.842 GB |
| M-07 | NOT_READY | 2 | 4 | 0 | 168.0 h / 32.298 GB |

* automatic accumulation: `PREPARED_NOT_AUTHORISED` — authorisation for a window long enough to close the shortfall, and a volume whose budget can pay for it

## 5. Governance, as the state view resolved it

Source `data/recovery/CAMPAIGN_STATE_VIEW.json`, status `CONSISTENT_WITH_ADVISORIES`.

| flag | effective | decided by |
| --- | --- | --- |
| `LIVE_TRADING` | `DISABLED` | data/st6/ST6_HEALTH_STATUS.json |
| `NEXT_CAMPAIGN` | `NOT_AUTHORIZED` | data/st6/ST6_HEALTH_STATUS.json |
| `PAPER_PROMOTION` | `NOT_AUTHORIZED` | data/rfc049/discovery2/CAMPAIGN_CLOSURE.json |
| `SEALED_OOS` | `CANCELLED_NOT_OPENED` | tasks/decisions.md#ADR-0026 |

* advisories: A1_registry_is_stale, A2_next_free_rfc_derived, A3_unresolved_pins, A4_append_only_drift
* derived next free RFC number: `50`

## 6. What these blockers do not block

* offline economic investigations that need no new data: the E-1 measurement ran on already-sealed segments, and any further analysis of the same seal is equally unaffected by the CI, volume and history blockers
* reading and re-verifying existing artefacts

## 7. Checks

* [x] the CI state is measured from the repository, not restated
* [x] no in-lane suspect survives the termination forensics
* [x] the budget verdict is arithmetic on measured numbers
* [x] the unsealed window is explicitly not counted as history
* [x] governance flags come from the state view's resolution

