# DEF-H5-GOV-002 — SELF_FINGERPRINT_MISMATCH

Status: **REJECTED** (outcome A — no mismatch exists)

## Resolution

| Field | Value |
| --- | --- |
| AUTHORITATIVE_BLOB_SHA256 | `29ececb759aff059282a0324b3b94b4bcd13b35b51060c6c742f2eaa48db0a86` |
| Retrieved from | `git cat-file blob a1eee0d287d6ce335024cb850251bd1e34d13e17` (commit `c426b35`) |
| manifest_sha256 embedded in contaminated file | `29ececb759aff059282a0324b3b94b4bcd13b35b51060c6c742f2eaa48db0a86` |
| Match | **true** |
| INTERNAL_FINGERPRINT_VALID | **true** |

## Interpretation

- The manifest's self-declared `manifest_sha256` equals the SHA256 of its own committed
  prereg bytes. The frozen file was self-consistent.
- Post-execution mutation of the working tree (DEF-H5-GOV-001) never invalidated the
  committed authority — the mutated copy simply repeated the committed fingerprint while
  adding post-execution state around it.
- Governance rule reaffirmed: the embedded fingerprint is **secondary confirmation only**.
  Restoration authority is the committed blob at `c426b35`, which is what was used.

## Evidence

- `H5_PREREG_RESTORATION_REPORT.json` (P0, P2 sections)
- `evidence/H5_MANIFEST_PREREG_C426B35.json` — byte-identical to the committed blob
- `evidence/H5_MANIFEST_GEN3_WRONG_RESTORE_DFD89A28.json` — preserved generation-3 state

## Hard constraint honored

The committed prereg blob was NOT rewritten to make hashes agree; no hash was "fixed".
The blob was retrieved and used as-is.
