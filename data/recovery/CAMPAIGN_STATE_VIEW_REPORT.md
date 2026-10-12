# CAMPAIGN STATE VIEW (WP-2)

- generated `2026-10-12T18:40:41Z` · head `90cee7327e69` · branch `agent/edge-recovery/WP-EDGE-00-baseline`
- **status: CONSISTENT_WITH_ADVISORIES** · sources unchanged: True

A frozen declaration is a historical record. This view resolves, per campaign and per field, which statement is *current*, using this precedence and nothing else:

| rank | level | rule |
| ---: | --- | --- |
| 1 | `P1_governance_decision` | the LATEST ADR in file order that names the campaign decides; ADRs are the highest authority (the charter grants the operator the power to amend governance) |
| 2 | `P2_campaign_record` | a closure or verification record written by the campaign itself decides next |
| 3 | `P3_runtime_ledger` | what the runtime actually enforces decides next |
| 4 | `P4_frozen_declaration` | a frozen declaration is a HISTORICAL record: it is never read as the current state unless nothing above it speaks |

## Campaigns

### RFC-046 — RFC-046 discovery campaign (recommended default route)

- governing decision: `ADR-0024` RFC-046: excepcion limitada y fechada de RFC-041 para Controlled Discovery (offline)

| field | effective value | decided by | superseded |
| --- | --- | --- | --- |
| TERMINAL_STATE | `"DISCOVERY_CAMPAIGN_FAILED"` | `P1_governance_decision` tasks/decisions.md#ADR-0024 | — |
| CHECKS | `76` | `P2_campaign_record` data/rfc046/ACTIVATION.json | — |
| CANDIDATES_REJECTED | `{"CAND-046-001": "CANDIDATE_REJECTED", "CAND-046-002": "CANDIDATE_REJECTED", "CAND-046-003": "CANDIDATE_REJECTED"}` | `P2_campaign_record` data/rfc046/ACTIVATION.json | — |
| STANDING_STATE | `{"G_BUSINESS_REENTRY": "NOT_PASS", "campaign_status": "DISCOVERY_CAMPAIGN_FAILED", "discovery_campaign_failed": "DISCOVERY_CAMPAIGN_FAILED", "discovery_offline_authorized": true, "false_success": 0, "live_trading": false, "next_campaign": "NOT_AUTHORIZED", "profitability_verified": false, "risk_engine": "DETERMINISTIC", "trades_authorized": 0}` | `P4_frozen_declaration` data/rfc046/ECONOMIC_FEASIBILITY.json | — |
| DECISION | `{"edge_status": "NOT_DEMONSTRATED", "families_at_the_boundary": ["intraday"], "families_cost_compatible": ["mean_reversion", "momentum", "swing_trading", "trend_following"], "families_not_cost_compatible": ["scalping"], "meaning": "a cost profile exists under which the toll is small relative to the typical move available at the strategy's own horizon; it is a *cost* finding and says nothing about whether any edge exists", "next_campaign": "NOT_AUTHORIZED", "not_an_edge_claim": true, "note": "no strategy is proposed, no hypothesis is created and no gate is reopened by this recommendation; the owner must authorize any next step", "profile": {"execution": "market/taker on both legs (the cheapest permitted posture at VIP0)", "horizon_region": "holding periods from about one day upwards, where the measured median move is at least seven times the toll", "minimum_gross_edge_bps": 23.353553391, "product": "Binance Spot, long/cash only", "required_gross_edge_bps_at_1p5x": 35.030330086, "round_trip_bps_at_200_usdt": 23.353553391, "turnover_region": "low: each round trip costs 0.467071068 USDT at full deployment, so the annual toll is roughly 0.852 x capital per round trip per day", "venue": "BINANCE_SPOT_STANDARD_TAKER"}, "scope_recommendation": "VIABLE_COST_PROFILE_IDENTIFIED", "violated_if": ["realised round-trip cost exceeds the modelled toll: every extra bps of realised cost is an extra bps of required gross edge, and ST-6 halts the campaign on exactly that", "the forward spread measurement contradicts the modelled 1.0 bps (SRC-07 has no historical endpoint, so the estimate is unverified until then)", "a candidate's holding horizon is shorter than its own measured cost-compatible region"]}` | `P2_campaign_record` data/rfc046/ECONOMIC_FEASIBILITY.json | — |
| FALSE_SUCCESS | `"0"` | `P1_governance_decision` tasks/decisions.md#ADR-0024 | P2_campaign_record `data/rfc046/ECONOMIC_FEASIBILITY.json` = 0 |

