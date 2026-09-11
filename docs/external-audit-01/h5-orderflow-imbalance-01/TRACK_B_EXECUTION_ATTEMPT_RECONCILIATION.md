# TRACK B — EXECUTION ATTEMPT RECONCILIATION

Canonical counts:

- `ECONOMIC_EXPERIMENT_IDS = 1`
- `EXECUTION_ATTEMPTS = 2`
- `FAILED_ATTEMPTS = 1`
- `COMPLETED_ATTEMPTS = 1`

## Attempts

### A1 — H5-ORDERFLOW-IMBALANCE-CONTINUATION-01/a1

- Status: `FAILED`
- Started: `2026-09-10T22:55:57.528925+00:00`
- Completed: `2026-09-10T22:55:57.547580+00:00`
- Failure reason: runner defect during economic evaluation
- Identity consumed: **no**

Note: A1 failed before completion, so the experiment identity was not consumed by A1.

### A2 — H5-ORDERFLOW-IMBALANCE-CONTINUATION-01/a2

- Status: `COMPLETED`
- Result class: `DISCOVERY_FAIL`
- Started: `2026-09-10T22:57:28.277869+00:00`
- Completed: `2026-09-10T22:57:42.608115+00:00`
- Identity consumed: **yes**, only completed attempt

## Recovery relationship

- A1 did not consume the identity.
- A2 therefore started on the same experiment identity.
- Recovery metadata in the manifest currently lists `recovered_by_attempt_id: null` for both rows.
- This is a documentation gap, not an economic-parameter divergence. The effective recovery is:
  - A2 is the effective recovery/completion of the failed A1 execution path.
- Recommended manifest correction: set `recovered_by_attempt_id` on A2 to `H5-ORDERFLOW-IMBALANCE-CONTINUATION-01/a1` if the manifest is ever edited for evidence clarity. Do not rewrite history; if edited, preserve the prior blob as evidence.

## Economic parameter identity

The following must be identical across A1 and A2 for the result to be valid:

- spec SHA256
- dataset SHA256
- protocol SHA256
- economic parameters

Manifest source of truth:

- `spec_sha256`: `c743fba4a2a589dc1c3a15c7cd48b1b6ddf80255b8a157ea4f7ef19cc2f81023`
- `dataset_sha256`: `3cb2d6ec1298533d53da50f2b9cc2ec2ff770733d89c2a1aceed758b705ec0ad`
- `protocol_sha256`: `4f63a6b11c7ddf31f3323c6e60e103e20cb04cf7f184a99d5b2b9349522ffa3d`
- `economic_parameters_unchanged_from_prereg`: `true`

Reconciliation conclusion: economic parameters and experiment identity are consistent across attempts. The only allowed divergence is the runner defect fixed between A1 and A2.

## Final completed attempt

- `final_completed_attempt_id = H5-ORDERFLOW-IMBALANCE-CONTINUATION-01/a2`
- This is the authoritative completed execution for H5.

---

## ADDENDUM — H5-RESULT-INTEGRITY-RECONCILIATION-02 (2026-09-11)

Corrections against the durable ledger (ledger wins; this document originally repeated
numbers from the prior-run summary artifact `H5_EXECUTION_RECORD.json`):

| Field | This doc said | Ledger (authoritative) |
| --- | --- | --- |
| a1 started | 2026-09-10T22:55:57.528925+00:00 | 2026-09-10T22:57:03.993990+00:00 |
| a1 completed | 2026-09-10T22:55:57.547580+00:00 | 2026-09-10T22:57:09.304156+00:00 |
| a1 failure_reason | "runner defect during economic evaluation" (paraphrase) | `economic evaluation failed: too many values to unpack (expected 2)` |
| a2 started | 2026-09-10T22:57:28.277869+00:00 | 2026-09-10T22:57:25.458561+00:00 |
| a2 completed | 2026-09-10T22:57:42.608115+00:00 | 2026-09-10T22:57:30.931333+00:00 |
| protocol_sha256 | 4f63a6b11c7ddf31f3323c6e60e103e20cb04cf7f184a99d5b2b9349522ffa3d | **8452c0cfd6f6b71feca6736e66158f9e7105e7924fc2deba6879c7d0716b8e92** (exact derivation of the frozen runner; 4f63a6b1 unsupported) |
| manifest "manifest correction" suggestion | set recovered_by_attempt_id on A2 | SUPERSEDED by append-only policy: ledger rows never rewritten; recovery links recorded in `H5_EXECUTION_RECORD.json` (governance-established) |

Also corrected here: the ledger `dataset_sha256` fields are EMPTY on all rows (runner
defect); the actual dataset fingerprint is anchored via `H5_RESULT.json →
dataset_sha256 = 3cb2d6ec1298533d53da50f2b9cc2ec2ff770733d89c2a1aceed758b705ec0ad`,
and H5_RESULT.json is itself ledger-anchored via a2 `result_sha256`.

Reconciliation outcome: canonical counts stand (1 / 2 / 1 / 1); spec & protocol hashes
identical across a1/a2; economic parameters unchanged; `CERTIFY_EXACTLY_ONCE_H5 = false`
(EVALUATION_ATTEMPTS not persisted; a1 died inside economic evaluation).
