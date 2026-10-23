# WP-051-02G — final report

**Phase:** EXP-004A, phase 3 (incremental prospective acquisition) · **Work package:** WP-051-02G ·
**RFC:** `CODEX — WP-051-02G` · **Date:** 2026-10-22

> The mechanism works on real bytes: nine write-once shards, three assets, three closed days, 216
> bars, verified by a program that does not import the builder. The window it was built for opens
> at `2026-10-23T00:00:00Z` — after this session — so the phase's own coverage is
> `PENDING_WINDOW_OPEN` and must stay that way until ninety days of forward bars exist. A complete
> rehearsal is not evidence about a window that has not begun, and this report does not pretend
> otherwise.

---

## 1. The headline

| Field | Value |
|---|---|
| `IMPLEMENTATION_STATUS` | **PASS** |
| `TEST_STATUS` (02G suite) | **PASS** — 49 passed, 0 failed (`2026-10-23` re-run: `49 passed in 38.78s`, exit 0) |
| `TEST_STATUS` (`tests/unit/research`) | see §7 — 1 module cannot be collected at HEAD, plus pre-existing failures across modules this package does not touch |
| `RUNTIME_CAPTURE_STATUS` (rehearsal) | **CAPTURED_VERIFIED** — 9 shards, 216/216 bars |
| `INDEPENDENT_VERIFICATION` (rehearsal) | **PASS** — `PASS_COVERAGE_COMPLETE`, 19 checks, 0 failed, reproduced byte for byte on `2026-10-23` |
| `INDEPENDENT_VERIFICATION` (phase, pre-open claim `a2bce8a6`) | **PASS** — `PASS_PENDING_WINDOW_OPEN`, 20 checks, 0 failed, reproducible only with the clock pinned (§5) |
| `INDEPENDENT_VERIFICATION` (phase, post-open attempt `7fe919f5`) | **PASS** — `PASS_COVERAGE_INCOMPLETE`, 20 checks, 0 failed, exit 3 |
| `COVERAGE_STATUS` (rehearsal) | **`COVERAGE_COMPLETE`** — for the rehearsal's own 216-bar denominator |
| `COVERAGE_STATUS` (phase window) | **`PENDING`** — 0 of 6480 bars; the window opened at `2026-10-23T00:00:00Z` and the first day closes at `2026-10-24T00:00:00Z` |
| `CERTIFICATION_ALLOWED` | **NO** — `certification_blocked_by: REHEARSAL_IS_NOT_EVIDENCE` for the rehearsal, `COVERAGE_PENDING` for the phase |
| `PAPER_VALIDATION` | **NOT_ATTEMPTED** |
| `PROMOTION` | **NO_PROMOTION** |
| `FALSE_SUCCESS` | **0** |
| `OPERATIONAL_BLOCKER` | **`DEF-02G-10`** — the forward observer is stale (last bar `2026-10-22T18:00Z`); the phase cannot accumulate admissible bars until it resumes |
| **Overall** | **PARTIAL** — the mechanism is delivered and verified on real data; the window's coverage is by construction not yet earned |

`CAPTURE_VERIFIED` and `COVERAGE_COMPLETE` are two different sentences and this package keeps them
apart. The first says the bytes are internally consistent with their manifests; the second says
every bar the declaration asked for is present and admissible. Only the rehearsal satisfies both,
and only because a rehearsal has its own denominator.

---

## 2. What the audit found before anything was built

Three facts decided the design.

1. **The phase-2 extractor cannot be extended.** It selects a whole window at once, ignores
   `coverage_required`, and refuses to rewrite its target, so `DEF-02F-01` froze
   `data/exp004a/EXP-004A-1H-{BTC,ETH,SOL}.jsonl` at 14 of 2160 declared bars for ever. No amount
   of re-running fixes that, and deleting them to retry would be the "clean the artefacts until you
   get a PASS" move the freeze forbids.
2. **A prospective window must open after its declaration is committed.** That is a Git fact, not
   a field. The phase-2 window opened at `2026-10-22T00:00:00Z`, so every bar a phase-2 dataset
   could contain was fetched after the declaration existed — but a *new* mechanism declared today
   can only claim a window that has not started yet. The phase-3 window therefore opens at
   `2026-10-23T00:00:00Z`, 90 days and 2160 hourly bars per asset.
