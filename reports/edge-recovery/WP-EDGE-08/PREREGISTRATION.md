# WP-EDGE-08 / RFC-EDGE-008 — pre-registration, written before the cross-section is read

*Registered at `2026-10-14T20:26:49Z` (`EDGE08_V1`).* this file is committed before any bar of the cross-section is aggregated or measured; the raw shards are fetched from public Binance REST, and a download is not a reading — no figure of this universe existed anywhere when this file was written

## 1. Why this work package exists

RFC-EDGE-008 continues the direction WP-EDGE-07's measured cost barrier pointed at: hourly books need to capture 58-86 % of the open-to-open move to pay a 23.79 bps round trip (closed by arithmetic), a daily clock needs 11-16 % (a strategy problem).

Every time-based resource of the BTC/ETH/SOL universe has been read: the `trend` OOS window was consulted by WP-EDGE-01 and WP-EDGE-02, and the `NEW_HOLDOUT` window WP-EDGE-07 created was read once and spent. What is still unread is the **symbol dimension**:

| | |
| --- | --- |
| Cross-section | AAVEUSDT, UNIUSDT, KSMUSDT, SNXUSDT, CRVUSDT, SUSHIUSDT |
| Known universe (screening ground) | BTC, ETH, SOL |
| Corpus | `data/edge08/universe-1h` (1h, from `BINANCE_PUBLIC_REST:/api/v3/klines`) |
| Corpus digest | `fb32470f5bc6329e…` |
| Claim | no committed artefact of this repository has been measured on these symbols: their history, and the whole of it, is the evidence this work package reads once |

A symbol with a shard in one of these corpora is not a holdout: `reports/alpha-expansion-v1/data`, `data/raw/alpha003/price`, `data/edge07/holdout-1h`. The fetch refuses such a symbol and the verifier re-checks the claim from the manifest.

## 2. The two tracks, kept apart

| Track | What it is |
| --- | --- |
| **QUALITY** | a daily clock, holds of days to weeks, few trades with a large objective each; screened on gross expectancy and on a frequency floor, never on frequency alone |
| **ACTIVE** | a one-hour entry clock with multi-day holds, aiming at three trades a day across the universe; net expectancy comes before frequency and nothing is forced |
| **CURRENT** | books this project already registered and measured, carried as the baseline; they change no verdict |

## 3. The registered books

| Arm | Track | Clock | Horizon (min) | Params hash | What it answers |
| --- | --- | --- | --- | --- | --- |
| `edge08_quality_breakout_daily` | QUALITY | 1d | 4320 | `576a457a58e9fc79…` | Q-1: does the daily breakout pay its own round trip on a cross-section? |
| `edge08_quality_pullback_daily` | QUALITY | 1d | 4320 | `2ba39edfc34f04df…` | Q-2: is the cheaper entry into an uptrend the one that survives costs? |
| `edge08_quality_reversion_daily` | QUALITY | 1d | 4320 | `988137f4e8dbaf64…` | Q-3: does a band stretch inside a range regime pay after costs? |
| `edge08_active_daybreak_1h` | ACTIVE | 1h | 1440 | `d1ed6bbe8a016018…` | A-1: can a day-high break held for days reach three trades a day and pay? |
| `edge08_active_stretch_revert_1h` | ACTIVE | 1h | 1440 | `d625bd8129fed25e…` | A-2: is the dislocation the frequent side, and does it pay the round trip? |
| `edge08_active_multiday_range_1h` | ACTIVE | 1h | 1440 | `5c9c1f4e9e25257a…` | A-3: does a compressed three-day range pay when it breaks? |

| Arm | Track | Clock | Already says |
| --- | --- | --- | --- |
| `edge_trend_01_4h` | CURRENT | 4h | the frozen WP-EDGE-01 ruleset: 4h trend with a 3xATR trailing exit |
| `edge06_trend_fixed` | CURRENT | 4h | WP-EDGE-06's fixed 3xATR target, REJECT on WP-EDGE-07's unread window |
| `edge07_active_thrust` | CURRENT | 1h | WP-EDGE-07's ACTIVE thrust book, REJECT_NO_GROSS_EDGE on the known universe |

### Parameters, byte for byte

- `edge08_quality_breakout_daily` — atr_period=20 breakout_lookback=20 cost_margin=1.5 exit_ema=100 min_rr=1.5 stop_atr=2.0 target_atr=6.0 trail_atr=4.0 trend_ema=200
- `edge08_quality_pullback_daily` — atr_period=20 cost_margin=1.5 entry_distance_atr=0.5 exit_ema=100 min_rr=1.5 pullback_ema=20 stop_atr=2.0 target_atr=3.0 trail_atr=2.5 trend_fast=50 trend_slow=200
- `edge08_quality_reversion_daily` — atr_period=20 cost_margin=1.5 mean_period=20 min_rr=1.5 regime_ema_fast=50 regime_ema_slow=200 regime_max_gap_pct=1.0 stop_atr=2.0 stretch_atr=3.0
- `edge08_active_daybreak_1h` — atr_period=14 breakout_lookback=24 cost_margin=1.5 exit_ema=50 min_rr=1.25 stop_atr=2.0 target_atr=4.0 thrust_atr=0.5 trail_atr=3.0 trend_ema=200
- `edge08_active_stretch_revert_1h` — atr_period=14 cost_margin=1.5 down_bar_atr=1.0 mean_ema=48 min_rr=1.0 stop_atr=1.5 stretch_atr=2.5
- `edge08_active_multiday_range_1h` — atr_period=14 compression_atr=6.0 cost_margin=1.5 exit_ema=50 min_rr=1.5 range_lookback=72 stop_atr=2.0 target_atr=5.0 trail_atr=3.0 trend_ema=200

