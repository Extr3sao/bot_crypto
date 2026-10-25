# P0 — reproducible commands

Run from the repository root. `uv run --frozen` is the project's locked runner.

## Preflight

```bash
git rev-parse HEAD                     # 96e211bd before the change; efd97e76 after
git status --short                     # clean source; evidence files only when uncommitted
grep -rn "LiveTradingGate" src/        # before: own module + __init__ only
grep -n "_live_order_boundary(" src/trading_bot/app.py   # 7 call sites
```

## BEFORE (old code, new probe)

```bash
for g in GATE-001 GATE-002 GATE-003 GATE-004 GATE-005 \
         GATE-006 GATE-007 GATE-008 GATE-009 GATE-010; do
  uv run --frozen python scripts/audit/p0_live_gate_probe.py \
    --entrypoint place-order-futures --run-dir ".tmp/p0-before-$g" \
    --break "$g" --json "docs/audit/runs/run-20261024T163641Z-P0-LIVE-GATE/before/place-order-futures-$g.json"
done
```

Observed: all ten exit 0, `broker_calls = 1`, `gate_validations = 0`.

## AFTER (new code)

Same loop writing to `after/`, plus:

```bash
for e in run-futures run-spot place-order-spot; do
  uv run --frozen python scripts/audit/p0_live_gate_probe.py --entrypoint "$e" \
    --run-dir ".tmp/p0-after-$e" --break GATE-003 \
    --json "docs/audit/runs/run-20261024T163641Z-P0-LIVE-GATE/after/$e-GATE-003.json"
done
for e in close-position set-tpsl place-order-futures-close place-order-spot-sell; do
  uv run --frozen python scripts/audit/p0_live_gate_probe.py --entrypoint "$e" \
    --run-dir ".tmp/p0-after-$e" --break GATE-004 \
    --json "docs/audit/runs/run-20261024T163641Z-P0-LIVE-GATE/after/$e-GATE-004.json"
done
uv run --frozen python scripts/audit/p0_live_gate_probe.py --entrypoint place-order-futures \
  --run-dir .tmp/p0-badcfg --settings-error --json after/settings-error-place-order-futures.json
uv run --frozen python scripts/audit/p0_live_gate_probe.py --entrypoint run-futures \
  --run-dir .tmp/p0-crash --gate-crash --json after/gate-crash-run-spot.json
```

Observed: ten gates 0 calls / exit 2 / gate id in stderr; four reduction paths
1 call / exit 0 / 0 gate validations; settings error and gate crash 0 calls /
exit 2.

## Tests

```bash
uv run --frozen pytest tests/unit/test_live_gate_enforcement.py -q   # 47 passed
uv run --frozen pytest tests/unit/test_live_hot_stop_coverage.py -q  # 21 passed
uv run --frozen pytest tests/unit/test_app_cli_contract.py \
  tests/unit/test_app_demo.py tests/unit/autonomous/ -q              # 405 passed
uv run --frozen pytest tests/unit/test_audit_contracts_tracked.py -q # contract tracked
```

## Mutation matrix

```bash
uv run --frozen python scripts/audit/p0_live_gate_mutants.py \
  --rev efd97e76 --source archive \
  --json docs/audit/runs/run-20261024T163641Z-P0-LIVE-GATE/mutations.json
```

Observed: baseline green; 7/7 killed in 135.4 s; `app_sha256` equals the export.

## Independent verifier

```bash
uv run --frozen python scripts/audit/verify_p0_live_gate.py \
  --rev <verified-commit> --source archive \
  --mutations docs/audit/runs/run-20261024T163641Z-P0-LIVE-GATE/mutations.json \
  --report docs/audit/runs/run-20261024T163641Z-P0-LIVE-GATE/RUN_REPORT.json \
  --json docs/audit/runs/run-20261024T163641Z-P0-LIVE-GATE/verification.json
```

Exit status 0 only when every check passes. V-15 hashes the artefacts declared
in `RUN_REPORT.json`; `verification.json` itself is not in that list.

## Static checks

```bash
uv run --frozen ruff check src/trading_bot/app.py src/trading_bot/execution/live_gate.py \
  scripts/audit/p0_live_gate_probe.py scripts/audit/p0_live_gate_mutants.py \
  scripts/audit/verify_p0_live_gate.py tests/unit/test_live_gate_enforcement.py
uv run --frozen mypy src/trading_bot/app.py src/trading_bot/execution/live_gate.py \
  scripts/audit/p0_live_gate_probe.py scripts/audit/p0_live_gate_mutants.py \
  scripts/audit/verify_p0_live_gate.py
```

Both clean on the verified commit.
