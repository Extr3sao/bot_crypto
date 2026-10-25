# Coverage matrix — RFC-TAP-EXEC-SEC-002

Code commit: `de72ad2a`. Verifier: `scripts/audit/verify_exec_sec.py` on a
`git archive` export. `calls` is the number of recording-broker calls.

## 1. Entrypoint → authorization → broker

| Entrypoint | Confirmation | Category (rule) | Stop | Gate | Payload guard | Broker calls (proven / rejected) | Evidence |
|---|---|---|---|---|---|---|---|
| `run --auto-trade --mode live` (futures OPEN) | `--confirm-live` required | `OPEN_OR_INCREASE` (R-OPEN) | yes | 10/10 | n/a | 1 / 0 | V-10, V-11, V-12, M1, M4 |
| `run --auto-trade --mode live` (spot buy) | `--confirm-live` required | `OPEN_OR_INCREASE` (R-SPOT-BUY) | yes | 10/10 | n/a | 1 / 0 | P0 probe, unit tests |
| `run --auto-trade --mode shadow_live` | `--confirm-live` required | same as live if the resolved mode is LIVE | yes | 10/10 | n/a | 0 when the resolved mode is not LIVE | REQ-01, `_cmd_run` guard |
| `run` stale-position flatten (`flash_close_position`) | inherited from the loop | `PROVEN_REDUCTION` (R-FLASH-CLOSE) with an observable position; `UNKNOWN` otherwise | not required for proven | not consulted for proven | yes (`{positionId}` only) | 1 / 0 | V-14, V-16 |
| `place-order` futures OPEN | `--confirm-live` required | `OPEN_OR_INCREASE` (R-OPEN) | yes | 10/10 | n/a | 1 / 0 | V-12, V-11 |
| `place-order` futures CLOSE + `--reduce-only` + matching one-way position | `--confirm-live` required | `PROVEN_REDUCTION` (R-REDUCE-ONLY) | not required | not consulted | yes (`reduceOnly`, `tradeSide`, side, qty, id) | 1 / 0 | V-14 |
| `place-order` futures CLOSE without `--reduce-only` | `--confirm-live` required | `UNKNOWN` (R-CLOSE-NO-REDUCE-ONLY) | yes | 10/10 | n/a | 0 / 0 | V-15, M7 |
| `place-order` futures CLOSE, no position / zero / excess / hedge / wrong side | `--confirm-live` required | `UNKNOWN` (R-CLOSE-*) | yes | 10/10 | n/a | 0 / 0 | V-15, M9, M10, M11 |
| `place-order` spot `sell` | `--confirm-live` required | `UNKNOWN` (R-SPOT-SELL-NO-VENUE-PROOF) | yes | 10/10 | n/a | 0 / 0 | V-15, M5 |
| `place-order` spot `buy` | `--confirm-live` required | `OPEN_OR_INCREASE` (R-SPOT-BUY) | yes | 10/10 | n/a | 1 / 0 | P0 probe |
| `close-position` with an observable position | none | `PROVEN_REDUCTION` (R-FLASH-CLOSE) | not required | not consulted | yes | 1 / 0 | V-14, V-16 |
| `close-position` without a position / stale snapshot | none | `UNKNOWN` (R-FLASH-NO-POSITION / R-FLASH-STALE) | yes | 10/10 | n/a | 0 / 0 | V-15, M12 |
| `set-tpsl` | none | `UNKNOWN` (R-TPSL-NOT-MONOTONIC) | yes | 10/10 | n/a | 1 only when all checks pass / 0 when any rejects | V-15, V-17, M6 |
| `run --demo` → `paper_cycle` | n/a | not classified | no | no | n/a | unchanged (G-4) | out of scope |
| direct call to `_live_order_boundary` (no CLI) | the sink re-checks the flag | derived | yes | yes | if proven | 0 without confirmation | V-03, V-04, M2, T11 |

`shadow_live` is included in the confirmation requirement because the dispatch
functions read `settings.runtime.mode`, not the CLI mode: a shadow process
pointed at a live `.env` can place orders.

## 2. Requirement → evidence

| Requirement | Implementation | Own unit tests | Program tests | Verifier |
|---|---|---|---|---|
| REQ-01 confirmation | `_cmd_run` guard; `intent.requires_confirmation` in the sink | `test_a_live_entrypoint_without_confirmation_never_reaches_the_gate` | `test_t01_*`, `test_t04_*` | V-05, V-06, V-10, V-19 |
| REQ-02 sink authority | `_live_order_boundary` (typed context, no defaults); `LiveOrderAuthorization` | boundary group | T02/T03/T11 | V-02, V-03, V-04, V-11, V-13 |
| REQ-03 classification | `classify_order` + `PositionState` + `VenueCapabilities` | 16 classifier tests | T05/T06/T08 | V-01, V-14, V-15 |
| REQ-03 payload proof | `reduction_payload_violations`, `payload_guard` in the adapter | 10 mutation cases + adapter ordering | T07 | V-07, V-16 |
| REQ-04 TP/SL | `R-TPSL-NOT-MONOTONIC` → `UNKNOWN` | `test_set_tpsl_is_never_a_proven_reduction` | T09 | V-15, V-17 |
| REQ-05 stop + trace | stop first for every non-proven order; `live_order_authorizations.jsonl` | `test_a_stop_engages_between_the_check_and_the_call`, `test_every_decision_is_recorded_without_secrets` | T10 | V-08, V-18 |
| ACC-06 regression | suites + mutation | — | 190 passed in the worktree | V-20, V-21 |
| ACC-07 separate verification | `verify_exec_sec.py` | — | — | 21/21 on the export |

## 3. What is not covered

- **Real venue acceptance.** Every broker is a recorder. The probe proves the
  payload the process *would* send, not that Bitunix accepts it.
- **Hedge mode.** Refused as `UNKNOWN`; no hedge-mode venue was exercised.
- **G-4 (`run --demo`)** still has no gate or stop; unchanged by this RFC.
- **DEF-P0-03** (`GATE-006` resolves SQLite against the cwd) and **GATE-009/010
  configuration** are untouched.
- **TOCTOU between position read and order.** The exemption does not rely on the
  snapshot alone: the venue enforces `reduceOnly` or closes by id. The snapshot
  only decides whether the proof is allowed to start.
