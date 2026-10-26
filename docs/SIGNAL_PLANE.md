# SIGNAL PLANE — what the engine produces, why, and what the AI thinks

`WP-SIGNAL-001..003`. The runtime already persisted one hash-chained `DecisionTrace`
per decision; this plane makes that stream *watchable* without adding a second
decision path, a second dashboard or a trading authority.

```
market data (read-only)
        │
        ▼
autonomous_paper.py ──► DecisionTrace ──► signals.jsonl ──► dashboard  GET /api/signals
  (unchanged decision)      traces.jsonl        ▲   │                     GET /   (#signals)
                                                │   └──► analysis.jsonl ◄── ai_signal_analyst.py
                                                │            (AI, read-only)      GET /api/analysis
                                          outcome.jsonl (realised hypothetical result)
```

## WP-SIGNAL-001 — SignalEvent

One row per decision, projected from the persisted trace (`src/trading_bot/autonomous/signals.py`):

| field | source |
| --- | --- |
| `signal_id` | `sha256(run_id|decision_id|strategy_id|stage|bar_close_ms|direction)[:32]` — the identity |
| `run_id`, `decision_id`, `symbol`, `venue`, `timeframe` | trace, run configuration |
| `strategy_id`, `strategy_version`, `direction` | the proposal the decision carried |
| `bar_close_time_ms/_utc`, `decision_time_ms/_utc` | trace; `bar_close <= decision` is enforced |
| `stage` | `PAPER` (order created), `SHADOW` (observation, no order), `CANDIDATE` (proposal, no order), `REJECTED` (no proposal) |
| `kind` | `ALPHA`, `NO_ALPHA`, `NO_TRADE`, `OPERATIONAL_FAILURE` — an incident is never a decision |
| `gross_edge_bps`, `estimated_cost_bps`, `net_edge_bps` | the proposal's own numbers; **`None`** when there was no proposal (never `0`) |
| `risk_state`, `data_quality` | trace risk review; `OK`/`STALE`/`MISSING`/`UNVERIFIED` from the observation time |
| `evidence_refs` | trace `sequence` + `trace_hash` + data fingerprint |
| `candidates` | the per-strategy consideration the trace recorded, verbatim |
| `source` | `REAL` for a live provider, `FAKE` for the demo fetcher |

Storage is append-only JSONL with a monotonic `_sequence`, rotation at
20 000 rows per generation and 3 generations. Re-projecting a trace appends nothing
(same id, same body); a conflicting body under an existing id is refused and
counted, not silently chosen. The first cycle after a restart projects the whole
store, so a crash cannot leave a hole.

## WP-SIGNAL-002 — AI commentary

`scripts/ai_signal_analyst.py` + `src/trading_bot/autonomous/analysis.py`.

- Reads `signals.jsonl`, writes `analysis.jsonl`; separate process, own stop file.
- No broker, no risk engine, no order path — asserted by test, not by comment.
- States: `ANALYZED`, `PENDING` (budget), `FAILED` (timeout / provider error /
  invalid response), `NOT_CONFIGURED` (no key). A missing key is recorded per
  signal instead of looking like analysis.
- Budget: `--budget-per-hour` computed from the ledger, so a restart cannot reset it.
- The prompt carries the event and the engine's evidence, states that anything
  absent must be `null`, and marks the payload as data, not instructions.
- A later success supersedes an earlier failure as a **new** row; nothing is deleted.

Enable it with `SIGNAL_ANALYST_API_KEY` (plus optional `SIGNAL_ANALYST_MODEL`,
`SIGNAL_ANALYST_BASE_URL`, `SIGNAL_ANALYST_INPUT_USD_PER_MTOK`,
`SIGNAL_ANALYST_OUTPUT_USD_PER_MTOK`). Without it the plane still runs.

## WP-SIGNAL-003 — always-on service

| file | role |
| --- | --- |
| `scripts/paper_lab_service.cmd` | start/restart the lab with a stable run id |
| `scripts/paper_lab_dashboard.cmd` | read-only console on `http://127.0.0.1:8787` |
| `scripts/install_paper_lab_task.ps1` | Scheduled Task at logon, restarts on failure |
| `scripts/wp_signal_verify.py` | independent verifier (recomputes hashes, reads HTTP) |

Capability preflight is per layer and recorded in `LAB_PLAN.json`:
`INGEST`, `SIGNALS`, `SHADOW`, `ANALYST` run with 0 admitted strategies;
`PAPER_ORDER` is `BLOCKED` while the ledger admits none; `LIVE` is `DISABLED`
because no live path exists.

Windows route: a Scheduled Task at logon running a `.cmd`. It depends on a host
that is powered on and online — a task is not a datacentre — and GitHub Actions is
deliberately not the runtime.

## Dashboard surface (read-only, loopback only)

| endpoint | returns |
| --- | --- |
| `GET /` | the existing console plus a chronological signal board and an AI card |
| `GET /signals?symbol=&strategy=&stage=&limit=&cursor=` | the board fragment, rendered by the server |
| `GET /api/signals` | `paper-signals-view-v1`: events, filters, page, stats, integrity, retention |
| `GET /api/analysis` | `paper-analysis-view-v1`: coverage, cost, p95 latency, statuses, heartbeat |
| `GET /api/status`, `GET /healthz` | unchanged |

Pagination is bounded by the server (`MAX_PAGE_LIMIT = 200`) and cursor-based, so new
rows cannot make a page repeat or skip. `POST`/`PUT`/`PATCH`/`DELETE` return 405.

## What is *not* claimed

- No profitability: the signal plane reports what the engine decided, including
  that no strategy is admitted for paper.
- No live analysis without a configured provider: the rows say `NOT_CONFIGURED`.
- No 24×7 guarantee from this repository alone: the host has to stay up.
- `SHADOW` rows are observations, never orders; `PAPER_ORDER` stays `BLOCKED` until
  the admission gate is met.
