# GATE MATRIX — TAP-INTEGRATION-GATE-001

Run `003` at commit `9a420ff18179c1f196221495aba5fdd2a81f5073`, branch `gate/integration-001`,
tree clean before and after, one commit observed for the whole run. Evidence:
`evidence/GATE_REPORT.json`, `evidence/EVIDENCE_MANIFEST.json` (258 files),
`REVIEW.json`.

## 1. The fifteen steps of the gate

| Step | What it asserts | Status | Exit | Duration |
| --- | --- | --- | ---: | ---: |
| `G0_ENTRYPOINTS` | all five entrypoints are present | PASS | – | 0.0 s |
| `G1_TREE` | the tree is clean before anything runs | PASS | – | 0.0 s |
| `C1_SUPERVISOR_CAMPAIGN` | the supervisor campaign runs on this commit | PASS | 0 | 266.9 s |
| `C2_SUPERVISOR_SCENARIOS` | corrupt evidence and exhausted budget are exercised | PASS | 0 | 13.6 s |
| `V1_SUPERVISOR_VERIFIER` | the supervisor verifier judges that campaign | PASS | 0 | 5.6 s |
| `C3_LOCK_CAMPAIGN` | six crash sites and two reclaim races, on this commit | PASS | 0 | 999.8 s |
| `V2_LOCK_VERIFIER` | the lock verifier judges that campaign | PASS | 0 | 4.4 s |
| `A1_CAMPAIGN_AUDIT` | an independent audit re-derives both campaigns | PASS | 0 | 0.6 s |
| `J1_SUPERVISOR_CONTRACT` | the supervisor report satisfies its contract | PASS | – | 0.0 s |
| `J2_LOCK_CONTRACT` | the lock report satisfies its contract | PASS | – | 0.0 s |
| `J3_AUDIT_CLAIMS` | `C1`, `L1` and both self-controls pass | PASS | – | 0.0 s |
| `J4_CANDIDATE_BINDING` | every artefact is bound to the candidate commit | PASS | – | 0.0 s |
| `J5_CAMPAIGN_SHAPE` | the campaigns have the shape the contract requires | PASS | – | 0.0 s |
| `S1_COMMIT_STABLE` | the commit did not move while the gate ran | PASS | – | 0.0 s |
| `M1_MANIFEST` | every artefact is hashed into a manifest | PASS | – | 0.0 s |

Sum of step durations **1290.8 s (21.5 min)**. Verdict `PASS`, `certifies: true`,
`false_success: 0`.

## 2. The numbers the judgements rest on

| Quantity | Contract floor | This run |
| --- | ---: | ---: |
| Supervisor checks applicable | 31 | **33** (0 not applicable) |
| Supervisor mutations detected | 8 | **12 / 12** |
| Lock checks | 32 | **32** |
| Lock mutations detected | 9 | **9 / 9** |
| Lock iterations | 6 | **6** |
| Lock reclaim races (one winner) | 2 | **2** |
| Lock reclaim fences | strictly advancing | **2, 5, 8, 11, 14, 17** |
| Lock stream rows / cycles / starts | – | **64 / 17 / 12** |
| Supervisor cycles / reclaims / rows | ≥ 2 cycles | **5 / 1 / 13** |
| Campaign commits equal `HEAD` | 4 | **4 / 4** |
| Undetected mutations, both verifiers | 0 | **0** |
| `false_success` | 0 | **0** |

## 3. Independent campaign audit (`evidence/CAMPAIGN_AUDIT.json`)

| Claim | Assertion | Status |
| --- | --- | --- |
| `C1` | five cycles, recovered, no lock, no live order, scenarios present | PASS |
| `L1` | six iterations reclaimed once each, six resumes exit 0, fences advance, no lock, no live order | PASS |
| `S1` | breaking one stream line makes `C1` fail | PASS |
| `S2` | removing `iteration-03/RECOVERY.json` makes `L1` fail | PASS |
| `V1` | both verifier reports match the bytes and their floors | PASS |

