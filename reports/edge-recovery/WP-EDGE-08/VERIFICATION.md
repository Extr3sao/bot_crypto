# WP-EDGE-08 — independent verification

*Run at `2026-10-14T21:41:25Z` (`EDGE08_VERIFICATION_V1`). Result: **PASS** — 14/14 checks passed.*

| # | Check | Result |
| --- | --- | --- |
| A-1 | no corpus of this repository holds a bar of any of the six symbols, and every tracked mention of one is a catalogue, a fetch script, a test, documentation or this package | PASS |
| A-2 | every shard's SHA-256 recomputes, the corpus digest follows from those shards, and the registration pinned the same digest | PASS |
| A-3 | the complete bars per asset the report published recompute from the shards on all three clocks, and the decisive-window floor is the registered one | PASS |
| A-4 | `edge08_preregister.py --check` re-renders the committed registration from the code, and every registered parameter hash recomputes | PASS |
| B-1 | the parameter hash of every book under test recomputes to the registered value, the reading artefact names the same bytes, and no superseded hash is still under test | PASS |
| B-2 | the gross screen recomputes from its own DEV rows, every arm it stopped is absent from the cross-section reading, and each of those arms carries the registered verdict | PASS |
| B-3 | each arm's verdict follows from the checks the arm itself published, and no arm is admitted without the registered minimum sample | PASS |
| B-4 | no artefact of this package promotes anything or carries a size, a quantity or an order: promotion is NONE and order_sent is false everywhere | PASS |
| B-5 | the windows read are the registered windows on every artefact, and the cross-section read is the corpus the registration pinned | PASS |
| B-6 | the defect the screen exposed is published in both screen artefacts with its cause, its fix and the parameters it superseded | PASS |
| B-7 | the trades-per-day the verdicts read recompute from the decisive window's own rows and its own length | PASS |
| B-8 | each decisive cell's money is internally consistent: expectancy is net over trades, the interval's point is that expectancy, and concentration is published exactly when the net is positive | PASS |
| C-1 | the gate status lists every arm this package registers, its verdict agrees with the validation, and the table says what it is: a status, not a permission | PASS |
| C-2 | one published cell recomputes from the raw trade rows: the same trade count, the same net and the same cost per traded notional | PASS |

## What each check re-derived

### A-1 — PASS

no corpus of this repository holds a bar of any of the six symbols, and every tracked mention of one is a catalogue, a fetch script, a test, documentation or this package.

```json
{
  "allowed_kinds": [
    "catalogue",
    "fetch_or_list_script",
    "test",
    "documentation",
    "this_work_package"
  ],
  "method": "git grep over TRACKED files (an untracked scratch file cannot argue a symbol is clean, and a committed shard cannot hide), classified by path; plus a glob for a shard of the symbol in every corpus this repository already holds",
  "shards_outside_the_cross_section": {},
  "symbols": [
    "AAVEUSDT",
    "UNIUSDT",
    "KSMUSDT",
    "SNXUSDT",
    "CRVUSDT",
    "SUSHIUSDT"
  ],
  "violating_kinds": [],
  "violations": []
}
```

### A-2 — PASS

every shard's SHA-256 recomputes, the corpus digest follows from those shards, and the registration pinned the same digest.

```json
{
  "corpus_digest_in_manifest": "fb32470f5bc6329eee558dfdbc436685ad4de91a7a7374ea329499c1c258735b",
  "corpus_digest_in_registration": "fb32470f5bc6329eee558dfdbc436685ad4de91a7a7374ea329499c1c258735b",
  "corpus_digest_recomputed": "fb32470f5bc6329eee558dfdbc436685ad4de91a7a7374ea329499c1c258735b",
  "mismatched": {},
  "symbols": [
    "AAVEUSDT",
    "CRVUSDT",
    "KSMUSDT",
    "SNXUSDT",
    "SUSHIUSDT",
    "UNIUSDT"
  ]
}
```

### A-3 — PASS

the complete bars per asset the report published recompute from the shards on all three clocks, and the decisive-window floor is the registered one.

