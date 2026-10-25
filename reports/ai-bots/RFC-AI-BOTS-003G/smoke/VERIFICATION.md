# Independent verification — RFC-TAP-AI-BOTS-003G

**Session:** `reports\ai-bots\RFC-AI-BOTS-003G\smoke`
**Checks:** 24 PASS / 1 FAIL (25 total)

> Verifier: `scripts/ai_bots_003g_verify.py`. It imports no `trading_bot` module and
> recomputes every claim from the raw JSONL. It is written by the builder, so it is
> not a substitute for a second independent agent (`BUILDER != VERIFIER`).

| # | check | result | detail |
| --- | --- | --- | --- |
| 1 | `stream_chain_intact` | PASS | 5 chained rows |
| 2 | `session_is_paper` | PASS | mode=PAPER live_enabled=False |
| 3 | `subbar_enabled_for_paper_only` | PASS | subbar_entries=PAPER_ONLY |
| 4 | `tested_runtime_equals_used_runtime` | FAIL | src/trading_bot/vision/prospective.py: db59c211f3b259b8f70755a8153afd97696d53e30c17315559cb3e69c9315f79 -> e4ff5753c2f9b425b78c21caef1e462ddf5bfbee50595219ad58afa36a54e404; src/trading_bot/market_data/minute_collector.py: ab1a057ffd23b9cd03b26367a693379e02d3da6a443a1390e6089d9a1d27c495 -> 4fd7ddd8baa9e827f14a4565ef1dc92a685f400e44a2c0eed73a5366862bc0f9 |
| 5 | `no_live_order_route_in_runtime` | PASS | no order endpoint or order call in the runtime set |
| 6 | `every_stored_minute_is_closed` | PASS | no forming bar was stored |
| 7 | `minutes_strictly_increasing` | PASS | no duplicate or out-of-order minute in any store |
| 8 | `a_cycle_was_executed` | PASS | 2 executed cycles |
| 9 | `data_time_le_decision_time` | PASS | ok |
| 10 | `declared_delay_is_inside_the_wait` | PASS | declared delivery delay respected |
| 11 | `published_series_rebuilds_from_minutes` | PASS | per-cycle series digests match |
| 12 | `cycle_ledgers_are_chained` | PASS | chains intact |
| 13 | `subbar_fills_are_observed_prices` | PASS | fill price = 1m open at or after the answer |
| 14 | `entry_bar_range_is_post_fill` | PASS | range rebuilt minute by minute |
| 15 | `at_least_one_subbar_fill` | PASS | 1 of 1 fills happened inside the entry bar |
| 16 | `fills_have_an_approved_risk_gate` | PASS | every fill joins an approved decision |
| 17 | `close_pnl_identity_holds` | PASS | net = gross - commissions - execution cost |
| 18 | `no_past_decision_changed` | PASS | prefix determinism checked |
| 19 | `summary_net_matches_ledger` | PASS | summary=0 ledger=0 |
| 20 | `summary_fills_match_ledger` | PASS | summary=1 ledger=1 |
| 21 | `summary_closed_match_ledger` | PASS | summary=0 ledger=0 |
| 22 | `no_live_orders_recorded` | PASS | every stream row records live_orders=0 |
| 23 | `no_live_mode_in_any_artifact` | PASS | no artefact claims LIVE |
| 24 | `receipt_is_never_before_the_close` | PASS | 420 minutes with a positive delivery latency |
| 25 | `manifest_matches_the_minute_bytes` | PASS | each store's sha256 matches the manifest |
