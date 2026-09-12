# Shadow V2 Invalidation Record — EXT-SHADOW-002

**Status:** `previous 11/11 outcome claim = INVALIDATED`
**Reason:** maturity timestamps equalled capture timestamps despite frozen 48h rule.

| Field | Value |
|---|---|
| Invalidated artifact | `reports/poc02-r2-direction-arbitration-01/shadow/SHADOW_RESOLUTION_LEDGER.jsonl` (11 captures) |
| Claimed maturity range | `2026-09-09T21:15:00Z..2026-09-10T11:25:00Z` |
| Capture example | `decision_time 2026-09-09T21:15:00+00:00` → `maturity_time 2026-09-09T21:15:00Z` (delta 0h) |
| Correct maturity (48h) | `2026-09-11T21:15:00Z..2026-09-12T11:25:00Z` |
| External verifier | `SHADOW_MATURITY_RECONCILIATION=FAIL`, `SHADOW_11_OF_11=REJECTED`, `WRONG_MATURITY_DERIVATION` |

## Preservation

- Old `SHADOW_RESOLUTION_LEDGER.jsonl` and `SHADOW_COUNTERFACTUAL_REPORT.json` are preserved as **invalid historical evidence** — do not delete.
- New `SHADOW_MATURITY_AUTHORITY_V2.json` and `SHADOW_RESOLUTION_LEDGER_V2.jsonl` (or pending empty if not yet mature) supersede the invalid ledger with correct `capture + 48h` horizon.

## No Risk conclusion

- No `MAX_POSITIONS` or gate change allowed from invalidated outcomes.
- Even correctly resolved 11/11 would still be `INSUFFICIENT_SAMPLE` for policy (N=11).
- `H6_SHADOW_ISOLATION_REPORT` proves H6 does not consume Shadow outcomes.
