# COMMANDS — G-1

Exact invocations, in the order they were run, with the output that matters.
Every `pytest` line is the real exit status (`${PIPESTATUS[0]}` was checked; a
`tail` that hid a failure would be the defect this project keeps finding).

Checkout: `C:/Users/GVLLFR0035/Downloads/ff-wt-mt0004`
Branch: `audit/mt0004-negative-controls`

## Preflight (baseline, before any edit)

```bash
git rev-parse --show-toplevel          # C:/Users/GVLLFR0035/Downloads/ff-wt-mt0004
git rev-parse --abbrev-ref HEAD        # audit/mt0004-negative-controls
git rev-parse HEAD                     # 5238c05e2f11527606ec2afc89966dc1500a281d
git status --porcelain                 # (empty)

uv run --frozen pytest tests/unit/autonomous/test_decision_kill_switch.py -q
# 28 passed, exit 0

uv run --frozen pytest tests/unit/autonomous -q
# 339 passed, exit 0

uv run --frozen pytest tests/unit/autonomous/test_hot_engage.py \
                       tests/unit/autonomous/test_decision_kill_switch.py -q
# 1 failed, 54 passed, exit 1   ← G1-D-1, the order dependence
```

## Focal and regression (implementation commit `0bcc100c`)

```bash
uv run --frozen pytest tests/unit/autonomous/test_kill_switch_persistence.py -q
# 19 passed, exit 0

uv run --frozen pytest tests/unit/autonomous/test_hot_engage.py \
                       tests/unit/autonomous/test_decision_kill_switch.py -q
# 41 passed, exit 0

uv run --frozen pytest tests/unit/autonomous/test_decision_kill_switch.py \
                       tests/unit/autonomous/test_hot_engage.py -q
# 41 passed, exit 0

uv run --frozen pytest tests/unit/autonomous -q
# 359 passed, exit 0

uv run --frozen pytest tests/unit/autonomous tests/unit/test_app_cli_contract.py \
                       tests/unit/test_audit_contracts_tracked.py -q
# 382 passed, exit 0
```

Inside the **export** of `0bcc100c` (the verifier's V-9), the same suites give
19 / 41 / 41 / 15 / 359, plus the audit guard 8 in the checkout: **483 test
results**, every run exit 0.

## Tooling

```bash
uv run --frozen ruff check src/trading_bot/autonomous/hot_stop.py \
    src/trading_bot/app.py tests/unit/autonomous/test_kill_switch_persistence.py \
    tests/unit/autonomous/test_hot_engage.py scripts/audit/g1_mutants.py \
    scripts/audit/g1_restart_probe.py
# All checks passed!

uv run --frozen mypy src/trading_bot/autonomous/hot_stop.py src/trading_bot/app.py
# Success: no issues found in 2 source files

uv run --frozen ruff check .
# Found 180 errors — all pre-existing, none in a file this run touched

git show HEAD:tests/unit/autonomous/test_decision_kill_switch.py \
  | uv run --frozen ruff format --check --stdin-filename \
      tests/unit/autonomous/test_decision_kill_switch.py -
# exit 1 — the format drift at line 165 already exists at the baseline
```

## Mutation matrix

```bash
uv run --frozen python scripts/audit/g1_mutants.py --rev 0bcc100c \
    --json docs/audit/runs/run-20261024T064739Z-G-1/mutants.json
# baseline   n/a  0   green
# M1..M8     yes  1   all killed
# baseline green; 8/8 mutants killed
```

## Cross-process trace

```bash
uv run --frozen python \
  docs/audit/runs/run-20261024T064739Z-G-1/cross_process_trace.py \
  --out docs/audit/runs/run-20261024T064739Z-G-1/cross_process_trace.json
# blocked broker_calls=0 control broker_calls=1 ok=True
```

The two children are real interpreters:

```bash
uv run --frozen python -m trading_bot.app kill-switch --run-dir <A> --engage
uv run --frozen python scripts/audit/g1_restart_probe.py --run-dir <A>
uv run --frozen python scripts/audit/g1_restart_probe.py --run-dir <B>   # control
```

## Independent verifier

```bash
uv run --frozen python \
  docs/audit/runs/run-20261024T064739Z-G-1/verify_g1.py \
  --rev 0bcc100c \
  --json docs/audit/runs/run-20261024T064739Z-G-1/verification.json
# 13/13 checks passed — VERIFIED_SCOPED
```

The verifier exports `0bcc100c` with `git archive`, asserts the exported
`hot_stop.py` and `app.py` byte-match the commit, runs its own scenarios in that
export, and re-runs the suite and the mutants there.
