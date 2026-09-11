# H6 EXTERNAL VERIFIER PACKAGE — Track Q2

**Purpose:** enable a genuinely independent verifier (different agent/model/session, no builder role) to certify the H6 preregistration. The builder (buffy-agent) cannot certify its own prereg: `H6_SELF_VERIFICATION = PASS` is **self**-verification only. Until an external verdict arrives, checkpoint status is `PENDING_INDEPENDENT_VERIFICATION` (correct governance, not a failure).

## Contents

| File | Role |
| --- | --- |
| `H6_EXTERNAL_VERIFIER_PACKAGE.json` | machine-readable inputs: exact paths, SHA256s, expected invariants, test commands, forbidden outcomes, verdict schema |
| `H6_EXTERNAL_VERIFIER_PROMPT.md` | ready-to-run verifier instructions (copy into the independent agent) |

## Key facts

- **Prereg commit:** `e683e04e5df39d0f2f5feb6097664536b93cc636` (descendants allowed iff `git diff e683e04 -- <artifact>` is EMPTY for every prereg artifact)
- **OI freeze commit:** `256bd5ec6b82242c0b52e70a96dcd19edda61aa7`
- **Spec SHA256:** `f514fecf42b52d2e1c2946cac9dee94b2570d485cb236b9a6c663f46f5bbf148`
- **Manifest SHA256:** `345334c3107860a56fcbc8b2ec04a01e70b81b09ee551a54eeaf4a566b2cb29d`
- **OI dataset fingerprint:** `16779b7d2eff0dc9e56015c444c2dbe7b67ef083e6cf1877a024a6de74098d99`
- **H6_EXECUTIONS = 0 · H6_BACKTESTS = 0 · PERFORMANCE_OBSERVED = false**

## Independent-verifier checklist (summary)

1. recompute spec/manifest/whitelist SHA256 vs `H6_PREREG_COMMIT_RECORD.json`; `git diff` empty vs prereg commit
2. recompute the OI dataset fingerprint from the validity ledger → `16779b7d…`
3. verify all canonical semantics (expansion-only, 1h, no stop/cooldown, 10 bps TOTAL RT, funding excluded-with-limitation, orthogonality 0.50, MAD z-definition, z ≥ +1.0, N 30/100, all statistical gates, causal eligibility language)
4. verify counters zero and no realized-performance fields
5. run the three test commands (focused ×2 + full hermetic FAILED=0)
6. verify H5 immutability hashes
7. return the mandatory verdict JSON (`FINAL_VERDICT`: PASS | FAIL | BLOCKED_INSUFFICIENT_EVIDENCE)

Only `FINAL_VERDICT = PASS` allows `H6_INDEPENDENT_VERIFICATION = PASS` and opens `H6-INDEPENDENT-IMPLEMENTATION-AND-DISCOVERY-01`.
