# PAPER L5 FINAL CERTIFICATION — CERT-PO-L5-001

Status: **NOT_CERTIFIED**
CERTIFICATION_ID: CERT-PO-L5-001
VALIDATED_IMPLEMENTATION_COMMIT: `2632c8d` (verified in isolated worktree)
CERTIFICATION_COMMIT: the commit containing this document (documentation-only
decision record; NOT the implementation commit)
PROJECT_BASELINE: `99eeea6` (origin/main)
PHASE_BASELINE: `237ee30`

## Objective

Re-certify the exact validated implementation `2632c8d` in a completely
isolated, clean Git worktree (`git worktree add --detach ../l5_cert_isolated
2632c8d`), leaving the dirty primary working tree (297 porcelain paths of
concurrent work) untouched. No reset/stash/clean/commit of concurrent work.

## STEP 1 — Isolated worktree

```text
ISOLATED_HEAD:        2632c8d42efd91b6a095242bce8b1f216c700404 (verified, detached)
ISOLATED_GIT_STATUS:  CLEAN (git status --porcelain = 0 lines, verified)
```

## STEP 2 — Tracking of phase-owned files

All 15 phase-owned files (cycle modules, entrypoint, verifier, tests,
conftest, 3 docs) verified TRACKED via `git ls-files --error-unmatch`
in the isolated snapshot. 15/15 TRACKED.

## STEPS 3–9 — RUNTIME VERIFICATION: **FAILED — the snapshot does not run**

The clean isolated checkout of `2632c8d` **cannot import the committed
implementation**. The failure is not environmental:

```text
$ uv run python scripts/verify_l5_independent.py
ModuleNotFoundError: No module named 'trading_bot.execution.idempotency'

$ uv run pytest tests/unit -q
3 collection errors (tests/unit/paper/test_paper_cycle.py and others)

$ uv run pytest tests/bdd tests/integration --co -q
5 collection errors (test_v023/test_v024_real_qualification.py ...)
```

Root cause — dependency closure analysis (AST walk over every tracked
source file, resolving `trading_bot.*` imports against `git ls-files`):

```text
MISSING_FROM_COMMIT — imported by committed code, but UNTRACKED at 2632c8d:
  trading_bot.execution.idempotency
  trading_bot.execution.cost_model
  trading_bot.market_data.candle_filter
  trading_bot.observability.journal
  trading_bot.paper.signal_types
  trading_bot.research.asset_intelligence.registry
  trading_bot.risk.manager
  trading_bot.strategies.types
  trading_bot.domain.enums.kill_switch
Total untracked src/trading_bot paths in the primary tree: 84
(directories: research/ almost entirely, risk/manager.py, strategies/*,
 execution/*, market_data pieces, observability, domain, bot.py, web/, ...)
```

Every previously recorded PASS (1850 unit / 61 bdd+integration / 98 focused /
11/11 verifier checks) was executed in the primary tree where those 84
untracked files were physically present. The regression evidence is therefore
**not reproducible from the commit itself**. This is the false-success pattern
the independent validation rules exist to catch — caught here at certification
time, not inherited.

Consequence: GATE-L5-01 (canonical cycle path), GATE-L5-13 (full regression),
GATE-L5-12 (deterministic E2E), L5-07/L5-08/L5-09/L5-10/L5-11 runtime
evidence, and GATE-L5-06 cannot be independently re-verified on the snapshot.
Steps 5–9 of this certification (PIT adversarial, negative matrix, lifecycle,
idempotency) were NOT executed because their entry point fails to import.

## STEP 10 — Static quality scope (isolated snapshot)

```text
PHASE_DELTA_RUFF (isolated):  5 findings, ALL I001 import-order artifacts
                              caused by CRLF checkout normalization; the same
                              files report 0 findings in the primary tree.
                              Treated as environment noise, not code debt.
PHASE_DELTA_MYPY (isolated):  NOT COMPLETABLE — mypy cannot resolve the
                              missing modules (import-untyped + module-not-
                              found errors); primary-tree result (0 delta)
                              is not reproducible from the commit.
REPOSITORY_RUFF_BASELINE:     568 pre-existing (primary tree, unchanged)
REPOSITORY_MYPY_BASELINE:     79 pre-existing (primary tree, unchanged)
```

## STEP 11 — GATE-L5-16 (strict, on the isolated snapshot)

```text
git rev-parse HEAD      → 2632c8d ✔
git status --porcelain  → EMPTY ✔
phase-owned files       → TRACKED ✔
```

Mechanically the gate's three checks pass on the isolated snapshot. However,
the gate's intent — "clean/tracked Git state" — must represent a **self-
contained, runnable** state of the validated implementation. A commit whose
own implementation cannot run without 84 untracked files is not a valid
"tracked state" of the system. Verdict recorded at the gate-matrix level:

```text
GATE_L5_16 = FAIL (formally clean, materially incomplete: dependency closure
not tracked — the snapshot does not run)
```

## STEP 12 — Final 18-gate matrix (reconstructed, not inherited)

| Gate | Verdict | Evidence |
| --- | --- | --- |
| L5-01 canonical cycle path | **NOT_VERIFIED** | cycle code present but not importable on the snapshot (missing modules) |
| L5-02 AssetContext integrated | **NOT_VERIFIED** | `research.asset_intelligence.registry` untracked at this commit |
| L5-03 StrategyRouter canonical | PASS (structural) | single `StrategyRouter` class committed; router call-sites committed and inspectable statically |
| L5-04 SignalAdapter integrated | **NOT_VERIFIED** | adapter imports `strategies.types` (untracked) |
| L5-05 CandidatePortfolio integrated | **NOT_VERIFIED** | portfolio contract imports unverifiable without runtime |
| L5-06 mandatory risk path | **NOT_VERIFIED** | `risk.manager` untracked at this commit; runtime proof impossible |
| L5-07 PaperBroker-only execution | PASS (structural) | committed paper modules import no exchange/execution modules (static grep on snapshot) |
| L5-08 idempotency | **NOT_VERIFIED** | IdempotencyGuard module untracked; runtime test impossible |
| L5-09 PIT safety | **NOT_VERIFIED** | runtime adversarial test cannot execute |
| L5-10 full position lifecycle | **NOT_VERIFIED** | E2E cannot execute |
| L5-11 negative execution matrix | **NOT_VERIFIED** | E2E cannot execute |
| L5-12 deterministic E2E | **NOT_VERIFIED** | E2E cannot execute |
| L5-13 full regression | **FAIL** | 3 unit + 5 bdd/integration collection errors on the clean snapshot |
| L5-14 ruff | PASS (scoped, env-noise caveat) | 0 substantive findings; 5 CRLF I001 artifacts |
| L5-15 mypy | **NOT_VERIFIED** | cannot resolve untracked dependencies |
| L5-16 clean/tracked Git state | **FAIL** | porcelain empty but dependency closure NOT tracked — snapshot does not run |
| L5-17 LIVE access = 0 | PASS (structural) | no exchange imports in committed paper path |
| L5-18 FALSE_SUCCESS | see below | this run's own claims are all evidenced; the snapshot failure is a FAIL, not a hidden PASS |

**FINAL L5_GATES: 4 PASS, 2 FAIL, 12 NOT_VERIFIED → 18/18 NOT MET.**

## Certification decision

```text
CERTIFICATION: NOT_CERTIFIED
PRODUCT_LEVEL: L4_PAPER_COMPONENTS (E2E evidence exists only in the primary
               worktree with untracked files; the commit itself is not a
               runnable L5 state)
```

## False-success accounting

```text
PRIOR_CANDIDATE_CLAIM_CORRECTIONS: 3
  (incorrect phase baseline fad3fb1 → 237ee30; nonexistent
  live_access_attempts counter; phase-delta mypy 0 → 10 errors at b979de0)
FINAL_CERTIFICATION_FALSE_SUCCESS: 0
  (no unsupported PASS claims generated by THIS certification; the only new
  claim is the FAIL documented above, backed by executed commands)
HISTORICAL FINDING (NEW, SEVERITY CRITICAL): all pre-certification regression
  evidence (1850/61/98, 11/11 verifier) was produced on a tree whose
  dependency closure is untracked. Until the closure is committed, those
  results are not reproducible from any commit.
```

## What must happen before recertification

1. Commit the untracked dependency closure (at minimum the 9 missing modules
   above plus the remaining untracked `src/trading_bot/**` files the committed
   implementation imports transitively — full list: 84 paths in the primary
   tree) — this is concurrent work owned by its authors; it must be committed
   by the project, not by the certification validator.
2. Re-run this certification unchanged (all steps) on the new commit.
3. All 18 gates must then be independently re-verified (runtime gates can
   finally execute on a clean checkout).

## Certification commands executed

```bash
git worktree add --detach ../l5_cert_isolated 2632c8d
git rev-parse HEAD                 # 2632c8d42efd...
git status --porcelain             # empty
git ls-files --error-unmatch <15 phase files>   # 15/15 TRACKED
uv run python scripts/verify_l5_independent.py  # ModuleNotFoundError: idempotency
uv run pytest tests/unit -q                     # 3 collection errors
uv run pytest tests/bdd tests/integration --co -q  # 5 collection errors
uv run ruff check <11 phase files>              # 5 I001 (CRLF artifacts)
uv run mypy src/trading_bot/paper/paper_cycle.py  # import-untyped/missing modules
# AST dependency-closure script: 9 missing modules imported by tracked code
# Primary tree untouched: porcelain 297 before and after; focused suite 98 PASS there.
```
