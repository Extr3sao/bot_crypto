# WP-EDGE-04R — what the forward observer lost, and what each loss was

**Reading instant:** 2026-10-15T18:31:46Z · **Window:** 2026-10-13T11:23:38Z → 2026-10-15T18:31:46Z (55.136 h)
**Schedule:** every 900 s, phase +656 s, measured from the launches the host actually made.

Every figure below is re-derivable offline from `evidence/` alone:

```bash
python scripts/edge04r_continuity.py --offline --stored-snapshot --until 2026-10-15T18:31:46Z
python scripts/edge04r_verify.py --reports reports/edge-recovery/WP-EDGE-04R --repo . --self-test
```

## 1. Publish the five local commits

The lane's commits were local because the earlier probe had been answered without a
credential. The probe was re-taken: GitHub accepted a fast-forward of the lane's own
branch, and only the five commits this work package owns were pushed.

| | |
| --- | --- |
| Remote branch | `refs/heads/agent/edge-recovery/WP-EDGE-00-baseline` |
| Before | `26eeea4` (the parent of the first commit of the set) |
| After | `5980e37` (identical to local HEAD at the time) |
| Method | fast-forward; **no force push**; no other branch touched |

## 2. Why the schedule lost triggers, one cause at a time

WP-EDGE-04 reported the count — 74 of 96 triggers in a 24 h window — and could not say
what the missing ones were, because the host's own trigger history is not readable on
this machine. This work package places **every trigger the schedule should have fired**
on a timeline and asks the host's record which state it was in at that instant.

| | instants |
| --- | --- |
| Expected | 221 |
| Answered by a tick | 195 |
| — of which consumed their slot | 152 |
| — of which fired and were refused | 43 |
| Never answered by any process | 26 |
| **Total lost** | **69** |

| Cause of a trigger that no process answered | instants | evidence |
| --- | --- | --- |
| `NO_SESSION` | **24** | one 22 876.438 s (6.355 h) window between a logoff at 22:29:37Z and a sign-in at 04:50:54Z |
| `HOST_DOWN` | 1 | two reboots, 458.525 s of downtime |
| `SILENT_UNATTRIBUTABLE` | 1 | host up, session present, no tick and no host-side record |
| `SLEEP` | **0** | 0 sleep/resume pairs recorded |

### The local hypothesis this audit refutes

WP-EDGE-04 attributed the lost triggers to "a machine that sleeps". The host records **no
sleep and no standby in the window**: 29 Kernel-Power events, none of them a 42/107 pair,
and the Power-Troubleshooter log is empty. What the host does record is a logoff, two
reboot cycles and a sign-in six hours later. The cause is not the machine going to sleep;
it is that **nobody was signed in**, and the task is registered
`LogonType=InteractiveToken`, so a trigger that fires with no session produces no process
and — this is the part that made the loss invisible — no record either.

`AutoAdminLogon` is `0` on this host, so a reboot does not re-create the session: the
machine sits at the sign-in screen until a person signs in.

### The two causes that are not scheduling problems

* **Disk pressure: 43 triggers fired and were refused.** Not a missed trigger — the
  storage guard refused *before* any market request, so each cost a market call and a
  slot, never a false observation. Free space fell to **0.8302 GiB**, with **10.764 h**
  below the 2 GiB critical floor and **6.49 h** below the 5 GiB warning floor.
* **Long execution: ruled out.** Median tick 34.64 s, maximum 349.035 s, **zero** ticks
  over the 900 s interval. A tick cannot eat its successor's trigger at this duration.

## 3. Availability, and the ceiling it puts on observation

| | |
| --- | --- |
| Schedulable fraction (host up **and** a session present) | **0.8824** |
| Host up, no session | 6.355 h |
| Host down | 0.127 h |
| Recovery latency after the one sign-in | **321.41 s** |
| Silences over the 2× interval + 300 s bound | 1 (23 418.872 s, 25 missed triggers) |

The schedulable fraction is the ceiling, not a nuisance: it is the fraction of the window
in which this task could start at all.

## 4. Storage: is there anywhere better to put the store?

The lane's tree is **12 368 125 B of a declared 268 435 456 B budget** — it is not what is
filling the volume. The estate on this host:

| volume | filesystem | free | used | usable for relocation? |
| --- | --- | --- | --- | --- |
| `C:` | NTFS | 7.07 GiB | 97.03 % | no — the volume the lane already lives on |
| `G:` (Google Drive) | FAT32 | 6.71 GiB | — | no — not NTFS, and a cloud mount that reports the host's own capacity while holding none of it |
| (unmounted) | NTFS | 0.05 GiB | — | no — not mounted |
| (unmounted) | FAT32 | 0.01 GiB | — | no — not mounted, not NTFS |

