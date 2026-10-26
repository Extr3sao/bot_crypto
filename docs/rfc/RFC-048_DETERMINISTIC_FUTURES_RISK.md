# RFC-048 — DETERMINISTIC FUTURES RISK & LEVERAGE ENGINE

| field | value |
| --- | --- |
| RFC | **RFC-048** |
| STATUS | **IMPLEMENTED / RFC048_OFFLINE_VERIFIED** (offline only) |
| BASELINE | `66cfe08` (branch `main`) |
| MODE | offline deterministic research; **no paper orders, no live, no credentials** |
| SUPERSEDES | nothing |
| REFERENCES | RFC-046 (discovery, `FAILED`), RFC-047 (ST-6, untouched), `COST_MODEL_V3` (unmodified) |
| LIVE_TRADING | `DISABLED` |
| TRADES_AUTHORIZED | 0 |
| PROFITABILITY_VERIFIED | `FALSE` |
| FALSE_SUCCESS | 0 |
| VERDICT ARTEFACT | `data/rfc048/FINAL_REPORT.json` |

> **`RFC048_OFFLINE_VERIFIED` means exactly one thing**: the contracts and risk
> calculations this RFC supports passed offline verification, with a verifier that imports
> none of the builder's arithmetic and with eight negative controls that all fire. It does
> **not** mean profitable, admitted, eligible, or ready for production.

## 00 — MISSION AND SCOPE

Build a runtime that can operate futures **in a controlled way, when a genuinely profitable
strategy exists** — not leverage that hides a strategy without an edge. RFC-048 delivers the
risk plane and proves it works offline. It creates no strategy, opens no discovery campaign,
reuses no rejected out-of-sample result, sends no order and reads no private key.

Delivered scope: an **isolated, linear, USDT-margined perpetual** risk plane for one real
instrument (`BINANCE_USDM BTCUSDT PERPETUAL`), plus explicit refusals for every contract type
it does not model.

## 01 — RUNTIME AUDIT (WP-048-01)

Full classification in `docs/architecture/RFC048_RUNTIME_AUTHORITY_MAP.md`. Headlines:

- `RiskManager` (spot) is `RUNTIME_AUTHORITATIVE` and was **not modified**; no second risk
  engine was written.
- `DecisionEngine` + `autonomous/contracts.py` are the existing decision boundary and are
  **consumed** by the new adapter.
- No futures risk code existed anywhere in `src/` (no `leverage`, `liquidation`,
  `maintenance_margin` or `funding_rate` in any runtime module).
- `paper/portfolio_manager.py` is an orphan (0 importers) and was left alone;
  `research/managed_futures_v1.py` is an RFC-036 experiment and was reviewed, not extended.

## 02 — ARCHITECTURE

Two planes, one boundary: the deterministic trading runtime plane decides; the agent plane
only proposes. `docs/architecture/RFC048_FUTURES_RISK_FLOW.md` carries the full gate order.
The agent plane cannot set leverage, size, margin, risk limits, liquidation price or
execution authorisation: `RiskProposal` has no field for those, and every request is capped
by `min(request, policy, venue ceiling)`.

## 03 — INSTRUMENT CONTRACT

`InstrumentSpec` carries venue, contract type, collateral/settlement assets, multiplier,
step, tick, min/max notional, the venue's maintenance-margin ladder, fee schedule, funding
schedule, supported position modes, regulatory status and provenance
(`source_version`, `source_hash`, `source_hash_brackets`, `effective_timestamp_ms`).

Implemented: **`LINEAR_PERPETUAL`, isolated margin, multiplier 1.0**. Declared and refused:
`INVERSE_PERPETUAL` (no coin-margined algebra, no fixture fetched → `INSTRUMENT_NOT_SUPPORTED`),
`DELIVERY_FUTURE` (real quarterly fixture registered, settlement mechanics unmodelled →
`CONTRACT_TYPE_NOT_IMPLEMENTED`), and `CROSS` margin (dependencies unvalidated). No linear
formula is ever applied to a non-linear contract.

## 04 — CAPITAL & RISK BUDGET, SIZING (WP-048-03)

Experimental reference equity 200 USDT; 0.5 % and 1 % risk-budget scenarios only, never live
limits. The sizer enforces

```text
EXPECTED_STOP_LOSS_WITH_COSTS = notional·stop% + notional·gap_reserve% + round_trip_cost
                              <= RISK_BUDGET
```

with the quantity floored to the venue step (rounding may only reduce), the gap reserve
mandatory (absent → `GAP_RESERVE_MISSING`), and a post-rounding re-check. The stop is never
treated as a guaranteed fill.

## 05 — LEVERAGE ENGINE (part of WP-048-04)

Scenarios `1x/2x/3x/5x` are test values. The admissible leverage is
`min(requested, policy cap, venue bracket ceiling)`; a request for 500x yields 5x
(scenario S23) and a reduction is reported as `REDUCE_SIMULATED_SIZE`, never as an approval
of the request. Exceeding margin or risk budget ⇒ `RISK_VETO`.

