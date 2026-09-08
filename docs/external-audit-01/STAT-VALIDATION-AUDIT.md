# STAT-VALIDATION AUDIT — EXTERNAL-AUDIT-RECONCILIATION-01

Checkpoint: EXTERNAL-AUDIT-RECONCILIATION-01
Audited HEAD: `a282fcc`
Directive 15: confirm what exists; do not duplicate; record gaps only.

## Confirmed present at HEAD

| Capability | Local source | Status |
| --- | --- | --- |
| Walk-forward validation | `src/trading_bot/backtesting/walk_forward_reports.py` (`WalkForwardAggregateReport`, `build_walk_forward_aggregate`, per-fold `FoldReport`), `backtesting/reports.py`; config gates `config/runtime.py:124 enable_walk_forward`, `config/strategies.py:67 require_walk_forward_validation` | PRESENT (ADR-0007 pins walk-forward as pre-condition) |
| Sharpe (point estimate) | `backtesting/engine.py::_compute_sharpe` (annualized, `periods_per_year` pinned) + Sortino, Calmar, CAGR, max drawdown, PF, expectancy | PRESENT |
| Cross-fold aggregates | `walk_forward_reports.py` — mean/std/min/max per metric across folds | PRESENT |

## Not found at HEAD (grep-verified)

| Capability | Search | Result |
| --- | --- | --- |
| Monte Carlo simulation | `monte.?carlo` in `src/trading_bot/backtesting/` | 0 matches |
| Bootstrap / stress testing | `bootstrap` | 0 matches in backtesting |
| Permutation / significance tests | `permutation|significan` | 0 matches |

## Gaps to record (do not implement in this checkpoint)

1. **Sharpe bootstrap CI** — no confidence interval on Sharpe. Point estimate only.
2. **P(Sharpe > 0)** — no probabilistic Sharpe estimate (e.g. via bootstrap or
   probabilistic Sharpe ratio).
3. **Permutation/significance test** — no randomization test distinguishing
   strategy edge from luck.

## Mapping into StrategyAdmissionVerifier (next checkpoint)

The three gaps map cleanly onto the admission path
(`src/trading_bot/admission/` per ADMISSION-FOUNDATION-01, and
`config/strategies.py: require_walk_forward_validation`):

- `StrategyAdmissionVerifier` gains optional stat gates:
  - `sharpe_bootstrap_ci_lower >= threshold`
  - `prob_sharpe_positive >= threshold` (e.g. 0.95)
  - `permutation_p_value <= threshold` (e.g. 0.05)
- Gates are additive and config-gated; existing admission behavior is the
  fallback when the new gates are disabled.
- Implementation may be the next checkpoint (`STAT_VALIDATION_01` in the
  checkpoint chain). No admission code was modified here.