# PROFITABILITY_DISCOVERY_PROPOSAL

- status: **PROPOSED — NOT ACTIVATED**
- proposed_id: **RFC-046** (RFC-036 stays reserved for exact external replication; RFC-044 and RFC-045 are excluded by the standing next-action policy)
- proposed_by_artifact: `reports/profitability_gate035/FINAL_REPORT.json` (that artifact, not this document, records the commit the gate was evaluated at)
- as_of_utc: 2026-10-08T02:00:00Z

> This document is a **proposal**. It is not a decision, it does not open an RFC, and it does not authorize any work. The programme may start only after an explicit amendment of the master roadmap and of the RFC-043 operating model, both named in §5.

## 1. Why this is being proposed instead of continued search

RFC-035 closed as `CLOSED_NO_SUITABLE_EXTERNAL_STRATEGY`: three rounds read 75 sources, registered 33 opportunities and promoted none, because the external corpus did not contain a source that ships complete rules *and* an attributable result *and* a realistic cost model *and* fits this runtime.
The search was not the problem; the object it was looking for was not in the places it was allowed to look. That is a statement about the investigated universe, not about the market.

## 2. What the proposal is not

- it is not an exact replication programme (that is what RFC-036 is reserved for)
- it is not a strategy generator, an optimiser or a parameter search
- it does not weaken any acceptance criterion; the business-edge requirement (NET POSITIVE + BENCHMARK-ADJUSTED VALUE + EXECUTABLE + ROBUST) is unchanged
- it does not authorize capital, paper trading or live execution; `TRADES_AUTHORIZED` stays 0

## 3. Mandatory protocol

| id | requirement | rule |
| --- | --- | --- |
| P-01 | **Explicit economic hypothesis** | Every candidate declares the economic mechanism in one sentence and the external source it comes from. A candidate with no external source is out of scope for this programme. |
| P-02 | **Identified external source** | The hypothesis must be traceable to a registered source in research/profitability/source_registry.json, read at full-text level. Sources already closed by an earlier round are inadmissible as new. |
| P-03 | **Market and assets defined** | Long/cash spot only, majors or a preregistered liquid universe, on the runtime's venue. No derivatives. The universe is frozen with the candidate and is not re-selected after seeing results. |
| P-04 | **Frozen rules and parameters** | Entry, exit (including stop and target, or an explicit statement that none exists), sizing, warmup and order semantics are frozen and hashed BEFORE any measurement. No parameter search. |
| P-05 | **Point-in-time data** | Every input carries a PIT availability rule and a unit check. A feature whose publication timestamp cannot be pinned is not used. |
| P-06 | **Costs and execution model** | The admission cost is the project's own cost model at the candidate's venue, size and liquidity regime; the project's 23.791 bps floor applies unless a cheaper scenario is explicitly justified and recorded. No result is reported gross and called net. |
| P-07 | **Development and OOS separation** | A development window is frozen first; the out-of-sample window is opened once, after the candidate is hashed. Touching OOS to select or tune a candidate invalidates the candidate. |
| P-08 | **Capped candidates and experiments** | A hard cap on candidates and on experiments per candidate, declared before the programme starts, so that the number of attempts is visible in the result. |
| P-09 | **Multiple-testing control** | The programme records the total number of hypotheses and experiments and applies an explicit correction or an explicit honesty statement about the effective significance level. |
| P-10 | **Net-profitability gate** | A candidate passes only if its net edge after the frozen cost model is positive AND exceeds the benchmark alternative; DO_NOT_TRADE is a first-class benchmark, not an afterthought. |
| P-11 | **Robustness test** | A predeclared battery: cost stress at 1.25x and 1.5x, sub-period stability, sign stability across splits, and a sensitivity check that was named before the result was seen. |
| P-12 | **Independent verifier** | A second program re-derives the candidate's rules, data lineage, cost model and result, and may return FAIL even when the author recommends promotion. Builder != verifier. |
| P-13 | **STOP on a negative result** | A failed candidate closes; it is not re-tuned. The programme stops when the cap is reached or when a predeclared stop rule fires, and the result is written up whether positive or negative. |

## 4. The cost gate is the first gate, not the last

The audited admission cost is **23.7906 bps** round trip, of which **20.0 bps is the published taker fee** — an irreducible KNOWN term, not a model assumption. No candidate in this programme is measured until its gross edge per round trip is above 23.7906 bps, and none is promoted until it is above the 35.6859 bps stressed threshold with a turnover profile whose annual drag the programme can state in advance.

Consequence for candidate selection: a family whose per-trade edge is a few basis points is excluded before any data is loaded. The protocol therefore prefers low-turnover hypotheses whose per-trade expected edge can plausibly exceed the fee.

## 5. Required amendments before activation

| # | document | required change |
| --- | --- | --- |
| 1 | `tasks/roadmap.md` | add the discovery programme as its own phase with its own exit criteria, and name RFC-046 as the vehicle |
| 2 | `docs/research/PROFITABILITY_OPERATING_MODEL.json` | amend `next_action_policy.trigger`, which today admits only a NEW QUALIFIED OPPORTUNITY or a MATERIAL CAPITAL / INSTRUMENT CHANGE; this programme proceeds without either, so the policy must say so explicitly or the programme must not start |
| 3 | `docs/governance/PROFITABILITY_FIRST_FREEZE.md` | record that the RFC-035-scoped prohibition on our own backtesting lapses with RFC-035, and that discovery is admissible again only under this protocol |
| 4 | `tasks/decisions.md` | one ADR recording the amendment, the reason and the stop rule |

Until all four are done, the correct action is route A: wait.

## 6. Stop rule

The programme stops, and writes up the negative result, when any of these fires:

- the candidate cap is reached with no candidate above the stressed net-edge gate;
- any candidate's robustness battery fails the predeclared criterion;
- the independent verifier returns FAIL on a promoted candidate;
- the actual cost measured in paper execution exceeds the modelled cost by more than the predeclared tolerance.

A stop is a result, not a failure of the programme.

