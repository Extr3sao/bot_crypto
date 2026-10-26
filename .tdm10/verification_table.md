| Check | What it proves | Status | Evidence |
| --- | --- | --- | --- |
| `A1` | spec hash unchanged since measurement | **PASS** | — |
| `A2` | builder run reached its end | **PASS** | — |
| `B1` | dataset bytes match their manifests | **PASS** | files=24 |
| `C1` | cost == sum of its own components | **PASS** | component_sum_bps=23.79057 |
| `D1` | independent re-derivation completed | **PASS** | cells=24 |
| `D2` | trade list identical, trade by trade | **PASS** | cells=24, max_log_vs_simple_gap_bps=7.385621 |
| `D3` | exit strictly after entry | **PASS** | — |
| `D4` | no look-ahead (future overwritten) | **PASS** | trades_before_cut=116 |
| `D5` | DEV and HOLD disjoint | **PASS** | — |
| `E1` | published aggregates reproducible | **PASS** | cells=24, failure_count=0, max_log_vs_simple_gap_bps=0.271414 |
| `F1` | two significance methods agree | **PASS** | — |
| `G1` | verdicts follow the frozen rules | **PASS** | cells=24 |
