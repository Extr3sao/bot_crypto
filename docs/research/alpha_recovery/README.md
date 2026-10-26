# Alpha Recovery V1.1 (ARP-002) — tracked experiment record

`reports/` is gitignored, so this directory carries the *tracked* inputs and
conclusions of ARP-002 ("TRACKED DIAGNOSTICS + FIRST COST-AWARE EXPERIMENT
CAMPAIGN"). The full narrative lives in `reports/alpha-recovery-v1-1/` locally.

## Tracked source added by ARP-002

- `src/trading_bot/research/strategy_failure_diagnostics.py` — the ARP-001
  diagnostic promoted to tracked source (deterministic; ARP-001 byte-parity in
  `enrich=False` mode).
- `src/trading_bot/research/alpha_recovery/` — deterministic, PIT-safe rules and
  simulator for EXP-ARP-001/002/003/005.
- `scripts/alpha_recovery_campaign.py` — freezes manifests and runs the staged
  pipeline (DEV → COST → VALIDATION → ROBUSTNESS → OOS).
- `tests/unit/research/test_strategy_failure_diagnostics.py`,
  `tests/unit/research/test_alpha_recovery_pit.py`.
- this directory: per-experiment `SPEC.md` + frozen `MANIFEST.json`.

## Outcomes (frozen manifests, cost = COST_MODEL_V3 23.5590 bps RT)

| experiment | candidate | DEV | COST | VALIDATION | final |
| --- | --- | --- | --- | --- | --- |
| EXP-ARP-001 | STRAT-CAND-001 | gross −0.676 bps | not reached | not reached | `REJECT_NO_EDGE` |
| EXP-ARP-002 | STRAT-CAND-016 | gross +0.987 bps | `REJECT_COSTS` | net −22.2 bps | `REJECT_COSTS` |
| EXP-ARP-003 | STRAT-CAND-012 | gross +0.131 bps | `REJECT_COSTS` | net −23.2 bps | `REJECT_COSTS` |
| EXP-ARP-005 | STRAT-CAND-019 | gross +2.026 bps | `REJECT_COSTS` | gross −2.803 bps | `REJECT_COSTS` |

- `PROMOTION_CANDIDATES = 0`; OOS (W7) **unopened**.
- The six runtime strategies are reclassified **BASELINE_NO_EDGE** (not deleted,
  not optimized; all remain `admitted_for_paper = false`).
- **Source-faithfulness:** STRAT-CAND-016/012/019 declare
  `SOURCE_FAITHFUL_EXPERIMENT = FALSE`; their results are `PROJECT_DERIVED_VARIANT`
  and carry **no source attribution**.
- `FALSE_SUCCESS = 0`.

## Reproduce

```
.venv/Scripts/python.exe scripts/alpha_recovery_campaign.py
.venv/Scripts/python.exe -m pytest tests/unit/research -q
```

Experiment parameters and kill criteria are frozen in each `MANIFEST.json` here.
