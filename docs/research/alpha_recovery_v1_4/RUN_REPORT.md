# ARP-005 — RUN REPORT

Driver: `scripts/alpha_recovery_v1_4.py` (deterministic; two runs byte-identical
excluding the corpus dir). Output: `reports/alpha-recovery-v1-4/`.

## Environment

- `code_hash` = `6421480709beda15115148f538e251fc48af8f9bd0a4c2001ffbec9a6cfccbad`
  (11 tracked files).
- `config_hash` = `6c4dd0be1fc2fff24920c9f9226c7f81f8d3d4dc80671b5a424721da497f7db1`.
- canonical cost = `COST_MODEL_V3` = 23.559016994374947 bps.
- baseline dataset fingerprint = `9d51385d570b8ff4ba1af22c3d4491f78c36111ec7383173e7d0351d5ee21658` (unchanged).
- extended corpus digest = `d3669d28de0014bf4299361adb9cca2c4d0de9a9b856077b8e1bff92260030e0`.
- HEAD at run time = `eae4c27e8254303c30ddf42abebb4ddaecf10716`.

## Manifest validation

`MANIFEST_VALIDATION.json` → `all_valid: true` for EXP-ARP-009/011/012
(config, dataset, cost-model version, splits, OOS-locked, strategy-id all match).

## Stage matrix

| experiment | SPEC | PIT | DEV | COST | VALIDATION | ROBUSTNESS | OOS | final |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| EXP-ARP-009 | PASS | PASS | INSUFFICIENT_EVIDENCE | NOT_REACHED | NOT_REACHED | NOT_REACHED | NOT_OPENED | **INSUFFICIENT_EVIDENCE** |
| EXP-ARP-011 | PASS | PASS | INSUFFICIENT_EVIDENCE | NOT_REACHED | NOT_REACHED | NOT_REACHED | NOT_OPENED | **INSUFFICIENT_EVIDENCE** |
| EXP-ARP-012 | PASS | PASS | PASS | PASS | REJECT_VALIDATION | NOT_REACHED | NOT_OPENED | **REJECT_VALIDATION** |

## Headline numbers (DEV, canonical cost)

```
EXP-ARP-009  DEV  17 trades  gross -100.114 bps  net -123.673 bps  -> INSUFFICIENT_EVIDENCE
EXP-ARP-011  DEV   2 trades  gross  -63.301 bps  net  -86.861 bps  -> INSUFFICIENT_EVIDENCE
EXP-ARP-012  DEV  62 trades  gross  +27.610 bps  net   +4.051 bps  -> PASS
             COST break-even 27.610 bps; negative at 1.25x         -> PASS
             VAL   9 trades  gross -374.824 bps                    -> REJECT_VALIDATION
```

## Quality gates

- `pytest` — see FINAL_REPORT (exact counts).
- `ruff check .` — clean.
- `mypy . --exclude "reports"` — see FINAL_REPORT.
- `git diff --check` — clean.
- determinism — two driver runs byte-identical (excluding the data dir).

## Notes

- No runtime authority, Risk module, lifecycle or promotion state was touched.
- `src/trading_bot/research/experimental/` remained untracked.
- The large generated copies live under gitignored `reports/`; durable evidence is
  tracked under `docs/research/alpha_recovery_v1_4/`.
