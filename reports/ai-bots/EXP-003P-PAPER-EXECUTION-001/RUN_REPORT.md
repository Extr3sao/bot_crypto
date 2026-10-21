# RUN REPORT — EXP-003P

- status: **PARTIAL**
- commit: `bdd96f4cf9eda379294d92282aa78707c669ffd5` (agent/ai-bots/RFC-TAP-AI-BOTS-003)
- config digest: `sha256:4f93519d8fc6b4040e82df6f6c495671ae5f510fe47ee246937a4400baa071fa`
- provenance: `OFFLINE_SIMULATED` only; live orders: `0`

## What ran

| phase | events | orders | fills | reconciliation |
| --- | --- | --- | --- | --- |
| runtime (real VisionLane + PaperBroker) | 276 | 69 | 69 | PASS |
| scenario (offline venue double) | 32 | 8 | 7 | PASS |

## Dimensions

| dimension | value |
| --- | --- |
| `IMPLEMENTATION` | `PASS` |
| `TESTS` | `PASS` |
| `OFFLINE_RUNTIME_VALIDATION` | `PASS` |
| `CLEAN_CHECKOUT_REPRODUCTION` | `PASS` |
| `CHECKOUT_ENVIRONMENT` | `PASS` |
| `PAPER_VALIDATION` | `BLOCKED_NOT_CONFIGURED` |
| `ECONOMIC_EDGE` | `NOT_EVALUATED` |
| `STRATEGY_PROMOTION` | `DENIED` |
| `INDEPENDENT_VERIFICATION` | `PARTIAL` |
| `FALSE_SUCCESS` | `0` |
| `LIVE` | `DISABLED` |

## Tests and controls

- tests: `PASS`
- controls: 17/17 effective
- verifier checks: 18/18 (failed: none)

## Latencies (from persisted event times)

- submit → ACK: `{'clock': 'event_time_utc of the persisted envelopes', 'max': 5, 'p50': 0, 'samples': 75, 'unit': 'ms'}`
- ACK → fill: `{'clock': 'event_time_utc of the persisted envelopes', 'max': 240, 'p50': 0, 'samples': 74, 'unit': 'ms'}`
- signal → intent: `NOT_AVAILABLE` (the broker does not publish a decision clock)

## Blockers

- PAPER_VALIDATION=BLOCKED_NOT_CONFIGURED: no authorised paper/testnet provider, endpoint or account is configured in this workspace, so no fill of this cycle was observed at a venue. The offline book is not a substitute.
- organizational_independence=false: producer, verifier and controls were written by one agent. The separation is between programs.
- Prospective status does not rest on a commit that predates the run: the artifacts are committed by the evidence commit, which follows the code commit the run binds. The preregistration is a frozen document (`PROTOCOL_FROZEN_UTC`), its digest is recorded in every run, and a clean checkout re-derives the identical file from the frozen constants.

## What this run does not mean

- `OFFLINE_RUNTIME_VALIDATION` is not paper trading and does not promote to `PAPER_VALIDATION`.
- No economic edge is measured: `ECONOMIC_EDGE=NOT_EVALUATED`.
- `STRATEGY_PROMOTION=DENIED`, `HOLDOUT=CLOSED`, `LIVE=DISABLED`.
