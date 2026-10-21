# WP-051-02D independent verification

**Verifier**: `verifier-c/EXP-004A/WP-051-02D` (not `builder/EXP-004A/WP-051-02D`)  
**HEAD at verification**: `583c66379a26b6924e1ebb07488866825b45d865`  
**Declaration**: `config/preregistrations/EXP-004A.datasets.phase2.json` at `a179ed0d74bfc5fd00383b2d575c9949ca6e1f95`  
**Status**: `PASS`

| Control | Status | Failed checks |
| --- | --- | --- |
| `TECHNICAL_VERIFICATION` | `PASS` | - |
| `PROVENANCE_VERIFICATION` | `PASS` | - |
| `TEMPORAL_VERIFICATION` | `PASS` | - |
| `ARTIFACT_INTEGRITY` | `PASS` | - |
| `POLICY_COMPLIANCE` | `PASS` | - |

## Checks

### TECHNICAL_VERIFICATION — PASS

| Check | Status | Detail |
| --- | --- | --- |
| `V-TECH-01` | `PASS` | every required field is present |
| `V-TECH-02` | `PASS` | only generator_code_commit differs from phase 1 |
| `V-TECH-03` | `PASS` | 2026-10-22T00:00:00Z to 2027-01-20T00:00:00Z |
| `V-TECH-04` | `PASS` | every entry still invokes the declared command |
| `V-TECH-05` | `PASS` | st6:tape exit 2 |
| `V-TECH-06` | `PASS` | positive fixture exit 0, verbatim=True, provenance=yes |
| `V-TECH-07` | `PASS` | empty window exit 3 |
| `V-TECH-08` | `PASS` | pre-effective fixture exit 5 |
| `V-TECH-09` | `PASS` | the declared window is non-empty |

### PROVENANCE_VERIFICATION — PASS

| Check | Status | Detail |
| --- | --- | --- |
| `V-PROV-01` | `PASS` | fc036d967923f09a6092cb0e5de7409afd07ebd7 -> fc036d967923f09a6092cb0e5de7409afd07ebd7 |
| `V-PROV-02` | `PASS` | blob sha256 af1ab7cc23980dad... vs declared af1ab7cc23980dad... |
| `V-PROV-03` | `PASS` | would run 052832c2252a719c63d0859628ada648c799c6ce / commit holds 052832c2252a719c63d0859628ada648c799c6ce |
| `V-PROV-04` | `PASS` | generator commit is an ancestor of HEAD |
| `V-PROV-05` | `PASS` | phase-1 blob 8946f871a97b7575..., successor cites 8946f871a97b7575..., disk 8946f871a97b7575... |
| `V-PROV-06` | `PASS` | phase-1 blob 43c9deea29a8e4af1c0333bcc0b58131620ec3e7 / HEAD blob 43c9deea29a8e4af1c0333bcc0b58131620ec3e7 / dirty=False |

### TEMPORAL_VERIFICATION — PASS

| Check | Status | Detail |
| --- | --- | --- |
| `V-TEMP-01` | `PASS` | issued 2026-10-21T15:20:56.000Z <= effective 2026-10-21T16:00:00.000Z <= window 2026-10-22T00:00:00.000Z |
| `V-TEMP-02` | `PASS` | declaration commit a179ed0d74bfc5fd00383b2d575c9949ca6e1f95 dated 2026-10-21T15:21:23.000Z |
| `V-TEMP-03` | `PASS` | declaration commit is an ancestor of HEAD |
| `V-TEMP-04` | `PASS` | the committed declaration is the file on disk |
| `V-TEMP-05` | `PASS` | no capture exists, so no retroactive validity is claimed |
| `V-TEMP-06` | `PASS` | the extractor calls authorize() and eligibility_defects() before writing |

### ARTIFACT_INTEGRITY — PASS

| Check | Status | Detail |
| --- | --- | --- |
| `V-ART-01` | `PASS` | 8 artefacts present |
| `V-ART-02` | `PASS` | every artefact is committed and unmodified |
| `V-ART-03` | `PASS` | the builder's reported declaration and generator digests recompute |

### POLICY_COMPLIANCE — PASS

| Check | Status | Detail |
| --- | --- | --- |
| `V-POL-01` | `PASS` | original declaration blob 43c9deea29a8e4af1c0333bcc0b58131620ec3e7 is the phase-1 blob |
| `V-POL-02` | `PASS` | promotion NO_PROMOTION, prior verifier FAIL, decision file unchanged=True |
| `V-POL-03` | `PASS` | BUILDER != VERIFIER and the verifier imports neither the package nor the preflight |
| `V-POL-04` | `PASS` | the extractor holds no network client or credential |
| `V-POL-05` | `PASS` | preregistration unchanged=True, experiment EXP-004A |

## Limits

- No prospective capture exists yet: the window opens 2026-10-22, so this verifies the binding and the refusals, not any observed market day.
- No external timestamp attestation is available; the chronology rests on Git ancestry plus the bar store's own fetched_at_ms. C-013 stays TIME_PROOF_WEAK.
- PASS here is not an authorisation, a 90-day validation or a promotion.
