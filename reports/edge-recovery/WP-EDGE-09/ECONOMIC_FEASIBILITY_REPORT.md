# WP-EDGE-09D — economic feasibility report

*`2026-10-15T05:16:16Z`. Decision: **NO_ECONOMIC_EDGE_FOUND**.

no measured structure in this capture covers the round trip; the decision is about this capture and this venue set, not about microstructure in general

## 1. The barrier against the best measured gross

| Market | Symbol | Round trip (bps) | Required 1.5x (bps) | Best gross (bps) | Net at best gross (bps) | Gap to break-even (bps) | Survives |
| --- | --- | ---: | ---: | ---: | ---: | ---: | :-: |
| perp | BTCUSDT | 23.1104 | 34.6656 | 1.582703 | -21.5277 | 21.5277 | False |
| perp | ETHUSDT | 23.1512 | 34.7268 | 1.582703 | -21.5685 | 21.5685 | False |
| perp | SOLUSDT | 24.0731 | 36.1097 | 1.582703 | -22.4904 | 22.4904 | False |
| spot | BTCUSDT | 23.0968 | 34.6452 | 1.582703 | -21.5141 | 21.5141 | False |
| spot | ETHUSDT | 23.1508 | 34.7262 | 1.582703 | -21.5681 | 21.5681 | False |
| spot | SOLUSDT | 24.0813 | 36.1219 | 1.582703 | -22.4986 | 22.4986 | False |

Mean fee component 32.5 bps of a mean barrier 23.4439 bps (1.3863 of the round trip).

## 2. Frequency

| Source | Horizon (s) | Long-only opp/day | Any direction opp/day | Meets target |
| --- | ---: | ---: | ---: | :-: |
| selector | 1 | 0.0 | 0.0 | False |
| selector | 5 | 0.0 | 0.0 | False |
| selector | 60 | 144.061 | 312.121 | True |
| tape bound | 1 | 0.0 | — | False |
| tape bound | 5 | 0.0 | — | False |
| tape bound | 60 | 48.018 | — | True |
| tape bound | 900 | 179.619 | — | True |
| tape bound | 3600 | 11.553 | — | True |

## 3. What would change the answer

- a taker fee low enough that fee + spread + impact falls under the measured gross, or a measured maker fill model that turns a passive product into a costed one
- a product with a different cost structure (the runtime's spot book is long-only)
- a structure whose gross move is measured at or above 34-36 bps (1.5x of 23-24 bps) rather than the 1.6 bps best measured here

## 4. What is not measured

- duplicates (the collector appends events; no trade-id de-duplication pass exists)
- stale_rate (no staleness threshold is registered for the forward capture)
- provider_failure_rate (reconnect counters exist in the capture, not a failure rate)
- turnover, exposure, max_drawdown, profit_factor, expectancy (no PnL backtest was run)
- pnl_usd (the cost gate stopped every arm before a simulator was invoked)
- perp aggressor flow (the environment delivered zero perp aggTrade messages)
- maker fills on every venue (no measured fill model exists in this project)
- liquidation prints (no public endpoint answered)