One physical disk (KXIA NVMe SSD, 238.47 GiB), one data partition, 97 % full. **Verdict:
`NO_VOLUME_WITH_CAPACITY`.** Moving the store would not change the free space the guard
reads, and no other workstream's tree was moved to make room.

## 5. Session independence: what this host actually allows

Each mechanism was *attempted*; the verdict is what the host answered, not what the
documentation says. Full receipts in `evidence/SESSION_INDEPENDENCE.json`.

| mechanism | verdict | what it needs |
| --- | --- | --- |
| `SESSION_LOGON_TRIGGER` | **VIABLE** | registered on a throwaway task, read back carrying `MSFT_TaskLogonTrigger` (Delay PT1M) beside `MSFT_TaskTimeTrigger`, run on demand, deleted |
| `WITNESS_ACTION` | **VIABLE** | a first action that always writes its line before the long action; proved by running the probe |
| `S4U_TASK` | `NEEDS_ELEVATION` | the attempt did not complete non-interactively; S4U needs the batch-logon right |
| `WINDOWS_SERVICE` | `NEEDS_ELEVATION` | creating a service needs administrator rights |
| `AUTOMATIC_LOGON` | `NEEDS_CREDENTIALS` | would require storing the account password on the machine |
| `TASK_SCHEDULER_OPERATIONAL_LOG` | `NEEDS_ELEVATION` | the enable attempt was refused: *Acceso denegado* |
| `WAKE_TO_RUN` | `NOT_APPLICABLE` | no sleep or standby was recorded, so there is nothing to wake for |

**Nothing was applied to the live task.** Re-registering a running lane's task changes the
phase this audit measures and is a deployment decision for an operator; the probes used a
throwaway name and were deleted, leaving exactly one scheduled task on the machine.

What each available mechanism would buy, priced from the audit rather than guessed:

* the **logon trigger** bounds recovery from a sign-in to about a minute instead of up to a
  quarter of an hour — measured recovery was 321.41 s, so it recovers minutes;
* the **witness action** turns the 1 unattributable trigger into an attributable one,
  without needing an administrator;
* **S4U** is the only mechanism that would make the 24 triggers lost to an absent session
  scheduleable at all, and it is exactly the one this package cannot register.

## 6. The stale economic certificate

`data/recovery/wp7/COST_BARRIER_CERTIFICATION.json` pins
`data/recovery/ACTIVE_ECONOMIC_AUDIT.json` at `8a101e88…`. HEAD's content digests to
`d1d49f09…`, and the adversarial test that compares them fails.

| | |
| --- | --- |
| Certificate's commit | `57772ef` (2026-10-11) |
| Digest of that artefact **at that commit** | `8a101e88…` — matches the record |
| Commit that re-rendered the artefact | `7522255` (2026-10-12, `[WP-EDGE-01]`) |
| Digest at HEAD | `d1d49f09…` |
| Leaf values that changed, of 2 985 | **6** |
| Of those, economic values | **0** |

The regeneration changed the branch, the commit it was rendered at, and one live
observation (`data/st6/ST6_HEALTH_STATUS.json`, 6 143 → 6 290 bytes, same attested fields:
`HEALTHY`, `NEXT_CAMPAIGN=NOT_AUTHORIZED`, `LIVE_TRADING=DISABLED`). The economic
aggregates did not move.

**Verdict: `STALE_BY_PROVENANCE` — declared, not silenced.** The record was correct when
it was written; its input was re-rendered one day later by the lane that owns it. Editing
the recorded digest so the test passes would replace evidence with an assertion nobody
can trace to a commit, which is the one thing this work package was told not to do.

## 7. What was checked, and what could not be

| check | verdict |
| --- | --- |
| Audit's own 8 checks (reconciliation, attribution, sleep refutation, invariants) | **8/8 PASS** |
| Independent verifier, no code shared with the audit | **11/11 PASS** |
| Sabotage matrix on the verifier | **see `VERIFICATION.json`** |
| `tests/unit/research/test_edge04r_continuity.py` | **26 PASS** |
| Wider research suite | see §8 of `FINAL_REPORT.md` |
| A logon or a reboot during this pass | **NOT_EXERCISED** — logging off would end the session this work runs in |
| An S4U task actually running without a session | **BLOCKED** — needs the batch-logon right |
| Enabling the Task Scheduler operational log | **BLOCKED** — needs administrator rights |
| Linux | **NOT_EXERCISED** — portable by construction, unexercised in fact |

Research only: hypothetical marks, `order_sent: false`, promotion `NONE` in every record.
