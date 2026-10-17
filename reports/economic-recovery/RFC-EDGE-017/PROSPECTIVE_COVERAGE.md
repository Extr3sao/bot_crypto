# WP-EDGE-017 — prospective coverage and continuity

*as of 2026-10-17T11:59:44Z, freeze 2026-10-17T07:15:28Z*

## The numbers, per symbol

| symbol | captured bars | expected closed | observed | evaluated | missing | longest observed run | longest evaluated run |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| BTC/USDT | 3 | 3 | 3 | 3 | 0 | 3 h | 3 h |
| ETH/USDT | 3 | 3 | 3 | 3 | 0 | 3 h | 3 h |
| SOL/USDT | 3 | 3 | 3 | 3 | 0 | 3 h | 3 h |

**Identity** `expected = observed + missing`: holds.

## Why the missing hours are missing

The collector is manual. Every hour between the freeze and the first manual run is
`MISSING_NO_COLLECTOR`; those bars were never observed by anything in this project,
so they are missing evidence and not quiet market time. The ledger records the
first capture at
`2026-10-17T11:38:51Z`, and the slice is a subset of what the ledger recorded:
`True`.

## What the collector costs

- measured: **9576.3 B/h** (0.009576 MB/h) for three symbols, hourly;
- the 240 MB/h declared fallback overstates it by **25061.8x**;
- the existing guard, with its own reserve and 1.5x stress, returns **COHERENT** for a 24 h window and a 64 MiB valve;
- peak transient cost of the atomic write: 2510 B (old and new file).

Disk is **no longer** the reason capture is not automated.

## Runbook

```bash
cd "$(git rev-parse --show-toplevel)" && ./.venv/Scripts/python scripts/edge15_oos_preregistration.py --capture
# appends only new closed bars; re-running is byte-identical when nothing new closed
```
