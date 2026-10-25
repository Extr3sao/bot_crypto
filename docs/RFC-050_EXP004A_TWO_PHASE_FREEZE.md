# RFC-050 — Two-phase preregistration, and prospective admission as a numbered count

**Status:** IMPLEMENTED (mechanism) · **Experiment it prepares:** `EXP-004A` — `PROPOSED, NOT AUTHORISED`
**Date:** 2026-10-21 · **Code:** `src/trading_bot/research/prereg_gate.py`,
`src/trading_bot/research/prospective/`, `src/trading_bot/research/execution_cost/`

## 1. The two problems this settles

**P1 — a preregistration frozen before its data exists cannot pass the gate.** `prereg_gate` requires a
sha256 for every dataset. That is correct and must not be relaxed: the digest is what ties a protocol to
the bytes it was measured on. But a prospective experiment has no bytes at freeze time, so the only
routes were to freeze late (after the data had been seen) or to weaken the check for everybody. Both are
worse than the problem.

**P2 — a day count is not an observation count.** `data/forward/edge04/coverage.json` reports 235 days,
229 of which arrived in bulk after their close. The figure is arithmetically correct and evidentially
inert. A count that lives in a derived file regenerated on every observer tick cannot be quoted as
evidence of what was true when it was quoted.

## 2. Decision — the freeze is split, the address of the data is not

| Phase | Status | Contains | Gate result |
| --- | --- | --- | --- |
| 1 | `PROTOCOL_FROZEN` | question, splits, economics, acceptance, decision rule, and the *paths* the captures will occupy. Digests `null`, each dataset carrying `digest_deferred_by: TWO_PHASE_PHASE_1` | **`inspect` → exit 3** (`INSPECTION_ONLY_NO_RUN`); **`authorize` → exit 2** (`TWO_PHASE_PHASE_1_IS_NOT_AUTHORISABLE`) |
| 2 | `REGISTRY_FROZEN` | the same manifest plus every digest, committed after the capture closed | may reach exit 0 |

What makes phase 1 more than a promise is that the gate checks it against git, not against the manifest's
own claims:

- the manifest's **last commit time must be earlier than `capture.start_utc`** — a protocol written after
  the data arrived is refused with `PROTOCOL_FROZEN_AFTER_CAPTURE_STARTED`;
- **no declared dataset file may exist** during phase 1 (`DATASET_PRESENT_BEFORE_FREEZE`), because a path
  that already holds bytes means somebody looked before the protocol was frozen;
- `reproduction_status` may be `PENDING_CAPTURE` in phase 1 and **never** in phase 2.

And phase 2 cannot be reached early:

- `phase1_commit` must be a 40-hex ancestor of `HEAD` whose own commit time precedes `capture.start_utc`;
- `capture.closed` must be true **and** the registry's last commit time must be at or after
  `capture.end_utc` (`DIGESTS_FROZEN_BEFORE_CAPTURE_CLOSED`);
- every dataset must satisfy `period_start_utc >= capture.start_utc` and `period_end_utc <= capture.end_utc`
  (`DATASET_PREDATES_CAPTURE`, `DATASET_AFTER_CAPTURE_CLOSE`), so a file cannot be slipped in from before the
  window or extended past the close.

A timing that cannot be verified is not a timing: in `authorize` mode, an untracked registry or an
unreadable commit clock is `TWO_PHASE_TIMING_UNVERIFIABLE`, not a check.

## 3. Decision — `PROSPECTIVELY_OBSERVED` is a claim about the lag, and it is sealed

A day is admissible only if (`admission.classify_day`):

1. every declared series holds **≥ 90 %** of the bars the UTC calendar expects for it, and
2. every one of those bars satisfies `0 ≤ fetched_at_ms − (ts + interval) ≤ lag_bound`.

Two failure classes are kept apart on purpose: `DENSE_BUT_BACKFILLED` (bars exist, arrived late — history)
and `INCOMPLETE` (bars absent). A single "coverage" number cannot distinguish them, which is exactly how
229 backfilled days passed as a corpus.

Days are sealed by `AttestationLedger` into an append-only JSONL chain. Each record names, per series, the
**byte prefix** (`byte_end`, sha256) it was computed from, so appending tomorrow's bars leaves yesterday's
attestation valid while rewriting yesterday's bytes breaks it (`SERIES_REWRITTEN`). The chain link is
verified against the *recomputed* digest, so editing a record also breaks its successor's back-link.

A day is never sealed before it is settled: `sealable_through(now, lag_bounds)` returns
`now − max(lag + interval) − 1 day`, so a day whose bars could still legitimately arrive is `PENDING` and
counted neither way. Sealing early is how a backfill would be promoted.

## 4. Decision — the epoch is per series, and the intersection is the number that matters

A 1h lane reaching back to 2026-03-01 and a 15m lane starting 2026-10-07 do not share 235 days of evidence;
they share 15. `intersection_epoch` takes the maximum over declared series, and the runner reports the three
lanes separately rather than choosing the flattering one.

## 5. Decision — cost is measured with a knowledge class per component

`execution_cost` adds no pricing arithmetic: the fee comes from `VENUE_SPECS` (`KNOWN`), the spread is the
median of the recorded `bid`/`ask` (`OBSERVED`), and the depth walk is `OBSERVED` only when the tape walked
the declared notional. A total takes the **weakest** component's class, and a size nobody walked returns
`DECLARED_SIZE_NOT_WALKED` with a lower bound rather than a scaled number.

## 6. Decision — observations are counted per day, not per experiment

`ObservationBook` keys evidence on `(calendar day, bytes digest)`. `EXP-003J` and `EXP-003K` resolve to one
window because they measured the same 175 OOS trades; a sixth report over the same days adds nothing.

## 7. Consequences

- `EXP-004A`'s phase-1 manifest is committed at `config/preregistrations/EXP-004A.json` and is **refused**
  by the gate it was written for. That refusal is the mechanism working.
- Phase 2 cannot be authored by the builder of the measurement: `builder_identity !=
  independent_verifier_identity` is enforced separately.
- Nothing here authorises a strategy, a paper run, a promotion or live trading. `economic_executions: 0`.

## 8. Rejected alternatives

| Alternative | Why not |
| --- | --- |
| Allow `null` digests for everyone | it is the holdout-leak mechanism, restored for convenience |
| Freeze the protocol and the digests together after capture | the protocol then describes data already seen |
| Count days from `coverage.json` | a derived file cannot be evidence of its own past |
| Scale 200 USDT impact to 500 USDT | depth is not linear; the number would be invented |
| Add a second collector for the 90-day window | the WP-EDGE-03 observer already records per-bar ingest time; a second pipeline is a second truth |
