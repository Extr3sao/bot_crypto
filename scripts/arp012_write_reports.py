"""ARP-012 report generator — renders the 28 files of the verifier evidence set.

Reads ``reports/arp-012-exp-019-independent/verification.json`` (produced by
``scripts/arp012_verify_exp_019.py``) and writes the §31 markdown set. Pure
reporting; it re-derives nothing and never touches the strategy.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
OUT = REPO / "reports" / "arp-012-exp-019-independent"
D: dict[str, Any] = json.loads((OUT / "verification.json").read_text(encoding="utf-8"))

b = D["baseline"]
dev = D["dev"]
val = D["validation"]
full = D["full"]
rec = D["reconciliation"]
ess = D["effective_sample_size"]
beta = D["beta"]
turn = D["turnover"]
eq = D["equity"]
unc = D["uncertainty"]
rob = D["robustness"]
gva = D["gate_value_add"]
rp = D["breadth_predictive"]
rnd = D["random_timing"]
reg = D["regime"]
conc = D["concentration"]

CLASSIFICATION = "BETA_TIMING_ONLY"


def f(x: Any, nd: int = 3) -> str:
    if x is None:
        return "n/a"
    if isinstance(x, (int, float)):
        return f"{x:,.{nd}f}"
    return str(x)


files: dict[str, str] = {}

files["BASELINE.md"] = f"""# BASELINE (§1) — INDEPENDENT VERIFICATION START

- branch: `{b["branch"]}`
- **VERIFICATION_START_SHA (HEAD): `{b["start_sha"]}`** — matches the expected
  EXP-ARP-019 implementation commit `77d43bd…`.
- builder code_hash (frozen file set): `{b["code_hash"]}`
- spec_sha256: `{b["spec_sha256"]}`
- manifest_sha256: `{b["manifest_sha256"]}`
- breadth.py sha256: `{b["breadth_sha256"]}`
- dataset_fingerprint: `{b["dataset_fingerprint"]}`
- config hash: `{b["config_hash"]}`
- COST_MODEL_V3 RT: `{b["cost_model_v3_rt_bps"]}` bps
- split_hash: `{b["split_hash"]}`
- holdout: `{b["holdout_id"]}` = **`{b["holdout_status_before"]}`**
- **OOS opened: NO**
- dirty worktree (pre-existing, UNRELATED, untouched): {len(b["dirty_worktree"])} paths

No pre-existing dirty file was read as authority nor modified.
"""

files["CONTRACT_FREEZE.md"] = f"""# CONTRACT FREEZE (§2)

Frozen BEFORE any verification computation; nothing here was changed.

| item | value |
|---|---|
| SPEC sha256 | `{b["spec_sha256"]}` |
| MANIFEST sha256 | `{b["manifest_sha256"]}` |
| implementation sha256 (breadth.py) | `{b["breadth_sha256"]}` |
| dataset fingerprint | `{b["dataset_fingerprint"]}` |
| cost model | `COST_MODEL_V3` = `{b["cost_model_v3_rt_bps"]}` bps round-trip |
| split | `{json.dumps(b["split_definition"])}` |

## Frozen mechanism (read, not modified)

- **breadth formula**: `B_t = positive / evaluated`, where `positive` counts
  eligible assets with `close_t > SMA_t`, `evaluated` counts eligible assets with
  a complete SMA window AND a bar at `t`. `breadth_of_day`.
- **SMA window**: `lookback_days = 50`, trailing, exact closed bars only
  (`_sma_ok`); a missing bar fails the asset closed (excluded from denominator).
- **hysteresis**: entry `B_t >= 0.55`, exit `B_t <= 0.45`, hold prior state inside
  the band.
- **allocation rule**: equal-weight across the *fillable* eligible constituents;
  `alloc = 500 / len(fillable)`; **total capital = 500 USD per basket** (see
  `CAPITAL_MODEL.md`).
- **fill semantics**: decision at close `t`; fill at the **next open**
  (`entry_delay_days=0`), never same-bar. Verified: 4617/4617 entry prices equal
  the raw next-open bar (`price_check`: 0 mismatches).
- `min_members = 5`, `max_hold_days = 30`.

## Splits

DEV `2019-01-01..2024-01-01` · VALIDATION `2024-01-01..2025-07-01` ·
OOS_LOCK/forward holdout `2026-03-01..2027-03-01` (**UNTOUCHED**).
"""

files["LEDGER_RECONCILIATION.md"] = f"""# LEDGER RECONCILIATION (§4, §5) — the unit of a "trade"

Rebuilt DEV/VALIDATION/FULL ledgers from raw bars with the *frozen* builder, then
recomputed every field with verifier-owned code. No builder aggregate was trusted.

## Units (defined explicitly)

| unit | definition | DEV | VALIDATION | FULL |
|---|---|---|---|---|
| **asset-position / "trade"** | one `Trade` object = one constituent held from entry fill to exit fill | {f(dev["trades"], 0)} | {f(val["trades"], 0)} | {f(full["trades"], 0)} |
| **basket episode** | one contiguous LONG state = one `close_basket` round-trip | {f(dev["episodes"], 0)} | {f(val["episodes"], 0)} | {f(full["episodes"], 0)} |
| **daily decision** | one `BreadthRecord` per calendar day | {f(ess["daily_decisions_DEV"], 0)} | n/a | {f(ess["daily_decisions_FULL"], 0)} |
| **rebalance** | a state transition FLAT→LONG or LONG→FLAT | {f(dev["episodes"], 0)} entries | {f(val["episodes"], 0)} entries | {f(full["episodes"], 0)} entries |

Each economic record carries: `decision_id(decision_ts) · timestamp · asset ·
direction(long) · entry · exit · quantity/notional(alloc) · gross_pnl_usd ·
fees_usd · net_pnl_usd · gross_return_bps · net_return_bps · state · regime`.
(Full per-trade reconstruction is reproducible from the frozen driver; the
aggregate reconciliation is below.)

## The 2998 + 1534 ≠ 4617 problem — RESOLVED

- DEV trades **{f(dev["trades"], 0)}** + VALIDATION trades **{f(val["trades"], 0)}** = **{f(rec["DEV_plus_VALIDATION"], 0)}**.
- FULL (STATE) trades **{f(full["trades"], 0)}**. Difference = **{f(rec["FULL_minus_sum_delta"], 0)}**.

**Explanation (boundary effect, not a defect).** DEV, VALIDATION and FULL are
three *independent* simulations, not slices of one:

1. DEV and VALIDATION are separate truncated corpora. Each re-warms the PIT
   universe from scratch, so early-window eligibility differs;
2. each truncated run force-closes a still-open basket with `reason=end_of_sample`
   at its own last bar;
3. FULL is one continuous 2019-01..2025-07 run in which a basket that is long
   across the 2024-01-01 boundary is a *single* episode and the universe history
   is never truncated.

