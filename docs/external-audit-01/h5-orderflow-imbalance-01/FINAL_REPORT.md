# FINAL REPORT — H5-RESULT-INTEGRITY-RECONCILIATION-02

Date: 2026-09-11 · Actor: buffy-agent (Freebuff) · Branch: `feat/ma-2-specialist-opportunity-swarm` (HEAD `cb3de4f`)
Supersedes: `H5_PREREG_RESTORATION_BLOCKED_REPORT.json` (STATUS `BLOCKED_PREREG_AUTHORITY` from the prior blocked run)

---

## STATUS

**PASS**

(All unblocked phases completed and verified. P12/P13 remain WAIT by governance design —
early resolution of either would itself be a violation. `FALSE_SUCCESS = 0`. A final
STATUS of `BLOCKED_PREREG_AUTHORITY` is explicitly no longer applicable: the authority
was recovered and the restoration verified byte-identical.)

---

## 1. Prereg authority recovered (P0–P3)

| Item | Value |
| --- | --- |
| Authoritative commit | `c426b35` (exists; "H3-GOVERNANCE-RECONCILIATION-AND-H5-SELECTION-01: execution ledger + H5 prereg") |
| Authoritative blob | `a1eee0d287d6ce335024cb850251bd1e34d13e17` |
| **AUTHORITATIVE_BLOB_SHA256** | `29ececb759aff059282a0324b3b94b4bcd13b35b51060c6c742f2eaa48db0a86` |
| CONTAMINATED_SHA256 | `ed087e6c7bd569555918cefe23d8cead714a28094231d9747569b7dcdf94b94e` (preserved byte-for-byte, verified with `cmp`) |
| INTERNAL_FINGERPRINT_VALID | **true** — the self-declared `manifest_sha256` equals the committed bytes' sha256 |
| DEF-H5-GOV-002 | **REJECTED** (outcome A; self-fingerprint used as secondary confirmation only) |
| DEF-H5-GOV-001 | **CONFIRMED_FIXED** — working tree restored byte-identical from the blob |
| Restoration verification | `git diff c426b35 -- H5_MANIFEST.json` => EMPTY; `H5_PREREG_RESTORED = true` |

Key forensic finding: the prior run (git-blocked) left a *generation-3* file that was
neither the prereg blob nor the true contaminated state (filled-in prereg fields,
dropped campaign snapshot; sha256 `dfd89a28…`). It was preserved as evidence
(`evidence/H5_MANIFEST_GEN3_WRONG_RESTORE_DFD89A28.json`) before the authoritative
restore, and the `DEF_H5_GOV_001` record carries an addendum correcting its earlier
restoration claim.

Two facts explain the prior run's BLOCKED status: (a) git object access works in this
environment (proven throughout this run), and (b) the manifest's declared
`manifest_sha256` matches the authoritative blob sha256 exactly — so the "contaminated
manifest" framing of P2's authority question resolves as *valid fingerprint, mutated
file*.

## 2. Execution ledger reconciliation (P4–P5)

- Canonical counts: `ECONOMIC_EXPERIMENT_IDS = 1`, `EXECUTION_ATTEMPTS = 2`,
  `FAILED_ATTEMPTS = 1`, `COMPLETED_ATTEMPTS = 1`.
- Recovery links governance-established: `a1.recovered_by = a2`,
  `a2.recovery_of = a1`. Durable ledger rows retain `recovery_of_attempt_id = null`
  and are **not rewritten** (append-only policy; H3 precedent).
- Hash identity across attempts: `spec_sha256` (c743fba4…) and `protocol_sha256`
  (8452c0cf…) identical on all four rows; `economic parameters unchanged`.
- `failure_message_authority = COMPLETE_DURABLE_LEDGER` — the original verbatim error
  text IS available ("economic evaluation failed: too many values to unpack (expected 2)").
- Prior summary artifacts contained wrong timestamps, a paraphrased failure text, and an
  unsupported `protocol_sha256` (4f63a6b1…); all discrepancies registered in
  `H5_EXECUTION_RECORD.json → prior_artifact_discrepancies` with prior versions preserved
  under `evidence/`.
- `CERTIFY_EXACTLY_ONCE_H5 = false` (evaluation attempts not persisted; a1 died inside
  economic evaluation — H3 semantics correction applied verbatim).

## 3. Orthogonality reconciled without rerun (P6)

- Published invalid value: `daily_pnl_correlation = 61.91569544528234` (violates
  −1 ≤ r ≤ 1). Module/function traced: `scripts/h5_run_exactly_once.py`,
  `compute_orthogonality_diagnostics(...)`.
- Root cause proven: the numerator accumulated covariance as a raw SUM while the
  denominator used population std → the computed quantity is exactly **n × r**.
  Demonstrated by construction in `evidence/PEARSON_VERIFIER_SELFTEST.json`.
- Exact inversion from persisted frozen outputs only:
  **`CORRECTED_PEARSON_R = 61.91569544528234 / 102 = 0.6070166220125719`** — bounded,
  deterministic, parameter-free. `H5_ORTHOGONALITY = CORRECTED`.
- Independent verifier invariants (tolerance 1e-12): r(X,X)=1, r(X,−X)=−1, constant
  series guarded, −1 ≤ r ≤ 1, scale invariance — all PASS.
- Consequence: under the frozen redundancy rule, corrected corr 0.607 no longer trips
  the 0.7 threshold (overlap 0.916 unchanged, still flags non-independence). Corrected
  orthogonality **cannot promote H5**.

## 4. Canonical H5 result (P7)

**`H5_RESULT = DISCOVERY_FAIL` — FINAL.** No rerun, no retune, `H5_RESULT.json`
byte-identical (ledger-anchored `result_sha256` verified on a2). Failure is independently
carried by: P(Sharpe>0) = 0.8285 < 0.90; permutation p = 0.1838 > 0.05; halves [1, −1];
thirds [1, 1, −1]; walk-forward last third −0.0858 R.

