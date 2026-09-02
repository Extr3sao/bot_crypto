# PAPER L5 INDEPENDENT VALIDATION — VER-PO-L5-001

Status: **PAPER_OPERATIONAL_E2E_VALIDATED — INDEPENDENT_CERTIFICATION = NOT_CERTIFIED**
Validator: independent re-verification of CP-PO-002 (no trust in candidate claims)
CANDIDATE_COMMIT verified: `b979de0`
Validation artifact: `scripts/verify_l5_independent.py` (11/11 checks PASS, ruff+mypy clean)

## Step 1 — Git provenance (reconstructed independently)

```text
PROJECT_BASELINE:  99eeea6 (origin/main — upstream divergence point, not fad3fb1)
PHASE_BASELINE:    237ee30 (commit immediately preceding the FASE 7B-8C implementation;
                   the candidate doc's claim "BASELINE_COMMIT: fad3fb1" is corrected:
                   fad3fb1 precedes several earlier paper phases, not this one)
CANDIDATE_FINAL:   b979de0 (HEAD -> main)
ANCESTRY:          5804dfd, 398ab38, b979de0 all verified ancestors of HEAD
                   (git merge-base --is-ancestor)
PHASE_DIFF:        237ee30..5804dfd = 12 files, +1849/-31 (canonical cycle + tests)
```

## Step 2 — GATE-L5-16 resolved strictly

```text
REPOSITORY_WORKTREE_CLEAN:   NO  (54 modified + 220 untracked paths; pre-existing
                             concurrent drift incl. tests/bdd/conftest.py TSK-022.7
                             glue +876 lines, docs/* reports, config/* edits)
PHASE_OWNED_FILES_TRACKED:   YES (14/14 verified with git ls-files --error-unmatch)
PHASE_OWNED_FILES_CLEAN:     YES (14/14 verified with git diff --quiet HEAD -- <file>)
UNRELATED_PREEXISTING_DRIFT: 54 modified + ~220 untracked paths, none phase-owned
```

The original gate reads "clean/tracked Git state" without a phase-scoped clause.
The candidate implicitly applied a phase-scoped interpretation while claiming
18/18. Per the validation contract (do not redefine gates retroactively):

**GATE-L5-16 = FAIL (worktree not clean).** Phase-owned artifacts are tracked
and clean; repository-level cleanliness is not met.

## Step 3 — Canonical architecture (verified from code)

Call-site census (`grep -rn` over src/ scripts/):

- `PaperBroker.execute_signal`: exactly 2 runtime call sites —
  `paper/paper_cycle.py:332` (behind `RiskManager.check_signal` approval,
  verified by code reading: lines 306-331 reject/close on every non-approval
  path) and `bot.py:403` (guarded by `result.risk_check_approved` from
  `TradingPipeline.tick`, which itself runs `risk_manager.check_signal` first).
  No path reaches `execute_signal` for a NEW position without risk approval.
- `RiskManager.check_signal`: `paper/paper_cycle.py:306` (canonical cycle) and
  `strategies/pipeline.py:93` (TradingPipeline — same RiskManager class,
  same approval contract; this is convergence, not duplication).
- `StrategyRouter.route`: only `paper/paper_cycle.py:203, 388` (RouteOnlyEngine).
  Exactly one `class StrategyRouter` exists (`research/strategy_router.py:81`).
- No symbol hardcoding in `paper_cycle.py` / `harness.py` / `paper_orchestrator.py`
  (grep for BTC/ETH/SOL literals: no matches).

**CANONICAL_RUNTIME = PASS** (no competing runtime path for new PAPER orders).

## Step 4 — Execution boundary

- Grep of the 3 new cycle modules + bridge for `ccxt|bitunix|api_key|credentials|exchange_connector`: **zero matches** (also reproduced inside `scripts/verify_l5_independent.py`).
- Only `execution/` import in the cycle is `IdempotencyGuard` (a plain dataclass; not LIVE infrastructure).
- `PaperBroker` imports no exchange/execution modules.
- Entrypoint refuses `runtime.mode != PAPER` before constructing anything.
- `live_access_attempts` named counter: **DOES NOT EXIST** — candidate doc overstated this. The equivalent evidence is structural (no exchange imports anywhere in the paper path) + zero-match greps + PaperBroker-only call sites.
- `LIVE_ACCESS_ATTEMPTS = 0` (structurally proven; no counter named as claimed).

## Step 5 — PIT safety (independent adversarial test)

Injected 30 bars stamped AFTER the decision timestamp into the engine's history
(`scripts/verify_l5_independent.py`, GATE-L5-09):

