# RFC-PO-002 — Independent Verifier position in the paper runtime

Status: **ACCEPTED (design)** · Date: 2026-09-25 · Audit: session on HEAD `5e6f963`

## Context

Historical docs left two readings: (A) Decision → Risk → Execution → Verifier,
(B) Decision → Verifier → Risk → Execution. A post-execution-only verifier
cannot stop a trade; a non-deterministic verifier before Risk would put an
unaccountable component on the capital path.

## Decision

The runtime already implements the correct split, keep it and name it:

1. **PRE-EXECUTION VERIFICATION** = the deterministic gate chain inside
   `PaperCycleEngine` (context validation, PIT trim + validation, router
   decision validation, family/alpha validation, adapter validation,
   mandatory `RiskManager.check_signal` approval, idempotency). All
   failures reject with a recorded reason; nothing proceeds silently.
2. **EXECUTION** = `PaperBroker.execute_signal`, the only boundary, reached
   exclusively with risk-approved sizing (rebuilt frozen Signal).
3. **POST-EXECUTION VERIFICATION / RECONCILIATION** =
   `broker.reconcile_session` (fills, SL/TP, fees, PnL, equity identity,
   risk feedback) + startup reconciliation (GAP-R1 pending adoption).
4. **Independent verifier** = phase-level harness
   (`scripts/verify_l5_independent.py`), builder≠verifier at the phase
   boundary. It is NOT a runtime component and must never become one on the
   capital path.

## Consequences

- No new runtime component in this phase (§18).
- If an agent-critic layer is ever adopted, it sits strictly **before
  TradeProposal finalization**, emits structured critique only, holds no
  sizing/limit/authority, and its failure modes are fail-closed (critique
  unavailable ⇒ proceed with deterministic gates only, never ⇒ auto-approve).
- BUDGET-01 becomes a hard precondition for any such agent phase (GAP-R4).