3. **The live forward store contains days the lag policy must reject.** Measured on
   `data/forward/edge03/1h/BTC.jsonl` (5659 bars, last open `2026-10-22T18:00Z`):

   | Day | Bars | Max lag | Bars over the 2h bound |
   |---|---|---|---|
   | 2026-10-05 … 2026-10-11 | 24 each | 4239–11439 min | 24 each |
   | 2026-10-12 | 24 | 1360 min | 22 |
   | 2026-10-13 | 24 | 461 min | 10 |
   | 2026-10-14 | 24 | 356 min | 5 |
   | 2026-10-15 | 24 | 236 min | 2 |
   | 2026-10-16 | 24 | 11 min | 0 |
   | 2026-10-17 | 24 | 131 min | 1 |
   | 2026-10-18 | 24 | 476 min | 8 |
   | 2026-10-19 | 24 | 116 min | 0 |
   | 2026-10-20 | 24 | 41 min | 0 |
   | 2026-10-21 | 24 | 87 min | 0 |

   Those lags are the difference between a bar that was watched and a bar that was backfilled. The
   rehearsal window was placed on `2026-10-19 … 2026-10-21` — the three fully closed days the policy
   accepts — and the days it rejects are reported above instead of being captured and called clean.
   The rejection path itself is proved by the adversarial suite, not by those days.

---

## 3. What was built

Four new files. Nothing in `wp051_02b`..`wp051_02f`, the phase-2 declaration, the frozen
extractor or the economic runtime was modified; the verifier re-hashes 93 paths of those packages
against `HEAD` on every run and reports `FROZEN_PACKAGES_INTACT`.

| File | What it is |
|---|---|
| `config/preregistrations/EXP-004A.datasets.phase3.json` | the immutable acquisition contract: window, assets, timeframes, 2160 rows per slice, the lag policy, the shard rule, the coverage denominator, and the rehearsal window (disjoint from the phase window, `counts_toward_coverage: false`) |
| `src/trading_bot/research/prospective/incremental.py` | the engine: grid derivation, plan, atomic write-once shards, deterministic consolidation, coverage arithmetic. Pure functions; the caller injects paths and the clock |
| `scripts/exp004a_wp051_02g_capture.py` | the builder: `--once`, `--check`, `--resume`, `--schedule`, `--consolidate`, `--summary`, `--seal`, `--rehearsal`, `--as-of` |
| `scripts/exp004a_wp051_02g_verify.py` | the independent verifier: its own declaration parser, its own store reader, its own coverage arithmetic; imports neither the builder, the engine nor `trading_bot` |
| `tests/unit/research/test_exp004a_wp051_02g.py` | 49 tests, the adversarial suite of §6 |

### The design decisions a reviewer should check

* **A shard is a UTC day, and it exists only when its manifest does.** The payload is written and
  fsynced to `.part`, then the manifest, then both are renamed, payload first. A crash leaves
  nothing, or a `.part` that `--resume` names and removes — never a shard whose manifest describes
  other bytes.
* **A day is captured only after its last expected bar closed.** Publishing a day at noon would
  create a shard that a later tick must either extend (a rewrite) or abandon.
* **Admissibility is decided per day from the lag, and it is written down.** A day holding a late,
  negative-lag, unclosed or future bar is stored — the bytes are real — marked `admissible: false`
  with the individual defects, excluded from the consolidated dataset and from the numerator. The
  builder repairs nothing.
* **The denominator is the declaration's, never the data's.** `admissible_rows / declared_rows`,
  with `declared_rows` fixed at 2160 per slice. `coverage_required: 0.9` is a floor for
  adjudication: `COVERAGE_COMPLETE` requires **equality**, so a 90 %-complete dataset is
  `BELOW_DECLARED` and can never be certified as the declared one.
* **A rehearsal is structurally unable to leak.** It has its own shard root, its own scheduler
  watermark, `prospective: false` and `counts_toward_coverage: false` in every manifest, and the
  declaration refuses a rehearsal window that overlaps the capture window. The verifier checks
  disjointness itself.
* **A repetition is a no-op by construction.** An existing shard is compared, never rewritten:
  identical bytes are reported `ALREADY_HELD`, different bytes are a conflict that blocks the run,
  and a `.part` left by an interruption is the only thing `--resume` removes.
* **The verifier duplicates rather than shares.** It parses the declaration, walks the store's
  bytes and computes coverage on its own; a control fails if its import graph ever reaches the
  builder. It also re-derives admissibility instead of reading the manifest's `admissible` flag,
  and fails when the two disagree (`QUARANTINE_IS_DISCLOSED`).

### Commits

