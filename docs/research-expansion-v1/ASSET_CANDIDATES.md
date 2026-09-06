# RESEARCH-EXPANSION-V1 — Asset Candidates (§22)

POC01 universe stays BTC/ETH/SOL (frozen during the 7-day window). Candidates below are
`ASSET_CANDIDATE` records only. Metrics marked UNVERIFIED require a fresh-data quality
pass (same harness as FRESH-DATA-001-R1) before they can enter any future campaign —
none were downloaded in this checkpoint.

| Candidate | Exchange pair | Liquidity | Spread | Volatility character | Data quality (5m) | Correlation vs BTC | Diversity hypothesis | Preliminary decision |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| ASSET_CANDIDATE-01 | BNB/USDT:USDT | high | low | mid, event-driven spikes | good (Binance native) | mid | exchange-native regime, distinct from majors | ADOPT_P1 pending fresh validation |
| ASSET_CANDIDATE-02 | XRP/USDT:USDT | high | low | news/regulatory-driven bursts | good | mid-low | event-regime diversity | ADOPT_P2 |
| ASSET_CANDIDATE-03 | DOGE/USDT:USDT | high | low-mid | retail-momentum, fat tails | good | mid | momentum-regime contrast | EXPERIMENT (tail-risk review first) |
| ASSET_CANDIDATE-04 | AVAX/USDT:USDT | mid-high | mid | high-beta alt | good | high | beta within L1 cluster | DEFER (redundant vs ETH/SOL) |
| ASSET_CANDIDATE-05 | LINK/USDT:USDT | mid-high | mid | oracle-sector cycles | good | mid-high | sector-rotation signal | ADOPT_P2 |
| ASSET_CANDIDATE-06 | ADA/USDT:USDT | mid-high | low-mid | slow-trend, low volatility-of-vol | good | mid | low-regime contrast | DEFER |

Objective criteria scoring (liquidity/spread/volume/volatility/data-quality/availability/slippage/correlation/diversity/strategy-compatibility) will be computed from fresh 5m data in a future checkpoint — recorded here as UNVERIFIED by design. Do NOT add any of these to a running campaign.