### RFC-048V — RFC-048V futures risk plane (falsified and recertified)

- governing decision: none (no ADR names this campaign)

| field | effective value | decided by | superseded |
| --- | --- | --- | --- |
| TERMINAL_STATE | `"RFC048_OFFLINE_CERTIFIED"` | `P2_campaign_record` data/rfc048/FINAL_CERTIFICATION_REPORT.json | — |
| STATE_CHANGE | `{"regenerated": ["data/rfc048/INDEPENDENT_VERIFICATION.json", "data/rfc048/RUNTIME_EXECUTION_REPORT.json"], "verifier_decision_level_unchanged": true}` | `P2_campaign_record` data/rfc048/FINAL_CERTIFICATION_REPORT.json | — |
| ECONOMIC_CHECKS | `41` | `P2_campaign_record` data/rfc048/FINAL_CERTIFICATION_REPORT.json | — |
| ECONOMIC_CHECKS_FAILED | `[]` | `P2_campaign_record` data/rfc048/FINAL_CERTIFICATION_REPORT.json | — |
| FALSE_APPROVALS | `0` | `P2_campaign_record` data/rfc048/FINAL_CERTIFICATION_REPORT.json | — |

### RFC-049 — RFC-049 profitability discovery — Phase A / admission

- governing decision: `ADR-0026` RFC-049 Discovery 2: cierre de campana (DISCOVERY_CAMPAIGN_FAILED) y retirada de la apertura unica del OOS sellado
- decision history: `ADR-0025`(LIVE_TRADING=DISABLED, NEXT_CAMPAIGN=AUTHORIZED, PAPER_PROMOTION=NOT_AUTHORIZED, PROFITABILITY_VERIFIED=FALSE, SEALED_OOS=CLOSED, TRADES_AUTHORIZED=0) → `ADR-0026`(FALSE_SUCCESS=0, HYPOTHESIS_001=CLOSED_REJECTED_DEV_VAL, HYPOTHESIS_BUDGET=EXHAUSTED_NO_REFILL, LIVE_TRADING=DISABLED, NEXT_CAMPAIGN=NOT_AUTHORIZED, PAPER_PROMOTION=NOT_AUTHORIZED, PROFITABILITY_VERIFIED=FALSE, RFC_049_DISCOVERY2=CLOSED, RISK_ENGINE=DETERMINISTIC, SEALED_OOS=CANCELLED_NOT_OPENED, TRADES_AUTHORIZED=0)

| field | effective value | decided by | superseded |
| --- | --- | --- | --- |
| AUTHORIZED | `false` | `P4_frozen_declaration` data/rfc049/PREREGISTRATION_MANIFEST.json | — |
| GATE_REASON | `"NEXT_CAMPAIGN = NOT_AUTHORIZED; WP-049-06..10 remain blocked"` | `P4_frozen_declaration` data/rfc049/PREREGISTRATION_MANIFEST.json | — |
| PHASE_A_STATE | `"DISCOVERY2_NOT_AUTHORIZED"` | `P4_frozen_declaration` data/rfc049/ECONOMIC_RESULTS.json | — |
| SEALED_OOS_POLICY | `"forward observations strictly after freeze_timestamp_utc; opened once, after 20 closed round trips or 24 months, whichever comes first; fewer than 20 trips at 24 months => INSUFFICIENT_OOS_SAMPLE"` | `P4_frozen_declaration` data/rfc049/PREREGISTRATION_MANIFEST.json | — |
| ADMISSION_STATE | `{"next_campaign": "NOT_AUTHORIZED", "campaign_authorized": false, "experiments_executed": 0, "oos_opened": false, "trades_authorized": 0, "live_trading": "DISABLED", "profitability_verified": false}` | `P2_campaign_record` data/rfc049/admission/FINAL_ADMISSION_REPORT.json | — |
| NEXT_GATE | `"operator decision: authorize Discovery 2 for the candidates listed READY_FOR_AUTHORIZED_TEST"` | `P2_campaign_record` data/rfc049/admission/FINAL_ADMISSION_REPORT.json | — |
| ADMISSION_CHECKS_FAILED | `0` | `P2_campaign_record` data/rfc049/admission/FINAL_ADMISSION_REPORT.json | — |

