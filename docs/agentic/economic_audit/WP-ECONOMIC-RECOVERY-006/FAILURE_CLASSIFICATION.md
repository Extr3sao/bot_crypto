# Clasificación de fallos preexistentes

- XML: `C:\Users\GVLLFR0035\Downloads\WP005_OUT\w006_full_suite.xml`
- Total: 85 (71 fallos, 14 errores)

| categoría | nº |
| --- | --- |
| `MISSING_VERSIONED_ARTIFACT` | 41 |
| `EVIDENCE_DIGEST_MISMATCH` | 18 |
| `UNTRIAGED_ASSERTION` | 18 |
| `FIXTURE_INVENTORY_GAP` | 8 |

## MISSING_VERSIONED_ARTIFACT (41)

| artefacto ausente | tests | versionado |
| --- | --- | --- |
| `reports/profitability_gate035/FINAL_REPORT.json` | 14 | False |
| `reports/rfc035/search_round_3/RULE_CONTRACT_AUDIT.json` | 5 | False |
| `data/raw/alpha003/price/BTCUSDT_5m.json` | 3 | False |
| `reports/profitability_gate035/INDEPENDENT_VERIFICATION.json` | 2 | False |
| `reports/rfc035/search_round_3/FINAL_REPORT.json` | 2 | False |
| `reports/rfc035/search_round_3/INDEPENDENT_VERIFICATION.json` | 2 | False |
| `data/raw/alpha003/price/BTCUSDT_15m.json` | 1 | False |
| `reports/profitability_gate035/FINAL_REPORT.md` | 1 | False |
| `reports/profitability_gate035/SEARCH_POSTMORTEM.md` | 1 | False |
| `reports/profitability_gate035/ECONOMIC_FEASIBILITY.md` | 1 | False |
| `reports/profitability_gate035/ALTERNATIVE_PATHS.md` | 1 | False |
| `reports/profitability_gate035/INDEPENDENT_VERIFICATION.md` | 1 | False |
| `reports/rfc035/search_round_3/BASELINE.json` | 1 | False |
| `reports/rfc035/search_round_3/CANDIDATE_DEEP_DIVE.json` | 1 | False |
| `reports/rfc035/search_round_3/ECONOMIC_EVIDENCE.json` | 1 | False |
| `reports/rfc035/search_round_3/REJECTION_LOG.json` | 1 | False |
| `data/raw/alpha003/price/ETHUSDT_1h.json` | 1 | False |
| `reports/rfc046/CAMPAIGN_DETAIL.json` | 1 | False |
| `data/st6/ST6_HEALTH_STATUS.json` | 1 | False |

## FIXTURE_INVENTORY_GAP (8)

| test | detalle |
| --- | --- |
| `tests.unit.research.test_sprint024_stats::test_shock_event_is_the_frozen_detector` | a test double iterates a dataset combination that does not exist |
| `tests.unit.research.test_sprint024_stats::test_signal_values_are_in_int8_set` | a test double iterates a dataset combination that does not exist |
| `tests.unit.research.test_sprint024_stats::test_signals_are_point_in_time[shock_trend_continuation]` | a test double iterates a dataset combination that does not exist |
| `tests.unit.research.test_sprint024_stats::test_signals_are_point_in_time[shock_confirm_followthrough]` | a test double iterates a dataset combination that does not exist |
| `tests.unit.research.test_sprint024_stats::test_signals_are_point_in_time[shock_range_location]` | a test double iterates a dataset combination that does not exist |
| `tests.unit.research.test_sprint024_stats::test_forward_from_entry_is_nan_near_end` | a test double iterates a dataset combination that does not exist |
| `tests.unit.research.test_sprint024_stats::test_run_hypothesis_is_deterministic` | a test double iterates a dataset combination that does not exist |
| `tests.unit.research.test_sprint026_execution::test_candidate_replay_is_deterministic_and_reconciles` | a test double iterates a dataset combination that does not exist |

## EVIDENCE_DIGEST_MISMATCH (18)

