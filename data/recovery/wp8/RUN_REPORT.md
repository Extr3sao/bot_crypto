# RUN REPORT — WP-8 / RECOVERY DETERMINISM, STATE AUTHORITY & CLEAN CHECKOUT

- phase: **WP-8** (follows WP-7, the cost-barrier lane)
- branch: `main` · mode: OFFLINE — no keys, no orders, no capital, no live path
- the work package changed how this lane *reads* its inputs, not what it concludes
- FALSE_SUCCESS = 0 · BUILDER ≠ VERIFIER · TEST_TARGET == RUNTIME_TARGET
- LIVE_TRADING = DISABLED · PAPER_PROMOTION = NOT_AUTHORIZED

The commits that carry the implementation are recorded in §5 of
[FINAL_REPORT.md](FINAL_REPORT.md), which is where the "which commit is which" question
belongs. This file records **what was executed and what it returned**.

## 1. The failures this run had to remove

Captured before any test was edited, in three trees
(`evidence/BASELINE_REPRODUCTION.json`):

| tree | HEAD | result |
| --- | --- | --- |
| shared working tree | `33512b5` | 1 failed, 25 passed — `test_state_view_is_deterministic` |
| clean worktree of HEAD | `33512b5` | **3 failed**, 23 passed — all eight external inputs absent |
| clean worktree of the pre-WP-7 baseline | `38b8e18` | **3 failed**, 23 passed — the same three |

The three failing nodes in a clean checkout:

1. `test_state_view_is_deterministic`
2. `test_audit_is_deterministic_and_committed`
3. `test_audit_records_the_paper_lane_failure_honestly`

A suite that is green where it was written and red where it is checked out is the shape of
the defect: the lane's published numbers were a function of the machine, not of the commit.
The causes are enumerated in [CAMPAIGN_STATE_DETERMINISM_AUDIT.md](CAMPAIGN_STATE_DETERMINISM_AUDIT.md) §2
and the input classes in [RECOVERY_RUNTIME_AUTHORITY_MAP.md](RECOVERY_RUNTIME_AUTHORITY_MAP.md).

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
| lane contract tests | `python -m pytest tests/unit/research/test_active_recovery_wp.py -q` | 0 | **28 passed** |
| determinism regressions | `python -m pytest tests/unit/research/test_recovery_determinism.py -q` | 0 | **14 collected** (11 fast + 3 rehearsal) |
| CI parity contract | `python -m pytest tests/unit/research/test_recovery_ci_parity.py -q` | 0 | **8 passed** |
| lint | `python -m ruff check <ten touched files>` | 0 | All checks passed |
| types | `python -m mypy <five scripts + the new producer>` | 0 | Success: no issues found |
| global suite | `python -m pytest -m "not slow and not market" -q` | 0 | **3381 passed, 3 deselected** |

The three deselected tests are the rehearsal and its two sabotage cases: they are marked
`slow` and are executed by the clean-checkout path below and by CI.

## 3. The sequence that runs on the committed candidate

The rehearsal refuses to report on a tree that is dirty, and three of its tests are
`slow`, so the following is run **on the candidate commit** (`C` in §5 of the final
report) and its outcome — not this report — is the claim:

| step | command | outcome lands in |
| --- | --- | --- |
| clean-checkout rehearsal | `python scripts/clean_checkout_rehearsal.py --scope full --json` | `CLEAN_CHECKOUT_REHEARSAL_REPORT.json` / `.md` |
| the two sabotage cases | `python -m pytest tests/unit/research/test_recovery_determinism.py -m slow -q` | the same report's `sabotage` block |
| independent verification | `python scripts/recovery_verify.py` | `data/recovery/INDEPENDENT_VERIFICATION.json` |

The rehearsal builds the artefacts in a **detached worktree of the commit**, compares them
with the published ones byte for byte (content digests, so a CRLF checkout is not a
difference), and runs the independent verifier inside that worktree, where the verifier's
C17 requires the rehearsal report it is confirming to exist.

## 4. Artefacts of this run

| artefact | what it is |
| --- | --- |
| `evidence/BASELINE_REPRODUCTION.json` | the failures, recorded before the fix |
| `evidence/INPUT_EVIDENCE.json` + `evidence/inputs/` | the committed, digest-pinned authority for every external input |
| `evidence/ECONOMIC_INVARIANCE.json` | the before/after comparison that shows no finding moved |
| `RECOVERY_RUNTIME_AUTHORITY_MAP.md` | every input, its class and its authority |
| `CAMPAIGN_STATE_DETERMINISM_AUDIT.md` | the four demonstrated causes and the repairs |
| `ACTIVE_RECOVERY_REPRODUCIBILITY.md` | the audit's provenance repair and its invariance proof |
| `CLEAN_CHECKOUT_REHEARSAL_REPORT.json` / `.md` | the rehearsal on the candidate commit |
| `data/recovery/INDEPENDENT_VERIFICATION.json` | the independent verifier's record (C1–C17 + 12 controls) |

## 5. What is *not* claimed

- No strategy is profitable, admitted or promotable. `admitted_for_paper = 0` before and
  after the repair (`evidence/ECONOMIC_INVARIANCE.json`).
- The invariance evidence proves the repair moved no published finding; it is not a
  statement that the findings are correct — that is the verifier's and the contract tests'
  job, and RFC-049 remains `DISCOVERY_CAMPAIGN_FAILED` with the sealed OOS
  `CANCELLED_NOT_OPENED`.
- The rehearsal run recorded here executed on one operating system. The cross-platform
  claim rests on the content digests (LF-normalised) and on the CI run of the same
  versioned script (`.github/workflows/recovery-determinism.yml`, `runner: GITHUB_ACTIONS`),
  not on the local run.