### RFC-049-DISCOVERY-2 — RFC-049 Discovery 2 (Phase B, DEV/VAL, closed)

- governing decision: `ADR-0026` RFC-049 Discovery 2: cierre de campana (DISCOVERY_CAMPAIGN_FAILED) y retirada de la apertura unica del OOS sellado
- decision history: `ADR-0025`(LIVE_TRADING=DISABLED, NEXT_CAMPAIGN=AUTHORIZED, PAPER_PROMOTION=NOT_AUTHORIZED, PROFITABILITY_VERIFIED=FALSE, SEALED_OOS=CLOSED, TRADES_AUTHORIZED=0) → `ADR-0026`(FALSE_SUCCESS=0, HYPOTHESIS_001=CLOSED_REJECTED_DEV_VAL, HYPOTHESIS_BUDGET=EXHAUSTED_NO_REFILL, LIVE_TRADING=DISABLED, NEXT_CAMPAIGN=NOT_AUTHORIZED, PAPER_PROMOTION=NOT_AUTHORIZED, PROFITABILITY_VERIFIED=FALSE, RFC_049_DISCOVERY2=CLOSED, RISK_ENGINE=DETERMINISTIC, SEALED_OOS=CANCELLED_NOT_OPENED, TRADES_AUTHORIZED=0)

| field | effective value | decided by | superseded |
| --- | --- | --- | --- |
| TERMINAL_STATE | `"DISCOVERY_CAMPAIGN_FAILED"` | `P1_governance_decision` tasks/decisions.md#ADR-0026 | — |
| SEALED_OOS | `"CANCELLED_NOT_OPENED"` | `P1_governance_decision` tasks/decisions.md#ADR-0026 | P1_governance_decision `tasks/decisions.md#ADR-0025` = "CLOSED" |
| NEXT_CAMPAIGN | `"NOT_AUTHORIZED"` | `P1_governance_decision` tasks/decisions.md#ADR-0026 | P1_governance_decision `tasks/decisions.md#ADR-0025` = "AUTHORIZED" |
| PAPER_PROMOTION | `"NOT_AUTHORIZED"` | `P1_governance_decision` tasks/decisions.md#ADR-0026 | — |
| AUTHORIZED | `false` | `P4_frozen_declaration` data/rfc049/PREREGISTRATION_MANIFEST.json | — |

### ACTIVE-PAPER — ACTIVE strategy pipeline and the paper lane

- governing decision: none (no ADR names this campaign)

| field | effective value | decided by | superseded |
| --- | --- | --- | --- |
| STRATEGIES_REGISTERED | `24` | `P3_runtime_ledger` config/strategy_admission.json | — |
| ADMITTED_FOR_PAPER | `0` | `P3_runtime_ledger` config/strategy_admission.json | — |
| PAPER_RUN_STATE | `"PAPER_24H_DATA_FAILED"` | `P2_campaign_record` PAPER_DATA_24H_REPORT.json | — |
| PAPER_PROMOTION | `"NOT_AUTHORIZED"` | `P2_campaign_record` data/rfc049/discovery2/CAMPAIGN_CLOSURE.json | — |

### ST6-FORWARD-REGIME — ST-6 forward regime collection lane (external lane, hashed read-only)

- governing decision: none (no ADR names this campaign)

| field | effective value | decided by | superseded |
| --- | --- | --- | --- |
| LANE_STATE | `"HEALTHY"` | `P2_campaign_record` data/st6/ST6_HEALTH_STATUS.json | — |
| NEXT_CAMPAIGN | `"NOT_AUTHORIZED"` | `P2_campaign_record` data/st6/ST6_HEALTH_STATUS.json | — |
| LIVE_TRADING | `"DISABLED"` | `P2_campaign_record` data/st6/ST6_HEALTH_STATUS.json | — |

## Integrity