## 5. Failed research memory (P8)

Entry **#12** appended to `docs/external-audit-01/FAILED_RESEARCH_MEMORY.md` (terminal
DISCOVERY_FAIL; hypothesis, assets, timeframe, N=107, gross/net expectancy, PF, Sharpe+CI,
permutation p, halves/thirds, walk-forward, cost drag, orthogonality status, failure
mechanism). Positive subcells (BTC +0.456 R; ETH_LONG +0.546 R; SOL_LONG +0.477 R) are
marked **POST_HOC_LEAD_ONLY · INSUFFICIENT_SAMPLE · DO_NOT_RETEST_WITHOUT_NEW_EX_ANTE_HYPOTHESIS**.

## 6. Governance: same-data proliferation stopped (P9)

**`CURRENT_INFORMATION_SET = EXHAUSTED_FOR_NOW`** registered in **ADR-0033**
(`tasks/decisions.md`): no H6 from another OHLCV transformation, no parameter search over
H5. Next alpha work only via the adopted new data families, each requiring full source
validation and preregistration.

## 7. Alpha data expansion (P10–P11)

`ALPHA_DATA_EXPANSION_PLAN.md` evaluates all 8 requested families across the 11 required
attributes (source authority, historical depth, assets, resolution, PIT safety, cost,
rate limits, licensing, data quality, expected mechanism, expected frequency, storage).
Ranked scoring:

| Class | Family |
| --- | --- |
| **ADOPT_P0** (max 2) | 7. Trade flow (aggTrades, official deep archive) · 1. Open interest (data.binance.vision) |
| EXPERIMENT | 6. Cross-exchange funding differentials |
| Standby substitute | 3. Order book depth imbalance |
| DEFER | 4. Basis curve (conditioning input only) |
| REJECT | 2. Liquidations · 5. Cross-exchange prices · 8. Options IV/skew |

No H6 created. Hard preconditions (backfill validation, fingerprints, PIT contract,
corrected-Pearson orthogonality gate before economics) are listed in the plan.

## 8. Shadow (P12) — WAIT

11 captures, 0 mature, 0 resolved; earliest maturity 2026-09-11T21:15Z > current UTC
(11:10Z). No early resolution performed. `SHADOW_POLICY_CONCLUSION = INSUFFICIENT_SAMPLE`.

## 9. Confirmation lock (P13) — WAIT

`CONF-EDGE-002-001`: consumed=false, executions=0. Nothing done before
2026-09-22T00:00Z. Untouched.

## 10. Regression / governance validation (P14)

- Focused governance tests (`test_execution_ledger.py`, `test_h5_orderflow.py`): **20/20 PASS**.
- Full hermetic suite: **1235 passed / 2 failed (3m21s)** — both failures pre-existing and
  unrelated to this checkpoint (local config drift in `test_settings`; full-suite ordering
  artifact in `test_dependency_closure_guard`, passes in isolation). No code was modified
  by this run (verified via `git diff --name-only` → docs-only footprint).
- LIVE_CALLS = 0 · RISK_CHANGED = 0 · PAPER_PROMOTIONS = 0 · FALSE_SUCCESS = 0.

## 11. Artifacts produced (P15)

| Artifact | Path |
| --- | --- |
| Restoration report | `docs/external-audit-01/h5-orderflow-imbalance-01/H5_PREREG_RESTORATION_REPORT.json` |
| Orthogonality reconciliation | `docs/external-audit-01/h5-orderflow-imbalance-01/H5_ORTHOGONALITY_RECONCILIATION.md` |
| Execution record (canonical) | `docs/external-audit-01/h5-orderflow-imbalance-01/H5_EXECUTION_RECORD.json` |
| Post-execution annotations | `docs/external-audit-01/h5-orderflow-imbalance-01/H5_POST_EXECUTION_ANNOTATIONS.json` |
| Implementation post-exec status | `docs/external-audit-01/h5-orderflow-imbalance-01/H5_IMPLEMENTATION_POST_EXECUTION_STATUS.json` |
| Alpha data expansion plan | `docs/external-audit-01/h5-orderflow-imbalance-01/ALPHA_DATA_EXPANSION_PLAN.md` |
| Failed research memory #12 | `docs/external-audit-01/FAILED_RESEARCH_MEMORY.md` |
| Governance decision | `tasks/decisions.md` (ADR-0033) |
| Run report | `docs/external-audit-01/h5-orderflow-imbalance-01/RUN_REPORT.md` + `.json` |
| Defect records (updated) | `DEF_H5_GOV_001…`, `DEF_H5_GOV_002…`, `DEF_H5_ORTHO_001…`, `TRACK_B…`, `TRACK_D…` |
| Preserved evidence | `evidence/`: contaminated manifest, gen-3 wrong restore, prior-run artifacts, Pearson verifier self-test |

## 12. Open items / notes

- Working tree holds uncommitted H5 execution artifacts (ledger, result, etc.) from
  2026-09-10/11 plus this run's outputs; committing them is left as an explicit user
  decision (per repo governance, commits are not made unprompted).
- `H5_RESULT.json → code_commit: f0c246f2…` is not a valid git object (frozen file;
  preserved as-is; treated as unverifiable claim — see
  `H5_IMPLEMENTATION_POST_EXECUTION_STATUS.json`).
- Runner defect (empty `dataset_sha256` in ledger rows) noted for future protocol fix —
  the effective dataset fingerprint is anchored via `H5_RESULT.json → dataset_sha256`.
- P12 resolves only after 2026-09-11T21:15Z as captures mature; P13 unlocks
  2026-09-22T00:00Z.
