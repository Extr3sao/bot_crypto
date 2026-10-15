# WP-EDGE-09A — estate audit

*Read at the tree of `ef5c8f2baa4a` on branch `agent/edge-recovery/WP-EDGE-00-baseline`. RFC present: `True`.*

## 1. Authoritative inputs (read, never written)

| File | Bytes | SHA-256 | Last commit | Dirty |
| --- | ---: | --- | --- | :-: |
| `config/risk.yaml` | 1870 | `3c27c866d5f11afe…` | 10cdee2 chore: initial Phase 0 scaffolding for crypto-scalping-agentic-bot | False |
| `config/runtime.yaml` | 1907 | `ac3cf4fce9ff6246…` | 10cdee2 chore: initial Phase 0 scaffolding for crypto-scalping-agentic-bot | False |
| `docs/COST_MODEL_V3.json` | 28651 | `2f0e62d2408e6cc5…` | 3fd712e feat(research): parametrisable COST_MODEL_V3 + venue economics + execution model | False |
| `docs/EXECUTION_COST_MODEL_V4.json` | 9207 | `7e772c34cbf0c894…` | 3120f3f research(microstructure): measure the untested flow/OI hypotheses on real data â€” no edge found | False |
| `docs/FORWARD_DATA_CONTRACT.json` | 7740 | `eab7f4b158a9f8e4…` | d3b7c04 feat(research): certify the forward hour with a network-free replay and an id-space trade chain | False |
| `docs/source_registry.md` | 26899 | `c5a8bf6b48da6f73…` | df95974 docs(research): RFC-030 pair execution, short-cost and accounting contracts | True |

Runtime mode `paper`, `live_trading_enabled` in `config/runtime.yaml` = `false` and in `config/risk.yaml` = `false`. This package reads both and writes neither.

## 2. Data estate

| Path | Kind | Files | MiB |
| --- | --- | ---: | ---: |
| `data` | market and run data | 894 | 220.9 |
| `reports/microstructure-forward` | forward microstructure capture | 107 | 360.2 |
| `reports/microstructure-forward-continuous` | forward microstructure capture | 1132 | 1661.3 |
| `reports/microstructure-forward-lab` | forward microstructure capture | 421 | 530.7 |
| `reports/microstructure-v1` | microstructure phase artifacts | 67 | 92.4 |
| `reports/microstructure-v2` | microstructure phase artifacts | 7 | 5.5 |
| `reports/edge-recovery` | edge-recovery work packages | 320 | 70.1 |
| `reports/execution-economics` | execution cost phase | 36 | 0.1 |
| `reports/carry` | carry/basis research | 40 | 14.6 |
| `reports/economic001` | economic checkpoint | — | absent |

## 3. Forward microstructure captures actually on disk