| test | detalle |
| --- | --- |
| `tests.unit.research.test_alpha_expansion_manifests::test_frozen_manifest_present_and_pre_registered[EXP-ARP-013]` | recorded digest differs from the bytes it names |
| `tests.unit.research.test_alpha_expansion_manifests::test_frozen_manifest_present_and_pre_registered[EXP-ARP-014]` | recorded digest differs from the bytes it names |
| `tests.unit.research.test_alpha_expansion_manifests::test_frozen_manifest_present_and_pre_registered[EXP-ARP-015]` | recorded digest differs from the bytes it names |
| `tests.unit.research.test_alpha_recovery_manifests::test_frozen_manifest_is_present_and_pre_registered[EXP-ARP-007]` | recorded digest differs from the bytes it names |
| `tests.unit.research.test_alpha_recovery_manifests::test_frozen_manifest_is_present_and_pre_registered[EXP-ARP-010]` | recorded digest differs from the bytes it names |
| `tests.unit.research.test_alpha_recovery_v1_4_manifests::test_frozen_manifest_present_and_pre_registered[EXP-ARP-009]` | recorded digest differs from the bytes it names |
| `tests.unit.research.test_alpha_recovery_v1_4_manifests::test_frozen_manifest_present_and_pre_registered[EXP-ARP-011]` | recorded digest differs from the bytes it names |
| `tests.unit.research.test_alpha_recovery_v1_4_manifests::test_frozen_manifest_present_and_pre_registered[EXP-ARP-012]` | recorded digest differs from the bytes it names |
| `tests.unit.research.test_arp009_exp021_pit::test_frozen_manifest_matches_corpus_digest` | recorded digest differs from the bytes it names |
| `tests.unit.research.test_arp013_exp023_spec::test_dataset_fingerprint_matches_frozen_corpus` | recorded digest differs from the bytes it names |
| `tests.unit.research.test_cost_drift_monitor::test_every_window_keeps_its_raw_bytes_and_the_hash_matches` | recorded digest differs from the bytes it names |
| `tests.unit.research.test_economic001_evidence_closure::test_the_verified_bytes_are_the_shipped_bytes` | recorded digest differs from the bytes it names |
| `tests.unit.research.test_economic001_evidence_closure::test_every_deliverable_hash_matches_the_repository` | recorded digest differs from the bytes it names |
| `tests.unit.research.test_economic001_evidence_closure::test_the_report_bytes_still_match_the_rfc046_verification` | recorded digest differs from the bytes it names |
| `tests.unit.research.test_economic001_evidence_closure::test_the_two_tolls_are_distinct_and_the_historical_one_is_frozen` | recorded digest differs from the bytes it names |
| `tests.unit.research.test_rfc046_economic_gate::test_artefacts_exist_and_are_verified_clean` | recorded digest differs from the bytes it names |
| `tests.unit.research.test_rfc046_economic_gate::test_the_rfc046_confirmations_match_the_recorded_artefacts` | recorded digest differs from the bytes it names |
| `tests.unit.risk.test_futures_independent_verifier::test_verifier_reproduces_a_real_approval` | recorded digest differs from the bytes it names |

## UNTRIAGED_ASSERTION (18)

| test | detalle |
| --- | --- |
| `tests.unit.research.test_alpha_recovery_v1_4_manifests::test_split_firewall_never_opens_oos_when_validation_fails` | tests\unit\research\test_alpha_recovery_v1_4_manifests.py:128: AssertionError |
| `tests.unit.research.test_arp009_exp021_pit::test_frozen_contract_passes` | tests\unit\research\test_arp009_exp021_pit.py:223: AssertionError |
| `tests.unit.research.test_arp010_exp022_pit::test_frozen_contract_passes` | tests\unit\research\test_arp010_exp022_pit.py:216: AssertionError |
| `tests.unit.research.test_arp011_exp019_pit::test_frozen_contract_passes` | tests\unit\research\test_arp011_exp019_pit.py:199: AssertionError |
| `tests.unit.research.test_exp004a_wp051_02k::test_contract_reads_the_frozen_window` | tests\unit\research\test_exp004a_wp051_02k.py:441: AssertionError |
| `tests.unit.research.test_profitability_gate035::test_all_deliverables_exist_and_are_not_empty` | tests\unit\research\test_profitability_gate035.py:59: AssertionError |
| `tests.unit.research.test_rfc035s3_strategy_closure::test_the_eight_required_deliverables_exist` | tests\unit\research\test_rfc035s3_strategy_closure.py:75: AssertionError |
| `tests.unit.research.test_rfc035s3_strategy_closure::test_the_integrity_manifest_re_derives` | tests\unit\research\test_rfc035s3_strategy_closure.py:172: AssertionError |
| `tests.unit.research.test_rfc046_discovery_proposal::test_all_requested_deliverables_exist_and_are_not_empty` | tests\unit\research\test_rfc046_discovery_proposal.py:94: AssertionError |
| `tests.unit.research.test_rfc046_discovery_proposal::test_pit_enforcement_is_mechanical_and_rooted_in_a_real_defect` | tests\unit\research\test_rfc046_discovery_proposal.py:298: AssertionError |
| `tests.unit.research.test_rfc047_windows_evidence::test_the_verifier_shares_no_code_with_the_builder_and_passes` | tests\unit\research\test_rfc047_windows_evidence.py:799: AssertionError |
| `tests.unit.research.test_rfc047_windows_evidence::test_the_eighteen_controls_reject_the_manipulations_and_accept_the_honest_state` | tests\unit\research\test_rfc047_windows_evidence.py:812: AssertionError |
| `tests.unit.research.test_rfc047_windows_evidence::test_the_verifier_notices_a_host_that_disagrees_with_the_audit` | tests\unit\research\test_rfc047_windows_evidence.py:837: AssertionError |
| `tests.unit.research.test_st6_scheduler::test_the_task_definition_matches_the_repository_and_the_host` | tests\unit\research\test_st6_scheduler.py:202: AssertionError |
| `tests.unit.research.test_st6_scheduler::test_every_ended_slot_is_accounted_for_and_nothing_is_reconstructed` | tests\unit\research\test_st6_scheduler.py:286: AssertionError |
| `tests.unit.research.test_st6_scheduler::test_the_scheduler_report_agrees_with_its_verification` | tests\unit\research\test_st6_scheduler.py:883: AssertionError |
| `tests.unit.research.test_st6_scheduler::test_the_close_replay_is_isolated_and_passes_on_the_shipped_state` | tests\unit\research\test_st6_scheduler.py:971: AssertionError |
| `tests.unit.risk.test_futures_independent_verifier::test_executed_artifacts_verify_when_present` | tests\unit\risk\test_futures_independent_verifier.py:206: AssertionError |
