# EXPERIMENT_INVENTORY — every economic experiment this checkout actually contains

**Date:** 2026-10-21 · **Source of truth:** `reports/`, `data/`, `git ls-tree HEAD`
**Method:** every row was read from the run's own JSON, not from a summary. Rows marked **re-derived**
were recomputed this session; every other row is **read, not re-derived**, and says so.

The inventory exists to answer one question before any new experiment is proposed: *what has already been
measured, on which bytes, and what did it decide?*

---

## 1. The `EXP-003` chain (the economic core of this branch)

| | **003J** | **003K** | **003L** | **003M** | **003N** |
| --- | --- | --- | --- | --- | --- |
| Question | can a real signal reach the true paper entrypoint, and does it pay? | do six families beat `ema_crossover`? | what do fees and fills do to the best candidate? | does a tape-based maker fill model keep 003L's candidate alive? | does *any* cell have gross edge, before the cost argument? |
| Strategy | `ema_crossover` `sha256:1e7e392fd1d6efe8` | 6 families + baseline | grid frozen at 6 strategies × 4 timeframes = 24 cells, **8 executed** | frozen `5m/mean_reversion` | 6 families × 3 assets × 3 timeframes |
| Assets | BTC, ETH, SOL | BTC, ETH, SOL | BTC, ETH, SOL | BTC, ETH, SOL | BTC, ETH, SOL |
| Timeframe | 1m bars, decisions on bar close | 2h decision cadence over 1m bars | 5m / 1h / 4h | 5m signals, 1m tape | 5m / 1h / 4h |
| Dataset | 1m, **2026-08-20 → 2026-10-18**, 86 400 bars/asset, `52fd42dd…` / `6644c8f4…` / `62f55fa9…` | 1m, **2026-06-21 → 2026-08-19**, `7fbdfefa…` / `cf04dc37…` / `33342aac…` | same bytes as 003K | same bytes as 003K + trade tape | same bytes as 003K |
| Partitions | research / OOS per 003K | research 06-21→08-06, OOS 08-06→08-20, embargo 24 bars | research only; **holdout not opened** | research only | IS 06-21→07-11, VAL 07-11→07-26, TEST 07-26→08-06, holdout **CLOSED** |
| Fees (bps/side) | 10 + half spread + slippage | same | `spot_vip0_bnb`; fee floor 20 bps | 10 (taker), maker arm modelled | 10 + 2.39 price bps (BTC/ETH), 3.65 (SOL) → **24.79 / 27.31** round trip |
| Slippage | in `cost_for` | in `cost_for` | swept 1.0× / 1.5× / 2.0× | queue-position sweep, 0/1/2 ticks | half-spread + impact at 500 USDT |
| Trades | 505 total, **175 OOS** | 732 fills, **1 118 closes** across 4 arms (482 + 131 + 330 + 175) | 1 430 closes (identifier VL6) | 47 signals → **44 fills** (93.6 %) | 24 cells; signal counts gated at 50/20/15 |
| PnL | OOS real **−225.4010 USDT**, gross +0.4166, costs 225.8176, **−1.288/trade** | real/OOS −225.4010 (same run); control/OOS −202.4455 | every config negative; e.g. 339 closes **−503.54**, CI [−1.851, −1.084]/trade | gross **+0.2669/fill**, fee 0.75, **net −0.4831/fill**, total −21.2560 | no PnL claim; mean net bps per cell |
| Drawdown | 2.02 / 4.62 / 2.26 % | 1.69 / 5.03 / 0.66 % | 5.04 / 0.64 / 5.12 % | not reported (no equity curve) | n/a (signal-level) |
| Robustness | 10 000-round bootstrap, seed 20261020 | cost stress, regime split | 1.5×/2.0× cost stress, both halves, 10 000-round moving block | 4 fill scenarios + queue sweep | BH at q=0.10 over **114** tests |
| Verifier | PASS (external program) | VK1… PASS | VL1… PASS | 13 passed, 1 not executed (*seal*), 8/8 controls | **12/12 checks, 10/10 controls — re-derived from clean `HEAD`** |
| Evidence | `reports/ai-bots/EXP-003J-.../` — **untracked in Git** | reported | reported | `SEAL.json` present | sealed, `sha256sum -c` 29/29 |
| Decision | **REJECT** (economic), PASS (technical) | **BLOCKED / NO_VIABLE_CANDIDATE** | **NO_VIABLE_CANDIDATE** | **REJECT** | **no advance: 13 REJECT, 10 INSUFFICIENT_EVIDENCE, 1 EXPERIMENT, 0 ADVANCE** |

