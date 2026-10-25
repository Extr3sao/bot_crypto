# STATE MACHINE — EXP-003P

> Generated from `src/trading_bot/paper/lifecycle/contracts.py`.

| from | allowed next states |
| --- | --- |
| `CREATED` | `RISK_REJECTED`, `SUBMITTING` |
| `SUBMITTING` | `ACKNOWLEDGED`, `REJECTED`, `UNKNOWN` |
| `ACKNOWLEDGED` | `CANCELED`, `EXPIRED`, `FILLED`, `PARTIALLY_FILLED`, `UNKNOWN` |
| `PARTIALLY_FILLED` | `CANCELED`, `EXPIRED`, `FILLED`, `UNKNOWN` |
| `UNKNOWN` | `ACKNOWLEDGED`, `CANCELED`, `FILLED`, `PARTIALLY_FILLED`, `REJECTED` |
| `RISK_REJECTED` **(terminal)** | — (terminal) |
| `FILLED` **(terminal)** | — (terminal) |
| `CANCELED` **(terminal)** | — (terminal) |
| `REJECTED` **(terminal)** | — (terminal) |
| `EXPIRED` **(terminal)** | — (terminal) |

## Reading rules

- `ACK != FILL`: only an event carrying a fill fact changes quantity.
- A fill that arrives before its acknowledgement is reported as `FILL_WITHOUT_ACK`; no ACK is invented to complete the sequence.
- Events are projected in `(event_time_utc, arrival order)`; a transport reorder is reported as `OUT_OF_ORDER_EVENT` and the raw event is preserved.
- A terminal order never reopens: a contradictory later event becomes `TERMINAL_STATE_MUTATION` and is not applied.
- `UNKNOWN` is not terminal. It blocks any further send for that intent until a primary source resolves it through `ORDER_STATE_RESOLVED`.
- `cum_filled_qty` is monotonic and bounded by the ordered quantity (`QUANTITY_EXCEEDED` otherwise).
