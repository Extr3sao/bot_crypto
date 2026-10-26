# RFC-049 DISCOVERY 2 — CAMPAIGN CLOSURE AND SEALED-OOS RESOLUTION

| field | value |
| --- | --- |
| artifact | `RFC049_DISCOVERY2_CAMPAIGN_CLOSURE` |
| generated_at_utc | `2026-10-10T18:43:52Z` |
| head | `2d113a0ae82f38123eabe0385ab47bb7991b15ad` (branch `main`) |
| decision | ADR-0026 ([tasks/decisions.md](../../../tasks/decisions.md)) |
| decided_by | operator (owner) |
| terminal campaign state | **`DISCOVERY_CAMPAIGN_FAILED`** (ST-2) |
| candidates | `H-049-001`, `H-049-002` — both `CANDIDATE_REJECTED` at DEV/VAL |
| sealed forward OOS | **`CANCELLED_NOT_OPENED`** — the single inspection is retired unused |
| machine-readable record | [CAMPAIGN_CLOSURE.json](CAMPAIGN_CLOSURE.json) |

## 1. Why the campaign ends here

The stop is mechanical, not a judgement. `DISCOVERY_STOP_RULES.md` **ST-2** fires when *no
candidate satisfies `PROFITABILITY_GATE_V1`, including PG-6 and PG-7*; the predicate is
evaluated on artefacts — the `failed_criteria` lists in `ECONOMIC_RESULTS.json` — not on how
the numbers feel. Both admitted candidates carry registered failures:

| candidate | failed criteria (partition) |
| --- | --- |
| `H-049-001` | LCB > 0 (validation) · max drawdown ≤ 0.25 (development 51.4%, validation 27.9%) · single-trade share ≤ 0.4 (validation 53.8%) · incremental vs buy-and-hold > 0 (validation −9,788 bps) · incremental vs 200-day trend > 0 (validation −761 bps) |
| `H-049-002` | LCB > 0 (validation) · max drawdown ≤ 0.25 (validation 35.2%) · single-trade share ≤ 0.4 (development 49.9%) · incremental vs buy-and-hold > 0 (validation −9,281 bps) · incremental vs 200-day trend > 0 (validation −254 bps) |

Per `RFC049_DISCOVERY_ADMISSION.md` §6 a candidate that fails a stage is **closed at that
stage**. Both are closed, so nothing can reach the gate and the campaign has no next stage.
`DISCOVERY_CAMPAIGN_FAILED` and `HALTED_BY_VIOLATION` are terminal; there is no "paused and
quietly continued" state, and there is no automatic refill of the hypothesis budget.

The negative result is written up as carefully as a pass would have been
([FINAL_REPORT.md](FINAL_REPORT.md) §5–§8): a large real net result in 2019–2023
(+1,035% / +1,286% compounded) that decayed to non-confirmatory in 2024–2026, where the LCBs
turn negative, drawdowns breach the limit and both candidates lose to buy-and-hold and to a
200-day trend machine. Technical validity was never the problem — PIT violations 0, RFC-049B
counts reproduced exactly (14/9/23 and 26/22/48), independent verification PASS 37/37 with
8/8 controls and `FALSE_SUCCESS = 0`. What failed is the economic claim.

## 2. The sealed OOS: resolved by retiring the opening, not spending it

**Decision: `CANCELLED_NOT_OPENED`.** The window is never read; the single licensed
inspection is voided with the closed candidates.

The frozen gate is *"forward observations strictly after `freeze_timestamp_utc`; opened once,
after 20 closed round trips or 24 months, whichever comes first"*
(`PREREGISTRATION_MANIFEST.json#partition_policy.sealed_oos`; freeze `2026-10-10T11:26:20Z`,
window from `2026-10-11T00:00:00Z`). Three facts make exercising it pointless and costly:

1. **No decision can hang on it.** A closed candidate cannot be promoted, so no forward
   reading could produce a PASS or change any promotion. The information value is zero.
2. **The gate is unreachable inside its own window on this dataset.** At the measured
   turnover `H-049-001` expects 5.9 round trips in 24 months (81.0 months to 20) and
   `H-049-002` 12.4 (38.8 months to 20): the mechanical outcome would be
   `INSUFFICIENT_OOS_SAMPLE` regardless of the returns.
3. **The read would be irreversible.** ST-8 forbids inspecting OOS more than once per
   candidate. Spending the only uncontaminated forward sample on a dead candidate buys
   nothing and removes it from every better-posed hypothesis.