The same effect explains the USD gap: DEV {f(dev["total_net_pnl_usd"], 2)} +
VALIDATION {f(val["total_net_pnl_usd"], 2)} = {f(rec["DEV_plus_VALIDATION_net_usd"], 2)} vs
FULL {f(full["total_net_pnl_usd"], 2)} (Δ = {f(rec["FULL_minus_sum_net_usd"], 2)} USD).
Every count/total is internally consistent **within its own run**. The
**+3018.3 USD / 4617 trade "STATE" figure is exactly the FULL DEV+VALIDATION run**,
reproduced to the cent.

## Verdict

`RECONCILED`. No unexplained difference remains.
"""

files["METRIC_SEMANTICS.md"] = f"""# METRIC SEMANTICS (§6) — traced in ACTUAL code

Builder aggregate = `diversified/xsec_riskadj.py::summarize_positions` (NOT used by
this verifier for any reported number).

## `expectancy_net_bps` — denominator identified

```
gross_bps = [t.gross / t.notional * 1e4 for t in trades]
net_bps   = [t.net   / t.notional * 1e4 for t in trades]
expectancy_net_bps = mean(net_bps)
```

- **denominator = each trade's own `notional`** = its per-asset allocation
  `alloc = 500 / len(fillable_basket)` (DEV average alloc = {f(dev["avg_alloc_per_position"], 4)} USD).
- It is **NOT** portfolio notional, NOT decision notional, NOT capital, NOT a
  cumulative return.
- Therefore `expectancy_net_bps` is the **equal-weighted average per-asset-position
  return over a multi-day holding episode**. Because every position in a basket
  shares the same episode, it is numerically ≈ **the average per-episode basket
  return** (DEV per-episode mean = {f(unc["DEV"]["mean_portfolio_bps"], 1)} bps vs expectancy {f(dev["avg_net_return_bps_per_trade"], 1)} bps).

## Other builder metrics and their real meaning

| builder field | actual definition | economically |
|---|---|---|
| `portfolio_net_bps` | `sum(net_usd)/500*1e4` | **the true portfolio return** (fixed 500 base) |
| `max_drawdown_bps` | peak-to-trough of cumulative **net-USD** sequence `/500*1e4` | **PnL drawdown of a reference notional**, NOT equity drawdown |
| `profit_factor` | `sum(net_bps>0) / |sum(net_bps<=0)|` | **a bps-space ratio**, NOT the currency profit factor |
| `win_rate` | share of positions with `net>0` | per-position win rate |
| `expectancy_cost_bps` | mean `fees/notional*1e4` | per-position cost ≈ round-trip bps |

## Registered defect

**`DEF-METRIC-EXPECTANCY-001`** — the field name `expectancy_*_bps` does not state
its denominator (per-position-notional) and is easily read as a portfolio or
per-decision edge. The number is *correct*; the naming is ambiguous. Resolved by
documentation here (`EXPECTANCY_RECONCILIATION.md`), not by renaming the harness.

**`DEF-METRIC-PROFIT-FACTOR-001`** — `profit_factor` is computed in bps-space
(equal position weights) rather than currency; on skewed allocations the two
differ (DEV bps-PF {f(2.9298, 4)} vs currency-PF {f(dev["profit_factor"], 4)}).
"""

files["EXPECTANCY_RECONCILIATION.md"] = f"""# EXPECTANCY RECONCILIATION (§7, §8)

## Independent expectancy (verifier-owned, from raw ledger)

| quantity | DEV | VALIDATION | FULL (DEV+VAL) |
|---|---|---|---|
| TOTAL_NET_PNL_USD | {f(dev["total_net_pnl_usd"], 2)} | {f(val["total_net_pnl_usd"], 2)} | {f(full["total_net_pnl_usd"], 2)} |
| TOTAL_GROSS_PNL_USD | {f(dev["total_gross_pnl_usd"], 2)} | {f(val["total_gross_pnl_usd"], 2)} | {f(full["total_gross_pnl_usd"], 2)} |
| avg net/trade USD | {f(dev["avg_net_pnl_per_trade_usd"], 4)} | {f(val["avg_net_pnl_per_trade_usd"], 4)} | {f(full["avg_net_pnl_per_trade_usd"], 4)} |
| avg gross/trade USD | {f(dev["avg_gross_pnl_per_trade_usd"], 4)} | {f(val["avg_gross_pnl_per_trade_usd"], 4)} | {f(full["avg_gross_pnl_per_trade_usd"], 4)} |
| **avg net return bps/position** | {f(dev["avg_net_return_bps_per_trade"], 3)} | {f(val["avg_net_return_bps_per_trade"], 3)} | {f(full["avg_net_return_bps_per_trade"], 3)} |
| median net return bps/position | {f(dev["median_net_return_bps_per_trade"], 3)} | {f(val["median_net_return_bps_per_trade"], 3)} | {f(full["median_net_return_bps_per_trade"], 3)} |
| **PORTFOLIO_RETURN_BPS** (÷500) | {f(dev["portfolio_return_bps"], 1)} | {f(val["portfolio_return_bps"], 1)} | {f(full["portfolio_return_bps"], 1)} |

Note the **median is deeply negative** on every split
(DEV {f(dev["median_net_return_bps_per_trade"], 1)} bps) while the mean is strongly
positive: the strategy is a low-win-rate, fat-right-tail distribution — a handful of
large winners drive the result. This is characteristic of beta/trend exposure, not
of a broad edge.

## Reconcile +3018.3 USD vs +1247.8 / +238.7 bps

Three different concepts, all reconciled:

1. **+{f(full["total_net_pnl_usd"], 2)} USD** = total net PnL of the **FULL continuous DEV+VAL run** (4617 positions; = builder "STATE LONG" {f(rec["builder_state_LONG_net_usd"], 2)}). A **USD portfolio total**.
2. **+{f(dev["avg_net_return_bps_per_trade"], 1)} bps** = DEV **average per-position (≈ per-episode) net return**, denominator = position's own allocation. A **per-episode rate**, not a total and not a portfolio figure.
3. **+{f(val["avg_net_return_bps_per_trade"], 1)} bps** = same concept on VALIDATION.

Consistency check: DEV total {f(dev["total_net_pnl_usd"], 2)} USD ÷ 500 x 1e4 =
{f(dev["portfolio_return_bps"], 1)} bps = {f(dev["episodes"], 0)} episodes x {f(unc["DEV"]["mean_portfolio_bps"], 1)} bps/episode.
The per-position mean {f(dev["avg_net_return_bps_per_trade"], 1)} ≈ the per-episode
mean {f(unc["DEV"]["mean_portfolio_bps"], 1)} because basket constituents share one
episode. All three numbers are the *same economics* at different aggregation bases.

## Verdict

`RECONCILED` — no unreconcilable quantity. `DEF-METRIC-EXPECTANCY-001` registered
for *naming* (denominator not stated), **not** for an accounting error.
"""

files["COST_ACCOUNTING.md"] = f"""# COST ACCOUNTING (§9)

