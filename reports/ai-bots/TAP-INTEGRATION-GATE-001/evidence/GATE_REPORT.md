# Integration gate report

- **Commit:** `9a420ff18179c1f196221495aba5fdd2a81f5073`
- **Branch:** `gate/integration-001`
- **Generated:** 2026-10-25T13:31:25Z
- **Label:** local:gate-001:9a420ff1:run3
- **Verdict:** `PASS` (certifies: True)
- **False success:** 0

## Steps

| Step | Status | Exit | Duration | Detail |
| --- | --- | ---: | ---: | --- |
| `G0_ENTRYPOINTS` | PASS | None | 0.0s | all present |
| `G1_TREE` | PASS | None | 0.0s | clean at 9a420ff18179 on gate/integration-001 |
| `C1_SUPERVISOR_CAMPAIGN` | PASS | 0 | 266.92s |  |
| `C2_SUPERVISOR_SCENARIOS` | PASS | 0 | 13.59s |  |
| `V1_SUPERVISOR_VERIFIER` | PASS | 0 | 5.61s |  |
| `C3_LOCK_CAMPAIGN` | PASS | 0 | 999.78s |  |
| `V2_LOCK_VERIFIER` | PASS | 0 | 4.38s |  |
| `A1_CAMPAIGN_AUDIT` | PASS | 0 | 0.56s |  |
| `J1_SUPERVISOR_CONTRACT` | PASS | None | 0.0s | verdict=PASS checks=33 mutations=12 undetected=0 false_success=0 |
| `J2_LOCK_CONTRACT` | PASS | None | 0.0s | verdict=PASS checks=32 mutations=9 undetected=0 false_success=0 |
| `J3_AUDIT_CLAIMS` | PASS | None | 0.0s | claims=5/5 fail=0 unknown=0 false_success=0 |
| `J4_CANDIDATE_BINDING` | PASS | None | 0.0s | supervisor.campaign=9a420ff18179 lock.campaign=9a420ff18179 supervisor.verifier=9a420ff18179 lock.verifier=9a420ff18179 |
| `J5_CAMPAIGN_SHAPE` | PASS | None | 0.0s | lock iterations=6 races=2 sites=['AFTER_CYCLE', 'BEFORE_CYCLE']; supervisor episodes=1 cycles=5 state=RECOVERED |
| `S1_COMMIT_STABLE` | PASS | None | 0.0s | head=9a420ff18179 observed=1 clean=True/True |
| `M1_MANIFEST` | PASS | None | 0.0s | all mandatory artefacts present |

## In one sentence

Both PAPER campaigns ran on this commit, their verifiers and an independent audit accepted what they wrote, and HEAD did not move while they ran.

## Limitations

- a PASS certifies the campaigns and the commit, not profitability or PAPER admission
- the gate runs on one host at a time; a second host is a second data point, not a substitute
- G1 stays OPEN_SIGNOFF: the gate does not sign a risk-policy change

A `PASS` here certifies that both PAPER campaigns, their verifiers, the independent
campaign audit and the commit-stability check ran on this commit and agreed. It does
not certify profitability, does not authorise PAPER admission and does not make this
workflow a required status check.
