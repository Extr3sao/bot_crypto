# WP-EDGE-08 — the QUALITY track, screened on the known universe

*Read at `2026-10-14T20:35:45Z` (`EDGE08_V1`). Ground: the known universe (BTC/ETH/SOL) — the screening ground, never the evidence.*

## 1. The screen that decides whether the cross-section is read at all

**C0** — gross expectancy > 0 on `DEV`. A setup that loses money before any fee cannot be repaired by a fee, so a book that fails C0 is not read on the cross-section: its holdout rows are absent, not zero.

| Arm | DEV trades | DEV gross/trade (USDT) | DEV net (USDT) | C0 | Consequence |
| --- | --- | --- | --- | --- | --- |
| `edge08_quality_breakout_daily` | 52 | 18.4381 | 924.1688 | PASS | read on the cross-section (the screen does not itself admit anything) |
| `edge08_quality_pullback_daily` | 165 | -1.8711 | -378.976 | FAIL | a book that fails C0 gets REJECT_NO_GROSS_EDGE and is NOT read on the cross-section; its holdout rows are absent, not zero |
| `edge08_quality_reversion_daily` | 0 | None | 0 | FAIL | a book that fails C0 gets REJECT_NO_GROSS_EDGE and is NOT read on the cross-section; its holdout rows are absent, not zero |

Forward to the cross-section: ['edge08_quality_breakout_daily']; rejected before it: ['edge08_quality_pullback_daily', 'edge08_quality_reversion_daily'].

## 2. Every window, money first and frequency beside it

### `edge08_quality_breakout_daily` — Q-1: does the daily breakout pay its own round trip on a cross-section?

Clock `1d`, horizon 4320 min, params hash `576a457a58e9fc79…`.

| Window | Trades | Gross | Fees | Price costs | Net | Expectancy | PF | DD % | Sharpe | Cost bps/trade | Trades/day | Per asset/day | Hold (h) |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| DEV | 52 | 958.7812 | 29.0976 | 5.5149 | **924.1688** | 17.7725 | 2.4865 | 2.5776 | 1.3481 | 24.5964 | 0.0475 | 0.0158 | 347.0769 |
| VAL | 31 | 317.8406 | 19.0902 | 3.6181 | **295.1323** | 9.5204 | 1.7572 | 2.2886 | 1.0583 | 24.1887 | 0.0847 | 0.0282 | 296.5161 |
| OOS | 17 | -45.1579 | 10.6289 | 2.0145 | **-57.8012** | -3.4001 | 0.8014 | 2.1158 | -0.3013 | 23.6854 | 0.0261 | 0.0087 | 381.1765 |

- Exits on DEV: {'target': 19, 'trailing_stop': 10, 'stop_loss': 19, 'ema_invalidation': 2, 'end_of_data': 2}; refusals by reason: {'trend_filter_fail': 51}.
- Expectancy interval on DEV (90 %, block bootstrap): {'low': 5.8488, 'high': 28.7858, 'point': 17.7725}; positive time blocks: 2 of 3.

### `edge08_quality_pullback_daily` — Q-2: is the cheaper entry into an uptrend the one that survives costs?

Clock `1d`, horizon 4320 min, params hash `2ba39edfc34f04df…`.

| Window | Trades | Gross | Fees | Price costs | Net | Expectancy | PF | DD % | Sharpe | Cost bps/trade | Trades/day | Per asset/day | Hold (h) |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| DEV | 165 | -308.7333 | 59.0509 | 11.1918 | **-378.976** | -2.2968 | 0.5474 | 5.0301 | -0.9375 | 23.6624 | 0.1507 | 0.0502 | 53.2364 |
| VAL | 115 | -150.5451 | 52.3472 | 9.9213 | **-212.8136** | -1.8506 | 0.6502 | 3.3742 | -1.1933 | 23.7179 | 0.3142 | 0.1047 | 49.0435 |
| OOS | 127 | 96.5923 | 58.0431 | 11.0008 | **27.5484** | 0.2169 | 1.0519 | 1.5924 | 0.1444 | 23.8257 | 0.195 | 0.065 | 24.9449 |

- Exits on DEV: {'target': 6, 'stop_loss': 13, 'trailing_stop': 3, 'ema_invalidation': 143}; refusals by reason: {'trend_filter_fail': 681, 'rr_below_minimum': 170, 'risk_drawdown_halt': 31}.
- Expectancy interval on DEV (90 %, block bootstrap): {'low': -3.8263, 'high': -0.6931, 'point': -2.2968}; positive time blocks: 0 of 3.

### `edge08_quality_reversion_daily` — Q-3: does a band stretch inside a range regime pay after costs?

Clock `1d`, horizon 4320 min, params hash `988137f4e8dbaf64…`.

| Window | Trades | Gross | Fees | Price costs | Net | Expectancy | PF | DD % | Sharpe | Cost bps/trade | Trades/day | Per asset/day | Hold (h) |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| DEV | 0 | 0 | 0 | 0 | **0** | None | None | 0.0 | None | None | 0.0 | 0.0 | None |
| VAL | 0 | 0 | 0 | 0 | **0** | None | None | 0.0 | None | None | 0.0 | 0.0 | None |
| OOS | 0 | 0 | 0 | 0 | **0** | None | None | 0.0 | None | None | 0.0 | 0.0 | None |

- Exits on DEV: {}; refusals by reason: {'regime_filter_fail': 66}.
- Expectancy interval on DEV (90 %, block bootstrap): {'low': None, 'high': None, 'point': None}; positive time blocks: 0 of 3.

## 3. The frequency question, answered with numbers

The QUALITY track's registered target is **0.05 trades a day across the universe**. Measured on `OOS`: `edge08_quality_breakout_daily` 0.0261, `edge08_quality_pullback_daily` 0.195, `edge08_quality_reversion_daily` 0.0.

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