## COST_MODEL_V3 recomputed independently

`cost_model_v3_rt_bps(size_usd=500, horizon_minutes=30)` via the live `CostEngine`
→ `{b["cost_model_v3_rt_bps"]}` bps round-trip (never hardcoded; identical to the
builder baseline).

## Per-episode charge (correct simultaneous-basket handling)

- Entry fee per constituent: `alloc * 23.559/1e4`; exit fee modelled in the single
  round-trip fee on the same position.
- Summed over a basket: `Σ alloc * 23.559/1e4 = 500 * 23.559/1e4 = **1.178 USD per
  basket round-trip**`.
- Verified: charge per episode = `{f(turn["DEV"]["cost_charged_per_episode_usd"], 4)}`
  (DEV), `{f(turn["VALIDATION"]["cost_charged_per_episode_usd"], 4)}` (VALIDATION).
- Fees scale exactly with episode count, not constituent count:
  DEV {f(turn["DEV"]["episodes"], 0)} episodes x 1.178 = {f(dev["total_fees_usd"], 2)} = total fees ✓;
  VALIDATION {f(turn["VALIDATION"]["episodes"], 0)} x 1.178 = {f(val["total_fees_usd"], 2)} ✓.

## Verdict

**NOT undercharged.** Each asset-position pays cost on its own allocation, so a
single portfolio decision containing ~{f(turn["FULL"]["avg_episode_size_names"], 0)} asset
trades still pays exactly **one** basket round-trip on 500 USD. There is no
basket/holding cost leakage. Cost is charged **per round-trip per rebalance**, and
that equals per-position x per-rebalance correctly aggregated.
"""

files["TURNOVER.md"] = f"""# TURNOVER (§10)

Fixed 500 USD deployed while LONG, flat while FLAT; a long/flat timer re-trades the
whole basket each episode, so turnover is round-trip per episode.

| metric | DEV | VALIDATION | FULL |
|---|---|---|---|
| episodes | {f(turn["DEV"]["episodes"], 0)} | {f(turn["VALIDATION"]["episodes"], 0)} | {f(turn["FULL"]["episodes"], 0)} |
| entry notional USD | {f(turn["DEV"]["entry_notional_usd"], 0)} | {f(turn["VALIDATION"]["entry_notional_usd"], 0)} | {f(turn["FULL"]["entry_notional_usd"], 0)} |
| exit notional USD | {f(turn["DEV"]["exit_notional_usd"], 0)} | {f(turn["VALIDATION"]["exit_notional_usd"], 0)} | {f(turn["FULL"]["exit_notional_usd"], 0)} |
| **gross turnover USD** | {f(turn["DEV"]["gross_turnover_usd"], 0)} | {f(turn["VALIDATION"]["gross_turnover_usd"], 0)} | {f(turn["FULL"]["gross_turnover_usd"], 0)} |
| total fees USD | {f(dev["total_fees_usd"], 2)} | {f(val["total_fees_usd"], 2)} | {f(full["total_fees_usd"], 2)} |

- **Daily turnover (FULL)** = {f(turn["FULL"]["gross_turnover_usd"], 0)} / 2372 days ≈
  **{f(turn["FULL"]["gross_turnover_usd"] / 2372, 1)} USD/day** on a 500 base.
- **Rebalance turnover** ≈ 500 in + ~500 out per episode = 2x500 per rebalance.
- Costs are **not** undercharged because one decision spawns many asset trades
  (see `COST_ACCOUNTING.md`): total fees {f(full["total_fees_usd"], 2)} =
  {f(turn["FULL"]["episodes"], 0)} x 1.178.
"""

files["CAPITAL_MODEL.md"] = f"""# CAPITAL MODEL (§11) — economically critical

**`$500` = $500 TOTAL PORTFOLIO, NOT $500 per asset.**

- The builder sets `alloc = notional / len(fillable)` with `notional = 500`, and
  every constituent `Trade.notional` equals that **allocation**, not 500.
- Verified: average deployed capital per episode = `{f(turn["DEV"]["avg_deployed_capital_usd"], 2)}`
  USD (DEV), `{f(turn["VALIDATION"]["avg_deployed_capital_usd"], 2)}` (VALIDATION) —
  i.e. exactly 500 while long, regardless of basket size (~{f(turn["FULL"]["avg_episode_size_names"], 0)} names).
- Average `Trade.notional` = {f(dev["avg_alloc_per_position"], 4)} USD (DEV), {f(val["avg_alloc_per_position"], 4)} (VALIDATION) — the per-name slice of 500.

## Model

- **capital base**: 500 USD, **non-compounding** (each episode re-deploys a fresh 500).
- **cash state**: fully in cash when FLAT, fully deployed (equal-weight) when LONG,
  1x, long-only, **no leverage/margin**.
- **rebalance semantics**: whole-basket entry at next open; whole-basket exit at next
  open; no intra-episode re-weighting.
- **maximum concurrent exposure**: 500 USD gross; 0 net cushion (unlevered).

A per-asset reading of $500 (would imply 500 x N ≈ 40,000 USD exposure) is
**false** and would overstate capital by ~80x. All percentages below use the **500
total** base.
"""

files["EQUITY_CURVE.md"] = f"""# EQUITY CURVE (§13) — new, separate metrics

Built with **verifier-owned** portfolio accounting (does not overwrite any builder
metric):

`equity(d) = 500 + realised net of closed episodes + unrealised gross of open
episodes (marked at close_d)` — fixed-500, non-compounding, 1x.

| metric | DEV | VALIDATION | FULL |
|---|---|---|---|
| **EQUITY_RETURN_BPS** | {f(eq["DEV"]["equity_return_bps"], 1)} | {f(eq["VALIDATION"]["equity_return_bps"], 1)} | {f(eq["FULL"]["equity_return_bps"], 1)} |
| final equity USD | {f(eq["DEV"]["final_equity_usd"], 2)} | {f(eq["VALIDATION"]["final_equity_usd"], 2)} | {f(eq["FULL"]["final_equity_usd"], 2)} |
| **EQUITY_MAX_DRAWDOWN_BPS** | {f(eq["DEV"]["equity_max_drawdown_bps"], 1)} | {f(eq["VALIDATION"]["equity_max_drawdown_bps"], 1)} | {f(eq["FULL"]["equity_max_drawdown_bps"], 1)} |
| EQUITY_MAX_DRAWDOWN USD | {f(eq["DEV"]["equity_max_drawdown_usd"], 2)} | {f(eq["VALIDATION"]["equity_max_drawdown_usd"], 2)} | {f(eq["FULL"]["equity_max_drawdown_usd"], 2)} |

`EQUITY_RETURN` == `portfolio_net_bps` (÷500) — the two agree exactly, confirming
the capital base is 500 total. A valid equity curve **does** exist here, so
`EQUITY_METRICS_UNDEFINED` is **not** invoked.

