# 02 — SOURCE REGISTRY — EXECUTION-REALISM-AND-COST-AUTHORITY-01

Checkpoint: `EXECUTION-REALISM-AND-COST-AUTHORITY-01` · Generated: `2026-09-12T11:30:00Z` · Base: `0941082`

Machine artifact: `02_SOURCE_REGISTRY.json` (8 sources). All retrievals live except deep funding `2026-09-09T21:39Z`.

## Sources

| ID | Type | Provider | Retrieved | Claim |
|---|---|---|---|---|
| SRC-FEE-001 | OFFICIAL_EXCHANGE_DOC | binance | 2026-09-12T11:25Z | USD-M VIP0 maker 2bps / taker 5bps; BNB 10% → 1.8/4.5 (`binance.com/fee/futureFee`) |
| SRC-FEE-002 | OFFICIAL_EXCHANGE_DOC | binance | 2026-09-12T11:25Z | FAQ example regular 0.02%/0.05% |
| SRC-SPREAD-001 | OFFICIAL_EXCHANGE_DATA | binance | 2026-09-12T11:28Z | live bookTicker snapshot: BTC 0.013 bps, ETH 0.039 bps, SOL 0.98 bps (5× each) |
| SRC-FUND-001 | OFFICIAL_EXCHANGE_DATA | binance | 2026-09-12T11:28Z | live fundingRate per 8h: BTC 0.36 bps, ETH 0.50 bps, SOL 0.41 bps |
| SRC-FUND-DEEP-001 | OFFICIAL_EXCHANGE_DATA | binance | 2026-09-09T21:39Z | 7670 rows 2019-09-10→2026-09-09, 8h 100%, fp `8b0e79…`, sha `81936d1b` |
| SRC-PAPER-001 | SOURCE_CODE | internal | 2026-09-12T11:18Z | `paper/broker.py` fill model (slippage, fees, OHLC stop_first, no partial) |
| SRC-EXEC-001 | SOURCE_CODE | internal | 2026-09-12T11:18Z | `execution/cost_model.py` (commission 5bp + slippage 1bp default) |
| SRC-EXEC-002 | SOURCE_CODE | internal | 2026-09-12T11:18Z | `execution/intent+gateway+service` + `paper/paper_cycle:intent_cloid` idempotency |
| SRC-H6-001 | SOURCE_CODE | internal | 2026-09-12T11:18Z | `H6_SPEC_V2` 10 bps TOTAL RT + `EXCLUDED_WITH_LIMITATION` |

## Notes

- Official fee page `futureFee` requires JS; corroborated via Binance Square posts + blog `421499824684902239` (USDT & Coin-M taker 0.045%→0.0153% variant noted). Some mirrors show 0.04% taker — captured as UNKNOWN; canonical remains 5 bps taker (REGULAR tier).
- Spread snapshot is **point-in-time** only (2026-09-12 11:28Z low-vol window per `SHADOW` context `LOW_VOLATILITY`); do not extrapolate to 5-year history.
- Funding deep is BTC-only; ETH/SOL deep not yet admitted — hence H6 `EXCLUDED_WITH_LIMITATION` (honest).
