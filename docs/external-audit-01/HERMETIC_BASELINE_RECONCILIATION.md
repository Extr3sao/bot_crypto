# HERMETIC BASELINE RECONCILIATION — ALPHA-DATA-ADMISSION-01 / HERMETIC-BASELINE-RECONCILIATION-01

**Previous checkpoint status corrected: `PASS → REPAIR_REQUIRED`** (FALSE_SUCCESS=0 policy: 1235 passed / 2 failed was never a PASS). Both failures are now root-caused, repaired, and independently proven. Machine-readable: `HERMETIC_BASELINE_RECONCILIATION.json`.

## Track A — Clean baseline

- Disposable detached worktree at **`cb3de4f`** (clean baseline, not the dirty research tree): `git status --porcelain` clean, guard 3/3 PASS.
- Environment recorded: Python **3.11.15**, pytest **9.1.1**, uv **0.11.26**, Windows (bash toolchain).
- Host env: `EXCHANGE_ID=bybit` SET (contamination source); `EXCHANGE_SANDBOX`, `EXCHANGE_API_KEY/SECRET`, `BINANCE_API_KEY/SECRET` SET — values never read or recorded; `PYTHONPATH` not set on host (set to `src` explicitly for runs).

## Track A1 — Settings test: `HOST_ENVIRONMENT_CONTAMINATION`

| EXCHANGE_ID (clean baseline @ cb3de4f) | Result |
| --- | --- |
| `bybit` (host value) | **FAIL** |
| unset | PASS |
| `binance` | PASS |
| `garbage` | **FAIL** |

**Verdict: `FAILURE_IS_HOST_ENV_CONTAMINATION`** — the baseline code is correct; the test was not hermetic. The settings loader maps flat env aliases (`EXCHANGE_ID → exchange.id`, …) and the test did not control them.

**Repair (preferred per protocol):** the test now neutralizes documented flat env aliases and explicitly supplies the configuration it expects. Application defaults untouched. Adversarial matrix after repair (main tree): **26/26 PASS under unset / binance / bybit / garbage** — result is independent of host `EXCHANGE_ID`.

## Track A2 — Dependency closure: `UNTRACKED_IMPORTED_H5_SOURCE`

The guard inspects imported `trading_bot.*` modules and requires them to be git-tracked (clean-checkout contract). `src/trading_bot/research/h5_orderflow.py` (H5 execution code family) was imported by the suite but **untracked** — that is why the guard failed in the full suite and passed in isolation. **This is not a test-ordering artifact:**

- full-suite failure lists exactly the untracked H5 module(s);
- the guard passes 3/3 in a clean worktree at `cb3de4f` (which predates H5);
- it fails in the main tree until the files are tracked.

**Repair:** H5 code family tracked in scoped commit **`692286b`** (code only). The guard was **not** weakened. Classification: `DEF-TEST-ISOLATION-001 CONFIRMED + FIXED` (isolation defect was repo hygiene, not ordering).

## Track A3 — Final hermetic gate (after ALL checkpoint code was added)

```
env -u EXCHANGE_ID -u EXCHANGE_SANDBOX -u EXCHANGE_API_KEY -u EXCHANGE_SECRET \
    -u BINANCE_API_KEY -u BINANCE_SECRET PYTHONPATH=src \
    .venv/Scripts/python.exe -m pytest tests -q
→ 1259 passed, 0 failed, 0 skipped (176 s) @ commit ec2483f
```

No exclusions, no skips, no "pre-existing" exceptions. `FALSE_SUCCESS = 0`.

## Commits

| Commit | Scope |
| --- | --- |
| `692286b` | HERMETIC-BASELINE-RECONCILIATION-01: track H5 execution code family (4 files) |
| `ec2483f` | data-admission src/scripts/tests + hermetic settings repair (8 files) |

## Worktree status (honest statement)

The repository is **not git-clean overall**: checkpoint evidence (`docs/external-audit-01/**`, `docs/audit/**`) and raw/normalized data (`data/raw/**`, `data/processed/**`) are untracked **by design** (evidence and multi-GB data are not code; the Track-O report set is generated after the gate, so it cannot be inside the gate commit). The **tracked-code surface is clean and clean-checkout reproducible** — which is the contract the dependency guard enforces. `his.zip` is a pre-existing unrelated user archive (2026-08-22), untouched.
