# WP-EDGE-04R — what the forward observer lost, and what each loss was

**Reading instant:** 2026-10-15T18:31:46Z · **Window:** 2026-10-13T11:23:38Z → 2026-10-15T18:31:46Z (55.136 h)
**Schedule:** every 900 s, phase +656 s, measured from the launches the host actually made.

Every figure below is re-derivable offline from `evidence/` alone, and the check is a
comparison rather than a reading:

```bash
python scripts/edge04r_continuity.py --offline --reports reports/edge-recovery/WP-EDGE-04R --until 2026-10-15T18:31:46Z
python scripts/edge04r_verify.py --reports reports/edge-recovery/WP-EDGE-04R --repo . --self-test
```

**Measured, not asserted:** from a different working directory, with a relative `--reports`,
that command re-derives `evidence/EDGE04R_CONTINUITY_AUDIT.json` to
`sha256 5e053a7de5024d12207c451325b2fc44761fc2881b1be3c7805b6341bba5f37c` — the same bytes as
the committed record. `--offline` now implies `--stored-snapshot`: it reads the committed
tick snapshot, does not read the lane, and does not rewrite the snapshot it is checking.
An offline run with no `--until` reads the instant back from the record it is re-deriving.

## 1. Publish the local commits

The lane's commits were local because the earlier probe had been answered without a
credential. The probe was re-taken: GitHub accepted a fast-forward of the lane's own
branch, and only the commits this work package owns were pushed.

| | |
| --- | --- |
| Remote branch | `refs/heads/agent/edge-recovery/WP-EDGE-00-baseline` |
| Already on the remote before this pass | `5980e37` (the record of the previous pass) |
| After | `04bf155` — the read-back equals local HEAD |
| Commits pushed | `98d594e`, `40b3665`, `b892273`, `5daa3c0`, `e6a9df8`, `04bf155` |
| Method | fast-forward; **no force push**; no other branch touched |
| Read back from the remote after the push | `git ls-remote`, not the push command's own output |

The four commits the previous pass left local (`98d594e`, `40b3665`, `b892273`, `5daa3c0`)
and this pass's commits go out together as one fast-forward. The push is probed from the
remote afterwards, and the read-back — not the command's own output — is what the record
states.

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

### The host's own counter disagrees with the lane, and loses

The registered task reports `NumberOfMissedRuns: 0` for the whole window — the same
window in which 26 triggers produced no process. Its `LastTaskResult` is `0` and its state
is `Ready`. Neither number is wrong on the host's terms, and both are useless as evidence:
the counter does not count a trigger whose task could not start, and the operational log
that would have said so is **disabled** (`RecordCount: 0`). That is why this audit reads
the session and power records rather than the scheduler's own summary, and why
"the task is Ready with no missed runs" is not a statement about continuity.

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

## 4b. The definition this package would apply, and what the rehearsal found

`evidence/PROPOSED_FORWARD_TASK.xml` is the lane's own registration **plus two additions**,
rendered from the frozen host evidence (so the definition has no "now" in it and the
same inputs re-render the same bytes): a `LogonTrigger` with a 60 s delay, and a witness
`Exec` ahead of the lane's action. Everything else — the quarter-hourly `TimeTrigger` and
its original `StartBoundary` (the cadence phase the audit measured), the principal
(`InteractiveToken`, `LeastPrivilege`), `WakeToRun=false`, the 1 h time limit, the
`IgnoreNew` policy, the restart policy and the lane's own action with its working
directory — is carried over as the registration has it.

The rehearsal registered the committed definition, read it back from the scheduler, ran it
and deleted it:

| rehearsal | measured |
| --- | --- |
| verdict | `VIABLE` |
| trigger kinds the scheduler reported back | `MSFT_TaskLogonTrigger`, `MSFT_TaskTimeTrigger` |
| actions, in the order they run | 2 — witness first |
| witness line written | yes (`evidence/forward-witness.txt`, committed) |
| task deleted after the rehearsal | yes; 0 probe tasks left on the host |
| lines the rehearsal moved from the committed definition | **2** — the action payload |

The two lines are the lane's action, replaced for the rehearsal by `cmd.exe /c exit 0`:
running the lane's own action there would let a rehearsal write an out-of-phase tick into
the ledger this audit measures. That the difference is two lines is measured by the probe,
not claimed. Applying the definition is the operator's call, and it re-registers the live
task in place, which is why this package rehearses it instead of doing it:

```bash
schtasks /create /tn "TradingAgentic-EDGE04-Forward" /xml "reports/edge-recovery/WP-EDGE-04R/evidence/PROPOSED_FORWARD_TASK.xml" /f
```

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
| Independent verifier, no code shared with the audit | **16/16 PASS** |
| Sabotage matrix on the verifier | **12/12 detected** (`SELF_TEST_PASS`) |
| The committed definition carries the registration it claims | **PASS** — new check, and it fails on a flipped `WakeToRun` whose digest is kept consistent |
| Offline reproduction of the audit, from another working directory | **byte-exact**, `5e053a7d…` |
| `tests/unit/research/test_edge04r_continuity.py` | **33 PASS** |
| `tests/unit/research/test_edge04_autonomous.py` | **49 PASS** |
| Wider research suite | see §8 of `FINAL_REPORT.md` |
| A logon or a reboot during this pass | **NOT_EXERCISED** — logging off would end the session this work runs in |
| An S4U task actually running without a session | **BLOCKED** — needs the batch-logon right |
| Enabling the Task Scheduler operational log | **BLOCKED** — needs administrator rights |
| Linux | **NOT_EXERCISED** — portable by construction, unexercised in fact |

## 8. Defects this pass found and closed

Each of these was found by trying to *check* the previous pass's work rather than by
re-reading it, and each one had made a claim in this package read differently from what it
was measured to be.

| # | defect | how it showed up | closed by |
| --- | --- | --- | --- |
| `DEF-EDGE04R-1` | the witness probe resolved its scratch path against the caller's **working directory**, while the scheduled task it registers runs in the repository root | the probe reported `WITNESS_ACTION FAILED` when the reading was taken from another directory, and `VIABLE` when it was not | every declared path is anchored on `REPO_ROOT`; the verdict is now a property of the repository, not of where the command was typed |
| `DEF-EDGE04R-2` | the published way to check this reading **could not reproduce it**: no declared instant (the window ended at whatever time the reader ran the command) and an offline run re-copied the live lane over the frozen snapshot before auditing it | the re-derivation returned 228 instants where the record says 221, and rewrote the snapshot it was supposed to be checking | `--offline` reads the committed snapshot and never the lane; an offline run with no `--until` reads the instant back from the record; the command is rendered from the audit's own window |
| `DEF-EDGE04R-3` | the audit's own key for the trigger count is `expected`, and the probes asked for `expected_instants`; the fallback printed an unnumbered sentence, while a **hardcoded `220`** in two probes disagreed with the audit's `221` | the session record said "one of the 220 instants" beside an audit that counted 221 | the count is read from the audit in one place and quoted everywhere else; no figure is typed into a sentence |
| `DEF-EDGE04R-4` | the scheduler reports `WakeToRun` as the **string** `"False"`, and `bool("False")` is `True` | writing the check that the definition carries the registration caught the proposal flipping a setting while describing itself as carrying it over | settings that arrive as strings are parsed as booleans, and the verifier now compares the definition against the frozen registration element by element |

The verifier was hardened with the check that found `DEF-EDGE04R-4`, and the sabotage matrix
grew with it: flipping a carried setting **while moving the recorded digest with it** is
caught by the substance comparison, not by the digest comparison, which is the difference
between a check that can fail and a check that was never load-bearing.

## 9. What is still open

* **The stale economic certificate.** `STALE_BY_PROVENANCE`, declared and not silenced:
  re-issuing it belongs to the work package that owns the certificate, and editing the
  recorded digest to make the test pass was explicitly not done.
* **The three mechanisms that need an operator.** S4U (the batch-logon right), the Task
  Scheduler operational log and a service all need administrator rights or a credential
  this package does not hold and will not acquire. The commands that would grant each are
  in `SESSION_INDEPENDENCE.md`.
* **The definition itself is a proposal, not a deployment.** It is committed, rehearsed and
  ready to apply; whether to re-register a running lane (which moves the phase this audit
  measures) is a decision for the operator.
* **A logon or a reboot during a pass is still not exercised** — logging off would end the
  session the work runs in — so the logon trigger's recovery is bounded by construction and
  by the probe's read-back, not by a measured absence.
* **Linux is unexercised.** The reading is portable by construction; it has not been run
  there.

Research only: hypothetical marks, `order_sent: false`, promotion `NONE` in every record.
