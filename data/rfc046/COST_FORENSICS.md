# RFC-046 COST FORENSICS — WHY THE THREE CANDIDATES DIED

generated_at_utc = 2026-10-08T13:15:28Z (computed, not authored)
head_at_run = 0f09bda8f06fdefa16dbe2acf0da1b9fd87a125e
campaign_status_unchanged = **DISCOVERY_CAMPAIGN_FAILED**
false_success = 0

This artefact changes nothing: it decomposes a recorded rejection. It admits no candidate and generates no new hypothesis (RFC-046 stop rule).

## The decomposition

`net = gross - 23.7906 bps` per round trip in the admission scenario `BINANCE_SPOT_STANDARD_TAKER`, so gross expectancy is net expectancy plus the cost floor. Because the floor is a constant added to every trade, the sign of gross is the sign of the mechanism's own edge and is independent of execution.

| candidate | N | gross bps | net bps | break-even cost bps | hit rate | OOS gross bps | verdict |
| --- | --- | --- | --- | --- | --- | --- | --- |
| CAND-046-001 | 38 | 4.530596 | -19.260004 | 4.530596 | 0.526316 | -74.590884 | **COST_DISQUALIFIED** |
| CAND-046-002 | 75 | -25.45802 | -49.24862 | -25.45802 | 0.48 | -8.477294 | **NO_GROSS_EDGE** |
| CAND-046-003 | 0 | n/a | n/a | n/a | n/a | n/a | **ZERO_SAMPLE** |

## The documented cost landscape (frozen model, not retuned here)

| scenario | product | round trip bps |
| --- | --- | --- |
| BINANCE_USDM_PERP_MAKER | USDⓈ-M Perpetual | 9.25 |
| BINANCE_USDM_PERP_TAKER | USDⓈ-M Perpetual | 13.7906 |
| MEXC_SPOT_TAKER | Spot | 17.7906 |
| BINANCE_SPOT_BNB_TAKER | Spot | 18.7906 |
| BINANCE_SPOT_STANDARD_TAKER | Spot | 23.7906 |
| BYBIT_SPOT_TAKER | Spot | 23.7906 |
| OKX_SPOT_TAKER | Spot | 23.7906 |
| BINANCE_SPOT_BNB_MAKER | Spot | 31.25 |
| BINANCE_SPOT_STANDARD_MAKER | Spot | 41.25 |
| KRAKENPRO_SPOT_TAKER | Spot | 83.7906 |

Admission scenario: `BINANCE_SPOT_STANDARD_TAKER` at **23.7906 bps**; stressed at 1.5x = **35.6859 bps**. Cheapest documented scenario of any product: **9.25 bps** (`BINANCE_USDM_PERP_MAKER`); cheapest *spot* scenario: **17.7906 bps** (`MEXC_SPOT_TAKER`).

## Per candidate

### CAND-046-001 — COST_DISQUALIFIED

- strategy: `funding_capitulation` on BTCUSDT (forced_flows); spec hash `e5e58176e4c8fb01`
- gross expectancy: **4.530596 bps**; net expectancy -19.260004 bps; stressed net -31.155304 bps
- break-even round trip: **4.530596 bps** — 0.190436x the admission cost
- out-of-sample: gross -74.590884 bps over 10 trades
- partitions: {"development": {"gross_bps": 68.294628, "n": 19, "net_bps": 44.504028}, "final_oos": {"gross_bps": -74.590884, "n": 10, "net_bps": -98.381484}, "validation": {"gross_bps": -57.857462, "n": 8, "net_bps": -81.648062}}
- gross positive in every partition: False; no gross edge in: final_oos, validation
- recorded run reproduced: True (comparable: True, diff 0.0 bps)

gross expectancy is 4.5306 bps per trade, below even the cheapest documented scenario in the frozen cost model (9.25 bps, BINANCE_USDM_PERP_MAKER). No cost-side change documented in this repository rescues it. The aggregate is not a stable edge: gross is not positive in validation (-57.857462 bps), final_oos (-74.590884 bps), so the positive figure is confined to the earlier window and the mechanism has no gross edge out of sample either. Cost is the second problem, not the first.

### CAND-046-002 — NO_GROSS_EDGE

- strategy: `settlement_dip` on ETHUSDT (market_microstructure); spec hash `3336b8f343d899af`
- gross expectancy: **-25.45802 bps**; net expectancy -49.24862 bps; stressed net -61.14392 bps
- break-even round trip: **-25.45802 bps** — -1.070087x the admission cost
- out-of-sample: gross -8.477294 bps over 23 trades
- partitions: {"development": {"gross_bps": -7.773743, "n": 34, "net_bps": -31.564343}, "final_oos": {"gross_bps": -8.477294, "n": 23, "net_bps": -32.267894}, "validation": {"gross_bps": -80.559249, "n": 18, "net_bps": -104.349849}}
- gross positive in every partition: False; no gross edge in: development, final_oos, validation
- recorded run reproduced: True (comparable: True, diff 0.0 bps)

gross expectancy is -25.4580 bps per trade, i.e. the mechanism loses money before any cost is charged. Cost reduction cannot rescue it; this is an economic rejection, not an execution-cost rejection.

### CAND-046-003 — ZERO_SAMPLE

- strategy: `weekend_rebound` on BTCUSDT (institutional_constraint); spec hash `8f99b0366301a304`
- gross expectancy: **n/a (zero sample)**; net expectancy n/a (zero sample); stressed net n/a (zero sample)
- break-even round trip: **n/a (zero sample)**
- out-of-sample: gross n/a (zero sample) over 0 trades
- partitions: {"development": {"gross_bps": null, "n": 0, "net_bps": null}, "final_oos": {"gross_bps": null, "n": 0, "net_bps": null}, "validation": {"gross_bps": null, "n": 0, "net_bps": null}}
- gross positive in every partition: n/a (unmeasured: no trades)
- recorded run reproduced: n/a — the recorded run had no value to compare (not comparable)

no trade was generated, so no edge was measured in either direction: the entry filter never fired on the frozen data. Nothing about cost or mechanism follows from this.

## What this does and does not license

- It does **not** change the campaign verdict: `DISCOVERY_CAMPAIGN_FAILED` stands.
- It does **not** generate replacement hypotheses.
- It **does** establish, from the recorded evidence, which of the two failure causes applies to each candidate — the input any future owner decision needs.

```text
G_BUSINESS_REENTRY != PASS
LIVE_TRADING = DISABLED
TRADES_AUTHORIZED = 0
PROFITABILITY_VERIFIED = FALSE
FALSE_SUCCESS = 0
```
