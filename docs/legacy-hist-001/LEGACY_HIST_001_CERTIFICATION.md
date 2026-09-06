# LEGACY-HIST-001 — Historical Evidence Layer Certification (read-only / shadow)

```text
CHECKPOINT_ID: LEGACY-HIST-001
BASE_COMMIT: a282fcc4 (branch feat/ma-2-specialist-opportunity-swarm, CERT-DEMO-PAPER-01 round-2 record)
IMPLEMENTATION_COMMIT: aa065cf4047031e402c9f6f9d469f19414429d78 (branch feat/legacy-hist-001)
SOURCE_PATH: C:\Users\GVLLFR0035\Downloads\bot freebuff\his.zip
SOURCE_ZIP_SHA256: 1390a125fad267028ebbf0e47e1c0618e9b5252f43a99c2218c31acdbd326e1f
ORIGINAL_ZIP_UNTOUCHED: true (read-only access; hash verified before and after ingest)
STATUS: LEGACY_HIST_001_CERTIFIED
NEXT_AUTHORIZED_ACTION: fresh-data discovery (new checkpoint, outside CONSUMED_DEVELOPMENT window)
```

## ARCHITECTURE_MAPPING

| Legacy concept | Current-system integration | Impact on decisions/execution |
| --- | --- | --- |
| `RESULTADOS_V57_R26_B.json` portfolio/period | `legacy:r26:portfolio` record (`kind=portfolio`) | none — context only |
| `TRADES_V57_R26_B.csv` (2217 trades) | `legacy:r26:trades` record + recomputed economics (`kind=trade_aggregate`) | none |
| `OPPORTUNITIES_V57_R26_B.csv` (24379) | `legacy:r26:opportunities` record | none |
| `BLOCKED_V57_R26_B.csv` | `legacy:r26:blocked` record with reason taxonomy | none |
| `BY_ASSET_V57_R26_B.csv` (30 assets) | 30 `asset_aggregate` records; BTC/ETH/SOL queryable by Asset Experts; other 27 catalogued (NO new agents) | none |
| `BY_FAMILY_V57_R26_B.csv` (FBS/TP/BR/LSR) | `family_aggregate` records with `canonical_strategy_hint` (FBS→MeanReversion, TP→Trend, BR→Breakout, LSR→Volatility — informational only) | none |
| `DAILY_COVERAGE_V57_R26_B.csv` | `daily_coverage` record (R26 frequency PASS 108/108, economics FAIL_NET_NEGATIVE) | none |
| `FBS_BY_EXIT_REASON_V57_R26_B.csv` | 4 `exit_reason_aggregate` records (cost-problem evidence) | none |
| `RESULTADOS_V57_R31_9_DIAGNOSTIC.json` | `diagnostic` record, verdict **FAIL_NOT_PROMOTED** (VOL_GE_1) | none |
| `TP_VOLUME_REGIME_CLASSIFICATION_V57_R31_9.csv` | `classification_aggregate` record | none |
| `CAMPAIGN_FINAL_BCD.json` | `campaign` record: **CAMPAIGN_STOP_NO_EDGE**, 0/16 individual passers, 0/4 portfolio passers | none |
| `research_registry.json` | `registry` record (R26 RETAINED_DEVELOPMENT_BASELINE; R32 campaigns REJECTED / STOP) | none |
| Manifests E/F/G | 3 `manifest_metadata` records (metadata only, never code) | none |
| Legacy freeze/hash/disjoint-window *pattern* | re-implemented via current contracts (deterministic SHA-256 provenance, CONSUMED_DEVELOPMENT period ledger semantics, fail-closed flags) — **no legacy runtime copied** | none |

Existing contracts reused, no domain duplication: `AgentEvidence` hash/provenance
conventions (64-hex SHA-256, frozen metadata) mirrored in
`LegacyEvidenceRecord`; `ExperimentRegistry` consumed-period semantics
honored via `CONSUMED_DEVELOPMENT_PERIOD`; debate provenance conventions
(`CritiqueRecord`-style hints) exposed through `LegacyHypothesisIndex`.

## FILES_CHANGED (implementation commit aa065cf)

```text
src/trading_bot/legacy_evidence/__init__.py     (new — public API)
src/trading_bot/legacy_evidence/ingest.py       (new — allowlist ZIP ingest, SHA-256 provenance)
src/trading_bot/legacy_evidence/store.py        (new — immutable records, fail-closed flags/guards)
src/trading_bot/legacy_evidence/builder.py      (new — deterministic record construction + sanity)
src/trading_bot/legacy_evidence/critique.py     (new — LegacyHypothesisIndex / critique hints)
src/trading_bot/legacy_evidence/shadow.py       (new — ShadowEvidenceLinker, side-effect-free)
src/trading_bot/demo/paper_multi_agent.py       (modified — shadow-only legacy summary in reports)
scripts/validate_legacy_hist_001.py             (new — independent validator, 18 checks)
tests/unit/legacy_evidence/*                    (new — 36 tests)
docs/legacy-hist-001/evidence/*                 (evidence commit)
```

## LEGACY_RECORD_COUNTS

```text
total records: 50
  portfolio: 1          trades aggregate: 1      opportunities aggregate: 1
  blocked aggregate: 1  daily coverage: 1        registry: 1              campaign (BCD): 1
  diagnostic (R31.9): 1 classification: 1        manifests (E/F/G): 3
  asset aggregates: 30  family aggregates: 4     FBS exit-reason aggregates: 4
catalogued symbols: 30 (BTC, ETH, SOL core-queryable; 27 catalogued only, no new agents)
```

