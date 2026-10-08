# RFC-046 — CONTROLLED QUANTITATIVE STRATEGY DISCOVERY

| field | value |
| --- | --- |
| RFC | **RFC-046** |
| STATUS | **APPROVED / ACTIVE — owner decision 2026-10-08 (option 5A, ADR-0024)** |
| MODE | offline controlled quantitative research (`DISCOVERY_OFFLINE = AUTHORIZED`); no paper, no live |
| SUPERSEDES | nothing |
| PARENT AUTHORITY | RFC-041 `BUSINESS-FREEZE-2026-001` (unchanged) and `PROFITABILITY-FIRST-2026-002` (RFC-035 freeze, to be closed by the amendment) |
| PRECEDENT | `reports/profitability_gate035/FINAL_REPORT.json` — RFC-035 closed `CLOSED_NO_SUITABLE_EXTERNAL_STRATEGY` with `REPLICATE_P0 = NONE` |
| PRECEDENT (document) | `docs/roadmap/PROFITABILITY_DISCOVERY_PROPOSAL.md` — route B, `PROPOSED`, not activated |
| TRADES_AUTHORIZED | 0 |
| LIVE_TRADING | DISABLED |
| PROFITABILITY_VERIFIED | FALSE |

> **This document is a decision now.** The owner approved option 5A on 2026-10-08 (`tasks/decisions.md ADR-0024`): RFC-046 is **APPROVED / ACTIVE for offline research only**. `G_BUSINESS_REENTRY` stays `NOT_PASS`, `LIVE_TRADING` stays `DISABLED`, `TRADES_AUTHORIZED` stays `0`. The approval authorizes no capital and no production promotion.

## 00 — APPROVAL RECORD (2026-10-08)

- **Decision**: option 5A — a specific, dated RFC-041 exemption that activates RFC-046 **only in
  offline research**.
- **Recorded in**: `tasks/decisions.md ADR-0024`.
- **Applied changes**: dated exemption in `docs/research/BUSINESS_REENTRY_POLICY.*`; trigger amended in
  `docs/research/PROFITABILITY_OPERATING_MODEL.*`; RFC-035 freeze closed in
  `docs/governance/PROFITABILITY_FIRST_FREEZE.md`; `Fase 10` in `tasks/roadmap.md`; identifier registry
  `docs/roadmap/RFC_REGISTRY.json`.
- **Unchanged**: `G_BUSINESS_REENTRY != PASS`, `LIVE_TRADING = DISABLED`, `TRADES_AUTHORIZED = 0`,
  `RISK_ENGINE = DETERMINISTIC`, `BUILDER != VERIFIER`, `FALSE_SUCCESS = 0`, and every RFC-041 reject
  condition. The approval opens the research door only.
- **Stop**: `docs/governance/DISCOVERY_STOP_RULES.md`; `DISCOVERY_CAMPAIGN_FAILED` ends the programme
  with no automatic refill.

## 01 — PRESERVE EXISTING AUTHORITY

### 01.1 Authority order (unchanged)

```text
REAL_RUNTIME > EXECUTION_EVIDENCE > TESTS > CODE > RFC > EXTERNAL_SOURCE > ASSUMPTION
```

No clause of this RFC reorders that chain. A source claim can never outrank a runtime observation, and an RFC
can never outrank code that is actually deployed.

### 01.2 Baseline audited before proposing anything

| item | observed |
| --- | --- |
| HEAD at audit | recorded as `current_head` in `reports/rfc046/FINAL_REPORT.json` (the gitignored report, not this tracked document, carries the live commit) |
| working tree | shared checkout with other threads active; this RFC writes only the files listed in §14 and touches nothing else |
| existing RFC artefacts | `reports/RFC000…RFC044` artefacts present for 26 numbers, but **all of them live in the gitignored `reports/` tree**; `RFC045_*` absent by design; `RFC036_*` occupied by managed futures (see §01.3 and TD-5) |
| catalogue of sources | `research/profitability/source_registry.json` — 75 registered sources, 75 unique ids, round split 20 / 44 / 11 |
| RFC-035 result | 3 rounds, 33 registered opportunities, 0 accepted (`REPLICATE_P0 = NONE`) |
| CAP-004B | as recorded by the RFC-035 gate at `2026-10-06T20:18:19Z`: campaign `RUNNING`, chain `INTACT`, `NO_DRIFT`, 0 duplicate decisions, 0 duplicate evaluations, 0 false success, first settlement `PENDING` (matures `2026-10-07T16:00:00Z`). The campaign's own report on 2026-10-08 states `CAMPAIGN_STATUS = RUNNING`, `SUPERVISOR_STATUS = HEALTHY`, 4 sealed / 4 pending / 0 matured / 0 settled / 0 evaluated, last run `2026-10-06T20:17:39Z` — i.e. its last run predates this audit's date. **Observed, not adjudicated**: this RFC does not touch CAP-004B, and a stalled supervisor is that thread's finding to make, not this document's |
| CAP-004D | daily dashboard campaign cited by commit `ab4cc8e`; not touched |
| paper runtime | `mode: "paper"` (`config/runtime.yaml:10`), `live_trading_enabled: false` (`config/runtime.yaml:13`, `config/risk.yaml:60`), `require_manual_confirmation_for_live: true` (`config/runtime.yaml:14`), `sandbox: true` (`config/exchange.yaml:18`) |
| tests | full suite green at the RFC-035 closure commit `38885d2`; re-run for this RFC and recorded in `reports/rfc046/FINAL_REPORT.json` |

