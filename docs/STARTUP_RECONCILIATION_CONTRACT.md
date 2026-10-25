# STARTUP_RECONCILIATION_CONTRACT — V4 (GAP-R1)

Status: IMPLEMENTED + EXECUTED (RUN-C, real restart with recovered book)
Commits: `daf54af` (implementation) · `c21a44a` (exposure sync)
Components: `paper/paper_state_store.py`, `paper/reconciliation_v4.py`,
`paper/paper_runtime_state.py`, wiring in `scripts/start_paper_trading.py`.

## The nine deterministic questions

| Question | Source of truth |
| --- | --- |
| What did we intend? | `sent_intents` ledger (`paper_cycle.intent_cloid` cloids) |
| What did we send? | same ledger (registered BEFORE the broker call) |
| What was accepted? | `open_positions` + `closed_trades` durable rows |
| What was filled? | those rows (entry price, qty, notional, fees) |
| What position should exist? | recomputed from durable rows at load |
| What position is recorded? | in-memory `PaperBroker` after restore |
| What balance should exist? | `initial_equity + Σ closed.pnl` |
| What balance is recorded? | `broker.equity` (identity enforced) |
| What remains unresolved? | any status below ≠ CONSISTENT/RECOVERED |

## Persisted state (WHAT/WHERE/WHEN/IDENTIFIER/GUARANTEE)

- WHERE: one JSON file, default `data/storage/paper_state.json`
  (`--state-path` / `PAPER_STATE_PATH` override).
- WHEN: after every session (runner `paper.state.saved`) + final finally
  snapshot. Crash window ≤ one session.
- IDENTIFIER: economic intents as `PAPER-<sha256(symbol,strategy,direction,bar_ts)>`
  cloids; positions keyed by symbol; state stamped with `run_id` + `updated_at_ms`.
- GUARANTEE: atomic write (tmp + fsync + rename). A reader sees either the
  last complete state or `CorruptStateFile` — never a partial book.

## Statuses (inconsistency is NEVER normalized)

| Status | Meaning | Runtime behavior |
| --- | --- | --- |
| `CONSISTENT` | no persisted state (fresh book) | start normally |
| `RECOVERED` | book restored, equity identity holds | resume; restored ledger active |
| `MISMATCH` | persisted book violates `initial + Σpnl == equity` | refuse to start (today: fatal) |
| `FATAL` | corrupt/unreadable file or failed restore step | refuse to start; `.corrupt` backup preserved |

`PARTIAL_RECOVERY ≠ RECOVERED`: any restore failure yields `FATAL`.

## Recovery policies

- RESTORE_EXACTLY (default): the durable book is replayed into
  `PaperBroker` + `RiskManager` (counters BEFORE any new `check_signal`)
  + `IdempotencyGuard` ledger.
- Exposure visibility (PORTFOLIO-CONTEXT-01): `_sync_risk_equity` mirrors
  the real broker positions into `risk.open_positions` each cycle, so
  `max_open_positions` and the exposure clamp act on the restored book
  (demonstrated live: `risk_rejected=3 reason="Max open positions reached (3)"`).
- UNKNOWN broker outcome (crash between intent registration and fill
  persistence): the ledger marks the intent as sent; a retry is a
  DUPLICATE → suppressed. Re-execution requires the durable position row;
  blind resend is impossible by construction.
- `--fresh`: EXPLICIT rotation to `<name>.<ts>.bak` (economic history is
  never silently destroyed).

## Explicitly out of scope (recorded, not hidden)

- `MISMATCH` currently aborts (no auto-repair path); repairing a tampered
  book is a human/post-mortem action by design.
- No replay-by-`run_id` API yet (deterministic engine + fingerprints make
  it feasible; deferred P2).
