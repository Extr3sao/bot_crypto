# G-7 — Final report

**Verdict:** `G7_BLOCKED_NO_ELIGIBLE_STRATEGY`  
**Safety:** `PAPER_ONLY=true` · `LIVE_NO_GO` · `PRODUCTION_READY=false` · `FALSE_SUCCESS=0`  
**Implementation:** `5c76060f` (includes `f3a83569`)  
**Independent verification:** 18/18 checks, `FALSE_SUCCESS=0` (commit `41d34c81`)  
**Evidence:** `docs/audit/runs/run-20261025T173625Z-G-7/`

## IMPLEMENTADO

- `src/trading_bot/market_data/public_rest.py`: read-only Binance public
  adapter with an endpoint allowlist, no credentials, request journal and
  forming-candle removal. `ReplayMarketDataSource` serves a pinned capture and
  labels it `HISTORICAL_REPLAY` or `FORWARD`.
- `src/trading_bot/market_data/real_data_validation.py`: fail-closed PIT
  validation (`STALE`, `GAP`, `FUTURE`, `DUPLICATE`, `OUT_OF_ORDER`,
  `BAD_OHLCV`, `INCOMPLETE`, `EMPTY`) with a content hash.
- `src/trading_bot/paper/eligibility.py`: ledger-backed eligibility report
  through the real `StrategyRegistry` and `StrategyRouter`.
- `scripts/audit/g7_real_paper.py`: replay + forward campaign through
  `build_cycle_engine → PaperOrchestrator → PaperSessionRunner →
  PaperCycleEngine → DurablePaperBroker → StartupReconcilerV4`.
- `scripts/audit/verify_g7.py`: independent clean-export verifier.
- `scripts/start_paper_trading.py`: `--provider public` and `--data-audit`.

## EJECUTADO

- Deterministic replay of **500 real 5m bars × 3 symbols** at
  `2026-10-25T16:55Z`, `17:00Z`, `17:05Z`, plus a restart at `17:05Z`.
- One **forward** observation against the live public provider at
  `2026-10-25T17:19:46.823Z`.
- 15 contexts, 15 explicit `NO_TRADE:no_strategy_passed_gates`, 0 signals,
  0 orders, 0 broker `execute_signal` calls.
- 6/6 dangerous-data scenarios blocked; provider outage contained with 0
  orders.
- 75 focused tests passed.

## VERIFICADO

- Real provider, capture hash, no look-ahead, replay/forward labels, explicit
  decisions, durable restart, invalid-data blocking, provider containment,
  unchanged LIVE gate and hot stop, and the full focused test set.
- The independent verifier (`verify_g7.py`) runs from a `git archive` export
  and re-derives the checks rather than trusting the builder: **18/18**,
  `G7_BLOCKED_NO_ELIGIBLE_STRATEGY`, `FALSE_SUCCESS=0`, 75 tests passed inside
  the export, and a separate forward probe with 0 orders.
- The verifier overwrites none of the builder's claims: it re-runs the replay
  twice from the committed capture, checks the capture hash and PIT rules,
  compares the deterministic projection, and checks that the LIVE gate and
  hot stop are byte-identical.

## NO VERIFICADO / BLOQUEADO

- **No PAPER_TRADE.** The committed `config/strategy_admission.json` admits
  **0 of 24** strategies (`COST_KILLED=7`, `NO_GROSS_EDGE=17`,
  `PAPER_CANDIDATE=0`, `PAPER_ACTIVE=0`). Every router verdict is
  `NOT_APPLICABLE`.
- G-7 condition 3 (an existing eligible strategy really evaluated) therefore
  **fails**. G-7 is `BLOCKED`, not `PASS`.
- `paper_cycle` and `autonomous.decision` remain two engines.
- The campaign covers one 41 h 40 m capture and one forward instant, not a
  24 h continuous session.

## BLOQUEOS

The admission ledger is the sole authority and it admits nothing. Making a
trade happen would require editing the ledger, promoting a rejected strategy
or bypassing the router. None was done. The blocker is research evidence, not
runtime code.

## COMMITS

- Implementation: `f3a83569` + `5c76060f` (summary fix)
- Verification: `41d34c81`, 18/18 checks; verdict and count are in
  `verification.json`.
- Evidence: the commit containing this run directory. See
  `git log -- docs/audit/runs/run-20261025T173625Z-G-7`.
- G-6 baseline: `d5e599ec`.

## SIGUIENTE OBJETIVO

Produce a strategy with measured positive net edge, promote it through the
committed admission pipeline, and repeat this same real-data replay + forward
campaign with `admitted_for_paper=true`. Only then can G-7 move from `BLOCKED`
to a verified `PAPER_TRADE` and a real close.

## RUTAS EXACTAS

```text
docs/audit/G-7.md
docs/audit/runtime_authority_map.md
docs/audit/runs/run-20261025T173625Z-G-7/RUN_REPORT.md
docs/audit/runs/run-20261025T173625Z-G-7/RUN_REPORT.json
docs/audit/runs/run-20261025T173625Z-G-7/REAL_MARKET_DATA_REPORT.md
docs/audit/runs/run-20261025T173625Z-G-7/STRATEGY_ELIGIBILITY_REPORT.md
docs/audit/runs/run-20261025T173625Z-G-7/PAPER_EXECUTION_REPORT.md
docs/audit/runs/run-20261025T173625Z-G-7/verification.json
docs/audit/runs/run-20261025T173625Z-G-7/FINAL_REPORT.md
```

## COMANDOS REPRODUCIBLES

```bash
# deterministic replay (no network)
uv run python scripts/audit/g7_real_paper.py \
  --out /tmp/g7-replay \
  --capture docs/audit/fixtures/g7_market_capture.json \
  --timeframe 5m --assets BTC,ETH,SOL --no-forward

# independent verification (clean export; add --forward for a live probe)
uv run python scripts/audit/verify_g7.py \
  --rev HEAD \
  --run-dir docs/audit/runs/run-20261025T173625Z-G-7 \
  --out docs/audit/runs/run-20261025T173625Z-G-7/verification.json \
  --forward
```
