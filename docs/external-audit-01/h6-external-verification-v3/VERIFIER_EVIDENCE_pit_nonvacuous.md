# VERIFIER_EVIDENCE_pit_nonvacuous.md — Dynamic PIT Non-Vacuous Harness

**Gate:** `DYNAMIC_PIT_NON_VACUOUS_HARNESS`
**Verdict:** **PASS**
**Machine-readable:** `VERIFIER_EVIDENCE_pit_nonvacuous.json`
**Script:** `verifier_pit_nonvacuous.py` (run with `PYTHONPATH=<verifier>/src`)
**Audited target:** `a5487164803fb601f87f2cd4c865929c30da274e`
**Data:** verifier-authored **synthetic** series. `real_data_touched = false`. No economics.

---

## 1. Why "non-vacuous" is the whole point

A PIT test that only proves "mutating data after T changes nothing" is worthless if the state at T
was empty, ineligible, or `NO_TRADE` to begin with — the harness could not detect a change even if one
occurred. This harness therefore first forces a **positive, tradeable baseline** at T, and only then
tests invariance.

## 2. Synthetic fixture

- Symbol `TSTUSDT` (not a real research asset), 5-minute grid, `2026-03-01` → `2026-03-25`.
- Hourly last-snapshot OI alternates `+15 / +5`, giving rolling **median 10.0** and **MAD 5.0**
  (non-zero), so the robust z-score is defined.
- The decision hour receives an engineered **+4000** OI spike and the price bar is `open 100 → close 101`.
- Decision time **T = 2026-03-20T12:00:00Z** (≥ 338 hours of history available).
- Written as the frozen normalised layout `…/TSTUSDT/TSTUSDT-oi-5m-YYYY-MM-DD.jsonl` into a verifier
  temp dir that is removed afterwards.

## 3. Non-vacuous baseline at T

| property | value |
|---|---|
| `DECISION_ELIGIBILITY_AT_T.eligible` | **true** |
| `DECISION_ELIGIBILITY_AT_T.reason` | `ELIGIBLE` |
| rolling history length | **467** (≥ required 336) |
| `FEATURE_STATE_AT_T.decision_eligible` | **true** |
| `FEATURE_STATE_AT_T.robust_z_oi` | **269.12** (≥ +1.0) |
| `FEATURE_STATE_AT_T.delta_oi` | **+4005.0** (> 0) |
| `SIGNAL_INPUT_AT_T` causal rows | **5617** |
| max causal timestamp ≤ T | **true** (no future row admitted) |
| **signal** | **`LONG`**, entry `2026-03-20T13:00:00Z`, exit same bar close |

`NON_VACUOUS = true`. The baseline is a real, eligible, direction-decided trade — so invariance below
is meaningful.

## 4. Mutation results

Each mutation rewrites the synthetic dataset, recomputes all four artifacts, and compares
**SHA256 of canonical JSON** against the baseline.

### FUTURE mutations — must be byte-identical

| mutation | description | signal_input | eligibility | feature_state | signal | result |
|---|---|---|---|---|---|---|
| `future_row_value_mutation` | a row **strictly after T** scaled ×3 | unchanged | unchanged | unchanged | unchanged | **PASS** |
| `future_row_addition` | 60 later rows deleted **and** a row appended far after T | unchanged | unchanged | unchanged | unchanged | **PASS** |

### PAST mutations — must be detectable (proves harness sensitivity)

| mutation | description | signal_input | eligibility | feature_state | signal | result |
|---|---|---|---|---|---|---|
| `past_row_value_mutation` | a row **strictly before T** scaled ×1.5 | changed | changed | changed | changed | **PASS** |
| `past_gap_before_T` | the decision hour's 12 snapshots deleted | changed | changed | changed | changed | **PASS** |

Because the *same* comparison machinery detects the past mutations, the future-invariance result
cannot be an artefact of a blind harness. This satisfies the frozen `pit_rules.future_mutation`
requirement: *"DECISION_ELIGIBILITY_AT_T, FEATURE_STATE_AT_T and SIGNAL_INPUT_AT_T must be
byte-identical under mutations strictly after T (FUTURE_SAME_DAY_GAP_MUTATION test, non-vacuous
baseline); PAST_GAP_BEFORE_T may change eligibility; FUTURE_GAP_AFTER_T must not."*

## 5. Builder PIT suite also executed

`PYTHONPATH=<verifier>/src python -m pytest tests/unit/research/test_oi_full_history_v2_pit.py -q`
→ **14 passed**. The builder suite covers future gap/mutation/file-addition invariance, past-gap
sensitivity, out-of-order rows, exact-duplicate collapse, conflicting duplicates, byte invariance
under all future mutations, and the pytest canonical-write guard. Independently reproduced here; the
verifier's own harness is additive, not a re-run.

---

## 6. Defect found while building this harness — `FIND-PIT-01`

`src/trading_bot/research/h6/eligibility.py::build_completed_hour_oi` is **non-functional**.

```python
def _hour_close_boundaries(hour_close_time) -> tuple[datetime, datetime]:
    start = hour_close_time - timedelta(hours=1)
    return start, hour_close_time          # plain TUPLE

def build_completed_hour_oi(snapshots, *, hour_close_time):
    ts_to_use = _hour_close_boundaries(hour_close_time)
    within = [s for s in snapshots if ts_to_use.start <= s.oi_time <= ts_to_use.end]
                                     # ^^^^^^^^^^^^^^ AttributeError
```

Minimal reproduction (verifier-executed):

```
build_completed_hour_oi([], hour_close_time=T)     -> OK      (predicate never evaluated: VACUOUS PASS)
build_completed_hour_oi([one_snapshot], ...)       -> BROKEN  AttributeError: 'tuple' object has no attribute 'start'
```

- **Primary defect:** `.start` / `.end` used on a plain tuple → `AttributeError` for **any non-empty
  input**. The function only "works" on an empty list, i.e. exactly the case that carries no
  information.
- **Secondary defect (derived):** the bounds are **inclusive** (`<= end`) whereas
  `_snapshots_in_window_v2` and `SNAP` semantics are **half-open** `[start, end)`. On a grid-aligned
  hour, inclusive bounds yield **13** distinct snapshots, so `snapshot_count != 12` and the frozen
  `CURRENT_HOUR_OI_COMPLETENESS = 12` rule would fail even after the `AttributeError` is fixed.
- **Reachability:** the only references are the definition and the package re-export in
  `h6/__init__.py`. It has **no runtime caller** — consistent with
  `WHITELIST_RUNTIME_REACHABILITY = FAIL_NOT_WIRED`.
- **Severity:** MEDIUM (latent). It is dormant today but is public API, is required by the frozen
  `CURRENT_HOUR_OI_COMPLETENESS` semantics, and would break immediately when wired in.
- **Verifier action:** REPORTED ONLY, not repaired. This harness performs the equivalent half-open
  aggregation inline rather than working around the broken helper by calling it.

---

## 7. Result

| check | result |
|---|---|
| baseline non-vacuous (eligible + real signal + sufficient history) | ✅ |
| future mutations byte-invariant (2/2) | ✅ |
| past mutations detected (2/2) | ✅ |
| builder PIT suite (14 tests) | ✅ |
| **`DYNAMIC_PIT_NON_VACUOUS_HARNESS`** | **PASS** |

### Findings from this gate

| id | severity | title | status |
|---|---|---|---|
| `FIND-PIT-01` | MEDIUM | `build_completed_hour_oi` raises `AttributeError` on any non-empty input (`.start`/`.end` on a tuple); bounds also inclusive where half-open is required | OPEN, unrepaired |
