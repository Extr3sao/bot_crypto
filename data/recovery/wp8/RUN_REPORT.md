# RUN REPORT — WP-8 / RECOVERY DETERMINISM, STATE AUTHORITY & CLEAN CHECKOUT

- phase: **WP-8** (follows WP-7, the cost-barrier lane)
- branch: `main` · mode: OFFLINE — no keys, no orders, no capital, no live path
- the work package changed how this lane *reads* its inputs, not what it concludes
- FALSE_SUCCESS = 0 · BUILDER ≠ VERIFIER · TEST_TARGET == RUNTIME_TARGET
- LIVE_TRADING = DISABLED · PAPER_PROMOTION = NOT_AUTHORIZED

`sabotage` in this report means a deliberate mutation that the rehearsal is required to
notice; the two runs are kept as artefacts under `evidence/`.

## 1. The failures this run had to remove

Captured before any test was edited, in three trees
(`evidence/BASELINE_REPRODUCTION.json`):

| tree | HEAD | result |
| --- | --- | --- |
| shared working tree | `33512b5` | 1 failed, 25 passed — `test_state_view_is_deterministic` |
| clean worktree of HEAD | `33512b5` | **3 failed**, 23 passed — all eight external inputs absent |
| clean worktree of the pre-WP-7 baseline | `38b8e18` | **3 failed**, 23 passed — the same three |

The three failing nodes in a clean checkout were `test_state_view_is_deterministic`,
`test_audit_is_deterministic_and_committed` and
`test_audit_records_the_paper_lane_failure_honestly`. A suite that is green where it was
written and red where it is checked out is the shape of the defect. The four demonstrated
causes are in [CAMPAIGN_STATE_DETERMINISM_AUDIT.md](CAMPAIGN_STATE_DETERMINISM_AUDIT.md) §2,
the input classes in [RECOVERY_RUNTIME_AUTHORITY_MAP.md](RECOVERY_RUNTIME_AUTHORITY_MAP.md),
and the two further defects the rehearsal then found are in §4 below.

## 2. What was executed

| step | command | exit | result |
| --- | --- | ---: | --- |
| input authority (capture) | `python scripts/recovery_input_evidence.py --capture` | 0 | `evidence/INPUT_EVIDENCE.json` written |
| input bundle | `python scripts/recovery_input_evidence.py --verify` | 0 | **VERIFIED** — 0 failures |
| campaign state view | `python scripts/campaign_state_view.py` | 0 | **PASS** |
| state view determinism | `python scripts/campaign_state_view.py --check` | 0 | **PASS** |
| ACTIVE economic audit | `python scripts/active_economic_audit.py` | 0 | **PASS** |
| audit determinism | `python scripts/active_economic_audit.py --check` | 0 | **PASS** |
| economic invariance | `python scripts/recovery_economic_invariance.py --check` | 0 | **STABLE**, verdict `IDENTICAL` |
| lane contract tests | `python -m pytest tests/unit/research/test_active_recovery_wp.py -q` | 0 | **28 passed** (26 before WP-8) |
| determinism regressions | `python -m pytest tests/unit/research/test_recovery_determinism.py -q` | 0 | **15 tests** (12 fast + 3 slow) |
| CI parity contract | `python -m pytest tests/unit/research/test_recovery_ci_parity.py -q` | 0 | **8 passed** |
| cost-barrier lane tests | `python -m pytest tests/unit/research/test_cost_barrier_{explorer,gate,adversarial,ci_parity}.py -q` | 0 | **93 passed** |
| cost-barrier gate | `python scripts/cost_barrier_gate.py --report .ci/gate.json` | 0 | **FULL_REPRODUCTION_PASS**, 0 checks failed, 0 controls missed |
| adversarial sweep | `python scripts/cost_barrier_adversarial.py --out .ci/adv.json` | 0 | **EVALUATED**, 17 attacks, 0 evaded, 0 legs failed |
| certification re-issue | `python scripts/cost_barrier_certify.py --out data/recovery/wp7/COST_BARRIER_CERTIFICATION.json` | 0 | **CERTIFIED** (see §4) |
| lint | `python -m ruff check <thirteen touched files>` | 0 | All checks passed |
| types | `python -m mypy <seven scripts>` | 0 | Success: no issues found |
| global suite | `python -m pytest -m "not slow and not market" -q` | 0 | **3390 passed, 3 deselected** |

The three deselected tests are the rehearsal and its two sabotage cases: they are marked
`slow` and were run explicitly (§3).

## 3. The clean-checkout rehearsal — the claim this work package adds

`scripts/clean_checkout_rehearsal.py --scope full` was run on the committed candidate.
It creates a **detached worktree of the commit**, verifies both input bundles, runs the
producers and the lane's contract and determinism tests, rebuilds both artefacts, runs the
cost-barrier gate and the adversarial sweep, compares the rebuilt artefacts with the
published ones, and finally asks the independent verifier to confirm the report inside
that worktree.

```json
{"status": "PASS", "commit": "e07ce6cc3c00", "runner": "LOCAL", "steps_failed": [],
 "published_paths_moved": [], "run_records_changed": [],
 "inputs_modified_in_the_checkout": [], "exit_code": 0}
```

| what the rehearsal found | value |
| --- | --- |
| artefacts whose state reproduces | 4/4 — the two JSON artefacts and their two rendered reports |
| artefacts whose bytes differ | 4/4, only in the moment — reported, not treated as a finding |
| inputs modified inside the checkout | none |
| runner | `LOCAL`; the same script in CI reports `GITHUB_ACTIONS` (`recovery-determinism.yml`) |

