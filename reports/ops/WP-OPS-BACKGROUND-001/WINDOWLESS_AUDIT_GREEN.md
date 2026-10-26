# WINDOWLESS EXECUTION AUDIT

- generated `2026-10-18T18:42:05Z` · `win32`
- verdict **CLEAN** · HIGH `0`
- scanned: 1161 Python, 21 batch, 6 PowerShell; 9 files already use the helper

| severity | count |
| --- | ---: |
| MEDIUM | 324 |

## Findings

| severity | code | path:line | detail |
| --- | --- | --- | --- |
| MEDIUM | `RUN_WITHOUT_WINDOWLESS` | `logs/wp7_tmp/make_run_report.py:64` | subprocess without window suppression |
| MEDIUM | `RUN_WITHOUT_WINDOWLESS` | `logs/wp7_tmp/make_run_report.py:102` | subprocess without window suppression |
| MEDIUM | `RUN_WITHOUT_WINDOWLESS` | `logs/wp7_tmp/make_run_report.py:104` | subprocess without window suppression |
| MEDIUM | `RUN_WITHOUT_WINDOWLESS` | `logs/wp7_tmp/wp6_gate.py:221` | subprocess without window suppression |
| MEDIUM | `RUN_WITHOUT_WINDOWLESS` | `logs/wp7_tmp/wp6_gate.py:700` | subprocess without window suppression |
| MEDIUM | `RUN_WITHOUT_WINDOWLESS` | `logs/wp7_tmp/wp6_gate.py:703` | subprocess without window suppression |
| MEDIUM | `RUN_WITHOUT_WINDOWLESS` | `logs/wp8_tmp/capture_baseline.py:25` | subprocess without window suppression |
| MEDIUM | `RUN_WITHOUT_WINDOWLESS` | `logs/wp8_tmp/capture_baseline.py:29` | subprocess without window suppression |
| MEDIUM | `RUN_WITHOUT_WINDOWLESS` | `logs/wp8_tmp/diagnose_state_view.py:69` | subprocess without window suppression |
| MEDIUM | `RUN_WITHOUT_WINDOWLESS` | `logs/wp8_tmp/diagnose_state_view.py:75` | subprocess without window suppression |
| MEDIUM | `RUN_WITHOUT_WINDOWLESS` | `logs/wp8_tmp/diagnose_v2.py:28` | subprocess without window suppression |
| MEDIUM | `RUN_WITHOUT_WINDOWLESS` | `logs/wp8_tmp/diagnose_v3.py:30` | subprocess without window suppression |
| MEDIUM | `RUN_WITHOUT_WINDOWLESS` | `logs/wp8_tmp/diagnose_v3.py:35` | subprocess without window suppression |
| MEDIUM | `RUN_WITHOUT_WINDOWLESS` | `logs/wp8_tmp/diagnose_v3.py:40` | subprocess without window suppression |
| MEDIUM | `RUN_WITHOUT_WINDOWLESS` | `logs/wp8_tmp/economic_invariance.py:22` | subprocess without window suppression |
| MEDIUM | `RUN_WITHOUT_WINDOWLESS` | `logs/wp8_tmp/economic_invariance.py:35` | subprocess without window suppression |
| MEDIUM | `BAT_WITHOUT_WINDOWLESS` | `reports/alpha-recovery-v1-1/launch_campaign.bat:1` | batch launcher starts a console interpreter directly |
| MEDIUM | `BAT_WITHOUT_WINDOWLESS` | `reports/alpha-recovery-v1-1/run_gates.bat:1` | batch launcher starts a console interpreter directly |
| MEDIUM | `RUN_WITHOUT_WINDOWLESS` | `reports/alpha001/run_gates.py:44` | subprocess without window suppression |
| MEDIUM | `BAT_WITHOUT_WINDOWLESS` | `reports/paper-strategy-lifecycle-shadow-01/launch.bat:1` | batch launcher starts a console interpreter directly |
| MEDIUM | `BAT_WITHOUT_WINDOWLESS` | `reports/paper-strategy-lifecycle-shadow-02/launch.bat:1` | batch launcher starts a console interpreter directly |
| MEDIUM | `BAT_WITHOUT_WINDOWLESS` | `reports/source-runtime-verification/repro/run_pytest.bat:1` | batch launcher starts a console interpreter directly |
| MEDIUM | `BAT_WITHOUT_WINDOWLESS` | `reports/source-runtime-verification/repro/run_repro.bat:1` | batch launcher starts a console interpreter directly |
| MEDIUM | `BAT_WITHOUT_WINDOWLESS` | `reports/strategy-dynamic/run_exp.bat:1` | batch launcher starts a console interpreter directly |
| MEDIUM | `BAT_WITHOUT_WINDOWLESS` | `reports/strategy-lifecycle-gate0/run_exp.bat:1` | batch launcher starts a console interpreter directly |
| MEDIUM | `BAT_WITHOUT_WINDOWLESS` | `reports/strategy-lifecycle-hardening/run_checks.bat:1` | batch launcher starts a console interpreter directly |
| MEDIUM | `BAT_WITHOUT_WINDOWLESS` | `reports/strategy-lifecycle-hardening/run_exp.bat:1` | batch launcher starts a console interpreter directly |
| MEDIUM | `BAT_WITHOUT_WINDOWLESS` | `reports/strategy-lifecycle-persistence/run_checks.bat:1` | batch launcher starts a console interpreter directly |
| MEDIUM | `BAT_WITHOUT_WINDOWLESS` | `reports/strategy-lifecycle-router/run_exp.bat:1` | batch launcher starts a console interpreter directly |
| MEDIUM | `BAT_WITHOUT_WINDOWLESS` | `reports/strategy-lifecycle-verification/run_checks.bat:1` | batch launcher starts a console interpreter directly |
| MEDIUM | `BAT_WITHOUT_WINDOWLESS` | `reports/strategy-lifecycle-verification/run_exp.bat:1` | batch launcher starts a console interpreter directly |
| MEDIUM | `BAT_WITHOUT_WINDOWLESS` | `reports/strategy-lifecycle-verification/run_repro.bat:1` | batch launcher starts a console interpreter directly |
| MEDIUM | `BAT_WITHOUT_WINDOWLESS` | `reports/strategy-lifecycle-verification/run_zero_diag.bat:1` | batch launcher starts a console interpreter directly |
| MEDIUM | `BAT_WITHOUT_WINDOWLESS` | `reports/strategy-lifecycle/run_pytest.bat:1` | batch launcher starts a console interpreter directly |
| MEDIUM | `BAT_WITHOUT_WINDOWLESS` | `reports/wp-strat-08/data/run_repro_base.bat:1` | batch launcher starts a console interpreter directly |
| MEDIUM | `BAT_WITHOUT_WINDOWLESS` | `reports/wp-strat-08/data/run_research.bat:1` | batch launcher starts a console interpreter directly |
| MEDIUM | `BAT_WITHOUT_WINDOWLESS` | `reports/wp-strat-09/launch_canary.bat:1` | batch launcher starts a console interpreter directly |
| MEDIUM | `RUN_WITHOUT_WINDOWLESS` | `scripts/active_economic_audit.py:943` | subprocess without window suppression |
| MEDIUM | `RUN_WITHOUT_WINDOWLESS` | `scripts/active_economic_audit.py:944` | subprocess without window suppression |
| MEDIUM | `RUN_WITHOUT_WINDOWLESS` | `scripts/ai_bots_003c_capture.py:507` | subprocess without window suppression |
| MEDIUM | `RUN_WITHOUT_WINDOWLESS` | `scripts/ai_bots_verify.py:208` | subprocess without window suppression |
| MEDIUM | `RUN_WITHOUT_WINDOWLESS` | `scripts/ai_bots_verify.py:228` | subprocess without window suppression |
| MEDIUM | `RUN_WITHOUT_WINDOWLESS` | `scripts/alpha_diversified_verify.py:175` | subprocess without window suppression |
| MEDIUM | `RUN_WITHOUT_WINDOWLESS` | `scripts/alpha_expansion_v1.py:119` | subprocess without window suppression |
| MEDIUM | `RUN_WITHOUT_WINDOWLESS` | `scripts/alpha_recovery_v1_3.py:546` | subprocess without window suppression |
| MEDIUM | `RUN_WITHOUT_WINDOWLESS` | `scripts/alpha_recovery_v1_4.py:463` | subprocess without window suppression |
| MEDIUM | `RUN_WITHOUT_WINDOWLESS` | `scripts/arp007_oos.py:90` | subprocess without window suppression |
| MEDIUM | `RUN_WITHOUT_WINDOWLESS` | `scripts/arp008_post_oos_recovery.py:100` | subprocess without window suppression |
| MEDIUM | `RUN_WITHOUT_WINDOWLESS` | `scripts/arp009_exp_021.py:78` | subprocess without window suppression |
| MEDIUM | `RUN_WITHOUT_WINDOWLESS` | `scripts/arp010_exp_022.py:72` | subprocess without window suppression |
| MEDIUM | `RUN_WITHOUT_WINDOWLESS` | `scripts/arp011_exp_019.py:72` | subprocess without window suppression |
| MEDIUM | `RUN_WITHOUT_WINDOWLESS` | `scripts/arp012_verify_exp_019.py:77` | subprocess without window suppression |
| MEDIUM | `RUN_WITHOUT_WINDOWLESS` | `scripts/campaign_state_view.py:824` | subprocess without window suppression |
| MEDIUM | `RUN_WITHOUT_WINDOWLESS` | `scripts/campaign_state_view.py:825` | subprocess without window suppression |
| MEDIUM | `RUN_WITHOUT_WINDOWLESS` | `scripts/cap001_run.py:73` | subprocess without window suppression |
| MEDIUM | `RUN_WITHOUT_WINDOWLESS` | `scripts/cap004_campaign_runner.py:111` | subprocess without window suppression |
| MEDIUM | `RUN_WITHOUT_WINDOWLESS` | `scripts/cap004_campaign_runner.py:600` | subprocess without window suppression |
| MEDIUM | `RUN_WITHOUT_WINDOWLESS` | `scripts/cap004_verify.py:922` | subprocess without window suppression |
| MEDIUM | `RUN_WITHOUT_WINDOWLESS` | `scripts/cap004b_verify.py:158` | subprocess without window suppression |
| MEDIUM | `RUN_WITHOUT_WINDOWLESS` | `scripts/cap004c_migrate.py:55` | subprocess without window suppression |
| MEDIUM | `RUN_WITHOUT_WINDOWLESS` | `scripts/cap004c_verify.py:936` | subprocess without window suppression |
| MEDIUM | `RUN_WITHOUT_WINDOWLESS` | `scripts/clean_checkout_rehearsal.py:141` | subprocess without window suppression |
| MEDIUM | `RUN_WITHOUT_WINDOWLESS` | `scripts/clean_checkout_rehearsal.py:154` | subprocess without window suppression |
| MEDIUM | `RUN_WITHOUT_WINDOWLESS` | `scripts/cost_barrier_adversarial.py:174` | subprocess without window suppression |
| MEDIUM | `RUN_WITHOUT_WINDOWLESS` | `scripts/cost_barrier_adversarial.py:1099` | subprocess without window suppression |
| MEDIUM | `RUN_WITHOUT_WINDOWLESS` | `scripts/cost_barrier_certify.py:109` | subprocess without window suppression |
| MEDIUM | `RUN_WITHOUT_WINDOWLESS` | `scripts/cost_barrier_certify.py:120` | subprocess without window suppression |
| MEDIUM | `RUN_WITHOUT_WINDOWLESS` | `scripts/cost_barrier_certify.py:281` | subprocess without window suppression |
| MEDIUM | `RUN_WITHOUT_WINDOWLESS` | `scripts/cost_barrier_certify.py:300` | subprocess without window suppression |
| MEDIUM | `RUN_WITHOUT_WINDOWLESS` | `scripts/cost_barrier_evidence.py:157` | subprocess without window suppression |
| MEDIUM | `RUN_WITHOUT_WINDOWLESS` | `scripts/cost_barrier_explorer.py:100` | subprocess without window suppression |
| MEDIUM | `RUN_WITHOUT_WINDOWLESS` | `scripts/cost_barrier_explorer.py:879` | subprocess without window suppression |
| MEDIUM | `RUN_WITHOUT_WINDOWLESS` | `scripts/cost_barrier_explorer.py:881` | subprocess without window suppression |
| MEDIUM | `RUN_WITHOUT_WINDOWLESS` | `scripts/cost_barrier_gate.py:379` | subprocess without window suppression |
| MEDIUM | `RUN_WITHOUT_WINDOWLESS` | `scripts/cost_barrier_gate.py:1311` | subprocess without window suppression |
| MEDIUM | `RUN_WITHOUT_WINDOWLESS` | `scripts/cost_barrier_verify.py:480` | subprocess without window suppression |
| MEDIUM | `RUN_WITHOUT_WINDOWLESS` | `scripts/dependency_closure.py:25` | subprocess without window suppression |
| MEDIUM | `RUN_WITHOUT_WINDOWLESS` | `scripts/dependency_closure_files.py:27` | subprocess without window suppression |
| MEDIUM | `RUN_WITHOUT_WINDOWLESS` | `scripts/economic001_closure.py:187` | subprocess without window suppression |
| MEDIUM | `RUN_WITHOUT_WINDOWLESS` | `scripts/economic001_closure.py:192` | subprocess without window suppression |
| MEDIUM | `RUN_WITHOUT_WINDOWLESS` | `scripts/economic001_closure_verify.py:106` | subprocess without window suppression |
| MEDIUM | `RUN_WITHOUT_WINDOWLESS` | `scripts/economic001_closure_verify.py:129` | subprocess without window suppression |
| MEDIUM | `RUN_WITHOUT_WINDOWLESS` | `scripts/edge01_closure_report_check.py:274` | subprocess without window suppression |
| MEDIUM | `RUN_WITHOUT_WINDOWLESS` | `scripts/edge01_closure_report_check.py:286` | subprocess without window suppression |
| MEDIUM | `RUN_WITHOUT_WINDOWLESS` | `scripts/edge04_closure.py:372` | subprocess without window suppression |
| MEDIUM | `RUN_WITHOUT_WINDOWLESS` | `scripts/edge04r_verify.py:890` | subprocess without window suppression |
| MEDIUM | `RUN_WITHOUT_WINDOWLESS` | `scripts/edge04r_verify.py:920` | subprocess without window suppression |
| MEDIUM | `RUN_WITHOUT_WINDOWLESS` | `scripts/edge05_closure.py:68` | subprocess without window suppression |
| MEDIUM | `RUN_WITHOUT_WINDOWLESS` | `scripts/edge05r_regression.py:93` | subprocess without window suppression |
| MEDIUM | `RUN_WITHOUT_WINDOWLESS` | `scripts/edge05r_storage_inventory.py:226` | subprocess without window suppression |
| MEDIUM | `RUN_WITHOUT_WINDOWLESS` | `scripts/edge05r_storage_inventory.py:252` | subprocess without window suppression |
| MEDIUM | `RUN_WITHOUT_WINDOWLESS` | `scripts/edge05r_storage_reclaim.py:99` | subprocess without window suppression |
| MEDIUM | `RUN_WITHOUT_WINDOWLESS` | `scripts/edge05r_storage_reclaim.py:112` | subprocess without window suppression |
| MEDIUM | `RUN_WITHOUT_WINDOWLESS` | `scripts/edge06_report.py:65` | subprocess without window suppression |
| MEDIUM | `RUN_WITHOUT_WINDOWLESS` | `scripts/edge06_report.py:79` | subprocess without window suppression |
| MEDIUM | `RUN_WITHOUT_WINDOWLESS` | `scripts/edge06_verify.py:251` | subprocess without window suppression |
| MEDIUM | `RUN_WITHOUT_WINDOWLESS` | `scripts/edge06_verify.py:275` | subprocess without window suppression |
| MEDIUM | `RUN_WITHOUT_WINDOWLESS` | `scripts/edge06_verify.py:293` | subprocess without window suppression |
| MEDIUM | `RUN_WITHOUT_WINDOWLESS` | `scripts/edge07_growth_evidence.py:159` | subprocess without window suppression |
| MEDIUM | `RUN_WITHOUT_WINDOWLESS` | `scripts/edge07_reclaim.py:151` | subprocess without window suppression |
| MEDIUM | `RUN_WITHOUT_WINDOWLESS` | `scripts/edge07_report.py:92` | subprocess without window suppression |
| MEDIUM | `RUN_WITHOUT_WINDOWLESS` | `scripts/edge07_report.py:106` | subprocess without window suppression |
| MEDIUM | `RUN_WITHOUT_WINDOWLESS` | `scripts/edge08_report.py:115` | subprocess without window suppression |
| MEDIUM | `RUN_WITHOUT_WINDOWLESS` | `scripts/edge08_report.py:147` | subprocess without window suppression |
| MEDIUM | `RUN_WITHOUT_WINDOWLESS` | `scripts/edge08_verify.py:131` | subprocess without window suppression |
| MEDIUM | `RUN_WITHOUT_WINDOWLESS` | `scripts/edge09_report.py:105` | subprocess without window suppression |
| MEDIUM | `RUN_WITHOUT_WINDOWLESS` | `scripts/edge09_report.py:112` | subprocess without window suppression |
| MEDIUM | `RUN_WITHOUT_WINDOWLESS` | `scripts/edge09_suite_evidence.py:43` | subprocess without window suppression |
| MEDIUM | `RUN_WITHOUT_WINDOWLESS` | `scripts/edge09_suite_evidence.py:112` | subprocess without window suppression |
| MEDIUM | `RUN_WITHOUT_WINDOWLESS` | `scripts/edge12_reports.py:484` | subprocess without window suppression |
| MEDIUM | `RUN_WITHOUT_WINDOWLESS` | `scripts/edge12_tests.py:73` | subprocess without window suppression |
| MEDIUM | `RUN_WITHOUT_WINDOWLESS` | `scripts/edge14_reports.py:32` | subprocess without window suppression |
| MEDIUM | `RUN_WITHOUT_WINDOWLESS` | `scripts/edge14_reports.py:42` | subprocess without window suppression |
| MEDIUM | `RUN_WITHOUT_WINDOWLESS` | `scripts/edge14_run.py:323` | subprocess without window suppression |
| MEDIUM | `RUN_WITHOUT_WINDOWLESS` | `scripts/edge14r_engine_parity.py:227` | subprocess without window suppression |
| MEDIUM | `RUN_WITHOUT_WINDOWLESS` | `scripts/edge14r_engine_parity.py:261` | subprocess without window suppression |
| MEDIUM | `RUN_WITHOUT_WINDOWLESS` | `scripts/edge14r_external_engines.py:84` | subprocess without window suppression |
| MEDIUM | `RUN_WITHOUT_WINDOWLESS` | `scripts/edge14r_external_engines.py:89` | subprocess without window suppression |
| MEDIUM | `RUN_WITHOUT_WINDOWLESS` | `scripts/edge14r_external_engines.py:115` | subprocess without window suppression |
| MEDIUM | `RUN_WITHOUT_WINDOWLESS` | `scripts/edge14r_reports.py:40` | subprocess without window suppression |
| MEDIUM | `RUN_WITHOUT_WINDOWLESS` | `scripts/edge14r_verify.py:540` | subprocess without window suppression |
| MEDIUM | `RUN_WITHOUT_WINDOWLESS` | `scripts/edge15_oos_preregistration.py:120` | subprocess without window suppression |
| MEDIUM | `RUN_WITHOUT_WINDOWLESS` | `scripts/edge15_oos_preregistration.py:125` | subprocess without window suppression |
| MEDIUM | `RUN_WITHOUT_WINDOWLESS` | `scripts/edge15_oos_preregistration.py:131` | subprocess without window suppression |
| MEDIUM | `RUN_WITHOUT_WINDOWLESS` | `scripts/edge15_verify.py:299` | subprocess without window suppression |
| MEDIUM | `RUN_WITHOUT_WINDOWLESS` | `scripts/edge15_verify.py:305` | subprocess without window suppression |
| MEDIUM | `RUN_WITHOUT_WINDOWLESS` | `scripts/edge15_verify.py:387` | subprocess without window suppression |
| MEDIUM | `RUN_WITHOUT_WINDOWLESS` | `scripts/edge16_artifacts.py:157` | subprocess without window suppression |
| MEDIUM | `RUN_WITHOUT_WINDOWLESS` | `scripts/edge16_reports.py:44` | subprocess without window suppression |
| MEDIUM | `RUN_WITHOUT_WINDOWLESS` | `scripts/edge16_verify.py:1030` | subprocess without window suppression |
| MEDIUM | `RUN_WITHOUT_WINDOWLESS` | `scripts/edge17_prefix_replay.py:47` | subprocess without window suppression |
| MEDIUM | `RUN_WITHOUT_WINDOWLESS` | `scripts/edge17_prefix_replay.py:179` | subprocess without window suppression |
| MEDIUM | `RUN_WITHOUT_WINDOWLESS` | `scripts/edge17_prefix_replay.py:214` | subprocess without window suppression |
| MEDIUM | `RUN_WITHOUT_WINDOWLESS` | `scripts/edge17_reports.py:366` | subprocess without window suppression |
| MEDIUM | `RUN_WITHOUT_WINDOWLESS` | `scripts/edge17_reports.py:372` | subprocess without window suppression |
| MEDIUM | `RUN_WITHOUT_WINDOWLESS` | `scripts/forward_collection_verification.py:164` | subprocess without window suppression |
| MEDIUM | `RUN_WITHOUT_WINDOWLESS` | `scripts/forward_collection_verification.py:177` | subprocess without window suppression |
| MEDIUM | `RUN_WITHOUT_WINDOWLESS` | `scripts/forward_disk_guard_test.py:79` | subprocess without window suppression |
| MEDIUM | `RUN_WITHOUT_WINDOWLESS` | `scripts/forward_paper_coexistence.py:62` | subprocess without window suppression |
| MEDIUM | `RUN_WITHOUT_WINDOWLESS` | `scripts/forward_quality_gates.py:42` | subprocess without window suppression |
| MEDIUM | `RUN_WITHOUT_WINDOWLESS` | `scripts/forward_quality_gates.py:112` | subprocess without window suppression |
| MEDIUM | `RUN_WITHOUT_WINDOWLESS` | `scripts/paper_lab_verification.py:166` | subprocess without window suppression |
| MEDIUM | `RUN_WITHOUT_WINDOWLESS` | `scripts/paper_lab_verification.py:234` | subprocess without window suppression |
| MEDIUM | `RUN_WITHOUT_WINDOWLESS` | `scripts/paper_lab_verification.py:895` | subprocess without window suppression |
| MEDIUM | `RUN_WITHOUT_WINDOWLESS` | `scripts/paper_lab_verification.py:1253` | subprocess without window suppression |
| MEDIUM | `RUN_WITHOUT_WINDOWLESS` | `scripts/paper_lab_verification.py:1378` | subprocess without window suppression |
| MEDIUM | `RUN_WITHOUT_WINDOWLESS` | `scripts/paper_lab_verification.py:1437` | subprocess without window suppression |
| MEDIUM | `RUN_WITHOUT_WINDOWLESS` | `scripts/pgate035_closure.py:107` | subprocess without window suppression |
| MEDIUM | `RUN_WITHOUT_WINDOWLESS` | `scripts/pgate035_closure.py:252` | subprocess without window suppression |
| MEDIUM | `RUN_WITHOUT_WINDOWLESS` | `scripts/recovery_economic_invariance.py:65` | subprocess without window suppression |
| MEDIUM | `RUN_WITHOUT_WINDOWLESS` | `scripts/recovery_economic_invariance.py:72` | subprocess without window suppression |
| MEDIUM | `RUN_WITHOUT_WINDOWLESS` | `scripts/recovery_input_evidence.py:253` | subprocess without window suppression |
| MEDIUM | `RUN_WITHOUT_WINDOWLESS` | `scripts/recovery_input_evidence.py:268` | subprocess without window suppression |
| MEDIUM | `RUN_WITHOUT_WINDOWLESS` | `scripts/recovery_input_evidence.py:275` | subprocess without window suppression |
| MEDIUM | `RUN_WITHOUT_WINDOWLESS` | `scripts/recovery_verify.py:152` | subprocess without window suppression |
| MEDIUM | `RUN_WITHOUT_WINDOWLESS` | `scripts/recovery_verify.py:526` | subprocess without window suppression |
| MEDIUM | `RUN_WITHOUT_WINDOWLESS` | `scripts/recovery_verify.py:574` | subprocess without window suppression |
| MEDIUM | `RUN_WITHOUT_WINDOWLESS` | `scripts/research_verification.py:77` | subprocess without window suppression |
| MEDIUM | `RUN_WITHOUT_WINDOWLESS` | `scripts/research_verification.py:87` | subprocess without window suppression |
| MEDIUM | `RUN_WITHOUT_WINDOWLESS` | `scripts/rfc034_run.py:66` | subprocess without window suppression |
| MEDIUM | `RUN_WITHOUT_WINDOWLESS` | `scripts/rfc034_run.py:94` | subprocess without window suppression |
| MEDIUM | `RUN_WITHOUT_WINDOWLESS` | `scripts/rfc034_run.py:95` | subprocess without window suppression |
| MEDIUM | `RUN_WITHOUT_WINDOWLESS` | `scripts/rfc034_run.py:98` | subprocess without window suppression |
| MEDIUM | `RUN_WITHOUT_WINDOWLESS` | `scripts/rfc034_verify.py:57` | subprocess without window suppression |
| MEDIUM | `RUN_WITHOUT_WINDOWLESS` | `scripts/rfc035_discovery_verify.py:130` | subprocess without window suppression |
| MEDIUM | `RUN_WITHOUT_WINDOWLESS` | `scripts/rfc035_run.py:34` | subprocess without window suppression |
| MEDIUM | `RUN_WITHOUT_WINDOWLESS` | `scripts/rfc035_verify.py:121` | subprocess without window suppression |
| MEDIUM | `RUN_WITHOUT_WINDOWLESS` | `scripts/rfc035s2_search.py:1657` | subprocess without window suppression |
| MEDIUM | `RUN_WITHOUT_WINDOWLESS` | `scripts/rfc035s2_verify.py:154` | subprocess without window suppression |
| MEDIUM | `RUN_WITHOUT_WINDOWLESS` | `scripts/rfc035s3_closure.py:124` | subprocess without window suppression |
| MEDIUM | `RUN_WITHOUT_WINDOWLESS` | `scripts/rfc035s3_verify.py:484` | subprocess without window suppression |
| MEDIUM | `RUN_WITHOUT_WINDOWLESS` | `scripts/rfc035s3_verify.py:515` | subprocess without window suppression |
| MEDIUM | `RUN_WITHOUT_WINDOWLESS` | `scripts/rfc035s3_verify.py:579` | subprocess without window suppression |
| MEDIUM | `RUN_WITHOUT_WINDOWLESS` | `scripts/rfc035s3_verify.py:597` | subprocess without window suppression |
| MEDIUM | `RUN_WITHOUT_WINDOWLESS` | `scripts/rfc039_run.py:88` | subprocess without window suppression |
| MEDIUM | `RUN_WITHOUT_WINDOWLESS` | `scripts/rfc040_run.py:87` | subprocess without window suppression |
| MEDIUM | `RUN_WITHOUT_WINDOWLESS` | `scripts/rfc040_run.py:92` | subprocess without window suppression |
| MEDIUM | `RUN_WITHOUT_WINDOWLESS` | `scripts/rfc041_run.py:58` | subprocess without window suppression |
| MEDIUM | `RUN_WITHOUT_WINDOWLESS` | `scripts/rfc041_run.py:63` | subprocess without window suppression |
| MEDIUM | `RUN_WITHOUT_WINDOWLESS` | `scripts/rfc041_verify.py:49` | subprocess without window suppression |
| MEDIUM | `RUN_WITHOUT_WINDOWLESS` | `scripts/rfc042_run.py:917` | subprocess without window suppression |
| MEDIUM | `RUN_WITHOUT_WINDOWLESS` | `scripts/rfc042_run.py:999` | subprocess without window suppression |
| MEDIUM | `RUN_WITHOUT_WINDOWLESS` | `scripts/rfc042_verify.py:97` | subprocess without window suppression |
| MEDIUM | `RUN_WITHOUT_WINDOWLESS` | `scripts/rfc042_verify.py:170` | subprocess without window suppression |
| MEDIUM | `RUN_WITHOUT_WINDOWLESS` | `scripts/rfc043_run.py:142` | subprocess without window suppression |
| MEDIUM | `RUN_WITHOUT_WINDOWLESS` | `scripts/rfc043_run.py:215` | subprocess without window suppression |
| MEDIUM | `RUN_WITHOUT_WINDOWLESS` | `scripts/rfc043_verify.py:137` | subprocess without window suppression |
| MEDIUM | `RUN_WITHOUT_WINDOWLESS` | `scripts/rfc043_verify.py:143` | subprocess without window suppression |
| MEDIUM | `RUN_WITHOUT_WINDOWLESS` | `scripts/rfc044_run.py:76` | subprocess without window suppression |
| MEDIUM | `RUN_WITHOUT_WINDOWLESS` | `scripts/rfc044_run.py:141` | subprocess without window suppression |
| MEDIUM | `RUN_WITHOUT_WINDOWLESS` | `scripts/rfc044_verify.py:174` | subprocess without window suppression |
| MEDIUM | `RUN_WITHOUT_WINDOWLESS` | `scripts/rfc044_verify.py:180` | subprocess without window suppression |
| MEDIUM | `RUN_WITHOUT_WINDOWLESS` | `scripts/rfc046_audit.py:85` | subprocess without window suppression |
| MEDIUM | `RUN_WITHOUT_WINDOWLESS` | `scripts/rfc046_campaign.py:193` | subprocess without window suppression |
| MEDIUM | `RUN_WITHOUT_WINDOWLESS` | `scripts/rfc046_campaign.py:196` | subprocess without window suppression |
| MEDIUM | `RUN_WITHOUT_WINDOWLESS` | `scripts/rfc046_campaign_verify.py:336` | subprocess without window suppression |
| MEDIUM | `RUN_WITHOUT_WINDOWLESS` | `scripts/rfc046_economic_gate_verify.py:818` | subprocess without window suppression |
| MEDIUM | `RUN_WITHOUT_WINDOWLESS` | `scripts/rfc046_verify.py:89` | subprocess without window suppression |
| MEDIUM | `RUN_WITHOUT_WINDOWLESS` | `scripts/rfc047_builder.py:159` | subprocess without window suppression |
| MEDIUM | `RUN_WITHOUT_WINDOWLESS` | `scripts/rfc047_builder.py:186` | subprocess without window suppression |
| MEDIUM | `RUN_WITHOUT_WINDOWLESS` | `scripts/rfc047_verify.py:216` | subprocess without window suppression |
| MEDIUM | `RUN_WITHOUT_WINDOWLESS` | `scripts/rfc047_verify.py:249` | subprocess without window suppression |
| MEDIUM | `RUN_WITHOUT_WINDOWLESS` | `scripts/rfc048_report.py:46` | subprocess without window suppression |
| MEDIUM | `RUN_WITHOUT_WINDOWLESS` | `scripts/rfc048_run.py:75` | subprocess without window suppression |
| MEDIUM | `RUN_WITHOUT_WINDOWLESS` | `scripts/rfc048_verify.py:45` | subprocess without window suppression |
| MEDIUM | `RUN_WITHOUT_WINDOWLESS` | `scripts/rfc048v_certify.py:201` | subprocess without window suppression |
| MEDIUM | `RUN_WITHOUT_WINDOWLESS` | `scripts/rfc048v_falsify.py:90` | subprocess without window suppression |
| MEDIUM | `RUN_WITHOUT_WINDOWLESS` | `scripts/rfc048v_runtime_authority.py:77` | subprocess without window suppression |
| MEDIUM | `RUN_WITHOUT_WINDOWLESS` | `scripts/rfc049_prepare.py:350` | subprocess without window suppression |
| MEDIUM | `RUN_WITHOUT_WINDOWLESS` | `scripts/rfc049_prepare.py:549` | subprocess without window suppression |
| MEDIUM | `RUN_WITHOUT_WINDOWLESS` | `scripts/rfc049b_admission.py:147` | subprocess without window suppression |
| MEDIUM | `RUN_WITHOUT_WINDOWLESS` | `scripts/rfc049c_ablation.py:146` | subprocess without window suppression |
| MEDIUM | `RUN_WITHOUT_WINDOWLESS` | `scripts/rfc049c_active_audit.py:40` | subprocess without window suppression |
| MEDIUM | `RUN_WITHOUT_WINDOWLESS` | `scripts/rfc049c_active_audit.py:132` | subprocess without window suppression |
| MEDIUM | `RUN_WITHOUT_WINDOWLESS` | `scripts/rfc049c_engine.py:971` | subprocess without window suppression |
| MEDIUM | `RUN_WITHOUT_WINDOWLESS` | `scripts/rfc049c_verify.py:614` | subprocess without window suppression |
| MEDIUM | `RUN_WITHOUT_WINDOWLESS` | `scripts/source_candidate_experiment.py:99` | subprocess without window suppression |
| MEDIUM | `RUN_WITHOUT_WINDOWLESS` | `scripts/sprint024_analysis.py:26` | subprocess without window suppression |
| MEDIUM | `RUN_WITHOUT_WINDOWLESS` | `scripts/sprint025_analysis.py:238` | subprocess without window suppression |
| MEDIUM | `RUN_WITHOUT_WINDOWLESS` | `scripts/sprint030_run.py:33` | subprocess without window suppression |
| MEDIUM | `RUN_WITHOUT_WINDOWLESS` | `scripts/sprint031_run.py:31` | subprocess without window suppression |
| MEDIUM | `RUN_WITHOUT_WINDOWLESS` | `scripts/sprint032_run.py:44` | subprocess without window suppression |
| MEDIUM | `RUN_WITHOUT_WINDOWLESS` | `scripts/sprint032_verify.py:410` | subprocess without window suppression |
| MEDIUM | `RUN_WITHOUT_WINDOWLESS` | `scripts/sprint033_run.py:72` | subprocess without window suppression |
| MEDIUM | `RUN_WITHOUT_WINDOWLESS` | `scripts/sprint033_verify.py:39` | subprocess without window suppression |
| MEDIUM | `RUN_WITHOUT_WINDOWLESS` | `scripts/st6_close_verify.py:1405` | subprocess without window suppression |
| MEDIUM | `RUN_WITHOUT_WINDOWLESS` | `scripts/st6_forward_regime.py:177` | subprocess without window suppression |
| MEDIUM | `RUN_WITHOUT_WINDOWLESS` | `scripts/st6_forward_regime.py:2226` | subprocess without window suppression |
| MEDIUM | `RUN_WITHOUT_WINDOWLESS` | `scripts/st6_forward_regime.py:2406` | subprocess without window suppression |
| MEDIUM | `RUN_WITHOUT_WINDOWLESS` | `scripts/st6_forward_regime.py:2488` | subprocess without window suppression |
| MEDIUM | `RUN_WITHOUT_WINDOWLESS` | `scripts/st6_scheduler_verify.py:217` | subprocess without window suppression |
| MEDIUM | `RUN_WITHOUT_WINDOWLESS` | `scripts/st6_scheduler_verify.py:261` | subprocess without window suppression |
| MEDIUM | `RUN_WITHOUT_WINDOWLESS` | `scripts/st6_scheduler_verify.py:324` | subprocess without window suppression |
| MEDIUM | `RUN_WITHOUT_WINDOWLESS` | `scripts/st6_scheduler_witness.py:152` | subprocess without window suppression |
| MEDIUM | `RUN_WITHOUT_WINDOWLESS` | `scripts/st6_scheduler_witness.py:205` | subprocess without window suppression |
| MEDIUM | `RUN_WITHOUT_WINDOWLESS` | `scripts/st6_state_snapshot.py:115` | subprocess without window suppression |
| MEDIUM | `RUN_WITHOUT_WINDOWLESS` | `scripts/st6_state_snapshot.py:125` | subprocess without window suppression |
| MEDIUM | `RUN_WITHOUT_WINDOWLESS` | `scripts/st6_windows_events.py:173` | subprocess without window suppression |
| MEDIUM | `RUN_WITHOUT_WINDOWLESS` | `scripts/start_paper_lab.py:484` | subprocess without window suppression |
| MEDIUM | `RUN_WITHOUT_WINDOWLESS` | `scripts/start_paper_lab.py:803` | subprocess without window suppression |
| MEDIUM | `RUN_WITHOUT_WINDOWLESS` | `scripts/strategy_dynamic_experiment.py:290` | subprocess without window suppression |
| MEDIUM | `RUN_WITHOUT_WINDOWLESS` | `scripts/swing_run.py:86` | subprocess without window suppression |
| MEDIUM | `RUN_WITHOUT_WINDOWLESS` | `scripts/swing_run.py:283` | subprocess without window suppression |
| MEDIUM | `RUN_WITHOUT_WINDOWLESS` | `scripts/swing_run.py:877` | subprocess without window suppression |
| MEDIUM | `RUN_WITHOUT_WINDOWLESS` | `scripts/swing_verify.py:783` | subprocess without window suppression |
| MEDIUM | `RUN_WITHOUT_WINDOWLESS` | `scripts/verify_l5_independent.py:334` | subprocess without window suppression |
| MEDIUM | `RUN_WITHOUT_WINDOWLESS` | `scripts/wp10_active_recovery.py:73` | subprocess without window suppression |
| MEDIUM | `RUN_WITHOUT_WINDOWLESS` | `scripts/wp10_baseline_economic_audit.py:433` | subprocess without window suppression |
| MEDIUM | `RUN_WITHOUT_WINDOWLESS` | `scripts/wp10_e1_cost_reality.py:913` | subprocess without window suppression |
| MEDIUM | `RUN_WITHOUT_WINDOWLESS` | `scripts/wp10_e1_decision.py:79` | subprocess without window suppression |
| MEDIUM | `RUN_WITHOUT_WINDOWLESS` | `scripts/wp10_open_blockers.py:60` | subprocess without window suppression |
| MEDIUM | `RUN_WITHOUT_WINDOWLESS` | `scripts/wp10_phase0_wp9_closure.py:105` | subprocess without window suppression |
| MEDIUM | `RUN_WITHOUT_WINDOWLESS` | `scripts/wp10_phase0_wp9_closure.py:235` | subprocess without window suppression |
| MEDIUM | `RUN_WITHOUT_WINDOWLESS` | `scripts/wp10_phase0_wp9_closure.py:239` | subprocess without window suppression |
| MEDIUM | `RUN_WITHOUT_WINDOWLESS` | `scripts/wp10_phase0_wp9_closure.py:293` | subprocess without window suppression |
| MEDIUM | `RUN_WITHOUT_WINDOWLESS` | `scripts/wp10_run_report.py:48` | subprocess without window suppression |
| MEDIUM | `RUN_WITHOUT_WINDOWLESS` | `scripts/wp10_verify.py:135` | subprocess without window suppression |
| MEDIUM | `RUN_WITHOUT_WINDOWLESS` | `scripts/wp10_verify.py:756` | subprocess without window suppression |
| MEDIUM | `RUN_WITHOUT_WINDOWLESS` | `scripts/wp10_verify.py:944` | subprocess without window suppression |
| MEDIUM | `RUN_WITHOUT_WINDOWLESS` | `scripts/wp9_ci_audit.py:136` | subprocess without window suppression |
| MEDIUM | `RUN_WITHOUT_WINDOWLESS` | `scripts/wp9_ci_audit.py:361` | subprocess without window suppression |
| MEDIUM | `RUN_WITHOUT_WINDOWLESS` | `scripts/wp9_ci_audit.py:447` | subprocess without window suppression |
| MEDIUM | `RUN_WITHOUT_WINDOWLESS` | `scripts/wp9_economic_blockers.py:202` | subprocess without window suppression |
| MEDIUM | `RUN_WITHOUT_WINDOWLESS` | `scripts/wp9_verify.py:497` | subprocess without window suppression |
| MEDIUM | `RUN_WITHOUT_WINDOWLESS` | `scripts/wp9_verify.py:535` | subprocess without window suppression |
| MEDIUM | `RUN_WITHOUT_WINDOWLESS` | `scripts/wp9_verify.py:539` | subprocess without window suppression |
| MEDIUM | `RUN_WITHOUT_WINDOWLESS` | `scripts/wp9_verify.py:704` | subprocess without window suppression |
| MEDIUM | `RUN_WITHOUT_WINDOWLESS` | `scripts/wp_edge_00_verify.py:167` | subprocess without window suppression |
| MEDIUM | `RUN_WITHOUT_WINDOWLESS` | `scripts/wp_edge_00_verify.py:177` | subprocess without window suppression |
| MEDIUM | `RUN_WITHOUT_WINDOWLESS` | `scripts/wp_edge_00_verify.py:185` | subprocess without window suppression |
| MEDIUM | `RUN_WITHOUT_WINDOWLESS` | `scripts/wp_edge_00b_verify.py:411` | subprocess without window suppression |
| MEDIUM | `RUN_WITHOUT_WINDOWLESS` | `src/trading_bot/autonomous/observability.py:96` | subprocess without window suppression |
| MEDIUM | `RUN_WITHOUT_WINDOWLESS` | `src/trading_bot/autonomous/observability.py:155` | subprocess without window suppression |
| MEDIUM | `RUN_WITHOUT_WINDOWLESS` | `src/trading_bot/autonomous/runtime.py:1755` | subprocess without window suppression |
| MEDIUM | `RUN_WITHOUT_WINDOWLESS` | `src/trading_bot/observability/ecosystem.py:835` | subprocess without window suppression |
| MEDIUM | `RUN_WITHOUT_WINDOWLESS` | `src/trading_bot/research/economic_recovery/parity.py:130` | subprocess without window suppression |
| MEDIUM | `RUN_WITHOUT_WINDOWLESS` | `src/trading_bot/research/economic_recovery/parity.py:286` | subprocess without window suppression |
| MEDIUM | `RUN_WITHOUT_WINDOWLESS` | `src/trading_bot/research/economic_recovery/render.py:639` | subprocess without window suppression |
| MEDIUM | `RUN_WITHOUT_WINDOWLESS` | `src/trading_bot/research/edge01/campaign.py:3267` | subprocess without window suppression |
| MEDIUM | `RUN_WITHOUT_WINDOWLESS` | `src/trading_bot/research/edge01/campaign.py:3324` | subprocess without window suppression |
| MEDIUM | `RUN_WITHOUT_WINDOWLESS` | `src/trading_bot/research/edge04r/os_evidence.py:220` | subprocess without window suppression |
| MEDIUM | `RESEARCH_PROBE_CMD_ACTION` | `src/trading_bot/research/edge04r/session.py:137` | a research probe's task definition uses cmd.exe as an action |
| MEDIUM | `RUN_WITHOUT_WINDOWLESS` | `src/trading_bot/research/edge04r/session.py:403` | subprocess without window suppression |
| MEDIUM | `RUN_WITHOUT_WINDOWLESS` | `src/trading_bot/research/edge05/reading.py:330` | subprocess without window suppression |
| MEDIUM | `RUN_WITHOUT_WINDOWLESS` | `src/trading_bot/research/edge05/watchdog.py:460` | subprocess without window suppression |
| MEDIUM | `RUN_WITHOUT_WINDOWLESS` | `src/trading_bot/research/edge05/watchdog.py:511` | subprocess without window suppression |
| MEDIUM | `RUN_WITHOUT_WINDOWLESS` | `src/trading_bot/research/edge08/disjointness.py:100` | subprocess without window suppression |
| MEDIUM | `RUN_WITHOUT_WINDOWLESS` | `src/trading_bot/research/edge09/estate.py:98` | subprocess without window suppression |
| MEDIUM | `RUN_WITHOUT_WINDOWLESS` | `src/trading_bot/research/edge12/gate.py:104` | subprocess without window suppression |
| MEDIUM | `RUN_WITHOUT_WINDOWLESS` | `src/trading_bot/research/edge12/gate.py:264` | subprocess without window suppression |
| MEDIUM | `RUN_WITHOUT_WINDOWLESS` | `src/trading_bot/research/edge12/gate.py:306` | subprocess without window suppression |
| MEDIUM | `RUN_WITHOUT_WINDOWLESS` | `src/trading_bot/research/edge12/runner.py:96` | subprocess without window suppression |
| MEDIUM | `RUN_WITHOUT_WINDOWLESS` | `src/trading_bot/research/experiment_evidence.py:154` | subprocess without window suppression |
| MEDIUM | `RUN_WITHOUT_WINDOWLESS` | `src/trading_bot/research/experiment_evidence.py:167` | subprocess without window suppression |
| MEDIUM | `RUN_WITHOUT_WINDOWLESS` | `src/trading_bot/research/forward/collector.py:2145` | subprocess without window suppression |
| MEDIUM | `RUN_WITHOUT_WINDOWLESS` | `tests/unit/cert/test_canonical_core_lint_guard.py:76` | subprocess without window suppression |
| MEDIUM | `RUN_WITHOUT_WINDOWLESS` | `tests/unit/cert/test_ema_crossover_strategy_guard.py:119` | subprocess without window suppression |
| MEDIUM | `RUN_WITHOUT_WINDOWLESS` | `tests/unit/cert/test_ema_crossover_strategy_guard.py:134` | subprocess without window suppression |
| MEDIUM | `RUN_WITHOUT_WINDOWLESS` | `tests/unit/cert/test_paper_smoke_decision_path.py:156` | subprocess without window suppression |
| MEDIUM | `RUN_WITHOUT_WINDOWLESS` | `tests/unit/forward/test_forward_collector_replay.py:619` | subprocess without window suppression |
| MEDIUM | `RUN_WITHOUT_WINDOWLESS` | `tests/unit/forward/test_forward_collector_replay.py:628` | subprocess without window suppression |
| MEDIUM | `RUN_WITHOUT_WINDOWLESS` | `tests/unit/research/test_cost_barrier_ci_parity.py:159` | subprocess without window suppression |
| MEDIUM | `RUN_WITHOUT_WINDOWLESS` | `tests/unit/research/test_cost_barrier_ci_parity.py:207` | subprocess without window suppression |
| MEDIUM | `RUN_WITHOUT_WINDOWLESS` | `tests/unit/research/test_cost_barrier_gate.py:149` | subprocess without window suppression |
| MEDIUM | `RUN_WITHOUT_WINDOWLESS` | `tests/unit/research/test_cost_barrier_gate.py:154` | subprocess without window suppression |
| MEDIUM | `RUN_WITHOUT_WINDOWLESS` | `tests/unit/research/test_cost_barrier_gate.py:162` | subprocess without window suppression |
| MEDIUM | `RUN_WITHOUT_WINDOWLESS` | `tests/unit/research/test_economic001_evidence_closure.py:85` | subprocess without window suppression |
| MEDIUM | `RUN_WITHOUT_WINDOWLESS` | `tests/unit/research/test_economic001_evidence_closure.py:181` | subprocess without window suppression |
| MEDIUM | `RUN_WITHOUT_WINDOWLESS` | `tests/unit/research/test_edge04_autonomous.py:1150` | subprocess without window suppression |
| MEDIUM | `RUN_WITHOUT_WINDOWLESS` | `tests/unit/research/test_recovery_determinism.py:185` | subprocess without window suppression |
| MEDIUM | `RUN_WITHOUT_WINDOWLESS` | `tests/unit/research/test_rfc046_discovery_proposal.py:76` | subprocess without window suppression |
| MEDIUM | `RUN_WITHOUT_WINDOWLESS` | `tests/unit/research/test_rfc046_discovery_proposal.py:402` | subprocess without window suppression |
| MEDIUM | `RUN_WITHOUT_WINDOWLESS` | `tests/unit/research/test_rfc046_discovery_proposal.py:405` | subprocess without window suppression |
| MEDIUM | `RUN_WITHOUT_WINDOWLESS` | `tests/unit/research/test_st6_forward_regime.py:831` | subprocess without window suppression |
| MEDIUM | `RUN_WITHOUT_WINDOWLESS` | `tests/unit/research/test_st6_scheduler.py:114` | subprocess without window suppression |
| MEDIUM | `RUN_WITHOUT_WINDOWLESS` | `tests/unit/research/test_st6_scheduler.py:131` | subprocess without window suppression |
| MEDIUM | `RUN_WITHOUT_WINDOWLESS` | `tests/unit/research/test_st6_scheduler.py:229` | subprocess without window suppression |
| MEDIUM | `RUN_WITHOUT_WINDOWLESS` | `tests/unit/research/test_st6_scheduler.py:960` | subprocess without window suppression |
| MEDIUM | `RUN_WITHOUT_WINDOWLESS` | `tests/unit/risk/test_futures_independent_verifier.py:135` | subprocess without window suppression |
| MEDIUM | `RUN_WITHOUT_WINDOWLESS` | `tests/unit/strategy_lifecycle/test_restart_recovery.py:20` | subprocess without window suppression |
| MEDIUM | `RUN_WITHOUT_WINDOWLESS` | `tests/unit/test_dependency_closure_guard.py:27` | subprocess without window suppression |
| MEDIUM | `RUN_WITHOUT_WINDOWLESS` | `tests/unit/test_dependency_closure_guard.py:47` | subprocess without window suppression |
| MEDIUM | `RUN_WITHOUT_WINDOWLESS` | `tests/unit/test_dependency_closure_guard.py:85` | subprocess without window suppression |
| MEDIUM | `RUN_WITHOUT_WINDOWLESS` | `tests/unit/test_dependency_closure_guard.py:178` | subprocess without window suppression |

## Scope

HIGH = a child that can outlive the call, a shell hop, or a scheduled-task action that owns a console for its whole life. MEDIUM = a bounded subprocess call that still needs the helper when its caller has no console; reported, not hidden, and not counted as fixed.

