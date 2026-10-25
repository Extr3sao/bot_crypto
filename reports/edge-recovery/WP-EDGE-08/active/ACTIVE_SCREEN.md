# WP-EDGE-08 — the ACTIVE track, screened on the known universe

*Read at `2026-10-14T20:36:07Z` (`EDGE08_V1`). Ground: the known universe (BTC/ETH/SOL) — the screening ground, never the evidence.*

## 1. The screen that decides whether the cross-section is read at all

**C0** — gross expectancy > 0 on `DEV`. A setup that loses money before any fee cannot be repaired by a fee, so a book that fails C0 is not read on the cross-section: its holdout rows are absent, not zero.

| Arm | DEV trades | DEV gross/trade (USDT) | DEV net (USDT) | C0 | Consequence |
| --- | --- | --- | --- | --- | --- |
| `edge08_active_daybreak_1h` | 554 | 1.1815 | 18.9021 | PASS | read on the cross-section (the screen does not itself admit anything) |
| `edge08_active_multiday_range_1h` | 205 | 2.3116 | 238.7233 | PASS | read on the cross-section (the screen does not itself admit anything) |
| `edge08_active_stretch_revert_1h` | 132 | -1.2496 | -314.0392 | FAIL | a book that fails C0 gets REJECT_NO_GROSS_EDGE and is NOT read on the cross-section; its holdout rows are absent, not zero |

Forward to the cross-section: ['edge08_active_daybreak_1h', 'edge08_active_multiday_range_1h']; rejected before it: ['edge08_active_stretch_revert_1h'].

## 2. Every window, money first and frequency beside it

### `edge08_active_daybreak_1h` — A-1: can a day-high break held for days reach three trades a day and pay?

Clock `1h`, horizon 1440 min, params hash `d1ed6bbe8a016018…`.

| Window | Trades | Gross | Fees | Price costs | Net | Expectancy | PF | DD % | Sharpe | Cost bps/trade | Trades/day | Per asset/day | Hold (h) |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| DEV | 554 | 654.5252 | 534.3488 | 101.2743 | **18.9021** | 0.0341 | 1.0041 | 5.0844 | 0.0355 | 23.8152 | 0.506 | 0.1687 | 15.7762 |
| VAL | 314 | -30.9289 | 312.8366 | 59.2914 | **-403.0569** | -1.2836 | 0.791 | 4.96 | -1.3037 | 23.7837 | 0.858 | 0.286 | 14.2611 |
| OOS | 167 | -116.9139 | 166.3754 | 31.5329 | **-314.8222** | -1.8852 | 0.7194 | 5.1076 | -1.2265 | 23.7694 | 0.2564 | 0.0855 | 13.5988 |

- Exits on DEV: {'target': 151, 'trailing_stop': 80, 'stop_loss': 207, 'ema_invalidation': 116}; refusals by reason: {'risk_drawdown_halt': 1088, 'trend_filter_fail': 539, 'thrust_filter_fail': 388}.
- Expectancy interval on DEV (90 %, block bootstrap): {'low': -1.5446, 'high': 1.8223, 'point': 0.0341}; positive time blocks: 1 of 3.

### `edge08_active_multiday_range_1h` — A-3: does a compressed three-day range pay when it breaks?

Clock `1h`, horizon 1440 min, params hash `5c9c1f4e9e25257a…`.

| Window | Trades | Gross | Fees | Price costs | Net | Expectancy | PF | DD % | Sharpe | Cost bps/trade | Trades/day | Per asset/day | Hold (h) |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| DEV | 205 | 473.8715 | 197.6818 | 37.4664 | **238.7233** | 1.1645 | 1.1539 | 2.3346 | 0.4281 | 23.8432 | 0.1872 | 0.0624 | 17.6976 |
| VAL | 71 | 382.2841 | 71.026 | 13.4615 | **297.7967** | 4.1943 | 1.8287 | 0.8048 | 1.7584 | 23.9148 | 0.194 | 0.0647 | 20.8873 |
| OOS | 83 | 75.1417 | 83.0594 | 15.7421 | **-23.6598** | -0.2851 | 0.9528 | 2.1508 | -0.1437 | 23.8076 | 0.1274 | 0.0425 | 18.5783 |

- Exits on DEV: {'target': 51, 'stop_loss': 87, 'ema_invalidation': 39, 'trailing_stop': 28}; refusals by reason: {'range_not_compressed': 1531, 'trend_filter_fail': 8}.
- Expectancy interval on DEV (90 %, block bootstrap): {'low': -0.8528, 'high': 3.1717, 'point': 1.1645}; positive time blocks: 2 of 3.

