# BASELINE RUN REPORT — RFC-TDM-015

```text
head      : 3be8e5bd36cab4f6fc532a0b891147b1f21efe08
branch    : feat/wp-signal-001-003
remote    : https://github.com/Extr3sao/bot_crypto.git
python    : 3.11.15
summary   : 90 failed, 3406 passed, 30 skipped, 78 warnings, 14 errors in 531.11s (0:08:51)
failed    : 90
```

## Regression against the parent commit

- baseline: `ff-wt-wp15-base at 3be8e5bd (clean, no untracked data/)` — 97 failing node(s)
- this checkout: 104 failing node(s)
- regressions: 9
- fixed since baseline: 2

- REGRESSION `tests/unit/observability/test_dashboard_server.py::test_runtime_artifacts_are_untouched_by_serving`
- REGRESSION `tests/unit/research/test_cost_drift_monitor.py::test_every_window_keeps_its_raw_bytes_and_the_hash_matches`
- REGRESSION `tests/unit/research/test_economic001_evidence_closure.py::test_the_report_bytes_still_match_the_rfc046_verification`
- REGRESSION `tests/unit/research/test_economic001_evidence_closure.py::test_the_two_tolls_are_distinct_and_the_historical_one_is_frozen`
- REGRESSION `tests/unit/research/test_economic001_evidence_closure.py::test_the_verified_bytes_are_the_shipped_bytes`
- REGRESSION `tests/unit/research/test_rfc046_economic_gate.py::test_artefacts_exist_and_are_verified_clean`
- REGRESSION `tests/unit/research/test_rfc046_economic_gate.py::test_the_rfc046_confirmations_match_the_recorded_artefacts`
- REGRESSION `tests/unit/risk/test_futures_independent_verifier.py::test_executed_artifacts_verify_when_present`
- REGRESSION `tests/unit/risk/test_futures_independent_verifier.py::test_verifier_reproduces_a_real_approval`

## What this baseline is not

The suite is not green on this host, and this report does not claim it is. The failures named in the JSON are the ones the run produced; those that also fail at the parent commit are inherited, and the ones that do not are listed as regressions above with their node ids.
