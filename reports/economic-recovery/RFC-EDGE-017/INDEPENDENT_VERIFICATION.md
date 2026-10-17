# WP-EDGE-017 — independent verification

**VERIFIED** — 27/27 checks verified, 11/11 injected faults detected.

The verifier does not import any module that built these artifacts: the rules below are
re-implemented from the published JSON and from the text of the runtime sources.

| check | status | detail |
| --- | --- | --- |
| C1 slice rows are post-freeze | VERIFIED | 9 rows, freeze 1792221328939 |
| C2 every slice key is unique | VERIFIED |  |
| C3 the manifest digest is the file's digest | VERIFIED |  |
| C4 the row census adds up and the slice never shrank | VERIFIED | before 9 after 9 |
| C5 the independent ledger records every slice row | VERIFIED | 9 ledger keys |
| C6 a re-run added nothing and left the bytes identical | VERIFIED | 3 ledger entries |
| C7 expected = observed + missing per symbol | VERIFIED |  |
| C8 captured bars per symbol is the real count, not 0/1 | VERIFIED |  |
| C9 missing hours are MISSING_NO_COLLECTOR | VERIFIED |  |
| C10 evaluated hours match the lane's own ledger | VERIFIED | 9 |
| C11 the still-forming hour never entered the slice | VERIFIED |  |
| S1 storage bytes and rows match the file | VERIFIED |  |
| S2 the guard's decision follows its own arithmetic | VERIFIED |  |
| S3 the fallback overstatement is the measured ratio | VERIFIED |  |
| N1 1x: every trade reconciles its net | VERIFIED | 146 trades |
| N2 2x: every trade reconciles its net | VERIFIED | 110 trades |
| N3 3x: every trade reconciles its net | VERIFIED | 67 trades |
| N4 no fill is free | VERIFIED |  |
| N5 broker net, risk equity and reconciliation agree | VERIFIED |  |
| N6 fills fall monotonically as costs rise | VERIFIED |  |
| N7 lost fills are explained by a loss rule | VERIFIED |  |
| N8 with costs off the engine reproduces WP-EDGE-016 fill for fill | VERIFIED |  |
| N9 the economic result is a net loss | VERIFIED | -238.770489 |
| D1 the four declared blocks are evaluated on the paper path | VERIFIED |  |
| D2 the risk policy was not edited and live stays off | VERIFIED |  |
| D3 the block matrix maps all four rules | VERIFIED |  |
| V1 every injected fault is detected | VERIFIED | 11/11 detected |

## Injected faults

| fault | detected |
| --- | --- |
| M1 drop a captured bar | yes |
| M2 duplicate a bar | yes |
| M3 rewrite the manifest digest | yes |
| M4 call a missing hour a quiet one | yes |
| M5 inflate one trade's net | yes |
| M6 charge nothing | yes |
| M7 reverse the fill ladder | yes |
| M8 claim a huge rate still fits | yes |
| M9 unwire the defensive blocks from the launcher | yes |
| M10 enable live trading in the runtime config | yes |
| M11 break the frictionless equivalence | yes |
