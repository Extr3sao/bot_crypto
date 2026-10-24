# G-3 — commands actually run

Every block below was executed in
`C:/Users/GVLLFR0035/Downloads/ff-wt-mt0004` on `audit/mt0004-negative-controls`.
The results are copied from the real output, including the failures.

## 1. Preflight

```bash
git rev-parse HEAD            # a072da90ebedac71a11e8e301f3c6db3e0401733
git branch --show-current     # audit/mt0004-negative-controls
git status --porcelain        # (empty)
grep -rn "HotStopGate" src/   # hot_stop.py, runtime.py:81,323,353 — and app.py: none
grep -n "\.place_order(\|\.create_order(\|\.place_spot_order(\|\.flash_close_position(\|\.place_position_tpsl(" src/
```

The last two are the finding: the gate lives in one module and the seven live
sinks live in another. `HotStopGate` is imported by `app.py` **nowhere**; the
file only imported `write_control_file` for the G-2 CLI.

## 2. Baseline suites at `a072da90` — one pre-existing failure

```bash
uv run pytest tests/unit/test_app_cli_contract.py tests/unit/test_app_demo.py \
  tests/unit/test_app_trade_journal.py tests/unit/autonomous/test_hot_engage.py \
  tests/unit/autonomous/test_kill_switch_persistence.py -q
# 1 failed, 81 passed
# FAILED tests/unit/test_app_demo.py::test_main_kill_switch_not_implemented_returns_two
```

Reproduced in a clean export, to rule out local state:

```bash
git archive a072da90 | tar -x -C .tmp/g3-baseline
cd .tmp/g3-baseline
PYTHONPATH=src ../../.venv/Scripts/python.exe -m pytest tests/unit/test_app_demo.py -q -k kill_switch
# 1 failed, 29 deselected
# SystemExit: trading-bot kill-switch: error: the following arguments are required: --run-dir
```

`evidence/baseline_stale_test.txt`. This is **DEF-G3-01**: G-2 implemented the
command and did not update the test that asserted it did not exist. G-3 would
not report "regressions pass" against a red baseline, so the assertion is
updated (§4.7 of the contract) and the before/after kept.

## 3. Pre-fix measurement — the bypass, with a marker in the run directory

```bash
for ep in place-order-futures place-order-spot run-futures run-spot close-position set-tpsl; do
  mkdir -p .tmp/g3probe/before/$ep
  printf 'operator stop\n' > .tmp/g3probe/before/$ep/KILL_SWITCH
  uv run python scripts/audit/g3_live_probe.py --entrypoint $ep \
    --run-dir .tmp/g3probe/before/$ep --json .tmp/g3probe/before/$ep/probe.json
done
```

| entrypoint | `broker_calls` | exit |
|---|---|---|
| place-order-futures | **1** | 0 |
| place-order-spot | **1** | 0 |
| run-futures | **1** | 0 |
| run-spot | **1** | 0 |
| close-position | 1 | 0 |
| set-tpsl | 1 | 0 |

`evidence/live_matrix_before.json`. The marker was present in every run
directory and the operator-facing commands still reached the exchange.

## 4. The new tests before the fix (ACC-G3-11)

The same test file, run against an export of `a072da90` with the probe:

```bash
git archive a072da90 | tar -x -C .tmp/g3-red
cp tests/unit/test_live_hot_stop_coverage.py .tmp/g3-red/tests/unit/
cp scripts/audit/g3_live_probe.py .tmp/g3-red/scripts/audit/
cd .tmp/g3-red
PYTHONPATH=src ../../.venv/Scripts/python.exe -m pytest tests/unit/test_live_hot_stop_coverage.py -q
# 11 failed, 10 passed
```

The 10 that pass are the ones that must not depend on the change: the four
positive controls, the four reduction paths, `--disarm`, and the identity check.
`evidence/red_focal_tests.txt`.

## 5. Post-fix measurement