| pin | kind | recorded | actual (LF content digest) | eol | result |
| --- | --- | --- | --- | --- | --- |
| `spec:H-049-001` | STRICT | `fd5cd2991466e243` | `fd5cd2991466e243` | LF | **VERIFIED** |
| `spec:H-049-002` | STRICT | `cdafdc151e2514f9` | `cdafdc151e2514f9` | LF | **VERIFIED** |
| `spec:H-049-003` | STRICT | `c77aa9a8c7aa897c` | `c77aa9a8c7aa897c` | LF | **VERIFIED** |
| `dataset:signal_series:defillama_stablecoin_supply_all.json` | UNRESOLVED | `b8250250e0cabc5d` | `None` | — | **UNRESOLVED** |
| `dataset:signal_series:blockchain_info_hashrate_8y.json` | UNRESOLVED | `ede914a9089311a2` | `None` | — | **UNRESOLVED** |
| `dataset:signal_series:blockchain_info_miners_revenue_all.json` | UNRESOLVED | `c62f0a94a622dd35` | `None` | — | **UNRESOLVED** |
| `dataset:signal_series:fred_WALCL.csv` | UNRESOLVED | `c6519d91e9d8546c` | `None` | — | **UNRESOLVED** |
| `dataset:signal_series:fred_RRPONTSYD.csv` | UNRESOLVED | `1bea66a24c8bae36` | `None` | — | **UNRESOLVED** |
| `dataset:signal_series:fred_WTREGEN.csv` | UNRESOLVED | `1efab94a7a507516` | `None` | — | **UNRESOLVED** |
| `dataset:signal_series:fred_DFII10.csv` | UNRESOLVED | `0277781c1336527c` | `None` | — | **UNRESOLVED** |
| `dataset:signal_series:fred_DTWEXBGS.csv` | UNRESOLVED | `75edd28ba1eceade` | `None` | — | **UNRESOLVED** |
| `dataset:signal_series:fred_DFF.csv` | UNRESOLVED | `a93504210b53532f` | `None` | — | **UNRESOLVED** |
| `rfc046-spec:HYP-001` | UNRESOLVED | `e5e58176e4c8fb01` | `None` | — | **UNRESOLVED** |
| `rfc046-spec:HYP-002` | UNRESOLVED | `3336b8f343d899af` | `None` | — | **UNRESOLVED** |
| `rfc046-spec:HYP-003` | UNRESOLVED | `8f99b0366301a304` | `None` | — | **UNRESOLVED** |
| `document_hashes:tasks/decisions.md` | APPEND_ONLY | `38622df9a5ad74db` | `dbf540c11dced96b` | LF | **DRIFTED** |
| `document_hashes:tasks/roadmap.md` | APPEND_ONLY | `5310f6a423318cdb` | `5310f6a423318cdb` | LF | **VERIFIED** |
| `document_hashes:docs/rfc/RFC-046_CONTROLLED_DISCOVERY.md` | APPEND_ONLY | `a14753f5ec62446e` | `a14753f5ec62446e` | LF | **VERIFIED** |
| `document_hashes:docs/rfc/RFC-046_CONTROLLED_DISCOVERY.json` | APPEND_ONLY | `5b7275c366ff1ac3` | `5b7275c366ff1ac3` | LF | **VERIFIED** |
| `document_hashes:docs/research/BUSINESS_REENTRY_POLICY.md` | APPEND_ONLY | `efb3e3e112378281` | `efb3e3e112378281` | LF | **VERIFIED** |
| `document_hashes:docs/research/BUSINESS_REENTRY_POLICY.json` | APPEND_ONLY | `961e92c0cd1f02ac` | `961e92c0cd1f02ac` | LF | **VERIFIED** |
| `document_hashes:docs/research/PROFITABILITY_OPERATING_MODEL.json` | APPEND_ONLY | `39c97e02716f9cee` | `39c97e02716f9cee` | LF | **VERIFIED** |
| `document_hashes:docs/research/PROFITABILITY_OPERATING_MODEL.md` | APPEND_ONLY | `cfd503b2a5e4dc62` | `cfd503b2a5e4dc62` | LF | **VERIFIED** |
| `document_hashes:docs/governance/PROFITABILITY_FIRST_FREEZE.md` | APPEND_ONLY | `4eb331f58f669f6b` | `4eb331f58f669f6b` | LF | **VERIFIED** |
| `document_hashes:docs/roadmap/RFC_REGISTRY.json` | APPEND_ONLY | `04aab57d2e3e4cfe` | `04aab57d2e3e4cfe` | LF | **VERIFIED** |
| `document_hashes:docs/roadmap/PROFITABILITY_ROADMAP_AMENDMENT.md` | APPEND_ONLY | `c25e1794376781cb` | `c25e1794376781cb` | LF | **VERIFIED** |
| `document_hashes:docs/governance/DISCOVERY_ADMISSION_POLICY.md` | APPEND_ONLY | `209f8f47ffc509ef` | `209f8f47ffc509ef` | LF | **VERIFIED** |
| `document_hashes:docs/governance/DISCOVERY_STOP_RULES.md` | APPEND_ONLY | `3c5bfd2cf00f73ab` | `3c5bfd2cf00f73ab` | LF | **VERIFIED** |
| `document_hashes:docs/architecture/DISCOVERY_EXECUTION_FLOW.md` | APPEND_ONLY | `95ece8b5fa493605` | `95ece8b5fa493605` | LF | **VERIFIED** |

