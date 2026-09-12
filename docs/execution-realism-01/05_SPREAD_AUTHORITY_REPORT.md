# 05 — SPREAD AUTHORITY REPORT — EXECUTION-REALISM-AND-COST-AUTHORITY-01

Machine: `05_SPREAD_AUTHORITY_REPORT.json` · Snapshot: `2026-09-12T11:28:00Z` · Provider: `binance usdm fapi/v1/ticker/bookTicker` (public)

## 13 — Historical spread authority (§13)

Search: repo has **no persisted L1/L2 bookTicker history** (no `bid/ask` archive; only OHLCV + takerBuyVolume + funding). `docs/external-audit-01/data-admission-01` covers OI + trade-flow admission only. `strategy_runtime_authority_map.md` lists `bidPrice/askPrice` as a *survey-only* sampling probe, not as a ledger.

**Conclusion: `HISTORICAL_SPREAD_AUTHORITY = UNAVAILABLE` (explicit).** No historical spread distribution can be attributed to a past performance.

## Observational spread sample (§13-§14 — point-in-time only, public unauthenticated, no orders placed)

Public endpoint `fapi/v1/ticker/bookTicker?symbol={BTC,ETH,SOL}USDT`, 5 consecutive polls `2026-09-12T11:28Z` (low-volatility window per shadow context `LOW_VOLATILITY`, strategy health `INSUFFICIENT_EVIDENCE`).

| Asset | bid | ask | mid | abs spread | spread_bps | samples | variance |
|---|---|---|---|---|---|---|---|
| BTCUSDT | 77333.2 | 77333.3 | 77333.25 | 0.10 | **0.0129 bps** | 5 | zero (stable) |
| ETHUSDT | 2535.49 | 2535.50 | 2535.495 | 0.01 | **0.039 bps** | 5 | zero |
| SOLUSDT | 102.07 | 102.08 | 102.075 | 0.01 | **0.98 bps** | 5 | zero |

Scope label: `OBSERVATIONAL_SAMPLE_2026-09-12T11:28Z_LOW_VOL_5X_PER_ASSET`; NOT a multi-year or stress estimate.

## 14 — Metrics (this sample only)

| Metric | BTC | ETH | SOL | Cross-asset |
|---|---|---|---|---|
| median | 0.0129 | 0.039 | 0.98 | 0.039 |
| P75/P90/P95/P99 | same (no variance in 5× window) | same | same | same |
| absolute | 0.10 USDT | 0.01 USDT | 0.01 USDT | — |
| by time-of-day | insufficient (one window) | — | — | — |
| by volatility | `LOW_VOL` only (shadow regime) | — | — | — |

**Do NOT extrapolate** this ~0.01-0.98 bps sample to high-vol or stressed regimes. A future `EXECUTION-DATA-ADMISSION` with `bookTicker` archiving is needed for `median→P99`.

## Half-spread cost (what PaperBroker ignores)

Effective spread cost for a round-trip that crosses the spread twice (marketable paper fill modeled at `ask` in / `bid` out): half-spread per leg ≈ `spread_bps/2`? Actually for a signal at `mid`, realistic fill adds `+half` on entry (ask) and subtracts `half` on exit (bid): round-trip = `spread_bps` (full width) + slippage + fees. For this sample:

| Asset | RT spread cost = spread_bps | Feasible total today (fee 10 + spread) | With slippage 2 |
|---|---|---|---|
| BTC | 0.013 bps | **10.01 bps** | 12.01 |
| ETH | 0.039 bps | **10.04 bps** | 12.04 |
| SOL | 0.98 bps | **10.98 bps** | 12.98 |

SOL is an order of magnitude wider — small-cap friction dominates.

## UNKNOWN policy

Historical spread remains `UNKNOWN` for any statement like *"spread is 3 bps"*. Say: *"historical real spread is UNKNOWN; observational 2026-09-12 low-vol snapshot shows BTC 0.013 / ETH 0.039 / SOL 0.98 bps for that 5-poll window"*.

## Recommendation (for 11_EXECUTION_DATA_GAPS)

- **ADOPT_P1**: `bookTicker` lightweight archiver (bid/ask per cycle; storage ~KB/day) to build real `median→P99` before PAPER profitability certification.
- Do NOT backfill 100 GB aggTrades for spread; bookTicker is sufficient and cheaper (see 11).
