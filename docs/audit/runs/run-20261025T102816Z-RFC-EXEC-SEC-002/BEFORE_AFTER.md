# Before / after — RFC-TAP-EXEC-SEC-002

The "before" column is not a recollection: `verify_exec_sec.py --rev 43e1ce2c`
was run against the clean pre-RFC commit and produced
[`verification-before.json`](verification-before.json) (8/21, `NOT_VERIFIED`).
The "after" column is the same verifier on the exported final commit
`09a44c21` (code `de72ad2a`) — 21/21,
`P0_ORDER_AUTHORIZATION_VERIFIED_SCOPED`.

## 1. What actually changed

| Property | Before `43e1ce2c` | After `09a44c21` (code `de72ad2a`) |
|---|---|---|
| `run --auto-trade` consent | no `--confirm-live`; live dispatch begins with no per-invocation consent | flag required for `live` and `shadow_live`; absent → exit 2 before the scanner |
| Reduction classification | caller boolean `opens_risk`; `trade_side=CLOSE` **or** `reduce_only` **or** `side=buy` decided it | derived from primitive + `tradeSide` + `reduceOnly` + position id/side/qty/mode/freshness + venue capability |
| Spot `sell` | exempt (gate skipped) | `UNKNOWN` → gate |
| `set-tpsl` | exempt (gate skipped) | `UNKNOWN` → gate |
| `close-position` | exempt by command name | `PROVEN_REDUCTION` only with an observable, fresh, non-zero position; otherwise `UNKNOWN` |
| `place-order` futures CLOSE | exempt if `--trade-side CLOSE` **or** `--reduce-only`, without looking at the position | exempt only with both, a matching one-way position, the closing side and `0 < qty <= position.qty` |
| Final wire payload | not re-checked after the decision | guard inside `place_order`/`flash_close_position`, immediately before `_request` |
| Audit trail | none | `live_order_authorizations.jsonl` per decision (category, rule, gate, fingerprint) |
| Stop priority | stop checked before the gate; reduction exempt | unchanged for openings; proven reductions bypass the stop by design |

`hot_stop.py`, `execution/live_gate.py` and the ten checks are unchanged.
`hot_stop.py` is byte-identical to `76cfca23…` (the G-1/G-2/G-3/P0 authority).

## 2. Measured scenarios

| Scenario | Before | After |
|---|---|---|
| `run` live auto-trade **without** confirmation | **exit 0, 1 broker call, scanner built, 2 clients** | **exit 2, 0 calls, 0 scanner, 0 clients** |
| `run` live auto-trade **with** confirmation and legal settings | flag rejected by argparse → exit 2, 0 calls | exit 0, 1 call |
| `run` with each of the ten checks rejected | not measurable: the flag did not exist, argparse refused first | 10/10 exit 2, 0 calls, gate id in stderr |
| `place-order` futures CLOSE, `reduceOnly`, long position, GATE-004 rejected | 1 call | 1 call (proven), payload carries `reduceOnly=true` |
| `place-order` futures CLOSE, **no position observable**, GATE-004 rejected | **1 call** | **0 calls, exit 2** |
| `place-order` futures CLOSE, **qty 0.5 > position 0.01**, GATE-004 rejected | **1 call** | **0 calls, exit 2** |
| `place-order` futures CLOSE, **hedge mode**, GATE-004 rejected | **1 call** | **0 calls, exit 2** |
| `place-order` futures CLOSE, **buy against a long**, GATE-004 rejected | **1 call** | **0 calls, exit 2** |
| `place-order` spot `sell`, GATE-004 rejected | **1 call** | **0 calls, exit 2** |
| `set-tpsl`, GATE-004 rejected | **1 call** | **0 calls, exit 2** |
| `set-tpsl`, all checks pass | 1 call | 1 call |
| `close-position` with a position, GATE-004 rejected | 1 call | 1 call |
| `close-position` with a position, stopped | 1 call | 1 call (emergency flatten preserved) |
| `run` under a stop with confirmation | flag rejected; not measurable | exit 0, 0 calls (G-3 skip preserved) |
| **Drop `reduceOnly` from the final payload** | **1 call** | **0 calls, exit 2** |
| **Inject `side`/`qty` into the flash-close payload** | **1 call** | **0 calls, exit 2** |
| `paper --auto-trade` without confirmation | exit 0 | exit 0 (not blocked by the flag) |

The two payload rows are the ones P0 could not see: the exemption was decided
before the adapter built the wire payload, so a payload that no longer carried
its proof still reached the broker.

## 3. Why V-11 "passes" on the before tree

On `43e1ce2c` the `run --confirm-live` scenarios exit 2 because **argparse does
not know the flag**, not because the gate refuses. The verifier's positive
control (`run_legal`, V-12) is red for that reason. The gate rows are only
meaningful after V-06 (the parser declares the flag) and V-12 (the positive
control reaches the broker) pass. The overall before verdict is `NOT_VERIFIED`;
no individual row is promoted to a pass.

## 4. Behaviour changes an operator will notice

1. `run --mode live --auto-trade` now needs `--confirm-live`; scripts without it
   exit 2 and do nothing.
2. `set-tpsl` no longer works when the gate rejects. That is REQ-04: the adapter
   cannot prove a TP/SL change tightens protection, because
   `get_pending_positions` does not return the live levels.
3. `set-tpsl` and a spot `sell` are refused while the hot stop is engaged. They
   were exempt under P0; under the RFC they are `UNKNOWN` and take the same
   controls as an entry. A **proven** close (`close-position`, `reduceOnly`
   CLOSE) remains available.
4. `place-order --trade-side CLOSE` without `--reduce-only` no longer skips the
   gate.
5. `place-order` futures CLOSE now performs one read-only
   `get_pending_positions` call to observe the position it claims to reduce.

None of these changes market logic, sizing, strategy or the gate's ten checks.