Alternatives were considered and rejected in ADR-0026: opening at the gate anyway (a reading
with no decision attached — the unrecorded-trial hazard of ST-10) and leaving the gate armed
until 2028-10-10 (the same irreversible consumption, two years later, with two closed
candidates kept alive as tracking objects).

What this decision is **not**: not a rejection on power (the 20-trip floor is untouched and
`INSUFFICIENT_OOS_SAMPLE` remains the label the gate would have produced), not an inspection
(`OOS_OPENED` stays false), not a threshold change, not a re-tune, not a reopened candidate,
not a new budget. It also does not claim the hypotheses were disproved forward — that question
stays unanswered on purpose.

**Scope.** The frozen declaration in `PREREGISTRATION_MANIFEST.json` is *not* edited (it is a
Phase A record under a hash). This closure and ADR-0026 are the forward-looking authority and
supersede it: the declared opening will not be exercised, and no reader may cite the manifest's
gate text as evidence that an opening is still pending. The window itself is neither read nor
deleted. A future campaign gets its **own** freeze timestamp and its **own** sealed window; it
may not claim the 2026-10-11 window as its first inspection, because that window was defined
for `H-049-001`/`H-049-002` and is retired with them.

## 3. Mandatory stop artefacts (`DISCOVERY_STOP_RULES.md` §3)

```text
campaign state (terminal)   DISCOVERY_CAMPAIGN_FAILED
hypotheses attempted        9 sourced/screened -> 2 admitted and frozen, 1 deferred, 6 rejected pre-admission, 0 refilled
candidates attempted        2
trials counted              2 economic candidates + 4 diagnostic ablation arms; parameter searches 0; discarded attempts 0
rejection reason            per candidate with the frozen threshold key, recorded above and in CAMPAIGN_CLOSURE.json
the negative result         FINAL_REPORT.md sections 5-8 and RUN_REPORT.{md,json}
defects                     RFC049B-DEF-01..09 (recorded by admission; none changes a frozen rule) + RFC049C-DEF-01 (corrected)
superseded measurements     Phase A NOT_RUN contracts and the re-stamped RFC-049B verifier artefact, retained
```

Every trial is accounted for, so PG-10's multiple-testing correction stays valid and ST-10 did
not fire. No trial was discarded: the four ablation arms and the failing DEV/VAL result are
published with the same care as a success would have been.

## 4. Governance after closure

```text
RFC_049_DISCOVERY2     = CLOSED
HYPOTHESIS_001         = CLOSED_REJECTED_DEV_VAL
HYPOTHESIS_002         = CLOSED_REJECTED_DEV_VAL
HYPOTHESIS_BUDGET      = EXHAUSTED_NO_REFILL
NEXT_CAMPAIGN          = NOT_AUTHORIZED   (the ADR-0025 scope was consumed; it does not extend to new work)
SEALED_OOS             = CANCELLED_NOT_OPENED
OOS_OPENED             = FALSE
PAPER_PROMOTION        = NOT_AUTHORIZED
LIVE_TRADING           = DISABLED
TRADES_AUTHORIZED      = 0
PROFITABILITY_VERIFIED = FALSE
FALSE_SUCCESS          = 0
DEFAULT_ROUTE          = wait for qualified external evidence; do not reopen the closed families, do not refill the budget
```

Nothing here creates a hypothesis, a candidate, a budget or an authorization. The default
route is the pre-existing one: wait. If internal discovery is ever resumed it must be a **new
campaign** whose entry condition is mechanical — a mechanism whose turnover-adjusted gross edge
is expected to clear the frozen 23.353553391 bps per round trip at its own cadence — with a new
budget and an explicit operator authorization. The evidence against the closed families is that
the 24-strategy admission ledger reports 0 admitted for paper and a best gross edge of
8.91 bps/trade against the 23.353553391 bps round-trip cost floor, and that the liquidity lines
decayed into the trend proxy they were meant to augment. The cap was not the reason for
stopping: the budget allows 3 admitted hypotheses, 2 were admitted and tested, and none was
refilled — ST-2 fired on the results, not on exhaustion.

Reversal is possible only through a new ADR that explicitly reverses ADR-0026, and even then
the gate could only be re-armed as a data-collection schedule: a terminated candidate stays
closed, and any restatement of its rules is a new hypothesis.

## 5. Checks

Six closure checks, 0 failed (`CAMPAIGN_CLOSURE.json#checks`): terminal state is ST-2 on
artefacts; both candidates closed with criteria traceable to frozen threshold keys; the sealed
window unread; no frozen artefact rewritten; no threshold or cost change; no new authorization
created.
