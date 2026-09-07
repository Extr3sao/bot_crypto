# RFC-CONFIRMATION-PROTOCOL-V2

Status: ACCEPTED (ex-ante — written BEFORE the confirmation window's data
became eligible; the manifest commit provably precedes `window_start`).

## Motivation

EDGE-RESEARCH-002-CONFIRMATION-01 returned `BLOCKED_CONFIRMATION_AUTHORITY`
(commit `a647dfb`): the confirmation window could not be proven to predate
the discovery results. This RFC fixes experiment governance so every future
confirmation has provable, pre-committed authority.

## Protocol

1. **Pre-registration.** A `ConfirmationManifest` (schema
   `confirmation-manifest-v2`) is committed to git BEFORE the confirmation
   window starts. Required proof, checked at verification time:

   ```text
   manifest_commit_time < confirmation_window_start < execution_time
   ```

2. **Window selection (ex-ante).** The window is the NEXT FUTURE complete
   UTC boundary boundary set at manifest creation:
   - `window_start` = next complete UTC midnight after the manifest commit;
   - `window_end`  = `window_start` + 14 complete UTC days.
   No window may ever be chosen or shortened after seeing any results.

3. **Minimum sample (ex-ante).** A confirmation run is decisive only when
   every candidate has **N >= 30 trades inside the confirmation window**.
   Fewer trades → `INSUFFICIENT_SAMPLE` (a valid, final result — no
   extension, no re-roll).

4. **Acceptance criteria (frozen).** The manifest carries the exact
   pre-registered acceptance rule; for the EDGE-RESEARCH-002 passers the
   frozen v2 criteria apply (net expectancy > 0, net PF > 1.0, thirds/halves
   sign-consistency, N >= 30, no parameter sweep, no direction change, no
   asset substitution). Criteria may never be edited after commit
   (manifest hash fails closed on tampering).

5. **Data authority.** Only candles with `window_start <= ts < window_end`
   are eligible. Discovery data, R1 confirmation/holdout, and EDGE windows
   are NOT reused. The dataset fingerprint is bound into the consumption
   receipt at execution.

6. **Single use.** Consumption is registered in a `ConfirmationRegistry`;
   a confirmation_id can be consumed exactly once. A consumed manifest can
   never authorize a second execution.

7. **Independent classification.** Every naturally generated verifier/risk
   rejection during confirmation must be classified
   `EXPECTED_FAIL_CLOSED` or `DEFECT` before results enter the registry.

## First authorized manifest

`CONF-EDGE-002-001` — window 2026-09-08T00:00Z → 2026-09-22T00:00Z,
candidates = the 3 EDGE-RESEARCH-002 discovery passers (SOL LONG
concentration 100% preserved), status COMMITTED, consumed=false.
Execution is NOT authorized in this checkpoint.
