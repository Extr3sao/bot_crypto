# TEST_BASELINE_COMPARISON — WP-ECONOMIC-BLOCKER-001

Commit: `e67194e79a42` on `audit/economic-blocker-001`  ·  Python 3.11.15

## Method

The same pytest selection is run twice: once in this working tree, once in a
clean checkout produced by `git archive HEAD` (no untracked files, no local
`reports/**`), with `PYTHONPATH` pointed at the checkout's own `src` and the
import path asserted so the run cannot silently import this tree's package.

The run is split into three phases (`--phase working|clean|healthy`) plus
`--phase assemble`, so it fits inside a command timeout without changing what
is measured.

- clean checkout imported its own source: **True**
- `src/`, `tests/`, `config/` modified by this WP: **none**

## Results

| Run | `unit/risk` + `unit/research` |
| --- | --- |
| working tree | error=14, failed=89, passed=1845, skipped=30 (exit 1) |
| clean checkout | error=14, failed=110, passed=1824, skipped=30 (exit 1) |

Healthy sets (`tests/unit/autonomous`, `tests/unit/paper`, `tests/unit/scanner`): passed=447 (exit 0)

- every working-tree failure also fails on the clean checkout: **True**
- identical failing node IDs: **False**
- preexisting failures (intersection): **103**
- only in working tree (would be a regression caused by this WP): 0
- only in clean checkout (depends on unversioned local state): 21

## Conclusion

every test that fails in this working tree also fails on a clean checkout of the same commit, so none of the failures is caused by this work package.

The extra failures in the clean checkout are the interesting ones: they are tests
whose *pass* depends on artefacts that exist only in a developer's working tree
(`reports/**` and similar). They are listed below rather than hidden, because a
green local run there is not reproducible evidence.

Side finding: `data/st6/RFC047_RUNTIME_VERIFICATION.json` is tracked, and two of the
research tests rewrite it while running. The suite therefore mutates repository
state; that file was restored to `HEAD` after this measurement so the WP leaves no
side effects.

### Failing only on the clean checkout

- `FAILED tests/unit/research/test_active_recovery_wp.py::test_audit_is_deterministic_and_committed`
- `FAILED tests/unit/research/test_active_recovery_wp.py::test_state_view_is_deterministic`
- `FAILED tests/unit/research/test_cost_barrier_ci_parity.py::test_tests_ci_and_the_runtime_all_run_the_same_bytes`
- `FAILED tests/unit/research/test_cost_barrier_ci_parity.py::test_the_producer_pins_survive_a_checkout_that_rewrites_line_endings`
- `FAILED tests/unit/research/test_economic001_evidence_closure.py::test_the_closure_is_not_inside_the_commit_it_names`
- `FAILED tests/unit/research/test_economic001_evidence_closure.py::test_the_delivery_commit_carries_exactly_the_six_deliverables`
- `FAILED tests/unit/research/test_economic001_evidence_closure.py::test_the_verification_artefact_stays_inside_its_own_vocabulary`
- `FAILED tests/unit/research/test_recovery_determinism.py::test_a_sabotaged_committed_input_is_detected`
- `FAILED tests/unit/research/test_recovery_determinism.py::test_a_sabotaged_evidence_copy_is_detected`
- `FAILED tests/unit/research/test_recovery_determinism.py::test_an_uncommitted_edit_to_a_committed_document_cannot_move_the_identity`
- `FAILED tests/unit/research/test_recovery_determinism.py::test_every_evidence_copy_reproduces_the_published_authority`
- `FAILED tests/unit/research/test_recovery_determinism.py::test_no_source_of_either_artefact_came_from_the_working_tree`
- `FAILED tests/unit/research/test_recovery_determinism.py::test_repeated_reproduction_is_byte_identical`
- `FAILED tests/unit/research/test_recovery_determinism.py::test_the_clean_checkout_rehearsal_passes_on_this_commit`
- `FAILED tests/unit/research/test_recovery_determinism.py::test_the_published_artefacts_report_reproducibility_invariants`
- `FAILED tests/unit/research/test_recovery_determinism.py::test_the_repair_moved_no_economic_finding`
- `FAILED tests/unit/research/test_rfc046_discovery_proposal.py::test_rfc_045_stays_empty_by_control`
- `FAILED tests/unit/research/test_st6_scheduler.py::test_a_second_writer_refuses_and_makes_no_market_request`
- `FAILED tests/unit/research/test_st6_scheduler.py::test_an_impossible_cadence_refuses_with_a_non_zero_status`
- `FAILED tests/unit/research/test_st6_scheduler.py::test_the_run_log_is_compact_self_consistent_and_unique`
- `FAILED tests/unit/research/test_st6_scheduler.py::test_the_run_log_records_who_invoked_the_tick`