### 1.1 Two findings that change how the chain should be read

**`EXP-003J` is not a second confirmation of `EXP-003K`; it is the same 175 trades.** J reports 505 total
closes and 175 OOS; K's `real` arm reports 330 research + 175 OOS = 505, with the identical
`net_usdt = −225.401044` at OOS and the identical cost figure. J is K's `real` arm rendered as a runtime
report. Anyone counting them as two independent negative results would double-count one.

**The `2026-08-06 → 2026-08-20` window is spent, even though `EXP-003N` labels it `CLOSED`.** K ran both its
`control` (131 closes) and its `real` (175 closes) arms on that OOS window. N's `CLOSED` is true *of N's own
protocol* — N produced no row at or after `2026-08-06T00:00:00Z`, which the verifier confirms twice — but the
window had already been read. It cannot be a confirmatory holdout for anything, and N's refusal to touch it
was the right call for a different reason than its report states.

## 2. The `WP-EDGE` family (reports/edge-recovery)

Nine work packages, all negative, all with an independent verifier and a sabotage self-test. Read, not
re-derived here.

| WP | What was tested | Sample | Result | Decision |
| --- | --- | --- | --- | --- |
| 01 | intraday 15m, retest+FVG, and a no-FVG variant | 686 orders | gross −496.43 / −189.88 / −500.83 USDT | `REJECT` |
| 02 | same arms, risk-policy attribution | 372/686 filled (54.2 %) | 148 of 183 rejections were the 5 % drawdown halt — correct behaviour | `REJECT` (no execution bug) |
| 06 | `edge06_fade_extension`; `edge06_trend_fixed` | — | fade: `REJECT_NO_GROSS_EDGE`; trend: +230.02 on a **previously read** window | trend result explicitly *not* validation |
| 07 | trend book, fixed 3×ATR target, on a genuinely new window `2026-03-01 → 2026-10-14`, preregistered at `2026-10-14T08:53:54Z` **before fetching** | **65 trades** | net **−140.3041**, expectancy **−2.1585/trade**, 1 of 3 time blocks positive, sample powered | **`REJECT`** |
| 08 | daily cross-sectional quality breakout, 7 alts (`data/edge08/universe-1h`) | 30 cross trades | **−166.6146 USDT** | **`REJECT`** |
| 09 | adoption review of the above | — | — | **`DO_NOT_ADOPT`** |

WP-EDGE-07 is the methodological benchmark of this repository: the window was created because the previous
one had been read, the criteria were committed before the fetch, and the arm was still rejected. That is what
an honest experiment looks like when the answer is no.

## 3. The `ALPHA` family (pre-003)

| Experiment | What was tested | Sample | Gross | Net | Decision |
| --- | --- | --- | --- | --- | --- |
| ALPHA-001 | **106 OHLCV technical variants**, BH-FDR(q=0.10) + Holm | 106 tests | — | — | **0 survivors**; best-of-N p = 0.29–0.77 |
| ALPHA-002 | TSMOM + funding/flow/positioning features | 582 and 1 188 trades | −0.39 / −1.10 bps | **−24.18 / −24.89 bps** | `NO_ALPHA_WITH_UNTESTED_HYPOTHESES`; both rejected |
| ALPHA-003 | BTC→ETH / BTC→SOL lead-lag, L1/L2, 5m/15m | 1 699 – 13 685 trades/cell | +1.87 … −0.58 bps | −21.9 … −24.4 bps | `NO_ALPHA` |

The pattern is identical across every one of them: **gross is a small number of bps, net is roughly minus the
toll.** That is the single most reproducible fact in this repository.

## 4. The standing economic gate

