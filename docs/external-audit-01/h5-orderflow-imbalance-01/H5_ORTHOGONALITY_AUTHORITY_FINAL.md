# H5 ORTHOGONALITY AUTHORITY — FINAL (Track B1/B2)

Checkpoint: ALPHA-DATA-ADMISSION-01 / H5-GOVERNANCE-FINAL-CLOSURE · 2026-09-11
Machine-readable: `H5_ORTHOGONALITY_AUTHORITY_FINAL.json` (same directory)

## Verdict summary

| Field | Value |
| --- | --- |
| `EXECUTED_SOURCE_TEXT_AUTHORITY` | **INCOMPLETE** — the executed `.py` text was not recovered byte-exact; the current `scripts/h5_run_exactly_once.py` was edited 39 s AFTER execution completed (mtime 22:58:09Z / 22,480 B vs pyc-embedded source identity 22:56:17Z / 22,801 B) and is therefore NOT the executed source |
| `EXECUTED_ORTHOGONALITY_SEMANTICS_AUTHORITY` | **PROVEN_FROM_COMPILED_ARTIFACT** — the execution-era pyc (compiled 22:56:52Z, pre-execution) preserves the executed bytecode |
| `DERIVED_PEARSON_AUTHORITY` | **FORMULA_DERIVED_FROM_EXECUTED_BYTECODE** |
| `INDEPENDENT_RAW_RECOMPUTATION` | **false** — the 102-day daily PnL arrays were never persisted |

## Evidence chain (bytecode-level)

1. `scripts/__pycache__/h5_run_exactly_once.cpython-311.pyc` preserved as `evidence/H5_EXECUTED_RUNNER_PYC.pyc`, sha256 `28adcf70059df3cfbbbd9f93bd9fe336cab8972611cb6ebfe737bf35385ef3f8`.
2. Timeline (all UTC, 2026-09-10): pyc compiled **22:56:52.671769Z** embedding source identity `mtime 22:56:17Z, size 22801`; attempt a1 started **22:57:03Z**; a2 completed **22:57:30Z**; current `.py` mtime **22:58:09Z** (22,480 B) → source edited post-execution.
3. Disassembly of the executed `compute_orthogonality_diagnostics` (`evidence/EXECUTED_ORTHOGONALITY_DISASSEMBLY.txt`): **no `np.corrcoef`**; uses `mean/sum/std` with locals `cov, sx, sy, corr` — the hand-rolled form
   `corr = sum((x-mean(x))*(y-mean(y))) / (std(x)*std(y))` ≡ **n × Pearson_r**.
4. Algebraic identity proven by construction: `evidence/PEARSON_VERIFIER_SELFTEST.json` (`buggy_formula_is_n_times_pearson=true`).

## Derived (conditional) Pearson

```
DERIVED_CONDITIONAL_PEARSON = 61.91569544528234 / 102 = 0.6070166220125719
```

- Valid **because** the executed formula identity is now proven at bytecode level against the hash-anchored artifact (upgrades the prior checkpoint's "valid only IF" status).
- Still **`NOT_INDEPENDENT_RECOMPUTATION`**: input arrays were not persisted, so this is an exact algebraic inversion of the published statistic — forensic reconciliation evidence, **not** primary experiment evidence.
- Historical git references `f0c246f2…` / `1efbe3e1…` do not resolve as valid git objects (verified with `git cat-file -t` / `git rev-parse --verify`) and were not relied upon.

## Governance effect

- `H5_RESULT = DISCOVERY_FAIL` — unchanged, terminal (sha256 `2427310d…` verified).
- Prereg manifest sha256 `29ececb7…` — unchanged.
- `H5_RERUNS = 0` · `promotion_effect = NONE`.
- Note: corrected r ≈ 0.607 sits below the frozen 0.7 redundancy bar, but the overlap statistic (0.916) still flags momentum dependence — and no orthogonality reconciliation can promote a DISCOVERY_FAIL hypothesis.
