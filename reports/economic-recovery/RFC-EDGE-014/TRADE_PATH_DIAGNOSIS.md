# WP-EDGE-14A — trade path diagnosis

*Window `2026-10-06T19:59:02Z` → `2026-10-16T12:45:03Z` (9.6986 days, requested 30).*

Live status **VERIFIED_ZERO**: the exchange's private ledger was not consulted; what is verified is that no order left this runtime, from the ledger the runtime writes itself. A zero at the venue is not asserted without a venue source.

## Funnel

| stage | count | evidence class | note |
| --- | --- | --- | --- |
| MARKET_DATA | 4 | observed | each row carries bars_used; the raw OHLCV is pinned by hash per row |
| SIGNAL | 4 | observed | 1 directional, 3 NO_TRADE |
| PROPOSAL | 1 | observed | no separate proposal artefact exists in this ledger; the directional decision is the last stage the ledger records before risk |
| ROUTER | UNKNOWN | unknown | UNKNOWN, not zero: this campaign path does not write a router record |
| RISK | UNKNOWN | unknown | UNKNOWN, not zero: risk was not invoked on a directional decision in this window |
| ORDER_INTENT | 0 | absent_ledger | no intent ledger exists on this path, so zero is asserted weakly: nothing would have recorded an intent had one happened |
| PAPER_BROKER | 0 | absent_ledger | no paper broker ran on this path; no fill ledger exists |
| RECONCILIATION | 4 | observed | 1 closed as WIN/LOSS, 3 as NO_TRADE |

## Headline

| measure | value |
| --- | --- |
| closed_trades | 1 |
| directional_decisions | 1 |
| exchange_orders | 0 |
| paper_broker_fills | 0 |
| paper_order_intents | 0 |
| sealed_decisions | 4 |
| settled_outcomes | 4 |

stages whose ledger is absent are UNKNOWN or weakly-zero with the absence named; only stages with a present ledger assert a real zero

over the measured window this runtime sealed 4 decision(s), sent 0 paper intent(s) and 0 exchange order(s)