```json
{
  "decisive_window": {
    "1d": {
      "floor": 400,
      "floor_is_registered": true,
      "published": {
        "AAVE": 651,
        "CRV": 651,
        "KSM": 651,
        "SNX": 651,
        "SUSHI": 651,
        "UNI": 651
      },
      "recomputed": {
        "AAVE": 651,
        "CRV": 651,
        "KSM": 651,
        "SNX": 651,
        "SUSHI": 651,
        "UNI": 651
      }
    },
    "1h": {
      "floor": 8000,
      "floor_is_registered": true,
      "published": {
        "AAVE": 15633,
        "CRV": 15633,
        "KSM": 15633,
        "SNX": 15633,
        "SUSHI": 15633,
        "UNI": 15633
      },
      "recomputed": {
        "AAVE": 15633,
        "CRV": 15633,
        "KSM": 15633,
        "SNX": 15633,
        "SUSHI": 15633,
        "UNI": 15633
      }
    },
    "4h": {
      "floor": 1500,
      "floor_is_registered": true,
      "published": {
        "AAVE": 3909,
        "CRV": 3909,
        "KSM": 3909,
        "SNX": 3909,
        "SUSHI": 3909,
        "UNI": 3909
      },
      "recomputed": {
        "AAVE": 3909,
        "CRV": 3909,
        "KSM": 3909,
        "SNX": 3909,
        "SUSHI": 3909,
        "UNI": 3909
      }
    }
  },
  "mismatches": {}
}
```

### A-4 — PASS

`edge08_preregister.py --check` re-renders the committed registration from the code, and every registered parameter hash recomputes.

```json
{
  "exit_code": 0,
  "mismatched": {},
  "stderr": "",
  "stdout": "registration matches the code that obeys it"
}
```

### B-1 — PASS

the parameter hash of every book under test recomputes to the registered value, the reading artefact names the same bytes, and no superseded hash is still under test.

```json
{
  "books_without_registration": [],
  "mismatched_params_hashes": {},
  "registered_books": [
    "edge08_active_daybreak_1h",
    "edge08_active_multiday_range_1h",
    "edge08_active_stretch_revert_1h",
    "edge08_quality_breakout_daily",
    "edge08_quality_pullback_daily",
    "edge08_quality_reversion_daily"
  ],
  "superseded_hashes": [
    "7d2c5f5c2fba5e969197f3847feee48f72e37be3043817f6ecd42aef3dd8b750",
    "c44e61e2745b5d5b1f688084da702875078102b1b7e22aa2888e4220fa5d1d10"
  ],
  "superseded_still_under_test": [],
  "validation_artefact_mismatches": {}
}
```

### B-2 — PASS

the gross screen recomputes from its own DEV rows, every arm it stopped is absent from the cross-section reading, and each of those arms carries the registered verdict.

```json
{
  "arms": [
    {
      "arm": "edge08_quality_breakout_daily",
      "dev_gross_expectancy_usdt": 18.4381,
      "dev_trades": 52,
      "published": true,
      "recomputed": true
    },
    {
      "arm": "edge08_quality_pullback_daily",
      "dev_gross_expectancy_usdt": -1.8711,
      "dev_trades": 165,
      "published": false,
      "recomputed": false
    },
    {
      "arm": "edge08_quality_reversion_daily",
      "dev_gross_expectancy_usdt": null,
      "dev_trades": 0,
      "published": false,
      "recomputed": false
    },
    {
      "arm": "edge08_active_daybreak_1h",
      "dev_gross_expectancy_usdt": 1.1815,
      "dev_trades": 554,
      "published": true,
      "recomputed": true
    },
    {
      "arm": "edge08_active_multiday_range_1h",
      "dev_gross_expectancy_usdt": 2.3116,
      "dev_trades": 205,
      "published": true,
      "recomputed": true
    },
    {
      "arm": "edge08_active_stretch_revert_1h",
      "dev_gross_expectancy_usdt": -1.2496,
      "dev_trades": 132,
      "published": false,
      "recomputed": false
    }
  ],
  "mismatched": [],
  "stopped_arms": [
    "edge08_active_stretch_revert_1h",
    "edge08_quality_pullback_daily",
    "edge08_quality_reversion_daily"
  ],
  "stopped_but_read": []
}
```

### B-3 — PASS

each arm's verdict follows from the checks the arm itself published, and no arm is admitted without the registered minimum sample.

