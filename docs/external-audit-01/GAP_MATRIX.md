# GAP MATRIX — EXTERNAL-AUDIT-RECONCILIATION-01

Checkpoint: EXTERNAL-AUDIT-RECONCILIATION-01
Audited HEAD: `a282fcca2098e3623c50b3c1033ef75e30337659` (branch `feat/ma-2-specialist-opportunity-swarm`)
Method: every external claim re-audited at HEAD with local source + runtime evidence.
Classification legend: `PRESENT_AND_SUFFICIENT` | `PRESENT_BUT_INCOMPLETE` | `ABSENT` | `NOT_RUNTIME_REACHABLE` | `NOT_APPLICABLE`

Rule honored: **no capability classified PRESENT_AND_SUFFICIENT was re-implemented.**

| # | Capability | CLAIM (external audit) | SOURCE | LOCAL_SOURCE (verified at HEAD) | RUNTIME_EVIDENCE | DECISION / CLASS |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | Stable TradeIntent identity | execution lacks deterministic immutable intent id | external audit gap list | `src/trading_bot/execution/idempotency.py` (`IdempotencyGuard` tracks sent cloids); `src/trading_bot/market_data/exchange_connector.py:566` `cid = client_order_id or str(uuid.uuid4())`; `grep TradeIntent|intent_id` → 0 matches | No `TradeIntent` type exists; connector cloid defaults to random UUID4 → same economic intent retried can mint a new client identity unless caller reuses it | **CONFIRMED GAP → ABSENT**. Implemented in EXECUTION-RELIABILITY-01 (`execution/intent.py`) |
| 2 | Execution journal | no durable canonical execution states | external audit gap list | `src/trading_bot/paper/trade_journal.py` (paper trade records, audit trail); `src/trading_bot/observability/journal.py`; no state machine `CREATED/SUBMITTING/ACK_UNKNOWN/...` anywhere (grep → 0) | Paper journal exists and is auditable, but no append-only execution state-transition journal with canonical states | **PRESENT_BUT_INCOMPLETE**. Journal state machine added in EXECUTION-RELIABILITY-01 (`execution/journal.py`); paper trade journal NOT touched (POC01 frozen) |
| 3 | Ambiguous ACK recovery | timeout-after-submit treated as safe retry | external audit gap list | grep `ACK_UNKNOWN` → 0 matches; `paper_cycle.py:295` rejects duplicates pre-submit only (`is_duplicate(cloid)`) | No timeout→ACK_UNKNOWN→query-venue flow exists | **CONFIRMED GAP → ABSENT**. Implemented (`execution/intent.py` recovery flow) |
| 4 | Fill idempotency | duplicate fills double-count | external audit gap list | `PaperBroker` applies fills internally (single-owner fills, no venue duplicates possible); `market_data/types.py` `OrderResult.client_order_id` propagated; no venue fill-identity dedup layer | In paper runtime fills are broker-internal (cannot duplicate); live path has no fill-idempotency layer | **PRESENT_BUT_INCOMPLETE** (paper: sufficient; live adapter path: absent). Fill dedup implemented (`execution/intent.py::FillLedger`) |
| 5 | Cancellation confirmation | cancel request sent ⇒ assumed cancelled | external audit gap list | `market_data/exchange_connector.py:616 cancel_order`, `bitunix*.py cancel_order` exist; grep `CANCEL_PENDING` → 0 | Adapters expose cancel; no CANCEL_PENDING→CANCELLED confirmation state machine | **CONFIRMED GAP → ABSENT** (execution layer). Implemented (`execution/journal.py` states + intent flow) |
| 6 | Orphan detection | missing | external audit gap list | `src/trading_bot/paper/reconciliation.py:72-101` — `orphaned_in_broker` / `orphaned_in_journal`, policy `CLOSE_ORPHANED`, event `reconciliation.closed_orphan` | Tests: `tests/unit/paper/` + startup recovery tests exercise orphan close | **PRESENT_AND_SUFFICIENT (paper runtime)** — not re-implemented |
| 7 | Startup reconciliation | missing | external audit gap list | `src/trading_bot/paper/startup_recovery.py` (`compute_orphan_reconciliation_close`, `startup_recovery.orphan_closed`); `paper/reconciliation.py` `StartupReconciler` | Report `startup_reconciliation_report.json` produced; fail-closed semantics in recovery module | **PRESENT_AND_SUFFICIENT (paper runtime)** — not re-implemented. Live-path EXECUTION_READY gate added as design note in EXECUTION-RELIABILITY-01 (does not enable live) |
| 8 | Feed dead-man | stale feed not blocked | external audit gap list | `domain/enums/risk.py:43 STALE_SNAPSHOT` (risk reason exists); `research/router_gates.py` + `research/strategy_router.py:126` reject stale context (`stale_context` no-trade); `market_data/test_fake_freshness.py` freshness tests; no execution-layer dead-man blocking new entries on stale feed | Research layer refuses stale context; execution layer has no feed-staleness gate | **PRESENT_BUT_INCOMPLETE**. Implemented (`execution/feed_guard.py`) without touching strategy logic |
| 9 | StrategyHealth / lifecycle | missing lifecycle | external audit gap list | `src/trading_bot/strategies/` — `Strategy` Protocol, `StrategyConfig`, pipeline; `paper/strategy_selector.py` config registry; grep `quarantine|retire|lifecycle` → 0 in strategies/ | No health lifecycle states exist | **ABSENT → RFC only** (`RFC-STRATEGY-HEALTH-01`) per directive 13 |
| 10 | Statistical significance / Sharpe bootstrap CI | missing | external audit gap list | `backtesting/engine.py` `_compute_sharpe` (point estimate), `walk_forward_reports.py` (cross-fold mean/std/min/max aggregates), Monte Carlo not found (grep → 0 in backtesting), no bootstrap/permutation | Walk-forward aggregate reports exist; no CI / significance tests | **PRESENT_BUT_INCOMPLETE** (walk-forward present; bootstrap CI / P(Sharpe>0) / permutation ABSENT). Gaps recorded, mapped to StrategyAdmissionVerifier (directive 15) |
| 11 | correlation_cluster uses static 0.85/0.55 | claimed defect | external audit claim | grep `0.85` in `src/` at HEAD → 0 matches; grep `0.55` → only `charting/local_renderer.py:84` (candle width layout, unrelated); `domain/enums/risk.py:29 CORRELATION_CLUSTER` enum declared but **no implementation references it** (single match); `paper/candidate_portfolio.py:42` uses `correlation_group` label (e.g. "crypto-beta"), not numeric constants; same verified at audited commits `3c274cc` and `bb46c92` via `git grep` | No static correlation risk factor exists in runtime; `CORRELATION_CLUSTER` reason is dead enum | **CLAIM REJECTED → DEF-CORR-001 NOT CONFIRMED**. Classification: `NOT_RUNTIME_REACHABLE` (declared enum, unimplemented). Correlation-regime design still recorded as RFC (directive 14) |
| 12 | Portfolio intelligence | missing | external audit gap list | `src/trading_bot/paper/portfolio_manager.py` (position sizing, exposure limits, max positions, daily loss, drawdown protection); `paper/candidate_portfolio.py` (consolidation with correlation_group labels); `src/trading_bot/portfolio/` = `__init__.py` only | PortfolioManager enforces limits in paper runtime | **PRESENT_BUT_INCOMPLETE** (sizing/exposure present; real rolling correlation absent — see #11) |
| 13 | Exchange adapter conformance | no unified conformance | external audit gap list | `market_data/types.py` Protocol (`create_order`/`cancel_order`/`client_order_id` propagation); `exchange_connector.py` (idempotent retries via tenacity, sandbox, whitelist); `bitunix.py:425-590` loud-fail on missing client_order_id correlation; per-adapter tests in `tests/unit/market_data/` (7 files) | Adapter contract partially pinned by tests; no unified conformance suite (reconnect, reconciliation, stale behavior, timeouts, rate limits, error normalization) | **PRESENT_BUT_INCOMPLETE** → RFC (`RFC-EXCHANGE-CONFORMANCE-01`), directive 16 |

## Summary counts

- PRESENT_AND_SUFFICIENT: 2 (#6, #7 — paper runtime)
- PRESENT_BUT_INCOMPLETE: 6 (#2, #4, #8, #10, #12, #13)
- ABSENT (confirmed gaps): 4 (#1, #3, #5, #9)
- NOT_RUNTIME_REACHABLE: 1 (#11)
- Claims REJECTED: 1 (static correlation constants)

## POC01 isolation statement

None of the audited/changed capabilities touch: strategies, RiskManager,
MetaRanker, MA3, MA4, PaperBroker, fees, slippage, assets, or the frozen
`paper-observation-01` campaign state. All new execution-reliability code is
new-module-only (`src/trading_bot/execution/`) and is not wired into the POC01
demo runtime in this checkpoint.
