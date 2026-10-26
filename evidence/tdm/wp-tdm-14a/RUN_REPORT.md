# RUN_REPORT — RFC-TDM-014A

**Veredicto:** `VERIFIED_PORTABLE_FULL_REPLAY`
**Baseline:** `04fb8bc8a0900c278cd72c5e3478a45b66fcbc03` · **HEAD:** `a806a7bf6866c38a03c6545e04f0512e3a016952` · **Rama:** `fix/tdm14a`

## Commits

- `a806a7bf Publish the regenerated deliverables and the closing report`
- `d7185a21 Render the closing report from the verdict instead of writing it by hand`
- `409050c3 Close the second evidence commit against its own blobs`
- `49c89696 Re-verify after the custody fix: twelve of twelve`
- `d93408e8 Stop the custody check from mangling the first dirty path`
- `5f42de14 Close the first evidence commit against its own blobs`
- `f8ae0243 Replay TDM-12 from scratch twice and publish the evidence`
- `7a4593cb Keep the sealed TDM-13 inputs byte-identical in a CRLF checkout`
- `04b02c2d Fingerprint the committed blob so a checkout cannot rename the code`

## Criterios de aceptación

| ACC | estado |
| --- | --- |
| ACC-01 | PASS |
| ACC-02 | PASS |
| ACC-03 | PASS |
| ACC-04 | PASS |
| ACC-05 | PASS |
| ACC-06 | PASS |
| ACC-07 | PASS |
| ACC-08 | PASS |
| ACC-09 | PASS |
| ACC-10 | PASS |
| ACC-11 | PASS |
| ACC-12 | PASS |

## Ejecuciones

| run_id | EOL | estado | duración | fases | outputs |
| --- | --- | --- | --- | --- | --- |
| `tdm14a-lf-20261025T181821Z` | `false` | PASS | 419.7 s | {'review': 'PASS', 'inventory': 'PASS'} | 5/5 |
| `tdm14a-crlf-20261025T182823Z` | `true` | PASS | 386.1 s | {'review': 'PASS', 'inventory': 'PASS'} | 5/5 |

## Tests

- suites: tests/unit/research (whole directory) plus a targeted run of the new and directly affected suites
- pasados: 43 · fallados: 0 · exit: 0
- duración: 7.39 s

## Controles negativos

| control | estado | exit |
| --- | --- | --- |
| `source_tamper` | PROVEN | 1 |
| `source_staged_tamper` | PROVEN | 1 |
| `untracked_module` | PROVEN | 1 |
| `unreadable_blob` | PROVEN | 1 |
| `dataset_byte_tamper` | PROVEN | 1 |
| `economic_value_tamper` | PROVEN | 1 |
| `timeout_and_process_tree` | PROVEN | 1 |
| `evidence_digest_tamper` | PROVEN | 1 |
| `v1_v2_rejection` | PROVEN | 1 |
| `stale_output_injection` | PROVEN | 1 |

**10/10 demostrados**

## Compatibilidad v1

- estado: PASS
- diferencias con el registro publicado: 0
- CSV idéntico: True
- históricos intactos: {'CANDIDATE_REGISTRY.json': True, 'CANDIDATE_REGISTRY.csv': True, 'DATA_WINDOW_REGISTRY.json': True, 'RUN_REPORT.json': True}

## Defectos

| id | estado | detalle |
| --- | --- | --- |
| `D-01` | FIXED | v1 hashed working-tree bytes, so the same blob produced two identities under LF and CRLF; v2 hashes the blob (ACC-02 reproduced, ACC-03 fixed). |
| `D-02` | DOCUMENTED, NOT REWRITTEN | tdm12_inventory.py hardcoded source_commit='504256ec' as a literal, so no TDM-12 artefact recorded the commit it actually ran at. v2 derives it from git HEAD; v1 keeps the literal only to reproduce the published artefact. |
| `D-03` | FIXED | the sealed TDM-13 input bundle had no -text attribute, so a CRLF checkout delivered 189575 bytes instead of 189574 and the replay could not start. Fixed in .gitattributes, which is why the CRLF run now reaches the pipeline. |
| `D-04` | FIXED IN THIS WORK, FOUND BY THE TESTS | the first v2 preflight used git status as its cleanliness oracle; on a CRLF checkout status reports ' M path' for content identical to the blob, which would have refused the only transformation the RFC tolerates. Replaced with content hash-object --path plus diff-index --cached. |
| `D-05` | OPEN, REPORTED | identity fields outside the registry (triage.json admission_ledger.sha256, runtime_entrypoints sha256) still hash working-tree bytes, so those scratch values remain EOL-sensitive. They are not published contracts and do not enter any ACC. |

