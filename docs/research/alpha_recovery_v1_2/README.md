# ARP-003 — Source Faithfulness + Backlog Reconciliation + Cost-Compatible Discovery

Tracked record of the third Alpha Recovery phase. The full run artifacts live in
`reports/alpha-recovery-v1-2/` (gitignored); **this directory carries the canonical
knowledge** so that the reconciliation, the source reconstructions, the negative
knowledge and the pre-registered experiment manifests are reproducible by SHA.

Authority order: `REAL_RUNTIME > EXECUTION_EVIDENCE > TESTS > SOURCE_CODE > ARCH/RFC >
EXTERNAL_SOURCE/RESEARCH > ASSUMPTION`. `FALSE_SUCCESS = 0`. `NO_TRADE` is a valid
result. No LIVE, no risk change, no threshold loosening, no OOS tuning.

## Contents

| file | purpose |
| --- | --- |
| `REGISTRY_RECONCILIATION.md` | §1/§2 — every research candidate classified against the canonical registry |
| `SOURCE_FAITHFULNESS.md` | §3–§6 — the per-rule status of the three non-faithful candidates; source vs project identity |
| `CANDIDATE_FAMILY_MAP.md` | §22/§23 — the Alpha Research backlog |
| `NEGATIVE_KNOWLEDGE.md` | §12 — what must never be rerun or claimed |
| `INFRASTRUCTURE_NOTES.md` | §20/§21 — cross-sectional + HTF PIT readiness |
| `source-faithful/STRAT-CAND-016.md` | §3 |
| `source-faithful/STRAT-CAND-012.md` | §4 |
| `source-faithful/STRAT-CAND-019.md` | §5 |
| `experiments/EXP-ARP-006..010/*` | §13–§15 — pre-registered experiments (`SPEC.md` + `MANIFEST.json` frozen **before** any result) |

## Headline results

1. **All three selected non-faithful candidates stay `BLOCKED_NEEDS_SPEC`.**
   STRAT-CAND-016 / 012 / 019 each lack the deterministic rules a testable spec
   requires. Their ARP-002 `REJECT_COSTS` verdicts reject a *project variant*, not
   the source hypothesis.
2. **The 5-minute horizon is structurally inside the cost-dominated region.** From
   the frozen DEV+VALIDATION corpus, the mean absolute price move over 30m is
   ≈ 25.4 bps against a 23.559 bps round trip (ratio 1.08×) — a mechanism would have
   to capture ~93 % of the typical move to break even. The ratio only becomes
   comfortable at multi-hour-to-daily horizons (1d ≈ 8.2×, 7d ≈ 22.3×). See
   `COST_FEASIBILITY.md` in the run report.
3. **The canonical registry (21 candidates) is complete.** No unmerged candidate
   022–047 exists; every other artifact is a duplicate, variant, or superseded design
   note. No id was renumbered.
4. **Five lower-turnover experiments are pre-registered, not executed.** Execution is
   the next authorized step; this phase deliberately avoids another blind batch.

## Registration status

No candidate is `PROMOTION_CANDIDATE`. No strategy is admitted for paper. The five
new experiments are `PREREGISTERED_NOT_IMPLEMENTED` with `verifier: UNASSIGNED`.
