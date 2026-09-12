# 10 — PAPERBROKER GAP ANALYSIS — EXECUTION-REALISM-AND-COST-AUTHORITY-01

Machine: `10_PAPERBROKER_GAP_ANALYSIS.json` (§26 — DO NOT MODIFY PaperBroker this checkpoint §27)

## CURRENT_PAPERBROKER vs REALISTIC_EXECUTION_CONTRACT

| Dimension | Current PaperBroker | Realistic | Gap |
|---|---|---|---|
| **fill side** | **UNREALISTIC** — signal price ± synthetic `1bp/leg` (no bid/ask); LONG uses `signal*(1.0001)` should be `ask+slip`; SHORT `/1.0001` should be `bid-slip` | must reference `ask` (long) / `bid` (short) then slippage | fix: ingest `bookTicker` bid/ask per decision |
| **spread** | **MISSING** (0) | `0.013 BTC / 0.039 ETH / 0.98 SOL bps` round-trip at 2026-09-12 low-vol snapshot; historical UNKNOWN | bookTicker archiver (ADOPT_P1) |
| **slippage** | **APPROXIMATION** — deterministic `1bp/leg` synthetic (symmetric, always cost) | real `NOT_MEASURED` (no venue fills) | measure `decision mid → fill` with archived aggr/L1 |
| **fees** | **MATCH** — `5+5=10 fee RT` matches Binance VIP0 taker+taker; `5+5+1+1=12 RT` with slip matches paper; `planned_net_rr()` does `fees+slip` correctly | `2/5 bps VIP0` official (1.8/4.5 BNB) | none for fee math; config legacy `spot` must be pinned `usdm` in authority |
| **funding** | **MISSING** (0, honest) | BTC deep `7669 rows` admitted; `0 or ~0.4 bps per 8h` if `1h` bar straddles settlement (~12.5% of bars) | deep `ETH/SOL` backfill (EXECUTION-DATA-ADMISSION-01) |
| **latency** | **UNREALISTIC** (`0 ms`) — synchronous in-process | real `NETWORK_LATENCY NOT_MEASURED`; guard `FeedDeadMan` exists | measure `decision→fill ms` with live `VenuePort` or ticks; adverse-move contract exists (`adverse_move.py`) but coverage `None` until ticks archived |
| **partial fills** | **MISSING** — always 100% | `UNKNOWN` (no depth model) | L2 depth / aggTrades required for real partials; defer for PAPER small notionals |
| **rejects** | **APPROXIMATION** — only `paper.skip_duplicate` + `intent_cloid` dedup; no liquidity/venue rejects | real rejects `UNKNOWN` (no venue) | feed staleness `BLOCK` exists; real `InsufficientMargin` etc. needs live-port tests |
| **liquidity / impact** | **UNKNOWN** — `impact 0` assumed; paper `20-500 USDT` claims `NOT_EMPIRICALLY_ESTIMATED` beyond | `SMALL/MEDIUM/LARGE` buckets TBD vs depth | depth book + notional buckets |
| **market impact** | **MISSING** | `UNKNOWN` (no depth) | same as liquidity |
| **order lifecycle** | **APPROXIMATION** — market-only `TradeIntent(market)`; no limit/GTC/post-only/cancel; intent ledger `R2_INTENT 3` tracks `buy/sell` dedup by `date|asset|side|strategy` | real lifecycle `UNMODELED` | `execution/gateway + journal` already exist (RUNTIME_REACHABLE) — can be mounted for paper limit orders |
| **reconciliation** | **MATCH** — `reconcile_session(price map)` + `StartupReconciler(CLOSE_ORPHANED)` + `report_json`; `equity == initial+sum(pnl)` proven | same (in-paper recon) | none — but cross-day `R2_COVERAGE downtime 1436/1435 min` shows gaps are reported, not hidden |

## Top-3 improvements (for 15_IMPLEMENTATION_ROADMAP)

1. **bookTicker archiver** — `bid/ask` per cycle (KB/day) → real `spread median→P99`, enables `BASE/STRESSED` totals and correct `ask/bid+slip` fills.
2. **Venue-timed fills** — mount `ExecutionGateway(VenuePort=PaperVenue)` to get `decision→fill ms` and enable limit-order lifecycle without breaking `PaperBroker` comparability (shadow DUAL until cutover).
3. **Funding deep ETH/SOL** — paginated `fundingRate` backfill `startTime 1000/page` until `2019-09-10` parity, with 8h cadence + fingerprint validation.

## Status (27)

**Do NOT modify `PaperBroker`**. This is AUDIT + MODEL FOUNDATION. Deferred cutover: design/prepare integration only (`EXECUTION-REALISM-PAPER-INTEGRATION-RFC-01`). Changing now invalidates `R2` comparability.
