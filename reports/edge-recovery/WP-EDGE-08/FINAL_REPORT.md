# WP-EDGE-08 — final report

*One reading of the whole package at `2026-10-14T21:42:44Z` (`EDGE08-REPORT-20261014T214244Z`). Every figure below comes from that reading; the four documents are rendered from one dictionary, so they cannot disagree with each other.*

## 1. The verdict

**`CLOSED_WITH_OPEN_ITEMS`** — the cross-section was read once, every arm the screen let through is rejected on it, the gate status is published, the verification passes with its sabotage self-test, and the open items are the ones the numbers point at.

The resource read here was the one thing this project had not spent: a **cross-section** of ['AAVEUSDT', 'UNIUSDT', 'KSMUSDT', 'SNXUSDT', 'CRVUSDT', 'SUSHIUSDT'], whose bar history no committed artefact had ever measured. It was read once, by three books that had cleared the gross screen, against criteria registered before the first bar of it was aggregated.

| Arm | Track | Verdict | Failed criteria | Cross trades | Cross net (USDT) | Cross trades/day |
| --- | --- | --- | --- | --- | --- | --- |
| `edge08_quality_breakout_daily` | QUALITY | **REJECT** | P2, P3, P4, P5, P6, R1, R2, S1, F2 | 30 | -166.6146 | 0.0461 |
| `edge08_quality_pullback_daily` | QUALITY | **REJECT_NO_GROSS_EDGE** | C0 | not read | not read | — |
| `edge08_quality_reversion_daily` | QUALITY | **REJECT_NO_GROSS_EDGE** | C0 | not read | not read | — |
| `edge08_active_daybreak_1h` | ACTIVE | **REJECT** | P2, P3, P4, P5, P6, R1, R2, F1 | 103 | -474.0861 | 0.1581 |
| `edge08_active_multiday_range_1h` | ACTIVE | **REJECT** | P2, P3, P4, P5, R1, R2, S1, F1 | 128 | -494.7063 | 0.1965 |
| `edge08_active_stretch_revert_1h` | ACTIVE | **REJECT_NO_GROSS_EDGE** | C0 | not read | not read | — |
| `edge06_trend_fixed` | CURRENT | **NOT_APPLICABLE** | — | 144 | -415.825 | 0.2211 |
| `edge07_active_thrust` | CURRENT | **NOT_APPLICABLE** | — | 196 | -350.7431 | 0.3009 |
| `edge_trend_01_4h` | CURRENT | **NOT_APPLICABLE** | — | 126 | -215.8994 | 0.1934 |

## 2. What the cross-section said

- `edge08_quality_breakout_daily`
- `edge08_active_daybreak_1h`
- `edge08_active_multiday_range_1h`

All of them lost money on it. The sharpest case is the daily breakout: on the screening ground (BTC/ETH/SOL, a universe every earlier work package has read) it earned 924.1688 USDT at DEV, and on six names it had never seen its entry lost money **before any fee** — the S1 criterion exists precisely to catch that, and it fired.

## 3. The two tracks, kept apart

| Track | Clock | Registered target | Measured on the cross-section |
| --- | --- | --- | --- |
| QUALITY | daily | ≥ 0.05 trades/day | REJECT — 0.046/day, below its own floor |
| ACTIVE | 1 h entries, multi-day holds | ≥ 3.0 trades/day | 0.16 and 0.20 trades/day; rejected with power (103 and 128 trades) |

Neither track reached its frequency target, and neither reached positive expectancy. Both facts are measurements, not opinions: no trade was forced and no filter was loosened.

## 4. The comparison, on the same corpus

| Group | Arm | Known net (DEV) | Cross net (OOS) | Cross trades | Cross trades/day |
| --- | --- | --- | --- | --- | --- |
| QUALITY | `edge08_quality_breakout_daily` | 924.1688 | -166.6146 | 30 | 0.0461 |
| QUALITY | `edge08_quality_pullback_daily` | -378.976 | not read | — | — |
| QUALITY | `edge08_quality_reversion_daily` | 0 | not read | — | — |
| ACTIVE | `edge08_active_daybreak_1h` | 18.9021 | -474.0861 | 103 | 0.1581 |
| ACTIVE | `edge08_active_multiday_range_1h` | 238.7233 | -494.7063 | 128 | 0.1965 |
| ACTIVE | `edge08_active_stretch_revert_1h` | -314.0392 | not read | — | — |
| CURRENT | `edge06_trend_fixed` | 470.1555 | -415.825 | 144 | 0.2211 |
| CURRENT | `edge07_active_thrust` | -440.9027 | -350.7431 | 196 | 0.3009 |
| CURRENT | `edge_trend_01_4h` | 572.9393 | -215.8994 | 126 | 0.1934 |

The CURRENT books were read on the identical corpus for the comparison: they lose too, and on every window. That is the honest baseline this package delivers — not that a new book beat the old ones, but that neither the old nor the new books survive a universe they were not chosen on.

## 5. Gates

`validation/GATE_STATUS.{json,md}` lists 9 arms with their registered verdict beside the frozen gate's own reading. No arm is `ADMIT_PAPER`, so nothing moves towards paper, and nothing moves towards live.

## 6. Verification

- verifier **PASS**, 14/14 checks;
- sabotage self-test **PASS**, 14/14 tampered inputs detected;
- the owned tests, the linter, the formatter and the type checker run from the run report;
- every artefact's digest is published in the run report, with the files this script writes excluded by name.

## 7. Defects found by running, and fixed

- `DEF-EDGE08-01` (QUALITY and ACTIVE) — two registered QUALITY books produced no trades at all on the screening ground: edge08_quality_pullback_daily and edge08_quality_reversion_daily could not fire, the second of them on any bar of a three-year corpus. → the reward/risk of both books was made satisfiable by design rather than by weakening a gate: Q-2 moved to a 2.0 ATR stop against a 3.0 ATR objective (R:R 1.5) and Q-3 to an ATR-denominated dislocation (entry at least 3.0 ATR below the 20-day mean, 2.0 ATR stop, objective the mean), both with min_rr = cost_margin = 1.5, so the gate judges each setup instead of refusing the book.

## 8. Open items

- no book transfers to the unread cross-section: the daily breakout is the sharpest case, positive on BTC/ETH/SOL and negative *gross* on six names it had never seen - a new registration, on a different structure, is the only honest way forward — *quant-researcher: a new pre-registration*
- the ACTIVE target of three trades a day is not reached by any registered book (0.16-0.20 a day measured): with the capture fraction the barrier table demands at 24 h, the frequency question is a strategy question on a slower clock, not a filter to loosen — *quant-researcher: a slower clock or a different universe*
- the quality reversion book is structurally empty on this tape: 66 dislocations on the screening ground, every one of them outside the range-bound regime it requires - the two conditions never co-occur — *quant-researcher: separate the regime and the dislocation, or drop it*
- the cross-section is six symbols: a transfer test across six names is evidence about those names, not a general law - a second cross-section, registered the same way, is the natural next step — *context-engineer then quant-researcher*

## 9. What this does not do

- It does not declare profitability, `PAPER_READY` or `PASS`: `promotion: NONE`, `order_sent: False`.
- It does not re-read a spent window: the WP-EDGE-07 holdout is not part of any criterion, and the cross-section was read once.
- It does not touch a risk limit: `config/risk.yaml` (digest `3c27c866d5f11afe…`) is read, never written.
- It does not claim a general law from six symbols.
