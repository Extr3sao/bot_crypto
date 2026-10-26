# ARP-003 — NEGATIVE KNOWLEDGE (§12)

Append-only. Nothing is deleted. Each entry names the exact configuration so the
same work is not repeated.

## Shared frozen context

- corpus digest (21 × 5m base files): `9d51385d570b8ff4ba1af22c3d4491f78c36111ec7383173e7d0351d5ee21658`
- cost model: `COST_MODEL_V3` / `BINANCE_SPOT_STANDARD_TAKER`, **23.559016994374947 bps** RT
- code hash (ARP-002 experiments): `9982d1fd1975da08a427167ca3b4329cf6afe0761ef03813ff0b7aa0debdd6ca`
- DEV W1_2026-03…W4_2026-06 · VALIDATION W5_2026-07…W6_2026-08 · OOS W7_2026-09 **unopened**

## Carried forward — do not rerun

| id | experiment | candidate | decision | why |
| --- | --- | --- | --- | --- |
| NEG-ARP-002-01 | EXP-ARP-001 | STRAT-CAND-001 (source-faithful) | `REJECT_NO_EDGE` | DEV gr −0.676 bps, net −24.235, n 3835 |
| NEG-ARP-002-02 | EXP-ARP-002 | STRAT-CAND-016 project variant | `REJECT_COSTS` | DEV gr +0.987 < 11.78 half-cost; net −22.572 |
| NEG-ARP-002-03 | EXP-ARP-003 | STRAT-CAND-012 project variant | `REJECT_COSTS` | DEV gr +0.131; net −23.428 |
| NEG-ARP-002-04 | EXP-ARP-005 | STRAT-CAND-019 project variant | `REJECT_COSTS` | DEV gr +2.026 but VALIDATION gr collapsed to −2.803 |
| NEG-ARP-002-05 | meta | source-faithfulness | `INSUFFICIENT_EVIDENCE` | 3/4 candidates declare `SOURCE_FAITHFUL_EXPERIMENT = FALSE` |
| NEG-ARP-002-06 | EXP-ARP-004 | H-MR-SLOW-HORIZON | `REJECT_COSTS` | best +1.63 bps at +24 bars < cost (regression only) |
| NEG-ARP-002-07 | diagnostics | six runtime families | `NO_GROSS_EDGE` ×6 | kept `BASELINE_NO_EDGE`; not optimized, not deleted |

## New in ARP-003

### NEG-ARP-003-01 — the 5-minute horizon is structurally cost-dominated

- Observed (frozen DEV+VALIDATION corpus, `COST_FEASIBILITY.json`): mean absolute
  move over 30m = 25.44 bps vs a 23.559 bps round trip (ratio **1.08**); over 1h
  = 36.15 bps (ratio **1.53**); over 2h = 51.37 (ratio **2.18**).
- Must not claim: that any 5m/15m mechanism merely needs "a bit more edge". At ratio
  ≈ 1.1 a mechanism would have to capture ≈ 93 % of the typical move.
- Project action: pre-register only mechanisms whose natural horizon is ≥ 4–8 h
  (ratio ≥ 3–4), and prefer ≥ 1 day (ratio ≥ 8).

### NEG-ARP-003-02 — the three non-faithful candidates remain non-faithful

- Observed: STRAT-CAND-016 / 012 / 019 each still lack the deterministic rules a
  testable spec needs (see §3–§5 reconstructions).
- Must not claim: any of their ARP-002 results refutes the source hypothesis; or
  that "the source was tested".
- Project action: keep `SOURCE_FAITHFUL_EXPERIMENT = BLOCKED_NEEDS_SPEC`. Any test
  is a `PROJECT_DERIVED_VARIANT`.

### NEG-ARP-003-03 — the canonical registry is complete; no unmerged alpha candidate survives

- Observed: 21 `STRAT-CAND`; 34 `HYP` (all alpha hypotheses already map to a
  canonical id or to a risk/process spec); 3 unmerged discovery candidates
  (`D-02`, `D-03`, `D-04`), all REJECTED/INTESTABLE.
- Must not claim: that a "missing" candidate 022–047 exists, or that `D-02/D-04`
  are new hypotheses.
- Project action: do not renumber, do not reopen D-02/D-04 without evidence.

### NEG-ARP-003-04 — `D-03_squeeze_breakout` produces zero signals

- Observed: 0 signals across the whole dataset under its pre-registered spec.
- Must not claim: that its parameters should be loosened (that would be post-hoc
  re-tuning, forbidden by §23/the discovery phase).
- Project action: leave untested; a genuinely new pre-registered spec would be
  required, with a new id.

### NEG-ARP-003-05 — `CrossSectionalEngine` is an orphan

- Observed: 391 lines, exported, **no caller, no test**.
- Must not claim: that cross-sectional capability is "available" for research use.
- Project action: a PIT test + thin adapter is the minimum capability before
  `EXP-ARP-009` can run.

### NEG-ARP-003-06 — slower project variants are still not source-faithful

- Observed: migrating 016/019 to a daily horizon ratifies a *project* choice.
- Must not claim: that the daily variant tests the source claim.
- Project action: label `STRAT-CAND-016-VARIANT-B` / `STRAT-CAND-019-VARIANT-B`,
  never `-SOURCE`.
