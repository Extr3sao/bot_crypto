# RUN_REPORT — paper-lab-rfc008-live-02

```text
state        : DEGRADED
uptime       : 1958.982 s
cycles       : 11
signals      : 33
provider     : ccxt / MAINNET / binance-public-rest
paper orders : 0   shadow outcomes: 1
admitted     : 0
verifier     : True
```

## Blockers

- `PAPER_ORDER_BLOCKED_ADMISSION_0_OF_24`
- `AI_NOT_CONFIGURED`

## Limitations

- no ANALYZED row: no provider key was configured; latency/cost are null
- observed window is 0.54 h, not 24 h: state is 24H_NOT_VERIFIED

## Signals by stage/kind

`{"CANDIDATE": {"ALPHA": 28}, "REJECTED": {"NO_ALPHA": 4}, "SHADOW": {"ALPHA": 1}}`

## Analysis

`{"NOT_CONFIGURED": 33}`

## HTTP

`{"/": {"bytes": 126463, "http": 200, "latency_ms": 62}, "/api/analysis": {"bytes": 35689, "http": 200, "latency_ms": 93}, "/api/signals": {"bytes": 144442, "http": 200, "latency_ms": 94}, "/api/status": {"bytes": 203558, "http": 200, "latency_ms": 92}, "/healthz": {"bytes": 53, "http": 200, "latency_ms": 125}, "POST /api/signals": {"http": 405}}`

## Evidence sha256

- `PAPER_RUN.json` — `fed98883b464d4b1af24e109d68ef7fcdd59427cda04412c857d6ef2c99335a1`
- `signals.jsonl` — `37603b4681fdc3f043599524242376ff86f34a78099f4a89d9519e9c0eb6799a`
- `traces.jsonl` — `04ac16d4ac39eae6e9aeda139eb4af5da0927a02f5cab2b39b3d5547dd7da9cc`
- `analysis.jsonl` — `3f7c8363bda5b48d0d0d7bf0238c7fd3bde4ddbda43e52f0de27e4714cf9ee12`
- `outcomes.jsonl` — `131045a4bcaca3387f7f35a88ad3095dcb37fb578d7a083897d7924e886ed6cf`
- `heartbeat.json` — `dd4f84db8f3481912a344b906ae1996e46fdc4d36364417a7a436b09760df208`
- `heartbeat.jsonl` — `0e76b68bcb9ff6b3806547930955eeb266c40722079953a64ac3c5a59c74ada4`
- `SIGNAL_VERIFY.json` — `0185e7b6259748f7449f4e7318fed30d37dd5219aeedcb721b6030fb4c634b0a`
- `LAB_PLAN.json` — `e14c7183478da217e4e62729ed5fa60971bebacccec45ccc07cfbf1603d8e0b2`
- `LAB_RUN_REPORT.json` — `1e6baeadb5e594305d9f61450a6b9264825d02416e6a8128975ddfee4df94167`
- `SYSTEM_HEARTBEAT.json` — `a3155733d7ec5879579450d2ca98065e5d198a51490328a86eca418c1cefe324`
