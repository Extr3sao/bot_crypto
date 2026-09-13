# VERIFIER_EVIDENCE — Confirmation & Shadow Gates

**Audited target:** `a5487164803fb601f87f2cd4c865929c30da274e`
**Machine-readable:** `VERIFIER_EVIDENCE_confirmation_shadow.json`
**Script:** `verifier_confirmation_shadow.py` (run with `PYTHONPATH=<verifier>/src`)

| gate | verdict |
|---|---|
| `CONFIRMATION_LEDGER` | **PASS** (12/12 adversarial cases) |
| `CONFIRMATION_LOCK` | **PASS** |
| `CONFIRMATION_H6_FIREWALL` | **PASS** |
| `SHADOW_INVALIDATION` | **PASS** |
| `SHADOW_MATURITY_AUTHORITY` | **PASS** |
| `SHADOW_H6_FIREWALL` | **PASS** |

---

## 1. `CONFIRMATION_LOCK` / `CONFIRMATION_LEDGER`

The lock is driven adversarially with **verifier-authored ledgers** (each in its own temp dir); the
real lock function is executed by temporarily pointing `CONFIRMATION_LEDGER_PATH` at the synthetic
file. No builder test was reused.

| case | expected | observed source | consumed | executions | raised | result |
|---|---|---|---|---|---|---|
| `absent_ledger_fails_closed` | RAISE | `missing_manifest` | UNKNOWN | UNKNOWN | ✅ violation | **PASS** |
| `empty_ledger_is_treated_as_valid_locked` | locked | `confirmation_ledger_v2` | False | 0 | – | **PASS** |
| `created_plus_lock_check_stays_locked` | locked | `confirmation_ledger_v2` | False | 0 | – | **PASS** |
| `CONSUMED_event_breaks_lock` | RAISE | `confirmation_ledger_v2` | **True** | 0 | ✅ `consumed=True; expected false` | **PASS** |
| `STARTED_event_breaks_lock` | RAISE | `confirmation_ledger_v2` | False | **1** | ✅ `executions=1; expected 0` | **PASS** |
| `invalid_event_type_breaks_lock` | RAISE | `confirmation_ledger_v2_invalid` | UNKNOWN | UNKNOWN | ✅ ledger invalid | **PASS** |
| `other_confirmation_id_isolated` | locked | `confirmation_ledger_v2` | False | 0 | – | **PASS** |
| `ledger_order_independent_distinct_attempts` | locked | `confirmation_ledger_v2` | False | 0 | – | **PASS** |
| `malformed_row_without_confirmation_id_is_ignored` | locked | `confirmation_ledger_v2` | False | 0 | – | **PASS** |
| `malformed_row_with_correct_confirmation_id_breaks_lock` | RAISE | `confirmation_ledger_v2_invalid` | UNKNOWN | UNKNOWN | ✅ | **PASS** |
| `duplicate_consumed_breaks_lock` | RAISE | `confirmation_ledger_v2_invalid` | UNKNOWN | UNKNOWN | ✅ | **PASS** |
| `started_after_consumed_breaks_lock` | RAISE | `confirmation_ledger_v2_invalid` | UNKNOWN | UNKNOWN | ✅ | **PASS** |

### `ledger_derived_not_hardcoded = true`

The state is genuinely reduced from the ledger, not hard-coded:

- a ledger containing a `CONSUMED` event yields `consumed = True` and the lock **raises**;
- a clean ledger yields `consumed = False`, `executions = 0` and the lock **passes**.

Both directions were observed with the *same* code path, so `consumed=false` is not a constant.

Real ledger at the frozen relative path
`docs/external-audit-01/oi-full-history-02/CONFIRMATION_LEDGER_V2.jsonl`:
exists, **1 line**, sha256 `188290908fe4765c0197f7fc27c0572a19d7b2d34a82741cc04c223bb18e5add` — a single
`LOCK_CHECK` row with `status = LOCKED_UNTIL_2026-09-22T00:00:00Z_CONSUMED_FALSE_EXECUTIONS_0`.

`lock_expired_at_audit_time = false` (audit date 2026-09-13 < 2026-09-22).

### Finding `FIND-CONF-01` — truncation is not detected (MEDIUM)

| scenario | behaviour |
|---|---|
| ledger file **absent** | fails closed (raises `ConfirmationLockViolation`) |
| ledger file **present, truncated to 0 lines** | **accepted as a valid, not-consumed, locked state** |

