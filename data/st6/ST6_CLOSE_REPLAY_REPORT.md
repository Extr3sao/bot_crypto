# ST-6 — isolated close replay

Generated 2026-10-09T07:59:59Z at `9eb1e464cf8b090af222127153e33f6ea6e1e949`.

Inside the sandbox the tick records the code identity as `REPLAY_SANDBOX_NOT_A_COMMIT`:
a constant on purpose, so the determinism proof does not depend on the commit hash.

Replay of `scripts/st6_forward_regime.py` against an isolated copy of the live state, with an injected
UTC clock. Period `2026-10-08T16:21:20Z` → `2026-10-22T16:21:20Z`; close instant `2026-10-22T16:21:20Z`.

**Close mechanics: PASS** — 10/10 scenarios PASS, 0 FAIL, 0 declared deviation(s).

## Scenarios

| # | scenario | verdict |
| --- | --- | --- |
| | 1. a tick before the close, in an already observed slot | **PASS** |
| | 2. the last eligible slot, and the boundary slot the period closes inside | **PASS** |
| | 3. the exact close instant | **PASS** |
| | 4. and 5. a tick after the close, and repeated execution after the close | **PASS** |
| | 6. unattended windows | **PASS** |
| | 7. concurrent execution | **PASS** |
| | 8. corrupt data and duplication | **PASS** |
| | 9. missing evidence | **PASS** |
| | 10. recovery after a host restart | **PASS** |
| | 11. the declared extension policy against the shipped flag | **PASS** |

## Isolation and non-interference

Sandboxes: `C:\Users\GVLLFR~1\AppData\Local\Temp\st6-close-replay-v5nq3157` (a temporary directory outside the
repository). Real state unmoved by the replay: **True** (identical bytes before and after: True)

Real market requests: 0. Real scheduler calls: 0. Market attempts refused by the guard: 2. Terminal transitions intercepted: 6.

## Declared boundary deviations

### BOUNDARY-SLOT-DUE-RULE

- contract: the plan is 84 windows counted from the slot that contains the period start; the partial slot the period closes inside (2026-10-22 16:00-16:21:20Z) is *not* a planned window: 'nothing may be expected, missed or penalised there'
- shipped behaviour: the due rule is 'this slot has no window yet', which is not bounded by the declared plan; a scheduled tick between 16:00Z and the close would attempt to collect a window in the undeclared boundary slot (and would sample it, since the attempt is only refused here by the replay's market guard)
- minimal correction: in the due path, collect only when the current slot's key is in the declared plan, i.e. `this_slot in {slot['key'] for slot in declared_slots_upto(period, parse(period['ends_at_utc']))}`, and otherwise record the existing SKIPPED_NO_WINDOW_DUE token with no market request
- effect on collected evidence: none: no window, no observation and no hash changes

### EXTENSION-FLAG-INERT

- contract: the period file declares: 'after ends_at_utc collection stops unless a human passes --authorize-extension, and that flag never turns an incomplete period into a PASS'
- shipped behaviour: the ended branch returns before the collection branch, so the flag cannot extend anything; and the collection branch is itself guarded by `not args.authorize_extension`, so passing the flag during the open period suppresses collection and turns the tick into a report-only run
- minimal correction: either honour the flag in a guarded branch (`if ended and not args.authorize_extension:` consolidate; else collect), keeping the 'never turns an incomplete period into a PASS' rule, or amend the declared text to state that the period never extends
- effect on collected evidence: none: no window, no observation and no hash changes

## What the replay does not claim

- it does not sample the market: a slot that is due is recorded as *refused by the guard*,
  never filled with invented evidence;
- it does not run the delegated verifiers inside the sandbox: the delegation is intercepted
  and recorded (`NOT_EXECUTED_IN_REPLAY`), so a sandbox run event never claims a
  verification that did not run;
- it is not evidence about the real period: the real period closes on its own date, and the
  consolidation of the real period is produced by the tick, then verified independently.

Research only: no orders, no credentials, no capital.