**Reconciliation of this list with execution:** each row is either an artefact read at a named commit or a file
read from disk; nothing in this section is recalled from memory or inferred from a summary.

### 01.3 RFC numbering collisions (resolved, not ignored)

The RFC number space is **not** backed by a machine-readable registry. The audit therefore works from artefact
presence on disk, from tracked documents that declare a number, and from text references at HEAD, and it
classifies every number honestly. The full per-number evidence is in `data/rfc046/audit.json`:

| class | numbers | evidence |
| --- | --- | --- |
| occupied — 26 numbers | `000`, `010`, `020`, `021`, `023`…`044` | final reports and campaign subdirectories under `reports/` (`RFC036_PLAN`, `RFC041_VERIFICATION`, `rfc000/`, …). **None of these artefacts is versioned**: `reports/*` is gitignored |
| occupied *and* declared in a tracked document — 9 of the 26 | `020`, `030`, `035`, `036`, `037`, `038`, `041`, `043`, `044` | tracked `docs/**` carrying an `"rfc": "RFC-nnn"` field or an `# RFC-nnn` heading, e.g. `docs/research/MANAGED_FUTURES_TREND_V1.md` |
| occupied with **no versioned declaration at all** — 17 of the 26 | `000`, `010`, `021`, `023`…`029`, `031`…`034`, `039`, `040`, `042` | artefacts exist only in the gitignored tree (TD-5) |
| **deliberately vacant and asserted absent** | `RFC-045` | the check `no RFC-045 artifact exists` appears in **four** campaign verifier scripts (`scripts/cap001_verify.py` … `cap004_verify.py`) and in their result JSONs |
| named in prose only, no artefact | `001`, `016`, `022` | text mentions at HEAD, no report, script or test |
| **taken by this RFC** | `RFC-046` | no prior artefact; the only prior mentions are the RFC-035 closure lineage that named it as the intended vehicle |
| separate namespace | `RFC-STRAT-013`, `RFC-STRAT-014` | `docs/research/strategy_lifecycle/rfc/`; not a collision with the `RFC-0nn` space |

Consequences, all binding on this RFC:

1. **RFC-046 is used, and it is free.** It was named as the vehicle by the RFC-035 closure proposal, and nothing
   has an artefact under that number.
2. **RFC-045 must not be used.** Its absence is a *control* asserted by four campaign verifier scripts;
   creating an `RFC-045` artefact would break those checks and destroy a real invariant.
3. **RFC-036 is not reused for anything.** It is occupied by a managed-futures trend reproduction opened in
   `d0efb51`; the earlier claim that it was "reserved for exact replication" was false and is corrected in
   `docs/roadmap/PROFITABILITY_DISCOVERY_PROPOSAL.md` §0.
4. **A registry is proposed, not assumed.** §12 asks for a tracked `RFC_REGISTRY` so that the next number is
   checked against data instead of prose.

### 01.4 Untouched by construction

CAP-004B and CAP-004D are neither modified nor redirected. The paper campaigns running in this checkout keep their
code environment: this RFC adds documentation plus one audit script, one verifier and one test file, and it changes
no file the paper runtime imports.

## 02 — GOVERNANCE AMENDMENT

### 02.1 The substitution being proposed

```text
BEFORE : only externally complete strategies may enter validation
AFTER  : externally supported economic hypotheses may enter a bounded, preregistered research pipeline
```

**Honest provenance of the "BEFORE" text.** That sentence is a *paraphrase*; it is not a verbatim quotation from
any tracked document. The restrictions it summarises are real and live in four places:

