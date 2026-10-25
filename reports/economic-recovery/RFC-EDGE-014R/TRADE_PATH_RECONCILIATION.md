# WP-EDGE-14R/P1 — trade path reconciliation

*Two recordings of one pipeline. Only one of them has a ledger at every stage, and it
says where the funnel stops.*

## The stop

| stage | authoritative arm (`GATE_INTACT`) | evidence |
| --- | --- | --- |
| MARKET_DATA | 1758 symbol-contexts built over 879 cycles | observed |
| SIGNAL | 0 signals | observed |
| TRADE_PROPOSAL | 0 proposals | observed |
| ROUTER | 1758 invocations, all NO_TRADE | observed |
| DETERMINISTIC_RISK | 0 decisions | observed |
| PAPER_BROKER | 0 orders | observed |
| FILL_LEDGER | 0 closed fills | observed |
| RECONCILIATION | 879 cycles reconciled | observed |

The single terminal cause is `1758 x NO_TRADE:no_strategy_passed_gates`:
`config/strategy_admission.json` admits nothing, so the router refuses before sizing.
That is the capital gate working. It is not a broken stage.

## The same path, with an admitted strategy

Placed in this package's scratch directory, a declared sandbox ledger admitting one
family drives the same canonical pipeline:

| stage | sandbox arm | count |
| --- | --- | ---: |
| ROUTER | invocations | 1758 |
| DETERMINISTIC_RISK | accepted + rejected | 1528 |
| PAPER_BROKER | orders created | 394 |
| FILL_LEDGER | fills closed | 347 |

Final broker equity 9787.46 from
10000 (realised PnL -212.5447).
Connectivity is certified by this arm and admissibility is certified by no arm.

## The CAP-004 real-decision path

Four sealed decisions, one directional, **no** paper order, **no** exchange order. It is
reconciled here rather than reinterpreted: that path writes decision and outcome records
but no order-intent, router or broker record, so its middle is unobserved. `0` there is a
**weak zero** — nothing would have recorded an intent had one existed — and it is never
presented as evidence that the runtime chose not to trade.

## Capacity

- guardian status **WARNING**, free **3.9506 GiB**
  (critical threshold 2 GiB,
  healthy 5 GiB);
- `allows_new_decision` = **True** — the earlier
  `NO_NEW_DECISION_DISK_CRITICAL` refusals are gone because space was recovered, not
  because the guard was relaxed;
- reclaimed: 1823182848 bytes from regenerable caches and scratch
  (pip cache, bytecode caches, pytest scratch, type-check cache, re-fetchable clones). No
  evidence artifact was deleted and no limit was lowered.

## What this file does not claim

- it does not claim the paper path has an edge: it certifies that the path runs;
- it does not present a replay as prospective paper: every bar predates the run;
- it does not turn an absent ledger into a zero.