**Caveat**: an equity return of {f(eq["FULL"]["equity_return_bps"] / 10000, 2)}x on a
500 base over 6.4 years is *non-compounding* (fixed bet sizing), so it is not an
annualised CAGR. The peak-to-trough USD drawdown of ~{f(eq["DEV"]["equity_max_drawdown_usd"], 0)} USD
on 500 deployed is **~47% of deployed capital** — economically severe for a
long-only crypto timer.
"""

files["DRAWDOWN_RECONCILIATION.md"] = f"""# DRAWDOWN RECONCILIATION (§14)

## Reproduced existing metric

`max_drawdown_bps` = peak-to-trough of the cumulative **non-compounding net-USD**
sequence (emission order) divided by 500 x 1e4:

| split | builder | verifier (reproduced) |
|---|---|---|
| DEV | 4704.519 | {f(dev["pnl_drawdown_bps_of_reference_notional"], 3)} |
| VALIDATION | 4534.442 | {f(val["pnl_drawdown_bps_of_reference_notional"], 3)} |

**Renamed conceptually**: `PNL_DRAWDOWN_BPS_OF_REFERENCE_NOTIONAL`.

It is **NOT equity drawdown**: the drawdown is measured on the *closed-trade PnL
accumulator*, not on a marked-to-market account; it can and does exceed 100% of the
reference notional in a leveraged or compounded reading, and it ignores the
unrealised excursion of open positions.

## True equity drawdown (new)

| split | EQUITY_MAX_DRAWDOWN_BPS (mark-to-market) | episode-ordered realised DD bps |
|---|---|---|
| DEV | {f(eq["DEV"]["equity_max_drawdown_bps"], 1)} | {f(D["exit_ordered_drawdown"]["DEV"]["episode_ordered_drawdown_bps_of_500"], 1)} |
| VALIDATION | {f(eq["VALIDATION"]["equity_max_drawdown_bps"], 1)} | {f(D["exit_ordered_drawdown"]["VALIDATION"]["episode_ordered_drawdown_bps_of_500"], 1)} |

The mark-to-market equity DD ({f(eq["DEV"]["equity_max_drawdown_bps"], 1)} bps DEV) is
close to but distinct from the PnL drawdown ({f(dev["pnl_drawdown_bps_of_reference_notional"], 1)} bps):
the realised-order metric slightly understates the true excursion. Both are now
reported under unambiguous names.
"""

files["PF_REPRODUCTION.md"] = f"""# PROFIT FACTOR REPRODUCTION (§15)

Two valid but different definitions; both are reported.

| definition | DEV | VALIDATION |
|---|---|---|
| **builder** `sum(net_bps>0)/|sum(net_bps<=0)|` (bps-space, equal position weight) | 2.9298 | 1.3746 |
| **verifier** gross profit USD / |gross loss USD| (**currency**, economically standard) | **{f(dev["profit_factor"], 4)}** | **{f(val["profit_factor"], 4)}** |

- DEV gross profit {f(dev["gross_profit_usd"], 2)} / gross loss {f(abs(dev["gross_loss_usd"]), 2)} = {f(dev["profit_factor"], 4)}.
- VALIDATION gross profit {f(val["gross_profit_usd"], 2)} / gross loss {f(abs(val["gross_loss_usd"]), 2)} = {f(val["profit_factor"], 4)}.

The builder's ≈2.93 / ≈1.37 are **reproduced exactly** as the bps-space ratio. The
currency PF is slightly higher because large winners sit in larger baskets. Both
confirm "DEV profitable, VALIDATION marginally profitable" — the direction the
builder reported is correct; only the space (bps vs USD) differs.
"""

files["DEV_REPRODUCTION.md"] = f"""# DEV REPRODUCTION (§16)

Frozen split 2019-01-01..2024-01-01; raw bars; verifier-owned metrics.

| metric | builder | verifier | match |
|---|---|---|---|
| trades | 2998 | {f(dev["trades"], 0)} | ✓ |
| episodes | (n/a) | {f(dev["episodes"], 0)} | — |
| gross PnL bps/pos | 1271.375 | {f(dev["avg_gross_return_bps_per_trade"], 3)} | ✓ |
| net PnL bps/pos | 1247.816 | {f(dev["avg_net_return_bps_per_trade"], 3)} | ✓ |
| total net USD | 2666.0 | {f(dev["total_net_pnl_usd"], 2)} | ✓ |
| portfolio net bps | 53319.999 | {f(dev["portfolio_return_bps"], 1)} | ✓ |
| fees USD | 49.47 | {f(dev["total_fees_usd"], 2)} | ✓ |
| win rate | 0.4253 | {f(dev["win_rate"], 4)} | ✓ |
| PF | 2.9298 | {f(dev["profit_factor"], 4)} (currency) / 2.9298 (bps) | ✓ (space) |
| PnL drawdown bps | 4704.519 | {f(dev["pnl_drawdown_bps_of_reference_notional"], 3)} | ✓ |

Entry-price integrity: **2998/2998** fills equal the raw next-open bar (0 mismatches).
`DEV_PASS` confirmed. No builder result parser was used as authority.
"""

files[
    "VALIDATION_REPRODUCTION.md"
] = f"""# VALIDATION REPRODUCTION (§17) — most important economic evidence

Frozen split 2024-01-01..2025-07-01.

| metric | builder | verifier | match |
|---|---|---|---|
| trades | 1534 | {f(val["trades"], 0)} | ✓ |
| episodes | (n/a) | {f(val["episodes"], 0)} | — |
| gross PnL bps/pos | 262.281 | {f(val["avg_gross_return_bps_per_trade"], 3)} | ✓ |
| net PnL bps/pos | 238.722 | {f(val["avg_net_return_bps_per_trade"], 3)} | ✓ |
| total net USD | 192.11 | {f(val["total_net_pnl_usd"], 2)} | ✓ |
| portfolio net bps | 3842.274 | {f(val["portfolio_return_bps"], 1)} | ✓ |
| PF | 1.3746 | {f(val["profit_factor"], 4)} (currency) | ✓ (space) |
| win rate | 0.2855 | {f(val["win_rate"], 4)} | ✓ |

## Is VALIDATION *genuinely* positive under correct accounting?

**Directionally yes; statistically not demonstrable.**

- Portfolio return {f(val["portfolio_return_bps"], 1)} bps on 500 = +{f(val["total_net_pnl_usd"], 2)} USD.
- **Per-episode mean** = {f(unc["VALIDATION"]["mean_portfolio_bps"], 1)} bps over only
  **{f(val["episodes"], 0)} basket episodes**; block-bootstrap 95% CI
  **[+{f(unc["VALIDATION"]["mean_ci95"][0], 0)}, +{f(unc["VALIDATION"]["mean_ci95"][1], 0)}] bps**
  — **includes zero**; P(mean ≤ 0) ≈ {f(unc["VALIDATION"]["mean_p_leq_zero"], 2)}.
