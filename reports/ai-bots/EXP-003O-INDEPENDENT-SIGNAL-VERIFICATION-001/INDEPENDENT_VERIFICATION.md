# INDEPENDENT VERIFICATION — EXP-003O

**TECHNICAL_SIGNAL_PARITY = `PASS`** · **FULL_INDEPENDENT_CERTIFICATION = `INCOMPLETE_REAL_DATA_COVERAGE`** · `ECONOMIC_EDGE = NOT_EVALUATED`

Design digest `b28a7b4c53168fd5…` · 12/12 checks · 275724 keys compared · 52848/52848 signals

| check | state | detail |
| --- | --- | --- |
| `V1_input_provenance` | **PASS** | dataset matches=True |
| `V2_design_binding` | **PASS** | digest=match |
| `V3_holdout` | **PASS** | bars=0 rows=0 |
| `V4_calendar_coverage` | **PASS** | both streams cover the bar-close calendar |
| `V5_pit` | **PASS** | 551448 window digests recomputed |
| `V6_prefix_invariance` | **PASS** | clean at cuts [300, 1500] |
| `V7_independence` | **PASS** | hook clean=True detects cheat=True |
| `V9_negative_controls` | **PASS** | 12/12 detected |
| `V8_parity_recomputation` | **PASS** | verifier=0 comparator=0 |
| `V10_governance` | **PASS** | config unchanged=True live disabled=True |
| `V11_functional_coverage` | **PASS** | fixtures complete=True |
| `V12_no_false_success` | **PASS** | mismatches=0 |

## Negative controls

| control | expected | observed | detected |
| --- | --- | --- | --- |
| `NEG-01` | `PIT_VIOLATION` | `PIT_VIOLATION` | sí |
| `NEG-02` | `TIMING_MISMATCH` | `TIMING_MISMATCH` | sí |
| `NEG-03` | `PIT_VIOLATION` | `PIT_VIOLATION` | sí |
| `NEG-04` | `PIT_VIOLATION` | `PIT_VIOLATION` | sí |
| `NEG-05` | `PARAMETER_HASH_MISMATCH` | `PARAMETER_HASH_MISMATCH` | sí |
| `NEG-06` | `MISSING_SIGNAL` | `MISSING_SIGNAL` | sí |
| `NEG-07` | `EXTRA_SIGNAL` | `EXTRA_SIGNAL` | sí |
| `NEG-08` | `DIRECTION_MISMATCH` | `DIRECTION_MISMATCH` | sí |
| `NEG-09` | `DATA_INTEGRITY_FAIL` | `DATA_INTEGRITY_FAIL` | sí |
| `NEG-10` | `STATE_MISMATCH` | `STATE_MISMATCH` | sí |
| `NEG-11` | `PREFIX_INVARIANCE_FAIL` | `PREFIX_INVARIANCE_FAIL` | sí |
| `NEG-12` | `INDEPENDENCE_VIOLATION` | `INDEPENDENCE_VIOLATION` | sí |

## What this verification does not establish

- It says nothing about profitability. `ECONOMIC_EDGE = NOT_EVALUATED` and the verdict
  promotes no strategy.
- It does not open the holdout and produces no order of any kind.
- The two producers agree on decisions taken on the same bars under the declared
  availability convention; a venue that publishes late would move both of them.
