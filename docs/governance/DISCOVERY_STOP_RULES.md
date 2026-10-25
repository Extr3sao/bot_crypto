# DISCOVERY STOP RULES

| field | value |
| --- | --- |
| policy_id | `DISCOVERY-STOP-2026-001` |
| status | **PROPOSED — NOT IN FORCE** |
| vehicle | `docs/rfc/RFC-046_CONTROLLED_DISCOVERY.md` |
| companion | `docs/governance/DISCOVERY_ADMISSION_POLICY.md` |
| principle | **a stop is a result** |

> The purpose of these rules is to make stopping the *pre-registered* outcome rather than a decision made while
> looking at a promising number. Every predicate below is evaluated on artefacts, not on judgement.

## 1. Campaign state machine

```text
PROPOSED ──approval──▶ ACTIVE ──┬──▶ CAMPAIGN_COMPLETE_PASS   (a candidate passed PROFITABILITY_GATE_V1)
                                ├──▶ DISCOVERY_CAMPAIGN_FAILED (cap reached, nothing passed)
                                └──▶ HALTED_BY_VIOLATION       (a rule below 2.x fired)

terminal states: all three. There is no "paused and quietly continued" state.
```

Only `CAMPAIGN_COMPLETE_PASS` allows the next stage, and even then only to a **separately granted** paper promotion
gate. `DISCOVERY_CAMPAIGN_FAILED` and `HALTED_BY_VIOLATION` both end the campaign, publish the negative result and
require a new explicit authorization before any further work.

## 2. Stop conditions

| id | predicate (mechanical) | consequence |
| --- | --- | --- |
| **ST-1** | the budget cap is reached (`hypotheses_tested = 3`, or 1 candidate per hypothesis, no refill) | `DISCOVERY_CAMPAIGN_FAILED` |
| **ST-2** | no candidate satisfies `PROFITABILITY_GATE_V1`, including PG-6 and PG-7 | `DISCOVERY_CAMPAIGN_FAILED` |
| **ST-3** | a robustness battery fails a predeclared criterion (cost stress 1.25x/1.5x, sub-period stability, regime splits) | candidate `CANDIDATE_REJECTED`; counts against the cap |
| **ST-4** | the independent verifier returns `FAIL` on a candidate the author recommends | candidate closed immediately; the recommendation is void |
| **ST-5** | the verifier cannot reproduce the result, errors out, or is incomplete | promotion blocked; defect registered; the *candidate* is not automatically rejected |
| **ST-6** | realised cost in paper exceeds the modelled cost beyond the predeclared tolerance | campaign halts for a cost re-audit; no candidate may be promoted until the audit is published |
| **ST-7** | any PIT violation, look-ahead finding, or `data_time > decision_time` observation | `HALTED_BY_VIOLATION`; every candidate using that data path is invalidated |
| **ST-8** | OOS was used for selection, tuning or comparison (i.e. inspected more than once per candidate) | `HALTED_BY_VIOLATION`; the candidate is void regardless of its result |
| **ST-9** | a rule, parameter, universe or exit was changed after measurement without a new candidate id and hash | `HALTED_BY_VIOLATION`; the affected measurement is discarded, the old candidate stays closed with its result |
| **ST-10** | an attempt was discarded, or the total number of trials cannot be reconstructed | `HALTED_BY_VIOLATION`; the multiple-testing correction (PG-10) is void and so is the result |
| **ST-11** | the governing authorization is withdrawn (RFC-041 exemption removed, policy revoked, or approval reversed) | `NOT_ACTIVE` immediately, mid-campaign, with artefacts left intact |
| **ST-12** | a defect is found that makes a published measurement wrong or unreadable | fix in a **new version** (named commit), repeat from a valid baseline, keep the superseded measurement as recorded |

ST-6 is the only stop that can be lifted by a documented re-measurement of the cost model; every other stop ends the
thing it stops.

## 3. What a stop produces (mandatory artefacts)

```text
campaign state (terminal) · hypotheses attempted · candidates attempted · trials counted
rejection reason per candidate, with the gate id that rejected it
the negative result, written as carefully as a positive one would be
any defect discovered, registered as its own incident
superseded measurements, retained with their commit
```

A stop that is not written up is treated as an unrecorded trial (ST-10). "We stopped because it looked bad" is not
a stop rule; `PG-7 failed at 1.5x` is.

## 4. Violation handling

1. The campaign halts at the moment the violation is detected, not at the end of the current work item.
2. Any result obtained under the violation is **void**, not merely suspicious. It is retained in the ledger with
   `INVALIDATED`, so a later reader cannot mistake it for evidence.
3. A violation is not repaired by re-running until a clean pass appears; that is `TUNE_UNTIL_PASS` wearing a
   process costume.
4. A violation discovered *after* a promotion blocks the promotion retroactively and is recorded against the
   campaign, not silently patched.

## 5. Forbidden responses to a failing candidate

```text
TUNE_UNTIL_PASS · silently widening a threshold · changing the OOS window after seeing it
lowering the cost model · re-labelling the same rules as a new hypothesis
adding a filter to rescue a specific losing period · replacing a candidate with a "close" variant
```

Dropping or loosening a criterion so that a candidate passes is the one failure mode this whole file exists to
prevent. It is also the reason `PROFITABILITY_GATE_V1`'s thresholds are frozen before results and `false_success`
is measured rather than asserted.

## 6. Interaction with the existing freeze

Until RFC-046 is approved, none of these rules is in force and the correct state is `NOT_ACTIVE` — waiting. After
approval they are in force for the discovery campaign only; the RFC-041 business freeze and the reentry gate are
otherwise unchanged, and `LIVE_TRADING` remains `DISABLED` throughout, in every state of the machine above.