## SOURCE_HASHES (deterministic; full detail in docs/legacy-hist-001/evidence/PROVENANCE.json)

```text
his.zip: 1390a125fad267028ebbf0e47e1c0618e9b5252f43a99c2218c31acdbd326e1f
RESULTADOS_V57_R26_B.json:                    0160e64ad07e0f66…
TRADES_V57_R26_B.csv:                         a1a95014fcda4af2…
OPPORTUNITIES_V57_R26_B.csv:                  3af02d9a1f8fa38f…
BLOCKED_V57_R26_B.csv:                        b0e67795f494a7f8…
BY_ASSET_V57_R26_B.csv:                       80a3735bcaf1d3c5…
BY_FAMILY_V57_R26_B.csv:                      fb9ee7190f6344f7…
DAILY_COVERAGE_V57_R26_B.csv:                 74a95ed95c846880…
FBS_BY_EXIT_REASON_V57_R26_B.csv:             8354d3a10b4b62dc…
RESULTADOS_V57_R31_9_DIAGNOSTIC.json:         6b5937105cf6d80b…
TP_VOLUME_REGIME_CLASSIFICATION_V57_R31_9.csv 6a2f69785a4923e5…
CAMPAIGN_FINAL_BCD.json:                      5c9d1a2c8adcbc75…
research_registry.json:                       d38ee3b56a35b7db…
E/F/G manifests: hashed in PROVENANCE.json (metadata only)
```

## SANITY_CHECKS (all PASS — reconstructed from ingested legacy files)

```text
opportunities = 24379  PASS
trades        = 2217   PASS
complete days = 108    PASS
gross PnL     = +1923.3045   PASS (1923.3044633308157)
fees          = 5805.7575    PASS (5805.7574709909595)
net PnL       = -3882.4530   PASS (-3882.453007660144)
PF            = 0.809422     PASS (0.8094220176749788)
expectancy    = -0.086659R   PASS (-0.08665853223975328)
trade-level recomputation cross-check: gross/fees/net match portfolio JSON
R31.9 VOL_GE_1 = FAIL (net_exp_r -0.05895, PF 0.85585, matched test NOT justified) — never promoted
BCD = 0/16 individual passers, 0/4 portfolio passers, CAMPAIGN_STOP_NO_EDGE — preserved
R26 ledger status = RETAINED_DEVELOPMENT_BASELINE, economics FAIL_NET_NEGATIVE — preserved
```

## GATES: 18/18 PASS

```text
G1  source_intact                  PASS (exact path, ZIP untouched, sha256 stable)
G2  allowlist_strict               PASS (15/15 members, unique, no dupes)
G3  secrets_never_ingested         PASS (read=15, never_read=3551; no secret values in any record)
G4  provenance_deterministic       PASS (recomputed SHA-256 matches; repeat ingest identical)
G5  consumed_period                PASS (2026-05-01..2026-08-18 CONSUMED_DEVELOPMENT on all 50 records)
G6  fail_closed_flags              PASS (training/promotion/confirmation/execution hard-wired False)
G7  metaranker_invariance          PASS (identical scores/components layer ON vs OFF; no legacy
                                    input surface in MetaRanker/OpportunityBoard/RankedOpportunity)
G8  expert_queries                 PASS (BTC/ETH/SOL per-asset; TP/FBS per-family; 30 catalogued)
G9  critics_detect_legacy          PASS (tested hypotheses, rejected campaigns, cost problems,
                                    post-hoc R31.9 detection)
G10 paper_execution_invariance     PASS (identical broker order counts ON vs OFF; legacy summary
                                    attached after the trading loop)
G11 pit_no_lookahead               PASS (period_end <= 2026-08-18 < now; no execution capability)
G12 vet_wif_promotion_rejected     PASS (LegacyPromotionError on every attempt)
G13 r319_rule_conversion_rejected  PASS (VOL_GE_1 FAIL can never become a rule)
G14 import_idempotent              PASS (reload-safe, no cross-module leaks)
G15 same_input_same_records        PASS (identical IDs/sanity across rebuilds)
G16 full_regression                PASS (802 passed, 0 failed — see below)
+   legacy_verdicts_preserved      PASS
+   no_legacy_code_ported          PASS (AST audit: no fran_*/research_daemon/scheduler imports)
```

## FULL_REGRESSION

```text
802 passed, 0 failed (tests/, host EXCHANGE_ID=bybit override neutralized — pre-existing
classified env baseline from CERT-DEMO-PAPER-01 round 2; 766 baseline + 36 new legacy tests)
Ruff (scoped legacy_evidence + validator + tests): 0 findings
Mypy (legacy_evidence): 0 errors
DEMO-PAPER-01 fixture E2E: DEMO_FUNCTIONAL_PASS, realized 242.82705154 (byte-identical certified value)
```

```text
METARANKER_IMPACT = 0
PAPER_EXECUTION_IMPACT = 0
LIVE_EXECUTION = 0 (LIVE=0; PaperBroker invariants intact; can_affect_execution=False everywhere)
```

## Exclusions honored

`freebuff2api/**` (never read), `.env` (never read), `.git`, `.venv`,
`__pycache__`, BAT/PS1 (1229 such members never touched), tokens/credentials,
legacy daemon executable and scheduler: all excluded by the strict allowlist +
forbidden-basename guard. No V5.7 strategy code, no `research_daemon.py`, no
installer scripts, no E/F/G campaign code was ported — only their JSON
manifests as historical metadata records.
