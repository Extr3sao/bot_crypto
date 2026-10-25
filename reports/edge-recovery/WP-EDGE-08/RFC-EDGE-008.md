# RFC-EDGE-008 — alpha on an unread cross-section, with ACTIVE and QUALITY kept apart

*Status: **executing**. Work packages `WP-EDGE-08A` … `WP-EDGE-08F`. Nothing in this document
promotes a strategy, sizes a position or enables trading: `promotion: NONE`, `order_sent: false`.*

---

## 1. What the previous work package left on the table

WP-EDGE-07 measured the thing this project had been guessing at: the **cost barrier**, on the real
bars. A round trip costs **23.79 bps** on `COST_MODEL_V3` at `BINANCE_SPOT_STANDARD_TAKER`, and the
fraction of the open-to-open move a *perfect* direction call would have to capture merely to break
even is, on the window nobody had read:

| Holding horizon | Trades/day (3 assets) | BTC | ETH | SOL |
| --- | --- | --- | --- | --- |
| 1 h | 72 | 86 % | 67 % | 58 % |
| 4 h | 18 | 43 % | 33 % | 28 % |
| 24 h | 3 | 16 % | 12 % | 11 % |

Two conclusions, both of them actionable:

1. **An hourly book is closed by arithmetic, not by a bad candidate.** Both ACTIVE candidates
   WP-EDGE-07 registered lost money *before any fee* and captured ≈0 % of the move.
2. **The daily clock is not closed.** At a day's hold the requirement drops to 11–16 %, and the
   frozen daily trend book's problem was never cost — it was sample size.

WP-EDGE-07 wrote that down as a *proposal* (`FINDINGS.md` §4, `P-ACTIVE-DAILY`) and stopped there,
because a structure that would have helped is a new registration, never an edit. This RFC is that
registration, with one addition the earlier packages could not make.

## 2. The resource that is still unread

Every **time-based** resource of the BTC/ETH/SOL universe has been spent: the `trend` OOS window
(2025-01-01 … 2026-02-28) was consulted by WP-EDGE-01 and again by WP-EDGE-02, and WP-EDGE-07's
`NEW_HOLDOUT` (2026-03-01 … 2026-10-14) was read once and is spent. Reusing any of them would be
reading a window whose outcome is already known.

What has never been read is the **symbol dimension**. Six liquid Binance spot majors — **AAVE, UNI,
KSM, SNX, CRV, SUSHI** — have no bar anywhere in this repository's corpora and no committed
artefact has ever been measured on them. Their history, 2021-01-01 to the last closed hour, is the
evidence: fetched once from public Binance REST into `data/edge08/universe-1h/`, one SHA-256 per
shard, gaps left absent, and the disjointness claim checked by the fetch script and re-checked by
the verifier from disk.

The universe itself was fixed before the registration was committed, and the way it was fixed is
part of the record: `MKRUSDT` was in the first draft and was dropped by the fetch script's own
coverage pre-check, because MKR stops trading on 2025-09-15 (the SKY migration) and cannot cover the
decisive window. `KSMUSDT` took its place. No strategy had touched a bar at that point: the check
reads coverage, not outcomes.

This buys the property the earlier packages could not have: **a transfer test**. A book whose
parameters were frozen on BTC/ETH/SOL is measured on six names it has never seen, over a period
none of them has been read for. If a "trend edge" is a property of three instruments rather than of
markets, a cross-section is where that shows up.

## 3. Two tracks, kept apart

| Track | Clock | Shape | Its own target |
| --- | --- | --- | --- |
| **QUALITY** | daily | holds of days to weeks, few trades, a large objective per trade | net expectancy after costs, measured at a frequency floor (≥ 0.05 trades/day across the universe) |
| **ACTIVE** | 1 h entry, multi-day holds | aims at the mission's three trades a day *across* the universe | net expectancy after costs **and** the frequency, in that order of priority |

They are separate because the arithmetic that closes one opens the other. A single blended "strategy
search" would average a book that cannot pay its costs against a book that cannot reach a sample,
and call the mean a result.

Six books are registered — three of each — each with a documented prior, and every parameter is
hashed into `PREREGISTRATION.json` before anything is measured:

* **Q-1** `edge08_quality_breakout_daily` — 20-day Donchian breakout under the frozen 200-day EMA,
  2 ATR stop, 6 ATR objective, 4 ATR trail.