### `edge08_active_stretch_revert_1h` — A-2: is the dislocation the frequent side, and does it pay the round trip?

Clock `1h`, horizon 1440 min, params hash `d625bd8129fed25e…`.

| Window | Trades | Gross | Fees | Price costs | Net | Expectancy | PF | DD % | Sharpe | Cost bps/trade | Trades/day | Per asset/day | Hold (h) |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| DEV | 132 | -164.9428 | 125.3407 | 23.7556 | **-314.0392** | -2.3791 | 0.8133 | 5.2001 | -0.482 | 23.7548 | 0.1206 | 0.0402 | 11.3409 |
| VAL | 238 | -124.446 | 237.3453 | 44.9837 | **-406.7751** | -1.7091 | 0.7715 | 5.084 | -1.1886 | 23.7736 | 0.6503 | 0.2168 | 15.3739 |
| OOS | 141 | -359.6194 | 140.0301 | 26.5397 | **-526.1891** | -3.7318 | 0.5505 | 5.2619 | -1.9495 | 23.7251 | 0.2165 | 0.0722 | 11.5319 |

- Exits on DEV: {'stop_loss': 96, 'target': 36}; refusals by reason: {'stretch_filter_fail': 30918, 'down_bar_filter_fail': 6392, 'risk_drawdown_halt': 1064, 'reward_below_cost': 2}.
- Expectancy interval on DEV (90 %, block bootstrap): {'low': -6.6569, 'high': 0.9703, 'point': -2.3791}; positive time blocks: 0 of 3.

## 3. The frequency question, answered with numbers

The ACTIVE track's registered target is **3.0 trades a day across the universe**. Measured on `OOS`: `edge08_active_daybreak_1h` 0.2564, `edge08_active_multiday_range_1h` 0.1274, `edge08_active_stretch_revert_1h` 0.2165.

Context, cited rather than remembered: `reports/edge-recovery/WP-EDGE-07/active-research/COST_BARRIER_ACTIVE.json` (sha256 `d7fcaee590aa0c77…`) measured the round trip at None bps and the capture fraction a perfect call needs merely to break even, per holding horizon. the measured barrier this track is judged against: the fraction of the open-to-open move a perfect call must capture merely to break even, per holding horizon.

## 4. Defects found by running this screen, and fixed before the registration

### `DEF-EDGE08-01`

- **Symptom.** two registered QUALITY books produced no trades at all on the screening ground: edge08_quality_pullback_daily and edge08_quality_reversion_daily could not fire, the second of them on any bar of a three-year corpus.
- **Cause.** the frozen cost_gate applies max(min_rr, cost_margin) as its reward/risk floor, so a book whose registered min_rr (1.2 and 0.5) sits below its declared cost_margin (1.5) carries a requirement that is unsatisfiable by construction — the same defect class DEF-EDGE01-01 recorded for the frozen campaign, where a candidate printed signals and never traded one of them.
- **Fix.** the reward/risk of both books was made satisfiable by design rather than by weakening a gate: Q-2 moved to a 2.0 ATR stop against a 3.0 ATR objective (R:R 1.5) and Q-3 to an ATR-denominated dislocation (entry at least 3.0 ATR below the 20-day mean, 2.0 ATR stop, objective the mean), both with min_rr = cost_margin = 1.5, so the gate judges each setup instead of refusing the book.
- **Superseded parameter hashes.** `edge08_quality_pullback_daily` `7d2c5f5c2fba5e96…` `edge08_quality_reversion_daily` `c44e61e2745b5d5b…` 
- **Found.** by running the screen, before the registration was committed and before any bar of the cross-section was aggregated or measured.
- **What did not happen.** no criterion, window, cost scenario or risk limit moved; the two books' signals are what changed, and the cross-section had not been touched when they did.
- **Evidence.** the per-arm funnels of both affected arms (zero trades and zero refusals on DEV, VAL and OOS before the fix) and the hashes above, absent from every book under test.

## 5. What this screen does not say

- Passing C0 is **not** evidence of an edge: it is a gross test on a window every earlier work package has read, and its only job is to keep a hopeless book from spending the cross-section.
- Nothing here promotes, sizes or executes: `promotion: NONE`, `order_sent: false`.
- The frequency reading is reported for every book and is never a reason to force a trade: a book that cannot reach its track's target says so with a number.