| Root | Run | Started | Duration (s) | Markets | Segments | Continuity | Status |
| --- | --- | --- | ---: | --- | ---: | --- | --- |
| `reports/microstructure-forward` | `forward-1790610007-9d07f3df` | 2026-09-28T15:40:07.810000+00:00 | 3783.3 | ['spot', 'perp'] | 78 | INCOMPLETE_DATA | None |
| `reports/microstructure-forward-cert01` | `paper-lab-cert-01` | 2026-09-29T22:14:04.368000+00:00 | 719.1 | ['spot', 'perp'] | 89 | CONTINUOUS_DATA | CONTROLLED_STOP |
| `reports/microstructure-forward-continuous` | `paper-lab-continuous-02` | 2026-09-29T22:59:18.288000+00:00 | 14973.5 | ['spot', 'perp'] | 1009 | INCOMPLETE_DATA | CONTROLLED_STOP |
| `reports/microstructure-forward-headcert` | `headcert-3d3be37` | 2026-09-29T18:29:44.490000+00:00 | 1000.9 | ['spot', 'perp'] | 211 | INCOMPLETE_DATA | None |
| `reports/microstructure-forward-headcert-222078b` | `headcert-222078b` | 2026-09-29T21:10:15.993000+00:00 | 782.3 | ['spot', 'perp'] | 297 | INCOMPLETE_DATA | COMPLETE |
| `reports/microstructure-forward-lab` | `paper-strategy-lifecycle-shadow-01` | 2026-10-01T16:10:21.686000+00:00 | 1114.9 | ['spot', 'perp'] | 409 | INCOMPLETE_DATA | CONTROLLED_STOP |
| `reports/microstructure-forward-lab` | `paper-strategy-lifecycle-shadow-02` | 2026-10-01T17:57:08.801000+00:00 | 7220.6 | ['spot', 'perp'] | 409 | INCOMPLETE_DATA | CONTROLLED_STOP |
| `reports/microstructure-forward-lab-05` | `paper-lab-stoprestart-02` | 2026-09-29T18:26:58.045000+00:00 | 94.0 | ['spot', 'perp'] | 49 | INCOMPLETE_DATA | None |
| `reports/microstructure-forward-lab-06` | `paper-lab-integrated-04` | 2026-09-29T18:48:59.246000+00:00 | 1296.0 | ['spot', 'perp'] | 143 | INCOMPLETE_DATA | None |
| `reports/microstructure-forward-lab-07` | `paper-lab-final-head-01` | 2026-09-29T19:15:51.791000+00:00 | 179.7 | ['spot', 'perp'] | 40 | CONTINUOUS_DATA | None |
| `reports/microstructure-forward-lab-08` | `paper-lab-continuous-01` | 2026-09-29T19:21:19.008000+00:00 | 3307.9 | ['spot', 'perp'] | 69 | INCOMPLETE_DATA | None |
| `reports/microstructure-forward-lab-smoke-cert` | `smoke-cert` | 2026-09-29T22:46:02.249000+00:00 | 20.9 | ['spot', 'perp'] | 38 | CONTINUOUS_DATA | COMPLETE |
| `reports/microstructure-forward-lab-smoke-cert2` | `smoke-cert2` | 2026-09-29T22:48:25.532000+00:00 | 20.9 | ['spot', 'perp'] | 38 | CONTINUOUS_DATA | COMPLETE |
| `reports/microstructure-forward-lab-smoke-cert3` | `smoke-cert3` | 2026-09-29T22:50:03.567000+00:00 | 20.9 | ['spot', 'perp'] | 38 | CONTINUOUS_DATA | COMPLETE |
| `reports/microstructure-forward-lab-smoke-cert4` | `smoke-cert4` | 2026-09-29T22:51:51.224000+00:00 | 20.7 | ['spot', 'perp'] | 59 | CONTINUOUS_DATA | COMPLETE |
| `reports/microstructure-forward-ops01` | `paper-lab-ops-hardened-01` | 2026-09-29T20:42:06.205000+00:00 | 1368.9 | ['spot', 'perp'] | 115 | INCOMPLETE_DATA | CONTROLLED_STOP |
| `reports/microstructure-forward-recert-7b14297` | `recert-7b14297` | 2026-09-29T20:17:29.502000+00:00 | 662.7 | ['spot', 'perp'] | 249 | CONTINUOUS_DATA | COMPLETE |
| `reports/microstructure-forward-smoke` | `forward-1790606407-7308fd49` | 2026-09-28T14:40:07.624000+00:00 | 23.3 | ['spot', 'perp'] | 38 | CONTINUOUS_DATA | None |
| `reports/microstructure-forward-writercert` | `writercert-v1` | 2026-09-29T14:28:26.596000+00:00 | 1006.7 | ['spot', 'perp'] | 0 | INCOMPLETE_DATA | None |

## 4. Closed work, read from the artifact that closed it

| Phase | Artifact | Status line | Digest |
| --- | --- | --- | --- |
| MICROSTRUCTURE-EDGE-V1/V2 | `docs/MICROSTRUCTURE_FINAL_REPORT.md` | FINAL STATUS: MICROSTRUCTURE_NO_EDGE_FOUND | `35a739c48db80e24` |
| MICROSTRUCTURE-V2-ADMISSION | `docs/MICROSTRUCTURE_ADMISSION_V2.md` | FINAL STATUS: MICROSTRUCTURE_NO_EDGE_FOUND (ampliado) | `53ba3143e26c99d8` |
| MICROSTRUCTURE-FORWARD-COLLECTION-V1 | `docs/MICROSTRUCTURE_FORWARD_COLLECTION_FINAL.md` | FINAL STATUS: MICROSTRUCTURE_FORWARD_DATA_VERIFIED | `b925d782cbdd1084` |
| EXECUTION-COST-MODEL-V4 | `docs/COST_MODEL_V3.md` | — | `e40e8f6a33d22317` |

## 5. What this package reuses, and what it must not repeat

- `src/trading_bot/research/microstructure/` — cost models V2/V3/V4, execution model, PIT types, integrity checks
- `src/trading_bot/research/forward/` — the capture read side (storage, contract, aggregation) this package reads
- `docs/source_registry.md` — SRC-01..SRC-18 with their measured claims; extended, never rewritten

## 6. Work packages of RFC-EDGE-009

- **WP-EDGE-09A** — audit: repository, runtime and the data actually held
- **WP-EDGE-09B** — sources: provider viability, coverage, provenance, point-in-time
- **WP-EDGE-09C** — hypotheses: falsifiable economic statements, registered first
- **WP-EDGE-09D** — gates: cost, liquidity, capacity and frequency
- **WP-EDGE-09E** — experiments: run only where the gates allow, negatives included
- **WP-EDGE-09F** — verification: independent, adversarial, and the closure