* **Q-2** `edge08_quality_pullback_daily` — the cheaper entry into an uptrend: EMA(50) > EMA(200)
  and the close half an ATR below the 20-day EMA, 2.5 ATR stop, 3 ATR objective.
* **Q-3** `edge08_quality_reversion_daily` — two standard deviations below the 20-day mean, but
  only when the 50- and 200-day EMAs are within one per cent of each other; the objective is the
  mean and the cost gate decides which stretches are worth paying for.
* **A-1** `edge08_active_daybreak_1h` — break of the prior 24 hours' high above the 200-hour mean,
  with a thrust requirement, 2 ATR stop, 4 ATR objective, trailed.
* **A-2** `edge08_active_stretch_revert_1h` — two and a half ranges below the two-day mean, target
  the mean.
* **A-3** `edge08_active_multiday_range_1h` — break of a *compressed* three-day range (its whole
  span at most six ATRs), above the 200-hour mean.

Plus three **CURRENT** arms — `edge_trend_01_4h`, `edge06_trend_fixed`, `edge07_active_thrust` —
read on the same corpus, window, costs, risk policy and simulator, so the comparison the mission
asks for is a comparison of books and not of accounting. Multiplicity: **9 arms**, all reported.

## 4. The gate sequence, fixed in advance

1. **Gross screen (C0)**, on the *known* universe's DEV window: gross expectancy > 0. A setup that
   loses before any fee cannot be repaired by a fee, so a book that fails C0 is **not read on the
   cross-section at all** — its holdout rows are absent, not zero. This is the rule WP-EDGE-07 Track
   C wrote down, kept unchanged.
2. **Economic matrix** on the known universe: every window, every cost scenario, with the
   block-bootstrap interval, the three time blocks, per-asset and per-market-context breakdowns,
   leave-out-largest, serial dependence and cost sensitivity.
3. **Cross-section validation**: the registered criteria (P1–P6, R1, R2, S1, plus the track's own
   frequency criterion) applied once, on the decisive window, to every book that cleared C0. The
   verdict is `ADMIT_PAPER`, `REJECT` or `INSUFFICIENT_EVIDENCE`, and an admission means a paper
   lane and nothing else.
4. **Independent verification** with its own sabotage self-test, and the reports.

## 5. The work packages

| WP | What it delivers | Artefacts |
| --- | --- | --- |
| **08A** | the registration, and the unread cross-section with its provenance and its disjointness proof | `RFC-EDGE-008.md`, `PREREGISTRATION.{json,md}`, `UNIVERSE.{json,md}`, `data/edge08/universe-1h/` + `_FETCH_MANIFEST.json` |
| **08B** | the QUALITY track: three books, screened for gross edge and measured for frequency on the known universe | `quality/QUALITY_SCREEN.{json,md}`, `quality/QUALITY_TRADES.csv` |
| **08C** | the ACTIVE track: three books on a clock the barrier can pay, screened the same way, with the frequency reading front and centre | `active/ACTIVE_SCREEN.{json,md}`, `active/ACTIVE_TRADES.csv` |
| **08D** | the economic matrix: 9 arms × 3 windows × 3 scenarios, with robustness and cost sensitivity | `economics/ECONOMIC_MATRIX.{json,md}`, `economics/ECONOMIC_TRADES.csv` |
| **08E** | the cross-section verdicts, per book, with the frozen gate reported beside them | `validation/VALIDATION.{json,md}`, `validation/GATE_STATUS.{json,md}`, `validation/HOLDOUT_TRADES.csv` |
| **08F** | independent verification with sabotages, the regression self-test, and the reports | `VERIFICATION.{json,md}`, `RUN_REPORT.{json,md}`, `FINAL_REPORT.md`, `INFORME_EJECUTIVO.md`, `GITHUB_STATE.json` |

## 6. What this RFC does not do

- It does not change a risk limit, a position size, a cooldown or the drawdown halt; every book is
  sized by `config/risk.yaml` through the frozen campaign's own risk policy.
- It does not enable trading of any kind, and no credential is read, stored or printed.
- It does not re-open a spent window: the cross-section's history is read once, and a book that
  fails is reported with its numbers rather than tuned and re-run.
- It does not claim that a transfer across six names proves generality. It measures six names, and
  says so.