So destroying the ledger's contents (rather than the file) silently restores the "locked" verdict,
while only deleting the file is caught. The ledger is a plain JSONL with **no hash chain, no
signature, and no entry-count pin**, so its "append-only" property is a convention rather than an
enforced guarantee. Whoever can write that file controls the gate.

Related, smaller: `CONFIRMATION_LEDGER_PATH` is a **relative** path, so this gate's outcome depends on
the process working directory (recorded in `constants.ledger_path_is_cwd_dependent = true`).

Also recorded: rows that do not carry the target `confirmation_id` are filtered out **before**
validation, so a malformed or foreign row is silently ignored rather than reported. This does **not**
open the lock (correctly demonstrated), but it means ledger corruption produces no error.

---

## 2. `CONFIRMATION_H6_FIREWALL` — **PASS**

- Frozen artifact declares `H6_CONFIRMATION_DATA_DEPENDENCY = "NONE"`.
- Static scan of every `src/trading_bot/research/h6/*.py`: the only modules referencing confirmation
  authority are `conf_lock.py` and `confirmation_state.py` themselves. **No H6 feature/signal module
  reads confirmation data** (`h6_runtime_modules_reading_confirmation_data = []`).
- These two modules are a *governance lock* that lives inside the h6 package, not a data dependency.
  Noted so the "NONE" declaration and the module location are not read as contradictory.

## 3. `SHADOW_INVALIDATION` — **PASS**

`SHADOW_V2_INVALIDATION_RECORD.json` explicitly **invalidates the builder's own earlier claim**:

- invalidated artifact: `reports/poc02-r2-direction-arbitration-01/shadow/SHADOW_RESOLUTION_LEDGER.jsonl`
- previous claim: `{total_captures: 11, mature_captures: 11, resolved_captures: 11, outcome: "11/11 PROFITABLE_REJECT"}`
- verdict: `INVALIDATED`
- reason: *"maturity timestamps equalled capture timestamps (maturity_time == decision_time) despite
  frozen 48h rule; zero horizon violates mature-only invariant"*

Independently checked that the invalidated claim is **not re-asserted** by the superseding
`SHADOW_RESOLUTION_REPORT_V2.json`: its `disposition` preserves the old ledger as invalid evidence
("do not silently overwrite") and points to `SHADOW_RESOLUTION_LEDGER_V2.jsonl`. The report does not
restate `11/11 PROFITABLE_REJECT` as an outcome.

**Note on the shape of this gate:** the earlier shadow performance claim was **withdrawn by the
builder and confirmed invalid by the verifier**. No shadow performance is currently asserted, and none
was observed by this audit. This is the correct disposition for a claim built on a zero-hour horizon.

## 4. `SHADOW_MATURITY_AUTHORITY` — **PASS**

| check | value |
|---|---|
| `protocol_version` | `SHADOW-48H-MATURE-ONLY-V1` |
| `horizon_hours` | **48** |
| `captures_total` | 11 |
| captures parsed | 11 |
| every `maturity_time − capture_time` == 48h | **true** (0 bad captures) |
| earliest maturity | `2026-09-11T21:15:00+00:00` |
| all matured as of audit time (2026-09-13) | **true** |

Arithmetic recomputed independently from the artifact's own timestamps for all 11 captures.

## 5. `SHADOW_H6_FIREWALL` — **PASS**

- Frozen artifact declares `H6_SHADOW_DATA_DEPENDENCY = "NONE"`.
- `h6_modules_importing_shadow = []` and `h6_modules_referencing_shadow_authority = []` — no H6 module
  imports or references the shadow package at all.

---

## Findings from this batch

| id | gate | severity | title | status |
|---|---|---|---|---|
| `FIND-CONF-01` | CONFIRMATION_LOCK | MEDIUM | An absent ledger fails closed but a **truncated** ledger is accepted as valid; the ledger has no hash chain, signature or entry-count pin, so "append-only" is unenforced and gate control reduces to write access to one plain file | OPEN, unrepaired |
| `FIND-CONF-02` | CONFIRMATION_LOCK | LOW | `CONFIRMATION_LEDGER_PATH` is a relative path → gate outcome is CWD-dependent | OPEN, unrepaired |
| `FIND-CONF-03` | CONFIRMATION_LEDGER | LOW | Rows lacking the target `confirmation_id` are filtered before validation, so malformed/foreign rows are silently ignored and ledger corruption reports no error | OPEN, unrepaired |

No file under `src/` was modified. No economics observed.