The two sabotage runs (`--sabotage`, kept as
`evidence/SABOTAGE_EVIDENCE_COPY.json` and `evidence/SABOTAGE_COMMITTED_INPUT.json`) both
end `SABOTAGE_DETECTED`, exit 0, detected by the **input guard**: the rehearsed checkout
contained `M data/recovery/wp8/evidence/inputs/TIMEFRAME_AUDIT.json` and `M tasks/decisions.md`
respectively. That guard is the detector that can actually fire for this lane: every declared
input is read from HEAD (§4), so a mutation inside the checkout is invisible to the steps
themselves — the guard is what sees it. A green rehearsal can therefore fail, and the failure
is recorded with the path that caused it.

## 4. The two defects the rehearsal found (and the chain they forced)

The rehearsal earned its place by failing three times before it passed, each failure a real
defect rather than a nuisance:

1. **The coverage summaries embedded the machine.** The two frozen price series are
   gitignored by policy, and the view published `resolved_from: LOCAL_MATERIALIZATION` when
   they existed here and `ABSENT` when they did not, inside a field that is part of the
   identity. `scripts/recovery_input_evidence.py` now resolves that route to a stable token
   (the presence is reported next to it, in the volatile part), and the rendered report's
   per-machine observation section is declared volatile next to the moment line.
   Fixed in `6c3af00`; consequence: both artefacts were regenerated.
2. **The cost-barrier lane pinned the audit's bytes.** Regenerating the audit moved a pin
   that could only ever be satisfied on the machine that wrote it — the same defect WP-8 had
   just removed from the recovery lane, found here by a rehearsal crossing lanes. The explorer
   now publishes a `state_sha256` next to the byte pin, the gate judges a state-pinned input
   on its state, and the producers were re-captured in the same commit (`279d73f`). The chain
   was re-pinned and re-verified (`66dc3de`, `279d73f`) and the WP-7 record re-issued:
   `CERTIFIED` on `e07ce6c`, `dirty_watched_paths: []`, 93 lane tests passed, gate
   `FULL_REPRODUCTION_PASS`, adversarial `EVALUATED` 17/17, fingerprint `0cfdb13e…`, with a
   `supersession` block naming the record it replaced (`bd607266…` on `081ee7a`).
3. **The sabotage detector could not fire** (`272df9f`). The two sabotage proofs were
   expected to be caught by the bundle verify step and the artefact comparison; both read
   from HEAD, so neither could see a mutation made inside the checkout. The rehearsal now
   guards that only the artefacts it reproduces and its own run records may change, and both
   sabotage targets are detected by that guard — with the mutation path named in the report.

Also corrected in this series: C14 of the recovery verifier demanded an evidence copy for the
two declared-only datasets, which by declaration never need one (`6cac3c6`); it now requires
that their authority lives in the commit and that nothing has promoted them into a
finding-bearing input, with control N13 showing that branch firing.

## 5. Independent verification

`python scripts/recovery_verify.py` → **PASS**, exit 0, head `e07ce6c`:
**17/17 checks**, **13/13 negative controls detected**, `builder_imported: false`,
`false_success: 0`. The verifier's record is
[../INDEPENDENT_VERIFICATION.json](../INDEPENDENT_VERIFICATION.json). Its C17 is satisfied by
the rehearsal report of §3 (`rehearsed_commit` an ancestor of HEAD, 4 artefacts identical).

## 6. Artefacts of this run

| artefact | what it is |
| --- | --- |
| `evidence/BASELINE_REPRODUCTION.json` | the failures, recorded before the fix |
| `evidence/INPUT_EVIDENCE.json` + `evidence/inputs/` | the committed, digest-pinned authority for every external input |
| `evidence/ECONOMIC_INVARIANCE.json` | the before/after comparison that shows no finding moved |
| `evidence/SABOTAGE_EVIDENCE_COPY.json`, `evidence/SABOTAGE_COMMITTED_INPUT.json` | the two proofs that the rehearsal can fail |
| `RECOVERY_RUNTIME_AUTHORITY_MAP.md` | every input, its class and its authority |
| `CAMPAIGN_STATE_DETERMINISM_AUDIT.md` | the demonstrated causes and the repairs |
| `ACTIVE_RECOVERY_REPRODUCIBILITY.md` | the audit's provenance repair and its invariance proof |
| `CLEAN_CHECKOUT_REHEARSAL_REPORT.json` / `.md` | the rehearsal on the candidate commit |
| `../INDEPENDENT_VERIFICATION.json` | the verifier's record (17 checks + 13 controls) |

## 7. What is *not* claimed

- No strategy is profitable, admitted or promotable: `admitted_for_paper = 0` before and
  after the repair (`evidence/ECONOMIC_INVARIANCE.json`).
- The invariance evidence proves the repair moved no published finding; it is not a statement
  that the findings are correct. RFC-049 remains `DISCOVERY_CAMPAIGN_FAILED` with the sealed
  OOS  `CANCELLED_NOT_OPENED` (`SEALED_OOS = CANCELLED_NOT_OPENED`).
- The rehearsal recorded here ran on one operating system. The cross-platform claim rests on
  the content digests (LF-normalised) and on the CI run of the same versioned script
  (`.github/workflows/recovery-determinism.yml`), which reports `runner: GITHUB_ACTIONS`; the
  workflow is committed but has not been executed on a GitHub runner from this machine.
- The WP-7 record was re-issued twice during this work package while the chain was being
  fixed; only the final re-issue is committed, and its `supersession` block names the record
  it replaced. The intermediate attempt lived in the working tree and is not part of the
  published history.
