# ST-6 — time window contract audit

Audit of the declared forward observation period of the ST-6 cost-regime validation and of the
eligible-window denominator, performed against the state on disk at `9660afab9003001d3a8130b9679c066071548421`
(verified `HEAD`, 2026-10-08) and re-measured at `14514d66dbcdd4236a9d18dcbc79c1d90d9a14a1` when the
end-of-period close was replayed. No history was altered, no count was corrected, and the period was
not touched: this document derives the contract and declares what does not match it.

## 1. The declaration

| field | value |
| --- | --- |
| start | `2026-10-08T16:21:20Z` |
| end | `2026-10-22T16:21:20Z` |
| duration | exactly 336 h = 14 natural days |
| slot length | 4 h (`slot_hours = 4`) |
| slots per day | 6 (`slots_per_day = 6`), 00–04, 04–08, 08–12, 12–16, 16–20, 20–24 UTC |
| declared plan | `period_days × slots_per_day = 14 × 6 = 84` |
| one window per slot | `one_window_per_slot: true` (repeated ticks in one slot collect nothing) |
| coverage rule | minima: 10 days, 42 windows, 8 per three-session bucket, 20 weekday, 4 weekend, 6 distinct slots, 2 volatility bands, asset presence ≥ 0.9, rejected fraction ≤ 0.2 |

Source: `data/st6/ST6_PERIOD.json` (immutable declaration; `head_at_declaration = 6b4edd4`).

## 2. Eligible windows derived from the contract (the denominator of 84)

The plan is counted **from the slot that contains the period start**, six slots per day, for the
declared number of days:

* the start `16:21:20Z` falls inside slot `2026-10-08#4` (16:00–20:00 UTC), so that slot is the
  **first** eligible window even though only its last 3 h 38 m 40 s lie inside the period;
* from the first *full* slot after the start (`2026-10-08T20:00Z`) to the end there are 83 complete
  4-hour slots, ending with `2026-10-22#3` (12:00–16:00 UTC), which is therefore the **last**
  eligible window;
* 83 full slots + 1 initial partial slot = **84**, which is exactly the declared plan.

Derived independently in three places, which agree:

| derivation | result |
| --- | --- |
| `scripts/st6_close_replay.py` (its own arithmetic) | 84, first `2026-10-08#4`, last `2026-10-22#3` |
| `scripts/st6_close_verify.py` (its own arithmetic) | 84, first `2026-10-08#4`, last `2026-10-22#3` |
| `scripts/st6_forward_regime.py::declared_slots_upto` (builder) | 84, first `2026-10-08#4`, last `2026-10-22#3` |

`declared_slots_reached` inside the replayed consolidation is 84 at the close instant.

## 3. Inclusion of the two partial intervals

**Initial partial interval (included).** The interval `16:21:20Z–20:00Z` of 2026-10-08 is part of the
first eligible window. It was collected: window `20261008T162202Z`, slot `2026-10-08#4`, at
16:22:02Z, 42 s after the declaration, with raw evidence whose uncompressed sha256 is
`e720f19ded6541b2b292940297d0b317328b0ad1ce1c2589de2ecda5e84da4e7` and which re-hashes to that value
today. So a window is attributed to a slot of which two thirds preceded the declaration; the
attribution is by the slot grid, not by the fraction of the slot inside the period.

**Final partial interval (excluded from the plan).** The interval `16:00Z–16:21:20Z` of 2026-10-22
(21 m 20 s) lies inside slot `2026-10-22#4`, which is **not** one of the 84: the builder's own
docstring for `declared_slots_upto` states that the partial slot the period closes inside is not a
planned window and that "nothing may be expected, missed or penalised there". The denominator of 84
therefore excludes it, and neither the missed accounting nor the coverage arithmetic ever counts it.

## 4. Semantics of the limits

* `period_ended(period, now) = now >= parse(period["ends_at_utc"])` — **inclusive**: at exactly
  `2026-10-22T16:21:20Z` the period is over and the tick closes.
* The ended branch is evaluated **before** any collection statement and returns
  `EXIT_PERIOD_ENDED` (3); the structural check `closure_guard_structure` in
  `scripts/st6_scheduler_verify.py` re-derives that dominance from the syntax tree (PASS).
