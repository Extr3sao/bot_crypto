# WP-EDGE-06 Track B — the registered families, measured

*Run at `2026-10-14T08:10:30Z` (`EDGE06-PROGRAM-20261014T081030Z`). Same corpus, same windows, same cost scenarios, same risk policy, same metric definitions and the same admission gate as the campaign that measured the frozen books — by calling its functions.*

## 1. The verdicts

| Family | Answers | Verdict | Gate said | OOS trades | OOS net | OOS gross DEV | Largest share | Without it |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `edge06_xs_momentum` | H-XS | **INSUFFICIENT_EVIDENCE** | `INSUFFICIENT_EVIDENCE` | 45 | 170.19 | 604.48 | 0.6372 | 61.74 |
| `edge06_fade_extension` | H-FADE | **REJECT_NO_GROSS_EDGE** | `REJECT` | 50 | -391.34 | -150.82 | None | -454.99 |
| `edge06_trend_fixed` | H-TARGET | **ADMIT** | `ADMIT` | 113 | 230.02 | 1,746.07 | 0.2219 | 178.98 |

### Why, in the gate's own words

- **`edge06_xs_momentum`** — INSUFFICIENT_EVIDENCE (powered (oos n=45 >= 30))
  - the largest single trade is 0.64 of the oos net
  - disclosure: the trend OOS window has already been read by the frozen 4h ruleset and by the robustness analysis of WP-EDGE-02, so clearing the gate here is 'not yet rejected' and never validation
- **`edge06_fade_extension`** — REJECT_NO_GROSS_EDGE (powered (oos n=50 >= 30))
  - oos net -391.34 USDT <= 0 after costs
  - oos expectancy -7.8269 USDT/trade <= 0
  - oos has 0 profitable regime(s), fewer than the required 1
  - oos net turns negative under 2x fees (-438.04 USDT): no cost margin
  - the DEV gross is -150.82 USDT: the setup loses money before any fee, which no cost change can repair
  - disclosure: the trend OOS window has already been read by the frozen 4h ruleset and by the robustness analysis of WP-EDGE-02, so clearing the gate here is 'not yet rejected' and never validation
- **`edge06_trend_fixed`** — ADMIT (powered (oos n=113 >= 30))
  - oos net positive after costs, sample powered, no single trade carries it
  - clears the frozen gate, is not carried by one trade, and survives removing its largest winner — still NOT validated: this OOS window was read before
  - disclosure: the trend OOS window has already been read by the frozen 4h ruleset and by the robustness analysis of WP-EDGE-02, so clearing the gate here is 'not yet rejected' and never validation

## 2. Every window, every cost scenario

| Family | Window | Scenario | Trades | Gross | Fees | Price costs | Net | Expectancy | PF | DD % | Cost bps | Largest share |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `edge06_xs_momentum` | DEV | 2X_FEES | 175 | 601.06 | 288.38 | 27.33 | **285.35** | 1.63 | 1.14 | 3.58 | 43.97 | 0.6752 |
| `edge06_xs_momentum` | DEV | ADVERSE | 175 | 572.34 | 287.29 | 67.31 | **217.74** | 1.24 | 1.10 | 3.94 | 49.55 | 0.8789 |
| `edge06_xs_momentum` | DEV | BASE | 175 | 604.48 | 144.63 | 27.41 | **432.44** | 2.47 | 1.22 | 3.16 | 23.89 | 0.4498 |
| `edge06_xs_momentum` | OOS | 2X_FEES | 45 | 222.83 | 88.44 | 8.38 | **126.01** | 2.80 | 1.23 | 2.03 | 44.00 | 0.852 |
| `edge06_xs_momentum` | OOS | ADVERSE | 45 | 222.16 | 88.37 | 20.71 | **113.08** | 2.51 | 1.20 | 2.06 | 49.60 | 0.9416 |
| `edge06_xs_momentum` | OOS | BASE | 45 | 222.80 | 44.22 | 8.38 | **170.19** | 3.78 | 1.33 | 1.91 | 23.91 | 0.6372 |
| `edge06_xs_momentum` | VAL | 2X_FEES | 59 | -11.58 | 112.67 | 10.68 | **-134.93** | -2.29 | 0.79 | 3.22 | 43.77 | None |
| `edge06_xs_momentum` | VAL | ADVERSE | 59 | -11.56 | 112.52 | 26.36 | **-150.44** | -2.55 | 0.77 | 3.32 | 49.34 | None |
| `edge06_xs_momentum` | VAL | BASE | 59 | -11.37 | 56.37 | 10.68 | **-78.43** | -1.33 | 0.87 | 2.89 | 23.78 | None |
| `edge06_fade_extension` | DEV | 2X_FEES | 79 | -232.37 | 146.12 | 13.85 | **-392.34** | -4.97 | 0.68 | 5.08 | 43.64 | None |
| `edge06_fade_extension` | DEV | ADVERSE | 79 | -231.39 | 145.96 | 34.20 | **-411.55** | -5.21 | 0.67 | 5.17 | 49.19 | None |
| `edge06_fade_extension` | DEV | BASE | 187 | -150.82 | 159.81 | 30.29 | **-340.92** | -1.82 | 0.89 | 5.37 | 23.76 | None |
| `edge06_fade_extension` | OOS | 2X_FEES | 50 | -333.90 | 95.13 | 9.01 | **-438.04** | -8.76 | 0.46 | 5.46 | 43.48 | None |
| `edge06_fade_extension` | OOS | ADVERSE | 50 | -332.40 | 95.01 | 22.26 | **-449.67** | -8.99 | 0.46 | 5.53 | 49.01 | None |
| `edge06_fade_extension` | OOS | BASE | 50 | -334.73 | 47.59 | 9.02 | **-391.34** | -7.83 | 0.50 | 5.17 | 23.62 | None |
| `edge06_fade_extension` | VAL | 2X_FEES | 99 | 580.94 | 190.29 | 18.03 | **372.62** | 3.76 | 1.31 | 2.96 | 44.05 | 0.3678 |
| `edge06_fade_extension` | VAL | ADVERSE | 99 | 579.05 | 190.05 | 44.53 | **344.47** | 3.48 | 1.28 | 2.99 | 49.65 | 0.3949 |
| `edge06_fade_extension` | VAL | BASE | 99 | 582.95 | 95.23 | 18.05 | **469.68** | 4.74 | 1.41 | 2.84 | 23.93 | 0.2956 |
| `edge06_trend_fixed` | DEV | 2X_FEES | 503 | 1,194.72 | 996.10 | 94.40 | **104.22** | 0.21 | 1.02 | 4.98 | 43.89 | 0.7245 |
| `edge06_trend_fixed` | DEV | ADVERSE | 495 | 1,232.29 | 979.45 | 229.48 | **23.37** | 0.05 | 1.00 | 4.92 | 49.47 | 3.1948 |
| `edge06_trend_fixed` | DEV | BASE | 584 | 1,746.07 | 579.88 | 109.90 | **1,056.29** | 1.81 | 1.20 | 4.04 | 23.86 | 0.0743 |
| `edge06_trend_fixed` | OOS | 2X_FEES | 113 | 364.84 | 226.69 | 21.48 | **116.67** | 1.03 | 1.15 | 1.76 | 43.92 | 0.4284 |
| `edge06_trend_fixed` | OOS | ADVERSE | 113 | 364.74 | 226.62 | 53.10 | **85.02** | 0.75 | 1.10 | 1.83 | 49.51 | 0.5843 |
| `edge06_trend_fixed` | OOS | BASE | 113 | 364.84 | 113.34 | 21.48 | **230.02** | 2.04 | 1.32 | 1.53 | 23.86 | 0.2219 |
| `edge06_trend_fixed` | VAL | 2X_FEES | 136 | 15.49 | 271.32 | 25.71 | **-281.54** | -2.07 | 0.77 | 4.18 | 43.79 | None |
| `edge06_trend_fixed` | VAL | ADVERSE | 136 | 15.78 | 271.23 | 63.55 | **-319.00** | -2.35 | 0.74 | 4.36 | 49.35 | None |
| `edge06_trend_fixed` | VAL | BASE | 136 | 15.23 | 135.67 | 25.71 | **-146.15** | -1.07 | 0.87 | 3.54 | 23.79 | None |

