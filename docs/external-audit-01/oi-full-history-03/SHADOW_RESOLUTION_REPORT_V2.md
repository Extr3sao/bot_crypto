# Shadow Resolution Report V2 — Corrected

Old ledger (`reports/poc02-r2-direction-arbitration-01/shadow/SHADOW_RESOLUTION_LEDGER.jsonl`) **preserved as invalid** — not overwritten.

- All 11 old entries have `maturity_time == decision_time` (0h) — they assume zero horizon, contradicting the frozen 48h.
- Correct maturity is `capture + 48h` per `SHADOW_MATURITY_AUTHORITY_V2.json`.

## Why V2 is awaiting rather than fabricating 11

This checkpoint records correction and policy; it does not rederive net-R values without a verifiable market path. Rules for future re-resolution (when mature and market data is verifiable):

- entry `plan.entry_reference` per capture
- direction `LONG/SHORT` per capture
- TP/SL from `plan.take_profit / stop_loss`, invalidation `preregistered_v1`
- horizon 48h, maturity cap, costs per preregistered cost model
- if both TP and SL occur within same coarse 1h bar and order unknown → `AMBIGUOUS_FIRST_TOUCH` (not PROFITABLE_REJECT)
- even 11/11 profitable → `INSUFFICIENT_SAMPLE` (no Risk change)

No `SHADOW_RESOLUTION_LEDGER_V2.jsonl` is emitted with fabricated `net_R`s in this checkpoint; the authority matrix plus maturity file makes rederivation possible and isolates H6.
