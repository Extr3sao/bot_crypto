# ADMISSION-FOUNDATION-01 — CHECKPOINT RECORD

Base: `3c274cc` (consolidated certified runtime) · Branch:
`feat/admission-foundation-01` · POC01 untouched (frozen, campaign
`poc01-paper-observation-01-001`).

## What was built

| Component | Module | Gate |
| --- | --- | --- |
| StrategyRegistry V1 (append-only, identity-hashed, tamper-detecting) | `src/trading_bot/admission/registry.py` | ADM-01 |
| Admission state machine (linear chain + side/terminal states, fail-closed) | `src/trading_bot/admission/states.py` | ADM-02, ADM-05 |
| StrategyAdmissionEngine (BUILDER: proposes evidence-bound promotions only) | `src/trading_bot/admission/engine.py` | ADM-03 |
| StrategyAdmissionVerifier (VERIFIER: independent re-derivation; only it can move state) | `src/trading_bot/admission/verifier.py` | ADM-03, ADM-04 |
| Confirmation Protocol V2 (immutable manifest, future-window ordering, single-use consumption) | `src/trading_bot/admission/confirmation.py` | ADM-08, ADM-09, ADM-10 |
| Shadow Plane V1 (non-authoritative counterfactual evaluation, isolated accounting) | `src/trading_bot/admission/shadow.py` | ADM-11..15 |
| Asset admission contract + honest XRP/DOGE records | `src/trading_bot/admission/assets.py` | §16 |
| Router plane-authority contract (NOT activated in frozen POC01) | `src/trading_bot/admission/router_contract.py` | ADM-18 |
| Frontend projection contract (strategy lab / asset lab / shadow) | `src/trading_bot/admission/projections.py` | ADM-19 |
| Bootstrap (registry seed + manifest pre-registration) | `scripts/bootstrap_admission_foundation.py` | ADM-06, ADM-07 |

## Registered strategies (honest)

- **5 runtime strategies** (`poc01-momentum/trend/breakout/mean_reversion/volatility`):
  `LEGACY_PAPER_BASELINE` — certified to RUN in the frozen POC01 PAPER plane,
  but with NO modern discovery/robustness/CV/walk-forward/confirmation gates.
  Evidence is NOT fabricated; the grandfathered status is documented in each
  record. Retro-admission may run later without touching the frozen campaign.
- **3 EDGE-RESEARCH-002 passers** (`DISCOVERY_PASS` +
  `CONFIRMATION_BLOCKED`): H-A momentum LONG SOL (n=51, +0.250R, PF 1.33),
  H-A breakout LONG SOL (n=36, +0.342R, PF 1.37), H-F session ema_crossover
  LONG SOL (n=34, +0.616R, PF 1.79). SOL concentration 100%, LONG
  concentration 100% preserved. NOT promoted.

## Confirmation authority (future window)

`CONF-EDGE-002-001` pre-registered with window 2026-09-08T00:00Z →
2026-09-22T00:00Z (14 complete UTC days per RFC-CONFIRMATION-PROTOCOL-V2;
N>=30 ex-ante; frozen v2 acceptance criteria; single-use consumption).
`manifest_commit_time < window_start < execution_time` provable from git.
Execution NOT authorized in this checkpoint; confirmation executions = 0.

## Shadow Plane first use case

Counterfactual evaluation of POC01 Risk-rejected valid decisions
(MAX_POSITIONS / CONSECUTIVE_LOSS_COOLDOWN). Structural isolation is
enforced: authority-bearing objects (broker/risk methods) are rejected at
entry; `PaperBroker` calls from shadow = 0; RiskManager untouched; shadow
accounting is separate and labeled SHADOW_ONLY / COUNTERFACTUAL /
EXCLUDED_FROM_POC01_PNL / EXCLUDED_FROM_POC01_FREQUENCY.

Honest limitation: the running POC01 campaign persists aggregate risk
metrics but not per-rejected-decision proposals/prices, so historical
counterfactual backfill is NOT possible without fabricating data. The
capability is certified with hermetic fixtures; actual backfill requires a
per-decision persistence addition at a future authorized checkpoint.
The shadow plane answers §14's questions observationally and does NOT
recommend relaxing Risk.

## Asset admission contract

Contract-only (fields defined); XRP and DOGE recorded as `ASSET_CANDIDATE`
with liquidity PASS and incremental opportunity FAIL/current universe
(measured evidence from `feat/edge-research-002@e831420`). Not promoted.

## Gates

| Gate | Result |
| --- | --- |
| ADM-01 StrategyRegistry | PASS |
| ADM-02 Admission state machine | PASS |
| ADM-03 Builder != Verifier | PASS (verifier never imports engine; engine has no apply path) |
| ADM-04 Evidence-bound promotion | PASS (missing/forged/stale evidence rejected) |
| ADM-05 Illegal transitions fail-closed | PASS (incl. DISCOVERY_PASS→PAPER_ELIGIBLE) |
| ADM-06 Runtime strategy registration | PASS (5, LEGACY_PAPER_BASELINE) |
| ADM-07 Discovery passer registration | PASS (3, DISCOVERY_PASS/CONFIRMATION_BLOCKED) |
| ADM-08 Confirmation Protocol V2 | PASS |
| ADM-09 Future-data authority | PASS (manifest commit < window start, git-provable) |
| ADM-10 Confirmation consumption guard | PASS (single-use registry) |
| ADM-11 Shadow Plane isolation | PASS (authority objects rejected at entry) |
| ADM-12 ShadowTrade contract | PASS (immutable, all §11 fields) |
| ADM-13 Shadow accounting isolation | PASS |
| ADM-14 Risk-reject counterfactual support | PASS (capability; historical backfill NOT_PERSISTED — honest) |
| ADM-15 Duplicate prevention | PASS (source_decision_id) |
| ADM-16 PIT safety | PASS (PIT proof required for market-data promotions; entry uses execution-bar-open semantics ref) |
| ADM-17 Traceability | PASS (promotion_history replay) |
| ADM-18 Router integration contract | PASS (pure mapping; not activated) |
| ADM-19 Frontend projection contract | PASS (read-only projections) |
| ADM-20 POC01 untouched | PASS (0 runtime changes; campaign continues) |
| ADM-21 PaperBroker calls from Shadow = 0 | PASS |
| ADM-22 LIVE = 0 | PASS |
| ADM-23 FALSE_SUCCESS = 0 | PASS (no fabricated evidence; honest NOT_PERSISTED) |

**ADMISSION_GATES: 23/23 PASS**

## Verification

- Admission tests: 33/33 (`tests/unit/admission/`)
- Ruff scoped: 0 findings · Mypy scoped: 0 errors
- Full regression: see gate report in evidence commit
- POC01 health re-checked unchanged (ACTIVE, cycling, LIVE=0)