| Commit | What it carries |
|---|---|
| `889abf30` | engine, builder, verifier, 49-test suite; `ruff` and `mypy --strict` clean |
| `937a55c3` | the phase-3 declaration, naming `889abf30` and the blob digests of the three programs |
| *(this package's evidence commit)* | the shards, the consolidated datasets, the run evidence, the seal and this report — `git log -1 -- docs/agentic/exp004a/wp051_02g/FINAL_REPORT.md` |

The commit that carries this file cannot name itself, for the reason 02F gave: writing its id into
the file changes the file. The declaration's `DECLARATION_COMMIT_PRECEDES_WINDOW` control resolves
`937a55c3` to `2026-10-22T22:10:29Z`, which is 1 h 49 min before the window opens at
`2026-10-23T00:00:00Z`.

---

## 4. Real execution

Four attempts, four directories, no attempt overwriting another. The evidence directories are the
attempts; `RUN_REPORT.json` in each names its own `run_id`.

| Run | Mode | UTC | State | Shards | What it proves |
|---|---|---|---|---|---|
| `20261022T221043Z-a2bce8a6` | `--once` (phase) | 22:10:43 | `PENDING_WINDOW_OPEN` | 0 | 270 day-slots planned (90 days × 3 slices), all `INCOMPLETE_DAY` with 24 unclosed opens each; coverage 0/6480. The window had not opened. |
| `20261022T221044Z-c9a9f320` | `--once --rehearsal` | 22:10:44 | `CAPTURE_COMPLETE_AWAITING_VERIFICATION` | 9 | **the capture**: 9 shards, 72 bars per slice, coverage 216/216 |
| `20261022T221046Z-8a317fe4` | `--once --rehearsal` (repeat) | 22:10:46 | `NOT_DUE` | 0 | 9 × `ALREADY_HELD`, no bytes changed |
| `20261022T221048Z-0d5ae0a6` | `--resume --rehearsal` | 22:10:48 | `RESUMED` | 0 | reconciliation: 9 shards seen, 9 healthy, 0 conflicts, 0 partials recovered |
| `20261023T053435Z-7fe919f5` | `--once` (phase, after the window opened) | 05:34:35 | `NOT_DUE` | 0 | the window is open and empty: coverage `PENDING`, 0 / 6480, every day-slot `INCOMPLETE_DAY` because `2026-10-23` has not closed. Exit 3, no shard, nothing promoted |

The scheduler watermark (`data/exp004a/phase3/rehearsal/state/scheduler.json`) records
`runs_recorded: 1, 2, 3` across the three rehearsal attempts. It is bookkeeping, not evidence: the
verifier never reads it, so a tampered watermark cannot make a claim pass.

### The rehearsal capture

| Slice | Days | Rows / declared | Consolidated sha256 | Admissible | Max lag |
|---|---|---|---|---|---|
| `1h:BTC` | 2026-10-19, -20, -21 | 72 / 72 | `04361e8cdc343b59…` | yes | 6 957 826 ms |
| `1h:ETH` | 2026-10-19, -20, -21 | 72 / 72 | `65c17b79d8c7e7f6…` | yes | 6 957 826 ms |
| `1h:SOL` | 2026-10-19, -20, -21 | 72 / 72 | `a2366231303309cb…` | yes | 6 957 826 ms |

Day-level lags, the reason the window was chosen: `2026-10-19` peaks at 6 957 826 ms
(115.96 min), `2026-10-20` at 2 476 429 ms (41.27 min), `2026-10-21` at 5 194 647 ms (86.58 min).
All three are inside the declared 7 200 000 ms bound, and `2026-10-19` is the tightest admissible
observation in the window — seven minutes short of quarantine.

The consolidated digests are **identical across all three rehearsal attempts**
(`04361e8c…`, `65c17b79…`, `a2366231…`), which is the determinism claim measured rather than
asserted: three runs of the builder over the same store bytes produced the same dataset digest,
and the repeat run wrote no shard at all.

Every row is the forward store's own line, byte for byte; the shard manifest records the exact
prefix of the store it was taken from (`prefix_bytes`, `prefix_sha256`) so a later append cannot
retroactively invalidate it.

`data/forward/` is git-ignored, so the store was copied into this isolated worktree for the
rehearsal and the copy's digest is recorded in each shard manifest (`sha256_at_read`).

---

## 5. The independent verdicts

`INDEPENDENT_VERIFICATION.json` at the package root — **`PASS_COVERAGE_COMPLETE`**, 19 checks,
0 failed, `certification_allowed: false`, `certification_blocked_by: REHEARSAL_IS_NOT_EVIDENCE`.
`evidence/20261022T221043Z-a2bce8a6/INDEPENDENT_VERIFICATION.json` — **`PASS_PENDING_WINDOW_OPEN`**,
20 checks, 0 failed, blocked by `COVERAGE_PENDING_WINDOW_OPEN`.

| Control | What it establishes |
|---|---|
| `DECLARATION_SHA256`, `DECLARATION_ID` | the claim was made under this declaration and no other (`baeffad097f7d937…`) |
| `DECLARATION_ARITHMETIC` | 2160 = 90 days × 24 hours per slice; every entry stays inside the window; every entry has a positive lag bound |
| `GENERATOR_BLOB_RECORDED` | program `2fec1484…`, engine `75d73669…`, verifier `20503fb2…` hash to the blob ids the declaration names |
| `REHEARSAL_DISJOINT_FROM_WINDOW` | the rehearsal shares no instant with the capture window and counts for nothing |
| `DECLARATION_COMMIT_PRECEDES_WINDOW` | commit `937a55c3` at `2026-10-22T22:10:29Z` < window start `2026-10-23T00:00:00Z` (phase run only) |
| `SHARD_BYTES_MATCH_MANIFESTS` | 9/9 shards hash to their manifests and every row is the store's own line |
| `NO_DUPLICATE_OPENS` | no open instant appears twice across shards |
| `GENERATOR_CONSISTENT` | every shard was written by program digest `b778c642efdf9b4d…` |
| `QUARANTINE_IS_DISCLOSED` | 0 inadmissible days exist; had any existed, a manifest calling it admissible would fail here |
| `CONSOLIDATED_IS_THE_SHARDS` | the consolidated dataset rebuilds from the shards byte for byte |
| `TEMPORAL_POLICY_IN_THE_DATASET` | 216 rows: none is future, late, unclosed or unbounded |
| `COVERAGE_RECOMPUTED`, `COVERAGE_NOT_OVERSTATED`, `DENOMINATOR_IS_THE_DECLARATION` | the coverage word and the denominator are recomputed, not copied |
| `BUILDER_CANNOT_TRADE`, `BUILDER_DID_NOT_CERTIFY`, `GATES_UNCHANGED` | the builder names no order entry point and claims neither certification nor a gate move |
| `FROZEN_PACKAGES_INTACT` | 93 paths of `wp051_02b`..`wp051_02f` are byte-identical to `HEAD` |
| `VERIFIER_IS_INDEPENDENT` | the verifier's import graph contains neither the builder, the engine nor `trading_bot` |

The phase run carries one control the rehearsal run does not need
(`DECLARATION_COMMIT_PRECEDES_WINDOW`), which is why the counts differ: 20 and 19.

### Re-verification on `2026-10-23`, by a separate process

The verifier was run again against the sealed claims, from a fresh interpreter, after the window
opened:

| Claim | Command | Verdict | Identical to the sealed verdict? |
|---|---|---|---|
| rehearsal `c9a9f320` | `--claim … --rehearsal` | `PASS_COVERAGE_COMPLETE`, exit 0 | **yes**, every field but `at_utc` |
| phase `a2bce8a6` | `--claim … --as-of 2026-10-22T22:10:59Z` | `PASS_PENDING_WINDOW_OPEN`, exit 3 | **yes**, every field but `at_utc` |
| phase `a2bce8a6` | `--claim …` (today's clock) | **`FAIL`**, `COVERAGE_RECOMPUTED`, exit 2 | no — and correctly so, see `DEF-02G-08` |
| phase `7fe919f5` | `--claim …` (today's clock) | `PASS_COVERAGE_INCOMPLETE`, exit 3 | first run: this is its sealed verdict |

The third line is the one worth reading twice. The old claim says `PENDING_WINDOW_OPEN`; the bytes
and the declaration, at *today's* clock, say `PENDING`. Both statements are true and they are not
the same statement, because the window opened between them. The verifier recomputes the status
against its own clock instead of trusting the claim — so it refuses a phrase that has expired
rather than certifying it. Pinning the clock with `--as-of` reproduces the original verdict exactly,
which is the reproducibility the package actually promises: same bytes and same observation instant
in, same verdict out.

The rehearsal verdict carries `certification_allowed: false` and
`certification_blocked_by: REHEARSAL_IS_NOT_EVIDENCE` even though its coverage is complete. That
is the point of separating the two words: **`COVERAGE_COMPLETE` describes a denominator;
`certification_allowed` describes an experiment.**

---

## 6. The adversarial suite (49 tests)

| # | Attack | Where it is refused | Result |
|---|---|---|---|
| 1 | Grid read from the store instead of the declaration | `test_the_grid_comes_from_the_window_and_the_timeframe_not_from_the_store` | PASS |
| 2 | Declared row count contradicts the window | `test_a_declared_row_count_that_contradicts_the_window_is_refused` | PASS |
| 3 | Entry without a lag bound | `test_a_declaration_without_a_lag_bound_is_refused` | PASS |
| 4 | Shard granularity other than a day | `test_a_shard_granularity_other_than_a_day_is_refused` | PASS |
| 5 | Entry that leaves the declared window | `test_an_entry_that_leaves_the_declared_window_is_refused` | PASS |
| 6 | Rehearsal that claims to count | `test_a_rehearsal_that_counts_toward_coverage_is_refused` | PASS |
| 7 | A capture that copies rows instead of the store's own lines | `test_a_capture_writes_one_shard_per_day_holding_the_stores_own_lines` | PASS |
| 8 | Second capture rewrites evidence | `test_a_second_capture_writes_nothing_and_changes_nothing` | PASS |
| 9 | Shard edited behind its manifest | `test_a_shard_whose_bytes_contradict_its_manifest_is_a_conflict_not_a_rewrite` | PASS |
| 10 | Payload with its manifest removed | `test_a_payload_without_a_manifest_is_never_adopted` | PASS |
| 11 | Interrupted write | `test_an_interrupted_write_leaves_nothing_visible_and_resume_removes_the_partial` | PASS |
| 12 | Day published before its last bar closed | `test_a_day_whose_last_bar_has_not_closed_is_never_published` | PASS |
| 13 | Bar opening at the capture instant | `test_a_bar_that_opens_at_the_capture_instant_is_a_future_bar` | PASS |
| 14 | Bar missing from the store | `test_a_missing_bar_makes_the_day_not_due_and_names_the_open` | PASS |
| 15 | Late (backfilled) bar | `test_a_late_bar_quarantines_its_day_and_never_reaches_the_dataset` | PASS |
| 16 | Negative lag (forged timestamp) | `test_a_bar_stored_before_it_closed_is_a_forged_timestamp` | PASS |
| 17 | Bar the store says is open | `test_a_bar_the_store_says_is_not_closed_blocks_the_day` | PASS |
| 18 | Coverage above the floor but below the declaration | `test_coverage_never_completes_while_a_day_is_missing_even_above_the_required_fraction` | PASS |
| 19 | Complete coverage | `test_coverage_completes_only_when_every_declared_bar_is_admissible` | PASS |
| 20 | Window not yet open | `test_before_the_window_opens_the_status_is_pending_and_not_complete` | PASS |
| 21 | Rehearsal completion leaking into the phase | `test_a_rehearsal_that_is_complete_leaves_the_phase_pending` | PASS |
| 22 | Rehearsal shard claiming prospective status | `test_a_rehearsal_shard_is_stamped_non_prospective` | PASS |
| 23 | Two consolidations differ | `test_consolidation_is_deterministic_in_the_shard_bytes` | PASS |
| 24 | Tampered shard byte | `test_a_tampered_shard_is_excluded_and_named` | PASS |
| 25 | A day holding another day's bars | `test_a_second_day_holding_the_first_days_bars_is_reported_as_gap_and_duplicate` | PASS |
| 26 | Rehearsal shard claiming coverage | `test_a_shard_claiming_coverage_inside_a_rehearsal_is_refused` | PASS |
| 27 | Builder claiming a capture as a verdict | `test_the_builder_captures_and_reports_without_certifying` | PASS |
| 28 | Repeated tick | `test_a_repeated_tick_writes_no_shard_and_says_so` | PASS |
| 29 | Resume after a clean run | `test_resume_reports_the_shards_it_found_healthy_and_rewrites_none` | PASS |
| 30 | `--check` writing something | `test_check_writes_nothing_at_all` | PASS |
| 31 | Scheduler tick budget | `test_the_scheduler_runs_a_bounded_number_of_ticks` | PASS |
| 32 | Two concurrent captures | `test_the_lock_refuses_a_second_concurrent_capture` | PASS |
| 33 | Abandoned lock | `test_an_abandoned_lock_is_taken_over_and_the_takeover_is_recorded` | PASS |
| 34 | Two attempts sharing a run id | `test_two_attempts_never_share_a_run_id` | PASS |
| 35 | Independent re-verification | `test_the_independent_verifier_reproduces_a_complete_capture` | PASS |
| 36 | Incomplete coverage called a pass | `test_the_verifier_refuses_to_call_an_incomplete_capture_a_pass` | PASS |
| 37 | Shard removed after the claim | `test_a_published_shard_removed_after_the_claim_makes_the_verifier_fail` | PASS |
| 38 | Builder and verifier disagreeing on the word | `test_the_verifier_and_the_builder_agree_on_the_coverage_word` | PASS |
| 39 | Shard digest broken | `test_the_verifier_fails_a_shard_whose_bytes_no_longer_hash_to_its_manifest` | PASS |
| 40 | Manifest calling a late day admissible | `test_the_verifier_fails_a_manifest_that_calls_an_inadmissible_day_admissible` | PASS |
| 41 | Shard published before its day closed | `test_the_verifier_fails_a_shard_published_before_its_last_bar_closed` | PASS |
| 42 | Shard written under another declaration | `test_the_verifier_fails_a_shard_written_under_another_declaration` | PASS |
| 43 | Rehearsal accepted, certification refused | `test_the_verifier_accepts_a_rehearsal_and_never_lets_it_move_the_phase` | PASS |
| 44 | Rehearsal verdict counted as the phase's | `test_the_verifier_does_not_let_the_rehearsal_move_the_phase` | PASS |
| 45 | Two generators in one package | `test_the_verifier_fails_two_different_generators_in_one_package` | PASS |
| 46 | Programs swapped behind the declaration | `test_the_verifier_checks_the_programs_against_the_declaration` | PASS |
| 47 | Verifier importing the builder | `test_the_verifier_is_a_separate_implementation` | PASS |
| 48 | Builder naming a way to trade | `test_the_builder_names_no_way_to_trade` | PASS |
| 49 | Builder claiming a verification | `test_the_builder_never_claims_a_verification` | PASS |

`49 passed in 34.70 s` at `HEAD`, `ruff` clean on the four files, `mypy --strict` clean on the
three source files.

---

## 7. The wider suite, and what is not this package's

`tests/unit/research` at `HEAD`, with `PYTHONPATH=src` so that `trading_bot` resolves to *this*
worktree and not to the editable install that points at another checkout:

```
$ PYTHONPATH=src python -m pytest tests/unit/research -q --continue-on-collection-errors -p no:cacheprovider
115 failed, 2570 passed, 31 skipped, 15 errors in 650.21s (0:10:50)
EXIT=1
```

All 49 tests of §6 are inside that `2570 passed`: this package contributes no failure, no skip and
no xfail, and `grep -rl wp051_02g tests/` finds only `test_exp004a_wp051_02g.py`, so no failing
module imports a 02G file. The 115 failures and 15 errors are other packages' and the tree's, and
they fall into four groups:

* **Missing generated artefacts of other packages in this isolated worktree** — the largest group,
  and the cause of all 14 setup errors: `reports/profitability_gate035/FINAL_REPORT.json`,
  `reports/profitability_gate035/INDEPENDENT_VERIFICATION.json`, `reports/rfc035/search_round_3/*`,
  `reports/alpha-expansion-v1/data` (no 1h shards), `reports/strategy-baseline/COST_BARRIER.json`,
  `reports/rfc046/*` and `data/raw/alpha003/price/*`. Those reports are not produced by this
  worktree and this package neither writes nor reads them.
* **`<module 'alpha15'> has no attribute 'PRE_PIT_RUNNERS'`** — the collection error of
  `test_edge16_pit.py` plus three `test_arp*_pit.py` failures. A tree-level API drift: `alpha15` at
  `HEAD` exports `FAMILY_BY_NAME` and `SINGLE_ASSET_FAMILIES` but not `PRE_PIT_RUNNERS`. 02F hit the
  same class of problem for a different reason (another package's in-flight `alpha15.py` edits); it
  is reported here, not worked around. The run uses `--continue-on-collection-errors` so the rest
  of the suite is still measured.
* **A shared virtual environment pointing at a second checkout** — `test_st6_scheduler.py`'s
  host check fails because `sys.executable` resolves to
  `…/Downloads/bot freebuff/.venv/Scripts/python.exe`; that is the venv this worktree has to borrow,
  not a fact about the package. Four ST6 failures are `WinError 2` for the same missing scripts.
* **02B–02F's own frozen controls refusing a dirty worktree** — `GENERATOR_WORKTREE_UNCHANGED`
  (02E/02F) fails while the tree holds this package's uncommitted files, and 02E/provenance's
  declaration controls now report `DECLARATION_COMMITTED_AFTER_WINDOW_START` because their window
  opened at `2026-10-22T00:00:00Z` and the clock has passed it. Both are properties of *when and
  where* the run happened: they must be re-run after this package's evidence commit, against a
  clean tree, and this report does not count them as passing until that happens.

No test was skipped, weakened, marked xfail or deselected to make this column read better. The
command above is the command that produced the numbers, exit status included.

**A collection trap worth naming:** running `tests/unit/research` without `PYTHONPATH=src` makes
`test_exp004a_wp051_02g.py` resolve `trading_bot.research.prospective` from the other checkout and
fail to import `incremental` (`2 errors during collection`, `EXIT=2`). The single-file run passes
because the test inserts its own `src` first. It is an artefact of the borrowed venv, not of the
package, which is why the suite is reported with the path pinned.

---

## 8. Defects and limitations

| ID | Statement | Status |
|---|---|---|
| `DEF-02F-01` | the phase-2 datasets hold 14 of 2160 declared bars and the frozen extractor cannot extend them | **CARRIED, not fixed here.** Phase 3 does not touch, extend or rewrite them. |
| `DEF-02G-01` | coverage can only complete after 90 days; today the phase stands at 0/6480 | **OPEN BY CONSTRUCTION.** The first phase shard becomes due at `2026-10-24T00:00:00Z` (the day `2026-10-23` has to close first). |
| `DEF-02G-02` | the scheduler is an in-process bounded loop (`--schedule`), not a service; no cron entry, task or daemon is installed | **OPEN.** `L-02` from 02F stays open; the mechanism is resumable and idempotent, but a person or an external scheduler must call it. |
| `DEF-02G-03` | a day that becomes inadmissible (its bars arrive too late) is quarantined for ever; there is no re-fetch, by design | **OBSERVED, by design.** A recovery path would be a re-observation of the same window, which is a different claim. |
| `DEF-02G-04` | `--as-of` lets a capture write a past `captured_at_utc`; the manifests record it, and the verifier recomputes admissibility against *its own* clock, so a backdated shard is visible rather than invisible | **MITIGATED.** No `--as-of` capture is sealed in this package; every sealed shard carries the real capture instant. |
| `DEF-02G-05` | `data/forward/` is git-ignored, so the rehearsal ran against a copy of the store made in this worktree (`sha256_at_read` in each manifest) | **LIMITATION.** Recorded in every shard manifest; the copy's digest is what the evidence attests. |
| `DEF-02G-06` | the declaration's `rehearsal.note` quotes "max lag 86.6 min" as the window's figure; the window's true maximum is 115.96 min on `2026-10-19`. 86.6 min is the 21st's day maximum | **DOCUMENTATION DEFECT, left uncorrected on purpose.** The declaration is immutable and its `sha256` is pinned in evidence; editing one sentence would invalidate `DECLARATION_SHA256` and force a re-capture over the same bytes, which is a worse trade than a wrong adjective in a note. §4 carries the correct figures. |
| `DEF-02G-08` | a sealed phase claim that says `PENDING_WINDOW_OPEN` stops verifying once the window opens: the verifier recomputes the status at *its own* clock and returns `FAIL`/`COVERAGE_RECOMPUTED` (`PENDING` ≠ `PENDING_WINDOW_OPEN`) | **OBSERVED, not worked around.** The refusal is the control doing its job — an expired phrase must not be re-certified — but it makes a historical claim dependent on `--as-of` to reproduce. The fix is a verdict word for "this claim was true at its own instant", which is a contract change and belongs to the next declaration, not to a patch under this one. §5 records both runs. |
| `DEF-02G-07` | `DECLARATION_COMMIT_PRECEDES_WINDOW` prints the committer's local timestamp (`2026-10-23T00:10:29+02:00`) next to a `Z` window start, which reads as "10 minutes after" until it is converted | **DISPLAY DEFECT, not a control failure.** The comparison itself is done on epoch milliseconds and passes with 1 h 49 min of margin. Fixing the string would change the verifier's blob and break `GENERATOR_BLOB_RECORDED`, so it is reported for the next declaration rather than patched under a frozen one. |

| `DEF-02G-09` | a sealed `sha256` is the hash of the bytes **in this checkout**, and this checkout materialises CRLF (`core.autocrlf=true`), so a manifest written over LF bytes disagrees with itself after a re-checkout | **MEASURED, pre-existing across the experiment.** Re-hashing 02D's 19 sealed artefacts shows 13 disagreements, **all** of them resolved by `CRLF→LF` normalisation: 0 content drift. 02G's own manifest was sealed over the bytes on disk and verifies 29/29 *here*; a fresh clone must use `git -c core.autocrlf=false checkout` or the digests will not match. Not patched, because the fix is a `.gitattributes` policy for the whole repository. |
| `DEF-02G-10` | the forward observer is **stale**: `data/forward/edge03/1h/{BTC,ETH,SOL}.jsonl` stop at `2026-10-22T18:00:00Z` (last fetched `19:10:58Z`), 11 hourly bars behind the `2026-10-23T05:35Z` clock | **OPEN, operational.** 02E's `FORWARD_OBSERVER_FRESH` fails on all three series. The capture mechanism is idle, not broken — but if the observer does not resume before `2026-10-24T00:00Z`, the bars for `2026-10-23` will arrive with a lag beyond the declared 2 h bound and the day will be **quarantined**, not captured, and 90 quarantined days is 0 % coverage. This is the real next action; §10 says so. |

What could not be run, and is not reported as a pass:

* the **phase window's own coverage** — the window opened at `2026-10-23T00:00:00Z` and stands at
  0 of 6480 (`PENDING`); nothing is captured until `2026-10-24T00:00:00Z`, so there is nothing to
  verify beyond the absence of a shard;
* **paper validation** and anything downstream of it: not attempted, not claimed;
* **`test_edge16_pit.py`** — collection error at `HEAD` (§7).

---

### The neighbouring packages, re-run at the evidence commit

`8a4fd2cb`-era runs saw 02E and 02F fail on `GENERATOR_WORKTREE_UNCHANGED` while 02G's files were
uncommitted. Re-run after commit `c05e6ba7`, with the artefacts written to a scratch directory so
nothing frozen is touched:

```
$ PYTHONPATH=src python scripts/exp004a_wp051_02e_preflight.py --out-dir .tmp02g/02e_rerun
  PASS  STORE_READABLE · STORE_HAS_NO_FUTURE_INGEST · ST6_TAPE_REFUSED · WINDOW_CANNOT_BE_EXTENDED
  FAIL  SEALED_02D_PACKAGE_INTACT   19 sealed artefacts, 13 drifted  → DEF-02G-09, all 13 are CRLF
  FAIL  FORWARD_OBSERVER_FRESH      stale series: 1h:BTC, 1h:ETH, 1h:SOL → DEF-02G-10
  FAIL  NO_DATASET_PUBLISHED        3 datasets + 3 manifests in data/exp004a (the phase-2 files of DEF-02F-01)
BLOCKED − 10 controls − 4 failed  (exit 2)
$ PYTHONPATH=src python scripts/exp004a_wp051_02f_runner.py --check --out-dir .tmp02g/02f_check
eligible_series 1h:BTC, 1h:ETH, 1h:SOL · economic_executions 0 · exit 0
```

Neither run is 02G's verdict to give, and neither is claimed as one. What the re-run establishes is
attribution: the three failures are a line-ending policy, a stale observer and phase-2's own frozen
dataset — **none of them imports or reads a 02G file**, and none is repaired here.

## 9. Evidence map

All paths relative to the repository root. Digests of every file are in `EVIDENCE_MANIFEST.json`,
which is written last and lists every other file of the package.

| Artefact | What it is |
|---|---|
| `docs/agentic/exp004a/wp051_02g/RUN_REPORT.json` / `.md` | the sealed claim of the rehearsal capture (`20261022T221044Z-c9a9f320`) |
| `docs/agentic/exp004a/wp051_02g/INDEPENDENT_VERIFICATION.json` | the verifier's verdict on that claim — `PASS_COVERAGE_COMPLETE`, 19 checks |
| `docs/agentic/exp004a/wp051_02g/EVIDENCE_MANIFEST.json` | every file of the package, with `sha256` and, where Git knows the path, `git_blob_sha` |
| `docs/agentic/exp004a/wp051_02g/PACKAGE_SUMMARY.json` | every attempt, with the phase and the rehearsal listed apart |
| `docs/agentic/exp004a/wp051_02g/LATEST_RUN.json` | which run the seal points at |
| `docs/agentic/exp004a/wp051_02g/CHECK.json` | the read-only `--check` output |
| `docs/agentic/exp004a/wp051_02g/RUNTIME_AUTHORITY.md` | which program may produce which artifact |
| `docs/agentic/exp004a/wp051_02g/evidence/<run_id>/` | per attempt: `RUN_REPORT.json`, `RUN_REPORT.md`, `CLAIM.json`, `INDEPENDENT_VERIFICATION.json`, `shards.jsonl` |
| `data/exp004a/phase3/rehearsal/1h_{BTC,ETH,SOL}/2026-10-{19,20,21}.jsonl` + `.MANIFEST.json` | the nine shards |
| `data/exp004a/phase3/rehearsal/consolidated/1h_*/<run_id>.jsonl` + `.MANIFEST.json` | the consolidated datasets, one triple per attempt |
| `data/exp004a/phase3/rehearsal/state/scheduler.json` | the watermark (not evidence; the verifier never reads it) |
| `config/preregistrations/EXP-004A.datasets.phase3.json` | the declaration |

Hash semantics, stated once: `sha256` is the hash of the bytes in this checkout; `git_blob_sha` is
the Git object id. They are different magnitudes and are never presented as the same value.

---

## 10. Next operational step

Nothing else is needed for the mechanism. What is needed is time and a caller:

As of `2026-10-23T05:34Z` the phase stands at 0 / 6480 and `PENDING`. The first shard becomes due
at `2026-10-24T00:00Z`, when `2026-10-23` has closed.

```
PYTHONPATH=src python scripts/exp004a_wp051_02g_capture.py --once         # first shard due 2026-10-24T00:00Z
PYTHONPATH=src python scripts/exp004a_wp051_02g_verify.py --claim docs/agentic/exp004a/wp051_02g/RUN_REPORT.json
PYTHONPATH=src python scripts/exp004a_wp051_02g_capture.py --summary      # then re-seal once the phase has data
PYTHONPATH=src python -m pytest tests/unit/research/test_exp004a_wp051_02g.py -q
```

Until `2027-01-21T00:00:00Z` the honest word for the phase is `BELOW_DECLARED` or `PENDING`, and
after it, `COVERAGE_COMPLETE` only if all 6480 bars are present and admissible. A reviewer who
wants to see the mechanism's incompleteness path on real data should run `--check` on any window
that includes `2026-10-13 … 2026-10-18`: §2's table says what it will find, and it will name it
rather than capture it.

### The one thing that must happen before `2026-10-24T00:00Z`

Restart the forward observer. Nothing about the mechanism blocks the phase; the data does. The
store's last bar is `2026-10-22T18:00:00Z` and the bound is two hours, so an observer that comes
back after `2026-10-23T20:00Z` has already lost the day: those bars will be stored late, the day
will be written once with `admissible: false`, and the numerator will stay at zero. There is no
re-fetch path by design (`DEF-02G-03`), which is why this is written as an operational deadline
rather than a suggestion.

Nothing in this report certifies EXP-004A, moves it towards paper, or claims an edge. The
deliverable is a mechanism, its evidence, and an honest account of what is still owed.