```bash
for ep in place-order-futures place-order-spot run-futures run-spot close-position set-tpsl; do
  mkdir -p .tmp/g3probe/after/$ep
  printf 'operator stop\n' > .tmp/g3probe/after/$ep/KILL_SWITCH
  uv run python scripts/audit/g3_live_probe.py --entrypoint $ep \
    --run-dir .tmp/g3probe/after/$ep --json .tmp/g3probe/after/$ep/probe.json
done
```

| entrypoint | marker | `broker_calls` | exit |
|---|---|---|---|
| place-order-futures | present | **0** | 2 |
| place-order-spot | present | **0** | 2 |
| run-futures | present | **0** | 0 (SKIPPED) |
| run-spot | present | **0** | 0 (SKIPPED) |
| close-position | present | 1 | 0 |
| set-tpsl | present | 1 | 0 |

Controls, same build, empty run directory: all four entrypoints `broker_calls=1`,
exit 0. `KILL_SWITCH_ENV=halted`, no marker: `broker_calls=0`, exit 2,
`marker_present=false`.

`evidence/live_matrix_after.json`.

## 6. Suites on the verified tree

```bash
uv run pytest tests/unit/test_live_hot_stop_coverage.py -q
# 21 passed

uv run pytest tests/unit/test_live_hot_stop_coverage.py tests/unit/test_app_demo.py \
  tests/unit/test_app_cli_contract.py tests/unit/test_app_trade_journal.py -q
# 70 passed

uv run pytest tests/unit/autonomous/ -q
# 360 passed
```

The verifier runs the same four paths plus `tests/unit/autonomous/` from the
exported commit: **426 passed** (V-11).

## 7. Mutation matrix

```bash
uv run --frozen python scripts/audit/g3_mutants.py --rev 9eeb8e87 \
  --json .tmp/g3evidence/mutants.json
# baseline green; 6/6 mutants killed in 307.8s
```

| mutant | removed property | killed by |
|---|---|---|
| M1 | the boot-time switch is not consulted | `test_env_kill_switch_blocks_entry_without_a_marker` |
| M2 | spot entry ignores the run directory | `test_entry_is_refused_with_a_marker[run-spot]` (and the AST test) |
| M3 | futures entry ignores the run directory | `test_entry_is_refused_with_a_marker[run-futures]` |
| M4 | `place-order` stops classifying entry as risk | `test_entry_is_refused_with_a_marker[place-order-futures]` |
| M5 | each process invents its own run directory | `test_restart_over_the_same_run_dir_stays_blocked` |
| M6 | the boundary drops the lock | `test_engage_waits_for_the_inflight_dispatch` |

## 8. Verifier

```bash
uv run --frozen python scripts/audit/verify_g3.py --rev 9eeb8e87 \
  --report docs/audit/runs/run-20261024T112751Z-G-3/RUN_REPORT.json \
  --json docs/audit/runs/run-20261024T112751Z-G-3/verification.json
# 15/15 checks — G3_VERIFIED_SCOPED in 261.3s
```

An earlier run of the same verifier failed **V-10** on a byte-identical file
(git's UTF-8 arrows decoded through the Windows code page) and V-12 because the
matrix had not been merged into the report. Both were real defects of the
verifier, fixed in `9eeb8e87` and `823901cf`; the failing output is kept in
TIMELINE.md rather than hidden.

## 9. Lint and types

```bash
uv run ruff check src/trading_bot/app.py tests/unit/test_live_hot_stop_coverage.py \
  scripts/audit/g3_live_probe.py scripts/audit/g3_mutants.py scripts/audit/verify_g3.py
# All checks passed!

uv run ruff format --check <the same files>
# 0 would reformat

uv run mypy src/trading_bot/app.py
# Success: no issues found in 1 source file

uv run mypy scripts/audit/g3_live_probe.py scripts/audit/g3_mutants.py scripts/audit/verify_g3.py
# Success: no issues found in 3 source files
```

`uv run` without `--frozen` rewrote `uv.lock` (a uv-version artifact, 546 added
lines, no dependency change). It was restored with `git checkout -- uv.lock` and
never committed; every later command uses `--frozen`.