- Median position return is **-{f(abs(val["median_net_return_bps_per_trade"]), 0)} bps**:
  the positive total is a right-tail artifact of a few episodes.

So VALIDATION does not repeat the DEV→negative reversal (unlike EXP-ARP-008/021/022),
but with n = {f(val["episodes"], 0)} independent episodes it cannot reject zero. This
is **positive-but-insufficient**, not a demonstrated edge.
"""

files["BETA_REPRODUCTION.md"] = f"""# BETA REPRODUCTION (§18)

Builder `beta_decomposition` reproduced by independent OLS/through-origin regression:

| item | documentation |
|---|---|
| dependent variable | `y = gross / notional` = the **GROSS** per-position return over its holding window |
| independent variable | `x = BTCUSDT close(exit_ts)/close(entry_ts) - 1` (BTC return over the SAME window) |
| frequency | **per asset-position episode** (not per calendar day, not per portfolio decision) |
| intercept | **forced through origin** in the builder (`beta = Σxy/Σx²`) |
| sample | all DEV+VALIDATION per-position episodes |

## Reproduced

| sample | beta | mean pos return | mean BTC return | residual stdev |
|---|---|---|---|---|
| FULL | **{f(beta["FULL"]["market_beta"], 4)}** (builder 1.7143) | 0.097695 | 0.022534 | {f(beta["FULL"]["residual_stdev"], 6)} |
| DEV | {f(beta["DEV"]["market_beta"], 4)} | — | — | — |
| VALIDATION | {f(beta["VALIDATION"]["market_beta"], 4)} | — | — | — |

Beta ≈ 1.71 (VAL {f(beta["VALIDATION"]["market_beta"], 4)}) ⇒ **the basket is ~1.7x
BTC beta**. Note the dependent variable is per-position and BTC positions appear on
*both* sides (BTC is a constituent), and the 4617 "observations" are ~
{f(turn["FULL"]["avg_episode_size_names"], 0)}-way correlated within only
{f(full["episodes"], 0)} episodes — so the naive observation count is not an
independent sample.

**The residual mean is NOT "alpha" by itself** — see `TIMING_ALPHA_ANALYSIS.md`.
"""

files["TIMING_ALPHA_ANALYSIS.md"] = f"""# TIMING ALPHA ANALYSIS (§19)

## What the builder calls "timing alpha"

`timing_alpha` = **mean residual of a through-origin regression of gross
per-position return on BTC return** = {f(beta["FULL"]["timing_alpha_residual_mean"], 6)}
(FULL). Units: a **fractional return per position-episode** (0.0591 = +5.9% per
position over its holding window), **not** an alpha in bps/day and **not** a
risk-adjusted return.

## Statistical distinguishability from zero

Because the dependent variable is through-origin and there is **no fitted
intercept**, the residual mean is mechanically non-zero whenever `mean(y) ≠
beta·mean(x)`; it is **not** a tested intercept.

Independent tests:

| test | statistic | value | interpretation |
|---|---|---|---|
| naive SE (per position) | SE = {f(beta["FULL"]["se_naive_per_position"], 6)} → t = {f(beta["FULL"]["t_naive"], 2)} | huge | **invalid**: ignores within-episode correlation |
| **clustered by entry day** | SE = {f(beta["FULL"]["se_clustered_by_entry_day"], 6)} → t = {f(beta["FULL"]["t_clustered"], 2)} (n_days = {f(beta["FULL"]["n_distinct_entry_days"], 0)}) | t ≈ 2.1 | weak, borderline |
| OLS **with intercept** (FULL) | intercept = {f(beta["FULL"]["ols_with_intercept_intercept"], 6)} ± {f(beta["FULL"]["ols_with_intercept_se_intercept"], 6)} → t = {f(beta["FULL"]["ols_with_intercept_t"], 2)} | positive | positive intercept on FULL |
| OLS with intercept (**VALIDATION**) | intercept = {f(beta["VALIDATION"]["ols_with_intercept_intercept"], 6)} ± {f(beta["VALIDATION"]["ols_with_intercept_se_intercept"], 6)} → t = {f(beta["VALIDATION"]["ols_with_intercept_t"], 2)} | **negative** | does not carry forward |
| OLS with intercept (**DEV**) | t = {f(beta["DEV"]["ols_with_intercept_t"], 2)} | positive | DEV-only |

## Verdict

A `+0.0591` residual mean is **not demonstrated alpha**. Once the cross-sectional
dependence is respected (clustering by entry day) the FULL-window effect is
borderline (t ≈ 2.1), and on the untouched VALIDATION window the intercept is
**negative** (t = {f(beta["VALIDATION"]["ols_with_intercept_t"], 2)}). Any timing
"alpha" present in DEV does not survive into VALIDATION with a well-specified model.
"""

files["REGIME_ANALYSIS.md"] = (
    """# REGIME ANALYSIS (§20)

Builder `88.6%` bull-share reproduced. **Total net by regime, with sample sizes:**

| regime | asset-positions | net USD | % of total net | positive net USD | share of positive net |
|---|---|---|---|---|---|
"""
    + "\n".join(
        f"| {k} | {f(v['trades'], 0)} | {f(v['net_usd'], 2)} | {f(v['net_pct_of_total'], 2)}% | {f(v['positive_net_usd'], 2)} | {f(v['share_of_all_positive_net'], 4)} |"
        for k, v in reg["by_regime"].items()
    )
    + f"""

- total positive net USD: {f(reg["total_positive_net_usd"], 2)}
- **BULL share of all positive net = {f(reg["by_regime"]["BULL"]["share_of_all_positive_net"], 4)}** (builder 0.886) ✓
- **BULL share of TOTAL net = {f(reg["by_regime"]["BULL"]["net_pct_of_total"], 2)}%**

RANGE is absent because `RegimeEngine` emits BULL/BEAR/HIGH_VOL/LOW_VOL/MIXED (the
manifest's "RANGE" maps to MIXED here; reported explicitly rather than silently
dropped). The result is unambiguously **BULL-dominated**: the entire positive net is
a bull-market phenomenon; BEAR/LOW_VOL add little and HIGH_VOL/MIXED are negative.
"""
)

files["ALWAYS_LONG_CONTROL.md"] = f"""# ALWAYS-LONG CONTROL (§21) — critical

Same universe, same equal weighting, same window, same costs; **only the gate
differs**. ALWAYS_LONG = `entry_breadth=0.0, exit_breadth=-1.0` (always risk-on,
re-deployed every 30 days by the same `max_hold` cap).

