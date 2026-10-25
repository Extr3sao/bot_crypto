# Reproducibility comparison — WP-ECONOMIC-RECOVERY-002

- commit under measurement: `64fa5112ebdea81291dbc5db07512cc8737feeb0` (branch `repro/economic-recovery-002`; this file lives in a later commit by construction)
- python: 3.11.15

## Method

the clean checkout is a real `git clone` at the commit under test, not `git archive HEAD | tar -x`: the archive has no .git, which made 17 of the 21 nodes the previous work package attributed to the clean checkout fail for the method's reason (9 of them in test_recovery_determinism.py alone).

| tree | failed | passed | rewritten tracked files |
| --- | --- | --- | --- |
| working tree | 90 | 1848 | 0 |
| clean clone | 90 | 1847 | 0 |

## The nodes previously attributed to the clean checkout

| outcome | working tree | clean clone | node |
| --- | --- | --- | --- |
| explained | PASSED | PASSED | `tests/unit/research/test_active_recovery_wp.py::test_audit_is_deterministic_and_committed` |
| explained | PASSED | PASSED | `tests/unit/research/test_active_recovery_wp.py::test_state_view_is_deterministic` |
| explained | PASSED | PASSED | `tests/unit/research/test_cost_barrier_ci_parity.py::test_tests_ci_and_the_runtime_all_run_the_same_bytes` |
| explained | PASSED | PASSED | `tests/unit/research/test_cost_barrier_ci_parity.py::test_the_producer_pins_survive_a_checkout_that_rewrites_line_endings` |
| explained | PASSED | PASSED | `tests/unit/research/test_economic001_evidence_closure.py::test_the_closure_is_not_inside_the_commit_it_names` |
| explained | PASSED | PASSED | `tests/unit/research/test_economic001_evidence_closure.py::test_the_delivery_commit_carries_exactly_the_six_deliverables` |
| explained | PASSED | PASSED | `tests/unit/research/test_economic001_evidence_closure.py::test_the_verification_artefact_stays_inside_its_own_vocabulary` |
| explained | PASSED | PASSED | `tests/unit/research/test_recovery_determinism.py::test_a_sabotaged_committed_input_is_detected` |
| explained | PASSED | PASSED | `tests/unit/research/test_recovery_determinism.py::test_a_sabotaged_evidence_copy_is_detected` |
| explained | PASSED | PASSED | `tests/unit/research/test_recovery_determinism.py::test_an_uncommitted_edit_to_a_committed_document_cannot_move_the_identity` |
| explained | PASSED | PASSED | `tests/unit/research/test_recovery_determinism.py::test_every_evidence_copy_reproduces_the_published_authority` |
| explained | PASSED | PASSED | `tests/unit/research/test_recovery_determinism.py::test_no_source_of_either_artefact_came_from_the_working_tree` |
| explained | PASSED | PASSED | `tests/unit/research/test_recovery_determinism.py::test_repeated_reproduction_is_byte_identical` |
| explained | PASSED | PASSED | `tests/unit/research/test_recovery_determinism.py::test_the_clean_checkout_rehearsal_passes_on_this_commit` |
| explained | PASSED | PASSED | `tests/unit/research/test_recovery_determinism.py::test_the_published_artefacts_report_reproducibility_invariants` |
| explained | PASSED | PASSED | `tests/unit/research/test_recovery_determinism.py::test_the_repair_moved_no_economic_finding` |
| explained | PASSED | PASSED | `tests/unit/research/test_rfc046_discovery_proposal.py::test_rfc_045_stays_empty_by_control` |
| explained | PASSED | PASSED | `tests/unit/research/test_st6_scheduler.py::test_a_second_writer_refuses_and_makes_no_market_request` |
| explained | PASSED | PASSED | `tests/unit/research/test_st6_scheduler.py::test_an_impossible_cadence_refuses_with_a_non_zero_status` |
| explained | PASSED | PASSED | `tests/unit/research/test_st6_scheduler.py::test_the_run_log_is_compact_self_consistent_and_unique` |
| explained | PASSED | PASSED | `tests/unit/research/test_st6_scheduler.py::test_the_run_log_records_who_invoked_the_tick` |

- nodes that only fail in the working tree: **0**
- nodes that only fail in the clean clone: **0**
- the suite rewrites no tracked file: **True**
