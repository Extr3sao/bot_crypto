# VERIFIER_EVIDENCE_python_import_authority.md — H6 V3 Python Import Authority Gate

**Gate:** `PYTHON_IMPORT_AUTHORITY`
**Verdict:** `PYTHON_IMPORT_AUTHORITY = PASS` (after verifier-local remediation)
**Machine-readable:** `VERIFIER_EVIDENCE_python_import_authority.json`
**Script:** `verifier_python_import_authority.py`
**Audited target:** `a5487164803fb601f87f2cd4c865929c30da274e`
**Verifier worktree:** `C:\Users\GVLLFR0035\Downloads\bot freebuff\.worktrees\h6-external-verifier-v3`

---

## 1. The defect: the shared venv pins the MAIN checkout

Interpreter: `C:\Users\GVLLFR0035\Downloads\bot freebuff\.venv\Scripts\python.exe` (CPython 3.11.15).

The venv lives **inside the main checkout** (`…bot freebuff/.venv`), and git worktrees share it.

`…/.venv/Lib/site-packages/` contains:

| `.pth` file | content |
|---|---|
| `__editable__.crypto_scalping_agentic_bot-0.1.0.pth` | `C:\Users\GVLLFR0035\Downloads\bot freebuff\src` |
| `_virtualenv.pth` | `import _virtualenv` |
| `a1_coverage.pth` | coverage startup hook |
| `distutils-precedence.pth` | setuptools shim |

The editable-install `.pth` contains an **absolute path to the MAIN checkout's `src`**. `.pth`
files are processed during `site` initialisation, so that directory is appended to `sys.path` for
**every** interpreter launched from **any** worktree.

### Empirical proof (no `PYTHONPATH`, cwd = verifier worktree)

```
$ cd .worktrees/h6-external-verifier-v3
$ python -c "import trading_bot; print(trading_bot.__file__)"
C:\Users\GVLLFR0035\Downloads\bot freebuff\src\trading_bot\__init__.py
```

The resolved path is the **main checkout**, *outside* the verifier worktree.
`resolved_outside_verifier_worktree = true`.

`sys.path` observed:

```
['', …cpython-3.11…, '…bot freebuff\.venv', '…bot freebuff\.venv\Lib\site-packages', '…bot freebuff\src']
```

### Why this matters concretely

The main checkout is on branch `feat/ma-2-specialist-opportunity-swarm` at `0941082fc8…` — which is
the **base commit**, i.e. *before* the V3 repair commits. Its working tree additionally carries
uncommitted edits to `src/trading_bot/research/h6/conf_lock.py` and
`src/trading_bot/research/h6/whitelist.py`.

So a verifier that trusts a bare import executes **pre-repair code** while believing it is auditing
`a548716`. Independently confirmed divergence: `src/trading_bot/research/oi_dataset_v2.py`

```
audited commit a548716 : sha256 8e2803cfdbfc002363bf8d9cf6cebaa892f144fc7e13b6669596775d82a89b62
main checkout (bare)   : sha256 e91d56b7b957ad47b6937f7a7b1a18e87c4c2af98fd1ca611930bdbcd39f604a
```

This file was rewritten by repair commit `f048520 [H6-V3-01] repair whitelist/hash/data/PIT
portability`. The bare-import path also resolves `conf_lock.py`, `whitelist.py`,
`confirmation_state.py` and `hash_validator.py` to a tree that is not the audited one.

**Any H6 result produced without an explicit import override has unproven target authority.**

## 2. Verifier-local remediation (builder code NOT modified)

Method: prepend the verifier worktree's own `src` to `sys.path` via `PYTHONPATH`.

```
PYTHONPATH=<verifier worktree>/src python <script>
```

`PYTHONPATH` entries are placed on `sys.path` *before* site-packages-derived directories, so the
worktree's `src` wins the resolution race. No file in the builder tree, venv, or `.pth` was changed.

### Proof

```
$ cd .worktrees/h6-external-verifier-v3
$ PYTHONPATH="$(pwd)/src" python -c "import trading_bot,pathlib;print(pathlib.Path(trading_bot.__file__).resolve())"
C:\Users\GVLLFR0035\Downloads\bot freebuff\.worktrees\h6-external-verifier-v3\src\trading_bot\__init__.py
```

## 3. Module-by-module authority (28 modules)

All 28 critical modules were probed under the remediation. For each: resolved path starts with the
verifier worktree root, and its **on-disk bytes were SHA256-compared against the blob at
`a548716`**.

