# RESEARCH-EXPANSION-V1 — Strategy Candidates (§23)

Every idea below is a `STRATEGY_CANDIDATE` only. Pipeline for each:
`IDEA → SPEC → PRE-REGISTER → IMPLEMENT → TEST → BACKTEST → ROBUSTNESS → OOS → MULTI-REGIME → PAPER`.
**No candidate enters PAPER automatically**; none may touch POC01 or the certified thresholds.

| Candidate | Source pattern | IDEA (one line) | Why plausible | Authority risk | Preliminary decision |
| --- | --- | --- | --- | --- | --- |
| STRATEGY_CANDIDATE-01 | EDGE-RESEARCH-002 H-A | 5m execution gated by 15m+1h closed-bucket trend alignment | already pre-registered; execution pending new-data gate | none (own rules) | KEEP_PRE_REGISTERED (do not duplicate) |
| STRATEGY_CANDIDATE-02 | EDGE-RESEARCH-002 H-B..H-F | vol-bucket, mean-rev fade, pullback, cross-sectional RS, session gates | already pre-registered H-D/H-E/H-F etc. | none | KEEP_PRE_REGISTERED |
| STRATEGY_CANDIDATE-03 | Freqtrade protections (SRC-001) | cooldown / stoplookback-style post-loss guards as pre-registered gates | proven community pattern; complements risk manager without touching sizing | must not alter RiskManager authority — gate proposals only | ADOPT_P1 → SPEC next checkpoint |
| STRATEGY_CANDIDATE-04 | Jesse/Nautilus parity patterns (SRC-003/004) | backtest-live parity harness as a promotion gate before any PAPER | closes TEST_TARGET==RUNTIME_TARGET for strategies | none (evaluation only) | ADOPT_P0 (pattern) |
| STRATEGY_CANDIDATE-05 | Qlib/RD-Agent (SRC-006/007) | rolling walk-forward retrain evaluation harness for future ML candidates | fills robustness/OOS gap in pipeline | keep LLM out of runtime decisions | ADOPT_P1 (research plane) |
| STRATEGY_CANDIDATE-06 | López de Prado meta-labeling (SRC-010) | meta-label our existing proposals (trade/no-trade filter learned from confirmed data only) | strong published lineage; uses our confirmed windows | training data must exclude consumed windows; never legacy | ADOPT_P1 → SPEC after confirmation data exists |
| STRATEGY_CANDIDATE-07 | vectorbt robustness surfaces (SRC-008) | neighborhood-robustness report for FROZEN candidates only | visualizes parameter fragility without re-tuning | forbidden for discovery sweeps | EXPERIMENT (research plane) |
| STRATEGY_CANDIDATE-08 | ML4T purged CV (SRC-009/010) | purged/embargoed CV as the default cross-validation for any future ML spec | prevents leakage class-wide | none | ADOPT_P0 (pattern) |

## Non-interference statement (§24)

EDGE-RESEARCH-002 stays intact on `feat/edge-research-002` (2089fc6): hypotheses
H-A..H-F remain frozen with their committed rules; they execute only when ≥6h of new
closed-candle time exists after 2026-09-06T15:15Z, per their own gates. This branch
neither absorbs nor retunes them. STRATEGY_CANDIDATE-01/02 merely reference their
existence — no copies, no re-registrations.
