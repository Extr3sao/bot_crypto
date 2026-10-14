# WP-EDGE-07 Track B — pre-registration, written before the new window is read

*Registered at `2026-10-14T08:53:54Z` (`EDGE07-PREREG-20261014T085354Z`). This file is committed
**before** the holdout corpus is fetched and before any figure of the new window exists. The
commit order is the evidence: `git log --follow` on this file shows the registration commit and
the results commit, and the results commit is the later one.*

## 1. What is being validated, and what is not

The trend book with a **fixed 3×ATR target** (`edge06_trend_fixed`, WP-EDGE-06) cleared the
frozen admission gate on the campaign's `trend` OOS window — 113 trades, +230.02 USDT at BASE,
+116.67 at 2× fees. That result is **not validation**: `HYPOTHESES.md` §1 disclosed that the
`trend` OOS window (2025-01-01…2026-02-28) had already been read by the frozen
`edge_trend_01_4h` ruleset in WP-EDGE-01 and again by WP-EDGE-02's robustness analysis.

The local corpora end exactly at that window's last bar (`BTCUSDT_2026.json`:
2026-02-28 23:00Z). So this work package creates the one thing that was missing — a period
nobody has read — and reads it once, with criteria fixed in advance.

**Frozen, byte for byte, from the WP-EDGE-06 registration** (`edge06_trend_fixed`, the only
book under test here; `params_hash`
`9ceb20fc7d4500c334e2d58f6ff4cd6d26c6b228c4f8ef93f3c709082e44e8ad`):

| Parameter | Value |
| --- | --- |
| `ema_fast` / `ema_slow` | 50 / 200 |
| `breakout_lookback` | 20 |
| `atr_period` | 14 |
| `stop_atr` | 1.0 × ATR |
| `target_atr` | 3.0 × ATR |
| `min_rr` | 2.00 |
| `cost_margin` | 1.50 |
| trailing exit | **none** |

Nothing above may change. A parameter that would have helped is a *proposal for a new
registration*, never an edit, and this window may not be re-run after seeing its figures.

## 2. The new window, and the corpus it comes from

| | |
| --- | --- |
| Window name | `NEW_HOLDOUT` |
| Period | `2026-03-01T00:00:00Z` … `2026-10-14T08:00:00Z` (end exclusive) |
| Corpus | 1h bars fetched once from the public Binance REST endpoint `/api/v3/klines`, aggregated to 4h by the campaign's own `resample` (a bucket is emitted only when complete and contiguous) |
| Provenance | `data/edge07/holdout-1h/_FETCH_MANIFEST.json`, one SHA-256 per shard, the exact request range, and the gaps left absent |
| Why unread | every earlier Edge work package read the corpora that end at 2026-02-28; this range begins after it |
| Coverage rule | the window is reported with its bar counts and gaps. A window whose 4h coverage is below `MIN_HOLDOUT_BARS` (300 bars per asset) is reported `INSUFFICIENT_EVIDENCE` for coverage, not measured around |

## 3. The arms, fixed now

| Arm | Book | Kept identical |
| --- | --- | --- |
| Primary (H-TARGET-H) | fixed 3×ATR target, no trail — the frozen `edge06_trend_fixed` parameters | — |
| Comparison | the frozen `edge_trend_01_4h` ruleset (3×ATR trailing exit + EMA(50) exit) | same corpus, same window, same costs, same risk policy, same simulator |

Two books, one window, no sweep of anything: the comparison arm is declared here so it cannot
be chosen after seeing which one looks better. Multiplicity is therefore 2 and is reported.

## 4. Costs, sizing and fills — unchanged from the campaign

`COST_MODEL_V3` through `edge01.costs.cost_plane`, scenarios **BASE**, **2X_FEES** and
**ADVERSE**. Sizing, caps, cooldowns and the drawdown halt come from `config/risk.yaml` through
the campaign's own `RiskPolicy`; no arm may size a position, relax a limit or add a cooldown.
Fills are the campaign's simulator: signal at the close of bar *i*, fill at the open of *i+1*,
gap through the stop fills at the open, stop evaluated before target inside a bar, an open
position is settled at the window's last bar.

Metrics are the campaign's own `_metrics`, plus the four readings this work package adds and
declares here: a 90 % confidence interval for expectancy by **trade-block bootstrap** (1,000
resamples of 20-trade blocks, fixed seed `20261014`), the **time-block** arm (the window split
into three equal consecutive thirds), **per-asset** and **per-market-context** breakdowns, and
one **serial-dependence** reading (lag-1 autocorrelation of trade returns with its own ±2/√n
band, plus a runs test on the sign sequence).

## 5. The criteria, and what each outcome means

Primary window `NEW_HOLDOUT`, BASE scenario unless stated. **All of P1–P6 and R1, R2, S1 must
hold for `ADMIT_PAPER`.**

| # | Criterion | Decisive |
| --- | --- | --- |
| P1 | trades ≥ 30 | yes |
| P2 | net > 0 | yes |
| P3 | expectancy > 0 | yes |
| P4 | net > 0 at 2× fees (cost margin) | yes |
| P5 | largest single trade ≤ 50 % of the net | yes |
| P6 | ≥ 1 positive regime (the campaign's own `by_regime` reading) | yes |
| R1 | net is still > 0 with the single largest winner removed | yes |
| R2 | net > 0 in ≥ 2 of the 3 equal consecutive time blocks | yes |
| R3 | per-asset and per-context breakdown, bootstrap CI: **reported, never decisive** | no |
| S1 | DEV gross > 0 (the entry, not the exit, carries the book) | yes |

| Verdict | Means |
| --- | --- |
| `ADMIT_PAPER` | every decisive criterion above passes on `NEW_HOLDOUT`. Admission to **paper only**: no live trading, no capital, no promotion beyond a paper lane, and the risk-manager's and release gate's own conditions still apply |
| `REJECT` | a decisive criterion failed with power: P1 with net ≤ 0, or P4, or R1, or R2, or S1, or a negative gross in DEV |
| `INSUFFICIENT_EVIDENCE` | P1 fails while the rest is non-negative, or P5 fails (one trade carries the net), or coverage is below `MIN_HOLDOUT_BARS`, or the fetch/aggregation could not produce the window |

Consequences fixed in advance: a `REJECT` is reported with its numbers and the family is **not**
tuned and re-run on this window; an `INSUFFICIENT_EVIDENCE` is reported as no result, never as a
pass; nothing here promotes, sizes or executes anything, and `order_sent` stays `false`.