```json
{
  "mismatched": {},
  "unknown_verdicts": [],
  "verdicts": {
    "edge06_trend_fixed": "NOT_APPLICABLE",
    "edge07_active_thrust": "NOT_APPLICABLE",
    "edge08_active_daybreak_1h": "REJECT",
    "edge08_active_multiday_range_1h": "REJECT",
    "edge08_active_stretch_revert_1h": "REJECT_NO_GROSS_EDGE",
    "edge08_quality_breakout_daily": "REJECT",
    "edge08_quality_pullback_daily": "REJECT_NO_GROSS_EDGE",
    "edge08_quality_reversion_daily": "REJECT_NO_GROSS_EDGE",
    "edge_trend_01_4h": "NOT_APPLICABLE"
  }
}
```

### B-4 — PASS

no artefact of this package promotes anything or carries a size, a quantity or an order: promotion is NONE and order_sent is false everywhere.

```json
{
  "offenders": []
}
```

### B-5 — PASS

the windows read are the registered windows on every artefact, and the cross-section read is the corpus the registration pinned.

```json
{
  "digest_consistent": true,
  "mismatches": {}
}
```

### B-6 — PASS

the defect the screen exposed is published in both screen artefacts with its cause, its fix and the parameters it superseded.

```json
{
  "affected_arms": [
    "edge08_quality_pullback_daily",
    "edge08_quality_reversion_daily"
  ],
  "in_active": [
    "DEF-EDGE08-01"
  ],
  "in_quality": [
    "DEF-EDGE08-01"
  ]
}
```

### B-7 — PASS

the trades-per-day the verdicts read recompute from the decisive window's own rows and its own length.

```json
{
  "decisive_window_days": 651.3333,
  "mismatches": {}
}
```

### B-8 — PASS

each decisive cell's money is internally consistent: expectancy is net over trades, the interval's point is that expectancy, and concentration is published exactly when the net is positive.

```json
{
  "mismatches": {}
}
```

### C-1 — PASS

the gate status lists every arm this package registers, its verdict agrees with the validation, and the table says what it is: a status, not a permission.

```json
{
  "arms_in_gate_status": [
    "edge06_trend_fixed",
    "edge07_active_thrust",
    "edge08_active_daybreak_1h",
    "edge08_active_multiday_range_1h",
    "edge08_active_stretch_revert_1h",
    "edge08_quality_breakout_daily",
    "edge08_quality_pullback_daily",
    "edge08_quality_reversion_daily",
    "edge_trend_01_4h"
  ],
  "arms_in_validation": [
    "edge06_trend_fixed",
    "edge07_active_thrust",
    "edge08_active_daybreak_1h",
    "edge08_active_multiday_range_1h",
    "edge08_active_stretch_revert_1h",
    "edge08_quality_breakout_daily",
    "edge08_quality_pullback_daily",
    "edge08_quality_reversion_daily",
    "edge_trend_01_4h"
  ],
  "load": {
    "edge06_trend_fixed": "not read",
    "edge07_active_thrust": "not read",
    "edge08_active_daybreak_1h": "read",
    "edge08_active_multiday_range_1h": "read",
    "edge08_active_stretch_revert_1h": "not read",
    "edge08_quality_breakout_daily": "read",
    "edge08_quality_pullback_daily": "not read",
    "edge08_quality_reversion_daily": "not read",
    "edge_trend_01_4h": "not read"
  },
  "mismatched": {}
}
```

### C-2 — PASS

one published cell recomputes from the raw trade rows: the same trade count, the same net and the same cost per traded notional.

```json
{
  "arm": "edge07_active_thrust",
  "published_cost_bps": 23.7839,
  "published_net_usdt": -488.0181,
  "recomputed_cost_bps": 23.7839,
  "recomputed_net_usdt": -488.0181,
  "rows": 381
}
```

## Sabotage self-test

Baseline PASS; 14/14 sabotages detected; result **PASS**.

| Check sabotaged | Detected |
| --- | --- |
| A-1 | True |
| A-2 | True |
| A-3 | True |
| A-4 | True |
| B-1 | True |
| B-2 | True |
| B-3 | True |
| B-4 | True |
| B-5 | True |
| B-6 | True |
| B-7 | True |
| B-8 | True |
| C-1 | True |
| C-2 | True |
