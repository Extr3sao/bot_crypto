# RUNTIME EXECUTION AUTHORITY MAP — EXECUTION-RELIABILITY-RUNTIME-01

Checkpoint: INTELLIGENCE-AND-EXECUTION-HARDENING-01 (Track A)
Base: `814f0e4` (EXECUTION-RELIABILITY-01 primitives)
Audited at: HEAD `814f0e4` + working tree

## 1. Runtime-reachable execution entrypoints and adapters

| Adapter | File | Runtime reachability | Whitelist |
| --- | --- | --- | --- |
| BinanceConnector (spot) | `src/trading_bot/market_data/exchange_connector.py:658` | **RUNTIME_REACHABLE** (registry factory, TSK-022.4) | yes |
| BybitConnector (spot, demo) | `src/trading_bot/market_data/exchange_connector.py:691` | **RUNTIME_REACHABLE** (registry factory; `.env` currently `EXCHANGE_ID=bybit`) | yes |
| CCXTExchangeConnector (generic) | same file, line 187 | REACHABLE (compat class; whitelist `{binance, bitunix, bybit}`) | restricted |
| BitunixSpotConnector | `src/trading_bot/market_data/bitunix.py:411` | **RUNTIME_REACHABLE** (own connector, TSK-022) | yes |
| BitunixFuturesConnector | `src/trading_bot/market_data/bitunix_futures.py:378` | **RUNTIME_REACHABLE** (clientId echo idempotency) | yes |
| OKX | — | **NOT_RUNTIME_REACHABLE** — no adapter exists; explicitly excluded by whitelist comment (lines 43-46, 107-108): "Cualquier otra ampliación (Coinbase, OKX, Kraken...) requiere un ticket dedicado" | no |
| Kraken | — | **NOT_RUNTIME_REACHABLE** — same as OKX | no |

The paper runtime (POC01) does NOT call any of these adapters for order
placement: it uses `PaperBroker` (paper cycle) and the demo fixture path.
The CCXT/Bitunix connectors are the *real* execution boundary for any future
non-paper mode, and are currently exercised only through unit tests.

## 2. Primitive integration status per adapter (before this checkpoint)

All adapters share the same shape: `create_order(..., client_order_id)` with
idempotent tenacity retries reusing the caller's `client_order_id`, but:

- **No adapter** receives a `TradeIntent`-derived stable identity (callers
  pass ad-hoc ids or none → `uuid4()` fallback in the generic connector).
- **No adapter** writes an `ExecutionJournal` — order state lives in
  connector logs only.
- **No adapter** implements ACK_UNKNOWN recovery (a raised submit is
  propagated; retry policy is tenacity-level, not identity-level).
- Fill idempotency exists only inside `PaperBroker` (single-owner fills);
  no venue-fill-id ledger on the adapter path.
- Cancel is fire-and-confirm-void: `cancel_order()` returns None; no
  CANCEL_PENDING/CANCELLED distinction.

## 3. Integration added in this checkpoint (Track A)

`src/trading_bot/execution/gateway.py::ExecutionGateway` composes the
certified primitives into ONE authority path:

```
TradeIntent -> intent_id -> client_order_id
  -> ExecutionJournal (CREATED -> SUBMITTING -> ACCEPTED/ACK_UNKNOWN/...)
  -> VenuePort (submit/query/venue_order_id_of)
  -> ACK_UNKNOWN resolution / controlled retry / fill idempotency
  -> cancel (CANCEL_PENDING -> CANCELLED on confirmation)
  -> reconcile (adopt-or-close, never auto-resubmit)
  -> execution_ready() fail-closed startup gate
```

Post-submit retry short-circuit: an intent already ACCEPTED/PARTIALLY_FILLED/
FILLED/CANCEL_*/REJECTED returns the cached venue reference with **zero**
additional venue calls. Controlled retries route through the same idempotent
gate, so even a "retry" cannot mint a second economic order.

E2E evidence: `tests/unit/execution/test_gateway_e2e.py` (16 tests) —
A1 identity/retry/wall-clock/feed-block, A2 adopt/absent-retry/uncertain-block,
A3 duplicate+partial+out-of-order fills, A4 startup reconciliation and
EXECUTION_READY fail-closed gate, cancel semantics.

## 4. Adapter classification (directive of Track A)

| Adapter | Classification | Reason |
| --- | --- | --- |
| BinanceConnector | **PARTIALLY_INTEGRATED** | Idempotent client_order_id retries yes; TradeIntent identity, journal, ACK recovery, fill ledger: NO (gateway is available but not wired into this adapter's call sites) |
| BybitConnector | **PARTILY_INTEGRATED** (same as Binance) | identical CCXT base |
| BitunixSpotConnector | **PARTIALLY_INTEGRATED** | loud-fail on missing client_order_id correlation (strong); rest as above |
| BitunixFuturesConnector | **PARTIALLY_INTEGRATED** | clientId echo idempotency (strong); rest as above |
| OKX | **NOT_RUNTIME_REACHABLE** | no adapter |
| Kraken | **NOT_RUNTIME_REACHABLE** | no adapter |

No adapter is PRIMITIVES_INTEGRATED yet: wiring `ExecutionGateway` into the
adapters' call sites (app.py auto-trade, paper_cycle) is deliberately deferred
— POC01 is frozen and its runtime must not change.

## 5. A6 certification decision

**EXECUTION_RELIABILITY_FOUNDATION_ONLY** (not RUNTIME_CERTIFIED):

- Primitives + gateway are runtime-reachable *as a library* and adversarially
  tested E2E against a fake venue port at the real gateway boundary.
- Missing for RUNTIME_CERTIFIED: `ExecutionGateway` wired into at least one
  real adapter call site (Binance/Bybit/Bitunix) with journal persistence to
  disk, plus OKX/Kraken adapters (currently not runtime-reachable at all).
- Exact missing integration list:
  1. `app.py` / `paper_cycle.py` order paths do not construct `ExecutionGateway`.
  2. No adapter passes `derive_client_order_id(intent_id)` as cloid.
  3. `ExecutionJournal(path=...)` JSONL persistence not mounted in runtime.
  4. No OKX/Kraken connector exists (whitelist excludes them by design).
  5. `cancel_order` adapter return type is `None` — no confirmation payload
     to feed CANCELLED transitions in the real path.

LIVE remains DISABLED either way.
