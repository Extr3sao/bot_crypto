# FINAL REPORT — MA-DIRECTION-ARBITRATION-AND-POC02-REPAIR-01

| Field | Value |
| --- | --- |
| **CHECKPOINT** | MA-DIRECTION-ARBITRATION-AND-POC02-REPAIR-01 |
| **BASE** | `53c5910` + POC02 observation lineage (runtime commit at launch: `6f0513fbc609…`) |
| **POC02_PRE_REPAIR** | Frozen: `POC02_PRE_REPAIR_BASELINE.{md,json}` + `poc02-pre-repair/` (5 artifact SHA-256 hashes; 11 cycles, 33 windows, 18 candidates) |
| **STRUCTURAL_DIRECTION_DEFECT** | **CONFIRMED** |
| **ROOT_CAUSE** | Composition layer (`_proposal_set` dual-direction loop) submits mutually exclusive alternatives of one evaluation as simultaneous independent claims → `CounterSignalCritic` (per its own correct contract) surfaces each as the other's counter-signal → debate deterministically UNRESOLVED → MA-4 `INELIGIBLE_UNRESOLVED_CONFLICT`. ROOT_COMPONENT = composition + MA-3/MA-4 contract gap; ROOT_CONTRACT = CounterSignalCritic × UNRESOLVED_CONFLICT eligibility gate |
| **LONG_SHORT_SEMANTICS** | **ALTERNATIVE_DIRECTIONS** (proven from family source, board conflict model, router/critic/decision contracts — not AMBIGUOUS_CONTRACT, not INDEPENDENT_PROPOSALS) |
| **COUNTERSIGNAL_CRITIC_DEFECT** | **NO** — critic behaves per contract; it was fed alternatives as independent claims. **CRITIC_WEAKENED: false** (source untouched; adversarial authority preserved) |
| **DIRECTION_ARBITRATION** | **PASS** — `OpportunityGroup` + deterministic LLM-free `DirectionArbiter` (closed-set rule: sole→select, strict-higher-score→win, tie/below-floor→NONE) + independent `OpportunityGroupVerifier` (builder ≠ verifier) |
| **NO_FORCED_DIRECTION** | **PASS** — NONE first-class; sole-candidate below floor ⇒ NONE; tie ⇒ NONE; no code path fabricates a direction (test-enforced) |
| **MOMENTUM_RUNTIME** | PROPOSAL_GENERATED (fixture-echo composition only — canonical expert bypassed on POC02 runtime path) |
| **TREND_RUNTIME** | NOT_RUNTIME_REACHABLE (registered + invoked, never consulted by POC02 composition) |
| **BREAKOUT_RUNTIME** | NOT_RUNTIME_REACHABLE (same) |
| **MEAN_REVERSION_RUNTIME** | NOT_RUNTIME_REACHABLE (same) |
| **VOLATILITY_RUNTIME** | NOT_RUNTIME_REACHABLE (same) |
| **STRATEGY_RUNTIME_DEFECT** | **DEF-STRAT-RUNTIME-001 — LEGACY_STRATEGY_RUNTIME_REACHABILITY** (composition bypass; NOT auto-activated; frozen in R2 manifest) |
| **NATURAL_CASES_TO_RISK** | **3/3 natural** public binanceusdm-5m windows reached candidate→arbitration→critique→decision→verifier VERIFIED→Risk (3/3 ACCEPT); fixture secondary proof also 3/3. Reports: `reports/poc02-r2-smoke/R2_SMOKE_*.json` |
| **VERIFIER** | **PASS** — `OpportunityGroupVerifier`: candidate binding, group membership (same run/trace/asset/strategy/timeframe), score integrity (forged score rejected), losing-side preservation, counter-evidence integrity, PIT, group-id replay determinism; also passes the pre-existing MA-4 package verifier |
| **OLD_POC02_CLASSIFICATION** | **DIAGNOSTIC_BLOCKED_CAMPAIGN** — STRUCTURAL_AGENT_DIRECTION_CONFLICT (`POC02_CAMPAIGN_CLASSIFICATION.md`); no frequency/profitability claims; preserved as execution evidence |
| **OLD_POC02_ARTIFACTS_CHANGED** | **0** (git-verified; frozen copies hash-match baseline) |
| **REPLACEMENT_CAMPAIGN_MANIFEST** | `docs/external-audit-01/POC02_R2_MANIFEST.md` (PREREGISTERED: runtime commit, strategies, assets, provider, Risk-policy hash, agent-config hash, arbitration-contract hash, fees/slippage, coverage ≥ 0.80, Shadow V2, frequency KPI) |
| **REPLACEMENT_CAMPAIGN_LAUNCHED** | **true** (all 8 preregistered gates passed; no human approval required for PAPER per H1) |
| **NEW_CAMPAIGN_ID** | **`POC-02-R2-direction-arbitration-01`** (fresh identity, fresh accounting, fresh Shadow ledger `data/storage/shadow/poc02-r2/`) |
| **SHADOW_V2** | ENABLED — RiskGateRouter + ShadowCandidateCapture on the R2 bundle; isolation rules unchanged (SHADOW_PAPERBROKER_CALLS = 0) |
| **CARRY_FUNDING_DEEP_PREREG** | **PREREGISTERED / NOT_STARTED** — `CARRY_FUNDING_DEEP_01_PREREG.md` (pagination/units/timestamp/PIT/fingerprint/cost contracts; old invalid fingerprint discarded; no research executed) |
| **CONFIRMATION_CONSUMED** | **false** (verified from committed `CONFIRMATION_MANIFEST.json` @ `39578a6`) |
| **CONFIRMATION_EXECUTIONS** | **0** |
| **RISK_CHANGED** | **0** (RiskManager source untouched) |
| **THRESHOLDS_CHANGED** | **0** (signal thresholds stay owned by strategy families; critics and debate thresholds untouched) |
| **LIVE_CALLS** | **0** (also REAL_BROKER=0, PRIVATE=0, SHADOW_PAPERBROKER=0; public REST + PAPER only) |
| **FALSE_SUCCESS** | **0** |
| **TESTS** | 13/13 arbitration adversarial tests + DIR-01 natural reproduction PASS (ruff + mypy clean on all changed files) |
| **HERMETIC_REGRESSION** | **1165 passed / 0 failed** |
| **STATUS** | **PASS** |
| **NEXT** | **RUN_CLEAN_CAMPAIGN** (`POC-02-R2-direction-arbitration-01` daily observation) **+ SHADOW_OBSERVATION** **+ REGIME_BOTTLENECK_ANALYSIS** (on the now-unblocked funnel) **+ CARRY_FUNDING_DEEP_RESEARCH** (after contract validation) **+ CONFIRMATION_WAIT** (2026-09-22) |

