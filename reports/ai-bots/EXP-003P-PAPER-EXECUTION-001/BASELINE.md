# BASELINE — EXP-003P (WP-003P-00)

- branch `agent/ai-bots/RFC-TAP-AI-BOTS-003`, HEAD `bdd96f4cf9ed` (Leave another experiment's suite out of this gate, and say so)
- working tree: 251 modified paths in scopes `.ci, .edge04r_tmp, .tmp, .wp003i_gate_update.py, INAL_REPORT.md, RFC-TAP-AI-BOTS-003F.md, RFC-TAP-AI-BOTS-003I.md, RUN_REPORT.json, RUN_REPORT.md, context, data, docs, evidence, reports, scripts, servers.txt, src, tasks, tests` — 003P does not touch them
- config digest: `sha256:4f93519d8fc6b4040e82df6f6c495671ae5f510fe47ee246937a4400baa071fa`
- 003O dependency: `INCOMPLETE` (technical `PASS`, full `INCOMPLETE_REAL_DATA_COVERAGE`), edge `NOT_EVALUATED`

## Reachability probe (executed now, not asserted)

- `PaperBroker.execute_signal` → 8 lifecycle events `['ORDER_CREATED', 'ORDER_SUBMITTED', 'ORDER_ACKNOWLEDGED', 'ORDER_FILLED', 'ORDER_CREATED', 'ORDER_SUBMITTED', 'ORDER_ACKNOWLEDGED', 'ORDER_FILLED']`
- ledger fills applied: 2; provenance tags `['OFFLINE_SIMULATED']`; live orders: 0

## Paper provider viability

- exchange `sandbox` flag: `true`
- credential names present: `none`
- verdict: **BLOCKED_NOT_CONFIGURED** — no paper/testnet order adapter is configured for this workspace; the live adapter is out of scope and unreachable from 003P by construction

## Frozen inputs

| file | sha256 |
| --- | --- |
| `BTCUSDT.1m.jsonl.gz` | `7fbdfefa12785bb025d525994466b5a64d5c0668d6ff997f5f7566bc42d13814` |
| `ETHUSDT.1m.jsonl.gz` | `cf04dc37617a0998016fcd7edfb9b2a77c9aa5fa656bbb54422805a5964650a6` |
| `SOLUSDT.1m.jsonl.gz` | `33342aacc2ac75f897e2c9df2602a41d340c96ed08cd683dbd3871c3c7c60c32` |
| `config/runtime.yaml` | `ac3cf4fce9ff6246997a059f1c409609a7c87a6bb416198c041ca479fc49a159` |
| `config/risk.yaml` | `3c27c866d5f11afea96a80598c1e72c69816ecc3b77e97c5ad7fa86417593a2e` |
| `config/vision.yaml` | `ba817ef6f2c8768ee8bd094ffbdb0f705281f7056466c95cd0b2016e6e3fd766` |

## What this baseline does not claim

- It does not claim a paper venue exists: the provider verdict is `BLOCKED_NOT_CONFIGURED`.
- It does not claim 003O is certified: its status is inherited unchanged.
- It does not claim edge: `ECONOMIC_EDGE=NOT_EVALUATED`.
