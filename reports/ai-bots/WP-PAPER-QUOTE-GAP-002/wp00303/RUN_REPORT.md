# RUN REPORT — WP-003-03 — PAPER end-to-end validation

Generated 2026-10-22T21:24:43Z from `PAPER_E2E_LAB.json`, `VERIFICATION.json` and the pytest log.

## Qué se ejecutó

| escenario | decisiones | TRADE | NO_TRADE | órdenes | fills abiertos | fills cerrados |
| --- | --- | --- | --- | --- | --- | --- |
| E2E-COMMITTED | 480 | 0 | 479 | 0 | 0 | 0 |
| E2E-SCENARIO | 480 | 32 | 448 | 23 | 21 | 21 |
| E2E-RESTART | 120 | 0 | 120 | 0 | 21 | 21 |

- Ventana: 160 ciclos por escenario desde el índice 600, 1h, activos BTC, ETH, SOL.
- Datos: BINANCE_PUBLIC_REST:/api/v3/klines (1h), manifiesto `data/edge07/holdout-1h/_FETCH_MANIFEST.json`; 3 series con sha256 verificado.
- Spread: 1.0 bps — ESTIMATED: COST_MODEL_V3 majors default, not an observed quote.

## Dimensiones (no se fusionan)

| dimensión | resultado | base |
| --- | --- | --- |
| IMPLEMENTATION_STATUS | PASS | paper_e2e_lab.py and verify_paper_e2e.py are committed with the evidence; no runtime file was modified (runtime_identity check re-hashes 13 files) |
| TEST_STATUS | PASS | pytest: 37 passed in 4.95s (exit 0) |
| RUNTIME_VALIDATION | FAIL | the real AutonomousPaperRuntime ran 23 orders / 480 decisions in E2E-SCENARIO and 480 decisions in E2E-COMMITTED |
| NETWORK_ISOLATION | FAIL | the network check failed: see VERIFICATION.json |
| EXTERNAL_ORDER_PREVENTION | FAIL | 13 refusals across 8 abuse scenarios; 0 venue calls |
| INDEPENDENT_VERIFICATION | NOT_RUN | verify_paper_e2e.py: 0/0 checks, None/None negative controls rejected |
| PAPER_VALIDATION | BLOCKED | recorded Binance 1h klines (sha256-matched); orders=23 fills_closed=21 PAPER only. EXTERNAL_SESSION=NOT_PERFORMED: the paper policy denies the network, so no venue-connected session can exist under it. |
| GITHUB_SYNC | REMOTE_BRANCH_SYNCED | local=baf5b560 remote=baf5b560 main=5e6f9632 pending=1 |
| FALSE_SUCCESS | FAIL | unsupported_pass_count=0; every dimension above is derived from a measured artefact, and a blocked check is never counted as passed |

## GITHUB_SYNC

| field | value |
| --- | --- |
| repository | https://github.com/Extr3sao/bot_crypto.git |
| local_branch | recovery/wp00303 |
| remote_branch | recovery/wp00303 |
| local_head_sha | baf5b560101188ecceb36a4880d3dca16b267e31 |
| remote_head_sha | baf5b560101188ecceb36a4880d3dca16b267e31 |
| default_branch_sha | 5e6f9632e8d9c15dabd60ea92ac68f350ca28c9d |
| commits_pending | 1 |
| push_result | ok |
| pull_request_url | None |
| merge_result | None |
| sync_status | REMOTE_BRANCH_SYNCED |
| verification_timestamp | 2026-10-22T21:22:24Z |

## Comandos

```bash
python scripts/paper_e2e_lab.py
python scripts/verify_paper_e2e.py --lab ... --bundle ... --repo . --evidence-sha <commit> --repeat <second run> --negative-controls --json ...
```

pytest: 37 passed in 4.95s

