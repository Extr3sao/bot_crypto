# 07 — LATENCY REPORT — EXECUTION-REALISM-AND-COST-AUTHORITY-01

Machine: `07_LATENCY_REPORT.json` · Runtime: `paper_cycle` + `execution/*` (no real venue)

## 18 — Traced path (paper, no live venue)

```
decision (StrategyRouter/Signal generation, bar_ts)
  → verification (DecisionVerifier BUILDER!=VERIFIER)
  → RiskManager.check_signal (mandatory)
  → PaperBroker.execute_signal(Signal{price, notional, SL, TP})
  → execution: immediate (no queue)
```

Artifacts with timestamps: `PaperSessionResult(started_at/ended_at, duration_ms)`, `PaperCycleEngine.CycleStageCounts`, `R2_CYCLE_LEDGER.jsonl` (cycle_id/run_id/utc_date, not decision→risk ms), `ClosedTrade opened_at/closed_at` second-level (`time.time()`), `R2_INTENT_LEDGER written_at`.

## Measured

| Hop | How measured | Value (paper) | Type |
|---|---|---|---|
| `decision_to_Risk` | inspector: Risk path is **synchronous in-process** (no network) — same call stack | ~µs-ms `COMPUTE_LATENCY` | COMPUTE |
| `Risk_to_intent` | `intent_cloid` built before Risk; Risk approval gates `PaperBroker.execute_signal` in same engine call | ~µs | COMPUTE |
| `intent_to_fill` | `PaperBroker.execute_signal` returns `PaperPosition` **immediately** (no venue submit) | `0 ms` `SIMULATED_PAPER_LATENCY=0` | simulated |
| `decision_to_fill` | synchronous walk: proposal→decision→Risk→broker all in one `PaperCycleEngine.run_cycle` | `0 ms` simulated | COMPUTE |
| cycle duration | `PaperSessionResult.duration_ms` + `R2_CYCLE_LEDGER coverage_minutes` (`1.704 / 1.946 min` samples) | scanner+cycle seconds, not execution latency | COMPUTE |
| **Network latency (real exchange)** | **not measurable** — no real `exchange.createOrder/fetchTicker` call (`LIVE_CALLS=0`) | **`NOT_MEASURED`** | NETWORK |
| feed staleness guard | `execution/feed_guard.FeedDeadManGuard` (BLOCK on stale, intent not journaled REJECTED) | threshold not exercised (no staleness in R2) | guard |

No `NETWORK_LATENCY` exists for the current authority — `execution/gateway.submit` exists but no `VenuePort` is mounted for PAPER (PaperBroker is used directly). `exchange_connector.fetch_ohlcv` is market-data fetch, not order placement.

## 19 — OFFLINE adverse-move diagnostic contract (§19)

- Contract: `src/trading_bot/execution_realism/adverse_move.py` — `AdverseMoveHorizons(h_50ms..h_5s)`, helper `adverse_move_bps(decision_price, price_after)` + `adverse_move_for_direction(raw, direction)` (LONG adverse = price falls, SHORT adverse = rises).
- Horizons: `50ms / 100ms / 250ms / 500ms / 1s / 5s`.
- Coverage rule: **do not fabricate sub-second from 5m/1h candles.** Only where data supports it may a horizon be populated; otherwise `None` + `coverage="" limitations="insufficient granularity"`.
- AggTrades opportunity (§17): admitted `TRADE_FLOW_DATASET_MANIFEST.json` (aggTrades sample, not linked to fills) + deep funding sample — could support `250ms-5s` **only** where aggTrades depth is available (not for full 100 GB backfill without `COST_REVIEW_REQUIRED`).
- Stale-quotes / price movement `decision→fill` in paper: currently `decision_price == signal.price` (tick derived) and `fill_price = signal.price ± slippage` — no adverse move beyond slippage+spread; real adverse is `UNKNOWN` until ticks/aggTrades archived.

## Verdict

`DECISION_LATENCY_REAL = UNKNOWN` for a real venue (no exchange latency measured). Paper latency is usefully ~0 with correct **compute-only** semantics, but says nothing about real `50ms-1s` adverse move. Must archive `tick/bookTicker` or `aggTrades` for the `19` contract to produce `P50/P90` adverse-move curves — currently all `None`.