## Órdenes y decisión

- `paper_orders = 0` · `live_orders = 0`
- `false_success = 0`
- decisión de mercado: NO_ELIGIBLE_CANDIDATE / REJECTED_ALPHA (inherited from TDM-11/12/13, untouched)

## Archivos cambiados desde la baseline

- `M	.gitattributes`
- `A	evidence/tdm/wp-tdm-14a/BASELINE_REPORT.json`
- `A	evidence/tdm/wp-tdm-14a/BASELINE_REPORT.md`
- `A	evidence/tdm/wp-tdm-14a/EOL_COMPARISON.json`
- `A	evidence/tdm/wp-tdm-14a/FINAL_REPORT.md`
- `A	evidence/tdm/wp-tdm-14a/FINGERPRINT_SCHEME_V2.md`
- `A	evidence/tdm/wp-tdm-14a/INPUT_MANIFEST.json`
- `A	evidence/tdm/wp-tdm-14a/LOG_MANIFEST.json`
- `A	evidence/tdm/wp-tdm-14a/NEGATIVE_CONTROLS.json`
- `A	evidence/tdm/wp-tdm-14a/OUTPUT_MANIFEST.json`
- `A	evidence/tdm/wp-tdm-14a/POST_COMMIT_CLOSURE.json`
- `A	evidence/tdm/wp-tdm-14a/REPLAY_REPORT.json`
- `A	evidence/tdm/wp-tdm-14a/REPLAY_REPORT.md`
- `A	evidence/tdm/wp-tdm-14a/RUN_REPORT.json`
- `A	evidence/tdm/wp-tdm-14a/RUN_REPORT.md`
- `A	evidence/tdm/wp-tdm-14a/TEST_RESULTS.json`
- `A	evidence/tdm/wp-tdm-14a/run-logs/crlf/inventory.log.txt`
- `A	evidence/tdm/wp-tdm-14a/run-logs/crlf/review.log.txt`
- `A	evidence/tdm/wp-tdm-14a/run-logs/lf/inventory.log.txt`
- `A	evidence/tdm/wp-tdm-14a/run-logs/lf/review.log.txt`
- `A	evidence/tdm/wp-tdm-14a/run-logs/tests/pytest-base.log.txt`
- `A	evidence/tdm/wp-tdm-14a/run-logs/tests/pytest-head-crlf.log.txt`
- `A	evidence/tdm/wp-tdm-14a/run-logs/tests/pytest-head-lf.log.txt`
- `A	evidence/tdm/wp-tdm-14a/run-logs/tests/pytest-targeted-closure.log.txt`
- `A	evidence/tdm/wp-tdm-14a/run-logs/tests/pytest-targeted-final.log.txt`
- `A	evidence/tdm/wp-tdm-14a/run_crlf.json`
- `A	evidence/tdm/wp-tdm-14a/run_lf.json`
- `A	evidence/tdm/wp-tdm-14a/v1_compat.json`
- `A	evidence/tdm/wp-tdm-14a/verification_result.json`
- `M	scripts/tdm12_inventory.py`
- `A	scripts/tdm14a_baseline.py`
- `A	scripts/tdm14a_negative_controls.py`
- `A	scripts/tdm14a_replay.py`
- `A	scripts/tdm14a_report.py`
- `A	scripts/tdm14a_v1_compat.py`
- `A	scripts/tdm14a_verify.py`
- `A	src/trading_bot/research/source_fingerprint.py`
- `A	tests/unit/research/test_source_fingerprint.py`
- `A	tests/unit/research/test_tdm14a_report.py`
- `A	tests/unit/research/test_tdm14a_verifier.py`
