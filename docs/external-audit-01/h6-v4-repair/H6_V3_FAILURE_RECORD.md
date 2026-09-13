# H6 V3 FAILURE RECORD

**Checkpoint:** `H6-V4-AUTHORITY-CONTRACT-AND-RUNTIME-BINDING-REPAIR-01`
**Machine-readable:** `H6_V3_FAILURE_RECORD.json`

> V3 is **IMMUTABLE FAILED HISTORY**. Nothing in this document mutates any V3 artifact.

## 1. V3 identity

| item | value |
|---|---|
| V3 prereg freeze commit | `9f1d844312419575d6b635a7356111050fd9b93a` |
| V3 final builder package | `a5487164803fb601f87f2cd4c865929c30da274e` |
| builder-crosscheck audit branch | `audit/h6-external-verification-v3` |
| verifier evidence commits | `1a58e03`, `f7b4487`, `d9674f2`, `24ea186`, `625449d`, `a608bbd` |

Those verifier commits are **read-only evidence**. They are **not** merged into the repair branch and
**no verifier implementation code is cherry-picked**; V4 repairs are independently implemented from the
evidence.

## 2. Status

| generation | status |
|---|---|
| H6 V1 | `FAILED_EXTERNAL_VERIFICATION` |
| H6 V2 | `FAILED_EXTERNAL_VERIFICATION_V2` |
| H6 V3 | `FAILED_PRE_EXECUTION` |

`H6_BACKTESTS = 0`, `H6_EXECUTIONS = 0`, `PERFORMANCE_OBSERVED = false`.
V3 never executed economically. No PnL, Sharpe, profit factor, expectancy or win rate was ever
computed for H6.

## 3. Defect register

| id | title | severity |
|---|---|---|
| `V3-WL-001` | Raw backing map exposed via `H6FieldAccess.data` | **HIGH** |
| `V3-WL-002` | `repr` / `str` / `copy` / `pickle` leakage of forbidden values | MEDIUM |
| `V3-WL-003` | Whitelist not on the actual H6 runtime data path | **HIGH** |
| `V3-AUTH-001` | Control plane bound to failed/superseded V1 authority | **HIGH** |
| `V3-SPEC-001` | `statistical_gates` missing from the V3 frozen spec | **HIGH** |
| `V3-SPEC-002` | Structured `pit_rules` missing from the V3 frozen spec | **HIGH** |
| `V3-SPEC-003` | `stop_invalidation` absent | MEDIUM |
| `V3-SPEC-004` | `cooldown` absent as a standalone frozen field | LOW |
| `V3-IMPORT-001` | Shared editable `.pth` can import the main checkout instead of the worktree | **HIGH** |
| `V3-FEATURE-001` | `build_completed_hour_oi` fails for non-empty snapshots (`.start`/`.end` on a tuple) | MEDIUM |
| `V3-FEATURE-002` | Inclusive hour-window bounds can produce 13 snapshots instead of 12 | MEDIUM |

### Details

**`V3-WL-001` — raw backing map exposed (`HIGH`).**
`H6FieldAccess` is `@dataclass(frozen=True, slots=True)` with a `data` field. Because `slots=True`
creates a real slot descriptor, normal attribute lookup for `data` succeeds and the `__getattr__`
guard that raises `AttributeError` for the name `"data"` is **dead code**. One attribute access
(`wrapped.data["count_long_short_ratio"]`) retrieves a forbidden provider field, contradicting the
frozen artifact's `enforcement.bypass_paths_allowed = 0`.

**`V3-WL-002` — leakage (`MEDIUM`).**
The dataclass-generated `__repr__` renders the whole payload including forbidden names **and values**;
`copy.copy` and `pickle` round-trips carry the same raw mapping. Logs, tracebacks and evidence dumps
are evidence surfaces — forbidden feature values must never reach them.

**`V3-WL-003` — not wired (`HIGH`).**
A whole-`src` scan found the only references to `H6FieldAccess` / `check_row_whitelist` /
`assert_field_allowed` are `whitelist.py` itself and the `h6/__init__.py` re-export. No OI-reading
module invokes the accessor. Feature authority was enforced only by the normaliser stripping forbidden
columns and by static scans, so the control gave no runtime guarantee.

**`V3-AUTH-001` — stale V1 control plane (`HIGH`).**
18 bindings across 11 files pinned V1 identity (`e683e04…`, `f514fecf…`, `345334c3…`, `oi-full-history-01`)
while V3 was the live freeze. Affected: `contracts.py`, `feature_engine.py`, `execution_harness.py`,
`gate_config.py`, `frozen_contract_snapshot.py`, `external_verifier_report.py`, `contamination_scan.py`,
and four `scripts/`. Consequences: fail-closed in practice, but a legitimate V3 report would have been
rejected with `H6PreregMismatch`, a V1-keyed PASS report would have satisfied the gate, and the report
path was relative and therefore CWD-dependent.

**`V3-SPEC-001` — `statistical_gates` lost (`HIGH`).**
`H6_SPEC_V3.economics` contains no `statistical_gates` anywhere. Lost values: `P_Sharp_greater_0_min = 0.9`,
`permutation = "sign-flip permutation on hourly trade returns, 10,000 draws, fixed seed 20260911"`,
`permutation_p_max = 0.05`, `sharpe_ci_excludes_zero = true`. The runtime contract loader requires this
key. The permutation **seed and draw count** had no live frozen authority at all.

