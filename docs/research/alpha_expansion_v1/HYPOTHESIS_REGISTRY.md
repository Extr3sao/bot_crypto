# ARP-005 ALPHA EXPANSION — HYPOTHESIS REGISTRY

Three new project hypotheses, pre-registered before results (see each experiment's
`experiments/EXP-ARP-0xx/SPEC.md`).

| id | hypothesis | mechanism family | experiment | outcome |
| --- | --- | --- | --- | --- |
| `H-XSEC-MOM-LONG-001` | the cross-sectional leader of the crypto peer group keeps leading at medium horizon | cross-sectional momentum | `EXP-ARP-013` | `REJECT_FRAGILE` (single-trade concentration) |
| `H-XSEC-REV-001` | the cross-sectional laggard over a short horizon mean-reverts toward the group | cross-sectional short-horizon reversal | `EXP-ARP-014` | `REJECT_VALIDATION` (net −1.91 bps OOS-window) |
| `H-XSEC-LOWVOL-001` | the calmest peer earns better subsequent risk-adjusted returns | cross-sectional low-volatility | `EXP-ARP-015` | `INSUFFICIENT_EVIDENCE` (11 < 15 episodes) |

## Relationship to prior art

* All three are **NEW_PROJECT_HYPOTHESIS** (`source_faithful = false`,
  `source_attribution = NONE`). No result may be attributed to a source hypothesis.
* Existing cross-sectional hypothesis `H-XSEC-RELSTR-001` (`EXP-ARP-009`) was
  `INSUFFICIENT_EVIDENCE` on the 4-month daily corpus; `EXP-ARP-013` re-tests the
  same *family* with a distinct mechanism and a 6× larger, multi-regime corpus —
  a new experiment with a new id, not a silent re-reading.
* No mechanism here is a variant of the failed families (EMA crossover, momentum /
  breakout / trend / MR / volatility *timing*); each ranks *assets against each
  other* at a single instant.
