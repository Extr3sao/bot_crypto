# ARP-005 ALPHA EXPANSION — NEGATIVE KNOWLEDGE (§26)

Persisted rejections. Identical configurations may not be silently re-run later.

| id | experiment | mechanism | data | cost | stage | reason |
| --- | --- | --- | --- | --- | --- | --- |
| `NEG-EXP-01` | `EXP-ARP-013` | xsec momentum 90d / 5d rebalance / 30d hold | `2ce6e6b5…` DEV 1806 d | 23.559 bps | DEV | `REJECT_FRAGILE`: top1_share 0.5049 > 0.50 (single SOL-2021 trade dominates) |
| `NEG-EXP-02` | `EXP-ARP-014` | xsec reversal 7d / 3d rebalance / 7d hold | `2ce6e6b5…` DEV 1806 d | COST_MODEL_V3 | VALIDATION | DEV net +11.75 (PASS, COST break-even 35.31); VALIDATION net −1.91 ⇒ `REJECT_VALIDATION` |
| `NEG-EXP-03` | `EXP-ARP-015` | xsec low-vol 60d / 10d rebalance / 30d hold | `2ce6e6b5…` DEV 1806 d | (not reached) | DEV | `INSUFFICIENT_EVIDENCE`: 11 < 15 episodes; `ranking_window=60` not shortened |

## Generalizable lessons

* `NEG-EXP-04` — Long, multi-regime corpora expose **concentration** a short corpus
  hides: a factor can look strong yet be one trade.
* `NEG-EXP-05` — **Cost-compatibility is necessary, not sufficient**: the weekly
  reversal cleared COST with 173 DEV episodes and a 4.7 % top-1 share, then was
  net-negative out-of-sample.
* `NEG-EXP-06` — A **3-asset universe starves slow factors** (60d/30d ⇒ ~2
  episodes/year); cross-sectional factor research needs a wider universe or a
  faster rebalance.
* `NEG-EXP-07` — Crypto's **2020–2021 bull dominates a 2019–2023 DEV window**; a
  return-ranked factor inherits a non-repeating regime.

## Not opened

OOS `2025-07-01 … 2026-02-28` remains **sealed and unseen** for all three. For
`EXP-ARP-013`/`015` the VALIDATION split was never read either.