**`V3-SPEC-002` — `pit_rules` lost (`HIGH`).**
The structured block was dropped; only prose fragments survive inside
`common_window_utc.archive_validity_vs_decision_eligibility`. The runtime loader requires
`spec["pit_rules"]["oi"|"price"|"future_mutation"]`. Prose is not a substitute for a required field.

**`V3-SPEC-003` / `V3-SPEC-004` — `stop_invalidation` and `cooldown` (`MEDIUM` / `LOW`).**
Both were present in V2 and absent from `V3.economics`. `cooldown`'s meaning survives indirectly via the
textually identical `decision_spacing` field; `stop_invalidation` does not survive at all.

Net V2→V3 economic accounting: **24 V2 economic fields → 20 carried byte-identically, 0 changed, 4 absent.**

**`V3-IMPORT-001` — import authority (`HIGH`).**
The shared venv's `__editable__.crypto_scalping_agentic_bot-0.1.0.pth` holds the **absolute** path
`C:\Users\GVLLFR0035\Downloads\bot freebuff\src`. Worktrees share that venv, so a bare
`import trading_bot` from any worktree loads the **main checkout**, which sits at base commit
`0941082` — pre-repair code. Concrete divergence: `src/trading_bot/research/oi_dataset_v2.py`
is `8e2803cf…` at `a548716` but `e91d56b7…` in the main checkout. Any H6 result produced without an
explicit import override has unproven target authority.

**`V3-FEATURE-001` — tuple bug (`MEDIUM`).**
`build_completed_hour_oi` does `ts_to_use = _hour_close_boundaries(hour_close_time)` (which returns a
plain **tuple**) then reads `ts_to_use.start` / `ts_to_use.end` → `AttributeError` for **any non-empty**
snapshot list. With an empty list the predicate is never evaluated, so the function appears to work
exactly in the vacuous case. It has no runtime caller.

**`V3-FEATURE-002` — inclusive-bounds off-by-one (`MEDIUM`).**
The same function selects `start <= oi_time <= end` (**inclusive** both ends). On the frozen 5-minute
grid aligned to `:00`, an hour ending at `T` has **13** points in `[T-1h, T]` but exactly **12** in the
required half-open `[T-1h, T)`. `_snapshots_in_window_v2` and `SNAPSHOTS_PER_HOUR = 12` use half-open
semantics, so the inclusive variant would keep failing `CURRENT_HOUR_OI_COMPLETENESS` even after
`V3-FEATURE-001` is fixed.

## 4. Preserved V3 PASSes

These results are available as evidence and **do not cancel** the critical failures above.

| gate | V3 result |
|---|---|
| `DATA_AUTHORITY_V3` | PASS (10/10: ledger+manifest sha256, independent dataset fingerprint, 5596/5596 normalised files, 5691/5691 raw zips, BTC 2024-06-05 forensic) |
| `PIT_DYNAMIC_V3` | PASS (non-vacuous: ELIGIBLE baseline, robust_z 269.1, LONG signal; future mutations byte-invariant, past mutations detected; builder suite 14 passed) |
| `PRICE_AUTHORITY_V3` | PASS (`PRICE_CONTINUITY` + `PRICE_FULL_OVERLAP`, 9/9; authority sha256 recomputes to `e1c2462a…`) |
| `CONFIRMATION_V3` | PASS (`CONFIRMATION_LEDGER`, `CONFIRMATION_LOCK`, `CONFIRMATION_H6_FIREWALL`; 12/12 adversarial lock cases) |
| `SHADOW_ISOLATION_V3` | PASS (`SHADOW_INVALIDATION`, `SHADOW_MATURITY_AUTHORITY` 48h 11/11, `SHADOW_H6_FIREWALL`) |
| also passing | `GIT_AUTHORITY`, `PREREG_FREEZE`, `FROZEN_ARTIFACT_HASH_RECOMPUTATION`, `POST_PREREG_IMMUTABILITY`, `ANCESTRY_INTEGRITY`, `PYTHON_IMPORT_AUTHORITY` (only **with** the explicit `PYTHONPATH` override), `TEST_TARGET_AUTHORITY`, `PERFORMANCE_CONTAMINATION`, `H5_IMMUTABILITY`, `DEFECT_REGRESSION_MATRIX_PRESENCE` |

## 5. V3 gates deliberately NOT completed

Per the V4 checkpoint instruction, execution budget is not spent finishing V3:
`DASHBOARD_20X`, `FULL_HERMETIC`, the full A/B determinism rerun, and remaining V3 defect-matrix reruns.
V3 already failed on critical authority gates. These run later **against V4**.

## 6. Non-blocking limitation carried forward

**Confirmation ledger tamper evidence.** An absent ledger fails closed, but a ledger truncated to zero
lines is accepted as a valid, not-consumed, locked state; the ledger has no hash chain, signature or
entry-count pin. Status: `LIMITATION_EXPLICIT_NON_BLOCKING` **only while** H6 has no confirmation
data/result dependency (`H6_CONFIRMATION_DATA_DEPENDENCY = NONE`). Not redesigned in V4.

## 7. Why V4 exists

V3 failed on authority, whitelist, runtime-binding and spec-consistency defects **before any economic
execution**. V4 therefore repairs those and re-preregisters. The economic mechanism is **unchanged and
not retuned**. `H6_BACKTESTS = 0`, `H6_EXECUTIONS = 0`, `PERFORMANCE_OBSERVED = false`.
