# CP-PO-003.1 — Pre-Certification Hygiene Record

## Status: READY_FOR_FINAL_L5_CERTIFICATION

```text
CHECKPOINT_ID:            CP-PO-003.1
PRE_CERT_BASE:            2c0be60
PRE_CERT_CANDIDATE_COMMIT: 05fca62
```

Commit chain on `repair/cp-po-003`:

```text
2c0be60  docs(repo): record CP-PO-003 reproducibility repair      (PRE_CERT_BASE)
411fc23  fix(execution): remove idempotency lint defects          (STEP 1)
83f2cf9  test(cert): enforce hermetic paper certification env     (STEP 3/4)
2567405  chore(cert): add package marker for unit cert tests
05fca62  chore(ruff): exclude shell scripts from Python linting   (STEP 5)
```

## STEP 1 — Idempotency F401 repair

- `src/trading_bot/execution/idempotency.py`: removed 3 unused imports
  (`datetime`, `timedelta`, `Optional`). Purely lexical.
- `IDEMPOTENCY_F401_BEFORE: 3` → `IDEMPOTENCY_F401_AFTER: 0`.
- `RUNTIME_BEHAVIOR_CHANGED: NO` (47 paper tests + verifier 11/11 PASS unchanged).

## STEP 3 — Certification environment contract

`scripts/cert_env.sh`: hermetic wrapper that unsets every live-selecting /
credential variable before `exec "$@"`, then exports `CERT_HERMETIC=1` so the
permanent guard is active. Scrub list (23 vars, mirrors the guard list,
drift-enforced by test):

- Flat FLAT_ENV_ALIASES (trading_bot/config/settings.py): `TRADING_MODE`,
  `LIVE_TRADING_ENABLED`, `I_UNDERSTAND_THE_RISKS`, `EXCHANGE_ID`,
  `RUNTIME_EXCHANGE_ID`, `EXCHANGE_SANDBOX`, `EXCHANGE_API_KEY`,
  `EXCHANGE_API_SECRET`, `EXCHANGE_PASSWORD`
- Direct `os.getenv` consumers (bitunix.py / bitunix_futures.py):
  `BITUNIX_API_KEY`, `BITUNIX_API_SECRET`
- Generic credentials + persistence: `API_KEY`, `API_SECRET`, `DATABASE_URL`
- pydantic-settings nested forms (`env_nested_delimiter="__"`):
  `RUNTIME__MODE`, `RUNTIME__LIVE_TRADING_ENABLED`, `RUNTIME__EXCHANGE_ID`,
  `RUNTIME__I_UNDERSTAND_THE_RISKS`, `EXCHANGE__ID`, `EXCHANGE__SANDBOX`,
  `EXCHANGE__API_KEY`, `EXCHANGE__API_SECRET`, `EXCHANGE__PASSWORD`

Env-surface provenance: repository inspection only. Found in the operator
shell (Windows user environment, not committed): `TRADING_MODE`,
`LIVE_TRADING_ENABLED`, `I_UNDERSTAND_THE_RISKS`, `EXCHANGE_ID`,
`EXCHANGE_SANDBOX`, `EXCHANGE_API_KEY`, `EXCHANGE_API_SECRET`, `DATABASE_URL`.

The operator's real `.env` is never read, copied, modified or exposed: from a
clean worktree no `.env` exists, and the guard loads settings with
`env_file=None`. `LOCAL_DOTENV_USED: NO`.

## STEP 4 — Environment isolation guard (permanent)

`tests/unit/cert/test_cert_env_isolation.py`:

- `guard_hermetic()` fails loudly (`RuntimeError:
  HERMETIC_CERT_ENV_VIOLATION`) if any guarded variable is set, or if the
  committed defaults do not resolve to
  `mode == PAPER ∧ live_trading_enabled == False ∧ sandbox == True ∧
  api_key == api_secret == password == ""` (loaded with `env_file=None`).
- `test_guard_raises_when_external_var_selects_live`: every guarded var
  trips either the guard or a pydantic `ValidationError` — never a silent
  PASS. Teeth proven live: under `CERT_HERMETIC=1` with `EXCHANGE_ID` left
  in the shell, the guard FAILED as designed.
- Drift tests keep `cert_env.sh` and the guard list in lockstep.
- No invented counters; uses existing configuration contracts only.
- Skipped when `CERT_HERMETIC != 1` so ordinary development is unaffected.

## STEP 5 — Clean validation (second clean detached worktree)

Isolated worktree `../l5_precert`, detached at `05fca62`,
`git status --porcelain` = EMPTY. All runs through `scripts/cert_env.sh`:

```text
IMPORT_GATE:                 PASS  (8/8 L5 entry modules)
UNIT_COLLECTION:             PASS  (492 collected, 0 errors)
BDD_INTEGRATION_COLLECTION:  PASS  (45 collected, 0 errors)
FOCUSED_PAPER + cert + guard:PASS  (53 passed)
INDEPENDENT_VERIFIER:        PASS  (11/11 checks)
UNIT_REGRESSION:             PASS  (492 passed, 0 failed, hermetic)
BDD_INTEGRATION_REGRESSION:  PASS  (45 passed, 0 failed)
RUFF (candidate-owned files):PASS  (0 findings; cert_env.sh excluded via
                                    force-exclude — bash is not Python)
MYPY (candidate-owned files):PASS  (0 errors, src context)
PAPER_RUNTIME_SMOKE:         PASS  (start_paper_trading --max-cycles 2,
                                    mode=paper, orders_created=0,
                                    live_access=none, fail-closed NO_TRADE)
SECOND_CLEAN_CHECKOUT:       PASS
EXTERNAL_WORKTREE_DEPENDENCIES: 0
DEPENDENCY_CLOSURE:          PASS  (tests/unit/test_dependency_closure_guard.py)
LIVE_CONFIGURATION_VISIBLE:  NO
FALSE_SUCCESS:               0
```

Primary worktree untouched throughout (`git status --porcelain` = 297 before
and after; no reset/clean/stash; no concurrent files modified).

## Note on ruff scope

`pyproject.toml` now sets `extend-exclude = ["*.sh"]` + `force-exclude = true`
so `cert_env.sh` (bash) is not misparsed as Python. Without this, repo-wide
ruff measurements during final certification would absorb 12 false-positive
syntax errors.

## NEXT_ACTION

Run CERT-PO-L5-001 unchanged against `PRE_CERT_CANDIDATE_COMMIT 05fca62`
using `scripts/cert_env.sh` for every certification command.