```text
trim_to_pit(130 bars, ts=bar99) -> 100 bars (all 30 future bars excluded)
engine: contexts_built=1, risk_accepted=1, orders_created=1, strategy_errors=0
```

The context was built ONLY from the 100-bar PIT slice. Additionally verified:
`FetcherBarReader` caps fetch server-side; `snapshot_context.trim_to_pit`
filters `bar.timestamp <= decision_timestamp` (bar AT the decision ts included
as the completed bar); engine applies `_pit_slice` before any feature/context
computation; context carries `data_fingerprint` (sha256 of exact bars) +
`window_end_ts`. Dedicated tests: `test_pit_trim_excludes_future_bars` PASSED.

**GATE-L5-09 PIT = PASS.**

## Step 6 — Strategy router & map

- Exactly one `StrategyRouter` implementation in the runtime (GATE-L5-03).
- Regime: `context.market_regime` — the same regime embedded in the AssetContext
  built by `CryptoAssetAgentRegistry` is what is passed to `route()`. Traceable,
  no second classifier (GATE-L5-02).
- Strategy-map source: **composition-injected** (not config-backed, not
  registry-backed): `scripts/start_paper_trading.py::build_cycle_engine`
  builds one preregistered entry per committed AlphaFamily. Nothing hardcoded
  inside the runner; the map is an injected constructor argument.

## Steps 7–8 — Negative matrix & idempotency (independently reproduced)

`scripts/verify_l5_independent.py` (independent script, not the committed tests):

```text
PASS NEG no strategy            (empty map -> router_no_trade, orders=0)
PASS NEG strategy exception     (BoomFamily -> orders=0)
PASS NEG invalid/empty context  (no bars -> context error, orders=0)
PASS NEG risk rejection         (daily loss exhausted -> orders=0)
PASS NEG risk exception         (check_signal raises -> orders=0)
PASS NEG stale data             (decision ts after last bar -> orders=0)
PASS NEG broker exception       (execute_signal raises -> orders=0)
PASS GATE-L5-08 idempotency     (same intent twice -> 1 execution, 1 duplicate_intents)
```

Plus committed engine matrix (all PASSED, run fresh):
`test_router_no_trade_empty_map_zero_orders`, `test_router_exception_zero_orders`,
`test_strategy_exception_zero_orders`, `test_direction_mismatch_zero_orders`,
`test_risk_rejection_zero_execution`, `test_risk_exception_zero_execution`,
`test_duplicate_intent_exactly_one_execution`, `test_context_error_fail_closed`,
`test_route_only_engine_counts_and_fail_closed`.

**GATE-L5-11 = PASS. GATE-L5-08 = PASS.**

## Step 9 — Position lifecycle E2E (independently reproduced)

Through the REAL `PaperSessionRunner` (scanner + same-source history reader +
cycle engine), seeded `FakeMarketDataSource`:

```text
CYCLE 1 (rising BTC/ETH/SOL): 3 contexts, 3 risk accepts, 3 orders, positions open
CYCLE 2 (falling, offset bars): reconcile closes 3 positions,
    realized_pnl = -1492.02, report written (reports/paper/report.json)
opened=3, closed=3, nothing lost
```

**GATE-L5-10 = PASS. GATE-L5-12 = PASS** (deterministic, same run reproduced
identically across script invocations and the committed E2E-002 test).

## Steps 11–12 — Fresh regression and quality scope

```text
UNIT_REGRESSION:      1850 passed, 0 failed (tests/unit, fresh run)
BDD_INTEGRATION:      61 passed, 0 failed (tests/bdd + tests/integration, fresh run)
FOCUSED PAPER:        98 passed (unit/paper + e2e-001 + e2e-002, fresh run)

PHASE_DELTA_RUFF:     0 findings (11 phase-owned files)
REPOSITORY_RUFF:      568 pre-existing findings (baseline unchanged; matches
                      candidate claim; verified excluding the untracked
                      validation script)

PHASE_DELTA_MYPY:     0 after validator repair. INDEPENDENT FINDING: the
                      candidate's "0 phase delta mypy" was FALSE at b979de0 —
                      tests/integration/test_paper_e2e_001.py had 10
                      [no-untyped-call/def] errors (two untyped helpers).
                      Repaired during validation (type annotations only, no
                      behavior change; 9/9 E2E-001 tests still PASS).
REPOSITORY_MYPY:      79 pre-existing errors in 21 files (baseline unchanged)
```

## Step 13 — Independent 18-gate matrix