`data/economic001/EVIDENCE_CLOSURE.json` (`ECONOMIC-001`, HEAD `8e0a4b5f`) consolidates the cost evidence and
is the reason no campaign is authorised today:

| Family | Horizon | Median \|move\| | × frozen toll (23.8 bps) | Movement margin sufficient |
| --- | --- | --- | --- | --- |
| scalping | 5m | 8.59 bps | **0.36×** | false |
| intraday | 1h | 29.38 bps | **1.23×** | false |
| mean_reversion | 4h | 60.47 bps | **2.54×** | false |

`standing`: `PROFITABILITY_VERIFIED=false`, `TRADES_AUTHORIZED=0`, `LIVE_TRADING=DISABLED`,
`NEXT_CAMPAIGN=NOT_AUTHORIZED`, `FALSE_SUCCESS=0`, `builder_equals_verifier=false`. Open defect
`ECO-1` says the cost snapshot is a few seconds, not regimes; ST-6 partially closes it by accumulating
windows. That defect is the only measured quantity in this repository that is improving over time.

## 5. The negative-alpha registry (the do-not-repeat list)

`reports/alpha001/NEGATIVE_ALPHA_REGISTRY.md` is the authoritative list of falsified families and their reopen
conditions:

| id | Family | Observed | Reopen requires |
| --- | --- | --- | --- |
| NEG-A1-01 | technical TA (106 variants) | 0 BH/Holm survivors | NEW MECHANISM or MATERIAL NEW DATA |
| NEG-A1-02 | time-series momentum (spot + perp) | tradability FAIL; perp −563.80 bps | NEW EXTERNAL EVIDENCE |
| NEG-A1-03 | cross-sectional momentum | DEV +376.9 → VALIDATION −508.4 | NEW MECHANISM |
| NEG-A1-04 | cross-sectional reversal | **gross +15.71 ≤ cost 23.56** | **MATERIAL COST REDUCTION** |
| NEG-A1-05 | volatility magnitude | reproduces; **no direction** | NEW MECHANISM |
| NEG-A1-06 | funding / basis carry | `G_CARRY_2 FAIL` | **NEW DATA WINDOW** |
| NEG-A1-07 | liquidations / OI / order book | **DATA_BLOCKED / FORWARD_ONLY** | **PIT HISTORY EXISTS** |
| NEG-A1-08 | regime switching router | 0 trades; gate abstains | MUCH LARGER EVIDENCE VOLUME |
| NEG-A1-09 | ETF dual momentum | < risk-matched passive | NEW STRUCTURAL EDGE |

Two rows matter for the next experiment. `NEG-A1-04` says the best cross-sectional gross edge measured in
this repository is **+15.71 bps against a 23.56 bps toll**: a 1.50× shortfall that no amount of signal tuning
closes. `NEG-A1-07` is the only family whose failure was **data absence, not economics** — and it is the only
reopen condition (a point-in-time order-flow history) that this repository does not yet have.

## 6. What the inventory says

1. **Nothing in this checkout has a positive net expectancy after costs.** Four families, ~30 recorded arms,
   more than 30 000 trades once ALPHA-003's 5m cells are counted, every net negative; the two positive net
   results that appeared (003K `control` research +163.45 gross, EDGE-06 trend +230.02) were respectively
   cost-dominated and measured on an already-read window.
2. **The binding constraint is the toll, not the signal.** Best gross measured: 003N's
   `lane_a::trend::4h::48` at **14.80 bps in VAL against 27.31 bps**; ALPHA-003 lead-lag at 1.87 bps;
   ALPHA-002 at −0.39 bps. Only 4h median moves (60.47 bps) exceed the toll, and 4h *signals* capture only a
   quarter of that move.
3. **Three windows are spent:** `2026-08-06 → 2026-08-20` (K, twice), `2026-08-20 → 2026-10-18` (J/K real
   arm), `2026-03-01 → 2026-10-14` (EDGE-07). No confirmatory test can be built on any of them.
4. **The one open door is data, not strategy:** NEG-A1-07 reopens with a PIT order-flow history, and ST-6 has
   been collecting exactly that since `2026-10-08` (75 of 84 windows at the time of writing).