- governance scan over 10 artefacts: 0 profitability claims, 0 sealed-OOS openings.

## Inputs and their authority

What each input is, and what it answers to. A committed input is read from the commit; an external one from the evidence copy the repository carries. The declaration is part of the view's identity; whether this machine happens to hold the original is not.

| input | class | required | authority | evidence copy |
| --- | --- | --- | --- | --- |
| `PAPER_DATA_24H_REPORT.json` | COMMITTED | yes | `committed` | — |
| `data/raw/alpha001/BTC-USDT_1d.json` | EXTERNAL_DATASET | no | `preregistration_manifest` | — |
| `data/raw/alpha001/ETH-USDT_1d.json` | EXTERNAL_DATASET | no | `preregistration_manifest` | — |
| `data/st6/ST6_HEALTH_STATUS.json` | EXTERNAL_LIVE | yes | `dated_snapshot` | `data/recovery/wp8/evidence/inputs/ST6_HEALTH_STATUS.json` (`945f94e0757f`) |
| `reports/alpha-recovery-v1/STRATEGY_FAILURE_MATRIX.md` | EXTERNAL_GENERATED | yes | `published_sources` | `data/recovery/wp8/evidence/inputs/STRATEGY_FAILURE_MATRIX.md` (`b248c3687fbd`) |
| `reports/strategy-baseline/COST_BARRIER.json` | EXTERNAL_GENERATED | yes | `published_sources` | `data/recovery/wp8/evidence/inputs/COST_BARRIER.json` (`1547cea438d2`) |
| `reports/strategy-baseline/REGIME_ANALYSIS.json` | EXTERNAL_GENERATED | yes | `published_sources` | `data/recovery/wp8/evidence/inputs/REGIME_ANALYSIS.json` (`fca537b09a71`) |
| `reports/strategy-baseline/TIMEFRAME_AUDIT.json` | EXTERNAL_GENERATED | yes | `published_sources` | `data/recovery/wp8/evidence/inputs/TIMEFRAME_AUDIT.json` (`82df1ba81b18`) |

## Local observations (volatile — not part of the identity)

- `PAPER_DATA_24H_REPORT.json` (COMMITTED): resolved from `HEAD`; local file present: True; reproduces its authority: True
- `data/raw/alpha001/BTC-USDT_1d.json` (EXTERNAL_DATASET): resolved from `LOCAL_MATERIALIZATION`; local file present: True; reproduces its authority: True
- `data/raw/alpha001/ETH-USDT_1d.json` (EXTERNAL_DATASET): resolved from `LOCAL_MATERIALIZATION`; local file present: True; reproduces its authority: True
- `data/st6/ST6_HEALTH_STATUS.json` (EXTERNAL_LIVE): resolved from `EVIDENCE_COPY`; local file present: True; reproduces its authority: False; attested fields match the snapshot: True
- `reports/alpha-recovery-v1/STRATEGY_FAILURE_MATRIX.md` (EXTERNAL_GENERATED): resolved from `EVIDENCE_COPY`; local file present: True; reproduces its authority: True
- `reports/strategy-baseline/COST_BARRIER.json` (EXTERNAL_GENERATED): resolved from `EVIDENCE_COPY`; local file present: True; reproduces its authority: True
- `reports/strategy-baseline/REGIME_ANALYSIS.json` (EXTERNAL_GENERATED): resolved from `EVIDENCE_COPY`; local file present: True; reproduces its authority: True
- `reports/strategy-baseline/TIMEFRAME_AUDIT.json` (EXTERNAL_GENERATED): resolved from `EVIDENCE_COPY`; local file present: True; reproduces its authority: True