## 3. The frozen books, side by side (read from their own artefact)

| Book | Window | Trades | Gross | Fees | Price costs | Net | Expectancy | PF | Largest share |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `edge_trend_01_4h` | DEV | 223 | 2,128.91 | 174.63 | 33.10 | 1,921.18 | 8.62 | 1.78 | 0.0673 |
| `edge_trend_01_4h` | OOS | 52 | 264.32 | 47.34 | 8.97 | 208.01 | 4.00 | 1.33 | 0.7987 |
| `edge_trend_01_4h` | VAL | 58 | 62.52 | 48.75 | 9.24 | 4.53 | 0.08 | 1.01 | 27.5248 |
| `edge_trend_01_1d` | DEV | 39 | 943.79 | 14.53 | 2.75 | 926.51 | 23.76 | 3.93 | 0.1426 |
| `edge_trend_01_1d` | OOS | 13 | -110.74 | 6.61 | 1.25 | -118.60 | -9.12 | 0.42 | None |
| `edge_trend_01_1d` | VAL | 20 | 95.55 | 7.58 | 1.44 | 86.54 | 4.33 | 1.27 | 1.5971 |
| `edge_intra_01` | DEV | 290 | -151.71 | 289.79 | 54.92 | -496.43 | -1.71 | 0.32 | None |
| `edge_intra_01` | OOS | 63 | -19.91 | 62.97 | 11.93 | -94.81 | -1.50 | 0.30 | None |
| `edge_intra_01` | VAL | 344 | -70.15 | 343.86 | 65.17 | -479.18 | -1.39 | 0.37 | None |

*Source: `reports/edge-recovery/WP-EDGE-01/STRATEGY_RESULTS.json` — measured by the WP-EDGE-01 campaign, not by this work package.*

## 4. What this run does not do

- It does not promote anything: `promotion: NONE`, `order_sent: false`, no PAPER admission.
- It does not tune. Every parameter is the one `HYPOTHESES.md` registered before the run;
  a parameter that would have helped is a proposal for a new registration, not an edit.
- It does not claim validation from a previously read window, and says so per family.

### The registered parameters, as run

```json
{
  "edge06_fade_extension": {
    "atr_period": 14,
    "cost_margin": 1.5,
    "ema_period": 200,
    "entry_distance_atr": 2.0,
    "min_rr": 1.5,
    "stop_atr": 1.5
  },
  "edge06_trend_fixed": {
    "atr_period": 14,
    "breakout_lookback": 20,
    "cost_margin": 1.5,
    "ema_fast": 50,
    "ema_slow": 200,
    "min_rr": 2.0,
    "stop_atr": 1.0,
    "target_atr": 3.0
  },
  "edge06_xs_momentum": {
    "atr_period": 14,
    "cost_margin": 1.0,
    "exit_ema": 100,
    "relative_strength_lookback": 30,
    "stop_atr": 2.0,
    "trend_ema": 200
  }
}
```
