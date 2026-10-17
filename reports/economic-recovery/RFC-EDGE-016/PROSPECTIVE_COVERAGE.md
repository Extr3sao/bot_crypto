# WP-EDGE-016 — prospective coverage

*as of 2026-10-17T10:18:53Z, freeze 2026-10-17T07:15:28Z*

## The numbers

| quantity | value |
| --- | ---: |
| expected closed hourly bars per symbol | 2 |
| captured bars per symbol | 1 |
| observed symbol-bars | 3 |
| evaluated symbol-bars | 3 |
| bars with a proposal | 0 |
| bars with a fill | 0 |
| coverage ratio | 50.0% |

## What the gap means

The difference between expected and observed bars is **not** a quiet market: it is a
collector that is not running. Each such bar is classified `MISSING_NO_COLLECTOR` in
`CAPTURE_CONTINUITY.json`, and the package reports
`PROSPECTIVE_CAPTURE_NOT_AUTOMATED` rather than a coverage claim.

An observed bar with no proposal is `NO_SIGNAL`, which is a decision; a bar nobody
observed is missing evidence. The two are never merged.

## Runbook (manual collector)

```bash
# capture every closed hourly bar of the frozen universe; idempotent, appends only new bars
cd "$(git rev-parse --show-toplevel)" && ./.venv/Scripts/python scripts/edge15_oos_preregistration.py --capture
# commit the slice BEFORE verifying: V34 refuses a slice Git would not ship
git add reports/economic-recovery/RFC-EDGE-015/scratch/OOS_PROSPECTIVE_1H.jsonl \
        reports/economic-recovery/RFC-EDGE-015/OOS_CAPTURE_MANIFEST_V2.json
git commit -m 'Capture the closed hourly bars'
./.venv/Scripts/python scripts/edge15_verify.py   # 35/35
```

Status while the disk guard is `INSUFFICIENT_FREE_SPACE`: **PROSPECTIVE_CAPTURE_NOT_AUTOMATED**.

## Evaluation of the three captured bars

The paper lane consumed them (one per symbol) and no family proposed anything on them, so
they are `NO_SIGNAL` and not `NO_TRADE`: a proposal is what a machine emits when a rule
fires, and no rule fired. Zero prospective trades is a result, not a failure.
