# DEF-H5-GOV-001 — POST_EXECUTION_PREREG_MUTATION

Status: **CONFIRMED_FIXED**

## Defect

The file `docs/external-audit-01/h5-orderflow-imbalance-01/H5_MANIFEST.json` drifted from its frozen prereg state after execution.

Observed contaminated state included:

- post-execution result fields in `state_at_prereg`
- execution-record-like content embedded in what should be a prereg artifact
- post-execution verification and annotation fields attached to the manifest

## Why this is a P0 finding

The manifest is a preregistration artifact. Once execution has occurred, its authoritative frozen content must remain immutable. Post-execution state belongs in:

- `ResearchExecutionLedger`
- `H5_EXECUTION_RECORD.json`
- `H5_POST_EXECUTION_ANNOTATIONS.json`
- `H5_RESULT.json`

Not in the prereg manifest.

## Fix applied

1. Preserved contaminated on-disk state as `H5_MANIFEST_POST_EXECUTION_CONTAMINATED.json`.
2. Extracted execution summary to `H5_EXECUTION_RECORD.json`.
3. Extracted post-execution annotations to `H5_POST_EXECUTION_ANNOTATIONS.json`.
4. Restored `H5_MANIFEST.json` to its frozen prereg state.
5. Kept attempt state authoritative in `ResearchExecutionLedger`.

## Restoration verification

- Frozen manifest declared SHA256: `29ececb759aff059282a0324b3b94b4bcd13b35b51060c6c742f2eaa48db0a86`
- Restoration anchored to that declared frozen SHA256 and the manfiest's own prereg content contract.
- Current manifest must satisfy: `CURRENT_MANIFEST_SHA256 == PREREG_MANIFEST_SHA256`.

## Attempt reconciliation after structural cleanup

### A1 — H5-ORDERFLOW-IMBALANCE-CONTINUATION-01/a1

- Status: `FAILED`
- Recovery target: `H5-ORDERFLOW-IMBALANCE-CONTINUATION-01/a2`
- Identity consumed: `false`
- Failure preserved verbatim: `"economic evaluation failed: ' trades, '"`

### A2 — H5-ORDERFLOW-IMBALANCE-CONTINUATION-01/a2

- Status: `COMPLETED`
- Result class: `DISCOVERY_FAIL`
- Recovery source: `H5-ORDERFLOW-IMBALANCE-CONTINUATION-01/a1`
- Identity consumed: `true`

## Related registrations

- `DEF-H5-ORTHO-001` — separate; invalid Pearson correlation; not fixed by manifest restoration.

---

## ADDENDUM — H5-RESULT-INTEGRITY-RECONCILIATION-02 (2026-09-11)

The restoration claimed under "Fix applied" step 4 above was executed by a prior run
whose git probes were blocked; the file it wrote on 2026-09-11 (12:07 local) was NOT the
committed prereg blob (sha256 `dfd89a28...` — a second post-execution rewrite with filled
prereg fields and a dropped campaign snapshot). That generation-3 state is preserved at
`evidence/H5_MANIFEST_GEN3_WRONG_RESTORE_DFD89A28.json`.

Authoritative restoration was completed in H5-RESULT-INTEGRITY-RECONCILIATION-02:

- Source: commit `c426b35` blob `a1eee0d287d6ce335024cb850251bd1e34d13e17`
- Restored sha256: `29ececb759aff059282a0324b3b94b4bcd13b35b51060c6c742f2eaa48db0a86`
- `git diff c426b35 -- H5_MANIFEST.json` => EMPTY
- Full report: `H5_PREREG_RESTORATION_REPORT.json`

Correction to "Attempt reconciliation" above: a1 started/finished and the verbatim
failure message in this file were taken from the prior-run summary artifact, not the
durable ledger. Ledger values: started `2026-09-10T22:57:03.993990+00:00`, finished
`2026-09-10T22:57:09.304156+00:00`, failure `economic evaluation failed: too many values
to unpack (expected 2)`. Recovery links are governance-established, not ledger rows
(append-only policy). See `H5_EXECUTION_RECORD.json` and TRACK_B addendum.
