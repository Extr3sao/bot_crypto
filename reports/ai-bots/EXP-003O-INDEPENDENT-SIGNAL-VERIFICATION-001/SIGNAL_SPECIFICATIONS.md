# SIGNAL SPECIFICATIONS — EXP-003O

Semantics read from the frozen code at `scripts/exp_003n_screen.py`,
`src/trading_bot/research/families/*.py`, `src/trading_bot/indicators/builtin.py` and
`src/trading_bot/research/economic_recovery/pit15.py`. Every statement below is a property of
that code, including the parts a reader would not guess.

## 1. Data and calendar

- Minutes are the archived 1m klines of EXP-003K (`reports/ai-bots/EXP-003K-CANDIDATE-001/dataset`),
  one row per minute, `ts_ms` = the bar's **open** time.
- A bar of timeframe `T` aggregates `T / 1m` consecutive minutes **by position**, starting at
  the series' first minute; a trailing partial group is dropped, never padded. The series is
  86 400 minutes (2026-06-21 00:00 → 2026-08-19 23:59 UTC), evenly divisible by 5, 60 and 240,
  and has no gaps (verified: 86 399 deltas of exactly 60 000 ms in every symbol).
- The research series is cut at `bar_open_time < 2026-08-06T00:00:00Z`. No bar, signal or
  statistic at or after that instant is produced.
- **Availability convention** (declared, not observed): a bar whose open is `T` and whose
  interval is `I` holds the trades of `[T, T+I)` and is treated as available at `T+I`.
  `bar_close_time = data_available_at = T+I`, and `decision_time = data_available_at`.
  An entry that the decision triggers fills at the **open of the next bar**, whose own
  timestamp is also `T+I`; the contract therefore allows `decision_time == fill_time` and
  records it as a known optimism (no latency, no queue, no partial fill) rather than pretending
  the fill is observed.

## 2. Lane A — the six AlphaFamilies

Common to all six:

