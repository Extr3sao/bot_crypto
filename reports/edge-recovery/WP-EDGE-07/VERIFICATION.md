# WP-EDGE-07 — independent verification

*Run at `2026-10-14T09:42:29Z`. Result: **PASS** (13/13 checks).*

| # | Claim re-derived | Result | Detail |
| --- | --- | --- | --- |
| A-1 | the volume is above the runtime's 2 GiB critical floor | True | `{"free_bytes": 3307401216, "free_gib": 3.08, "critical_floor_bytes": 2147483648, "healthy_floor_bytes": 5368709120, "clears_healthy_floor": false}` |
| A-2 | every path the reclaim recorded as removed is gone, and at least one sweep was applied | True | `{"applied_runs": 4, "paths_recorded_as_removed": 193, "paths_that_still_exist": [], "reclaimed_bytes_total": 2261922757}` |
| A-3 | at least two real scheduled ticks observed after the reclaim | True | `{"after": "2026-10-14T08:44:22Z", "count": 4, "ticks": [{"slot_key": "2026-10-14T08:45Z", "started_at_utc": "2026-10-14T08:55:56Z", "new_bars": 18, "market_requests": 7}, {"slot_key": "2026-10-14T09:00Z", "started_at_…` |
| A-4 | every scheduled tick after the wiring has a durable receipt, and its ran/not-ran follows the tick's own outcome | True | `{"wiring_reference": "2026-10-14T09:07:00Z", "scheduled_ticks_since": 3, "receipts_on_file": 3, "receipts_missing": [], "receipts_inconsistent_with_the_tick": [], "last_receipt": {"after_outcome": "OBSERVED", "artifac…` |
| A-5 | every scheduled slot WP-EDGE-06 published is still in the lane's log, in order, never replayed, and its store still holds every series | True | `{"run_records": 98, "slots_anchored": 11, "slots_vanished": [], "records_replayed": 0, "started_at_non_decreasing": true, "store_series": {"15m/BTC.jsonl": 663, "15m/ETH.jsonl": 663, "15m/SOL.jsonl": 663, "1h/BTC.json…` |
| B-1 | every holdout shard still hashes to the digest its manifest recorded | True | `{"symbols": ["BTCUSDT", "ETHUSDT", "SOLUSDT"], "mismatched": [], "corpus_digest": "196884f9e719315eaf4a0e1844d28cdf2528f9743f043931c9383a172a7e3cec", "gaps": 0}` |
| B-2 | the parameters read on the new window are the registered bytes, and the run says so | True | `{"recomputed": "9ceb20fc7d4500c334e2d58f6ff4cd6d26c6b228c4f8ef93f3c709082e44e8ad", "registered": "9ceb20fc7d4500c334e2d58f6ff4cd6d26c6b228c4f8ef93f3c709082e44e8ad", "recorded": "9ceb20fc7d4500c334e2d58f6ff4cd6d26c6b22…` |
| B-3 | the runner reproduced every published consulted-window figure it re-derived | True | `{"figures": 10, "unequal": []}` |
| B-4 | the trend verdict follows from its own checks by the registered mapping | True | `{"published": "REJECT", "recomputed": "REJECT", "failed": ["P2", "P3", "P4", "P5", "P6", "R1", "R2"]}` |
| B-5 | nothing was promoted, no order was sent, every reading is hypothetical | True | `{"validation.promotion": "NONE", "validation.order_sent": false, "validation.hypothetical": true, "active.promotion": "NONE", "active.order_sent": false, "active.hypothetical": true}` |
| B-6 | the new window begins after the last bar of every frozen corpus | True | `{"new_window_start_ms": 1772323200000, "frozen_last_bar_ms": 1772319600000, "gap_hours": 1.0}` |
| C-1 | each ACTIVE verdict follows from its own checks, and a screened-out book read no independent window | True | `{"books": {"edge07_active_fade": "REJECT_NO_GROSS_EDGE", "edge07_active_thrust": "REJECT_NO_GROSS_EDGE"}, "mismatched": {}, "holdout_read_by_any_candidate": false}` |
| C-2 | the published one-hour ceiling for BTC on the new window recomputes from the bars | True | `{"published": 27.6151, "recomputed": 27.6151, "observations": 5453}` |

## The verifier's own saboteur

14/14 sabotages detected (baseline PASS).


## What a PASS means, and what it does not

- It means the artefacts this work package published agree with each other and with the
  live facts they rest on: the floors, the reclaim history, the lane's own run log and its
  receipt, the corpus digests, the registered parameters, the verdicts' own logic, and one
  measured ceiling recomputed from the bars.
- It does not mean the strategies make money. Two of the three books measured here are
  rejected and nothing is promoted; a PASS on a rejection is the intended outcome.
