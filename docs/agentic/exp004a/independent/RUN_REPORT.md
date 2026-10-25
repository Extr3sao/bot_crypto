# Run report — EXP-004A independent verification (WP-051-02)

**Run:** `verifier-b/EXP-004A/WP-051-02:2026-10-21T10:26:12.509519Z` · **Status:** `FAIL` · **Promotion:** `NO_PROMOTION`
**Evaluated commit:** `47116b2f2c5fd37ed1a60550eefe17d8bd703638` (tree `51394aa9efc02ba7ddc595428419253d3b229857`)
**Verifier implementation:** `35cdf88ec40e671d6eaac43cdabbf3e1b77a8b9f58f0a7068afd6fad5c4eb6d9`
**Environment:** win32, Python 3.11.15, 263 dirty entries in the shared tree

## Claims

| Claim | Status | Reason |
| --- | --- | --- |
| C-000 | BLOCKED | INDEPENDENCE_NOT_PROVEN |
| C-001 | PASS | — |
| C-002 | PASS | — |
| C-003 | PASS | — |
| C-004 | FAIL | ADMISSION_REPLAY_MISMATCH |
| C-005 | PASS | — |
| C-006 | PASS | — |
| C-007 | BLOCKED | COST_SCOPE_UNPROVEN |
| C-008 | PASS | — |
| C-009 | PASS | — |
| C-010 | PASS | — |
| C-011 | PASS | — |
| C-012 | PASS | — |
| C-013 | BLOCKED | TIME_PROOF_WEAK |
| C-014 | PASS | — |

Totals: 11 PASS, 1 FAIL, 3 BLOCKED.

## Measurements

- Verifier acceptance suite: 20 passed in 23.53s
- Builder suites re-executed: 128 passed, 1 skipped in 223.98s (0:03:43)
- `FALSE_SUCCESS`: 0 · source mutations: 0 · economic executions: 0
- Promotion blocks: PHASE2_CAPTURE_OPEN, INSUFFICIENT_ADMITTED_DAYS, DECLARED_SIZE_NOT_WALKED, ZERO_ADMITTED_DAYS_INSIDE_CAPTURE_WINDOW, BLOCKED_MISSING_INDEPENDENT_VERIFIER

## Artifacts (sha256)

- `ACCEPTANCE_DECISION.json` — `5c42deedadb97c09822655f93bc73168b1609b0cb59ee1c924242663b82eac77`
- `ADVERSARIAL_TEST_REPORT.md` — `2936f3f00ffe8d3cd05460720ac3ee07edbad626bda2a64f2a6e3fe511e3a690`
- `CLAIM_VERDICTS.json` — `b74ac974c899b52e2ca5a5ec5d2c98184e682f220dc0cab7392352a24708d5b4`
- `DIGEST_RECONCILIATION.json` — `5a7d55a20f1ee5170fbdbd80ceab8388da07e3532f77c4ecf52901148697c0e1`
- `FINAL_REPORT.md` — `fd3d1f3aaebfe6024f06eca34aca3bc756468dd968309ba1eeff6979f6cd5df6`
- `INDEPENDENT_VERIFICATION_REPORT.json` — `19974cc07d2531b2b7eaa854f4467441eb6861984878ff6476978f27e050c563`
- `INDEPENDENT_VERIFICATION_REPORT.md` — `86bdf006158788148126d8023b57b24077d84e028c17cf69f441b2a2b56a4cc8`
- `RUNTIME_VALIDATION.md` — `b9fa508527f412fa54fa4fcc72b5c09b840f59214efe626550af819c2a074436`
- `SOURCE_INVENTORY.json` — `fd6a3feb8a0a4a757efbdb50027f5e3aad7cf9f076eb126fef3444576b7207f4`

_the audit ran before its own commit existed; scripts/exp004a_verify.py at sha256 35cdf88ec40e671d6eaac43cdabbf3e1b77a8b9f58f0a7068afd6fad5c4eb6d9 is the binding link between this report and the code that produced it_