| restriction | where it actually lives |
| --- | --- |
| an admitted opportunity had to ship rules **and** an attributable result **and** a cost model | RFC-035 admission filter, `research/profitability/source_registry.json`, `reports/profitability_gate035/SEARCH_POSTMORTEM.md` |
| a new RFC requires the reentry gate | `docs/research/BUSINESS_REENTRY_POLICY.md` → `"next_rfc_requires": "G_BUSINESS_REENTRY = PASS"` |
| evaluation reopens only on a qualified trigger | `docs/research/PROFITABILITY_OPERATING_MODEL.json` → `next_action_policy.trigger` |
| our own backtesting and parameter search were frozen while RFC-035 was open | `docs/governance/PROFITABILITY_FIRST_FREEZE.md` §2 |

Anyone reading the amendment must therefore read it as *"replace the union of those four restrictions with the
permission in the AFTER line, under the constraints below"*, not as "delete one sentence".

### 02.2 The amendment does not authorize

- real trading;
- automatic modification of the Risk Engine;
- optimisation on OOS;
- auto-promotion to production;
- any increase in leverage;
- retrospective adjustment of success criteria;
- a lower cost model than the applicable one (`§03`);
- reuse of a family already closed by RFC-041 reject conditions;
- new agents unless a demonstrated blocker exists (`§05`).

### 02.3 How approval must be registered

Three contradictions exist today and each must be resolved in the document that owns it — an amendment in one of
them alone leaves the programme unauthorized:

| # | document | contradiction | resolution required |
| --- | --- | --- | --- |
| 1 | `docs/research/BUSINESS_REENTRY_POLICY.md` | `next_rfc_requires = G_BUSINESS_REENTRY = PASS`, and no trigger A/B/C/D/E has fired | either the owner grants an explicit, dated exemption for discovery, or the programme does not start |
| 2 | `docs/research/PROFITABILITY_OPERATING_MODEL.json` | `next_action_policy.trigger` admits only NEW QUALIFIED OPPORTUNITY or MATERIAL CAPITAL / INSTRUMENT CHANGE | amend the trigger to admit a preregistered discovery campaign, stated explicitly |
| 3 | `docs/governance/PROFITABILITY_FIRST_FREEZE.md` | `ACTIVE_RFC: RFC-035` with `status: ACTIVE while RFC-035 is open` — and RFC-035 is now closed, so the freeze's own exit rule is undefined for a `NO_SUITABLE_OPPORTUNITY` ending | close the freeze explicitly and record that its RFC-035-scoped prohibition on our own backtesting lapses, while the RFC-041 business freeze does **not** lift |

Supporting observation, registered rather than fixed: `docs/governance/PROFITABILITY_FIRST_FREEZE.md` is not
tracked by git at the time of this audit. A governance document that other documents depend on should be
versioned. This RFC neither deletes nor commits it — that decision belongs to its owning thread — but the
amendment cannot be considered durable while its object can vanish from the history.

### 02.4 Why RFC-046 is not a forbidden periodic RFC

The operating model forbids creating an RFC "merely because time passes" (`no_periodic_rfc`). RFC-046 is triggered
by an artefact: RFC-035 closed with a written result and a recommendation, on the day it closed, not on a calendar.
That distinguishes it from the forbidden pattern, and the distinction is recorded here so a later reader can
check it.

## 03 — ECONOMIC BASELINE

### 03.1 The audited cost floor

| dimension | value | source |
| --- | --- | --- |
| market / venue | Binance **Spot**, admission scenario `BINANCE_SPOT_STANDARD_TAKER` | `docs/COST_MODEL_V3.json` → `admission_scenario_id` |
| fee tier | VIP0, regular user, 30-day volume < 1,000,000 USD | `docs/AGGTRADES_RESULTS_V1.md` §6 |
| fee-payment mode | `quote_asset` (no BNB discount applied) | `reports/profitability_gate035/ECONOMIC_FEASIBILITY.json` |
| order type | `market`, **taker on both legs** | same |
| size assumption | 1,000 USD notional | `reference_intent.size_usd` |
| liquidity regime | `normal` | `reference_intent.liquidity_regime` |
| holding horizon assumed | 25 minutes | `reference_intent.horizon_minutes` |
| measurement date | 2026-09-27, preregistered in `config/microstructure_preregistration.json` | `measurement_origin` |
| round-trip cost | **23.7906 bps** measured (documented as 23.791) | `round_trip_bps` |
| stressed requirement (1.5x) | **35.6859 bps** | `required_gross_edge_stressed_bps` |

### 03.2 Known versus estimated versus assumed