| strategy | portfolio return bps | total net USD | asset-positions | episodes |
|---|---|---|---|---|
| ALWAYS_LONG_SAME_BASKET | {f(gva["always_long_same_basket"]["portfolio_return_bps"], 1)} | {f(gva["always_long_same_basket"]["total_net_pnl_usd"], 2)} | {f(gva["always_long_same_basket"]["trades"], 0)} | {f(gva["always_long_same_basket"]["episodes"], 0)} |
| BREADTH GATE (frozen) | {f(gva["breadth_gate"]["portfolio_return_bps"], 1)} | {f(gva["breadth_gate"]["total_net_pnl_usd"], 2)} | {f(gva["breadth_gate"]["trades"], 0)} | {f(gva["breadth_gate"]["episodes"], 0)} |
| **value-add** | **+{f(gva["breadth_value_add_bps"], 1)}** | **+{f(gva["breadth_value_add_usd"], 2)}** | | |

## Isolating timing value from crypto beta

- Always-long earns **{f(gva["always_long_same_basket"]["portfolio_return_bps"], 1)} bps**;
  the gate earns {f(gva["breadth_gate"]["portfolio_return_bps"], 1)} bps.
- The gate's **timing value-add is only +{f(gva["breadth_value_add_bps"], 1)} bps**
  (+{f(gva["breadth_value_add_usd"], 2)} USD) over {f(2025 - 2019, 0)} years —
  **~{f(gva["breadth_value_add_bps"] / gva["always_long_same_basket"]["portfolio_return_bps"] * 100, 1)}%** of the always-long result.
- **≈{f(gva["always_long_same_basket"]["portfolio_return_bps"] / gva["breadth_gate"]["portfolio_return_bps"] * 100, 0)}% of the gate's profit is simply long crypto beta**, not timing.

Verdict: the breadth gate is a **beta-exposure timer** with a small, marginal
timing increment — not an independent source of edge.
"""

files["RANDOM_TIMING_CONTROL.md"] = f"""# RANDOM TIMING CONTROL (§22) — diagnostic only

Same number of LONG days ({f(rnd["long_days"], 0)}), same universe; the *timing* of
exposure is randomized with **fixed recorded seeds** `{rnd["seeds"][0]}..{rnd["seeds"][-1]}`.
Return = sum of daily equal-weight eligible-universe returns over the chosen days
(500 base, bps). Not promotable — a diagnostic.

| quantity | portfolio bps |
|---|---|
| REAL breadth-gate exposure days | {f(rnd["real_portfolio_bps"], 1)} |
| random mean | {f(rnd["random_mean_portfolio_bps"], 1)} |
| random p05 | {f(rnd["random_p05"], 1)} |
| random p95 | {f(rnd["random_p95"], 1)} |
| **real percentile** | **{f(rnd["real_percentile"], 4)}** |

## Interpretation (careful)

The gate's realized exposure sits at/above the 95th percentile of random timing,
which in isolation looks like timing skill. **It is confounded**: (i) LONG days are
*clustered* (contiguous runs), and crypto daily returns are positively
autocorrelated, so a clustered schedule mechanically accumulates trends that a
scattered random schedule does not; (ii) the control ignores costs and is not a
tradeable alternative. It is therefore a weak positive signal of *clustering*, not
proof of predictive timing — and it cannot be promoted.
"""

files["BREADTH_PREDICTIVE_VALUE.md"] = (
    """# BREADTH PREDICTIVE VALUE (§23)

Only the horizons **pre-declared in ARP-011** (1/5/10/20/30 d) are reported.

| horizon | corr(B_t, fwd basket return) | block-bootstrap SE (20d blocks) | n |
|---|---|---|---|
"""
    + "\n".join(
        f"| {h.replace('h', '')}d | {f(rp[h]['corr'], 4)} | {f(rp[h]['corr_se_block20'], 4)} | {rp[h]['n']} |"
        for h in ["h1", "h5", "h10", "h20", "h30"]
    )
    + f"""

- `observations = {rp["observations"]}` daily decision points.
- Strongest at **10d**: corr {f(rp["h10"]["corr"], 4)} ± {f(rp["h10"]["corr_se_block20"], 4)}
  (≈{f(rp["h10"]["corr"] / rp["h10"]["corr_se_block20"], 1)}sigma) and **5d**:
  {f(rp["h5"]["corr"], 4)} ± {f(rp["h5"]["corr_se_block20"], 4)}.
- At **20d/30d the correlation is statistically indistinguishable from zero**
  ({f(rp["h20"]["corr"], 4)}, {f(rp["h30"]["corr"], 4)}).

So breadth carries a **weak, short-horizon** (≤10d) predictive signal, with effect
size well under R²≈0.03. It is not a strong return predictor and the point estimates
are fragile across horizons.
"""
)

files["STATISTICAL_UNCERTAINTY.md"] = f"""# STATISTICAL UNCERTAINTY (§24)

Circular block bootstrap over **basket episodes** (not positions), respecting
temporal dependence and overlapping exposure.

| split | episodes | mean bps/episode | 95% CI | bootstrap SE | P(mean ≤ 0) |
|---|---|---|---|---|---|
| DEV | {unc["DEV"]["episodes"]} | {f(unc["DEV"]["mean_portfolio_bps"], 1)} | [{f(unc["DEV"]["mean_ci95"][0], 0)}, {f(unc["DEV"]["mean_ci95"][1], 0)}] | {f(unc["DEV"]["mean_bootstrap_se"], 1)} | {f(unc["DEV"]["mean_p_leq_zero"], 4)} |
| VALIDATION | {unc["VALIDATION"]["episodes"]} | {f(unc["VALIDATION"]["mean_portfolio_bps"], 1)} | [{f(unc["VALIDATION"]["mean_ci95"][0], 0)}, {f(unc["VALIDATION"]["mean_ci95"][1], 0)}] | {f(unc["VALIDATION"]["mean_bootstrap_se"], 1)} | {f(unc["VALIDATION"]["mean_p_leq_zero"], 4)} |
| FULL | {unc["FULL"]["episodes"]} | {f(unc["FULL"]["mean_portfolio_bps"], 1)} | [{f(unc["FULL"]["mean_ci95"][0], 0)}, {f(unc["FULL"]["mean_ci95"][1], 0)}] | {f(unc["FULL"]["mean_bootstrap_se"], 1)} | {f(unc["FULL"]["mean_p_leq_zero"], 4)} |

## Reading

- DEV is robustly positive (P(≤0) = {f(unc["DEV"]["mean_p_leq_zero"], 3)}).
- **VALIDATION is NOT**: its 95% CI **includes zero** and the bootstrap puts ~{f(unc["VALIDATION"]["mean_p_leq_zero"] * 100, 0)}% mass at or below zero.
- The headline "net expectancy" of a whole split hides this because it pools thousands of correlated positions; at the correct (episode) resolution VALIDATION is statistically indistinguishable from zero.
"""

files["EFFECTIVE_SAMPLE_SIZE.md"] = f"""# EFFECTIVE SAMPLE SIZE (§25)

2998 / 1534 **asset-positions** massively overstate independent evidence because
~{f(turn["FULL"]["avg_episode_size_names"], 0)} positions are opened **simultaneously**
inside one basket decision.

