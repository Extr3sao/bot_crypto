# DEMO-PAPER-01 Baseline

Date: 2026-09-05

## Repository authority

- Current HEAD: `a38e11eb7f894df2df27630a3ab7673b40a82f0a`
- MA-4 implementation authority reachable: `b730ede14b4e925978cd8790da2bafb58a11876f`
- MA-4 certification record reachable: `cdf0714b903435cf3e9bb652c0643912ccd51489`
- Certification tooling authority: `0c350b56d597b70cef496ff4f65364637dbc4a3d`
- Working tree: pre-existing untracked `.agentic-backup/` and `.worktrees/`; no tracked modifications were made for this baseline.

## Existing behavior

- `scripts/start_paper_trading.py` is the current paper entrypoint.
- Default provider is `fake`; `ccxt` is explicit and read-only market-data wiring.
- Paper runtime refuses non-`paper` mode.
- Existing paper integration tests and MA suites: `224 passed` for the baseline command:

```bash
uv run pytest -q tests/unit/multi_agent tests/unit/paper tests/integration/test_paper_e2e_001.py tests/integration/test_paper_e2e_002.py tests/integration/test_paper_e2e_003.py
```

- Existing paper path is `AssetContext → StrategyRouter → AlphaFamily → CandidatePortfolio → RiskManager → PaperBroker`, but it does not consume MA-3 DebateReports or MA-4 DecisionPackages.
- No current reachable dashboard server or SSE implementation was found under `src/trading_bot/web` or `src/trading_bot/paper_dashboard`.
- Existing `PaperBroker` owns simulated positions, reconciliation checks, closed trades, equity, fees/slippage, and realized PnL.
- Existing `PaperSessionRunner`/`PaperOrchestrator` own paper lifecycle and report hooks.

## Baseline tooling

- Generic pre-repair closure script reports unresolved static-analysis findings; this is known certification-tooling debt and will not be used as a substitute for the corrected closure tool in the implementation checkout.
- Existing full repository regression has the documented unrelated `binance` versus `bybit` failure.

## Scope decision

Implement a thin DEMO-PAPER-01 orchestration surface that reuses certified MA-2/3/4 artifacts and existing paper/risk/broker authorities. Do not modify certified MA-4 runtime behavior, risk sizing, broker accounting, or live configuration.