| component | bps | knowledge class | why |
| --- | ---: | --- | --- |
| exchange fee, entry | 10.0 | **KNOWN** | published Binance spot VIP0 schedule, `SRC-01`; maker and taker are equal at VIP0, so passive execution saves no fee |
| exchange fee, exit | 10.0 | **KNOWN** | same |
| spread | 1.0 | **ESTIMATED** | deliberately rounded **up** from the live `bookTicker` observation (BTC 0.001, ETH 0.04, SOL 0.83 bps), `SRC-07` |
| slippage | 2.6325 | **ESTIMATED** | `MODEL-V3` size / liquidity / volatility factors at 1,000 USD |
| market impact | 0.1581 | **ESTIMATED** | same model |
| adverse selection, funding | not applied | — | no maker legs, spot only |

```text
KNOWN     = 20.0000 bps (84.07% of the floor, irreducible)
ESTIMATED =  3.7906 bps
ASSUMED   =  0.0000 bps
ROUND TRIP = 23.7906 bps
```

The per-asset measured variant of the same model (`docs/EXECUTION_COST_MODEL_V4.md`) gives BTC 23.500, ETH 23.761,
SOL 24.687 bps round trip, with 1.5x break-even requirements of 35.250 / 35.641 / 37.030 bps. The single-number
floor used for admission is the conservative one, and no candidate may claim the BTC figure instead.

### 03.3 Validity scope, stated so it cannot be over-read

Valid for **taker round trips in majors on Binance spot at VIP0 with a ~1,000 USD notional**. It is *not* valid for
the illiquid tail (where a 1.0 bps spread assumption understates reality), *not* a forecast of any particular
strategy's realized cost, and *not* transferable to another venue without a new measurement. At the project's
200 USDT reference capital the same model gives a slightly lower floor (23.35 bps at 200 USD), and the programme
still uses 23.7906 bps for admission so that no apparent improvement comes from a smaller notional.

### 03.4 Turnover is the immediately binding constraint

At 23.7906 bps per round trip, the annual cost drag is a property of the hypothesis, not of the strategy:

| rebalance cadence | round trips / year | annual drag | 1.5x stressed |
| --- | ---: | ---: | ---: |
| monthly | 12 | 2.85% | 4.28% |
| biweekly | 26 | 6.19% | 9.28% |
| weekly | 52 | 12.37% | 18.56% |
| twice weekly | 104 | 24.74% | 37.11% |
| daily | 365 | 86.84% | 130.25% |
| hourly | 8,760 | 2,084.05% | 3,126.08% |

Two conclusions follow, and both are binding on the programme rather than advisory:

1. A family whose edge per round trip is a few basis points is excluded **before any data is loaded**. The
   programme therefore prefers low-turnover hypotheses whose per-trade expected edge can plausibly exceed the fee.
2. For context only (not a baseline): the internal line's own gross measurement was 2.36 bps aggregated and
   0.614 bps tick-level, i.e. roughly 10–40x **below** the cost floor. That is why "same price behaviour, better
   parameters" is not a discovery hypothesis.

Family comparison under equal assumptions: any hypothesis may be compared with any other only using this same
floor, and the comparison must be made at the hypothesis's own natural turnover, converted to annual drag with the
table above. A hypothesis whose annual drag exceeds the benchmark alternative's expectation is dead on arrival and
must be recorded as such.

### 03.5 No cheaper cost model without evidence

No strategy becomes viable by being measured against a cheaper model than the applicable one. The BNB discount is
`POSSIBLE` but **not confirmed** for our account and is therefore not applied; a derivatives venue is
`NEEDS_GOVERNANCE_DECISION` and buying a lower fee with leverage is explicitly refused
(`LEVERAGE_IS_NOT_A_CAPITAL_SUBSTITUTE`). `ZERO_COST` remains diagnostic only.

## 04 — HYPOTHESIS REGISTRY

Each hypothesis entering the pipeline registers this record *before* any measurement:

```yaml
HYPOTHESIS_ID:        H-<nnn>
ECONOMIC_MECHANISM:   one sentence naming who pays and why
EXTERNAL_SOURCE:      source id from research/profitability/source_registry.json, read at full-text level
ASSET_UNIVERSE:       frozen list, majors or a preregistered liquid universe
TIMEFRAME:            frozen
REGIME:               the regime the mechanism is claimed to live in, and the regime it dies in
EXPECTED_EFFECT:      sign and rough magnitude, with its turnover implication in bps/year
INVALIDATION:         the observation that would falsify the mechanism, stated before measurement
COUNTER_EVIDENCE:     known evidence against it, including our own closed results
DATA_REQUIREMENTS:    fields, granularity, PIT availability rule, coverage window
TRANSACTION_COSTS:    the applicable floor from §03 and the drag at the hypothesis's turnover
KNOWN_FAILURES:       what is already known to have failed for this mechanism
```

