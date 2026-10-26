# ALPHA RESEARCH PLAYBOOK

canonical tracked document (RFC-034 §52)
as_of_commit = 38b97009deeea83b120b4039b00feca1845db475
generated_at = 2026-10-05T11:26:52Z

This is the default workflow for any future candidate. A future research RFC may
only be created after an external opportunity passes the ALPHA ADMISSION
SCORECARD (see `reports/strategy-closure/ALPHA_ADMISSION_SCORECARD.md` and
`ALPHA_REENTRY_POLICY.md`).

## Stage 0 — SOURCE / CLAIM / MECHANISM (§53)
No code yet. Identify the external evidence (>= 2 independent sources when they
exist, at least one peer-reviewed / credible working paper / exchange research /
independent replication / audited experiment). Social media is not sufficient.

## Stage 1 — DATA FEASIBILITY / TRADABILITY / COST FLOOR (§54)
Check historical depth, PIT availability, instrument tradability, transaction-cost
evidence, universe feasibility and survivorship. Compute HEADROOM_RATIO =
expected gross edge / realistic estimated cost. Kill early.

## Stage 2 — FAITHFUL REPRODUCTION (§55)
Reproduce the original effect exactly. No adaptation, no tuning.

## Stage 3 — DISCOVERY (§56)
Only after faithful reproduction.

## Stage 4 — VALIDATION (§57)
On unseen data with a pre-registered spec. Fail → STOP.

## Stage 5 — ROBUSTNESS (§58)
Walk-forward, temporal stability, cost stress, parameter stability, asset/regime
robustness as relevant.

## Stage 6 — HOLDOUT (§59)
Untouched holdout.

## Stage 7 — CERTIFICATION (§60)
Tradability, universe, cost, PIT and independent reproduction via the RFC-032
`CandidateCertificationGate`. Verifier checks (reproduction/hash/PIT/accounting/
contract) are separate from the economic gates (see verification semantics).

## Stage 8 — FORWARD PAPER (§61)
Fresh evidence only.

## Stage 9 — CANARY / LIVE READINESS (§62)
Only after forward success. Requires explicit human approval.

## Definitions

- VALIDATED NET EDGE (§63): net > 0 after realistic costs on unseen Validation
  with executable instruments.
- ROBUST EDGE (§64): Validation PASS + walk-forward + temporal stability + cost
  stress + parameter stability + asset/regime robustness.
- PAPER CANDIDATE (§65): robust edge + untouched holdout PASS + tradability PASS
  + independent verification PASS.
- PROFITABLE (§66): NEVER used for a Discovery winner, a historical backtest, a
  Validation-only result or a paper candidate.
- FORWARD_PAPER_PROFITABLE (§67): only after sufficient fresh paper evidence.
- LIVE_PROFITABLE (§68): only after real executed trades, real costs,
  reconciliation and a sufficient live sample. No current strategy qualifies.

## Gate order (§34)
DATA → REPRODUCTION → DISCOVERY → VALIDATION → ROBUSTNESS → HOLDOUT → CERTIFICATION → PAPER → FORWARD_EVIDENCE → CANARY → LIVE

No later gate compensates an earlier one.
