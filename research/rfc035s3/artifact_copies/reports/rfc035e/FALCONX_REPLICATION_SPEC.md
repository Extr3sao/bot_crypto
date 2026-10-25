# RFC-035E — FALCONX_REPLICATION_SPEC (frozen)

spec_digest = `d362d6d75129d2337fb1fa4b3434dc8b1412f059816f7091f9e76dc48b8bb9cf`

Every choice below was frozen before any statistic was computed; the equivalent JSON drives the estimation script.

```json
{
  "spec_version": "FALCONX_REPLICATION_SPEC_V1",
  "rfc": "RFC-035E",
  "frozen_at_utc": "2026-10-07T23:55:00Z",
  "frozen_before_results": true,
  "statement": "Every choice below was fixed before any statistic was computed. No parameter, window, lag, transform or trimming rule may change between the source replication and the out-of-sample run.",
  "source_claim_under_test": {
    "source_id": "S-01",
    "title": "Spot ETF Flows & Bitcoin Price Trajectory (FalconX Research, 2024-10-11)",
    "reported": {
      "granger_F": 8.4767,
      "granger_p": 0.00406,
      "lagged_flow_coefficient_on_price": 0.027,
      "flow_persistence_coefficient": 0.533,
      "price_momentum_coefficient": 0.802,
      "correlation_flows_vs_price": 0.3,
      "impulse_response_peak": "about +1.2% at days 3-4"
    }
  },
  "data": {
    "flow_source": "RF-01 Farside Investors, all-data daily net flow table (US$m), 12 fund columns + printed Total",
    "price_source": "RF-02 Binance BTCUSDT 1d klines (UTC)",
    "join_key": "flow_date == UTC calendar date of the Binance daily kline",
    "calendar": "provider sessions only (weekends absent; holidays present with zero flow); returns are computed between consecutive rows of this calendar",
    "missing_data_policy": "drop rows where any variable in the estimated equation is undefined; no interpolation, no fill, no forward-fill",
    "timezone": "UTC throughout"
  },
  "pit": {
    "exact_publication_timestamps": "UNKNOWN",
    "conservative_availability_rule": "flow_date + 1 calendar day at 00:00:00Z",
    "aggressive_rule": "flow_date at 00:00:00Z (contrast only, never used for conclusions)",
    "invariant": "available_to_strategy_at <= decision_time"
  },
  "windows": {
    "SOURCE_REPLICATION": {
      "start": "2024-01-11",
      "end": "2024-10-11"
    },
    "EXTERNAL_EFFECT_OOS": {
      "start": "2024-10-12",
      "end": "last available session"
    },
    "temporal_partitions": "three equal consecutive thirds of the SOURCE_REPLICATION window by row count, labelled EARLY/MIDDLE/LATE"
  },
  "variables": {
    "return_1d": "r_t = ln(close_t / close_{t-1}) on consecutive provider sessions",
    "return_7d": "ln(close_t / close_{t-7}) over provider sessions (the source's weekly price change)",
    "flow_raw": "F_t = printed Total net flow in US$m",
    "flow_sum7": "S7_t = sum of F over the trailing 7 provider sessions",
    "flow_normalized_difference": "ND_t = (S7_t - S7_{t-7}) / (|S7_t| + |S7_{t-7}|); rows with zero denominator are dropped (the source names this transformation but does not print its formula)",
    "flow_zscore": "Z_t = F_t / stdev(F over trailing 20 sessions); declared as OUR scaling, used only for the economic-magnitude step",
    "flow_sign": "sign(F_t), used only in the falsification battery"
  },
  "models": {
    "primary": "bivariate VAR(1) in [price change, flow transform] with intercept, estimated by OLS on rows where both series are defined",
    "granger": "F-test that the lagged flow coefficients in the price equation are jointly zero (lag 1: one restriction); reverse F-test for return -> flow",
    "robustness_order": "VAR(2) reported alongside, same variables",
    "irf": "orthogonalised impulse response, Cholesky ordering [flow, price], 10 steps, percentile 95% interval from 1000 residual bootstrap resamples",
    "bootstrap_seed": 20261007,
    "significance_threshold": 0.05
  },
  "source_fidelity_notes": [
    "The source's Granger F/p and VAR coefficients are reported on 7-day aggregated variables and a normalized-difference flow transform; the exact construction is not published, so three declared transforms are computed and the one the source names (ND) is the reference.",
    "The source's sample is roughly 2024-01-11..2024-10-11 (10 months of daily data); our SOURCE_REPLICATION window is exactly that calendar range.",
    "Nothing in the source implies a tradable rule; this reproduction tests the existence of the statistical relation only."
  ],
  "falsification_battery_predeclared": [
    "add the same-day return to the price equation",
    "add the previous return (momentum) to the price equation",
    "add trailing 20-session realised volatility",
    "add day-of-week dummies",
    "winsorise flows at the 1st/99th percentiles",
    "exclude |flow| > 10,000 USD m",
    "exclude the first 20 sessions (launch-period effects)",
    "reverse direction (return -> flow) reported with the same detail as the forward direction"
  ],
  "forbidden": [
    "no entry/exit rule, threshold, holding period, stop or take profit",
    "no parameter search, no asset sweep, no lag selection by outcome",
    "no claim of profitability"
  ],
  "economic_magnitude_rule": "for a 1-standard-deviation flow shock and for a 500 USD m shock, report the predicted cumulative BTC move in bps over h = 1..3 sessions from the same VAR, and compare with the project cost floor of 23.791 bps; the comparison is a scale check, not a strategy result"
}
```
