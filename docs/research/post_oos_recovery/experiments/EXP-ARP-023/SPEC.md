# EXP-ARP-023 — SPEC (pre-registered BEFORE any result)

## Identity

- experiment_id: `EXP-ARP-023`
- strategy_id: `H-MKTNEUTRAL-RELVAL-001` (**NEW mechanism** — not an EXP-ARP-008,
  EXP-ARP-016, EXP-ARP-017 or EXP-ARP-021 variant)
- arm: `PROJECT_DERIVED_VARIANT`
- mechanism family: **market-neutral relative value (dollar-neutral + beta-neutral
  cross-sectional long/short)**
- grounding: the frozen `ARP-006-UNIVERSE-v1` PIT universe and the daily corpus
  already support a cross-sectional *rank*; `research/diversified/xsec.py` and
  `research/diversified/analytics.py` carry the ranking and regime machinery. What
  does **not** yet exist is a neutral (two-sided) book or any short-leg cost model
  (`WP-PAIR-INFRA-001` records the execution/borrow gap). This experiments with the
  *relative-value spread* itself, not with a directional forecast.

## Why this is NOT a variant of the rejected long-only family

The ARP-006/007/011/012 verdicts (`NEG-006-02`, `NEG-006-05`, `NEG-006-08`,
ARP-012 `BETA_TIMING_ONLY`) all reduce to **crypto beta**: every long-only
cross-sectional configuration tested so far is positive mostly in BULL and carries
a portfolio beta of order 1. A message ordering for a re-run requires
`NEW_HYPOTHESIS + NEW_EXPERIMENT_ID` **and a documented material difference**
(`NEGATIVE_KNOWLEDGE.md`). The material differences here are:

- vs `EXP-ARP-008` — no time-series rule on one asset; the object is a
  cross-sectional portfolio.
- vs `EXP-ARP-016` (xsec momentum, long-only) / `EXP-ARP-017` (xsec reversal,
  long-only) / `EXP-ARP-021` (xsec risk-adjusted relative strength, long-only) —
  the book is **two-sided and neutralised**: `Σw = 0` (dollar-neutral) with a
  beta-neutrality target, so the return is a *relative-value spread*, not a
  directional exposure. No previously tested configuration is being re-run
  identically; the long-only results are treated as **no prior evidence** for or
  against this variant.

## Rules (frozen, a priori)

1. **Score (PIT only).** At the close of day `t`, for each asset `i` in the PIT
   eligible universe compute the trailing log return over `formation_days = 30`
   closed bars, `r_i = log(close_i,t / close_i,t-30)`. The frozen **relative-value
   score is the reversal sign**, `score_i = -r_i` (cheapness relative to peers).
   Rank all eligible names by `score_i` descending. Read closed bars only; a name
   with fewer than `formation_days + 1` closed bars is ineligible (fail closed).
2. **Eligible universe.** The PIT-safe `DynamicAssetUniverse` snapshot
   (`ARP-006-UNIVERSE-v1`: listing time, min history, liquidity floor, staleness,
   gap and synchronisation rules unchanged). Require `members >= min_members = 20`
   so a genuine cross-section exists; otherwise the rebalance is skipped.
3. **Book (dollar-neutral).** Long the top `top_k = 10` names by `score`, short the
   bottom `top_k = 10` names by `score`, equal **notional** within each leg. Hence
   `Σw = 0` and gross exposure `= 2.0 × notional`. There is no net directional
   position by construction.
4. **Beta-neutral overlay.** Estimate each held name's beta to `BTCUSDT` over
   `beta_window_days = 60` closed daily returns ending at `t` (through-origin OLS
   slope). The book beta is `β_book = Σ w_i β_i`. **Fail closed**: if
   `|β_book| > beta_tolerance = 0.10`, the rebalance is **not** taken and the book
   goes flat for that period. The realized `β_book` is a **mandatory reported
   metric** at every rebalance; `HEDGED` may never be asserted without it.
5. **Rebalance / hold.** Rebalance every `rebalance_days = 7` days at the UTC
   close; act at the **next** open. A name leaves the book when it drops out of
   its tail at a rebalance, or after `max_hold_days = 21`, whichever comes first.
   Mid-band members are held (no intra-week churn).
6. **Costs.** `COST_MODEL_V3` via the live `CostEngine` applied to **each leg**;
   the neutral book turns two legs per rotation (`2 × 23.559016994374947` bps of
   round-trip on the turned notional). Additionally the short leg accrues a
   **borrow/funding** cost that is **not observable in the 1d USDT corpus** — see
   the blocker below.
