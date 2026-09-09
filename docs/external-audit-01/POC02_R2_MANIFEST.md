# POC02-R2 MANIFEST — POC-02-R2-direction-arbitration-01

Checkpoint: **MA-DIRECTION-ARBITRATION-AND-POC02-REPAIR-01** (TRACK H)
Status: **PREREGISTERED** — all freezes below are committed before launch.
Mode: PAPER only. No credentials. LIVE_CALLS must remain 0.

## 1. Identity

| Field | Value |
| --- | --- |
| CAMPAIGN_ID | `POC-02-R2-direction-arbitration-01` |
| PREDECESSOR | `POC-02-paper-clean-01` (DIAGNOSTIC_BLOCKED_CAMPAIGN — see `POC02_CAMPAIGN_CLASSIFICATION.md`) |
| REPAIR CONTRACT | ADR-DIR-0001 — deterministic direction arbitration (`src/trading_bot/multi_agent/arbitration.py`) |
| RUNTIME COMPOSITION | `_proposal_set(..., arbitrate=True)` (POC02-R2 launcher only; frozen POC02 composition preserved) |

## 2. Preregistered freezes (before launch)

| Freeze | Value |
| --- | --- |
| RUNTIME_COMMIT | set at launcher write-time from `git rev-parse HEAD` |
| STRATEGIES | fixture-echo momentum composition (unchanged from POC02); canonical strategy reachability is DEF-STRAT-RUNTIME-001, NOT activated here |
| ASSETS | BTC, ETH, SOL |
| MARKET_DATA_PROVIDER | binanceusdm (public REST OHLCV, no credentials) |
| EXECUTION | PAPER / PaperBroker |
| RISK_POLICY_HASH | sha256 of `src/trading_bot/risk/manager.py` at launch (Risk unchanged — GOV-01) |
| AGENT_CONFIGURATION_HASH | sha256 over `multi_agent/{specialists,debate,decision}.py` at launch (critics unchanged — DIR-07) |
| DIRECTION_ARBITRATION_CONTRACT_HASH | sha256 of `src/trading_bot/multi_agent/arbitration.py` at launch |
| FEES / SLIPPAGE | PaperBroker preregistered schedule (unchanged from POC02) |
| COVERAGE_CONTRACT | ≥ 0.80 per completed UTC day (preregistered, never lowered) |
| SHADOW_V2 | ENABLED — RiskGateRouter + ShadowCandidateCapture, SHADOW_PAPERBROKER_CALLS = 0 |
| FREQUENCY_KPI | ≥ 3 executed valid PAPER trades per valid UTC day (unchanged target; quality gates never lowered) |
| CONFIRMATION_LOCK | CONF-EDGE-002-001 untouched (2026-09-08 → 2026-09-22, consumed=false, executions=0) |

## 3. Preregistered launch gates (all must pass; no human approval required for PAPER)

1. `old_campaign_artifacts_immutable` — sha256 of frozen POC02 artifacts match `POC02_PRE_REPAIR_BASELINE.json`.
2. `campaign_id_new` — R2 ID ≠ any prior campaign ID.
3. `arbitration_contract_importable` — `DirectionArbiter` + `OpportunityGroupVerifier` import and pass adversarial suite.
4. `provider_authority_explicit` — same authority block as POC02 (PAPER, binanceusdm public, PaperBroker).
5. `coverage_contract_preregistered` — ≥ 0.80 committed in this manifest.
6. `shadow_surface_importable` — ShadowCaptureHook + RiskGateRouter constructible.
7. `safety_counters_zero` — LIVE_CALLS = REAL_BROKER_CALLS = PRIVATE_EXCHANGE_CALLS = 0 enforced in bundle init.
8. `smoke_reached_risk` — TRACK F smoke shows the arbitrated composition can reach Risk (fixture proof accepted when no natural signal exists; natural count reported honestly).

## 4. Accounting

New reports root `reports/poc02-r2-direction-arbitration-01/`, new Shadow
ledger `data/storage/shadow/poc02-r2/` (relative to runner outputs), new
attribution/paper-trade ledgers. Nothing is shared with POC01 or POC02
except the immutable code contracts.

## 5. Analysis plan (inherited, unchanged semantics)

Daily coverage + performance, frequency KPI, bottleneck telemetry (canonical
taxonomy incl. OTHER_RISK), bottleneck × regime matrix, strategy contribution,
agent-filter rates, shadow V2 resolution + risk-value test, regime coverage
map, RUNTIME_STALE watch — all observational, per
`POC02-OBSERVATION-AND-ALPHA-DIAGNOSIS-01` semantics, now on a composition
that can actually reach Decision/Risk.