## 06 — LIQUIDATION MODEL

Isolated linear closed form of the venue's margin condition, with the ladder taken from the
venue payload and the worst touched bracket charged on stress paths. Funding owed and the
venue liquidation fee are charged before solving. Missing ladder, missing mark price or
missing liquidation fee ⇒ `LIQUIDATION_RISK_UNKNOWN` and no approval. Partial liquidation is
**not** modelled: a stress path that reaches liquidation voids the trade
(`GAP_BEYOND_STOP` + `PARTIAL_LIQUIDATION_UNSUPPORTED`).

**DEF-048-01** (found by the independent verifier, fixed): the long-side closed form
subtracted the adverse terms instead of adding them, over-stating the distance to
liquidation. The verifier's numeric root exposed it; see
`data/rfc048/INDEPENDENT_VERIFICATION.json → model_level_cases`.

## 07 — FUNDING & COSTS (WP-048-02, part of WP-048-06)

`SPOT_COST_MODEL` and `FUTURES_COST_MODEL` are separate; the 23.7906 bps spot figure is
**not** reused for futures (it is cited for the spot column of the comparison). The futures
model charges commission, measured spread, assumed slippage, measured depth impact, funding
and reports the liquidation fee. States `COST_KNOWN` / `COST_ESTIMATED` / `COST_UNKNOWN`;
unknown is refused, never zero. Funding is point-in-time (only settlements published at or
before the decision instant) and is zero **only** when the venue's own interval proves no
settlement falls inside the horizon.

## 08 — PORTFOLIO RISK (WP-048-05)

Gross/net exposure, concentration, correlation keys, shared-collateral refusal, margin
utilisation, drawdown, daily loss, consecutive losses and provider freshness, all evaluated
against a versioned snapshot. `MarginLedger.try_reserve` is atomic, so two simultaneous
decisions cannot spend the same free margin: the executed probe runs 8 concurrent decisions
against one 200 USDT pool and the ledger invariant holds.

## 09 — RISK DECISION CONTRACT

`RiskDecision` carries the full §11 field set plus sizing, margin, liquidation, cost and
portfolio evidence. Decisions: `APPROVE_SIMULATION`, `REDUCE_SIMULATED_SIZE`, `NO_TRADE`,
`RISK_VETO`, `DATA_INVALID`, `UNSUPPORTED_INSTRUMENT`. `order_authorised` is always `False`.

## 10 — ADVERSARIAL TESTS (§12)

All 24 required cases exist as named tests in
`tests/unit/risk/test_futures_risk_engine.py`, alongside property/invariant tests
(rounding never increases risk; a costlier assumption never approves a bigger size; leverage
never exceeds any applicable limit; no decision authorises an order) and the concurrency
requirement. Executed offline catalogue: **31 scenarios, 31 expectations met, 8 approvals,
23 refusals, 0 order authorisations**.

## 11 — INDEPENDENT VERIFIER (WP-048-07)

`src/trading_bot/risk/futures_verification.py` imports **no** builder module (proved in a
fresh interpreter, recorded in the verification artefact). It re-derives sizing by grid
search, margins from the raw ladder, liquidation by numeric root **and** by bar-by-bar
simulation over the venue's real 5-minute closes, funding from the venue settlement history,
and the aggregate margin pool. Measured: **31/31 decisions verified, 303 checks, 0 failures,
8/8 negative controls detected, FALSE_SUCCESS = 0, reproducible across two passes**.

## 12 — REGULATORY & VENUE GATE (§14)

Status recorded per instrument: `PRODUCT_ELIGIBILITY_UNKNOWN`, `research_allowed = true`,
`production_eligible = false`. ESMA's statement of 24/02/2026
(`ESMA35-243228190-8024`, raw payload + sha256 stored under `data/rfc048/raw/`) notes that
derivatives marketed as perpetual futures may fall within national CFD product-intervention
measures (leverage limits, margin close-out, negative balance protection). Therefore: offline
research on venue fixtures is allowed; **promotion to production is refused by construction**
(scenario S28 returns `DATA_INVALID / VENUE_OR_PRODUCT_NOT_ELIGIBLE`).

## 13 — WORK PACKAGES

| WP | state | evidence |
| --- | --- | --- |
| WP-048-01 Runtime audit | DONE | `docs/architecture/RFC048_RUNTIME_AUTHORITY_MAP.md` |
| WP-048-02 Instrument contracts | DONE | `data/rfc048/INSTRUMENTS.json`, `futures/instruments.py`, `futures/costs.py` |
| WP-048-03 Risk-bounded sizing | DONE | `futures/sizing.py`, S01-S06, invariant tests |
| WP-048-04 Liquidation & margin | DONE | `futures/margin.py`, `MARGIN_LIQUIDATION_CASES.json` |
| WP-048-05 Portfolio risk | DONE | `futures/portfolio.py`, concurrency probe |
| WP-048-06 Economic feasibility | DONE | `ECONOMIC_FEASIBILITY.json`, `docs/research/RFC048_FUTURES_ECONOMIC_FEASIBILITY.md` |
| WP-048-07 Independent verification | DONE | `INDEPENDENT_VERIFICATION.json` |
| WP-048-08 Runtime integration | DONE | `futures/integration.py`, S-probe, integration tests |

