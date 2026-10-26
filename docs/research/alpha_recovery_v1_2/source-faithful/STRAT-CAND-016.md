# STRAT-CAND-016 — SOURCE RECONSTRUCTION (ARP-003 §3)

**Source-faithful status: `BLOCKED_NEEDS_SPEC`.** No rule is invented; `UNKNOWN`
stays `UNKNOWN`.

- Candidate id: `STRAT-CAND-016` (unrenumbered)
- Source: `SRC-MANUAL-001` "Market Makers Method (Order Blocks)"
- Source location: pp.95-101
- Source claim: *fast directional "void" areas may later be revisited/rebalanced*
- Registry hypothesis: `HYP-023` — "objectively defined liquidity voids are revisited
  more than matched impulses"
- Experiment id: `EXP-024` (design-only; `DEFER_LOW_SPECIFICITY`)
- Prior project implementation: `EXP-ARP-002` = **`PROJECT_DERIVED_VARIANT`** (not a
  source-faithful test)

## Rule table (every field classified)

| field | value from source | class |
| --- | --- | --- |
| market | FX (discretionary technical/macro) | `SOURCE_EXPLICIT` |
| asset | FX pairs | `SOURCE_EXPLICIT` |
| timeframe | "multi-timeframe" | `SOURCE_EXPLICIT` (the specific TFs are `UNKNOWN`) |
| setup | identify a **fast / one-sided price area** ("void") | `SOURCE_EXPLICIT` (concept) |
| entry | enter when the void is **revisited / rebalanced** | `SOURCE_EXPLICIT` (concept) — trigger `UNKNOWN` |
| confirmation | — | `UNKNOWN` |
| invalidation | — | `UNKNOWN` |
| exit | — (`UNDERSPECIFIED`) | `UNKNOWN` |
| stop | — (`UNDERSPECIFIED`) | `UNKNOWN` |
| target | — (`UNDERSPECIFIED`) | `UNKNOWN` |
| holding logic | — | `UNKNOWN` |
| required indicators/features | none named; "fast move" implies bar speed/geometry | `SOURCE_IMPLIED` (must be *documented*, not assumed) |
| session/time constraints | — | `UNKNOWN` |
| context/regime requirements | voids are framed inside impulse→pullback alternation (CLAIM-M1-017) | `SOURCE_IMPLIED` |
| numeric thresholds (void size, void age, revisit window) | **none given** | `UNKNOWN` |

## Why the source-faithful experiment is blocked

A deterministic test needs at least four additional decisions and the source gives
none of them:

1. **What is a "void"?** No definition of "fast", no minimum displacement, no
   maximum duration. Any threshold ("≥ 3 monotone bars", "≥ 2×ATR") is
   `PROJECT_INTERPRETATION`, not the source.
2. **When is the void entered?** "Revisited/rebalanced" is a narrative, not an
   observable trigger (first touch? full fill? close beyond origin?).
3. **Where is the invalidation?** No stop.
4. **How long is the hold?** No horizon or exit rule.

The candidate spec itself records: *"Source itself questions distinctiveness;
boundaries and timing are vague; likely overlaps generic gap/imbalance/retracement
ideas."* The source review also preserves the source's own counter-evidence
(`CLAIM-M1-010`, `CLAIM-M1-026`, `NEG-020`).

**Consequence:** `SOURCE_FAITHFUL_EXPERIMENT = BLOCKED_NEEDS_SPEC`. Any test that
chooses a void threshold, a revisit trigger, a stop and a horizon is a
`PROJECT_DERIVED_VARIANT` and may not be attributed to the source. The prior
`EXP-ARP-002` result (`REJECT_COSTS`, DEV n 4052 gross +0.987 bps vs 23.559 bps RT)
therefore **does not** refute the source claim.

## Separation from the project variant (§6)

| identity | id | status |
| --- | --- | --- |
| source-faithful | `STRAT-CAND-016-SOURCE` | **BLOCKED_NEEDS_SPEC** (this file) |
| project variant | `STRAT-CAND-016-VARIANT-A` | pre-registered earlier as `EXP-ARP-002`; a *slower, daily* variant is pre-registered as `EXP-ARP-006` |

## What would unblock it

A written, causal, deterministic definition (thresholds + trigger + stop + horizon)
approved as a *project* rule and labeled as such. That changes the identity to
`PROJECT_DERIVED_VARIANT`; it never makes the test source-faithful.
