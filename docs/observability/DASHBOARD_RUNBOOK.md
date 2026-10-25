# Dashboard Runbook (WP-OBS-STRAT-01 §40)

## What it is

A **read-only** web console over the PAPER runtime's own artifacts. It never
starts, stops, promotes, sizes, changes risk, admits a strategy or executes.

## Start

```bash
uv run python scripts/strategy_ecosystem_dashboard.py
# read-only strategy ecosystem console on http://127.0.0.1:8790
```

Options:

| Flag | Default | Meaning |
| --- | --- | --- |
| `--host` | `127.0.0.1` | **loopback only**; a public host is refused |
| `--port` | `8790` | HTTP port |
| `--repo-root` | repo root | where `reports/` and `config/` live |
| `--runs-root` | `<repo>/reports/autonomous-paper` | run artifacts root |
| `--campaigns-root` | `<repo>/reports` | campaign reports root |
| `--run-id` | newest | pin the console to one run |
| `--stream-seconds` | `5` | SSE pulse interval |
| `--once` | off | print the page HTML and exit (no server) |

To inspect a specific run, open
`http://127.0.0.1:8790/?run_id=<run_id>`.

## Stop

`Ctrl-C` in the foreground. If it was started detached, kill the listening PID:

```bash
netstat -ano | grep :8790          # find the LISTENING pid
taskkill //F //PID <pid>           # Windows (Git Bash)
# kill <pid>                       # POSIX
```

Closing a browser tab does **not** stop the server.

## URL / ports

* Page: `http://127.0.0.1:8790/`
* Liveness: `http://127.0.0.1:8790/healthz`
* API base: `http://127.0.0.1:8790/api/...`
* SSE: `http://127.0.0.1:8790/api/events/stream`

## Dependencies

None beyond the standard library and the repo's own `trading_bot` package. No
`npm install`, no build step, no framework.

## Data sources

See [`DASHBOARD_DATA_SOURCES.md`](DASHBOARD_DATA_SOURCES.md). In short:
`config/strategy_admission.json`, and
`reports/autonomous-paper/<run_id>/{traces,outcomes,routing_comparisons}.jsonl`,
`performance.json`, `heartbeat.json`, `PAPER_RUN.json`, plus
`reports/paper-*/\{ANALYSIS.json,CAMPAIGN_CONFIG.md\}`.

## Runtime isolation (§30, ACC-OBS-17)

The dashboard runs as a **separate process** and only reads files. Stopping it, an
API error, a slow client or an SSE disconnect cannot affect the PAPER runtime or
the authoritative evidence it writes.

## Troubleshooting

| Symptom | Cause | Action |
| --- | --- | --- |
| `refusing to bind '0.0.0.0'` | loopback-only guard | use `127.0.0.1` |
| Page shows `Runtime: UNKNOWN`, `run_id NOT_AVAILABLE` | no run artifacts found | check `--runs-root`, or that a paper run exists |
| Everything `STALE` | heartbeat older than 900 s | expected for a stopped run; not a defect |
| `health` always `UNKNOWN` | health store not persisted this run | honest gap, see data-sources doc |
| `transitions NOT_AVAILABLE` | lifecycle event log not persisted | honest gap |
| Late funnel stages `NOT_AVAILABLE` | decision-level, not per-strategy | by design |
| `Address already in use` | another console on 8790 | `--port 8791` |
| POST/PUT/PATCH/DELETE return 405 | read-only by design | use GET |

## Verification quick check

```bash
curl -s http://127.0.0.1:8790/api/system        | head
curl -s http://127.0.0.1:8790/api/topology      | head
curl -s http://127.0.0.1:8790/api/routing/comparisons | head
curl -s -o /dev/null -w '%{http_code}\n' -X POST http://127.0.0.1:8790/api/strategies   # 405
```
