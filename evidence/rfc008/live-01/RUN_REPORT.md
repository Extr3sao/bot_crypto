# RUN_REPORT — paper-lab-rfc008-live-01

```text
state        : DEGRADED
uptime       : 1263.53 s
cycles       : 5
signals      : 15
provider     : ccxt / MAINNET / binance-public-rest
paper orders : 0   shadow outcomes: 0
admitted     : 0
verifier     : True
```

## Blockers

- `PAPER_ORDER_BLOCKED_ADMISSION_0_OF_24`
- `AI_NOT_CONFIGURED`

## Limitations

- no ANALYZED row: no provider key was configured; latency/cost are null
- observed window is 0.35 h, not 24 h: state is 24H_NOT_VERIFIED
- 1 process restart(s) occurred (analyst exit=1); a DEGRADED final_state reflects that restart, not a data failure

## Signals by stage/kind

`{"CANDIDATE": {"ALPHA": 12}, "REJECTED": {"NO_ALPHA": 3}}`

## Analysis

`{"NOT_CONFIGURED": 15}`

## HTTP

`{"/": {"bytes": 66780, "http": 200, "latency_ms": 45}, "/api/analysis": {"bytes": 17289, "http": 200, "latency_ms": 47}, "/api/signals": {"bytes": 66106, "http": 200, "latency_ms": 62}, "/api/status": {"bytes": 101406, "http": 200, "latency_ms": 30}, "/healthz": {"bytes": 53, "http": 200, "latency_ms": 63}, "POST /api/signals": {"http": 405}}`

## Evidence sha256

- `PAPER_RUN.json` — `2637de1d51fe3f5e1c60bfd86ff55a8993ca150a96acb708cb42b9702af65f28`
- `signals.jsonl` — `40ac8cbe81910ede5bdd8f56d16f5f5d1ad962d43c13c009e09979120b418eb6`
- `traces.jsonl` — `057c1c0a2ea96231f5ef244eb74d672139f085ddb41a3ae8d135a81e182897d3`
- `analysis.jsonl` — `d0c45337f2b33fc08b9f6827d9714280c48bbdd3803f2808e920f0b977ea7eef`
- `outcomes.jsonl` — `49f2a0ac924318c0ece7903f81ccd3743062d84d67f0d4c66fd80663c0587a03`
- `heartbeat.json` — `15504d2f4deaf9dfc353fedf4942d0e2076f65efbfad7896bebe5b919ac7c84e`
- `heartbeat.jsonl` — `0dfc888f9e1d6e30153de40bf47b984c479f5603c7e3cb8f66ce5cf77707e7c2`
- `SIGNAL_VERIFY.json` — `bf1fb59fc11dcad5134808f7f3673fb5b0443366566d7ede6e184d280f39aac8`
- `LAB_PLAN.json` — `282241dd07008f7072f3101752e1176d89f033778d294c117a277cd1c412bf76`
- `LAB_RUN_REPORT.json` — `4452056da76502fc3f048c370a43b7fe49a4d97902cf99acce497e912265a83a`
- `SYSTEM_HEARTBEAT.json` — `3d26c2270fefd57d90b8f1d53c0d804e23d386234901b98cbc770997015de97c`