Audit verdict `PASS`, `false_success: 0`.

## 4. Negative controls (`REVIEW.json`, `controls`)

Each control runs on a temporary copy; the original evidence is never touched.

| Control | What it proves the gate refuses | Result |
| --- | --- | --- |
| `N0_LEGACY_EVIDENCE` | the 002 delivery's evidence is not this gate's evidence | rejected (exit 1, `GATE_REPORT.json missing`) |
| `N1_STALE_COMMIT` | evidence carrying another commit, with a rebuilt manifest | rejected (`COMMIT_MISMATCH`) |
| `N2_HEAD_MOVED` | a commit that moves while a command runs (real git repo) | rejected (`HEAD moved`) |
| `N3_ABSENT_RECOVERY` | a campaign missing one `RECOVERY.json` | rejected (`RECOVERY.json`) |
| `N4_MUTATED_EVIDENCE` | an edited report whose manifest was not updated | rejected (`MANIFEST_MISMATCH`) |
| `N5_PARTIAL_CAMPAIGN` | five iterations declared complete | rejected (`contract is 6`) |
| `N6_WEAKENED_REPORT` | a smaller report with the same PASS verdict and a rebuilt manifest | rejected (`STEP_DISAGREEMENT`) |
| `N7_SINGLE_VERIFIER_FAILURE` | one failing verifier while every other step passed | rejected (`VERDICT`) |

**8 / 8 controls rejected what they must reject.** Reviewer checks 9 / 9 PASS.

## 5. Acceptance criteria of the mission

| # | Criterion | Status | Evidence |
| ---: | --- | --- | --- |
| 1 | Both campaigns run correctly from a clean checkout | PASS (same host; clean tree) | `evidence/logs/C1_*.log`, `C3_*.log`; `tree.clean_before/after` |
| 2 | The verifiers detect real alterations | PASS | 12/12 and 9/9 mutations; `N3`, `N6`, `N7` |
| 3 | The gate rejects old evidence and different commits | PASS | `N0`, `N1`, `N2` |
| 4 | An independent verifier validates the result | PASS | `REVIEW.json` 9/9 checks, 8/8 controls, `false_success 0` |
| 5 | CI can invoke it automatically | WIRED, NOT EXECUTED | `.github/workflows/integration-gate.yml`; no GitHub runner was available here |
| 6 | Effective integration protection demonstrated or declared blocked | **GOVERNANCE_BLOCKED** | no `gh`, no token: branch protection cannot be read or set from here; `imposition.required_check: false` |
| 7 | No unauthorised change to runtime, risk or execution | PASS | the delivery adds `scripts/tap_*`, one test, docs and one workflow; `git diff --stat 7d18140c..HEAD` touches nothing in `src/` |

## 6. Invariants

| Invariant | Value |
| --- | --- |
| `FALSE_SUCCESS` | 0 |
| `BUILDER != VERIFIER` | `scripts/tap_integration_gate.py` (builder) vs `tools/review_gate.py` (reviewer, imports nothing from it) |
| `LIVE_ORDERS` | 0 (both campaigns, every stream row) |
| `PAPER_ADMISSION` | `NO_GO` |
| `G1` | `OPEN_SIGNOFF` (the gate does not sign a risk-policy change) |
| Historical lane | `codepaper/supervisor-001` (`3b758e22`, 301 commits) **not merged** |
| `main` | not moved (`e67194e7`) |

## 7. What is *not* in this matrix

* No GitHub Actions runner executed the workflow: the CI wiring is static and is checked by
  `R10_CI_WIRING` (workflow present, invokes gate and reviewer, no `continue-on-error`).
* The full `pytest tests/unit` suite was not run in this worktree; the gate's own tests (12)
  and the static checks were.
* Profitability, PAPER admission and any live behaviour are out of scope and unchanged.