- **Decision window.** Each decision at bar index `i` is taken on the **80 bars ending at `i`**
  (`LANE_A_WINDOW = 80`, which is the frozen producer's `max(min_candles + 1, 80)`). Re-seeding
  an EMA on an 80-bar window is not the same number as running it over the whole series, so the
  window is part of the rule, not an implementation detail.
- **Decision instants.** Every bar from index 79 to the last bar of the research window.
  Indices 0..78 are `NOT_READY`.
- **Direction.** A signal is emitted at the close of bar `i`; the producer's forward-return
  code enters at the open of bar `i+1`. The signal is long or short only; nothing is emitted
  while a position is open, because lane A has no position state at all.
- **Indicators**, all computed on closes/volumes of that 80-bar window:
  - `EMA(p)`: seed = arithmetic mean of the first `p` closes of the window, then
    `ema = close*k + ema*(1-k)`, `k = 2/(p+1)`.
  - `RSI(14)`: Wilder. Seed = mean of the first 14 gains and of the first 14 losses of the
    window's 79 deltas; then `avg = (avg*(p-1) + value)/p`. `avg_loss == 0` returns `100.0`.
  - `ATR(14)`: true range per bar with the previous close (the window's first bar uses
    `high - low`); seed = mean of the first 14 TRs; Wilder smoothing. The family refuses to
    emit when `ATR <= 0`.
  - `MACD(12,26,9)`: EMA12 and EMA26 seeded on the window's closes; the fast series is aligned
    by dropping its first `26-12 = 14` values; the signal line is `EMA(9)` of the MACD series,
    seeded on its first 9 values; `histogram = macd - signal`.
  - `Bollinger(20, 2.0)`: mean and **population** standard deviation over the last 20 closes
    of the window (the current bar included).
  - `Momentum(10)`: `close[-1]/close[-11] - 1`.
  - `VolumeRelative(20)`: `volume[-1] / mean(volume[-21:-1])` — the current bar is excluded
    from its own baseline.

Per family:

| family | rule (long) | rule (short) | guard |
| --- | --- | --- | --- |
| `ema_crossover` | `EMA9 > EMA21` and `RSI14 > 50` | `EMA9 < EMA21` and `RSI14 < 50` | `ATR14 > 0` |
| `momentum` | `histogram > 0` and `Momentum10 > 0.005` | `histogram < 0` and `Momentum10 < -0.005` | `ATR14 > 0` |
| `breakout` | `close > max(high[-21:-1])` and `VolumeRelative20 >= 1.5` | `close < min(low[-21:-1])` and `VolumeRelative20 >= 1.5` | `ATR14 > 0` |
| `mean_reversion` | `close[-2] < lower` and `close[-1] > lower` | `close[-2] > upper` and `close[-1] < upper` | `ATR14 > 0` |
| `trend` | `EMA8 > EMA21 > EMA55` and `slope > 0.0005` | `EMA8 < EMA21 < EMA55` and `slope < -0.0005` | `ATR14 > 0`, `EMA55 > 0` |
| `volatility` | 6 consecutive squeeze bars, then `close > upper` | 6 consecutive squeeze bars, then `close < lower` | `ATR14 > 0` |

Three of those rules contain a detail that a paraphrase loses:

1. `trend` computes `slope` as `(EMA55(window) - EMA55(window[:-1])) / EMA55(window[:-1])`.
   The second value is a **55-EMA re-seeded on a 79-bar series**, not the previous value of the
   first series. Reproducing `slope` as a difference of consecutive EMA values of one series
   gives a different number.
2. `volatility` tests the squeeze on `window[:-i]` for `i = 6..1` while the released close is
   compared against the Bollinger bands of the **whole** window. The two band sets come from
   different prefixes by construction.
3. `mean_reversion` re-enters when the previous close was outside the band and the current close
   is back inside it. The band itself includes the current bar, so a violent bar can move the
   band it is being compared to.

## 3. Lane B — the three WP-EDGE-015 machines

- Stateful, streaming, one decision per closed bar, from bar 0. Warm-up is not a guard but a
  consequence: a rule whose input is `NaN` is false.
- `NOT_READY` is declared mechanically from the frozen inputs, not from the absence of signals:
  `vol_regime_breakout` and `mean_reversion_vol_liq` need 720 ATR values, and the ATR needs 24
  bars, so bar 743 is the first whose percentile exists; `trend_pullback` needs a 200-bar EMA and
  its value 24 bars back, so bar 223 is its first.
- **Parameter names lie about timeframes.** `channel_hours`, `percentile_window_hours`,
  `*_ema_hours` are consumed as **bar counts**. On 1h bars this coincides with the name; on 4h
  bars it does not (168 "hours" = 672 hours of wall clock). This is a defect of the inherited
  universe, reproduced as frozen (`DEF-003O-02`) and never silently repaired.
- `PercentileRank` fixes its bucket bounds from the first 720 known values, uses 50 buckets,
  clamps every later value into the outermost bucket, and returns
  `(count_below + 0.5*count_in_bucket) / 720`.
- Fill policy of the driver: a decision taken at the close of bar `t` fills at the open of `t+1`;
  an entry that would fill at the same instant as the previous exit is dropped; a position still
  open at the last bar is marked at that close with `is_mark=true` and is **not** a decision.
- **Direction** is long-only for all three machines. An exit decision is reported as
  `SIGNAL/FLAT` so that exits are compared too, not only entries.

## 4. What is compared

Only **decisions**: state, direction and decision instant, keyed by
`(cell_id, symbol, decision_time)`. Indicator values are not compared, and no numeric tolerance
is used for a decision: a float difference that changes a decision is a decision difference, and
a float difference that changes nothing is outside this experiment by design. That choice is
declared here, before any number exists, so it cannot be chosen after seeing a difference.

## 5. Known ambiguities that are reproduced, not repaired

| id | ambiguity | treatment |
| --- | --- | --- |
| `AMB-01` | `trend`'s slope is a difference of two differently-seeded EMAs | reproduced exactly; documented above |
| `AMB-02` | lane-B `*_hours` are bar counts | reproduced; flagged as `DEF-003O-02` |
| `AMB-03` | lane A has no position state, so a signal can fire on every bar of a trend | reproduced; it is a property of the screening, not of the verification |
| `AMB-04` | availability is `open + interval` by convention, never observed | declared; every row carries `data_available_at` |
| `AMB-05` | lane B 4h cells have 0 evaluable bars (276 bars, 744-bar warm-up) | `INSUFFICIENT_EVIDENCE_REAL_WINDOW`, never `PASS` |