| module | resolves inside verifier worktree | bytes == audited blob |
|---|---|---|
| `trading_bot` | ✅ | ✅ |
| `trading_bot.research.h6` | ✅ | ✅ |
| `trading_bot.research.h6.whitelist` | ✅ | ✅ |
| `trading_bot.research.h6.conf_lock` | ✅ | ✅ |
| `trading_bot.research.h6.confirmation_state` | ✅ | ✅ |
| `trading_bot.research.h6.execution_ledger` | ✅ | ✅ |
| `trading_bot.research.h6.execution_harness` | ✅ | ✅ |
| `trading_bot.research.h6.eligibility` | ✅ | ✅ |
| `trading_bot.research.h6.feature_engine` | ✅ | ✅ |
| `trading_bot.research.h6.contamination_scan` | ✅ | ✅ |
| `trading_bot.research.h6.drift_guard` | ✅ | ✅ |
| `trading_bot.research.h6.contracts` | ✅ | ✅ |
| `trading_bot.research.h6.cost` | ✅ | ✅ |
| `trading_bot.research.h6.hash_validator` | ✅ | ✅ |
| `trading_bot.research.h6.assertions` | ✅ | ✅ |
| `trading_bot.research.h6.external_verification` | ✅ | ✅ |
| `trading_bot.research.h6.gate_config` | ✅ | ✅ |
| `trading_bot.research.h6.funding` | ✅ | ✅ |
| `trading_bot.research.h6.result_schema` | ✅ | ✅ |
| `trading_bot.shadow` | ✅ | ✅ |
| `trading_bot.shadow.resolver` | ✅ | ✅ |
| `trading_bot.shadow.integration` | ✅ | ✅ |
| `trading_bot.shadow.outcome` | ✅ | ✅ |
| `trading_bot.shadow.capture` | ✅ | ✅ |
| `trading_bot.shadow.reject_metrics` | ✅ | ✅ |
| `trading_bot.shadow.router` | ✅ | ✅ |
| `trading_bot.execution.service` | ✅ | ✅ |
| `trading_bot.execution.idempotency` | ✅ | ✅ |

- non-`OK` modules: **0**
- on-disk vs audited-blob mismatches: **0**
- modules untracked at `a548716`: **0**

The verifier worktree works on a clean checkout, so "resolved inside the worktree" is strengthened to
"byte-identical to the audited commit".

## 4. Contamination delta (worktree `src` vs main checkout `src`)

- Python files differing: **1** — `trading_bot/research/oi_dataset_v2.py`
- Python files present only in the main checkout: **0**

## 5. pytest is separately protected (and that is not enough)

Repository root `conftest.py` force-prepends *this* worktree's `src`:

```python
_SRC = str((Path(__file__).resolve().parent / "src").resolve())
if sys.path and Path(sys.path[0]).resolve() != Path(_SRC):
    if _SRC in sys.path:
        sys.path.remove(_SRC)
    sys.path.insert(0, _SRC)
```

So pytest runs are safe. **Non-pytest verifier scripts have no such protection** and must set
`PYTHONPATH` explicitly. A previous verifier session had already observed this hazard
(`VERIFIER_ENVIRONMENT.md`); this gate confirms it empirically and closes it.

## 6. Mandatory rule for the rest of this audit

Every verifier command that imports project modules MUST:

1. run from the verifier worktree, and
2. set `PYTHONPATH=<verifier worktree>/src`, and
3. print the resolved `__file__` of every project module it uses.

Any result produced before this gate without the override must be treated as
`IMPORT_AUTHORITY_UNPROVEN`.

## 7. Gate result

| check | result |
|---|---|
| bare import contaminated | true (defect present, as the builder itself suspected) |
| all critical modules resolve inside worktree under remediation | **PASS (28/28)** |
| resolved modules byte-identical to audited commit | **PASS (0 mismatches)** |
| builder code modified by remediation | **none** |
| **`PYTHON_IMPORT_AUTHORITY`** | **PASS** |

## 8. Residual risks

- The override is **per-invocation**; a future `pip install -e` re-pins the main checkout.
- `.pth`-based contamination is invisible in `import trading_bot` output unless `__file__` is
  printed; a verifier that omits that print can be wrong without any error.
- `trading_bot.research.h6.dataset` (listed in an earlier environment record) **does not exist** in
  this codebase; the H6 package's dataset/authority logic lives elsewhere. Any checkpoint that
  assumes that module name must be corrected rather than "verified".
