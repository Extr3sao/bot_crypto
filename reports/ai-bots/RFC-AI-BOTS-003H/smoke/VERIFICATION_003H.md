# Independent verification — RFC-TAP-AI-BOTS-003H

> Checks 1-25 are the 003G byte checks, imported from
> `scripts/ai_bots_003g_verify.py` and unmodified; checks 26-33 are the 003H
> accounting, timestamp, settle and projection checks.

**Session:** `reports\ai-bots\RFC-AI-BOTS-003H\smoke`
**Checks:** 33 PASS / 0 FAIL (33 total)

> Verifier: `scripts/ai_bots_003g_verify.py`. It imports no `trading_bot` module and
> recomputes every claim from the raw JSONL. It is written by the builder, so it is
> not a substitute for a second independent agent (`BUILDER != VERIFIER`).

| # | check | result | detail |
| --- | --- | --- | --- |
| 1 | `stream_chain_intact` | PASS | 13 chained rows |
| 2 | `session_is_paper` | PASS | mode=PAPER live_enabled=False |
| 3 | `subbar_enabled_for_paper_only` | PASS | subbar_entries=PAPER_ONLY |
| 4 | `tested_runtime_equals_used_runtime` | PASS | all runtime hashes match |
| 5 | `no_live_order_route_in_runtime` | PASS | no order endpoint or order call in the runtime set |
| 6 | `every_stored_minute_is_closed` | PASS | no forming bar was stored |
| 7 | `minutes_strictly_increasing` | PASS | no duplicate or out-of-order minute in any store |
| 8 | `a_cycle_was_executed` | PASS | 10 executed cycles |
| 9 | `data_time_le_decision_time` | PASS | ok |
| 10 | `declared_delay_is_inside_the_wait` | PASS | declared delivery delay respected |
| 11 | `published_series_rebuilds_from_minutes` | PASS | per-cycle series digests match |
| 12 | `cycle_ledgers_are_chained` | PASS | chains intact |
| 13 | `subbar_fills_are_observed_prices` | PASS | fill price = 1m open at or after the answer |
| 14 | `entry_bar_range_is_post_fill` | PASS | range rebuilt minute by minute |
| 15 | `at_least_one_subbar_fill` | PASS | 8 sub-bar fill rows across the session, 1 in the last ledger |
| 16 | `fills_have_an_approved_risk_gate` | PASS | every fill joins an approved decision |
| 17 | `close_pnl_identity_holds` | PASS | net = gross - commissions - execution cost |
| 18 | `no_past_decision_changed` | PASS | prefix determinism checked |
| 19 | `summary_net_matches_ledger` | PASS | summary=0 ledger=0 |
| 20 | `summary_fills_match_ledger` | PASS | summary=1 ledger=1 |
| 21 | `summary_closed_match_ledger` | PASS | summary=0 ledger=0 |
| 22 | `no_live_orders_recorded` | PASS | every stream row records live_orders=0 |
| 23 | `no_live_mode_in_any_artifact` | PASS | no artefact claims LIVE |
| 24 | `receipt_is_never_before_the_close` | PASS | 572 minutes with a positive delivery latency |
| 25 | `manifest_matches_the_minute_bytes` | PASS | each store's sha256 matches the manifest |
| 26 | `accounting_contract_is_versioned_and_defined` | PASS | schema=paper-accounting/2 missing_terms=[] missing_meanings=[] |
| 27 | `costs_usdt_still_means_realised_cost` | PASS | summary=0 rebuilt_from_CLOSE_rows=0 |
| 28 | `open_position_commissions_are_accrued_once` | PASS | open_positions=1 accrued_from_fills=0.5 published=0.5 costs_total=0.5 notes=[] |
| 29 | `marked_equity_rebuilds_from_raw_minutes` | PASS | marks={'BTC/USDT': 83005.66, 'ETH/USDT': 2444.61} unrealised_gross=0.99443125 rebuilt_net=0.49443125 published_net=0.49443125 rebuilt_marked=10000.49443125 published=10000.49443125 notes=[] |
| 30 | `no_position_is_counted_twice` | PASS | fills=1 distinct=1 open_and_closed=[] |
| 31 | `fill_instants_are_ordered_and_named` | PASS | fills=1 problems=[] |
| 32 | `live_minutes_were_seen_after_they_settled` | PASS | settle_ms=2500 live_minutes_checked=82 problems=[] |
| 33 | `session_summary_matches_the_lane_ledger` | PASS | schema=paper-accounting/2 disagreements=[] projected_keys=['costs_realised_usdt', 'costs_total_usdt', 'costs_usdt', 'entry_commissions_accrued_open_usdt', 'initial_equity_usdt', 'mark_prices', 'marked_equity_usdt', 'pnl_realised_usdt', 'pnl_total_usdt', 'pnl_unrealised_usdt', 'schema_version'] |