## 4. Windows, costs and the readings a verdict uses

| Window | From | To |
| --- | --- | --- |
| `DEV` | 2021-01-01 | 2023-12-31 |
| `VAL` | 2024-01-01 | 2024-12-31 |
| `OOS` | 2025-01-01 | 2026-10-14 |

The decisive window is `OOS`. Coverage floor per asset on the decisive window: `1h` ≥ 8000, `4h` ≥ 1500, `1d` ≥ 400.

Costs: `COST_MODEL_V3` at BINANCE_SPOT_STANDARD_TAKER (VIP0 taker), scenarios BASE, 2X_FEES, ADVERSE, a 1000 USDT intent, evaluated at the arm's own declared horizon_minutes. the plane is a venue-level model: it does not carry a per-symbol spread or book depth, so the cross-section's thinner names are covered by the ADVERSE scenario rather than by a claim the data cannot support

Bootstrap: 1000 resamples of 20-trade blocks, seed 20261014 — trades inside a window are not independent; the serial-dependence reading states that rather than assuming it away.

## 5. Criteria, and what each outcome means

All of these must hold on the decisive window at `BASE` unless the statement says otherwise. Minimum sample: **30 trades**.

| # | Criterion | Decisive | Applies to |
| --- | --- | --- | --- |
| P1 | trades >= 30 on the decisive window | True | QUALITY, ACTIVE |
| P2 | net > 0 at BASE | True | QUALITY, ACTIVE |
| P3 | expectancy > 0 at BASE | True | QUALITY, ACTIVE |
| P4 | net > 0 at 2X_FEES | True | QUALITY, ACTIVE |
| P5 | largest single trade <= 50% of the net | True | QUALITY, ACTIVE |
| P6 | at least one positive market context | True | QUALITY, ACTIVE |
| R1 | net still > 0 with the largest winner removed | True | QUALITY, ACTIVE |
| R2 | net > 0 in at least 2 of the 3 equal time blocks | True | QUALITY, ACTIVE |
| S1 | DEV gross > 0 on the cross-section: the entry, not the exit, carries it | True | QUALITY, ACTIVE |
| F1 | ACTIVE only: trades/day across the universe >= 3.0 | True | ACTIVE |
| F2 | QUALITY only: trades/day across the universe >= 0.05 (about one trade per asset every twenty days), reported and decisive as a floor on viability | True | QUALITY |

**Gross screen (C0).** gross expectancy > 0 on the known universe's DEV window — a book that fails C0 gets REJECT_NO_GROSS_EDGE and is NOT read on the cross-section; its holdout rows are absent, not zero

**Frequency targets per day across the universe.** `ACTIVE` ≥ 3.0, `QUALITY` ≥ 0.05.

| Verdict | Means |
| --- | --- |
| `ADMIT_PAPER` | every decisive criterion passes on the cross-section's OOS window: admission to paper only; no live trading, no capital, no promotion beyond a paper lane, and the risk-manager's and the release gate's own conditions still apply |
| `REJECT` | a decisive criterion failed with power on the cross-section; the family is reported with its numbers and is not tuned and re-run on the same window |
| `INSUFFICIENT_EVIDENCE` | the measurement cannot support a conclusion (unpowered sample with the rest non-negative, one trade carrying the net, or coverage below the declared floor) |
| `REJECT_NO_GROSS_EDGE` | the book lost money before any fee on the known universe, so the cross-section was not read with it |

## 6. Multiplicity

6 proposed books plus 3 frozen comparison books: 9 arms, every one reported. every arm is reported; no book is re-parameterised after seeing a result, and a book that fails the gross screen is not read on the cross-section at all.

## 7. Consequences, fixed in advance

- a book that fails the gross screen (C0) is not read on the cross-section at all: its holdout rows are absent, not zero
- a REJECT is reported with its numbers and the family is not tuned and re-run on the same window
- an INSUFFICIENT_EVIDENCE is reported as no result, never as a pass
- no parameter, stop, target, filter or cooldown is changed after seeing a reading
- nothing here promotes, sizes or executes anything: promotion stays NONE and order_sent stays false for every arm

## 8. What this cannot say

- the cross-section is six symbols: a transfer test across six names is evidence about those names, not a proof that a book generalises to every market
- the cost plane is venue-level; a per-symbol spread is not modelled and the ADVERSE scenario is the only sensitivity that speaks to it
- the decisive window's sample size is what the book's own frequency makes it; a book that trades twice a year cannot be powered by 1.8 years of six symbols
