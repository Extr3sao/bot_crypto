# RFC-CORRELATION-REGIME-01 — Rolling Correlation Regime

Status: **DRAFT** (design only; no runtime replacement in this checkpoint)
Checkpoint: EXTERNAL-AUDIT-RECONCILIATION-01
Audited HEAD: `a282fcc`
Related: `DEF-CORR-001-REJECTED.md` (static-correlation claim rejected)

## 1. Problem

`domain/enums/risk.py` declares `CORRELATION_CLUSTER` as a risk reason, but no
implementation computes or consumes correlations. `paper/candidate_portfolio.py`
carries a `correlation_group` label. There is no real rolling correlation
anywhere. The portfolio cannot reason about actual cross-asset co-movement.

## 2. Design

Pipeline (all causal, PIT-aligned):

```
aligned PIT returns
  -> rolling correlation (window W)
  -> causal smoothing (only past data)
  -> hysteresis (enter/exit thresholds)
  -> correlation regime
```

- **Aligned PIT returns**: returns aligned by point-in-time bar close; no
  lookahead (same contract as `research/` staleness gates).
- **Rolling correlation**: Pearson correlation over a rolling window per pair.
- **Causal smoothing**: EMA over the rolling correlation series using only
  values at or before `t`.
- **Hysteresis**: regime flips require crossing `enter_threshold` (e.g. 0.85)
  upward and `exit_threshold` (e.g. 0.70) downward, preventing flapping.
- **Correlation regime**: discrete label per pair/cluster: `LOW / NORMAL / ELEVATED / CRISIS`.

## 3. Causal invariant (required)

**Future data changes -> past state unchanged.** For any timestamp `t`, the
regime value at `t` depends only on bars with close <= `t`. Property test
required: mutating bars after `t` must not change regime history up to `t`.

## 4. Non-goals for this checkpoint

- Do NOT replace runtime correlation during active POC01 (campaign frozen).
- No wiring into `RiskManager` / `candidate_portfolio` yet.
- Implementation deferred to a dedicated checkpoint.

## 5. Proposed module (future)

`src/trading_bot/portfolio/correlation_regime.py`:

```
CorrelationRegime(enum): LOW / NORMAL / ELEVATED / CRISIS
CorrelationRegimeConfig: window, smoothing_span, enter/exit thresholds
compute_rolling_correlation(returns: DataFrame) -> DataFrame (causal)
classify_regime(smoothed_corr: Series, config) -> CorrelationRegime (hysteresis)
```

## 6. Acceptance criteria (for the future implementation checkpoint)

1. Causal-invariant property test passes (mutate future bars -> past regime unchanged).
2. Deterministic: same input -> same regime series.
3. No import from POC01 demo runtime; POC01 untouched.
4. Coverage >= 90% on the new module.