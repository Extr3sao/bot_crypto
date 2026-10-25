# REAL_DATA_PAPER_RUN — REAL-DATA-PAPER-01 (+ RUN-A..D)

Executed on final HEAD `b1f427e` (main, clean tree). Environment: Windows,
Python 3.11.15, uv venv. NO credentials, NO order API: Binance **testnet**
spot via the existing CCXT connector (read-only OHLCV), paper mode enforced.

## Provider audit (no new provider added)

- Runtime-reachable real providers: `binance`, `bitunix`, `bybit` (hub adapters,
  `wiring._ADAPTER_BUILDERS`). Selected `binance` via a dedicated config
  profile `config/realdata/` (sandbox: true, `runtime.exchange_id: binance`,
  CL-4 no-fallback). Public read-only endpoints; zero credential variables set.

## Runs (all exit 0; raw stdout in `reports/runs/`, gitignored by policy)

| RUN | Provider | Result (cycle counters) |
| --- | --- | --- |
| RUN-A deterministic NO_TRADE | fake | 2 sessions; contexts=3, orders=0, reason `no_alpha_in_direction:ANY` (fail-closed strategy stage) |
| RUN-B TRADE lifecycle | **binance testnet** | fresh book: cycle 1 orders=3; cycles 2-3 duplicate_intents=3/3, orders=0 (exactly-once live) |
| RUN-C crash + restart + reconcile | **binance testnet** | restart on persisted book → `RECOVERED` (3 positions, 3 intents, equity 10000.0 identity OK); post-restart cycle orders=0; then with restored exposure: `risk_rejected=3 reason="Max open positions reached (3)"` |
| RUN-D duplicate/retry intent | **binance testnet** | cycle 1 orders=2; cycle 2 duplicates=2, orders=0 |
| RUN-E REAL-DATA-PAPER-01 | **binance testnet** | BTC,ETH,SOL 5m; 2 sessions; 3 real fills opened (500 USDT each, slippage 1bp, fee 5bp); cycle 2 all intents duplicates (0 new orders); state saved |

Note on RUN-E ordering: it was executed twice — first before the exposure
sync fix (3 orders), re-executed on the final HEAD after RUN-C (cycle 1
`risk_rejected=3` because the book legitimately held 3 restored positions).
Both behaviors are correct hardening outcomes; the final-HEAD run is the
authoritative evidence.

## Point-in-time capture (§15) — `reports/runs/REAL-DATA-PIT-CAPTURE.txt`

```json
{
  "symbol": "BTC/USDT", "timeframe": "5m",
  "pit_invariant_latest_consumed_le_decision": true,
  "forming_candle_excluded": true,
  "closed_rule_ok": true,
  "decision_time_ms": 1790325945000,
  "latest_source_timestamp_ms": 1790325900000,
  "latest_consumed_data_time_ms": 1790325600000
}
```

`latest_consumed_data_time <= decision_time` holds; the forming candle is
excluded by the V3 closed-candle rule (`open + tf <= decision_time`),
enforced in `FetcherBarReader` (new) + `trim_to_pit` (defence in depth).

## Provider failure policy (§14) — tests in `test_provider_failures.py`

| Case | Policy |
| --- | --- |
| timeout / network error | PROPAGATE (runner records history_error; never silent NO_TRADE) |
| empty dataset | [] → context error (fail closed, observable) |
| partial response | accept as-is; context enforces min history; never padded |
| duplicate candles | keep first, reject rest |
| out-of-order | reorder ascending |
| stale last candle | kept if closed (freshness is the router's stale gate) |
| future candle | rejected (closed-candle filter) |
| missing candle | never invented |
| invalid timestamp | bar rejected |
| forming candle | NEVER leaked (open + tf <= decision_time) |
| unknown timeframe | fail closed (`UnknownTimeframeError`) |
