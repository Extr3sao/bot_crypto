# H6 V4 — Selection rationale

**Checkpoint:** `H6-V4-AUTHORITY-CONTRACT-AND-RUNTIME-BINDING-REPAIR-01`
**Hypothesis ID:** `H6-OI-CONFIRMED-CONTINUATION-04`
**Status:** `PREREGISTERED_NOT_EXECUTED`

## 1. Why a V4 preregistration exists at all

V4 is **not** a new economic hypothesis. It is a governance / runtime-authority /
spec-consistency repair of the **same frozen economic mechanism**.

```
H6 V1  FAILED_EXTERNAL_VERIFICATION
H6 V2  FAILED_EXTERNAL_VERIFICATION_V2
H6 V3  FAILED_PRE_EXECUTION
```

V3 never executed economically:

```
H6_BACKTESTS        = 0
H6_EXECUTIONS       = 0
PERFORMANCE_OBSERVED = false
```

The V3 defects (recorded in `H6_V3_FAILURE_RECORD.json`) were:

| ID | Defect |
|----|--------|
| `V3-WL-001` | Raw backing mapping exposed via `H6FieldAccess.data` (`slots=True` made the `__getattr__` guard for `"data"` dead code). |
| `V3-WL-002` | `repr` / `copy` / `pickle` / backing-object leakage of unadmitted provider values. |
| `V3-WL-003` | Whitelist not on the actual H6 runtime data path — decorative. |
| `V3-AUTH-001` | Control plane bound to the superseded, failed **V1** preregistration across eleven files. |
| `V3-SPEC-001` | `statistical_gates` missing from the V3 frozen spec. |
| `V3-SPEC-002` | Structured `pit_rules` missing from the V3 frozen spec. |
| `V3-SPEC-003` | `stop_invalidation` absent. |
| `V3-SPEC-004` | `cooldown` absent as a standalone frozen field. |
| `V3-IMPORT-001` | Shared editable `.pth` can import the main checkout instead of the worktree. |
| `V3-FEATURE-001` | `build_completed_hour_oi` raised for every non-empty snapshot list (`_hour_close_boundaries` returned a tuple; caller read `.start` / `.end`). |
| `V3-FEATURE-002` | Inclusive hour bounds can yield 13 snapshots instead of the frozen 12. |

Because the frozen economic artifacts are immutable, a defect in the *authority
layer* cannot be repaired by editing them. A new preregistration is the only
governed way to re-freeze the same economics against a correct authority layer.

## 2. Economic identity — NO RETUNE

The V4 economic block is **programmatically carried forward** from the last
complete pre-performance economic authority (`H6_SPEC_V2.json`). Nothing was
retyped. `H6_V4_ECONOMIC_SEMANTIC_DIFF.json` reports:

```
UNEXPLAINED_DIFFERENCES = 0
ECONOMIC_RETUNE_COUNT   = 0
```

| Surface | Value (unchanged) |
|---------|-------------------|
| Assets | `BTCUSDT`, `ETHUSDT`, `SOLUSDT` |
| Decision timeframe | 1h completed bucket |
| Common window | `2021-12-01T00:00:00Z` → `2026-09-10T23:59:59Z` |
| OI authority | `sum_open_interest`, `sum_open_interest_value` |
| Rolling history | trailing 30 calendar days (720 completed hourly changes) |
| Minimum observations | 336 |
| Center / scale | median / `1.4826 × MAD` |
| Qualifying condition | `delta_oi > 0` **AND** `robust_z_oi >= +1.0` |
| MAD == 0 | `NO_SIGNAL` |
| OI contraction | `NO_SIGNAL` |
| Price direction | completed-hour close vs open |
| Entry | next-hour `OPEN` |
| Exit | same next-hour `CLOSE` (exact 1h hold) |
| Stop | `NONE` |
| Cooldown | `NONE` |
| Cost model | 10 bps base total round trip; sensitivity `0/10/20/40` |
| Funding | `EXCLUDED_WITH_LIMITATION` + materiality gate before promotion |
| Orthogonality | `≤ 0.50` vs momentum proxy |
| Minimum N | 30 per asset / 100 pooled |
| Statistical gates | `P_Sharp_greater_0_min = 0.90`, `permutation_p_max = 0.05`, `sharpe_ci_excludes_zero = true`, sign-flip permutation on hourly trade returns, 10 000 draws, fixed seed `20260911` |
| Robustness | halves / thirds / walk-forward |

## 3. What actually changed

Only representation, governance and runtime wiring:

1. **Whitelist root cause.** The accessor was redesigned so that it **never stores
   forbidden values**. Construction validates inbound keys and retains only admitted
   data in an immutable mapping. A second, *fail-closed* boundary
   (`feature_authority.admitted_observation`) rejects a dirty row **before** any
   aggregation, feature or signal exists, and is wired into the real runtime entry
   point (`preparation.prepare_decision`).
2. **Single authority binding.** No hash or path literals remain in the runtime
   package. Everything resolves from one versioned, non-economic artifact.
3. **Report path.** Versioned and repo-root resolved, never CWD dependent.
4. **Hour aggregation.** One explicit `HourWindow` representation, half-open
   `[T-1h, T)`, exactly 12 snapshots, conflicting duplicates fail closed.
5. **Spec completeness.** `statistical_gates`, structured `pit_rules`,
   `stop_invalidation` and `cooldown` are explicitly present and machine-checkable.

The two declared representation relocations (`statistical_gates.permutation` prose →
typed fields; `DECISION_ELIGIBILITY_AT_T` → `pit_rules.decision_eligibility`) preserve
the original values verbatim and are listed in the semantic diff.

## 4. What this document does NOT claim

```
H6_BACKTESTS         = 0
H6_EXECUTIONS        = 0
PERFORMANCE_OBSERVED = false
```

No PnL, Sharpe, profit factor, expectancy, win rate or future-return figure was
computed. Builder self-verification is **builder evidence only**. Independent
verification is `H6-EXTERNAL-INDEPENDENT-VERIFICATION-V4`.
