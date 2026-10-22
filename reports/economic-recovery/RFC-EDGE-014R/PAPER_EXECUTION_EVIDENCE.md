# WP-EDGE-14R — paper execution evidence

*Execution class `PAPER_REPLAY`. Dataset `sha256:c17c28bf5cb97e3b…`. False orders sent.*

historical bars driven through the canonical paper path; this is real execution of the runtime's code but NOT prospective observation, because every bar predates the run

## Arms

| arm | ledger | cycles | contexts | router no-trade | risk accepted | risk rejected | orders created | fills closed | realised pnl |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `GATE_INTACT` | committed | 879 | 1758 | 1758 | 0 | 0 | 0 | 0 | 0 |
| `SANDBOX_ADMISSION` | sandbox | 879 | 1758 | 0 | 1528 | 0 | 394 | 347 | -212.544674 |

## Reading

- the authoritative arm produced **0** fill(s) over 879 cycles: with the committed ledger the funnel stops at the router, before risk and before the broker, which is the gate working;
- the sandbox arm produced **347** fill(s) over 879 cycles, so the risk and broker boundary is reachable once a strategy is admitted;
- every fill is `HYPOTHETICAL_FILL` with `order_sent: false`; none of them is a PAPER_BROKER_FILL of the authoritative path, and none is an exchange order.

## Limitations

- a sandbox ledger is not an admission: the fills of the sandbox arm certify connectivity, never admissibility
- one dataset, two symbols, one timeframe, one family: enough to diagnose the path, not enough to infer an edge
- fills are modelled by PaperBroker at bar OHLC with its own slippage and commission, not by venue data