## Invariants

| id | result | statement | detail |
| --- | --- | --- | --- |
| `I1_frozen_pins_verify` | PASS | every hash-pinned frozen artefact matches its recorded digest | 16 verified, 0 failed, 0 missing |
| `I2_builder_is_not_verifier` | PASS | no verification record is signed by the code that produced the measurement | [{"source": "data/rfc049/admission/INDEPENDENT_VERIFICATION.json", "builder": "scripts/rfc049b_admission.py", "verifier": "scripts/rfc049b_verify.py", "builder_imported": false}, {"source": "data/rfc049/discovery2/INDEPENDENT_VERIFICATION.json", "builder": "scripts/rfc049c_engine.py", "verifier": "scripts/rfc049c_verify.py", "builder_imported": false}] |
| `I3_no_profitability_claim` | PASS | no scanned artefact asserts profitability | [] |
| `I4_sealed_window_never_read` | PASS | the sealed OOS window is not read and the single licensed inspection is not spent | [] |
| `I5_governance_mirrors_agree` | PASS | the closure record and the forward-regime lane state the same governance flags | 4 shared flags agree (LIVE_TRADING, NEXT_CAMPAIGN, PROFITABILITY_VERIFIED, TRADES_AUTHORIZED) |
| `I6_campaign_numbers_are_consistent` | PASS | an RFC number is claimed by exactly one RFC: campaigns that share a number are phases of it | declared [46, 48, 49] |
| `I7_inputs_are_reproducible` | PASS | every input a finding rests on resolves from the commit - HEAD content or a committed, digest-verified evidence copy - and never from an uncommitted file | 8 declared inputs resolve from the repository |

## Advisories (recorded, not contradictions)

