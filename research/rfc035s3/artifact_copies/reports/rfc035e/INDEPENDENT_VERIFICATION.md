# RFC-035E — independent verification

- status: **PASS**
- checks: 107/107
- mismatches: 0
- false success: 0

Re-derived from the raw bytes recorded in `research/rfc035e/raw_source_manifest.json`, re-parsing the Farside table and the Binance klines with this file's own code.

## Re-derived reference model (r1 + daily flow)

```json
{
  "source": {
    "regression_n": 194,
    "lag_flow_coefficient": 2.342561165094671e-05,
    "lag_flow_t": 2.0033135176913004,
    "lag_flow_p": 0.046557236280923404,
    "granger_F": 4.013265050165147,
    "granger_p": 0.04655723628091033,
    "persistence_ar1": 0.5723627841740533,
    "sessions": 195,
    "window": {
      "start": "2024-01-11",
      "end": "2024-10-11",
      "sessions_in_window": 197
    },
    "in_window_usable_rows": 196,
    "first_date": "2024-01-15",
    "last_date": "2024-10-11"
  },
  "oos": {
    "regression_n": 504,
    "lag_flow_coefficient": 8.719714874079696e-06,
    "lag_flow_t": 2.383541110357777,
    "lag_flow_p": 0.01751852535043962,
    "granger_F": 5.681268224774402,
    "granger_p": 0.017518525350352226,
    "persistence_ar1": 0.5145728170896767,
    "sessions": 505,
    "window": {
      "start": "2024-10-12",
      "end": "2026-10-07",
      "sessions_in_window": 506
    },
    "in_window_usable_rows": 506,
    "first_date": "2024-10-15",
    "last_date": "2026-10-07"
  }
}
```

## Mismatches

- none

## Notes

- tolerances: coefficient/statistic relative 1e-3, p-value absolute 1e-3, persistence absolute 5e-4
- sample semantics: sessions = in-window rows usable for a lag model, regression_n = rows entering the equations

## Limitations

- none
