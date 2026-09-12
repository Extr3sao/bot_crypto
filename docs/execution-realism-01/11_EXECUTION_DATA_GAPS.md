# 11 — EXECUTION DATA GAPS — EXECUTION-REALISM-AND-COST-AUTHORITY-01

Machine: `11_EXECUTION_DATA_GAPS.json` · §35-§36 (Requirement gap + Value-of-info)

## What additional data for high-fidelity modeling?

| Dataset | For | Status (§35) | Evidence today | Improvement if added | Recommendation (§36) |
|---|---|---|---|---|---|
| **L1 `bookTicker` bid/ask** | spread `median→P99`, correct `ask/bid+slip` fills, STRESSED/SEVERE | **NOT_AVAILABLE** (held only as 5× snapshot 2026-09-12) | live 0.013/0.039/0.98 bps sample low-vol | `median→P99` spread; `BASE/STRESSED` totals; SIM-quality fills | **ADOPT_P1** — archiver `bid/ask` per cycle (KB/day, CCXT public, no creds). Cost ~0; value HIGH. |
| **L2 depth (top 20)** | partial fills, market impact, size-dependent slippage | **NOT_AVAILABLE** | no depth cached | impact `SMALL/MEDIUM/LARGE` vs depth; real partials | **DEFER** (paper `20-500 USDT` impact ~0; need after spread baseline exists) |
| **aggTrades / trade intensity** | adverse move `50ms-5s`, effective spread proxy, decision→fill movement | **PARTIALLY_AVAILABLE** — admission deep sample exists (`TRADE_FLOW_DATASET_MANIFEST`, `OI_CADENCE_RECONCILIATION`) but not linked to fills; full ~100 GB backfill | sample tick stream admitted per `admission-01` | P50/P90 adverse curves; latency realism | **EXPERIMENT** — extend admitted sample for 250ms-5s adverse (cost-review for full 100 GB). |
| **mark price** | funding valuation (entry/exit mark vs last) | **PARTIALLY_AVAILABLE** (premiumIndex live includes `markPrice`) | live `premiumIndex` probe returns `markPrice` | accurate `entry_mark/exit_mark` for perp | **EXPERIMENT** — archive `premiumIndex` alongside bookTicker |
| **funding history ETH/SOL** | H6 1h funding gate (straddle) + promotion materiality | **PARTIALLY_AVAILABLE** (BTC 7670 deep; ETH/SOL 90 rows `INSUFFICIENT_DATA`) | BTC `8b0e79` sha, 8h 100% | parity for 3-asset H6 gate | **ADOPT_P0** — paginated `/fapi/v1/fundingRate?startTime=2019-09-10 limit=1000` until coverage gap closed, with monotonic+8h validation + fingerprint |
| **OHLCV authority** | price fills authority | **AVAILABLE** — `BTC/ETH/SOL_1h_v2 58680/58680/52505` + 5m cadence 288/d | frozen manifests | price integrity | none (exists) |
| **L1 `best bid/ask` history** | alias for bookTicker | **NOT_AVAILABLE** | same as L1 above | same | ADOPT_P1 |
| **Quote staleness timestamps** | stale-quote execution guard | **PARTIALLY_AVAILABLE** (FeedDeadManGuard exists, not exercised) | guard threshold wired but latency `NOT_MEASURED` | veto stale fills | wed to bookTicker adoption |

## 36 — Value of information per missing set

| Dataset | Decision value | Impl cost | Storage | Download | Exec-model improvement | Rec |
|---|---|---|---|---|---|---|
| bookTicker archiver | HIGH (unlocks spread+fills) | LOW (≤1 file: fetcher + store column) | LOW (bytes × cycles × 3 assets; KB/day) | LOW (1 REST call/cycle) | MEDIUM-HIGH (turns UNKNOWN spread→P99) | ADOPT_P1 |
| funding deep ETH/SOL | HIGH (unlocks H6 gate for 3 assets) | LOW (loop `startTime` 1000/page until coverage) | LOW (8h cadence ≈ 8k rows/asset total) | LOW (8 calls/asset for 6yrs) | MEDIUM | ADOPT_P0 |
| aggTrades deep (100 GB) | MEDIUM (adverse+impact) | HIGH (storage + pipeline) | HIGH (~100 GB for 3 assets 5yrs) | HIGH (months at API limits, needs `COST_REVIEW_REQUIRED`) | MEDIUM (but only after spread) | EXPERIMENT (sample first) / REJECT full backfill |
| L2 depth | LOW for current size | HIGH | MEDIUM | MEDIUM | LOW (paper size tiny) | DEFER |
| mark premiumIndex | LOW-MEDIUM | LOW | LOW | LOW | LOW | EXPERIMENT |

No expensive data is collected without proven worth. **Cheapest unlock first:** funding deep (8 calls) → bookTicker archiver (1 call/cycle) → sampled aggTrades → depth last.
