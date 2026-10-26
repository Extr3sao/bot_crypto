# `wp-signal-live-01` — session end

**Generated:** 2026-10-26T11:05:08+00:00

## Graceful stop

```
scripts/start_paper_lab.py --stop reports/paper-lab/wp-signal-live-01   -> exit 0
```

- `stop_reason`: **STOP file**, descriptor state `STOPPED`,
  ended at ms 1793012064833.
- Children at the end: paper=STOPPED, collector=STOPPED, retention=STOPPED, strategy_lab=STOPPED, analyst=STOPPED. Supervisor state `DEGRADED`.

## What the whole session produced

| Metric | Value |
|---|---|
| asset cycle evaluations | 153 |
| traces persisted | 153 |
| signals in the stream | 153 |
| analysis rows | 5 (NOT_CONFIGURED) |
| **orders created** | **0** |
| paper trades | 0 |
| shadow trades | 0 |
| runtime failures | 0 |
| risk APPROVED / VETOED | 78 / 0 |

`PAPER_ORDER` stayed `BLOCKED` for the whole session: the admission ledger admits
none of the 24 strategies, so nothing could be traded and nothing was.

## Dashboard after the stop

| Item | Value |
|---|---|
| `GET /api/signals` state | `DOWN` — the lab is not running; the stream is the last one written |
| `GET /api/status` system | `DEGRADED`, running=False |
| errors surfaced | ['supervisor heartbeat is 463s old: the lab may have died'] |

The board reports the lab as **DOWN**, not as healthy: a stopped lab must look
stopped.

## Verification after the stop

`scripts/wp_signal_verify.py` (clean clone of the head) → **29 checks,
0 failed, ok=True, exit 0**,
counts `{"provider": null, "traces": 153, "signal_rows": 153, "trace_linked": 153, "analysis_rows": 5, "analysis_by_status": {"NOT_CONFIGURED": 5}}`.

### Known limitation of this session

the final PAPER_RUN.json written by this session declares no `provider`, so the verifier reported provider=null. Cause: the session ran the entrypoint as it stood at 3be8e5bd; the head already rewrites the final descriptor with the provider.
The head scripts/autonomous_paper.py at the head writes "provider": args.provider in the STOPPED rewrite.

Refs: #50, PR #51.
