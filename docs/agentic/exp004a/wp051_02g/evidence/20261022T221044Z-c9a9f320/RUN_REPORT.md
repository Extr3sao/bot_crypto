# WP-051-02G run report — `20261022T221044Z-c9a9f320`

**Mode:** `once` · **State:** `CAPTURE_COMPLETE_AWAITING_VERIFICATION` · **Rehearsal:** True · **At:** `2026-10-22T22:10:44.810Z` · **HEAD:** `937a55c31df10cf3d1236dbca76049df5588c022`

> A capture is not a certification. The builder states what it wrote and what it found;
> `INDEPENDENT_VERIFICATION.json` is what decides whether the bytes are what they claim.

## The declaration

- `EXP-004A.datasets.phase3/v1` at `config/preregistrations/EXP-004A.datasets.phase3.json`
- sha256 `baeffad097f7d937` · git blob `82aec64affaf`
- commit time `2026-10-23T00:10:29+02:00`
- window `2026-10-23T00:00:00.000Z` → `2027-01-21T00:00:00.000Z` · effective from `2026-10-23T00:00:00.000Z`

## What the plan found

- `CAPTURED`: 9

## Shards written in this run

| Slice | Day | Rows | sha256 | Admissible | Max lag (ms) |
|---|---|---|---|---|---|
| `1h:BTC` | 2026-10-19 | 24 | `08ad8f215a8253f1` | True | 6957826 |
| `1h:BTC` | 2026-10-20 | 24 | `6155aaaf4358b383` | True | 2476429 |
| `1h:BTC` | 2026-10-21 | 24 | `491ef6db45b044ed` | True | 5194647 |
| `1h:ETH` | 2026-10-19 | 24 | `77dd6756b1847f67` | True | 6957826 |
| `1h:ETH` | 2026-10-20 | 24 | `0ebc13b0c7d7f046` | True | 2476429 |
| `1h:ETH` | 2026-10-21 | 24 | `c66d5240ba5417c8` | True | 5194647 |
| `1h:SOL` | 2026-10-19 | 24 | `340b566934986467` | True | 6957826 |
| `1h:SOL` | 2026-10-20 | 24 | `085fc73baf06cd27` | True | 2476429 |
| `1h:SOL` | 2026-10-21 | 24 | `5ab3c343e1d6091e` | True | 5194647 |

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