Rules:

- **A phenomenon is not a strategy.** "Retail flow is compensated" is a hypothesis; "buy at 09:00 and sell at 15:00"
  is a strategy that must be derived from it. The registry stores the phenomenon; `§06` stores the implementation.
- **A hypothesis is not confirmed alpha.** No status other than `PREREGISTERED`, `UNDER_TEST`, `REJECTED`,
  `INCONCLUSIVE` exists in this programme. There is no `VALIDATED_ALPHA` state.
- A hypothesis with no external source is out of scope. A hypothesis whose mechanism is already closed by the
  RFC-041 reject conditions (a new RSI variation, a different moving average, a different threshold, another pair,
  more LLM agents, a new sentiment source, ML bolted onto old features, parameter optimisation, a renamed rule set)
  is inadmissible and must be registered as a re-description of a closed line with our own result attached as
  counter-evidence.

## 05 — DISCOVERY BUDGET

```text
MAX_HYPOTHESES            = 3   (preregistered)
MAX_CANDIDATES_PER_HYPOTHESIS = 1
PARAMETER_SEARCHES        = 0
OOS_INSPECTIONS_ALLOWED   = 1 per candidate
NEW_AGENTS                = 0 unless a demonstrated blocker exists
```

- The budget is declared before the first measurement and is visible in every result.
- **Every attempt is registered, including negative ones.** A silently discarded attempt makes the effective
  number of trials unknowable and is treated as a violation, not an oversight.
- The cap is not refillable: three failed hypotheses end the campaign (`§09`), and a new campaign requires its own
  authorization.
- No new agent, orchestrator or framework is created for this programme unless a blocker is demonstrated in the
  same sense the RFC-035 freeze used that word: it must already have produced a wrong or unusable verdict.

## 06 — STRATEGY CANDIDATE

Before any economic evaluation runs, the candidate freezes and hashes:

```text
STRATEGY_ID · HYPOTHESIS_ID · SOURCE_IDS · ASSETS · TIMEFRAME
ENTRY_RULE · EXIT_RULE · PARAMETERS · SIZING_POLICY
EXECUTION_ASSUMPTIONS · COST_MODEL · RISK_CONSTRAINTS
DATASET_HASH · CONFIG_HASH
```

Binding properties:

- **The strategy proposes signals only.** Sizing, exposure limits, kill switch and every risk constraint stay under
  deterministic components (`src/trading_bot/risk/manager.py`) and no agent may modify them.
- A candidate whose `ENTRY_RULE` or `EXIT_RULE` changes after a measurement is a **new candidate** with a new id;
  the old one stays in the ledger with its result.
- One candidate per hypothesis. A second implementation of the same hypothesis is a parameter search wearing a
  different name.

## 07 — DATA PARTITION

```text
DEVELOPMENT DATA   -> may be used freely inside the hypothesis
VALIDATION DATA    -> used once per candidate, after the hash
FINAL UNSEEN OOS   -> opened once, at the end, and never for selection
```

The verifier must check, mechanically:

```text
data_time <= decision_time   for every feature of every candidate
```

and must block look-ahead, falsified timestamps and future HTF data. This is not a theoretical requirement in this
repository: `WP-HTF-PIT-001` documents an **open** defect, `DEF-HTF-PIT-001`, in
`market_data/htf_pit.py::get_completed_htf_state_at`, where a 15-minute bar is treated as closed 900 *milliseconds*
after its open, so a bar whose true close lies up to one HTF period in the future would be reported as completed.
The helper is currently an orphan (no runtime caller), which is why the defect is latent — and exactly why no
candidate may be wired into an unverified availability helper. The repo already contains the correct convention to
reuse: `autonomous/pit.availability_ms` and `candle_filter.is_candle_complete`, with one definition of the
availability rule and no second copy.

Partition rules:

- the development window is frozen first; the OOS window is opened **once**, after the candidate hash;
- touching OOS to select, tune or compare candidates invalidates the candidate and is a stop condition (`§09`);
- a partition boundary is a dataset artefact with its own hash, not a remembered convention.

## 08 — ECONOMIC HARD GATES

`PROFITABILITY_GATE_V1` is **defined here for the first time**. It was named by the RFC-035 closure but no such gate
existed in the repository, so this RFC cannot "maintain" it — it formalizes it, and says so.

