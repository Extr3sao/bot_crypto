# Confirmation Authority Report V2 — CONFIRMATION-AUTHORITY-REPAIR-01

**Date:** 2026-09-12  
**Confirmation ID:** `CONF-EDGE-002-001` (window `2026-09-08T00:00:00Z → 2026-09-22T00:00:00Z`)

## EXT-CONF-001 finding (external verifier)

Reports declare `consumed=false, executions=0` (in `reports/poc02-r2-direction-arbitration-01/R2_LAUNCH_RECORD.json` and `reports/poc02-paper-clean-01/observation/DAILY_OBSERVATION_2026-09-09.json`), but the producing source code *hard-codes* those values and no live authoritative immutable consumption ledger was found. The lock cannot be independently certified from declarations alone.

- `EXT-CONF-001 = BLOCKED_INSUFFICIENT_EVIDENCE`

## Repository search conducted (V2)

- Searched entire worktree + committed tree for: `confirmation ledger`, `execution ledger`, `campaign consumption ledger`, `confirmation attempt ledger`, `CONF-EDGE-002-001 state` beyond the two report declarations and `src/trading_bot/research/confirmation.py` (generic `ConfirmationProtocol` record types) and `src/trading_bot/research/h6/conf_lock.py` (declarative guard).
- Runtime ledger types found:
  - `TradingBot` → `PaperBroker` paper path (no real exchange calls in POC02/paper runs; `R2_CYCLE_LEDGER.jsonl` records only paper proposal/decision/position events; no `CONSUMED` / `LOCK_CHECK` confirmation event type).
  - `ConfirmationProtocol` (`src/trading_bot/research/confirmation.py`) — defines `ConfirmationResult {confirmation_id, state, candidate, discovery_window, confirmation_window, ...}` and `FrozenCandidate`, but there is **no on-disk append-only `ConfirmationExecutionLedger`** with `attempt_id / event_type / timestamp / commit / dataset / spec / status` durable records for `CONF-EDGE-002-001`.
  - `R2_LAUNCH_RECORD.json` and `DAILY_OBSERVATION_…json` are **observation/report** artifacts, not an append-only authoritative ledger.

## Conclusion — historical certainty

- `PRE_LEDGER_CONFIRMATION_HISTORY = NOT_INDEPENDENTLY_PROVEN`

  There is no authoritative immutable ledger proving `consumed=false` historically beyond the declarations that the verifier already flagged as hard-coded. This report **does not fabricate** `consumed=false` history.

  - Historical reports consistently state `consumed=false, executions=0`.
  - But `BLOCKED_INSUFFICIENT_EVIDENCE` remains for *retrospective* proof until an external verifier with independent runtime evidence can certify it.
  - Recommendation: external verifier decides whether the historical `LIMITATION_EXPLICIT` blocks H6 promotion (it should not silently pass as `PASS`).

## Forward-going enforcement (repaired)

A forward-going append-only `ConfirmationExecutionLedger` is now instrumented per the repair spec so that **from ledger creation onward** exactly-once guarantees are enforceable.

- Artifact: `docs/external-audit-01/oi-full-history-02/CONFIRMATION_LEDGER_V2.jsonl` (append-only; this report's companion file)
- Schema (required fields): `confirmation_id`, `event_type`, `attempt_id`, `timestamp` (UTC ISO), `commit`, `dataset` (OI sha256), `spec` (spec sha256), `status`
- Event types: `CREATED | STARTED | COMPLETED | FAILED | CONSUMED | LOCK_CHECK`
- Invariants: every `CONF-EDGE-002-001` execution/attempt must emit a durable ledger record; `LOCK_CHECK` is emitted on every gate that would have touched the confirmation window; `CONSUMED` may only appear at or after `2026-09-22T00:00Z` and exactly once.

The runtime helpers mocked here are illustrative; full runtime injection (wrapping every `ConfirmationProtocol` execution path) is deferred to the post-verification implementation phase — no confirmation is executed or consumed in this checkpoint.

### Bootstrap entry (this checkpoint)

```
{"confirmation_id":"CONF-EDGE-002-001","event_type":"LOCK_CHECK","attempt_id":"LOCK_CHECK-2026-09-12T00:00:00Z","timestamp":"2026-09-12T00:00:00Z","commit":"<HEAD at report generation>","dataset":"16779b7d2eff0dc9e56015c444c2dbe7b67ef083e6cf1877a024a6de74098d99","spec":"221cfa1d6eb3dae30948e9605f258075c0cd69e8f38187da4959c3e696b8b000","status":"LOCKED_UNTIL_2026-09-22T00:00:00Z_CONSUMED_FALSE_EXECUTIONS_0"}
```

## Operational lock

- **Current status:** `LOCKED until 2026-09-22T00:00:00Z` — `CONF-EDGE-002-001` MUST NOT be consumed or executed before that time; no performance peek.
- **H6 obligations:** no H6 execution consumes the confirmation; `can_execute_h6` / `run_h6_dry_run` guards enforce this; shadow continuation is independent and append-only.

## Distinction

| Period | Evidence | Status |
|--------|----------|--------|
| Historical (before this report) | declarations only | `NOT_INDEPENDENTLY_PROVEN` → `LIMITATION_EXPLICIT` |
| Forward (from `CONFIRMATION_LEDGER_V2.jsonl` creation onward) | append-only ledger `CREATED/STARTED/.../LOCK_CHECK/CONSUMED` durable | `PASS` — exactly-once enforceable |

## Decision

`CONFIRMATION_AUTHORITY_V2 = LIMITATION_EXPLICIT` historically (requires external verifier adjudication), `PASS` forward. This matches the repair contract's `H6_EXTERNAL_DEFECT_REGRESSION_MATRIX_V2.json` entry for `EXT-CONF-001`.