## Acceptance criteria

| ID | Criterion | Verdict |
| --- | --- | --- |
| DIR-01 | natural conflict reproduced | PASS — `test_poc02_natural_conflict_reproduction` (real MA-2→MA-3→MA-4 flow, no synthetic shortcut) |
| DIR-02 | direction semantics proven | PASS — ALTERNATIVE_DIRECTIONS (DIR-AUDIT-01 §B1) |
| DIR-03 | root cause identified | PASS — exact ROOT_COMPONENT/SYMBOL/CONTRACT/MECHANISM (§B2) |
| DIR-04 | alternative vs true counter-evidence separated | PASS — D3 contract; group-scope-limited arbitration; counter refs = losing side's evidence |
| DIR-05 | deterministic arbitration | PASS — closed-set rule, LLM-free, evidence-score authority only |
| DIR-06 | NONE remains valid | PASS — tie/floor/sole-below-floor → NONE with closed-set reasons |
| DIR-07 | critic not weakened | PASS — debate/decision sources untouched; cross-strategy conflict authority intact |
| DIR-08 | independent verifier | PASS — OpportunityGroupVerifier re-derives all claims; forged score + stripped side + cross-run + future-dated rejected |
| DIR-09 | PIT | PASS — future proposal/evidence rejected at formation + verification |
| DIR-10 | replay deterministic | PASS — identical inputs → identical group_id and payload (test-enforced) |
| DIR-11 | natural runtime can reach Risk when valid | PASS — 3/3 natural windows through the full chain (honest report; fixture secondary proof) |
| DIR-12 | no forced trades | PASS — NO_FORCED_DIRECTION structural |
| STR-01/02/03 | invocation audit | PASS — all 5 audited; NO_SIGNAL ≠ NOT_INVOKED ≠ NOT_RUNTIME_REACHABLE; DEF-STRAT-RUNTIME-001 registered |
| POC-01..05 | evidence/campaign governance | PASS — frozen+hashed, honest classification, manifest preregistered, new identity, Shadow V2 preserved |
| GOV-01..06 | Risk/thresholds/POC01/confirmation/live/false-success | PASS — all zero/unchanged (git-verified) |

## Key evidence notes

1. **The repair adds arbitration, not trades**: the R2 smoke selected SHORT on
   all three assets (each asset's downward-momentum side scored strictly
   higher on that window) — a deterministic outcome of preregistered scoring,
   not a loosening. Equal-score windows still end NO_TRADE (test-enforced).
2. **Provenance preservation**: every resolved group records both candidate
   refs, both direction scores, and the losing side's evidence as
   `EXPECTED_ALTERNATIVE_DIRECTION` — nothing is stripped (verifier-enforced).
3. **Frozen-behavior safety**: `_proposal_set` defaults to `arbitrate=False`;
   the frozen POC02 composition, POC01 demo, and all committed campaign
   artifacts are byte-identical to the baseline.
