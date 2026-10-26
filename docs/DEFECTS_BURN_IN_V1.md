# DEFECTS — PAPER-BURN-IN-V1

| DEF-ID | Severity | Observed at | Symptom | Root cause | Fix | Tests | Status |
| --- | --- | --- | --- | --- | --- | --- | --- |
| DEF-101 | P1 | STAGE 2 (cycles ~60+) | risk_state.trades_today=278 / daily_pnl=+980.46 with 4 real fills; 764 vetoes "Daily trade limit (20)" | reconcile_session returned FULL closed-trade ledger each session; runner re-fed it into RiskManager (cumulative double-count) | d370638: PaperExecutionSummary.new_closed_trades delta + report cursor; restored ledgers pre-marked; runner forwards delta only | test_reconcile_session_feeds_only_delta_to_risk | FIXED_AND_VERIFIED (55 post-fix cycles: trades_today==fills) |
| DEF-100 | P2 | instrument wiring (pre-burn-in) | UnboundLocalError in report paths while adding burn-in hook | str_replace removed local declarations | 0d0b76e (declarations restored) | existing report-event tests | FIXED (never reached a live cycle) |

P0 open: 0 · P1 open: 0 · P2 open: 0 · P3 deferred: per-stage latency breakdown, CPU/memory sampling.
