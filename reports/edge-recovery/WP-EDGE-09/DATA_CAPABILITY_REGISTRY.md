# WP-EDGE-09A/B — data capability registry

*`2026-10-15T05:16:16Z`. Derived from the audit and the source viability artifact; nothing here is re-measured. A field the package did not measure is null.*

| Dataset | Venue | Market | Resolution | First second (UTC) | Last second (UTC) | Quotes | Trades | Gaps (s) | Truncated | PIT | Verdict |
| --- | --- | --- | --- | --- | --- | ---: | ---: | ---: | ---: | --- | --- |
| `EDGE09-PANEL-paper-lab-continuous-02-perp-BTCUSDT` | Binance | perp | 1 s grid, 10 depth levels kept | 2026-09-29T22:59:20Z | 2026-09-30T03:08:37Z | 5070497 | 0 | 359 | 3 | yes — every row carries event/available/receive clocks and the panel uses receive | **FORWARD_ONLY** |
| `EDGE09-PANEL-paper-lab-continuous-02-perp-ETHUSDT` | Binance | perp | 1 s grid, 10 depth levels kept | 2026-09-29T22:59:20Z | 2026-09-30T03:08:37Z | 3815872 | 0 | 354 | 3 | yes — every row carries event/available/receive clocks and the panel uses receive | **FORWARD_ONLY** |
| `EDGE09-PANEL-paper-lab-continuous-02-spot-BTCUSDT` | Binance | spot | 1 s grid, 10 depth levels kept | 2026-09-29T22:59:20Z | 2026-09-30T03:08:37Z | 1241954 | 91391 | 410 | 2 | yes — every row carries event/available/receive clocks and the panel uses receive | **FORWARD_ONLY** |
| `EDGE09-PANEL-paper-lab-continuous-02-spot-ETHUSDT` | Binance | spot | 1 s grid, 10 depth levels kept | 2026-09-29T22:59:20Z | 2026-09-30T03:08:37Z | 692423 | 72269 | 714 | 2 | yes — every row carries event/available/receive clocks and the panel uses receive | **FORWARD_ONLY** |
| `EDGE09-PANEL-paper-strategy-lifecycle-shadow-02-perp-BTCUSDT` | Binance | perp | 1 s grid, 10 depth levels kept | 2026-10-01T17:57:10Z | 2026-10-01T19:57:08Z | 1791213 | 0 | 1295 | 0 | yes — every row carries event/available/receive clocks and the panel uses receive | **FORWARD_ONLY** |
| `EDGE09-PANEL-paper-strategy-lifecycle-shadow-02-perp-ETHUSDT` | Binance | perp | 1 s grid, 10 depth levels kept | 2026-10-01T17:57:11Z | 2026-10-01T19:57:08Z | 1603790 | 0 | 1280 | 0 | yes — every row carries event/available/receive clocks and the panel uses receive | **FORWARD_ONLY** |
| `EDGE09-PANEL-paper-strategy-lifecycle-shadow-02-perp-SOLUSDT` | Binance | perp | 1 s grid, 10 depth levels kept | 2026-10-01T17:57:11Z | 2026-10-01T19:57:08Z | 732665 | 0 | 1362 | 0 | yes — every row carries event/available/receive clocks and the panel uses receive | **FORWARD_ONLY** |
| `EDGE09-PANEL-paper-strategy-lifecycle-shadow-02-spot-BTCUSDT` | Binance | spot | 1 s grid, 10 depth levels kept | 2026-10-01T17:57:10Z | 2026-10-01T19:57:08Z | 862488 | 68973 | 370 | 0 | yes — every row carries event/available/receive clocks and the panel uses receive | **FORWARD_ONLY** |
| `EDGE09-PANEL-paper-strategy-lifecycle-shadow-02-spot-ETHUSDT` | Binance | spot | 1 s grid, 10 depth levels kept | 2026-10-01T17:57:11Z | 2026-10-01T19:57:08Z | 447514 | 43239 | 426 | 0 | yes — every row carries event/available/receive clocks and the panel uses receive | **FORWARD_ONLY** |
| `EDGE09-PANEL-paper-strategy-lifecycle-shadow-02-spot-SOLUSDT` | Binance | spot | 1 s grid, 10 depth levels kept | 2026-10-01T17:57:11Z | 2026-10-01T19:57:08Z | 368470 | 12074 | 539 | 0 | yes — every row carries event/available/receive clocks and the panel uses receive | **FORWARD_ONLY** |

## Declared as not measured

- duplicates (the collector appends events; no trade-id de-duplication pass exists)
- stale_rate (no staleness threshold is registered for the forward capture)
- provider_failure_rate (reconnect counters exist in the capture, not a failure rate)
- turnover, exposure, max_drawdown, profit_factor, expectancy (no PnL backtest was run)
- pnl_usd (the cost gate stopped every arm before a simulator was invoked)
