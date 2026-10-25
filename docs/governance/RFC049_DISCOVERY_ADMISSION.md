# RFC-049 DISCOVERY ADMISSION

| field | value |
| --- | --- |
| policy_id | `DISCOVERY-ADMISSION-RFC049` |
| status | **PROPOSED — NOT IN FORCE** (authorizes nothing until `NEXT_CAMPAIGN` changes) |
| vehicle | `docs/rfc/RFC-049_PROFITABILITY_DISCOVERY_2.md` |
| predecessor | `docs/governance/DISCOVERY_ADMISSION_POLICY.md` (RFC-046) and `docs/governance/DISCOVERY_STOP_RULES.md` |
| governs | offline hypothesis discovery in the Discovery 2 campaign, and nothing else |
| activation gate | `data/rfc049/BASELINE_AUDIT.json#governance_preserved` — currently `NEXT_CAMPAIGN = NOT_AUTHORIZED` |

> While this document is `PROPOSED`, it authorizes exactly nothing.  It exists so
> that campaign authorization is a decision about a written policy rather than a
> decision about a paragraph of intent.

## 1. What this policy is for

It admits one activity: formulating economic hypotheses **ourselves**, from
external evidence, and testing them offline under preregistered rules, after the
first controlled campaign (RFC-046) and three ALPHA campaigns produced negative
results by design and the RFC-048V risk plane was certified offline.  Discovery 2
exists because the earlier campaigns closed *families*, not the search: the
admissible design space still contains mechanisms with a causal story and free,
verifiable data (Phase A registered two).

## 2. What may enter

An entity enters the pipeline only if all of the following hold:

| # | condition | evidence at admission |
| --- | --- | --- |
| A-1 | it is an economic hypothesis, not a strategy and not a metric target | one sentence naming who pays, why, and in which regime |
| A-2 | it is externally supported by a registered source | `SRC-049-*` in `docs/research/RFC049_SOURCE_REGISTRY.md`, with declared read level |
| A-3 | it names a mechanism, not a price pattern | `ECONOMIC_MECHANISM` filled; "it worked in backtest" is not a mechanism |
| A-4 | it has a falsification condition stated before measurement | `invalidation` + `falsification_conditions` in the spec |
| A-5 | it is not a re-description of a closed line | checked against §4 of `RFC049_HYPOTHESIS_REGISTRY.md` |
| A-6 | it fits the runtime | long/cash spot or certified linear-perp offline; universe frozen |
| A-7 | its data is PIT-available under a named rule | `point_in_time_assumptions` with availability semantics |
| A-8 | its turnover can plausibly clear the cost floor | `cost_feasibility` with the frozen cost model |
| A-9 | it is within budget | ≤ 3 admitted hypotheses, 1 candidate each, declared before measurement |

Inadmissible by construction (inherited, not re-litigated): new RSI/MA/threshold
variations, another crypto pair as "new", more LLM agents, new sentiment sources,
parameter optimization, renamed rule sets, and every line in the closed-line
table of the registry.

## 3. The admission form

Every piece of work under this policy declares, before creating an artefact:

```text
POLICY                     = DISCOVERY-ADMISSION-RFC049
HYPOTHESIS_OR_RUN_ID       = H-049-00n / RUN-…
DIRECT_DISCOVERY_LINK      = which gate question this changes
BLOCKER_IF_NOT_DONE        = what the campaign cannot conclude without it
EVIDENCE                   = file, hash or measurement that shows it
```

If `DIRECT_DISCOVERY_LINK` cannot be filled in a way that changes a gate outcome,
the answer is `DEFER`.  A `DEFER` is not a rejection.

## 4. Budget and cap

```text
MAX_ADMITTED_HYPOTHESES        = 3        (preregistered, not refillable)
MAX_CANDIDATES_PER_HYPOTHESIS  = 1
PARAMETER_SEARCHES             = 0
OOS_INSPECTIONS_PER_CANDIDATE  = 1
NEW_AGENTS                     = 0 unless a demonstrated blocker exists
NEW_DAEMONS / SCHEDULERS       = 0 except the sealed-OOS data collector, which is
                                 data acquisition, not a trader
```

Every trial is recorded, including negative ones; a discarded attempt makes the
true number of trials unknowable and destroys the multiplicity correction.

## 5. Cost rule

The applicable floor is the frozen spot model at the runtime's own sizes:
**23.353553391 bps** round trip at 200 USDT and **23.790569415 bps** at 1000 USDT,
stressed to **35.030330086 bps** at 1.5x for the campaign stress test.  No
candidate is measured against a cheaper scenario; `ZERO_COST` runs are diagnostics
and can never appear in a gate decision.  Futures candidates are additionally
bound by the RFC-048V cost plane and do not inherit this floor.

## 6. Order of gates

```text
ADMISSION (this policy) → FROZEN SPEC (hash) → DEV/VAL RUN (exposed history, PIT-enforced)
  → SEALED FORWARD OOS (single opening) → ROBUSTNESS → INDEPENDENT VERIFICATION
  → (separate) PAPER-PROMOTION GATE
```

A candidate that fails any stage is closed at that stage; stages are not
reordered to make a result reachable.  A rejected line may re-enter only as a new
hypothesis with new budget — never as a re-tune.

## 7. Roles and authority

| role | may | may not |
| --- | --- | --- |
| hypothesis author | register, freeze, measure, publish | certify, promote, touch risk/sizing |
| builder (any program) | produce artefacts | verify its own result |
| independent verifier | re-derive everything, return FAIL | be the builder, be skipped |
| operator (human) | authorize the campaign, amend governance, promote to paper | be replaced by a default |

Deterministic risk, `NO_TRADE` as a first-class decision, no automatic live
execution and no strategy promotion without evidence all continue to hold.

## 8. Stop rules (binding)

Stop the campaign, and write the result up whether positive or negative, when:
the three-hypothesis budget is consumed; irreversible look-ahead is found; a risk
violation occurs; the OOS is contaminated; data is unrecoverably invalid; the
cost contract cannot evaluate a candidate; independent verification fails; or a
governance rule is breached.  Do not replace a rejected candidate automatically,
do not invent trades to grow the sample, do not extend windows to hunt a positive
result, and do not relax criteria after seeing results.

## 9. State at this writing (Phase A close)

```text
POLICY_STATUS            = PROPOSED, NOT IN FORCE
ADMITTED (spec frozen)   = H-049-001, H-049-002
DEFERRED                 = H-049-003
REJECTED PRE-ADMISSION   = R-049-001 .. R-049-006
ECONOMIC_TESTS           = NONE
OOS_OPENINGS             = 0
TRADES_AUTHORIZED        = 0
NEXT_CAMPAIGN            = NOT_AUTHORIZED
```

## 10. Revocation

Revoked automatically by any of: a stop condition firing and being confirmed; the
operator withdrawing authorization; the budget being consumed; or the
authorization being reversed.  On revocation the programme returns to
`NOT_ACTIVE`, and the correct action is the default: wait for qualified external
evidence.  No new document is needed.
