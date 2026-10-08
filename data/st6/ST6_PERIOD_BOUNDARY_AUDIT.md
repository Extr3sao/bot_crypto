# ST-6 — time window contract audit

Audit of the declared forward observation period of the ST-6 cost-regime validation and of the
eligible-window denominator, performed against the state on disk at `9660afab9003001d3a8130b9679c066071548421`
(verified `HEAD`, 2026-10-08). No history was altered, no count was corrected, and the period was not
touched: this document derives the contract and declares what does not match it.

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

## 7. What this audit does **not** claim

* It does not claim 84 windows of *continuous* coverage: each eligible window is a bounded
  three-round sample (about two minutes) taken by the first tick after the slot opens, so a
  "covered" slot means one independent sample inside it, not four hours of observation.
* It does not alter the denominator, the declaration or any collected byte to reach a PASS.
* It does not close the period or extend it: the period closes on its own date, at
  `2026-10-22T16:21:20Z`, by the tick's own guard.

Research only: no orders, no credentials, no capital.
