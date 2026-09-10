# H3 EXECUTION FORENSICS — ATTEMPT RECONSTRUCTION (Track A)

Checkpoint: H3-GOVERNANCE-RECONCILIATION-AND-H5-SELECTION-01 · Date: 2026-09-10
Reconstructed by the agent that executed both invocations; cross-checked against
on-disk artifacts (`H3_EXECUTION_MARKER.json`, `H3_RESULT.json`, `H3_EXECUTION_LOG.md`)
and the code ordering of `scripts/h3_relative_value_discovery.py` at commit `4ea37b3`.

## Attempt records

| Field | Attempt 1 | Attempt 2 |
| --- | --- | --- |
| attempt_id | H3-RELVAL-BTCETH-BETANEUTRAL-SPREAD-01#a1 (reconstructed row) | …#a2 (reconstructed row, RECOVERY_OF a1) |
| experiment_id | H3-RELVAL-BTCETH-BETANEUTRAL-SPREAD-01 | same |
| started_at | ~2026-09-10T20:1xZ (pre-attempt-2; exact wall time not instrumented) | 2026-09-10T20:16:48Z (marker timestamp, first durable record) |
| prereg_commit | 83b3acde3dc4c45f9680ab9be2f0a72eeeddeb41 | same |
| code_commit | 4ea37b3 (working tree) | 4ea37b3 + uncommitted comprehension fix (committed as 8059ee9) |
| spec_sha256 | 90c56699…48d50 (runner gate verified both times) | same |
| dataset_sha256 | BTC 52a79db4… / ETH 2a913891… (committed frozen files) | same |
| simulation_started_at | yes (after sync audit + future-mutation test) | yes (same) |
| simulation_completed_at | yes | yes |
| metrics_computed | **yes** — features, trades (243), orthogonality replays, base B1 summarize(), prereg sensitivity (2.5/5/10) — crash hit INSIDE the cost-engine-table loop | re-computed in full |
| metrics_displayed | **no** — stdout empty (crash preceded all print statements) | yes (final summary line) |
| metrics_persisted | **no** — no file written | yes (H3_RESULT.json) |
| marker_created | **no** (marker writes only in the pre-result block, after the crashing loop) | yes (written before result) |
| result_created | **no** | yes |
| failure | UnboundLocalError: name 't' is not defined (cost_per_trade_R comprehension lacked its iteration clause), scripts/h3_relative_value_discovery.py:225 | none — COMPLETED |
| failure_timestamp | between the two run invocations (~20:1xZ, 2026-09-10) | n/a |
| parameter_changes_after_attempt | **none** — single-token comprehension-variable fix only; spec/dataset/mechanics/thresholds identical | n/a |
| final_status | FAILED (RESULT_COMPUTED_NOT_OBSERVED) | COMPLETED |

## A1 — Attempt 1 result exposure classification

**RESULT_COMPUTED_NOT_OBSERVED.** Evidence:

1. The crash traceback (`UnboundLocalError … line 225`) is inside the
   `cost_engine_verification` table construction — code that runs AFTER
   `simulate_pair`, `summarize`, `h3_classify` inputs, orthogonality replays
   and the prereg sensitivity dict are fully computed in memory.
2. stdout of attempt 1 was **empty** (the only print statements execute after
   result persistence); stderr contained only the traceback.
3. No marker, no result, no log rows, no temp files were written by attempt 1
   (`H3_EXECUTION_LOG.md` did not exist before attempt 2's write; dataset cache
   files predate both attempts and are read-only inputs).
4. No metrics value from attempt 1 was seen by the operator or displayed
   anywhere before attempt 2 ran.

## A2 — Exactly-once reconciliation

| Count | Value |
| --- | --- |
| ECONOMIC_EXPERIMENTS | **1** (one experiment identity, one preregistered spec+dataset) |
| EXECUTION_ATTEMPTS | **2** |
| COMPLETED_EXECUTIONS | **1** (attempt 2) |
| FAILED_EXECUTION_ATTEMPTS | **1** (attempt 1, recovery-linked) |

**CERTIFY_EXACTLY_ONCE_H3 = true.** Justification: attempt 1 never persisted any
output and was never observed; attempt 2 was a legitimate recovery under B2
semantics (identical spec sha256, dataset sha256, code mechanics and frozen
parameters — the only code delta was the crashing line's comprehension bug).
The economic evaluation is defined by the COMPLETED result, not by in-memory
computation that died with its process. Had attempt 1 persisted or displayed
any metric, this certification would be false — it did not.

**DEF-H3-EXEC-001 CONFIRMED (root cause: LATE_EXECUTION_MARKER).** The legacy
pattern wrote the exactly-once marker only after simulation+metrics, so a crash
in that window leaves no durable attempt trace. Repaired permanently by the
ResearchExecutionLedger (STARTED persisted + fsync'd BEFORE any economic work;
see `src/trading_bot/research/execution_ledger.py`, 7 adversarial unit tests).
