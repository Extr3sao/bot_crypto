# WP-051-02F — final report

**Phase:** EXP-004A, phase 2 (prospective capture) · **Work package:** WP-051-02F · **RFC:**
`RFC_EXP004A_051_02F` (PROPOSED → IMPLEMENTED) · **Date:** 2026-10-22

> The window opened at `2026-10-22T00:00:00Z` and this package ran inside it. A real capture
> happened: three datasets, fourteen bars each, published by the frozen extractor and checked by
> a verifier that does not import the builder. That is a data result. It is not a certification,
> not a paper validation, and not a promotion.

---

## 1. The headline

| Field | Value |
|---|---|
| `IMPLEMENTATION_STATUS` | **PASS** |
| `TEST_STATUS` (02F suite) | **PASS** — 75 passed, 0 failed |
| `TEST_STATUS` (`tests/unit/research`, 3 modules excluded) | see §6 |
| `RUNTIME_CAPTURE_STATUS` | **CAPTURED_VERIFIED** (bytes) with **COVERAGE = BELOW_DECLARED** (see §5) |
| `INDEPENDENT_VERIFICATION` | **PASS** — 28 checks at run time, 32 checks in re-verification |
| `TIME_PROOF` / `C-013` | **TIME_PROOF_WEAK** — not promoted; no external attestation exists |
| `PAPER_VALIDATION` | **NOT_PASS** |
| `CERTIFICATION` | **BLOCKED** |
| `PROMOTION` | **NO_PROMOTION** |
| `FALSE_SUCCESS` | **0** |
| **Overall** | **PARTIAL** — the runner and its evidence pass; the declared dataset contract does not (§5) |

---

## 2. What was built

`scripts/exp004a_wp051_02f_runner.py` — a thin orchestrator, not a second engine:

- **`--once`** one authorised attempt: observation → window → freshness → eligibility → the
  frozen preflight → the frozen extractor → the temporal guard → the independent verifier.
- **`--check`** reads the world and writes nothing.
- **`--resume`** reconciles a crashed or interrupted attempt without republishing.
- **`--seal`** promotes one run's claim, verdict and manifest to the package's top level, and
  refuses to overwrite a seal that belongs to a different run.

`scripts/exp004a_wp051_02f_verify.py` — the independent verifier (`BUILDER != VERIFIER`). It
imports neither `trading_bot` nor the runner, runs the sealed 02E verifier as a separate process,
re-reads the store to compare published rows byte for byte, and re-runs as its own process in the
tests.

State machine, as the RFC asks, with the states the report can actually be in:

```
NOT_DUE · PENDING_DATA · PENDING_FRESHNESS · BLOCKED_INTEGRITY
CAPTURE_ATTEMPTED · TEMPORAL_QUARANTINE_CHECK · QUARANTINED · FAILED_OR_PENDING
INDEPENDENT_VERIFY → CAPTURED_VERIFIED | BLOCKED
```

Nothing is delegated that already exists: the ten provenance controls come from
`scripts/exp004a_wp051_02e_preflight.py`, the capture from `scripts/exp004a_capture.py` invoked
with the declaration's own command, the observation from `scripts/edge04_observer.py`.

### Defects found and fixed while doing it

| # | Defect | Fix |
|---|---|---|
| D1 | The runner required the preflight to return `PASS`; the 02E program never emits `PASS`, it emits `WINDOW_OPEN` once the window is open. The first real attempt blocked with an empty failed-control list. | The runner accepts exactly `("WINDOW_OPEN", "READY_FOR_WINDOW")` and refuses every other status, including a `PASS` nobody emits. |
| D2 | Two attempts in the same clock tick could share a `run_id` on Windows, where `time.time_ns` is coarse. | The seed mixes a process counter and an OS nonce with the clock. |
| D3 | The seal's manifest listed only the package's own files, so it sealed the description of a capture and not the capture. | Datasets and the extractor's own manifests are sealed with the claim's digest beside the measured one. |
| D4 | Nobody named the coverage gap. | `coverage_status` per dataset (`BELOW_DECLARED`, `AT_LEAST_DECLARED`, …) and a verifier control that recounts the bars from the declaration's own `row_count`. |
| D5 | "The sealed 02E still verifies" was treated as a byte-integrity control. It is not: 02E's verifier re-evaluates the world against its own clock and fails by construction once the window opens. | Two controls: `SEALED_02E_BYTES_INTACT` (23/23 files re-hashed against 02E's own manifest) and `SEALED_02E_REVERIFICATION`, which passes only when the failures are the named controls that expire, and says in words that 02E has not been re-certified. |
| D6 | Dead code: the runner carried an unused `reverify_02e`. | Removed; the verifier owns that control. |
| D7 | `ruff` and `mypy --strict` did not pass on the two new scripts. | Both clean. |

