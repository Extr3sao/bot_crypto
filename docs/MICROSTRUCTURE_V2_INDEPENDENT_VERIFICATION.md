# MICROSTRUCTURE_V2_INDEPENDENT_VERIFICATION

Verificador: `scripts/research_verification.py` — HEAD `ffc13e6670554fcc2d1b1ce2f3569da855c23091`.
Alcance: `MICROSTRUCTURE-EDGE & FORWARD-DATA V1 (V2 artifacts)`.

```text
STATUS: VERIFIED
CHECKS: 15/15 PASS
FAILURES: 0
```

| check | esperado | observado | pass |
| --- | --- | --- | :-: |
| V2 artifacts reproduce byte-for-byte on re-run | identical content hash for all five artifacts | {'content_identical': True, 'raw_bytes_identical': True, 'exit_code': 0, 'artifacts': 5, 'note': 'raw bytes differ when the checkout materialised CRLF (core.autocrlf); the content hash is the authoritative comparison'} | PASS |
| per-asset V4 cost re-derived from the raw forward capture | rebuilt round-trip == committed round-trip for every asset | all three assets match exactly | PASS |
| cost components sum to the reported round trip | 0 inconsistencies; maker labelled EXECUTION_DEPENDENT | consistent | PASS |
| independent 5m aggregation matches the exchange kline volume | {'bars': 288, 'volume_equal': True} | {'bars': 288, 'agg_volume': 21997.1605, 'kline_volume': 21997.1605} | PASS |
| committed cross-check agrees with the verifier's own measurement | {'mean_ratio': 1.0} | {'bars_compared': 288, 'mean_ratio': 1.0, 'min_ratio': 1.0, 'max_ratio': 1.0} | PASS |
| PIT: no lead/lag pair uses information published after the decision | {'pairs': 287, 'violations': 0, 'negative_lag_rejected': True} | {'pairs': 287, 'violations': 0, 'negative_lag_rejected': True} | PASS |
| admission table arithmetic and status honesty | 0 inconsistencies | consistent | PASS |
| gross is never reported as net | no candidate with positive cost has net == gross | no candidate conflates them | PASS |
| no candidate is admitted on this evidence | {'admitted': [], 'paper_candidates': []} | {'admitted': [], 'paper_candidates': []} | PASS |
| an unobserved spread is rejected rather than assumed to be zero | ValueError on zero observations | rejected | PASS |
| aggTrades sample integrity against its own manifest | every recorded file hash still matches | 42 files verified | PASS |
| forward capture integrity (sha256 + duplicate/order counters) | {'sha256_matches': True, 'duplicates': 0, 'out_of_order': 0} | {'sha256_matches': True, 'duplicates': 0, 'out_of_order': 0, 'records': 11346} | PASS |
| M-07 is reported as LIMITED_HISTORY, never as a tradeable result | 3 rows, rule_evaluated=false, classification=LIMITED_HISTORY | [{'candidate_id': 'M-07-BTC', 'classification': 'LIMITED_HISTORY', 'rule_evaluated': False}, {'candidate_id': 'M-07-ETH', 'classification': 'LIMITED_HISTORY', 'rule_evaluated': False}, {'candidate_id': 'M-07-SOL', 'cl... | PASS |
| classification counts match the candidate rows | {'COST_KILLED': 7, 'LIMITED_HISTORY': 3, 'NO_INFORMATION': 2} | {'COST_KILLED': 7, 'LIMITED_HISTORY': 3, 'NO_INFORMATION': 2} | PASS |
| the driver claims no paper candidate | 0 | 0 | PASS |

BUILDER != VERIFIER: ninguna cifra de esta fase se acepta desde el artefacto del builder sin re-derivarla aquí.