| Gate | Verdict | Evidence |
| --- | --- | --- |
| L5-01 canonical cycle path | PASS | call-site census; single route; E2E through real runner |
| L5-02 AssetContext integrated | PASS | registry-built context; regime traceable to router |
| L5-03 StrategyRouter canonical | PASS | one class; only cycle call sites; ADR recorded |
| L5-04 SignalAdapter integrated | PASS | alpha -> `alpha_signal_to_signal` -> Signal (code-verified) |
| L5-05 CandidatePortfolio integrated | PASS | `build_portfolio(candidates)` pre-risk in cycle |
| L5-06 mandatory risk path | PASS | execute_signal guarded by check_signal approval (both paths) |
| L5-07 PaperBroker-only execution | PASS | no exchange imports in paper path; PaperBroker-only call sites |
| L5-08 idempotency | PASS | independent script + committed tests |
| L5-09 PIT safety | PASS | adversarial future-bar injection rejected |
| L5-10 full position lifecycle | PASS | independent 2-cycle lifecycle reproduction |
| L5-11 negative execution matrix | PASS | 7 adversarial cases + 9 committed tests, all orders=0 |
| L5-12 deterministic E2E | PASS | reproduced identically, independent of committed test |
| L5-13 full regression | PASS | 1850 + 61 + 98 fresh passes |
| L5-14 ruff | PASS (scoped) | phase delta 0; repo baseline 568 (pre-existing, unchanged) |
| L5-15 mypy | PASS (scoped) | phase delta 0 AFTER validator repair (was 10); repo baseline 79 |
| L5-16 clean/tracked Git state | **FAIL** | worktree dirty: 54 modified + 220 untracked (all pre-existing/unrelated; phase-owned files are tracked+clean) |
| L5-17 LIVE access = 0 | PASS | structural proof (no exchange path); candidate's named `live_access_attempts` counter does NOT exist — claim corrected |
| L5-18 FALSE_SUCCESS = 0 | PASS | all PASS gates backed by executed commands/tests on this snapshot |

**INDEPENDENT_GATES: 17/18 PASS, 1 FAIL (L5-16), 0 NOT_VERIFIED.**

## Certification decision

Per the certification rule (18/18 required, no retroactive gate weakening):

```text
CERTIFICATION: PAPER_OPERATIONAL_E2E_VALIDATED_NOT_CERTIFIED
INDEPENDENT_CERTIFICATION = NOT_CERTIFIED
```

## Validator corrections to candidate claims (false-success accounting: 0)

1. `BASELINE_COMMIT fad3fb1` — corrected: phase baseline is `237ee30`; project
   baseline (origin/main) is `99eeea6`.
2. `live_access_attempts` counter — does not exist; LIVE=0 proven structurally.
3. `phase delta mypy = 0` — was 10 errors at `b979de0`
   (`test_paper_e2e_001.py` untyped helpers); repaired during this validation
   with type-only annotations.
4. GATE-L5-16 claimed PASS under an implicit phase-scoped reading — resolved
   strictly as FAIL per the original gate contract.

## What remains for certification

1. Commit or clean the 54 modified + 220 untracked pre-existing drift paths
   (or obtain explicit gate-contract approval for phase-scoped cleanliness),
   then re-verify `git status --short` = empty on the certification commit.
2. Re-run the 18-gate matrix on that exact commit.
3. Upon 18/18 on a clean snapshot: PAPER_OPERATIONAL_CERTIFIED.

## Validation commands executed

```bash
git rev-parse HEAD; git log --oneline --decorate -20; git merge-base --is-ancestor <sha> HEAD
git status --short; git ls-files --error-unmatch <14 phase files>; git diff --quiet HEAD -- <files>
grep -rn "\.execute_signal(\|check_signal(\|\.route(" src/ scripts/
grep -rniE "ccxt|bitunix|api_key|credentials|exchange_connector" src/trading_bot/paper/<cycle modules>
uv run python scripts/verify_l5_independent.py          # 11/11 PASS
uv run pytest tests/unit -q -p no:cacheprovider          # 1850 passed
uv run pytest tests/bdd tests/integration -q -p no:cacheprovider  # 61 passed
uv run pytest tests/unit/paper tests/integration/test_paper_e2e_001.py tests/integration/test_paper_e2e_002.py -q  # 98 passed
uv run mypy src/trading_bot                              # 79 pre-existing
uv run ruff check src tests <scripts minus validator>    # 568 pre-existing
uv run mypy <11 phase-owned files>                       # 0 errors
uv run ruff check <phase-owned files>                    # 0 findings
```
