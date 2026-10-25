# DISCOVERY ADMISSION POLICY

| field | value |
| --- | --- |
| policy_id | `DISCOVERY-ADMISSION-2026-001` |
| status | **PROPOSED — NOT IN FORCE** |
| vehicle | `docs/rfc/RFC-046_CONTROLLED_DISCOVERY.md` |
| in force from | the date RFC-046 is approved and its amendment is committed |
| parent | RFC-041 `BUSINESS-FREEZE-2026-001` (unchanged), `PROFITABILITY-FIRST-2026-002` (to be closed) |
| gate | `PROFITABILITY_GATE_V1` (`docs/rfc/RFC-046_CONTROLLED_DISCOVERY.json`) |
| stop rules | `docs/governance/DISCOVERY_STOP_RULES.md` |
| governs | offline hypothesis discovery, and nothing else |

> While this document is `PROPOSED`, it authorizes exactly nothing. It exists so that approval is a decision about
> a written policy rather than a decision about a paragraph of intent.

## 1. What this policy is for

It admits one activity that the current governance does not: **formulating economic hypotheses ourselves**, from
external evidence, and testing them offline under preregistered rules. It exists because RFC-035's search required
an external source to ship complete rules *and* an attributable result *and* a realistic cost model, and the
admissible corpus contained no such source — a statement about the searched universe, not about the market.

## 2. What may enter

An entity may enter the pipeline if and only if all of these hold:

| # | condition | evidence required at admission |
| --- | --- | --- |
| A-1 | it is an **economic hypothesis**, not a strategy and not a metric target | one sentence naming who pays, why, and in which regime |
| A-2 | it is **externally supported** by a registered source | `SOURCE_ID` from `research/profitability/source_registry.json`, read at full-text level |
| A-3 | it names a **mechanism**, not a price pattern | `ECONOMIC_MECHANISM` filled; "it worked in backtest" is not a mechanism |
| A-4 | it has a **falsification condition** stated before measurement | `INVALIDATION` and `COUNTER_EVIDENCE` filled |
| A-5 | it is **not a re-description of a closed line** | checked against `docs/research/CANDIDATE_ARCHIVE.json` and RFC-041 reject conditions |
| A-6 | it fits the **runtime**: long/cash spot, majors or a preregistered liquid universe, no derivatives | `ASSET_UNIVERSE` and `TIMEFRAME` frozen |
| A-7 | its **data is PIT-available** under a named rule | `DATA_REQUIREMENTS` with availability semantics, not just a field list |
| A-8 | its **turnover** can plausibly clear the cost floor | `TRANSACTION_COSTS` with annual drag at the hypothesis's own cadence |
| A-9 | it is **within budget**: ≤ 3 hypotheses, 1 candidate each | declared before the first measurement |

### 2.1 Inadmissible by construction

Inherited verbatim from RFC-041 (`reject_conditions`) and the RFC-035 freeze §6. These are not re-litigated here:

```text
new RSI variation · different moving average · different threshold · another crypto pair
more LLM agents · new sentiment source · adding ML to old features
parameter optimization · same strategy with renamed rules
```

A hypothesis that is a renamed rule set must be registered as a re-description of the closed line **with our own
result attached as counter-evidence** — including the internal measurement that the line's gross edge was roughly
10–40x below the cost floor. Re-testing it is not discovery.

### 2.2 What admission is not

Admission is not validation, not a profitability claim and not a promotion. The only states a hypothesis can hold
are `PREREGISTERED`, `UNDER_TEST`, `REJECTED`, `INCONCLUSIVE`. There is no `VALIDATED_ALPHA`.

## 3. The admission form

Every piece of work under this policy declares, before it creates an artefact:

```text
ACTIVE_POLICY             = DISCOVERY-ADMISSION-2026-001
RFC                       = RFC-046
HYPOTHESIS_ID             = H-<nnn>   (or CANDIDATE_ID for work on a frozen candidate)
DIRECT_DISCOVERY_LINK     = <which gate question this changes>
BLOCKER_IF_NOT_DONE       = <what the campaign cannot conclude without it>
EVIDENCE                  = <file, hash or measurement that shows it>
```

If `DIRECT_DISCOVERY_LINK` cannot be filled in a way that changes a gate outcome, the answer is `DEFER`. A `DEFER`
is not a rejection.

The single exception remains a demonstrated blocker, in the strict sense the freeze used: it must already have
produced a wrong or unusable verdict, an unreadable artefact, or an unrecordable measurement. The RFC-035E
verifier that raised `TypeError` on missing inputs (TD-2) is the reference example of what does **not** qualify:
it is a defect to register, not a blocker to spend budget on.

## 4. Budget and cap

```text
MAX_HYPOTHESES                 = 3        (preregistered, not refillable)
MAX_CANDIDATES_PER_HYPOTHESIS  = 1
PARAMETER_SEARCHES             = 0
OOS_INSPECTIONS_PER_CANDIDATE  = 1
NEW_AGENTS                     = 0 unless a blocker is demonstrated
NEW_DAEMONS / SCHEDULERS       = 0
```

Every trial is recorded, including every negative one. A discarded attempt makes the true number of trials
unknowable, which destroys the multiple-testing correction (PG-10) and therefore the result. Discarding an attempt
is a **violation**, not housekeeping.

## 5. Cost rule

The applicable floor is the audited one — **23.7906 bps** round trip (20.0 `KNOWN` + 3.7906 `ESTIMATED`), stressed
to **35.6859 bps** at 1.5x — at the candidate's own turnover. No candidate is measured against a cheaper model, and
no candidate is compared with another under different assumptions. Diagnostic `ZERO_COST` runs are permitted only
as diagnostics and may never appear in a gate decision.

## 6. Order of gates

```text
ADMISSION (this policy)  ->  FROZEN SPEC (hash)  ->  RESEARCH EXECUTION (DEV, PIT-enforced)
   ->  NET OOS VALIDATION (PROFITABILITY_GATE_V1)  ->  ROBUSTNESS  ->  INDEPENDENT VERIFICATION
   ->  (separate) PAPER PROMOTION GATE
```

A candidate that fails any stage is closed at that stage. Stages are not reordered to make a result reachable.

## 7. Roles and authority

| role | may | may not |
| --- | --- | --- |
| hypothesis author | register, freeze, measure, publish | certify, promote, touch risk/sizing |
| builder (any program) | produce artefacts | verify its own result |
| independent verifier | re-derive everything, return `FAIL` | be the builder, be skipped |
| owner (human) | approve this policy, amend governance, authorize paper/live | be replaced by a default |

Authority order is unchanged and non-negotiable:

```text
REAL_RUNTIME > EXECUTION_EVIDENCE > TESTS > CODE > RFC > EXTERNAL_SOURCE > ASSUMPTION
```

Deterministic risk, `NO_TRADE` as a first-class decision, no automatic live execution and no strategy promotion
without evidence all continue to hold. No agent may change sizing, leverage or risk constraints.

## 8. Revocation

This policy is revoked automatically by any of: a stop condition firing and being confirmed; the owner withdrawing
the RFC-041 exemption; the campaign cap being reached; or the approval being reversed. On revocation the programme
returns to `NOT_ACTIVE` and the default action is route A — wait for qualified external evidence. Revocation needs
no new document: removing the exemption from `docs/research/BUSINESS_REENTRY_POLICY.md` is sufficient because
RFC-046 is authorized by that exemption and by nothing else.