- **A1_registry_is_stale** — the RFC identifier registry does not list every number the tree already occupies. tree occupies [35, 46, 48, 49]; registry lists [0, 10, 20, 21, 23, 24, 25, 26, 27, 28, 29, 30, 31, 32, 33, 34, 35, 36, 37, 38, 39, 40, 41, 42, 43, 44, 46, 47]; missing [48, 49] (the registry's declared next free number cannot be trusted; the view derives it from the tree instead)
- **A2_next_free_rfc_derived** — next free RFC number above 046 is 050, derived from tree occupancy + registry. occupied in tree [35, 46, 48, 49]; registry [0, 10, 20, 21, 23, 24, 25, 26, 27, 28, 29, 30, 31, 32, 33, 34, 35, 36, 37, 38, 39, 40, 41, 42, 43, 44, 46, 47]; 045 stays vacant by control (informational: any new campaign must first reconcile the registry with the tree)
- **A3_unresolved_pins** — some recorded digests cannot be checked because the pinned artefact is not in the tree. 12 pins: ['dataset:signal_series:defillama_stablecoin_supply_all.json', 'dataset:signal_series:blockchain_info_hashrate_8y.json', 'dataset:signal_series:blockchain_info_miners_revenue_all.json', 'dataset:signal_series:fred_WALCL.csv', 'dataset:signal_series:fred_RRPONTSYD.csv', 'dataset:signal_series:fred_WTREGEN.csv'] (not a contradiction (nothing is contradicted), but those pins prove nothing today)
- **A4_append_only_drift** — an append-only document attestation no longer matches the document it attests. 1 attestations: ['tasks/decisions.md'] (expected: these documents are designed to grow by appending; the attestation is a snapshot, not a pin)

RFC numbering: tree occupies [35, 46, 48, 49]; registry lists [0, 10, 20, 21, 23, 24, 25, 26, 27, 28, 29, 30, 31, 32, 33, 34, 35, 36, 37, 38, 39, 40, 41, 42, 43, 44, 46, 47] and declares next free 048; the view derives next free **050**.

## ADR index (facts extracted from inline `KEY = VALUE`)

| adr | title | facts |
| --- | --- | --- |
| ADR-0001 | Licencia del proyecto | — |
| ADR-0002 | Gestor de dependencias | — |
| ADR-0003 | Dashboard | — |
| ADR-0004 | Telemetria | — |
| ADR-0005 | Persistencia (DAL/ORM) | — |
| ADR-0006 | Exchange y modo iniciales | — |
| ADR-0007 | Politica de no overfitting | — |
| ADR-0009 | Hosting y repositorio remoto | — |
| ADR-0010 | Alias de variables planas -> rutas anidadas en Settings | — |
| ADR-0011 | Cierre de sprint-001 con excepcion y apertura de sprint-002 | — |
| ADR-0012 | Recover de quality gates post-TSK-102 (numpy stub, coverage app.py, pip-audit nltk) | — |
| ADR-0013 | Reconciliacion de scope TSK-103: TSK-102 absorbe persistencia OHLCV, TSK-103 aisla dominio scanner | — |
| ADR-0016 | Baseline Health Remediation (mypy + pytest pre-existentes en main) | — |
| ADR-0014 | F5 closure (TSK-103.5 merge review) | — |
| ADR-0015 | Cierre de sprint-002 + Apertura de sprint-003 (firmada 2026-07-05) | — |
| ADR-0017 | — Branch Protection `gh api` Apply Auth-Gated (TSK-008/009 follow-up) | — |
| ADR-0018 | Cierre de Fase 2 Indicators (TSK-200..204) y formalización del F3 mirror contract para property tests | — |
| ADR-0020 | pwsh-only workflow scripts (`.ps1` a `pwsh` 7+, drop Windows PowerShell 5.1 compat) | — |
| ADR-0021 | — Credentials rotation policy for `PR_PIPELINE_SMOKE_PAT` | — |
| ADR-0022 | — Triage bundle for the 5 quality workstreams landed between `b98c8f8` and `b4b543d` | — |
| ADR-0023 | — Pin the ID-collision + numbering-note pattern (auto-reset behavior rule) | — |
| ADR-0024 | RFC-046: excepcion limitada y fechada de RFC-041 para Controlled Discovery (offline) | `DISCOVERY_OFFLINE=AUTHORIZED`, `FALSE_SUCCESS=0`, `LIVE_TRADING=DISABLED`, `REPLICATE_P0=NONE`, `RISK_ENGINE=DETERMINISTIC`, `TRADES_AUTHORIZED=0` |
| ADR-0025 | RFC-049 Discovery 2: autorizacion de campana offline (DEV/VAL) por el operador | `LIVE_TRADING=DISABLED`, `NEXT_CAMPAIGN=AUTHORIZED`, `PAPER_PROMOTION=NOT_AUTHORIZED`, `PROFITABILITY_VERIFIED=FALSE`, `SEALED_OOS=CLOSED`, `TRADES_AUTHORIZED=0` |
| ADR-0026 | RFC-049 Discovery 2: cierre de campana (DISCOVERY_CAMPAIGN_FAILED) y retirada de la apertura unica del OOS sellado | `FALSE_SUCCESS=0`, `HYPOTHESIS_001=CLOSED_REJECTED_DEV_VAL`, `HYPOTHESIS_BUDGET=EXHAUSTED_NO_REFILL`, `LIVE_TRADING=DISABLED`, `NEXT_CAMPAIGN=NOT_AUTHORIZED`, `PAPER_PROMOTION=NOT_AUTHORIZED`, `PROFITABILITY_VERIFIED=FALSE`, `RFC_049_DISCOVERY2=CLOSED`, `RISK_ENGINE=DETERMINISTIC`, `SEALED_OOS=CANCELLED_NOT_OPENED`, `TRADES_AUTHORIZED=0` |
| ADR-0027 | WP-EDGE-01: lane de investigacion edge01 congelado, verificacion por artefactos y runtime PAPER intacto | `LIVE_TRADING=DISABLED`, `PAPER_PROMOTION=NOT_AUTHORIZED`, `PROFITABILITY_VERIFIED=FALSE`, `TRADES_AUTHORIZED=0` |