| id | requirement | relation to existing pre-registered criteria (`docs/STRATEGY_ADMISSION_CRITERIA.md`, `c1ffbaa`) |
| --- | --- | --- |
| PG-1 | net expectancy > 0 after the §03 cost model | **strengthens** c2 (`net > 0 and expectancy > 0`) |
| PG-2 | net OOS PnL > 0 | inherits c4 |
| PG-3 | profit factor ≥ **1.10** | **tightens** c3 (which requires `> 1.0`) |
| PG-4 | OOS sample sufficient per the applicable contract | inherits c1 (≥ 100 total and ≥ 30 OOS are the current minima) |
| PG-5 | chronological validation across distinct periods | inherits c5 + the walk-forward convention |
| PG-6 | lower confidence bound of expectancy > 0, using a method valid under serial dependence | **new**; block bootstrap or HAC-style inference, never an i.i.d. t-test |
| PG-7 | 1.5x cost stress remains positive | **tightens** c7 (which requires PF > 0.9 at 2x); both are run |
| PG-8 | no Risk Engine violations | **new**; deterministic risk is not negotiable |
| PG-9 | no excessive dependence on one trade or one regime | inherits c8 (no window > 60% of positive net) and extends it to single-trade dependence |
| PG-10 | multiple-testing correction applied when the campaign ran more than one trial | **new**; total trials must be stated |
| PG-11 | no look-ahead or PIT violation | **new**; enforced mechanically per §07 |

```text
THRESHOLD FREEZE = sealed before any candidate is measured.
Thresholds may not be changed after results are known - in either direction.
```

**No retroactive application.** PG-3 and PG-7 are stricter than the pre-registered criteria, so they apply only to
candidates admitted after RFC-046 is approved. They never re-open, re-score or re-label a closed candidate: the
archive in `docs/research/CANDIDATE_ARCHIVE.json` and the RFC-035 result stay exactly as recorded. Relaxing a
threshold to admit a candidate that already failed is likewise forbidden, on the same principle that made
RFC-035's closure honest.

## 09 — FAILURE POLICY

A strategy that fails is:

```text
CANDIDATE_REJECTED
```

never `TUNE_UNTIL_PASS`. The candidate is closed with its evidence intact; its failure reason is written down; it
is not renamed, re-parameterised or re-scoped into a new attempt.

Infrastructure defects are different: a defect that produced a wrong or unusable verdict is repaired in a **new
version** (a named commit) and the affected measurement is repeated **from a valid baseline**. It is never
patched silently inside a running evaluation, and the defective measurement is retained as the baseline that was
superseded.

If all three preregistered hypotheses fail:

```text
DISCOVERY_CAMPAIGN_FAILED
```

The campaign stops. No further three hypotheses are generated automatically, no new budget is granted, and the
negative result is published exactly as a positive one would be. **A stop is a result.** Anything else is a
search for a number the author likes.

## 10 — INDEPENDENT VERIFICATION

The builder never certifies its own result. A second program, written after the candidate is frozen, re-derives
and checks:

1. the economic source actually says what the hypothesis claims;
2. the rules are the frozen rules, by hash;
3. the data is PIT-available under the declared rule;
4. the result reproduces from the frozen artefacts;
5. the cost model applied is the applicable one, at the candidate's own turnover;
6. the metrics are computed correctly, including the confidence bound (PG-6);
7. the temporal separation is real (no OOS leakage into selection);
8. every gate in §08 is satisfied, not paraphrased;
9. every artefact is traceable to a commit.

```text
FALSE_SUCCESS = 0   is a target that must be measured, not asserted.
BUILDER != VERIFIER is structural: different program, different author-time, and the right to return FAIL.
```

An incomplete verifier, a verifier that errors out, or a verifier that cannot reproduce a result **blocks
promotion**. A verifier that raises an exception instead of returning a verdict is itself a defect (this is
exactly the RFC-035E missing-input failure recorded in §13).

## 11 — PAPER AND LIVE

- The first discovery campaign ends in **offline validation**. That is its entire scope.
- Paper trading requires its own promotion gate, granted separately, with a passing `PROFITABILITY_GATE_V1`,
  a passed robustness battery and an independent verification — never as an automatic consequence of discovery.
- Micro-live requires a **new explicit authorization** with deterministic limits, exactly as the existing chain
  requires (`PAPER_EXECUTION_PASS`, `FORWARD_EVIDENCE`, `RISK_APPROVAL`, `HUMAN_CAPITAL_APPROVAL`).
- No agent may change sizing, leverage or risk constraints. `any_tier_authorized` stays `false`; the reference
  capital stays 200 USDT as `FUTURE_CANARY_CAPITAL`.

## 12 — ROADMAP AMENDMENT

### 12.1 The chain being proposed

