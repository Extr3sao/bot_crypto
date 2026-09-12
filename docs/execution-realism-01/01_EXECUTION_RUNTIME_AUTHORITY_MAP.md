# 01 — EXECUTION RUNTIME AUTHORITY MAP — EXECUTION-REALISM-AND-COST-AUTHORITY-01

Base: `0941082` · Generated: `2026-09-12T11:30:00Z` · Machine: `01_EXECUTION_RUNTIME_AUTHORITY_MAP.json`

## Classified

| Component | Path | Class | Evidence |
|---|---|---|---|
| **PaperBroker** | `paper/broker.py` | **RUNTIME_AUTHORITATIVE** | sole execution boundary (`PaperCycleEngine → RiskManager → PaperBroker.execute_signal`); `equity == initial + sum(pnl)` via `entry_commission` stored + both commissions at close; `check_positions_ohlc(both_hit_policy=stop_first)` conservative |
| PaperBroker types | `paper/types.py` | RUNTIME_AUTHORITATIVE | `PaperExecutionSummary/Result/Metrics` wired to harness/reporting |
| **PaperCycleEngine** | `paper/paper_cycle.py` | RUNTIME_AUTHORITATIVE | `PIT OHLCV → Agent → Router → Family → SignalAdapter → Portfolio → Risk → PaperBroker`; `intent_cloid = PAPER-sha256(s,st,d,t)`; `IdempotencyGuard`; 15 R2 cycles exercised |
| **ExecutionCostModel** | `execution/cost_model.py` | RUNTIME_AUTHORITATIVE | `commission 5bp + slippage 1bp` defaults (≈12 bps RT); `compute_costs(): gross = f(slippage) - fees = total; net_pnl = gross - total`; `planned_net_rr()` admitted |
| **TradeIntent + intent_id** | `execution/intent.py` | RUNTIME_AUTHORITATIVE | 8 canonical fields → `sha256`; `derive_client_order_id`; `FillLedger`, `IdempotentSubmitGate` (`ECONOMIC_ORDERS_PER_INTENT <=1`), `AmbiguousAckRecovery` |
| ExecutionGateway | `execution/gateway.py` | RUNTIME_REACHABLE | `VenuePort(submit/query/venue_order_id_of)` adapter-agnostic, no I/O; not yet on PAPER path (PaperBroker used directly) |
| ExecutionService | `execution/service.py` | RUNTIME_REACHABLE | durable JSONL journal, dead-man `FeedGuard`, startup reconciliation fail-closed; LIVE disabled (port injection) |
| ExecutionJournal | `execution/journal.py` | RUNTIME_REACHABLE | append-only `CREATED/SUBMITTING/...` with reason+evidence, durable |
| FeedGuard | `execution/feed_guard.py` | RUNTIME_REACHABLE | `BLOCK` forbids entry, intent NOT journaled REJECTED (transient) |
| LiveGate | `execution/live_gate.py` | RUNTIME_REACHABLE | pre-flight validator; `runtime.mode=paper`, `live_trading_enabled=false`, no creds |
| IdempotencyGuard | `execution/idempotency.py` | RUNTIME_AUTHORITATIVE | reused by `PaperCycleEngine` → `R2_INTENT_LEDGER 3 entries` (2026-09-10 BTC buy/sell, ETH sell) |
| Reconciliation | `paper/reconciliation.py` | RUNTIME_AUTHORITATIVE | `StartupReconciler(CLOSE_ORPHANED)` + `reconcile_session(price map from snapshots)`; R2 `R2_COVERAGE_DAILY 2 days` |
| SignalAdapter | `paper/signal_adapter.py` | RUNTIME_AUTHORITATIVE | single `AlphaSignal → Signal` conversion point |
| OHLCVFetcher | `market_data/ohlcv_fetcher.py` | RUNTIME_AUTHORITATIVE | `binanceusdm` public REST via CCXT, `OHLCVStore.upsert` idempotent, price authority `BTC/ETH/SOL_1h 58680/58680/52505` |
| RiskManager | `risk/manager.py` | RUNTIME_AUTHORITATIVE | mandatory before broker; `max_open_positions 3`, `min/max notional 20/500`, blocks `spread 50bps / ATR 8% / latency 2000ms / weekend` |
| Shadow | `shadow/` | RUNTIME_AUTHORITATIVE | `RiskGateRouter` 11 captures `Max open positions reached (1)`, `11/11 Mature→Resolved PROFITABLE_REJECT mean 0.39R`, `SHADOW_PAPERBROKER_CALLS 0` |

## Verified invariants

- `PaperBroker.execute_signal` is **ONLY** execution boundary (grep: zero `exchange.*placeOrder` in paper path).
- `equity == initial_equity + sum(ClosedTrade.pnl)` (both commissions at close, entry stored).
- Slippage always worsens: entry `buy*(1+mult)` / `sell/(1+mult)`; exit `buy/(1+mult)` / `sell*(1+mult)`.
- OHLC `both_hit_policy=stop_first` (conservative).
- `intent_cloid = PAPER-sha256(s,st,d,t)` deterministic.
- `ECONOMIC_ORDERS_PER_INTENT <=1` (`IdempotentSubmitGate`).
