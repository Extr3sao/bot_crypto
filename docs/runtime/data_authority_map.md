# RFC-020 — Data Authority Map

> Point-in-time inventory of every data source that can influence an autonomous
> decision. Machine-readable twin: [`data_authority_map.json`](data_authority_map.json).
>
> Authority order: `REAL_RUNTIME > EXECUTION_EVIDENCE > TESTS > SOURCE_CODE > ARCH/RFC > ASSUMPTION`
>
> Contract: `data_time <= decision_time`, and for aggregated data
> `bar_close_time <= decision_time`. `FALSE_SUCCESS = 0`.

## Runtime chain (authoritative)

```
scripts/autonomous_paper.py
  → AdmissionLedger → StrategyRegistry → UniverseScanner
  → FetcherBarReader (PIT) → CryptoAssetAgentRegistry (regime)
  → StrategyRouter.route → 6 AlphaFamilies → TradeProposal
  → 5 reviewers → IndependentVerifier → DecisionEngine
  → RiskManager.check_signal → PaperBroker.execute_signal
  → reconciliation → DecisionTraceStore + heartbeat + RUN_REPORT
```

## Time semantics (not assumed equal)

| field | meaning |
| --- | --- |
| `event_time` | bar **OPEN**, epoch ms (UTC) — the `ts` field |
| `bar_close_time` | `ts + interval_ms` — the **availability** instant |
| `available_time` | `bar_close_time` (a forming bar is never usable) |
| `ingestion_time` | fetch wall-clock in LIVE; replay clock in the harness |
| `decision_time` | `min(snapshot_ts, session_started_ms)` = the replay instant |
| `execution_time` | `PaperBroker.closed_at` wall clock — **observability only, never read back** |

## Sources

| data_id | provider | timeframe | runtime consumer | availability | status |
| --- | --- | --- | --- | --- | --- |
| `ohlcv_5m` | Binance REST / replay source | 5m | FetcherBarReader → AssetContext + families | `ts + 300000` | **PIT_SAFE** |
| `ohlcv_htf_15m_30m_1h` | `resample_baseline_data.py` | 15m/30m/1h | none (research only) | `ts + tf` | NOT_RUNTIME_REACHABLE |
| `spread_bps` | scanner snapshot / cost default | 5m | scanner rank + CostEngine | at scan | **PIT_CONDITIONAL** |
| `volume_24h_usdt` | scanner (trailing 288 bars) | 5m | scanner filter/rank | `<= decision` | PIT_SAFE |
| `last_price` | scanner (newest visible close) | 5m | scanner + market_context | `<= decision` | PIT_SAFE |
| `atr_pct` | scanner | 5m | scanner atr filter | `<= decision` | PIT_SAFE |
| `scanner_timestamp_ms` | `scanner._now_ms` (wall clock) | — | trace metadata only | — | **PIT_CONDITIONAL** |
| `strategy_admission_ledger` | `config/strategy_admission.json` | — | router ordering + decision class | static prior | **PIT_CONDITIONAL** |
| `experience_memory` | `performance.json` | — | bounded selection priority (±0.25) | after outcome horizon | PIT_SAFE |
| `outcomes` | OutcomeEvaluator | — | experience + calibration | `close > decision + horizon` | PIT_SAFE |
| `risk_config`, `cost_model_v3` | frozen YAML / constants | — | RiskManager, CostEngine | static | PIT_SAFE |
| `funding` | COST_MODEL_V3 | — | CostEngine | constant 0.0 | NOT_APPLICABLE |
| `htf_pit_helper` | orphan module | — | none | — | NOT_RUNTIME_REACHABLE |
| orderbook / tick / sentiment / macro | — | — | none | — | NOT_RUNTIME_REACHABLE |

## The three conditional items (audited, not assumed)

1. **`spread_bps`** — the frozen dataset has no historical spread series, so the
   replay uses the `COST_MODEL_V3` majors default (1.0 bps) and records it as
   `knowledge = ESTIMATED`. It is never treated as observed zero. PIT-safe in
   semantics (a constant), but not an observed market value.
2. **`scanner_timestamp_ms`** — the scanner stamps snapshots with the **wall
   clock**, not the replay clock. The runtime clips it with
   `decision_ts = min(snap_ts, session_started_ms)` and selects bars by
   `closed_bar_slice`, so it can never pull future data — but it is a semantics
   gap worth naming: in the replay the stamp is ~2026-10 while decisions are
   ~2026-02..06. It is metadata in the trace; no decision field derives from it.
3. **`strategy_admission_ledger`** — a frozen **pre-registered prior**. No
   runtime code writes it, and each edge value is a per-strategy constant (not
   per-decision market data). BUT its declared calibration period
   (`W1-W7, 2026-03-01..2026-09-24`) extends **beyond** the RFC-010 replay
   decisions (`W1-W4`), so the baseline is **in-sample w.r.t. the prior**. This
   is a **P1** finding — see [`LEDGER_REGIME_PIT_AUDIT.json`](../../reports/data-integrity/LEDGER_REGIME_PIT_AUDIT.json).

## Summary

```
total sources          15
PIT_SAFE                7
PIT_CONDITIONAL         3
PIT_UNSAFE              0
UNKNOWN                 0
NOT_RUNTIME_REACHABLE   4
NOT_APPLICABLE          1
```

No `PIT_UNSAFE` and no `UNKNOWN` source is runtime-reachable. The one open
temporal finding is the ledger prior's in-sample calibration window (P1).
