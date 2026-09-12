# 04 — EXCHANGE FEE AUTHORITY — EXECUTION-REALISM-AND-COST-AUTHORITY-01

Machine: `04_EXCHANGE_FEE_AUTHORITY.json` · Retrieved: `2026-09-12T11:25Z` · Provider: **binance / usdm**

## Configured exchange authority

| Field | Value | Evidence |
|---|---|---|
| `config/exchange.yaml:exchange.id` | `binance` | checked in `0941082` worktree |
| `default_type` | `spot` (config legacy; futures via `binanceusdm` CCXT market) | `config/exchange.yaml` |
| `config/runtime.yaml:runtime.mode` | `paper` | `runtime.mode=paper, live_trading_enabled=false` |
| Actual market data provider (runtime) | `binanceusdm` (public REST `/fapi/v1/*` via CCXT) | `R2_LAUNCH_RECORD, R2_CAMPAIGN_STATE, poc02_observation: PROVIDER=binanceusdm (public, no creds)` |
| Historical price authority | Binance USD-M 1h klines `BTC/ETH/SOLUSDT_1h_v2.jsonl` (58680/58680/52505) | `PRICE_1H_AUTHORITY_V2_MANIFEST.json` |
| Historical funding authority | `binanceusdm public /fapi/v1/fundingRate` (BTC deep `7670 rows` 2019-09-10→2026-09-09) | `D1_DATA_FINGERPRINT.json` |

Market type for fees relevant to **perp futures**: `usdm` is authoritative; `spot` config is legacy but futures fee schedule applies to any `H6/poc02` perp execution. No spot fee may be mixed into perp accounting.

## Official fee schedule (USD-M / USDT-margined futures)

| Tier | Maker | Taker | Round-trip taker+taker | Source | Effective |
|---|---|---|---|---|---|
| **VIP0 regular (no BNB)** | **2.0 bps (0.02%)** | **5.0 bps (0.05%)** | **10 bps** | `binance.com/fee/futureFee` + FAQ `360033544231` + Square post `24640040632442` | 2024+ live 2026-09-12 |
| VIP0 with 10% BNB discount | 1.8 bps | 4.5 bps | 9 bps | same (10% discount rule) | same |
| Variant report: some mirrors | 2.0 / 4.0 bps RT 8 bps | captured as **UNKNOWN** — not canonical until VIP/market-type qualified | `binance.com/en/square/post/21585262587618` (0.04% taker) | needs qualification |

Maker-maker RT = 4.0 bps / 3.6 bps (BNB). Taker-taker is the conservative default for marketable paper fills.

Fees are **on notional**, per side, in fee currency `USDT` (settlement coin). VIP tier lowers both; BNB 10% discount applies only when explicitly opted in. No hidden funding/commingling.

## Comparison: H6 discovery vs paper vs official

| Context | Total RT assumed | Matches VIP0 taker? | Sensitivity |
|---|---|---|---|
| `H6_SPEC_V2` discovery | **10 bps TOTAL RT** (single number, not 5+5 decomposed) | **Exact match** taker+taker without BNB | `0/10/20/40 bps` diagnostic, `gross_reporting_required` |
| PaperBroker default | 10 bps fees (`5+5`) + 2 bps slippage = **12 bps** | Fees match; slippage extra | `planned_net_rr()` does `entry_fee+exit_fee+entry_slip+exit_slip` correctly |
| Official VIP0 taker | `5+5 = 10 bps` | — | VIP1-9 reduces further |

**Classification:** `H6_DISCOVERY_COST_ASSUMPTION = APPROXIMATELY_REALISTIC` (conservative for fees; slightly optimistic once spread+slippage+funding+impact added — see 09/10).

## Deployment note

`config/exchange.yaml` `defaultType: spot` is legacy; any future PAPER futures execution must pin `market=usdm` explicitly at the `ExecutionCostAuthority`/`ExchangeExecutionProfile` level (portability §37) — do not touch `config/exchange.yaml` in this checkpoint.
