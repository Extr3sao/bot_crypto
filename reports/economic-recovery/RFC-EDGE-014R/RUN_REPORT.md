# WP-EDGE-14R — run report

*Generated 2026-10-16T21:20:55Z against `ee3922e9f8e8`. `FALSE_SUCCESS=0`, `BUILDER != VERIFIER`.*

## Execution classes, kept apart

| class | what it is | produced? |
| --- | --- | --- |
| `HISTORICAL_BACKTEST` | the frozen rule measured on frozen bars by four engines | yes |
| `PAPER_REPLAY` | historical bars driven through the runtime's own paper path | yes |
| `PROSPECTIVE_PAPER` | bars captured after every decision that used the exhausted window | **no** — captured and reserved, accruing |

A replay is not presented as prospective paper: every bar in it predates the run.

## P1 — the trade path

| stage | `GATE_INTACT` (authoritative) | `SANDBOX_ADMISSION` |
| --- | ---: | ---: |
| contexts built | 1758 | 1758 |
| router invocations | 1758 | 1758 |
| router no-trade | 1758 | 0 |
| risk accepted | 0 | 1528 |
| orders created | 0 | 394 |
| fills closed | 0 | 347 |
| realised PnL | 0 | -212.54467405113758 |

The one terminal cause is `1758 x NO_TRADE:no_strategy_passed_gates`:
the committed admission ledger admits nothing. The sandbox arm proves the rest of the path
is reachable once something is admitted; it is a connectivity certificate, never a
candidate.

Capacity: guardian **WARNING**,
`allows_new_decision` = **True**;
1823182848 bytes were recovered from regenerable caches and
scratch. No evidence artifact was deleted and no threshold was lowered.

## P2 — external engines, actually executed

| engine | outcome | trades | matched | count gap | matched residual (bps) | verdict |
| --- | --- | ---: | ---: | ---: | ---: | --- |
| `freqtrade` | EXECUTED | 44 | 44 | 0 | 0.010569 | AGREE_WITHIN_TOLERANCE |
| `jesse` | EXECUTED | 44 | 44 | 0 | 7.021359 | DIVERGENT |
| `vnpy_ctastrategy` | EXECUTED | 42 | 42 | 2 | 0.0 | AGREE_ON_MATCHED_TRADES_WITH_DECLARED_EXTRA |

Jesse consumes 1-minute source rows and generates the 1h bars itself; its source was
fetched for the same window and audited to aggregate onto the frozen bars exactly
(`identical_to_frozen_1h` = True).

## P4 — certification

- fee conventions reconciled: **True** (the per-trade identity
  holds on every engine to <1e-6 bps; the broker's own rule to <1e-9);
- adversarial suite: **10/10**
  executed cases pass, **0 declared-only**; the three formerly `POLICY_ASSERTED` cases are
  executed tests here;
- independent verification: **31/31** checks pass,
  verdict **VERIFIED**.

## P5 — economics

Six arms were scored in `ECONOMIC_COMPARISON.csv`; every one is **REJECT** or **DEFER**,
no arm reaches the ACTIVE target of three executed trades a day with a positive net, and
no arm was pushed to meet it.

## Open items

- none

The one accounting defect this package opened is closed, not absorbed:
`LEDGER_OPEN_CLOSE_RECONCILED` — the PAPER_REPLAY sandbox arm records 348 opened fills, 347 closed fills and 1 position still open when the replay ended.
How: an opening is identified by symbol, instant and execution price rather than by a timestamp two openings can share, and every close is drained from the broker's own closed-trades ledger, so the closes the engine performs inside its own cycle are recorded too.

## Limitations

- the frozen corpus is exhausted for selection; the prospective slice is small and cannot
  accept or reject anything yet;
- no engine's code enters this project; each ran in its own environment outside the
  checkout;
- the parity commission is a declared input, not a measured venue fee.
