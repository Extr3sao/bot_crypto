# WP-SIGNAL — supervised live session `wp-signal-live-01`

**Generated:** 2026-10-26T10:50:49+00:00 · **Run id:** `wp-signal-live-01`
**Mode:** PAPER/SHADOW, provider `ccxt`, routing `SHADOW` · **LIVE execution:** disabled

## What ran

```
scripts/start_paper_lab.py --run-id wp-signal-live-01 --provider ccxt --routing-mode SHADOW \
    --duration-hours 1 --data-root reports/microstructure-forward-lab-wp-signal-01
scripts/paper_lab_dashboard.py --port 8792 --run-id wp-signal-live-01
```

Supervisor state **HEALTHY**, uptime
3064 s, children:
paper=RUNNING, collector=RUNNING, retention=RUNNING, strategy_lab=RUNNING, analyst=RUNNING.

## What the engine really produced

| Stage | Rows |
|---|---|
| CANDIDATE | 72 |
| REJECTED | 72 |

| Kind | Rows |
|---|---|
| ALPHA | 72 |
| NO_ALPHA | 72 |

- 144 signals / 144 traces, all `source=REAL`
  (provider `ccxt`), decisions from 2026-10-26T09:59:35.090Z to 2026-10-26T10:50:05.906Z.
- **0 orders created.** `PAPER_ORDER` is `BLOCKED`:
  the admission ledger admits none of the 24 strategies, so nothing was traded.
  `SHADOW` records an observation and cannot create an order.
- Analysis rows: 5 (NOT_CONFIGURED=5). No model provider is
  configured on this host, so the sidecar records `NOT_CONFIGURED` rather than a synthesis.

## Dashboard (GET only, loopback)

| Endpoint | Result |
|---|---|
| `GET /healthz` | 200 |
| `GET /api/signals` | 200 — served 50 of 138 rows, stream `LIVE` (the newest signal is 25s old), `read_only=true` |
| `GET /api/analysis` | 200 — 138 signals, coverage 3.6%, state `NOT_CONFIGURED`, `authority_over_orders=false` |
| `GET /api/status` | 200 |
| `POST /api/signals` | 405 (mutation refused) |
| `DELETE /api/signals` | 405 (mutation refused) |

Captured payloads and the rendered page are in `evidence/` with their SHA-256 in
`RUN_REPORT.json`.

## Independent verification (BUILDER != VERIFIER)

`scripts/wp_signal_verify.py` was executed from a **clean clone of the PR head**
(`b21aab58`) against this run, importing nothing from `trading_bot.autonomous`:

- **29 checks, 0 failed, ok=True, exit 0**
- counts: `{"provider": "ccxt", "traces": 138, "signal_rows": 138, "trace_linked": 138, "analysis_rows": 5, "analysis_by_status": {"NOT_CONFIGURED": 5}}`

## Tests

| Suite | Result |
|---|---|
| signal tests (events/analysis/service/verifier + lab ops + cadence), before my change | 97 passed in 9.18s |
| same focal set after the verifier change | 55 passed in 4.78s |
| `tests/unit/risk` + `tests/unit/autonomous` + `tests/unit/config` in the working tree | 5 failed, 493 passed in 46.41s |
| `tests/unit/risk/test_futures_independent_verifier.py` in a clean clone of the PR head | 8 passed in 3.55s (exit 0) |

The two `risk` failures seen in the working tree (`bracket_provenance`) reproduce
**only** in this checkout and pass in the clean clone at the same commit: they are
local-state dependent (the ST6 workstream modified `data/st6/` here), not a
regression of the signal work.

## Defects found and their state

1. **`wp_signal_verify.py --out <directory>` crashed** with `PermissionError` from
   pathlib instead of writing the report inside the directory. Fixed (an existing
   directory now receives `SIGNAL_VERIFY.json`, missing parents are created) and
   covered by two new tests in `tests/unit/autonomous/test_signal_verifier.py`.
2. **`PAPER_RUN.json` recorded no provider**, so the verifier could not check
   `REAL` vs `FAKE` provenance. Fixed at the PR head; the verifier now fails
   `signals.source_provenance_known` instead of passing vacuously when the
   provider is absent.
3. **Re-projecting a resumed run reported `conflicts` instead of
   `skipped_duplicates`** (`sync()` defaulted to `REAL` while the rows were
   `FAKE`). A fix is in progress in the shared worktree
   (`SignalLedger` learns the run's provenance from disk).

## Claims this report does not make

- PAPER_RUNNING as a service claim: the supervisor, heartbeat and children were alive for the length of this session, but no Windows task was installed and no 24x7 ownership is claimed here.
- AI analysis: no model provider is configured and no key was used, so the analyst rows are NOT_CONFIGURED, never a fabricated claim.
- PROFITABLE: no strategy is admitted and no edge is claimed; every row is an observation of the engine's own decision.

Refs: #50, PR #51.
