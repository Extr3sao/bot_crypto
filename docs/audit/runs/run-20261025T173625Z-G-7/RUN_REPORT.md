# G-7 — Run report

**Verdict:** `G7_BLOCKED_NO_ELIGIBLE_STRATEGY`  
**Execution class:** `PAPER_ONLY_REAL_PUBLIC_DATA`  
**Implementation commit:** `5c76060f` (includes `f3a83569`)  
**G-6 baseline:** `d5e599ec` (`G6_VERIFIED`)  
**Evidence commit:** the commit that contains this directory (see `git log -- docs/audit/runs/run-20261025T173625Z-G-7`)  
**Started (UTC):** 2026-10-25T17:19:42Z  
**Finished (UTC):** 2026-10-25T17:19:47Z  
**Environment:** Python 3.11.15, `win32`, repo `C:/Users/GVLLFR0035/Downloads/ff-wt-g7`

## 1. Command

```bash
uv run python scripts/audit/g7_real_paper.py \
  --out docs/audit/runs/run-20261025T173625Z-G-7 \
  --capture docs/audit/fixtures/g7_market_capture.json \
  --timeframe 5m \
  --assets BTC,ETH,SOL
```

Exit code: `0` (evidence completed). The verdict is in the payload; exit 0 does
**not** mean G-7 passed.

## 2. Data

| Field | Value |
|---|---|
| Provider | `binance-public-rest` |
| Endpoint | `https://api.binance.com/api/v3/klines` (plus public tickers) |
| Capture | `docs/audit/fixtures/g7_market_capture.json` |
| Raw SHA-256 | `cad0cd5ce98a27ab17f558928b8024ff357906e443b849382311ee2835df7f53` |
| Canonical capture SHA-256 | `136ed36e45a6a8714786c9976df1b438b72192c06ebe9c010eabd1d99c37e5d7` |
| Symbols | BTC/USDT, ETH/USDT, SOL/USDT |
| Bars | 500 × 3, 5m |
| Range | 2026-10-23T23:25Z → 2026-10-25T17:00Z (open) |
| Forward received | 2026-10-25T17:19:46.823Z |
| Forward decision | 2026-10-25T17:19:46.823Z |

Replay and forward are separated by `data_mode`
(`HISTORICAL_REPLAY` vs `FORWARD`). The forward decision is after the provider
answered; no data was back-dated.

## 3. Results

| Metric | Value |
|---|---:|
| Replay sessions | 3 |
| Replay restart sessions | 1 |
| Forward sessions | 1 |
| Contexts built (total) | 15 |
| Router NO_TRADE (total) | 15 |
| Strategy invocations | 0 |
| Signals generated | 0 |
| Risk accepted | 0 |
| PAPER orders | 0 |
| Broker `execute_signal` calls | 0 |
| Eligible strategies | 0 |
| Strategy evaluations | 72 |
| Invalid-data scenarios blocked | 6/6 |
| Provider-failure orders | 0 |
| Duplicate orders | 0 |
| `FALSE_SUCCESS` | 0 |

Explicit decision outcomes: `{"NO_TRADE": 5}` — three replay sessions, one
restart, and the forward session. There is no `PAPER_TRADE` because no
strategy is admitted.

## 4. Why `BLOCKED`

The committed ledger has 24 entries and none has
`admitted_for_paper=true` (`COST_KILLED=7`, `NO_GROSS_EDGE=17`). The router
therefore returned `NOT_APPLICABLE` for every strategy/asset pair. Enabling one
would require changing admission policy or bypassing the router; neither was
done. This is the condition-3 failure required by the G-7 contract, so the
verdict is `BLOCKED`, not `PASS`.

## 5. Tests

```bash
uv run pytest -q \
  tests/unit/market_data/test_public_rest.py \
  tests/unit/market_data/test_real_data_validation.py \
  tests/unit/paper/test_real_eligibility.py \
  tests/integration/test_g7_real_paper_replay.py \
  tests/integration/test_g5_paper_end_to_end.py \
  tests/unit/test_live_gate_enforcement.py
# 75 passed in 41.40s
```

The independent verifier repeats these tests inside the clean export.

## 6. Independent verification

`verification.json` in this directory is produced by `scripts/audit/verify_g7.py`,
which:

1. exports the requested commit with `git archive`;
2. re-runs the replay twice from the committed capture;
3. optionally runs one forward observation;
4. re-derives every check below;
5. runs the tests inside the export.

Result: **18/18 checks**, veredicto `G7_BLOCKED_NO_ELIGIBLE_STRATEGY`,
`FALSE_SUCCESS=0`, sobre `c85e2af2`. El verifier ejecutó 75 tests dentro del
export y un forward propio (`EXECUTED`, `received_at == decision_time`, 0
órdenes). El detalle está en `verification.json`; el resumen en
`FINAL_REPORT.md`.

## 7. Artifacts

| File | Meaning |
|---|---|
| `RUN_REPORT.json` / `evidence.json` | machine-readable evidence (identical) |
| `market_capture.json` | exact capture replayed in this run |
| `data_access_forward.jsonl` | 9 public requests, `authenticated=false` |
| `replay/paper_state.json` | durable empty book after three replay decisions |
| `forward/paper_state.json` | durable book after the forward decision |
| `provider_failure/paper_state.json` | empty book after a provider outage |
| `REAL_MARKET_DATA_REPORT.md` | provenance and validation |
| `STRATEGY_ELIGIBILITY_REPORT.md` | all strategy verdicts |
| `PAPER_EXECUTION_REPORT.md` | circuit, decisions, durable state |
| `FINAL_REPORT.md` | concise delivery summary |
| `ARTIFACTS.sha256` / `EVIDENCE.sha256` | hashes of the evidence tree |

## 8. Limits

- One 41 h 40 m capture and one forward observation, not a 24 h continuous run.
- `paper_cycle` and `autonomous.decision` remain two engines.
- Verification is `PROCEDURALLY_SEPARATED` (distinct script, same author).
- No exchange client, credentials or real order; `LIVE_NO_GO` and
  `PRODUCTION_READY=false` unchanged.
