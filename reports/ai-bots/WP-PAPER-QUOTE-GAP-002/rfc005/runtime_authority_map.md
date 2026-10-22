# Runtime authority map — RFC-PAPER-ISOLATION-005

Derived by `scripts/isolation_inventory.py` (AST over the tree at the source commit) and
re-read by `scripts/verify_isolation.py` from the git blobs, so the map and the code cannot
disagree without the verifier noticing.

## Order-capable routes (13 found, 11 reachable at runtime)

| Route | File | Authority | Control |
|---|---|---|---|
| `BitunixSpotConnector.create_order` | `market_data/bitunix.py` | RUNTIME_REACHABLE | `assert_order_allowed` then `UnsupportedConnectorOperationError` |
| `BitunixSpotConnector.cancel_order` | `market_data/bitunix.py` | RUNTIME_REACHABLE | `assert_order_allowed` |
| `BitunixFuturesClient.place_order` | `market_data/bitunix_futures.py` | RUNTIME_REACHABLE (HTTP layer) | `assert_order_allowed` |
| `BitunixFuturesConnector.create_order` | `market_data/bitunix_futures.py` | RUNTIME_REACHABLE | `assert_order_allowed` |
| `BitunixFuturesConnector.cancel_order` | `market_data/bitunix_futures.py` | RUNTIME_REACHABLE | `assert_order_allowed` |
| `CCXTExchangeConnector.create_order` | `market_data/exchange_connector.py` | RUNTIME_REACHABLE | `assert_order_allowed` before ccxt |
| `CCXTExchangeConnector.cancel_order` | `market_data/exchange_connector.py` | RUNTIME_REACHABLE | `assert_order_allowed` |
| `_ObservedConnector.create_order` | `market_data/wiring.py` | RUNTIME_REACHABLE | delegates to `_inner.create_order` (gated) |
| `_ObservedConnector.cancel_order` | `market_data/wiring.py` | RUNTIME_REACHABLE | delegates to `_inner.cancel_order` (gated) |
| `ExchangeConnector.create_order` | `market_data/exchange_connector.py` | ABSTRACT | no body: cannot execute |
| `ExchangeConnector.cancel_order` | `market_data/exchange_connector.py` | ABSTRACT | no body |
| `MultiExchangeConnector.create_order` | `market_data/types.py` | PROTOCOL | no body |
| `MultiExchangeConnector.cancel_order` | `market_data/types.py` | PROTOCOL | no body |

CLI route: `trading_bot.app::_cmd_place_order` (not a class method, so not in the AST
table above) carries its own gate plus the pre-existing `--confirm-live` and mode checks.

## Network-capable runtime modules (15)

`app`, `market_data.bitunix`, `market_data.bitunix_futures`,
`market_data.exchange_connector`, `market_data.minute_collector`,
`research.campaign_lock`, `research.economic_recovery.paper_exec`,
`research.edge03.autonomous`, `research.edge03.ingest`, `research.edge05.watchdog`,
`research.edge09.sources`, `research.forward.collector`, `research.market_provenance`,
`vision.durable`, `vision.provider`.

Only the ones that the paper runtime under test can import matter for this WP:
`market_data.*` (venue SDK and REST clients), `app` (CLI order route) and
`vision.provider` (the model provider, used only in `--mode live`, which is declared outside
the isolation claim). The research collectors are separate jobs and are not started by the
paper runtime.

## Entry points that construct the paper runtime

- `scripts/ai_bots_run.py --mode mock` — installs the policy before building the lane.
- `scripts/ai_vision_lane.py --mode replay` — same, before provider or lane construction.
- `scripts/recovery_child.py` — RFC004 laboratory; keeps its own deny hook.
- `scripts/ai_bots_003c_capture.py`, `scripts/ai_bots_003g_compare.py`,
  `scripts/exp_003j_replay.py`, `scripts/paper_resume_drill.py`, `scripts/quote_gap_lab.py`
  — research/replay tools; they build the lane but are not the runtime of this WP. Their
  omission is named here rather than hidden: the claim is about the two entry points above.

## What the policy does not cover

- An operating-system sandbox: not available here. `OS_SANDBOX = NOT_AVAILABLE`.
- Child processes: the audit hook is per interpreter (measured in ISO-09).
- Network performed by a native extension that does not raise a Python audit event.
- `--mode live` of `ai_vision_lane.py` and `ai_bots_run.py`: those call an external model
  provider by design; they are outside the paper-isolation claim, not exempted inside it.
