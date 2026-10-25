# CLEAN CHECKOUT REHEARSAL REPORT (WP-8E)

- rehearsed commit `e07ce6cc3c00` · runner `LOCAL` · scope `full`
- **status: PASS**
- started `2026-10-11T18:51:11Z` · finished `2026-10-11T18:53:16Z`

The sequence runs in a detached worktree of the commit, never in the tree it was invoked
from: a pass here is a claim about the commit.

## Steps

| step | expected exit | actual | result |
| --- | ---: | ---: | --- |
| `verify_recovery_input_bundle` | 0 | 0 | **PASS** |
| `verify_cost_barrier_bundle` | 0 | 0 | **PASS** |
| `materialize_cost_barrier_input` | 0 | 0 | **PASS** |
| `run_active_economic_audit` | 0 | 0 | **PASS** |
| `run_campaign_state_view` | 0 | 0 | **PASS** |
| `run_contract_tests` | 0 | 0 | **PASS** |
| `run_determinism_tests` | 0 | 0 | **PASS** |
| `run_cost_barrier_gate` | 0 | 0 | **PASS** |
| `run_adversarial_sweep` | 0 | 0 | **PASS** |
| `run_independent_verifier` | 0 | 0 | **PASS** |

## Artefacts (state must be reproduced byte for byte)

The comparison is made on the state: the JSON documents minus the moment, the
commit and the per-machine source table, and the rendered reports minus the one
line that carries the moment. The raw byte digests are shown too - two rebuilds
of one commit differ there by construction.

| artefact | published state | regenerated state | identical | bytes identical |
| --- | --- | --- | --- | --- |
| `data/recovery/CAMPAIGN_STATE_VIEW.json` | `e7bee5d8b710` | `e7bee5d8b710` | **True** | False |
| `data/recovery/CAMPAIGN_STATE_VIEW_REPORT.md` | `7920b77b99a9` | `7920b77b99a9` | **True** | False |
| `data/recovery/ACTIVE_ECONOMIC_AUDIT.json` | `023b66ffd121` | `023b66ffd121` | **True** | False |
| `data/recovery/ACTIVE_ECONOMIC_AUDIT.md` | `62a57a9ad25d` | `62a57a9ad25d` | **True** | False |

## What moved

- published artefacts whose state moved: none
- artefacts whose bytes the rebuild rewrote (the moment): ['M data/recovery/ACTIVE_ECONOMIC_AUDIT.json', 'M data/recovery/ACTIVE_ECONOMIC_AUDIT.md', 'M data/recovery/CAMPAIGN_STATE_VIEW.json', 'M data/recovery/CAMPAIGN_STATE_VIEW_REPORT.md']
- **inputs modified inside the checkout: none**
- run records that legitimately differ: none
- excluded from the state comparison: document keys ['generated_at_utc', 'payload_sha256', 'head', 'branch', 'sources', 'local_observations']; report lines starting ['- generated `']; report sections containing ['Local observations (volatile']
- line-ending-only differences encountered: True

## Limitations

- this run proves the commit reproduces in a clean checkout and that the input authority resolves from the commit; it does not prove the derivation is correct - that is the verifier's and the contract tests' job
- the rehearsal was executed on one operating system; the cross-platform claim rests on the content digests, which are taken over LF-normalised content, and not on this run