7. **Splits.** Frozen `SplitDefinition` `2019-01-01 · 2024-01-01 · 2024-01-01 ·
   2025-07-01 · 2026-03-01 · 2027-03-01`; OOS is the existing forward-only
   `HOLDOUT-ARP-019-FORWARD`, `UNTOUCHED`.

## Parameters (frozen, a priori — not selected from any result)

`formation_days=30`, `top_k=10`, `min_members=20`, `rebalance_days=7`,
`beta_window_days=60`, `beta_tolerance=0.10`, `max_hold_days=21`.

`formation_days = 30` is one calendar month, the standard cross-sectional reversal
horizon and the smallest window that yields a stable 60-day beta estimate; it is
**not** the 7-day horizon of the rejected `EXP-ARP-017` and was fixed before any
result. A pre-registered robustness grid is declared in the MANIFEST
(`robustness_grid`) so the frozen choice cannot later be read as cherry-picked.

## Short-leg blocker (fail closed — do NOT invent a cost)

The corpus contains **no funding-rate, borrow-rate or basis series**; only native
1d USDT spot bars. Therefore:

- `SHORT_LEG_COST_STATUS = EXTERNAL_DATA_REQUIRED`.
- `assumed_borrow_bps_per_day = null`. **A zero (or guessed) borrow cost is
  forbidden**; any run that assumes one is invalid.
- The primary construction is therefore `IMPLEMENTATION_BLOCKED_PENDING_SHORT_LEG_COST`
  until a borrow/funding series is sourced. **No DEV execution is performed in
  this phase.** A non-promotable **gross-spread screen** (long/short spread PnL
  *before* borrow) may only be reported as `SHORT_LEG_UNCOSTED` and can never
  promote; it exists solely to locate whether any signal survives costing at all.

## Baselines / controls (frozen)

`NO_TRADE`; always-long same-basket (the beta reference); the naive dollar-neutral
BTC/ETH 1:1 pair with no ranking; random-rank long/short at fixed seeds; and a
**long-only top-k** run of the *same* score to isolate how much of the result is
the short leg (i.e. relative value) versus long beta.

## Metrics (mandatory)

Net/gross spread in bps of the book notional; per-leg costs; borrow/funding (or
`UNCOSTED`); realized `β_book` per rebalance and its distribution; turnover;
residual net exposure (must be ≈ 0); profit factor (bps-space, per
`DEF-METRIC-PROFIT-FACTOR-001`); per-position and portfolio net return (per
`DEF-METRIC-EXPECTANCY-001`); PnL drawdown of reference notional **and** a true
mark-to-market equity drawdown; concentration by name and period; and the
**effective number of independent rebalances** (`ESS`) with a block-bootstrap CI.

## Kill criteria (frozen)

- `REJECT_NO_EDGE` — DEV gross spread ≤ 0.
- `REJECT_COSTS` — DEV net ≤ 0 after **two-leg** cost **and** borrow.
- `REJECT_BETA` — portfolio `|β_book|` not distinguishable from 0, so neutrality is
  not established (the mechanism collapsed back to beta).
- `REJECT_INSUFFICIENT_SAMPLE` — DEV independent rebalances `< 40` or VALIDATION
  `< 15` (`ESS` is the binding constraint per ARP-012 §30).
- `REJECT_FRAGILE` — a single name or trade `> 50 %` of positive DEV net, or one
  period `> 60 %`.
- `REJECT_PIT` — any look-ahead in the score, the beta window or the fills.
- `REJECT_VALIDATION` — VALIDATION net `≤ 0`.
- Precondition (not a kill): `REJECT_SHORT_LEG_UNCOSTED` — any promotable result
  computed without an observed borrow/funding series is invalid.

## Promotion gate (frozen)

Positive net DEV **AND** positive net VALIDATION **AND** two-leg cost PASS **AND**
borrow observed **AND** robustness PASS **AND** PIT PASS **AND** contract PASS
**AND** sample sufficient **AND** `|β_book|` consistent with 0 **AND** concentration
acceptable **AND** builder ≠ verifier.

## Status

`PREREGISTERED_NOT_IMPLEMENTED`; `SHORT_LEG_DATA_BLOCKED`
(`EXTERNAL_DATA_REQUIRED`). **No profitability is asserted or implied.**
OOS **LOCKED**.