### Commits

| Commit | What it carries |
|---|---|
| `be5b68e1` | the runner, the verifier, the tests, the authority map, the sealed evidence and the three datasets |
| `5817184e` | the re-seal that includes this report (50 manifest entries, none orphaned) |

The commit that carries *this file* is the one this report cannot name, because writing its id into
the file would change the file. It is `git log -1 -- docs/agentic/exp004a/wp051_02f/FINAL_REPORT.md`,
and it also re-seals the manifest so that the digest it lists is the one that exists.

The checkout is shared: `HEAD` moved from `87ad0d7a` to `f20dff9b` to `2ed43ad4` while this package
ran. Only the paths listed in §10 were staged; nothing else was reverted, cleaned or stashed.

---

## 3. Real execution

The window was open and the store was current when the attempt ran, so the capture was due.

| Run | UTC | State | Exit | Meaning |
|---|---|---|---|---|
| `20261022T134802Z-821a8f05` | 13:48 | `BLOCKED_INTEGRITY` | 2 | D1: the preflight said `WINDOW_OPEN`, the runner wanted `PASS`. Published nothing. Kept as evidence. |
| `20261022T140037Z-de5d3329` | 14:00 | `CAPTURED_VERIFIED` | 0 | **the capture**: three datasets published, guard PASS, verifier PASS |
| `20261022T142234Z-55818916` | 14:22 | `BLOCKED_INTEGRITY` | 2 | the 02E pre-capture gate refuses once a dataset exists — by design. Published nothing. |

Every attempt has its own directory, its own claim (`CLAIM.json`), its own verdict
(`INDEPENDENT_VERIFICATION.json`) and its own logs. No attempt overwrote another.

The sealed run is `20261022T140037Z-de5d3329`:

| Slice | Extractor exit | Rows | Dataset sha256 (first 16) | Guard |
|---|---|---|---|---|
| `1h:BTC` | 0 `OK` | 14 | `da7310abcacc410e` | PASS, 14 rows, 0 violations |
| `1h:ETH` | 0 `OK` | 14 | `28275763fe0bc3d6` | PASS, 14 rows, 0 violations |
| `1h:SOL` | 0 `OK` | 14 | `b617d5492bb89ced` | PASS, 14 rows, 0 violations |

Observation before the capture: `OBSERVED`, 3 new closed bars, 0 missing, exit 0.
Capture decision: `2026-10-22T14:02:46.640Z`.

An audit computed outside both scripts confirmed it: for each asset, every published row is
byte-identical to the store's row for the same open instant, the opens are strictly increasing,
and no row has `fetched_at_ms` later than the decision or a close later than the decision.

`EXP-004A-ST6-TAPE` was **deferred**, not captured: its declared timeframe
(`4h slot, 3 rounds of 15s`) is not a bar series and the freeze defines no round-to-window rule.
The extractor refuses it with exit 2 and that refusal is recorded.

---

## 4. Independent verification of the sealed run