The repo already has an authority chain in `docs/research/BUSINESS_REENTRY_POLICY.md`
(`EXTERNAL EVIDENCE → PRODUCT FIT → REPRODUCTION → DISCOVERY → VALIDATION → BENCHMARK EDGE → ROBUSTNESS →
PAPER CERTIFICATION → FORWARD PAPER → CANARY → LIVE`). The discovery chain **inserts inside it** rather than
replacing it:

```text
 DISCOVERY GOVERNANCE            (RFC-046 approval; policies in docs/governance/)
        ↓
 ECONOMIC HYPOTHESIS             (registry, §04; max 3)
        ↓
 FROZEN STRATEGY SPEC            (§06; hash before measurement)
        ↓
 RESEARCH EXECUTION              (DEV only; PIT enforced, §07)
        ↓
 NET OOS VALIDATION              (opened once; PROFITABILITY_GATE_V1, §08)
        ↓
 ROBUSTNESS                      (cost stress 1.25x / 1.5x, sub-periods, regime splits)
        ↓
 INDEPENDENT VERIFICATION        (§10; may FAIL)
        ↓
 FORWARD PAPER                   (separate promotion gate, §11)
        ↓
 MICRO-LIVE                      (new explicit authorization, deterministic limits)
        ↓
 PROFITABILITY CERTIFICATION     (realized net PnL after real costs, not a backtest)
```

The insertion point is between `DISCOVERY` and `VALIDATION` of the existing chain: this programme **is** the
DISCOVERY stage that RFC-041 always described but never authorized to generate its own hypotheses.

### 12.2 Identifiers, checked against the real registry

- `RFC-046` — this document. Free; verified against artefacts, not prose.
- `RFC-045` — **unavailable by design** (asserted absent by three campaign verifiers).
- `RFC-039`…`RFC-044` — occupied; not reused.
- Downstream stage ids are **stage names, not RFC numbers**: no RFC identifier is assigned to `FROZEN STRATEGY
  SPEC`, `NET OOS VALIDATION` and so on. Numbers get allocated one at a time, when a stage actually opens, against
  the registry proposed below. Reserving a block of numbers now is exactly the mistake that produced the false
  "RFC-036 is reserved" claim.
- Proposed, not created: a tracked `RFC_REGISTRY` (planned path `docs/roadmap/RFC_REGISTRY.json`) recording for
  each number its status (`OCCUPIED` / `VACANT_BY_CONTROL` / `FREE`), its artefact and its commit — so that
  collision checking is a data lookup instead of a text search.

### 12.3 Amendment status

The amendment text itself is drafted in `docs/roadmap/PROFITABILITY_ROADMAP_AMENDMENT.md`. As of this document:

```text
tasks/roadmap.md                                  UNCHANGED
docs/research/PROFITABILITY_OPERATING_MODEL.json  UNCHANGED
docs/governance/PROFITABILITY_FIRST_FREEZE.md     UNCHANGED
tasks/decisions.md                                NO ADR RECORDED FOR RFC-046
```

Those four facts are verified mechanically (`§14`, verifier and test) and are the concrete meaning of
`NOT_ACTIVE`.

## 13 — TECHNICAL DEBT

Registered as separate incidents. Only defects that block the active gate are repaired — nothing here blocked this
RFC's gate, so all five are recorded and none is repaired. None is disguised as a PASS.

| # | incident | evidence | status |
| --- | --- | --- | --- |
| TD-1 | **repo-wide `mypy .` cannot complete**: `reports/paper-strategy-lifecycle-shadow-02/analyze.py` collides with `-01/analyze.py` (`Duplicate module named "analyze"`, errors prevented further checking) | `python -m mypy .` → exit 1 | OPEN — the failure belongs to another thread's scratch tree; the diagnosed remedy is to keep mypy out of the gitignored `reports/` tree (or add `__init__.py`), which is a repo-config decision, not this RFC's |
| TD-2 | **RFC-035E verifier raises `TypeError` on missing inputs** instead of returning FAIL/INCOMPLETE | `reports/profitability_gate035/FINAL_REPORT.md`; condition `research/rfc035e/raw_source_manifest.json` absent | OPEN — P2; not repaired because it would edit frozen round-2 evidence; now also a §10 precedent for "a crashing verifier is a defect" |
| TD-3 | **concurrency risk in `reports/`**: multiple threads write a gitignored scratch tree whose module basenames collide (TD-1 is a symptom, not the disease) | `reports/paper-strategy-lifecycle-shadow-01` and `-02`; concurrent untracked work packages | OPEN — mitigate by keeping canonical state in tracked `docs/`/`data/` artefacts (this RFC does that) |
| TD-4 | **execution timestamps fixed by constants**: an artefact's time is chosen by the author rather than measured | `RETRIEVED_AT` constants in `scripts/pgate035_closure.py`, `scripts/rfc035s2_search.py`, `scripts/rfc035s3_closure.py` (three instances; the RFC-035 gate's *value* was corrected in `38885d2`, the *pattern* remains) | OPEN — direction: derive the timestamp from the run, and keep any frozen constant out of a tracked artefact |
| TD-5 | **evidence persistence ignored by git**: `reports/*` is ignored (`!reports/.gitkeep`), so the workspace where results are produced is not versioned, while `evidence/real_decisions/*.jsonl` *is* tracked by deliberate exception. Quantified consequence: of the **26** RFC numbers with artefacts, **17 have no versioned declaration at all** — the ship history of two thirds of the RFC programme exists only on this machine | `.gitignore` lines 55–73; `data/rfc046/audit.json` → `governance.collision.occupied` | OPEN — mitigated here by mirroring state into tracked `docs/rfc/` and `data/rfc046/`, and by proposing the same for future campaigns |