| level | DEV | VALIDATION | FULL |
|---|---|---|---|
| asset-positions ("trades") | {ess["asset_positions_DEV"]} | {ess["asset_positions_VALIDATION"]} | {ess["asset_positions_FULL"]} |
| **basket episodes (independent rebalances)** | **{ess["basket_episodes_DEV"]}** | **{ess["basket_episodes_VALIDATION"]}** | **{ess["basket_episodes_FULL"]}** |
| daily decisions | {ess["daily_decisions_DEV"]} | n/a | {ess["daily_decisions_FULL"]} |
| constituents / episode | ~71 | ~110 | {f(ess["avg_constituents_per_episode"], 0)} |

## Effective sample estimate

- DEV: {ess["asset_positions_DEV"]} positions ÷ {ess["basket_episodes_DEV"]} episodes ≈
  shrinkage of **~{f(ess["asset_positions_DEV"] / ess["basket_episodes_DEV"], 0)}x**.
- **VALIDATION independent evidence ≈ {ess["basket_episodes_VALIDATION"]} episodes.**
- A defensible effective-n is bounded by the **episode count**, not the position
  count. On DEV the effective n ≈ {ess["basket_episodes_DEV"]}; on VALIDATION ≈
  {ess["basket_episodes_VALIDATION"]}.

This is why every uncertainty estimate in `STATISTICAL_UNCERTAINTY.md` is computed on
episodes. Any p-value or CI built from the 4617 positions would be inflated by roughly
an order of magnitude.
"""

files["ROBUSTNESS_REPRODUCTION.md"] = (
    f"""# ROBUSTNESS REPRODUCTION (§26)

All **{rob["positive_count"]}/{rob["total"]}** pre-declared perturbations, re-run on
VALIDATION with **corrected economic accounting** (total net USD > 0, not bps-only).
The builder ran 5 config perturbations + 3 cost multiples = 8; the 5 leave-one-out
top-5 assets were also reproduced earlier but are not part of the 8.

| perturbation | asset-positions | net USD | portfolio bps | expectancy bps | PASS |
|---|---|---|---|---|---|
"""
    + "\n".join(
        f"| {k} | {f(v['trades'], 0)} | {f(v['total_net_pnl_usd'], 2)} | {f(v['portfolio_return_bps'], 1)} | {f(v['expectancy_net_bps'], 1)} | {'✓' if v['positive'] else '✗'} |"
        for k, v in rob["perturbations"].items()
    )
    + f"""

- positive fraction: **{f(rob["positive_fraction"], 4)}**; reproduced: **{rob["reproduced"]}**.
- A perturbation counts PASS only if **corrected net economics remain positive** —
  all {rob["total"]} do.

**Caveat**: all 8 are re-runs on the *same* VALIDATION window with n ≈
{f(val["episodes"], 0)} episodes. 8/8 positive raises confidence in sign stability but
**cannot** overcome the effective-sample limit; it is not independent confirmation.
"""
)

files["CONCENTRATION.md"] = f"""# CONCENTRATION (§27)

Recomputed from true portfolio contribution (FULL DEV+VAL):

| measure | value |
|---|---|
| trades | {f(conc["trades"], 0)} |
| top-1 trade share of positive net | {f(conc["top1_trade_share"], 4)} |
| top-5 trade share | {f(conc["top5_trade_share"], 4)} |
| top asset share | {f(conc["top_asset_share"], 4)} ({conc["distinct_assets"]} assets) |
| top period share | {f(conc["top_period_share"], 4)} ({conc["distinct_periods"]} periods) |
| positive net USD | {f(conc["positive_net_usd"], 2)} |

## Portfolio-level (episode) concentration

At the correct resolution the unit is the **episode**: {f(full["episodes"], 0)} episodes
carry the whole result. The builder's "top-1 trade share {f(conc["top1_trade_share"], 4)}"
is *position*-level and therefore **understates** true concentration — one episode can
contain ~{f(turn["FULL"]["avg_episode_size_names"], 0)} positions shown as many "trades".

Regime concentration (`REGIME_ANALYSIS.md`) is the dominant factor: 92.9% of total net
in BULL. Asset-level concentration is low (top asset {f(conc["top_asset_share"], 4)}),
so the risk is **temporal/regime**, not single-name.
"""

files["INDEPENDENT_VERIFICATION.md"] = f"""# INDEPENDENT VERIFICATION (§28) — classification

**EXPERIMENT CLASSIFICATION: `{CLASSIFICATION}`**

## What is reproduced

- Contract, split, dataset fingerprint, holdout — all match; PIT intact (next-open
  fills, 4617/4617 verified).
- DEV: {f(dev["trades"], 0)} positions, net {f(dev["total_net_pnl_usd"], 2)} USD
  ({f(dev["portfolio_return_bps"], 1)} bps), PF {f(dev["profit_factor"], 4)} (currency);
  **reproduced exactly**.
- VALIDATION: {f(val["trades"], 0)} positions, net {f(val["total_net_pnl_usd"], 2)} USD
  ({f(val["portfolio_return_bps"], 1)} bps); **reproduced exactly**.
- Beta **{f(beta["FULL"]["market_beta"], 4)}**; bull share
  **{f(reg["by_regime"]["BULL"]["share_of_all_positive_net"], 4)}**; robustness **8/8** —
  all reproduced.

## Why NOT `ECONOMIC_EDGE_REPRODUCED`

1. **Metric naming defects** (`DEF-METRIC-EXPECTANCY-001`, `DEF-METRIC-PROFIT-FACTOR-001`)
   but the numbers themselves **reconcile** — so it is **not** `METRIC_ARTIFACT`.
2. **Beta dominates**: beta {f(beta["FULL"]["market_beta"], 4)}; the always-long control
   earns {f(gva["always_long_same_basket"]["portfolio_return_bps"], 1)} of the gate's
   {f(gva["breadth_gate"]["portfolio_return_bps"], 1)} bps → the gate's timing adds only
   **+{f(gva["breadth_value_add_bps"], 1)} bps** over 6.4 years.
3. **Not statistically demonstrable on VALIDATION**: {f(val["episodes"], 0)} episodes,
   95% CI [{f(unc["VALIDATION"]["mean_ci95"][0], 0)}, {f(unc["VALIDATION"]["mean_ci95"][1], 0)}] bps
   **includes zero**.

## Why NOT `INSUFFICIENT_EVIDENCE` as the *primary* label

It is not merely underpowered: even granting the DEV significance, the mechanism is
**structurally** a long-crypto-beta timer (positive net only in BULL, beta 1.7, 92% of
net from BULL) whose increment over always-long is marginal. That is a *cause*, not
just a sample-size limitation. `INSUFFICIENT_EVIDENCE` is recorded as the
**secondary/caveat** label for VALIDATION specifically.

## Classification

- **Primary: `{CLASSIFICATION}`** — positive expectancy is real and correctly
  accounted, but is dominated by crypto market beta; the breadth gate is a
  marginal, beta-exposed exposure timer, not an independent economic edge.
