# RUN_REPORT — DEMO-PAPER-01

- run_id: `DEMO-PAPER-01`
- executed_at: 2026-09-25 (this session)
- git commit: `5e6f963` · branch `main` · dirty state: NONE at run start (porcelain=0); session-defect fixes committed afterwards as separate commits (below)
- environment: Windows host, Python 3.11.15, uv 0.11.26, in-repo venv
- dataset/provider: `fake` (deterministic synthetic market data — no credentials, no network); provider contract identical to ccxt path (read-only `MarketDataSourceProtocol`)
- asset(s): BTC/USDT, ETH/USDT, SOL/USDT
- timeframe(s): 5m
- data fingerprints: per-context `sha256:` content fingerprints computed and carried by AssetContext (engine `_fingerprint` over the exact PIT bars); session logs capture cycle counters
- decision_time: per-bar decision timestamps from the scanner snapshots (session `7d104d14b0c747cc9b9883b6d2cc1f62`)
- runtime entrypoint: `scripts/start_paper_trading.py` (PAPER-only, refuses non-paper mode)
- agents invoked: 0 LLM calls (canonical path is deterministic; Asset Intelligence agents are feature/regime builders)
- strategies considered: 6 families in the deterministic map (ema_crossover, momentum, breakout, trend, mean_reversion, volatility)
- selected strategy: NONE — `signals_generated=0`
- rejected strategies: all six (no alpha produced from flat synthetic bars)
- TradeProposal: none produced (fail-closed at strategy stage with reason `no_alpha_in_direction:ANY` per symbol)
- evidence / counter-evidence: cycle rejections recorded per symbol in orchestrator status JSON (reproducible from `reports/runs/DEMO-PAPER-01-stdout.log`)
- decision: **NO_TRADE** (first-class, traversed the full pipeline)
- confidence: n/a (no proposal)
- risk result: not reached (0 proposals); risk gates proven separately in the TRADE leg
- paper order/fill: none this leg — TRADE leg evidence from the same engine: 3 orders, fills with slippage 1bp + commission 5bp, SL/TP closes, realized_pnl −1492.02 USDT (verifier `GATE-L5-10`)
- fees/cost assumptions: slippage_bps=1, commission_bps=5 (PaperBroker defaults, deterministic)
- reconciliation: in-session reconcile_session executed every cycle (equity identity holds: 10000 → 8507.98 on the TRADE leg = initial + Σ net pnl)
- portfolio state before/after: 10000.00 → 10000.00 (NO_TRADE leg); 10000.00 → 8507.98 (TRADE leg)
- errors: 0 · retries: 0 · latency: <1s per session · LLM calls: 0 · token/cost: 0

## Capture artifacts

- `reports/runs/DEMO-PAPER-01-stdout.log` (stdout+stderr, exit 0) — gitignored output dir by policy
- `docs/PAPER_L5_INDEPENDENT_VALIDATION_RUN_2026-09-25.md` — full verifier transcript (11/11) on this HEAD

## Determinism statement

Same HEAD + same seed/fake provider ⇒ same counters, same fingerprints, same decision. The verifier re-runs all adversarial paths deterministically. No LLM output participates, so bit-exact replay is trivially achievable for the current path (replay-by-run_id API remains deferred, P2).

## RUN_REPORT.json (machine-readable)

```json
{
  "run_id": "DEMO-PAPER-01",
  "git_commit": "5e6f963",
  "branch": "main",
  "worktree_dirty": false,
  "entrypoint": "scripts/start_paper_trading.py",
  "provider": "fake",
  "assets": ["BTC/USDT", "ETH/USDT", "SOL/USDT"],
  "timeframe": "5m",
  "sessions": 2,
  "decision": "NO_TRADE",
  "signals_generated": 0,
  "orders_created": 0,
  "risk_accepted": 0,
  "risk_rejected": 0,
  "router_invocations": 3,
  "router_no_trade": 0,
  "strategy_invocations": 3,
  "contexts_built": 3,
  "context_errors": 0,
  "rejections": [
    {"symbol": "BTC/USDT", "stage": "strategy", "reason": "no_alpha_in_direction:ANY"},
    {"symbol": "ETH/USDT", "stage": "strategy", "reason": "no_alpha_in_direction:ANY"},
    {"symbol": "SOL/USDT", "stage": "strategy", "reason": "no_alpha_in_direction:ANY"}
  ],
  "equity_before": 10000.0,
  "equity_after": 10000.0,
  "realized_pnl": 0.0,
  "llm_calls": 0,
  "trade_leg_evidence": {
    "source": "scripts/verify_l5_independent.py (same engine, deterministic data)",
    "orders_created": 3,
    "realized_pnl": -1492.02,
    "equity_after": 8507.98,
    "verifier_result": "11/11 PASS"
  },
  "temporal_integrity": "PASS (future-bar + stale-data adversarial executed)",
  "false_success": 0,
  "final_result": "NO_TRADE (valid first-class outcome); TRADE leg evidenced by verifier"
}
```