## 14 — DELIVERABLES

Created by this RFC (no programme is activated by any of them):

| # | path | role |
| --- | --- | --- |
| 1 | `docs/rfc/RFC-046_CONTROLLED_DISCOVERY.md` | this document |
| 2 | `docs/rfc/RFC-046_CONTROLLED_DISCOVERY.json` | tracked machine-readable state of this RFC (added beyond the brief's list, because §13 TD-5 makes a tracked canonical record necessary) |
| 3 | `docs/roadmap/PROFITABILITY_ROADMAP_AMENDMENT.md` | the exact amendment text, inert until approved |
| 4 | `docs/governance/DISCOVERY_ADMISSION_POLICY.md` | what may enter the pipeline, and the preregistration form |
| 5 | `docs/governance/DISCOVERY_STOP_RULES.md` | the stop conditions and the campaign state machine |
| 6 | `docs/architecture/DISCOVERY_EXECUTION_FLOW.md` | stages, artefacts, gates, verification boundary |
| 7 | `reports/rfc046/IMPACT_ASSESSMENT.md` | governance, collision and risk impact of approving |
| 8 | `reports/rfc046/FINAL_REPORT.md` / `.json` | measured final state (gitignored working surface) |
| 9 | `data/rfc046/audit.json` | tracked, HEAD-free audit record produced by `scripts/rfc046_audit.py` |
| 10 | `scripts/rfc046_audit.py`, `scripts/rfc046_verify.py`, `tests/unit/research/test_rfc046_discovery_proposal.py` | builder, independent verifier, and the test that keeps the invariants from rotting |

Every artefact that makes a claim cites either a file, a commit or a measurement. Nothing is asserted on the
strength of this document's own authority.

**Path-convention note (the brief asked for adaptation, so the adaptation is recorded).** No requested path
existed before this RFC, so nothing was overwritten. The RFC itself is placed at `docs/rfc/` as requested; the
repository's earlier RFC-numbered specifications live under `docs/research/` (RFC-036 at
`docs/research/MANAGED_FUTURES_TREND_V1.md`, RFC-039/040 in `docs/research/`) and in the separate
`RFC-STRAT-*` namespace. Rather than duplicate this document into a second location — which would create two
sources of truth for one RFC — the roadmap amendment points at `docs/rfc/RFC-046_CONTROLLED_DISCOVERY.md`
explicitly, and the proposed RFC registry (§12.2) would record that path as the artefact for number 046.

## 15 — FINAL DECISION

Owner decision 2026-10-08 (ADR-0024). The pre-approval state is kept for the record:

```text
RFC-046        = APPROVED / ACTIVE (2026-10-08, option 5A)
DISCOVERY      = ACTIVE (offline only)
LIVE_TRADING   = DISABLED
TRADES_AUTHORIZED = 0
```

Applied on 2026-10-08 (ADR-0024), together with the RFC identifier registry:

```text
RFC-046        = APPROVED
offline preregistered research permitted under docs/governance/DISCOVERY_* and PROFITABILITY_GATE_V1
```

Approval means **the permission to look**, and nothing else. It does not imply that a profitable strategy exists,
it does not authorize paper execution, it does not authorize live trading, it does not move the business-edge
milestone (`M0`), and it does not change `PROFITABILITY_VERIFIED = FALSE`. The next gate after activation is a
`PROFITABILITY_GATE_V1` result, and the honest default outcome of the campaign remains
`DISCOVERY_CAMPAIGN_FAILED`.
