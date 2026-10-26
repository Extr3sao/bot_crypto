# ARP-005 — NEGATIVE KNOWLEDGE (§2)

Every rejection is persisted; no failed experiment is deleted. Identical
configurations may not be silently re-run later without an explicit reason.

## Registrations

| id | experiment | rules | data | sample | gross | cost | decision | reason |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `NEG-ARP-005-01` | `EXP-ARP-009` `H-XSEC-RELSTR-001` | cross-sectional top-1 trailing-30d return, daily rotate, max_hold 30 | `9d51385d…` baseline | 17 | −100.114 bps | 23.559 | **INSUFFICIENT_EVIDENCE** | 17 < frozen 20 **and** gross negative; `lookback_days=30` not shortened |
| `NEG-ARP-005-02` | `EXP-ARP-011` `H-VOLEXP-BREAK-001` | Donchian-20 breakout + ATR-expansion gate, long, stop 1.5×ATR, target 3×ATR, max_hold 10 | `9d51385d…` baseline | 2 | −63.301 bps | (not reached) | **INSUFFICIENT_EVIDENCE** | 2 trades < 10; both gates trigger-starved on ~122 days; not relaxed |
| `NEG-ARP-005-03` | `EXP-ARP-012` `STRAT-CAND-016-VARIANT-B` | ≥3-day ≥2×ATR void, band retest, fade, stop 1.5×ATR, target 3×ATR, max_hold 5 | `d3669d28…` extended (303 d/symbol) | DEV 62 / VAL 9 | DEV +27.610 / VAL −374.824 bps | 23.559 | **REJECT_VALIDATION** | razor-thin DEV edge (break-even 27.61, fails at 1.25×) did not generalise; VALIDATION collapsed |

## Generalizable lessons (carried forward)

- `NEG-ARP-005-04` — **Closing the data gap is not the same as finding an edge.**
  Extending DEV from 122 → 303 days/symbol (inside the ARP-004 adequacy band) turned a
  `DATA_SHORT_FOR_HORIZON` mechanism into a fully-sampled one — and it *failed out of
  sample*. More history improves the *quality* of the rejection, not the edge.
- `NEG-ARP-005-05` — **A DEV edge that survives cost only at ≤ 1.0× is not an edge.**
  `EXP-ARP-012` gross +27.61 bps vs 23.56 bps cost (ratio 1.17) is inside the noise of
  the cost model; it fails at 1.25× and it failed VALIDATION by −374.8 bps. Treat
  `gross/cost ≲ 1.2` as `fragile-by-construction`.
- `NEG-ARP-005-06` — **Cross-sectional and régime-gated mechanisms are trigger-starved
  on a ≈4–7-month daily corpus.** `EXP-ARP-009` (17 rotations) and `EXP-ARP-011` (2)
  could not reach their frozen minimum samples without lowering a frozen threshold
  (disallowed). A daily-horizon *selection* mechanism needs a longer calendar or a
  wider universe, neither of which may be manufactured by loosening rules.
- `NEG-ARP-005-07` — **The orphan `CrossSectionalEngine` was never the bottleneck.**
  Replacing it with a minimal tested ranker unblocked `EXP-ARP-009`, which then failed
  on economics, not infrastructure. Repairing infrastructure does not create alpha.
- `NEG-ARP-005-08` — **Pre-filter head-room is necessary, not sufficient.** Every
  candidate had `move/cost ≥ 18`; two still had negative expectancy. `available_move`
  remains a rejection screen only.

## Not opened

For all three experiments the **OOS window `W7` was never read**; it remains unseen.

## Prohibitions restated

- `EXP-ARP-007` remains `REJECT_COSTS` and MUST NOT be paper-shadowed (§19).
- `EXP-ARP-010` `vol_z_entry=2.0` MUST NOT be lowered to grow the sample.
