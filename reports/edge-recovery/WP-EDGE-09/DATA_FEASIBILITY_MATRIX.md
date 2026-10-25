# WP-EDGE-09B — data feasibility matrix

*`2026-10-15T05:16:16Z`. A family is feasible only if the data its minimum specification names exists here with the availability semantics it needs.*

| Family | Minimum data | Available | Status | Why |
| --- | --- | :-: | --- | --- |
| spreads and liquidity (book imbalance) | forward quote/depth at the touch, point-in-time | True | **MEASURED_AND_REJECTED** | the capture exists and was measured; the best long-only gross is far below the barrier and the tape offers no clearing move at a 1 or 5 second horizon |
| regimes | OHLCV point-in-time plus volatility and volume | True | **DEFERRED** | klines are available but a bar close is not a decision instant this runtime would trade on; the package does not open a new window for it, and no arm here survived the cost gate to justify one |
| cross-asset (lead/lag) | synchronised bars, one venue and one clock | True | **DEFERRED** | the captured clock is one venue, but three symbols over a few hours cannot separate a lead/lag effect from a shared move; the sample is declared too small |
| funding and open interest | funding and OI history with the real publication time | True | **DEFERRED** | funding history is available and OI is retained for about 30 days; the forward capture held only 14 usable quadrant states, below the registered floor of 500, so the family is deferred rather than rejected on a sample too small to judge |
| events | an event feed with publication timestamps | True | **REJECTED_NO_DATA** | no public liquidation or event feed answered in this environment (probe 404), and a retrospective timestamp cannot be used as a publication instant |

Capture held: 21 roots, 10.14 h total, longest 14973.49 s.

## Probes

| Probe | URL | Status | Reachable |
| --- | --- | ---: | :-: |
| P-01 | `https://fapi.binance.com/fapi/v1/fundingRate?symbol=BTCUSDT&limit=1000` | 200 | True |
| P-02 | `https://fapi.binance.com/futures/data/openInterestHist?symbol=BTCUSDT&period=5m&limit=500` | 200 | True |
| P-03 | `https://fapi.binance.com/fapi/v1/allForceOrders?symbol=BTCUSDT&limit=100` | 404 | False |
| P-04 | `https://api.binance.com/api/v3/depth?symbol=BTCUSDT&limit=5` | 200 | True |
| P-05 | `https://data.binance.vision/data/spot/monthly/klines/BTCUSDT/1m/BTCUSDT-1m-2026-08.zip` | 200 | True |