* A slot is eligible only if it lies within the plan (84 slots from the start's own slot). A slot's
  *end* is not required to precede the period end for the slot to be eligible (the last eligible one
  ends exactly 21 m 20 s before the end); what is required is membership in the plan.
* A window's own timestamp is the instant its evidence closed, and windows are placed by that
  instant's slot, so a window cannot straddle two slots in the index.

## 5. Window count actually observed so far

| window_id | slot | complete | raw uncompressed sha256 | requests | orders | credentials |
| --- | --- | --- | --- | --- | --- | --- |
| `20261008T162202Z` | `2026-10-08#4` | true | `e720f19ded6541b2b292940297d0b317328b0ad1ce1c2589de2ecda5e84da4e7` | 22 | 0 | 0 |
| `20261008T200323Z` | `2026-10-08#5` | true | `1340ee19…1fd3` | 22 | 0 | 0 |

Two windows against a plan of 84: the period is 1 day into 14. The history is consistent with the
declaration — no window sits outside the plan, no slot holds two windows, and both raw snapshots
reproduce the hash recorded in the index.

### The live health artefact does not partition the plan (declared, not patched)

At 2026-10-08T21:48Z the live `ST6_HEALTH_STATUS.json` reported `declared_slots_ended = 1` and
`declared_slots_pending = 82`. The plan is 84, and the two numbers are **not** a partition of it, so a
reader who adds them up is short by one:

* `declared_slots_ended` counts slots whose end has passed — slot `2026-10-08#4`;
* `declared_slots_pending` counts slots that are *unobserved* and still to come — 82;
* the missing term is the slot that is **open right now and already observed**
  (`2026-10-08#5`), which is in neither list.

The arithmetic is not wrong, it is unnamed: the two counters answer different questions ("what has
ended" and "what is left to collect"), and nothing in the artefact says so. The minimal correction is
to name the third term — add `declared_slot_in_progress` (and whether it is observed) so the three
add up to the declared plan — or to rename the counters. It is a reporting ambiguity only: no window,
observation, hash, missed record or denominator is affected, so per the mission's rule it is declared
here and **not** patched while the period is running.

## 6. Findings: contract versus shipped behaviour

Two **forward-looking** mismatches between the declared contract and the shipped tick were measured
in the isolated replay (`data/st6/ST6_CLOSE_REPLAY_REPORT.md`, scenarios 2 and 11). Neither has
altered any collected evidence, and neither was silently repaired: the mission requires the
inconsistency to be declared with a minimal correction while the campaign is left untouched.

### F1 — `BOUNDARY-SLOT-DUE-RULE`

* **Contract**: 84 eligible windows; the partial slot the period closes inside is not one of them.
* **Shipped behaviour (measured)**: the due rule is "this slot has no window yet", which is *not*
  bounded by the plan. A scheduled tick between `2026-10-22T16:00:00Z` and the close would attempt to
  collect a window in `2026-10-22#4`. The replay proves the attempt: at `16:10:00Z` with an
  unobserved slot #4 the tick reaches for the probe (the replay's market guard refuses it, so no
  request was made and no window was fabricated).
* **Consequence**: the campaign could, depending on the tick's timing, end with **85** windows —
  84 declared plus one sampled, complete and hash-recorded window outside the plan. The coverage
  arithmetic would still be satisfied (a 5th window on that day is below the declared maximum of 6),
  but the observed count would exceed the declared denominator without the index saying why.
* **Minimal correction (proposed, not applied)**: bound the due rule by the plan — collect only when
  the current slot's key is in `declared_slots_upto(period, ends_at_utc)`, otherwise record the
  existing `SKIPPED_NO_WINDOW_DUE` token with no market request.
* **Effect on collected evidence if applied**: none — no window, observation or hash changes; it only
  stops one future sample.

### F2 — `EXTENSION-FLAG-INERT`

* **Contract**: the period file declares "after `ends_at_utc` collection stops unless a human passes
  `--authorize-extension`, and that flag never turns an incomplete period into a PASS".
* **Shipped behaviour (measured)**: the ended branch returns before the collection branch, so the
  flag cannot extend the period; and the collection branch is itself gated by
  `not args.authorize_extension`, so passing the flag *during* the open period suppresses collection
  and turns the tick into a report-only rollup. Measured in the replay: during the open period
  `--collect --authorize-extension` collected nothing (0 windows, 0 requests, event `REPORT_ONLY`),
  and at the close instant the flagged tick consolidated and recorded `PERIOD_ENDED_CONSOLIDATED`
  with `auto_extended: false`.
* **Consequence**: the declared policy promises a human extension path that does not exist, and the
  flag has a second, undeclared effect (it disables collection inside the period).
* **Minimal correction (proposed, not applied)**: either honour the flag in a guarded branch
  (`if ended and not args.authorize_extension:` consolidate) or amend the declared text to state
  that the period never extends. The safer behaviour — never extend — is what actually runs.

### F3 — `RUN-LOG-PROVENANCE-IS-DECLARED-MODE` (still open)

* **Contract**: the run log is the campaign's audit trail, so a reader should be able to tell the
  task's own ticks from a human or a verification invocation.
* **Shipped behaviour**: every run event now records the launch mode it declares (`SCHEDULED` for the
  task's command line, `MANUAL` otherwise), but that is a declaration, not an unforgeable origin: the
  fixtures that emulate the task's command line are recorded exactly as the task would be. The 129
  events written before the field existed carry no provenance at all (26 deliberate
  `REFUSED_INVALID_ARGUMENTS`, 24 `ALREADY_RUNNING` and 3 `REPORT_ONLY` of them came from fixtures), so
  the historical log cannot be separated, only labelled as unrecorded.
* **Minimal correction (proposed, not applied)**: have the registered task carry a per-installation
  token in its command line, or reconcile the log against Task Scheduler's own `Last Run Time`.
  Applying it means changing the installed task, which this work does not need in order to prove the
  close.

The three defects below were found while producing this evidence. Each of them made the *evidence*
untrustworthy rather than describing the campaign, so each is **fixed** in `14514d6`, with a unit test
that fails against the old behaviour:

### F4 — `FIXTURE-REFUSALS-TRIPPED-THE-LIVE-MONITOR` (fixed)

The health monitor computed its failure streak (critical at 3) and its 45-minute liveness heartbeat
over *every* run event, including the fixtures. Measured before the fix: `consecutive_failures = 2`
of 3 at 21:48Z — one more verification refusal and the live monitor would have raised a false
`CRITICAL` — and the heartbeat was refreshed by manual runs, so a stopped schedule could have looked
alive. The streak and the heartbeat are now derived from the non-manual events only, deliberately
still counting the unrecorded historical rows, because dropping them could hide a real failure. Live
reading after the fix: streak 1, `heartbeat_basis = LAST_NON_MANUAL_RUN`.

### F5 — `SNAPSHOT-CHECK-CONFLATED-DRIFT-WITH-CORRUPTION` (fixed)

`--check` compared each live file with the hash recorded when the snapshot was taken, so it failed as
soon as the tick rewrote its own state — five live files had already moved by 22:00Z. The check now
answers two questions apart: the snapshot's own bytes, its copied files and the raw evidence as
*integrity* (a failure when wrong), and the campaign moving on as *drift* (named, hashed, counted, not
a failure). New negative test: a tampered copy fails, a missing copy fails, a foreign manifest is
refused before anything is believed, and a moved live file passes as drift.

### F7 — `ARTEFACT-BYTES-DEPENDED-ON-THE-PLATFORM` (fixed)

The artefacts written by the new programs were produced through a Windows text-mode write, so they
carried CRLF while git stores LF, and the sha256 recorded for them did not describe the bytes that
ship. The acceptance check found it by re-hashing every recorded digest against the committed blob:
`3 recorded hashes did not reproduce`. The writers now open with `newline="\n"`, which matters here
more than anywhere else in this phase — the denominator audit, the replay report and the consolidation
are all quoted by hash, and a hash that only reproduces on the machine that wrote it proves nothing.

Related, and worth recording as evidence that the verification is not decorative: when three programs
were edited after `ST6_LIVE_STATE_20261008T221134Z` had been taken, the independent verifier **failed**
(`the implementation file scripts/st6_state_snapshot.py changed after the snapshot`, 18/19,
FALSE_SUCCESS 1). The snapshot was retaken once the code had stopped moving and the same verification
then passed 19/19.

### F6 — `LIVE-TESTS-RACED-THE-SCHEDULER` (fixed)

Three live tests asserted on the tick's outcome while the 15-minute task held the shared lease, so
they failed with `ALREADY_RUNNING` whenever the scheduler was mid-collection (observed at 22:03Z:
3 failed; the identical suite passed 24/24 at 22:08Z). They now wait for a free lease with a bounded
and loud timeout; a lease that never frees is a failure, not a skip.

## 7. What this audit does **not** claim

* It does not claim 84 windows of *continuous* coverage: each eligible window is a bounded
  three-round sample (about two minutes) taken by the first tick after the slot opens, so a
  "covered" slot means one independent sample inside it, not four hours of observation.
* It does not alter the denominator, the declaration or any collected byte to reach a PASS.
* It does not close the period or extend it: the period closes on its own date, at
  `2026-10-22T16:21:20Z`, by the tick's own guard.

Research only: no orders, no credentials, no capital.