`docs/agentic/exp004a/wp051_02f/INDEPENDENT_VERIFICATION.json` — **PASS, 28 checks** at run time,
including `SOURCE_COMPARED` (three datasets, rows equal to the store's bytes), `ROWS_ADMISSIBLE`,
`GENERATOR_BLOB`, `GENERATOR_WORKTREE_UNCHANGED`, the five locked gates, and
`SEALED_02E_BYTES_INTACT` (23/23).

`docs/agentic/exp004a/wp051_02f/REVERIFICATION_UNDER_FINAL_VERIFIER.json` — **PASS, 32 checks**,
produced by the final verifier over the same sealed claim. The four extra checks are the coverage
control (one per dataset) and the sealed-02E integrity control. It is a separate file on purpose:
re-running a verifier is not the same act as editing what it verified.

What the verifier does **not** do: it does not trust the runner's state word. `NO_FALSE_SUCCESS`
compares the claimed state with what is on disk, and the row-level controls re-read the forward
store rather than the runner's summary of it.

---

## 5. The finding that matters: the dataset is short, and it is short for good

The declaration promises `row_count: 2160` per 1h series over
`[2026-10-22T00:00:00Z, 2027-01-20T00:00:00Z)` and asks for `coverage_required: 0.9`.

The frozen extractor selects every bar whose open falls inside the declared period and **does not
enforce `coverage_required`**. A capture taken on the first day of a 90-day period therefore
publishes 14 bars of a 2160-bar promise, and because the extractor writes a dataset **once** and
refuses to regenerate it (`already exists; a dataset is written once, not regenerated`), those
files can never be extended by re-running the command.

| Dataset | Published | Declared | Fraction | Status |
|---|---|---|---|---|
| `EXP-004A-1H-BTC` | 14 | 2160 | 0.65 % | `BELOW_DECLARED` |
| `EXP-004A-1H-ETH` | 14 | 2160 | 0.65 % | `BELOW_DECLARED` |
| `EXP-004A-1H-SOL` | 14 | 2160 | 0.65 % | `BELOW_DECLARED` |

The bars that *are* there are real, prospective, admissible and verified. What is not there is the
dataset the declaration describes, and the honest reading of this work package is:

- `RUNTIME_CAPTURE_STATUS`: **CAPTURED_VERIFIED** for the bytes.
- `COVERAGE_STATUS`: **BELOW_DECLARED / frozen short** for the declared contract.
- `PHASE_2_DATASET_CONTRACT`: **NOT_MET** — and now permanently so for these three files, because
  the extractor refuses to rewrite them.

This package does not fix that and must not: deleting published data to retry would be exactly the
"clean the artefacts until you get a PASS" move the RFC forbids. The decision belongs to the
experiment owner, and there are three coherent options:

1. **Accept a partial prospective dataset** for phase 2 and say so in the phase declaration's
   successor — the 14 bars are genuine first-hour forward observations.
2. **Declare the capture premature** and open a phase-3 declaration that names new dataset paths
   and a capture instant at or after the window's end, leaving these files untouched on disk as
   the record of what was attempted.
3. **Leave phase 2 open and capture per-day artefacts** under a new declaration, which needs
   `DEF-02E-01` addressed first because the extractor still cannot refuse a bar ingested after the
   decision.

Option 2 is the one a reviewer can defend with the current freeze; options 1 and 3 need a new
preregistration either way.

### Why the runner did not simply wait

The RFC's WP-04 says to run against real forward bars when they are available and to report
`PENDING_DATA` when they are not. The window was open, the store was current, fourteen closed bars
existed. Nothing in the RFC or in the declaration says "wait until the period elapses", and a
runner that invented that rule would be reinterpreting the preregistration. What the runner can do
— and now does — is name the shortfall in the claim, in the seal and in the verification.

---

## 6. Tests

`tests/unit/research/test_exp004a_wp051_02f.py` — **75 passed, 0 failed**, `ruff` clean,
`mypy --strict` clean on both scripts. Every fixture is synthetic and lives in `tmp_path`; nothing
in the suite writes to `data/exp004a`, to the forward store or to the freeze.

### The fifteen adversarial cases of RFC §9

| # | Case | Where it is proved | Result |
|---|---|---|---|
| 1 | Window still closed | `test_before_the_window_the_runner_says_not_due_and_publishes_nothing` | PASS |
| 2 | Window open, no bars | `test_inside_the_window_without_a_closed_bar_is_pending_data` | PASS |
| 3 | BTC valid, ETH/SOL absent | `test_a_partially_published_series_is_never_a_global_pass` | PASS |
| 4 | Observer fresh, store behind (L-04) | `test_a_stale_store_is_pending_freshness_and_not_pending_data` | PASS |
| 5 | Bar open, not yet closed | `test_inside_the_window_without_a_closed_bar_is_pending_data` | PASS |
| 6 | Future bar marked eligible (L-01) | `test_a_capture_with_an_impossible_ingest_is_quarantined_and_left_on_disk` + nine guard cases | PASS |
| 7 | Timestamp without a comparable source | `test_the_verifier_refuses_to_promote_the_time_proof` | PASS |
| 8 | Declaration or generator hash adulterated | `test_a_broken_freeze_blocks_before_the_extractor_is_invoked`, `test_the_verifier_refuses_a_tampered_generator` | PASS |
| 9 | Exit 0 without output; codes 2/3/4/5 | `test_an_exit_zero_without_a_dataset_is_a_failure_not_a_capture`, `test_the_extractors_exit_codes_are_read_as_the_contract_says` (parametrised) | PASS |
| 10 | Two simultaneous runs, same slot | `test_a_second_runner_does_not_run_while_the_lock_is_held`, `test_the_lock_is_exclusive`, `test_two_attempts_never_share_a_run_id` | PASS |
| 11 | Crash after one series | `test_resume_finds_the_attempts_a_previous_crash_left_behind`, `test_resume_reconciles_without_publishing` | PASS |
| 12 | Re-run the independent verifier on published bytes | `test_the_verifier_can_be_run_as_its_own_process` + `REVERIFICATION_UNDER_FINAL_VERIFIER.json` | PASS |
| 13 | Missing logs, wrong hashes, CRLF | `test_the_verifier_rejects_a_dataset_whose_digest_does_not_match_the_claim`, `test_a_crlf_checkout_is_not_reported_as_freeze_drift`, `test_a_git_blob_id_is_not_a_sha256_of_the_checkout` | PASS |
| 14 | Protection of the 19 × 02D and all 02E artefacts | `test_the_sealed_02d_and_02e_artefacts_are_not_touched_by_a_run`, `test_the_sealed_02e_bytes_are_checked_against_their_own_manifest`, `test_check_writes_nothing_at_all` | PASS |
| 15 | Zero orders, zero paper orders, no gate moves | `test_the_runner_and_the_verifier_cannot_place_an_order`, `test_the_report_keeps_the_gates_where_they_were` | PASS |

### The wider suite

`tests/unit/research` as a whole, run after the last change in this checkout:

| | Count |
|---|---|
| passed | **2758** |
| failed | **24** |
| skipped | 1 |
| duration | 1019 s |
| could not be collected | 3 modules (§9) |

**None of the 24 is this package's.** The failure set is identical before and after this package's
changes, and every one of them reproduces with the three 02F files moved out of the tree — which
is also how they were attributed. The two causes observed are a shared checkout in flux and tests
that commit "now" into a repository whose window opened on 2026-10-22. §9 names them.

---

## 7. Frozen artefacts

| Package | Files | Status |
|---|---|---|
| `wp051_02b` | 14 | byte-identical to the pre-run baseline |
| `wp051_02c` | 14 | byte-identical |
| `wp051_02d` (19 sealed artefacts) | 20 files | byte-identical; the 02E preflight control `SEALED_02D_PACKAGE_INTACT` reports 19/19, 0 drifted |
| `wp051_02e` | 23 | byte-identical; `SEALED_02E_BYTES_INTACT` re-hashes 23/23 against 02E's own manifest |

Re-running the sealed **02E verifier** after the window opened returns exit 2 with three failures:
`V-TEMP-01`, `V-TEMP-02` (the sealed report described a window that had not opened) and
`V-ART-03` (it counted zero published datasets). Those controls describe a world this package is
required to change; they are recorded by name as expired and **never reported as passing**. 02E
has not been re-certified by anything here, and the two byte-integrity facts above are what
actually establish that 02E is untouched.

---

## 8. Open defects

| ID | Defect | Status |
|---|---|---|
| `DEF-02E-01` / `L-01` | The frozen extractor can mark a bar eligible whose `fetched_at_ms` is later than the capture decision. | **OPEN.** Not fixed (forbidden in phase 2). Contained by an independent guard that quarantines and a verifier that fails the claim. Needs a phase-3 RFC. |
| `DEF-02F-01` | The frozen extractor does not enforce `coverage_required` and writes a dataset once, so a mid-period capture freezes a permanently short dataset. | **OPEN.** Detected, named, sealed. The decision is §5's. |
| `L-02` | No scheduler: the capture must be triggered by a person. | **OPEN.** This package deliberately installs no cron, no task and no daemon. |
| `L-04` | An observer within its lag bound does not prove the last expected bar is in the store. | **MITIGATED, not closed.** The runner compares the store to the clock immediately before the attempt; the mitigation is exercised by case 4. |
| `DEF-02F-02` | The 02E preflight's `NO_DATASET_PUBLISHED` control means the frozen pre-capture gate refuses for ever after the first publication, so `--once` is a once-per-phase operation. | **OBSERVED, by design.** Recorded rather than worked around: any future capture needs a new declaration. |

---

## 9. What could not be run, and why

- `tests/unit/research/test_alpha15_causality.py`, `test_edge16_causality.py`,
  `test_edge16_pit.py` — **collection error**, not a test failure:
  `src/trading_bot/research/economic_recovery/alpha15.py` is modified in this shared checkout
  (`M` in `git status`) and no longer exports `FAMILY_BY_NAME` / `SINGLE_ASSET_FAMILIES`, which
  `economic_recovery/causality.py` imports. It is another package's in-flight work; this package
  neither reverts nor fixes it.
- `tests/unit/research` failures outside this package — see the counts in §6. Every one was
  reproduced with this package's three files moved out of the tree, so none is caused by them. The
  two root causes observed are a shared checkout in flux (another agent committed twice while this
  ran: `f20dff9b`, then `2ed43ad4`) and tests whose fixtures commit "now" into a repository whose
  window opened at `2026-10-22T00:00:00Z`, which makes them fail by the calendar rather than by
  code (`DECLARATION_COMMITTED_AFTER_WINDOW_START` in `test_exp004a_provenance.py`).
- No live/paper trading, no orders, no risk change, no credentials, no new market-data provider.

---

## 10. Evidence map

All paths relative to the repository root. SHA-256 of each sealed file is in
`EVIDENCE_MANIFEST.json` (48 entries, all re-hashed and matching).

| Artefact | What it is |
|---|---|
| `docs/agentic/exp004a/wp051_02f/RUN_REPORT.json` | the sealed claim: run id, HEAD, platform, declaration, generator, store, captures, guards, datasets, gates |
| `docs/agentic/exp004a/wp051_02f/RUN_REPORT.md` | the same, readable |
| `docs/agentic/exp004a/wp051_02f/INDEPENDENT_VERIFICATION.json` | the verifier's 28-check verdict at run time |
| `docs/agentic/exp004a/wp051_02f/REVERIFICATION_UNDER_FINAL_VERIFIER.json` | the final verifier's 32-check verdict over the same claim |
| `docs/agentic/exp004a/wp051_02f/EVIDENCE_MANIFEST.json` | every file of the package, plus the three datasets and the extractor's manifests |
| `docs/agentic/exp004a/wp051_02f/RUNTIME_AUTHORITY.md` | which program is authorised to do what, and what it writes |
| `docs/agentic/exp004a/wp051_02f/evidence/20261022T140037Z-de5d3329/` | the capture: claim, verdict, logs, its own copy of the 02E preflight and re-verification |
| `docs/agentic/exp004a/wp051_02f/evidence/20261022T134802Z-821a8f05/` | the blocked first attempt (D1) |
| `docs/agentic/exp004a/wp051_02f/evidence/20261022T142234Z-55818916/` | the blocked third attempt, refused by the frozen gate after publication |
| `data/exp004a/EXP-004A-1H-{BTC,ETH,SOL}.jsonl` | the published datasets (14 rows each) |
| `data/exp004a/EXP-004A-1H-{BTC,ETH,SOL}.MANIFEST.json` | the extractor's own manifests for them |
| `scripts/exp004a_wp051_02f_runner.py`, `scripts/exp004a_wp051_02f_verify.py`, `tests/unit/research/test_exp004a_wp051_02f.py` | the code and its tests |

Hash semantics, stated once: `sha256` is the hash of the bytes in this checkout; `git_blob_sha`
is the Git object id. They are different magnitudes and are never presented as the same value.

---

## 11. Next operational step

The one thing that is genuinely blocking the phase is not code. It is a decision about
`DEF-02F-01`: three files now hold 14 verified forward bars each and cannot be extended by the
frozen extractor. Until the experiment owner picks an option from §5, WP-051-02F's remaining work
is to keep running `--once` once a day and recording `BLOCKED_INTEGRITY`
(`NO_DATASET_PUBLISHED`) — which is truthful but adds nothing.

If the owner picks option 2 or 3, the prerequisite is a **phase-3 RFC for `DEF-02E-01`**: a new
generator that refuses a bar ingested after the decision, a new preregistered declaration with new
dataset paths, an adversarial point-in-time suite, and an independent comparator over identical
inputs. Phase 2's data must stay untouched by it.