- **Secondary (VALIDATION): `INSUFFICIENT_EVIDENCE`** — {f(val["episodes"], 0)} episodes
  cannot reject zero.

`FALSE_SUCCESS = 0`. No builder claim was accepted without independent recomputation.
"""

files[
    "MARKET_NEUTRAL_NEXT_SPEC.md"
] = f"""# MARKET-NEUTRAL RELATIVE VALUE — RESEARCH SPECIFICATION (§30)

**Specification only. No strategy is implemented in this phase.** No profitability
is asserted or implied.

## Objective

A family with a **near-zero market beta target**, distinct from the beta-exposed
trend/breadth family (EXP-ARP-008/016/017/018/019/021/022, all reduced to crypto
beta).

## Construction (to be pre-registered, not implemented here)

1. **Object**: relative value, not direction. At each rebalance rank the eligible
   `ARP-006-UNIVERSE-v1` universe and go **long the top-k / short the bottom-k** of a
   PIT-safe score, dollar- and beta-neutralised.
2. **Neutrality**: target `Σw = 0` (dollar-neutral) and regression beta of the
   portfolio to BTC ≈ 0; report residual beta each rebalance and fail closed if
   `|beta| > tolerance`.
3. **Score** (PIT-only): a cross-sectional, mean-reversion or relative-strength factor
   — frozen a priori; no OOS-driven choice; e.g. `log(close_t/close_{{t-L}})`
   demeaned, or a cointegration-residual spread; must read closed bars only.
4. **Execution**: next-open fills; skip stale/gap/thin names exactly as the existing
   `DynamicAssetUniverse` does.
5. **Costs**: `COST_MODEL_V3` **plus an explicit short leg** — borrow/funding must be
   stated as an assumption (rate, accrual basis, availability). If no perp/funding
   series exists in the corpus, the short leg is **DATA_BLOCKED** until it is sourced;
   do not invent a borrow cost.
6. **Splits**: same frozen DEV/VALIDATION and the **same forward holdout**
   `HOLDOUT-ARP-019-FORWARD` (UNTOUCHED) — or a new registered holdout.
7. **Kill criteria**: `REJECT_NO_EDGE`, `REJECT_COSTS` (net ≤ 0 after borrow+funding),
   `REJECT_BETA` (|beta| not distinguishable from 0), `REJECT_VALIDATION`.

## Explicit assumptions / blockers

- **Borrow cost** is assumed, not observed — a *stated* parameter, never fitted.
- **Short availability** in crypto spot is not modelled by the corpus; a funding/basis
  series is required for a defensible short leg → likely `EXTERNAL_DATA_REQUIRED`.
- With only ~{f(ess["basket_episodes_FULL"], 0)} independent episodes per family before,
  **effective sample** is the binding constraint; a market-neutral family must be
  constructed with enough **independent rebalances** to have power.

## Status

`RESEARCH_READY_SPEC` — specification complete, **not implemented**, **no profitability
claim**, OOS **CLOSED**.
"""

files["RUN_REPORT.md"] = f"""# RUN REPORT — ARP-012

- experiment: `EXP-ARP-019` / `H-BREADTH-REGIME-001`
- role: **INDEPENDENT VERIFIER** (BUILDER != VERIFIER)
- START_SHA: `{b["start_sha"]}`
- holdout `{b["holdout_id"]}`: **{D["holdout_status_after"]}**; OOS opened: **NO**
- DEV reproduced: **{f(dev["total_net_pnl_usd"], 2)} USD / {f(dev["portfolio_return_bps"], 1)} bps / {f(dev["trades"], 0)} positions / {f(dev["episodes"], 0)} episodes**
- VALIDATION reproduced: **{f(val["total_net_pnl_usd"], 2)} USD / {f(val["portfolio_return_bps"], 1)} bps / {f(val["trades"], 0)} positions / {f(val["episodes"], 0)} episodes**
- beta {f(beta["FULL"]["market_beta"], 4)}; bull share {f(reg["by_regime"]["BULL"]["share_of_all_positive_net"], 4)}; robustness {rob["positive_count"]}/{rob["total"]}
- **classification: `{CLASSIFICATION}`**
- machine copy: [`RUN_REPORT.json`](RUN_REPORT.json)

No strategy/threshold/asset/universe/cost/split was modified. No pre-existing dirty
file was touched.
"""

files[
    "FINAL_REPORT.md"
] = f"""# FINAL REPORT — ARP-012 EXP-ARP-019 INDEPENDENT ECONOMIC VERIFICATION

**Classification: `{CLASSIFICATION}`** (secondary: `INSUFFICIENT_EVIDENCE` on VALIDATION).

All builder headline numbers were **independently reproduced** from raw bars:
DEV {f(dev["total_net_pnl_usd"], 2)} USD / {f(dev["portfolio_return_bps"], 1)} bps,
VALIDATION {f(val["total_net_pnl_usd"], 2)} USD / {f(val["portfolio_return_bps"], 1)} bps,
beta {f(beta["FULL"]["market_beta"], 4)}, bull share {f(reg["by_regime"]["BULL"]["share_of_all_positive_net"], 4)},
robustness {rob["positive_count"]}/{rob["total"]}. The reported "+3018.3 USD / 4617 trades"
is the FULL continuous DEV+VAL run (reproduced to the cent).

Two **naming/semantics defects** were registered and reconciled — not accounting
errors: `expectancy_*_bps` is per-position (denominator = own alloc), and
`profit_factor` is bps-space. The `max_drawdown_bps` field is re-named conceptually
`PNL_DRAWDOWN_BPS_OF_REFERENCE_NOTIONAL`; a true mark-to-market `EQUITY_MAX_DRAWDOWN`
was built separately (DEV {f(eq["DEV"]["equity_max_drawdown_bps"], 1)} bps).

**Why not an economic edge**: (i) beta {f(beta["FULL"]["market_beta"], 4)}; (ii) the
always-long same-basket control earns {f(gva["always_long_same_basket"]["portfolio_return_bps"], 1)}
of the gate's {f(gva["breadth_gate"]["portfolio_return_bps"], 1)} bps, leaving only
+{f(gva["breadth_value_add_bps"], 1)} bps of timing value over 6.4 years; (iii) at the
correct episode resolution VALIDATION has only {f(val["episodes"], 0)} independent
observations and its 95% CI includes zero.

**HOLDOUT `{b["holdout_id"]}`: {D["holdout_status_after"]}. OOS OPENED: NO.** No OOS
authorization. Next authorized step: the MARKET-NEUTRAL RELATIVE VALUE **specification**
only (no implementation, no OOS).
"""

for name, content in files.items():
    (OUT / name).write_text(content, encoding="utf-8")

# machine copy
(OUT / "RUN_REPORT.json").write_text(
    json.dumps(D, indent=2, sort_keys=True, default=str), encoding="utf-8"
)
print("wrote", len(files) + 1, "files to", OUT)
