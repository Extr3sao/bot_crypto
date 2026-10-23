# WP-051-02G run report — `20261022T221048Z-0d5ae0a6`

**Mode:** `resume` · **State:** `RESUMED` · **Rehearsal:** True · **At:** `2026-10-22T22:10:48.059Z` · **HEAD:** `937a55c31df10cf3d1236dbca76049df5588c022`

> A capture is not a certification. The builder states what it wrote and what it found;
> `INDEPENDENT_VERIFICATION.json` is what decides whether the bytes are what they claim.

## The declaration

- `EXP-004A.datasets.phase3/v1` at `config/preregistrations/EXP-004A.datasets.phase3.json`
- sha256 `baeffad097f7d937` · git blob `82aec64affaf`
- commit time `2026-10-23T00:10:29+02:00`
- window `2026-10-23T00:00:00.000Z` → `2027-01-21T00:00:00.000Z` · effective from `2026-10-23T00:00:00.000Z`

## What the plan found

- `ALREADY_HELD`: 9

## Shards written in this run

No shard was written in this run.

## Consolidation

| Slice | Days | Rows | Declared | Fraction | Status | Deterministic |
|---|---|---|---|---|---|---|
| `1h:BTC` | 3 | 72 | 72 | 1.0000 | COVERAGE_COMPLETE | True |
| `1h:ETH` | 3 | 72 | 72 | 1.0000 | COVERAGE_COMPLETE | True |
| `1h:SOL` | 3 | 72 | 72 | 1.0000 | COVERAGE_COMPLETE | True |

**Coverage:** 216 / 216 (1.0000) · required 0.9 · **COVERAGE_COMPLETE** · counts toward coverage: False

## The gates this package did not move

- `economic_executions`: 0
- `orders_placed`: 0
- `paper_orders_placed`: 0
- `live_trading`: DISABLED
- `risk_limits`: UNCHANGED
- `promotion`: NO_PROMOTION
- `certification`: NOT_CLAIMED_BY_BUILDER

## Notes

- This run is a rehearsal over the declared rehearsal window. Every shard is stamped prospective=false and counts_toward_coverage=false; the phase's own coverage is not moved by it and is reported separately.

