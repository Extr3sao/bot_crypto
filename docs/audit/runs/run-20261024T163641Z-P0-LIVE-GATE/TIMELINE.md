# P0 — timeline

All times UTC, 2026-10-24. Every claim below has a command in `COMMANDS.md` and
a file in this directory.

## 1. Preflight

- `HEAD = 96e211bd`, branch `audit/mt0004-negative-controls`, tree clean.
- G-3 closed at `9eeb8e87` with `G3_VERIFIED_SCOPED`; its contract and run are
  committed. G-3 §4.6/§7 explicitly left `LiveTradingGate` out of scope
  (DEF-G3-03).
- Read the gate: ten checks, `GATE-001…GATE-010`, `all_passed` blocks only
  `critical` failures.
- `grep -rn "LiveTradingGate" src/` before the change: only
  `execution/live_gate.py` and `execution/__init__.py`. **Zero callers.**
- Live sinks: the same seven `_live_order_boundary` call sites G-3 verified.

## 2. BEFORE evidence (no code changed yet)

`p0_live_gate_probe.py` was written first, precisely so the defect would be
measured through the real `trading_bot.app.main`:

```
before/place-order-futures-GATE-001…010.json
```

Every one: `broker_calls = 1`, `gate_validations = 0`, `exit_code = 0`.
`before/SUMMARY.json` records `all_gates_sent_before = true` and
`gate_never_consulted = true`.

The same probe was run on `run-futures`, `run-spot`, `place-order-spot`
(1 call each) and on the four reduction paths (1 call each). At this point the
defect is reproducible and quantified: **ten rejections, ten orders.**

## 3. Implementation

1. `LiveTradingGate` gained one optional constructor argument,
   `credentials=(api_key, api_secret)`. Rule logic untouched.
2. `app._evaluate_live_gate` runs the ten checks and requires
   `failed_gates == 0` and `total_gates == 10`; a gate exception is
   `live_gate_error`, a short report is `live_gate_incomplete`.
3. `_live_order_boundary` now takes `settings` as a required keyword and
   consults the gate after the hot stop and before `order_boundary`.
4. `_cmd_run --auto-trade` refuses at startup (exit 2) before the scanner,
   unless the stop is already engaged; `_cmd_place_order` refuses before a
   client is constructed; a settings error exits 2.
5. Reduction call sites pass `settings` but keep `opens_risk=False`.

## 4. G-3 fixture correction (DEF-P0-01)

`scripts/audit/g3_live_probe.py` built live settings with `sandbox=True` and no
`exchange_id`. A real `load_settings` rejects live+sandbox (`config/settings.py`
validator), so the fixture was an object that could never exist in production.
With the gate enforced, G-3's positive controls were refused — correctly.

The fixture now sets `sandbox=False`, `exchange_id="bitunix"` and synthetic
credentials. G-3's 21 cases still pass (60 s), including the in-flight test that
now passes the required `settings` argument. This is a fixture correction, not
a change to G-3's claim.

## 5. Tests and mutants

- `tests/unit/test_live_gate_enforcement.py`: **47 passed** (122 s).
- Regression (`test_app_cli_contract`, `test_app_demo`, `tests/unit/autonomous`):
  **405 passed** (185 s).
- Mutation matrix at `efd97e76`: baseline green, **7/7 mutants killed**
  (135 s). M3 is the important one: it makes the gate use
  `critical_failures` (its own `all_passed` semantics) and is killed by the
  GATE-006/GATE-008 cases.

## 6. Verifier defect found and corrected (DEF-P0-02)

The first verifier pass at `6c90b21d` was **13/15**: V-15 failed because no
report had been supplied yet (expected), and V-9 failed for a real reason: the
verifier's in-process snippet set `runtime.mode = "live"` on a `model_copy`,
which is a `str`, not `TradingMode`. Two gate checks compared the enum (passing)
and then read `.value` (raising), so the report had two `ERROR` results.

Fixed in `efd97e76`: the snippet uses `TradingMode.LIVE`, and the parser skips
the structlog line that shares stdout. `verification-first-pass.json` keeps the
red pass; it was not overwritten.

## 7. What the run proves, and what it does not

Proves: on the exported commit, for each of the ten checks, a rejected
configuration sends zero orders through the real CLI; reduction still sends;
missing config and a raising gate refuse; the stop keeps priority.

Does not prove: exchange acceptance of the payload (all sinks are recorders),
real-host behaviour, or G-4 (`paper_cycle`), which remains uncovered.
