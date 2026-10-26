# Independent verification — RFC-TAP-AI-BOTS-003H

> Checks 1-25 are the 003G byte checks, imported from
> `scripts/ai_bots_003g_verify.py` and unmodified; checks 26-33 are the 003H
> accounting, timestamp, settle and projection checks.

**Session:** `reports\ai-bots\RFC-AI-BOTS-003G\session`
**Checks:** 28 PASS / 5 FAIL (33 total)

> Verifier: `scripts/ai_bots_003g_verify.py`. It imports no `trading_bot` module and
> recomputes every claim from the raw JSONL. It is written by the builder, so it is
> not a substitute for a second independent agent (`BUILDER != VERIFIER`).

| # | check | result | detail |
| --- | --- | --- | --- |
| 1 | `stream_chain_intact` | PASS | 11 chained rows |
| 2 | `session_is_paper` | PASS | mode=PAPER live_enabled=False |
| 3 | `subbar_enabled_for_paper_only` | PASS | subbar_entries=PAPER_ONLY |
| 4 | `tested_runtime_equals_used_runtime` | FAIL | src/trading_bot/vision/lane.py: c20fe99f43b8cb70c538aa8a98b5f3415bb4f5cefe0d3c733089dc2dab0520a8 -> e316b68eded2934a1f2a053dd8404876eb0d73e4539e4c28a1045bea3febf498; src/trading_bot/vision/prospective.py: e4ff5753c2f9b425b78c21caef1e462ddf5bfbee50595219ad58afa36a54e404 -> a6aa3610660cfe80f3d35be8029f5cbc1e4688c209551806b99234822d30fe8f |
| 5 | `no_live_order_route_in_runtime` | PASS | no order endpoint or order call in the runtime set |
| 6 | `every_stored_minute_is_closed` | PASS | no forming bar was stored |
| 7 | `minutes_strictly_increasing` | PASS | no duplicate or out-of-order minute in any store |
| 8 | `a_cycle_was_executed` | PASS | 8 executed cycles |
| 9 | `data_time_le_decision_time` | PASS | ok |
| 10 | `declared_delay_is_inside_the_wait` | PASS | declared delivery delay respected |
| 11 | `published_series_rebuilds_from_minutes` | PASS | per-cycle series digests match |
| 12 | `cycle_ledgers_are_chained` | PASS | chains intact |
| 13 | `subbar_fills_are_observed_prices` | PASS | fill price = 1m open at or after the answer |
| 14 | `entry_bar_range_is_post_fill` | PASS | range rebuilt minute by minute |
| 15 | `at_least_one_subbar_fill` | PASS | 6 sub-bar fill rows across the session, 1 in the last ledger |
| 16 | `fills_have_an_approved_risk_gate` | PASS | every fill joins an approved decision |
| 17 | `close_pnl_identity_holds` | PASS | net = gross - commissions - execution cost |
| 18 | `no_past_decision_changed` | PASS | prefix determinism checked |
| 19 | `summary_net_matches_ledger` | PASS | summary=0 ledger=0 |
| 20 | `summary_fills_match_ledger` | PASS | summary=1 ledger=1 |
| 21 | `summary_closed_match_ledger` | PASS | summary=0 ledger=0 |
| 22 | `no_live_orders_recorded` | PASS | every stream row records live_orders=0 |
| 23 | `no_live_mode_in_any_artifact` | PASS | no artefact claims LIVE |
| 24 | `receipt_is_never_before_the_close` | PASS | 552 minutes with a positive delivery latency |
| 25 | `manifest_matches_the_minute_bytes` | PASS | each store's sha256 matches the manifest |
| 26 | `accounting_contract_is_versioned_and_defined` | FAIL | schema=None missing_terms=['costs_realised_usdt', 'costs_total_usdt', 'entry_commissions_accrued_open_usdt', 'pnl_realised_usdt', 'pnl_unrealised_usdt', 'pnl_total_usdt', 'marked_equity_usdt'] missing_meanings=['costs_usdt', 'costs_realised_usdt', 'costs_total_usdt', 'entry_commissions_accrued_open_usdt', 'pnl_realised_usdt', 'pnl_unrealised_usdt', 'pnl_total_usdt', 'marked_equity_usdt'] |
| 27 | `costs_usdt_still_means_realised_cost` | PASS | summary=0 rebuilt_from_CLOSE_rows=0 |
| 28 | `open_position_commissions_are_accrued_once` | FAIL | open_positions=1 accrued_from_fills=0.0 published=0.0 costs_total=0.0 notes=[] |
| 29 | `marked_equity_rebuilds_from_raw_minutes` | FAIL | marks={'BTC/USDT': 82716.68, 'ETH/USDT': 2430.86} unrealised_gross=0.0 rebuilt_net=0.0 published_net=None rebuilt_marked=10000.0 published=None notes=['BTC/USDT: no FILL row or no mark price'] |
| 30 | `no_position_is_counted_twice` | PASS | fills=1 distinct=1 open_and_closed=[] |
| 31 | `fill_instants_are_ordered_and_named` | PASS | fills=1 problems=[] |
| 32 | `live_minutes_were_seen_after_they_settled` | PASS | settle_ms=2500 live_minutes_checked=62 problems=[] |
| 33 | `session_summary_matches_the_lane_ledger` | FAIL | schema=None disagreements=[] projected_keys=[] |
