# ST-6 — autonomous forward observation

Generated 2026-10-09T16:37:46Z at `7cd8d72f8d4330682af560f11b30cac211ad78b3`.

Status: **ST6_AUTONOMOUS_COLLECTION_ACTIVE**.

## Task

`TradingAgentic-ST6-Forward` — installed: True, enabled: True, repetition: PT15M.

Action: `C:\Users\GVLLFR0035\Downloads\bot freebuff\.venv\Scripts\python.exe` `"C:\Users\GVLLFR0035\Downloads\bot freebuff\scripts\st6_forward_regime.py" --due --scheduled` in `C:\Users\GVLLFR0035\Downloads\bot freebuff`.

| live test | result |
| --- | --- |
| real execution | PASS |
| due idempotency | PASS |
| concurrency | PASS |
| error exit status | PASS |
| period closure guard | PASS |

## Windows

Planned 84, completed 7, pending 77, missed 0.

Run events recorded: 375, of which 234 were ticks with nothing due. Market requests made by those ticks: 0.

## Health and storage

Health: HEALTHY (`data\st6\ST6_HEALTH_STATUS.json`, read at generation time, straight after the live tests that deliberately provoke a lease collision and a refusal; the health artefact is the authority). Disk: HEALTHY, 19.0566 GiB free (91.98% used).

Independent verification: PASS (5096/5096), FALSE_SUCCESS = 0.

## What a tick is and is not

a scheduled tick that took no sample is not a measurement: the evidence is the window with its raw bytes and its hash, and the run log only says what the tick did.

Period: `2026-10-08T16:21:20Z` -> `2026-10-22T16:21:20Z`, closed: False.

## Standing state

```text
DISCOVERY_CAMPAIGN_FAILED = True
NEXT_CAMPAIGN = NOT_AUTHORIZED
TRADES_AUTHORIZED = 0
LIVE_TRADING = DISABLED
PROFITABILITY_VERIFIED = False
ECO_2 = UNKNOWN_NOT_RESOLVABLE_OFFLINE
```

Next gate: the declared period closes at 2026-10-22T16:21:20Z; then the consolidation and the independent verification run automatically and the gate becomes the ECO-1 decision.

Research only: no orders, no credentials, no capital.
