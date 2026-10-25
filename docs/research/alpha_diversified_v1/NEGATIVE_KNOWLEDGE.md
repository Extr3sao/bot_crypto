# ARP-006 — NEGATIVE KNOWLEDGE

Freeze + rejections. Identical configurations may not be silently re-run later; a
rerun requires `NEW_HYPOTHESIS` + `NEW_EXPERIMENT_ID` + documented material
difference.

## Frozen (§1) — do not re-run identically

`EXP-ARP-001` `002` `003` `004` `005` `007` `010` `013` `014` `015`.

## New rejections (ARP-006)

| id | experiment | mechanism | universe | stage | reason |
| --- | --- | --- | --- | --- | --- |
| `NEG-006-01` | `EXP-ARP-006` | daily liquidity-reversal | 3 assets | DEV | `REJECT_NO_EDGE`: gross −182.147 bps |
| `NEG-006-02` | `EXP-ARP-016` | xsec momentum 90d (broad) | PIT dynamic (median 86) | VALIDATION | `REJECT_VALIDATION`: DEV +376.9 net, VALIDATION −508.4 net |
| `NEG-006-03` | `EXP-ARP-017` | xsec reversal 7d (broad) | PIT dynamic (91 assets) | DEV | `REJECT_COSTS`: gross +15.712 <= 23.559 bps |
| `NEG-006-04` | `EXP-ARP-018` | xsec low-vol 60d (broad) | PIT dynamic (8 assets) | VALIDATION | `REJECT_VALIDATION`: 1 trade; top-asset share 0.5384 |

## Generalizable lessons

* `NEG-006-05` — A **broader PIT universe fixes concentration, not edge.** The
  momentum mechanism's top1 trade share fell 0.5049 → 0.2062 (26 assets) yet still
  failed VALIDATION; reversal's top-asset share fell to 7.2 % yet is cost-negative.
* `NEG-006-06` — **Return-ranked edges are 2020-2021 artifacts.** `EXP-ARP-016` DEV
  PnL is +2,349 in 2021 and −1,273 in 2022 (NEG-EXP-07 confirmed), predicting its
  VALIDATION failure.
* `NEG-006-07` — **A slow factor can stay sample-starved even on 100+ assets** if its
  hold period is a large fraction of the validation window (`EXP-ARP-018`: 1 trade).
* `NEG-006-08` — **Long-only time-series momentum is crypto-beta, not neutral alpha.**
  Survivor `EXP-ARP-008` is positive in every regime but BULL-heavy; treat with a
  beta lens, never as market-neutral edge.
* `NEG-006-09` — **Survivorship biases cross-sectional results upward.** The 130
  markets are today's survivors (`SURVIVORSHIP_DATA_LIMITATION`); any positive
  cross-sectional result is an upper bound.

## Not opened

OOS `2025-07-01 … 2026-02-28` remains **sealed and unseen** for every ARP-006
experiment, including the survivor `EXP-ARP-008`.