No additional work packages were created.

## 14 — ACCEPTANCE CRITERIA

| id | criterion | state | evidence |
| --- | --- | --- | --- |
| ACC-048-01 | risk engine integrated in the relevant runtime | PASS | adapter onto the real `DecisionEngine`; `runtime_integration.reachable = true` |
| ACC-048-02 | existing spot without regressions | PASS | 3121 unit tests pass; `RiskManager` unmodified |
| ACC-048-03 | futures supported with an explicit contract | PASS | `InstrumentSpec` + venue fixture with hashes |
| ACC-048-04 | sizing subject to budgeted losses | PASS | verifier re-checks `worst_loss <= budget` for every approval |
| ACC-048-05 | verifiable margin limits | PASS | margins recomputed from the raw ladder |
| ACC-048-06 | liquidation simulated under an identified model | PASS | closed form + numeric root + bar simulation |
| ACC-048-07 | funding and costs included | PASS | PIT funding, measured spread/impact, unknown refused |
| ACC-048-08 | `NO_TRADE` and `RISK_VETO` work | PASS | 23 refusals across the catalogue |
| ACC-048-09 | no look-ahead, no stale data | PASS | S18/S19/S20 + freshness gate |
| ACC-048-10 | independent verification | PASS | 0 builder imports, 303 checks |
| ACC-048-11 | adversarial tests | PASS | 24/24 §12 cases |
| ACC-048-12 | evidence of real offline execution | PASS | `RUNTIME_EXECUTION_REPORT.json` |
| ACC-048-13 | no live order or credential | PASS | `order_authorised_anywhere = false`, `live_orders_sent = 0` |
| ACC-048-14 | reproducible economic comparison | PASS | `ECONOMIC_FEASIBILITY.json` + research doc |
| ACC-048-15 | `FALSE_SUCCESS = 0` | PASS | 8/8 controls detected; a control that cannot run FAILS the verdict |

## 15 — FAILURE CONDITIONS (§19) — self-assessment

| condition | triggered? | note |
| --- | --- | --- |
| integration exists only in test code | **NO** | executed through the real `DecisionEngine` in `scripts/rfc048_run.py` |
| liquidation formula is an approximation sold as exact | **NO** | derivation stated; verifier re-solves numerically and by simulation |
| a required margin bracket is missing | **NO** | 12-bracket ladder from the venue payload, continuity asserted |
| costs omitted | **NO** | unknown components refuse the trade |
| the stop is treated as a guarantee | **NO** | gap reserve required; `STOP_MISSING` refuses |
| a risk policy can be bypassed | **NO** | advisory-only adapter; the runtime refuses advisory reviews on authorising packets |
| results are not reproducible | **NO** | two verification passes identical; scripts are idempotent |
| spot/futures comparison uses incompatible assumptions | **NO** | both columns frozen and documented; grid-aligned sizes |
| no real offline execution | **NO** | `data/rfc048/RUNTIME_EXECUTION_REPORT.json` |
| the verifier depends on the builder | **NO** | fresh-interpreter probe: 0 builder modules |
| an unsupported product is treated as production-ready | **NO** | `production_eligible = false`; S29/S30 refuse by name |

## 16 — GOVERNANCE (§18)

Unchanged and asserted in the artefacts: `DISCOVERY_CAMPAIGN_FAILED`,
`NEXT_CAMPAIGN = NOT_AUTHORIZED`, `LIVE_TRADING = DISABLED`, `TRADES_AUTHORIZED = 0`,
`PROFITABILITY_VERIFIED = FALSE`. The ST-6 scheduler was not touched, `COST_MODEL_V3` was not
modified, no API key was read, no paper position is opened automatically, and
`config/risk.yaml` is byte-identical.

## 17 — DEFINITION OF DONE

`REQ → ACC → ARCH → IMPLEMENTATION → TEST → REAL_OFFLINE_EXECUTION → EVIDENCE →
INDEPENDENT_VERIFICATION` — complete. State: **`RFC048_OFFLINE_VERIFIED`**.

`RFC048_PARTIAL` would have been the honest state if any of: the verifier imported the
builder, a negative control failed to fire, the executed catalogue missed an expectation, or
the liquidation model was incomplete. None of those hold (see `FINAL_REPORT.json`).

## 18 — NEXT GATE

Before any live use of this plane: an independently verified admitted strategy with a
measured edge; a jurisdictional eligibility check for venue and account type; a **binding**
(non-advisory) futures review enabled by an ADR; partial-liquidation and cross-margin rules
or an explicit decision to exclude them; and paper-trading evidence for the futures plane
itself. See §21 of `data/rfc048/FINAL_REPORT.md`.
