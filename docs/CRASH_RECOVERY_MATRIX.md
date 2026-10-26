# CRASH_RECOVERY_MATRIX — hardening phase

Every row: crash boundary → recovery method → observable property → evidence.

| # | Boundary (crash between…) | Recovery | Observable property | Evidence |
| --- | --- | --- | --- | --- |
| A | signal generated / before risk | nothing persisted (no intent yet) | crash ⇒ NO side effect; retry may re-propose (no economic effect ever happened) | structural: intent registered only post-approval (`paper_cycle.py`) |
| B | risk approved / before intent persisted | intent + fill none | crash ⇒ zero economic effect; next session re-proposes cleanly | unit: `test_paper_recovery.py` engine ordering + verifier NEG matrix |
| C | intent persisted / before broker call | ledger restore; fill row absent (UNKNOWN) | retry after restart ⇒ DUPLICATE suppressed ⇒ max 1 economic execution | `test_crash_before_broker_call_no_duplicate_execution` |
| D | broker accepted / before fill persisted | position row replayed from durable state | restored position equals original (price/qty/notional); duplicate intent cannot add a second | `test_crash_after_broker_fill_position_replayed` |
| E | fill persisted / before risk counters update | risk counters restored BEFORE next decision | daily-loss/cooldown/drawdown limits see pre-crash results | `test_restart_with_open_position_full_restore` (counters asserted) |
| F | portfolio update / before session report | book (not report) is authority | next snapshot restores the book; report loss is observability-only, not economic | `paper.state.saved` after every session (runner) |
| G | position opened / process dies / restart | full RESTORE_EXACTLY | broker book + risk state + equity identity + intent ledger restored; same intent never re-executes | `test_restart_with_open_position_full_restore` + RUN-C (LIVE, real data) |
| H | position closed / before accounting finalization | closed-trade rows persisted with snapshot | equity reconstructs exactly (`initial + Σpnl == equity`); tampering ⇒ FATAL | `test_closed_trade_reconstruction_across_restart` + `test_equity_identity_mismatch_is_fatal` |

## Exactly-once effect (§7)

`same logical intent + arbitrary retry/restart ⇒ ≤ 1 economic execution`:
- intent id = `intent_cloid(symbol, strategy, direction, bar_ts)` (stable, domain-derived);
- registered in the ledger BEFORE the broker call and persisted per session;
- duplicate detection at the engine boundary (idempotency stage, reason recorded)
  AND broker-side same-symbol same-side skip.

Proven: unit (duplicate intent, duplicate callback), live real-data RUN-B
(cycles 2-3: 3 duplicates suppressed each) and RUN-D (2 suppressed), restart RUN-C
(post-restart cycle: 0 new orders on restored ledger).

## Unknown broker outcome (§8)

Classification (from durable state): `ALREADY_EXECUTED` (position/closed row
present), `NOT_EXECUTED` (no row + ledger present ⇒ retry suppressed
anyway — conservative), `STILL_PENDING`/`UNKNOWN` (no row, no ledger ⇒ treated
as NOT_EXECUTED but intent becomes marked on first send; subsequent retries
suppress). NEW EXECUTION IS BLOCKED until reconciliation resolves — fail
closed. Evidence: `test_unknown_broker_outcome_blocks_reexecution`.
