# WP-EDGE-14F — independent verification

**VERIFICATION_PASS** — 12/12 checks, 30/30 tamperings detected.

The builder's modules are not imported for decisive arithmetic: `False`.

| check | result | detail |
| --- | --- | --- |
| `cost_share_is_same_population` | PASS | admission share 0.8592 (published 0.8592), cross-population ratio 1.3863 (published 1.3863), per-scenario identity holds: True |
| `admission_fee_never_exceeds_its_own_round_trip` | PASS | scenarios where the fee exceeds its own round trip: none |
| `the_two_frequencies_are_not_the_same_metric` | PASS | re-derived non-overlapping tape bound 48.018 (published 48.018); selector sum 144.061; selector > tape: True |
| `trade_funnel_recounts_from_the_ledger` | PASS | verifier counts 4 decisions (1 directional, 3 NO_TRADE), 4 settled, 42 disk vetoes; builder headline agrees: True |
| `live_status_is_verified_zero_not_assumed` | PASS | published live status VERIFIED_ZERO; order ledger present False; fill ledger present False; order-submitting actions 0; unaccounted exits 0 |
| `neutral_arm_reproduces_with_an_independent_implementation` | PASS | verifier: 98 trades, gross 21.975396, net -1.011204; builder: 98 trades, gross 21.975396, net -1.011204 |
| `no_backtest_fill_is_presented_as_a_paper_or_exchange_fill` | PASS | fill classes present in executed arms: ['BACKTEST_FILL'] |
| `every_published_artefact_digest_still_recomputes` | PASS | 47 artefacts digested, none stale: True; declared exclusions: ['ARTIFACT_MANIFEST.json', 'INDEPENDENT_VERIFICATION.json']; unlisted and undeclared: none |
| `every_rejected_candidate_names_its_duplicate` | PASS | 3 rejected (all with a stated reason: True), 1 retained |
| `pins_resolve_and_licences_come_from_the_licence_file` | PASS | 3/3 pins resolved; licence file read for all: True |
| `paper_was_blocked_without_relaxing_a_gate` | PASS | status PAPER_BLOCKED_BY_GATE, gates relaxed [], risk changed False, forward days waived 0 |
| `sabotage_matrix_all_detected` | PASS | 30/30 tamperings detected; undetected: none |

## Sabotage matrix

| id | tampering | kind | detected |
| --- | --- | --- | --- |
| S01 | fee_bps_and_percent_confused | TAMPER_DETECTED | True |
| S02 | duplicated_fee | TAMPER_DETECTED | True |
| S03 | spread_and_impact_double_counted | TAMPER_DETECTED | True |
| S04 | fabricated_rebate_as_a_negative_fee | TAMPER_DETECTED | True |
| S05 | funding_component_dropped | TAMPER_DETECTED | True |
| S06 | next_bar_price_used | TAMPER_DETECTED | True |
| S07 | higher_timeframe_still_open | TAMPER_DETECTED | True |
| S08 | available_at_in_the_future | TAMPER_DETECTED | True |
| S09 | utc_and_local_clock_mixed | TAMPER_DETECTED | True |
| S10 | ohlcv_altered | TAMPER_DETECTED | True |
| S11 | duplicated_fill | TAMPER_DETECTED | True |
| S12 | fill_without_a_broker | POLICY_ASSERTED | True |
| S13 | signal_counted_as_a_trade | TAMPER_DETECTED | True |
| S14 | no_trade_rows_hidden | TAMPER_DETECTED | True |
| S15 | veto_reason_erased | TAMPER_DETECTED | True |
| S16 | fabricated_zero_spread | TAMPER_DETECTED | True |
| S17 | invented_maker_fill | POLICY_ASSERTED | True |
| S18 | parser_confuses_perp_and_spot | TAMPER_DETECTED | True |
| S19 | unexecuted_arm_marked_as_executed | TAMPER_DETECTED | True |
| S20 | stale_digest_polished | TAMPER_DETECTED | True |
| S21 | spent_holdout_relabelled_fresh | TAMPER_DETECTED | True |
| S22 | multiple_testing_undisclosed | TAMPER_DETECTED | True |
| S23 | day_denominator_modified | TAMPER_DETECTED | True |
| S24 | per_day_results_replaced_by_mean | TAMPER_DETECTED | True |
| S25 | sample_noise_labelled_robust | TAMPER_DETECTED | True |
| S26 | licence_not_checked_before_clone | TAMPER_DETECTED | True |
| S27 | runtime_change_enabling_live | POLICY_ASSERTED | True |
| S28 | extrapolated_rate_relabelled_measured | TAMPER_DETECTED | True |
| S29 | non_authoritative_test_target | TAMPER_DETECTED | True |
| S30 | md_report_diverges_from_json | TAMPER_DETECTED | True |
