# WP-EDGE-06 Track B — hypotheses, registered before the experiments run

> Written and committed **before** any out-of-sample reading of the families below. The
> commit that carries this file is the evidence of the order: `git log --follow` on it shows
> the registration commit and the results commit, and the results commit is the later one.
> Nothing in this document was edited after the run; corrections, if any are needed, are
> appended in the results report as *post-hoc* observations and labelled as such.

## 0. What the audit already settled, so no hypothesis is spent on it

`STRATEGY_AUDIT.md` (Track B, item 1–2) decomposes the frozen intraday book from the
campaign's own per-trade fields. The result is a fact, not a hypothesis:

- the gross expectation is **negative in every window** — DEV −10.46 bps/trade over 290
  trades, VAL −4.08 over 344, OOS −6.32 over 63 — against a cost of ~23.8 bps/trade;
- so the intraday loss is **not primarily a cost problem**, and `H-COST` ("the setup has a
  positive gross edge that fees consume") is **rejected by the frozen data**;
- the exit mix says where the money goes: the 40 `target` exits earned **+129.23 bps/trade**
  gross while the 130 `stop_loss` exits lost **−47.10** and the 73 `invalidation` exits
  **−36.09**. The setup's winners pay; there are far too few of them, and the losers leave
  earlier than the winners arrive.

That is the starting point. The three hypotheses below are families that could plausibly
have a *positive gross* expectation on the same corpus, and each one is written so that it
can fail.

## 1. The rules every experiment here obeys

| | |
| --- | --- |
| Corpus | the local frozen corpora only: 1h shards aggregated to 4h, 15m where declared. No new data, no vendor, no synthetic bars. |
| Windows | the campaign's own pre-registered `trend` split — DEV 2019-01-01…2023-12-31, VAL 2024-01-01…2024-12-31, OOS 2025-01-01…2026-02-28. |
| Costs | `COST_MODEL_V3` through the campaign's own `cost_plane`, scenarios BASE, 2X_FEES, ADVERSE, derived from the same components. |
| Sizing, caps, cooldowns | `config/risk.yaml` through the campaign's own `RiskPolicy`. No experiment may size a position, relax a limit or add a cooldown. |
| Fills | the campaign's own simulator: signal at the close of bar *i*, fill at the open of bar *i+1*, gap through the stop fills at the open, stop before target inside a bar, position open at the window's last bar settled there. |
| Metrics | the campaign's own `_metrics`, so expectancy, profit factor, drawdown, exposure and cost bps/trade have exactly the definitions the frozen books were measured with. |
| Gate | the campaign's own `_gate` and `ADMISSION_CRITERIA` (≥30 OOS trades, OOS net and expectancy > 0, no single trade > 50 % of the OOS net, ≥1 positive regime, OOS still positive at 2× fees). Unchanged. |

**Disclosure that bounds every claim below.** The `trend` OOS window has already been read
once, by the frozen `edge_trend_01_4h` ruleset (`WP-EDGE-01`, and again by `WP-EDGE-02`'s
robustness analysis). No corpus can invent a second, unread out-of-sample year. So a family
that clears the gate on this window is **not** validated by it: it is only *not yet rejected*
by a window that has been looked at before. The results report states this next to every
verdict, and no family is promoted on it.

## 2. H-XS — cross-sectional relative strength beats single-asset trend

**Statement.** Among BTC, ETH and SOL on 4h bars, an entry restricted to the asset with the
highest 30-bar return, while the benchmark is in an uptrend, has a positive gross
expectation after costs — because concentrating the book on the strongest asset of the three
avoids paying the stop-loss exits of the two weaker ones.

**Falsified if** the family's gross is not positive in DEV, or its OOS net turns negative
under 2× fees, or its OOS net is carried by one trade above the frozen 50 % limit.

| Parameter | Value |
| --- | --- |
| `lookback_bars` (relative strength) | 30 |
| `trend_ema` (asset must be above it) | 200 |
| `atr_period` | 14 |
| `stop_atr` (stop distance) | 2.0 × ATR |
| `exit_ema` (close below it exits) | 100 |

**Known weakness, stated in advance.** The simulator holds one position per asset, so this
book is *not* a true rotation: it suppresses entries from non-leaders, and an existing
position leaves only through its own EMA exit. If the family shows an edge, the next
question is a real rotation; if it shows none, no rotation machinery is worth building.

## 3. H-FADE — buying a stretched pullback back to the mean pays where breakouts do not

**Statement.** On 4h bars, a long entered when the close is at least 2 ATR below its own
200-bar EMA — a stretched pullback — and exited at the EMA itself, has a positive gross
expectation, because the intraday result suggests the family's problem is entering
*extensions* rather than entering *dislocations*.

**Falsified if** the gross is not positive in DEV, or the family fails the frozen gate's
cost-stress criterion, or it needs a stop distance smaller than the ATR to survive (that
would mean the result is an artefact of the stop, not of the entry).

| Parameter | Value |
| --- | --- |
| `ema_period` (the mean) | 200 |
| `atr_period` | 14 |
| `entry_distance` (below the mean) | 2.0 × ATR |
| `stop_atr` | 1.5 × ATR |
| `target` | the EMA at the decision bar |
| `min_rr` (reward/risk floor the cost gate enforces) | 1.5 |

## 4. H-TARGET — the 4h trend edge survives a fixed target, so it was never the trail

**Statement.** The frozen `edge_trend_01_4h` entry (breakout of the prior 20-bar extreme
with EMA(50) > EMA(200) and close > EMA(200)) with a **fixed** 3×ATR target and a 1×ATR stop
— no trailing exit at all — clears the same gate. This is the direct test of the reading
WP-EDGE-01 left open: its 4h book earned +208 USDT OOS but with 79.87 % of the net in one
trade, which is what a trailing exit does — it lets one runner pay for many small losses.

**Falsified if** the fixed-target variant's OOS net is not positive, or it fails the
concentration criterion, or its DEV gross is negative (which would say the entry, not the
exit, is what carried the frozen book).

| Parameter | Value |
| --- | --- |
| `breakout_lookback` | 20 (the frozen value) |
| `ema_fast` / `ema_slow` | 50 / 200 (the frozen values) |
| `atr_period` | 14 |
| `stop_atr` | 1.0 × ATR |
| `target_atr` | 3.0 × ATR |
| trailing | none |

## 5. What each outcome will be reported as

- **`ADMIT_ELIGIBLE`** — the frozen gate passes *and* the family is not carried by one
  trade *and* its gross is positive in DEV. Even then it goes to a *new* pre-registered
  window before PAPER, because of the disclosure in §1. Nothing in this work package
  promotes anything.
- **`REJECT_NO_GROSS_EDGE`** — negative gross expectation in DEV; the same class of result
  the intraday book produced. No amount of fee reduction moves it.
- **`REJECT_COST_MARGIN`** — positive gross, but the net turns negative under 2× fees.
- **`INSUFFICIENT_EVIDENCE`** — the gate's sample or concentration criteria are not met:
  underpowered, or one trade carries the net.
- **`REJECTED_BY_ROBUSTNESS`** — clears the gate but fails the same reading with its largest
  winning trade removed (the sensitivity arm the frozen books were already put through).

A family that fails is reported as failed, with its numbers, and is not tuned and re-run on
the same window. A parameter that would have helped is recorded as a *proposal for a new
pre-registered run*, never applied here.
