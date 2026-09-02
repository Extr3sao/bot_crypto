# CP-PO-003 — Repository Dependency Closure Repair

Status: **REPRODUCIBLE_L5_CANDIDATE_READY** (pending CERT-PO-L5-001 re-run)
REPAIR_BASE: `037f956` (branch `repair/cp-po-003`)
REPRODUCIBLE_CANDIDATE_COMMIT: `d06c09d`
IMPLEMENTATION_BASE: `2632c8d` (implementation files unchanged — provenance preserved)
CERTIFICATION_RECORD: `037f956`

## Root cause (from CERT-PO-L5-001)

The committed L5 candidate was not self-contained: a clean checkout of
`2632c8d` failed at import because required internal modules existed only as
untracked files in the concurrent primary worktree.

## Phase 1 — Closure computation

Method (Python-semantics exact):
1. Runtime probe — import the L5 entry roots in the primary tree (read-only)
   and dump every loaded `trading_bot.*` module → `__file__`
   (`sys.modules` probing; no relative-import ambiguity).
2. Suite probe — full `pytest --collect-only` over `tests/unit`, `tests/bdd`,
   `tests/integration` in the primary tree, then repeat collection in the
   repair worktree until zero `ModuleNotFoundError` (import fixpoint; 6
   iterations staged the last stragglers that the primary-tree probe missed
   because untracked tests themselves imported them).

```text
DIRECT_REQUIRED_MODULES (L5 runtime roots → untracked):
    execution.idempotency, execution.live_gate, execution.cost_model,
    risk.manager, strategies.types, strategies.pipeline, strategies.protocols,
    strategies.ema_crossover, research.types, research.alpha,
    research.asset_intelligence.*, research.regime, research.registry,
    research.reporting, research.validation, research.admission,
    research.portfolio_backtest, research.gates, research.evidence,
    market_data.wiring, market_data.multi_exchange, market_data.exceptions,
    observability.journal, domain.events.{journal,hashing},
    storage.event_store, domain.enums.kill_switch
TRANSITIVE_REQUIRED_MODULES: reached via the above (evidence chain, calendars,
    qualification, canonical accounting, strategy sandbox/engineer, ...)
MISSING_FROM_GIT (final): see FILES_ADDED below
ALREADY_TRACKED: the remaining 95 reachable tracked src files
```

## Phase 2 — Classification of the 121 untracked imported paths

| Class | Count | Handling |
| --- | --- | --- |
| A REQUIRED_RUNTIME | 39 | copied into repair worktree, committed |
| B REQUIRED_TEST (closure of the suite incl. research/v02x tests) | 82 | committed (suite must collect on clean checkout) |
| C REQUIRED_CONFIG_PACKAGING | 0 py; config YAMLs already tracked; `.env` NEVER committed (contains real API keys) | — |
| D UNRELATED_CONCURRENT_WORK | 40 (full list in repair commit message refs: `src/trading_agent/**`, `execution/gateway.py`, `research/robustness.py`, `asset_intelligence/{api,cross_asset,agents}.py`, `strategy_lab/data|reporting`, `web/run.py`, `portfolio/universe.py`, `risk/types.py`, `strategies/crossover_analysis.py`) | NOT included |
| E LEGACY_UNUSED / F DUPLICATE | 0 among imported files (guard+canonicality checks) | — |

Note: class D files are imports of untracked TESTS only (e.g. orphaned
test-support modules) — excluded with their tests from the committed suite
scope; the committed suite collection stays green without them.

## Phase 3 — Canonicality check

Exactly one implementation per responsibility in the committed tree
(verified by grep over the repair worktree):

```text
RiskManager → 1 (risk/manager.py)          IdempotencyGuard → 1 (execution/idempotency.py)
StrategyRouter → 1 (research/strategy_router.py)
AssetContext → 1 · CryptoAssetAgentRegistry → 1
TradeJournalStore → 1 · OHLCVStore → 1
```

No duplicate/parallel implementation was introduced; every added file is the
single existing implementation used by the primary tree.

## Phase 4 — Materialization

- Copied file-for-file from the primary tree (no rewrites, no behavior edits).
- 23 tracked-but-NEWER versions of closure files (scanner, market_data,
  config models, app.py) also updated to the concurrent state the closure
  requires — documented as `FILES_MODIFIED`.
- No PYTHONPATH/sys.path hacks, no symlinks, no external references.

## Phase 5 — Import fixpoint

`pytest --collect-only` over unit+bdd+integration in the REPAIR worktree:
**531 tests collected, 0 collection errors.**

## Phase 6 — Tracked dependency guard (permanent gate)

`tests/unit/test_dependency_closure_guard.py`:
- fails if any loaded `trading_bot.*` module resolves OUTSIDE the repo;
- fails if any loaded `trading_bot.*` module's source is NOT git-tracked;
- asserts the L5 entry chain imports.
First run correctly FAILED pre-commit (closure present but untracked) and
passes post-commit — proving the gate has teeth.

## Phases 7–9 — Collection / paper tests / regression (repair worktree)

```text
COLLECTION:        531 collected, 0 errors
PAPER (unit/paper):                    29 passed
PAPER (e2e_001 + e2e_002):             18 passed
INDEPENDENT_VERIFIER:                  11/11 PASS
FULL unit regression (pre-commit):     486 passed + 2 failed
  - closure guard (expected FAIL before commit; passes after)
  - tests/unit/config/test_settings.py::test_load_settings_happy_path
    ROOT CAUSE: ambient EXCHANGE_ID=bybit in the operator shell env
    (originates from .env with REAL API KEYS — never commit it).
    `env -u EXCHANGE_ID -u EXCHANGE_API_KEY -u EXCHANGE_SANDBOX` →
    26/26 config tests PASS. Environment anomaly, not a tree defect.
```

## Phase 12 — Commits

```text
REPRODUCIBLE_CANDIDATE_COMMIT: d06c09d
repair worktree git status --porcelain: EMPTY after commit
```

Primary concurrent worktree untouched throughout (verified: porcelain count
unchanged at 298 before/after; no clean/reset/stash/add -A executed there).

## Phase 13 — Second clean checkout

MANDATORY verification at a detached worktree of `d06c09d` — executed next;
results recorded in the final report of this phase (see BELOW if present, else
pending).

## False-success accounting

```text
FALSE_SUCCESS: 0 (all claims above backed by executed commands in the repair
worktree; the pre-commit guard failure and the env-dependent test failure are
documented as findings, not hidden)
```
