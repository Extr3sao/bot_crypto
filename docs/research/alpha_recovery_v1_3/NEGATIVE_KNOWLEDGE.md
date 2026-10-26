# ARP-004 — NEGATIVE KNOWLEDGE (§28)

Every rejection is persisted; no failed experiment is deleted. Identical
configurations may not be silently re-run later.

| id | experiment | rules | data | cost | failure stage | reason |
| --- | --- | --- | --- | --- | --- | --- |
| `NEG-ARP-004-01` | `EXP-ARP-007` `STRAT-CAND-019-VARIANT-B` | daily pivot fade; stop 1.0×ATR(14); target PP; max_hold 3; tie-break skips dual-touch days | `9d51385d…` DEV 122d | COST_MODEL_V3 23.559 bps | **COST** | DEV gross +0.776 bps ≪ cost; net −22.783 bps at 1.0×; break-even cost 0.776 bps; negative even at 0.5× (−11.004). |
| `NEG-ARP-004-02` | `EXP-ARP-010` `H-VOLSPIKE-MR-001` | long vol-spike down day; vol_z ≥ 2.0 vs 60d; ret ≤ −1.0×ATR; stop 2.0×ATR; target 1.0×ATR; max_hold 2 | `9d51385d…` DEV 122d | (not reached) | **DEV** | Only **6** DEV trades (<10) → `INSUFFICIENT_EVIDENCE`; gross −75.059 bps; frozen `vol_z_entry=2.0` NOT lowered. |

## Generalizable lessons (carried forward)

* `NEG-ARP-004-03` — **A favourable feasibility ratio is an upper bound, not an edge.**
  ARP-003 measured a 1-day opportunity/cost of ≈8.2; `EXP-ARP-007` captured **0.39 %**
  of the available daily move (capture ratio 0.0039). Moving a mechanism to a
  cost-compatible horizon does not, by itself, produce positive expectancy.
* `NEG-ARP-004-04` — **`CrossSectionalEngine` is not experiment-ready.** Orphan (no
  caller/test), no-op rank assignment (`AssetMetric.rank/percentile` always `None`), and
  no asset-synchronization/staleness guard. `EXP-ARP-009` = `INFRASTRUCTURE_BLOCKED`.
* `NEG-ARP-004-05` — **Two pre-registered 1d experiments remain `DATA_SHORT_FOR_HORIZON`.**
  `EXP-ARP-006` (5-day holds) needs ≈230–330 DEV days/symbol (gap ≈110–210);
  `EXP-ARP-008` (20-day holds) needs ≈830–1230 DEV days/symbol (gap ≈2–3 years). Current
  DEV = 122 days/symbol.
* `NEG-ARP-004-06` — **Slow-horizon mean reversion is trigger-starved at 1d.** A 2σ
  daily realized-vol spike is rare: 7 signal-days in 122 DEV days (across 3 assets) and
  **0** in VALIDATION and OOS. A project variant at this horizon cannot reach a usable
  sample on a ≈7-month corpus without loosening a frozen threshold (disallowed).

## Not opened

For both experiments the **VALIDATION split and the OOS window `W7` were never read**.
They remain unseen and available for a future, separately pre-registered experiment.
