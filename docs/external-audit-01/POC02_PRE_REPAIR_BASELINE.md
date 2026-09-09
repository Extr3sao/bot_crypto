# POC02 PRE-REPAIR BASELINE (FROZEN)

Checkpoint: **MA-DIRECTION-ARBITRATION-AND-POC02-REPAIR-01**
Frozen: 2026-09-09 (UTC) · Authoritative base: `53c5910` + POC02 observation lineage
Campaign: `POC-02-paper-clean-01` (window 2026-09-09T13:38:55Z → 2026-09-30, PAPER, binanceusdm public, PaperBroker, Shadow V2 enabled, coverage ≥ 0.80)

**This baseline is immutable.** Frozen copies of all campaign artifacts live in
`docs/external-audit-01/poc02-pre-repair/`; original campaign artifacts under
`reports/poc02-paper-clean-01/` are untouched (0 modifications).

## 1. Frozen runtime state (at capture time)

| Metric | Value |
| --- | --- |
| Cycles observed | 11 |
| Market scans | 11 |
| Strategy evaluations | 11 |
| Attributed candidates (Decision stage) | 18 (momentum; 9 LONG / 9 SHORT) |
| Debates | 11 |
| Critic outcomes | `critic-counter-signal` CHALLENGE 18/18 (material_dissent=true); `critic-evidence` SUPPORT; `critic-regime` SUPPORT |
| Selected | 0 |
| Verified | 0 |
| Risk calls | 0 |
| Paper trades | 0 (0 opens, 0 closes) |
| Shadow captures / resolved | 0 / 0 |
| Net PnL | 0.0 |
| LIVE / REAL_BROKER / PRIVATE / SHADOW_PAPERBROKER calls | 0 / 0 / 0 / 0 |

## 2. Observation windows (BottleneckState)

33/33 windows → `AGENT_FILTER`; AGENT_FILTER_RATE = 1.0; typed reason
`UNRESOLVED_CONFLICT` raised by `critic-counter-signal`. No Risk, Verifier,
Execution or NO_SIGNAL windows exist in the sample.

## 3. Observed pattern (candidate-level, from POC02_ATTRIBUTION.jsonl)

Every POC02 cycle that generated proposals produced **exactly one LONG and one
SHORT momentum candidate for the same asset / strategy / timeframe /
decision window**. Both directions are CHALLENGEd by the CounterSignalCritic
because each is the mirror of the other inside the same proposal set; the
DebateReport terminates `UNRESOLVED`; the DecisionEngine marks every candidate
`INELIGIBLE_UNRESOLVED_CONFLICT`. Result: deterministic structural deadlock —
no candidate can ever reach Decision/Risk whenever the runtime submits both
directions of one evaluation as simultaneous independent claims.

Real examples captured (all with `material_dissent=true`,
`challenged_by=["critic-counter-signal"]`): BTC LONG/SHORT pair
(`decision:802443ea50895590`), ETH LONG/SHORT pair, SOL LONG/SHORT pair —
full rows in `poc02-pre-repair/cycles/POC02_ATTRIBUTION.jsonl`.

## 4. Artifact hashes (SHA-256, over frozen copies)

| Artifact | SHA-256 |
| --- | --- |
| POC02_CAMPAIGN_STATE.json | `058c0b122b4d352b603a821615dbcf337c2ba1ec6fab925591fc1c0b313fac9a` |
| POC02_CYCLE_LEDGER.jsonl | `495d10665f178cd6f04317679cdfb6c86531df953da07fccab407d9c90336238` |
| POC02_COVERAGE_DAILY.jsonl | `f8117d6ff879ba80a74ab75da91934a97378da37b423b52bee5b55931aedc8b2` |
| POC02_LAUNCH_RECORD.json | `9a31298fc1d5f60f9d5abaec45850b8a63cc2de0d1934b6efaf328edf07a3fec` |
| POC02_ATTRIBUTION.jsonl | `2bdca63cb625e7243aef3b77736d9747e50f55bbd4770de0424379f7e9569f31` |

## 5. Governance at freeze

- Old campaign artifacts modified: **0**
- POC01 modified: **0**
- RiskManager modified: **0** · Thresholds modified: **0**
- Confirmation lock CONF-EDGE-002-001: consumed=false, executions=0
