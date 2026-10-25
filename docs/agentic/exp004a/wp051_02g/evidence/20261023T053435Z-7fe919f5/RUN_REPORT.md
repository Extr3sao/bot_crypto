# WP-051-02G run report — `20261023T053435Z-7fe919f5`

**Mode:** `once` · **State:** `NOT_DUE` · **Rehearsal:** False · **At:** `2026-10-23T05:34:35.848Z` · **HEAD:** `937a55c31df10cf3d1236dbca76049df5588c022`

> A capture is not a certification. The builder states what it wrote and what it found;
> `INDEPENDENT_VERIFICATION.json` is what decides whether the bytes are what they claim.

## The declaration

- `EXP-004A.datasets.phase3/v1` at `config/preregistrations/EXP-004A.datasets.phase3.json`
- sha256 `baeffad097f7d937` · git blob `82aec64affaf`
- commit time `2026-10-23T00:10:29+02:00`
- window `2026-10-23T00:00:00.000Z` → `2027-01-21T00:00:00.000Z` · effective from `2026-10-23T00:00:00.000Z`

## What the plan found

- `INCOMPLETE_DAY`: 270

## Shards written in this run

No shard was written in this run.

## Consolidation

| Slice | Days | Rows | Declared | Fraction | Status | Deterministic |
|---|---|---|---|---|---|---|
| `1h:BTC` | 0 | 0 | 2160 | 0.0000 | PENDING | True |
| `1h:ETH` | 0 | 0 | 2160 | 0.0000 | PENDING | True |
| `1h:SOL` | 0 | 0 | 2160 | 0.0000 | PENDING | True |

**Coverage:** 0 / 6480 (0.0000) · required 0.9 · **PENDING** · counts toward coverage: True

## The gates this package did not move

- `economic_executions`: 0
- `orders_placed`: 0
- `paper_orders_placed`: 0
- `live_trading`: DISABLED
- `risk_limits`: UNCHANGED
- `promotion`: NO_PROMOTION
- `certification`: NOT_CLAIMED_BY_BUILDER

## Notes

- Coverage is incomplete. Incomplete coverage stays PENDING for ever; no run of this program can promote it.

