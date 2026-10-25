# ARP-004 — DATA COVERAGE & SAMPLE SUFFICIENCY (§5–§6)

## Corpus

Frozen 5-minute corpus (`reports/strategy-baseline/data`), fingerprint
`9d51385d570b8ff4ba1af22c3d4491f78c36111ec7383173e7d0351d5ee21658`, assets
BTCUSDT/ETHUSDT/SOLUSDT. Windows are contiguous calendar months; every day in a
window is complete (288 × 5m bars), except the tail of the locked OOS window.

| split | windows | calendar span | complete daily bars / symbol |
| --- | --- | --- | --- |
| DEV | W1–W4 | 2026-03-01 … 2026-06-30 | **122** |
| VALIDATION | W5–W6 | 2026-07-01 … 2026-08-31 | **62** |
| OOS_LOCK | W7 | 2026-09-01 … 2026-09-24 | 24 (last partial day dropped) |

Daily bars are derived PIT-safely from complete UTC epoch buckets; a calendar day is
turned into a bar **only** if it carries all 288 contiguous 5m bars. Calendar length
alone is not treated as sufficient evidence.

## Eligible observations (signal days found by the frozen rules)

| experiment | DEV signal-days | VALIDATION signal-days | OOS signal-days |
| --- | --- | --- | --- |
| `EXP-ARP-007` | **211** (BTC 72 · ETH 70 · SOL 69) | 84 | 14 |
| `EXP-ARP-010` | **7** | **0** | **0** |

`EXP-ARP-010`'s 60-day warmup consumes half of DEV, and the frozen `vol_z >= 2.0`
spike trigger is rare: 7 signal-days in DEV, and none at all in VALIDATION/OOS.

## Sample sufficiency (§6)

* `EXP-ARP-007`: **153 completed DEV trades** (≥ 10 required). Holds average ≈988 min
  (≈0.69 day), so trades on a symbol rarely overlap; concentration is low
  (top-1 positive-net share 0.039), and all three assets contribute. Treating this as
  a usable sample, the honest conclusion is a *negative* one: the gross edge is
  +0.776 bps, ~30× below the frozen kill threshold.
* `EXP-ARP-010`: **6 completed DEV trades** (< 10 required) → `INSUFFICIENT_EVIDENCE`.
  A 6-trade, loss-making sample cannot support any edge claim, and the trigger
  threshold must not be loosened after the fact (§6, spec caveat).

Machine-readable per-experiment coverage is in each
`EXP-ARP-00X/DATA_COVERAGE.json`.
