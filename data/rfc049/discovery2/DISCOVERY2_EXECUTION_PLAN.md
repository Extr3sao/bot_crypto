# RFC-049 DISCOVERY 2 — EXECUTION PLAN (PREREGISTRATION)

| field | value |
| --- | --- |
| artifact | `RFC049_DISCOVERY2_EXECUTION_PLAN` |
| written_before_economic_run | **true** — this document is frozen before any return, PnL or trade count for a candidate is computed |
| generated_at_utc | `2026-10-10T16:22:02Z` |
| head_at_write | `2d113a0ae82f38123eabe0385ab47bb7991b15ad` |
| authorization | `data/rfc049/discovery2/CAMPAIGN_AUTHORIZATION.json` (ADR-0025); scope `OFFLINE_DEV_VAL_ONLY` |
| frozen specs | `data/rfc049/specs/H-049-001.json` (`fd5cd299…`), `H-049-002.json` (`cdafdc15…`) — inputs, never outputs |
| cost model | `docs/COST_MODEL_V3.json`, scenario `BINANCE_SPOT_STANDARD_TAKER`, re-derived at run time from `trading_bot.research.microstructure.cost_model_v3` |
| charters | `docs/governance/RFC049_DISCOVERY_ADMISSION.md`, `DISCOVERY_STOP_RULES.md` |
| results go to | `data/rfc049/discovery2/` — Phase A and RFC-049B artifacts are not modified |

## 1. What this campaign does and does not do

**Does:** implement the two frozen hypotheses in the research plane, run their economic
experiments on the RESEARCH_EXPOSED partitions (development + validation) with PIT
enforcement and the frozen cost model, run the robustness battery, run a filter-ablation
diagnostic for the stablecoin/macro states against a declared base, audit the ACTIVE
pipeline, and have everything independently reproduced.

**Does not:** open the sealed forward OOS (it opens exactly once, at its gate: 20 closed
round trips or 24 months after `freeze_timestamp_utc = 2026-10-10T11:26:20Z`), promote
anything, change any threshold, run any parameter search, trade, or touch live. No PASS is
emittable in this phase; the best reachable state now is `PENDING_SEALED_OOS`.

## 2. Frozen inputs and integrity checks (fail-closed)

Before computing anything, the engine re-hashes and verifies, against
`PREREGISTRATION_MANIFEST.json` and `VENDOR_MANIFEST.json`:

- spec files (must equal the freeze-time hashes; any drift aborts the run);
- the four traded inputs (`defillama_stablecoin_supply_all.json`, `fred_WALCL.csv`,
  `fred_RRPONTSYD.csv`, `fred_WTREGEN.csv`) and the two price files
  (`BTC-USDT_1d.json`, `ETH-USDT_1d.json`);
- the COST_MODEL_V3 artifact hash.

Rule adopted for the current day (FASE 1.6): a value dated `t` is treated as available at
`00:00 UTC of t+1` (H-049-001) or under the declared release lags (H-049-002); the value
dated 2026-10-10 is therefore never a complete, available daily observation and cannot be
consumed by any decision. The last decision instant of the campaign (2026-10-04) consumes
inputs dated no later than 2026-10-03 in every case.

## 3. Decision grid (identical to RFC-049B, re-derived, not copied)

```text
first_signal = first dated stablecoin row + 395 days
grid_start   = max(first_signal, first BTC bar date + 60 days, 2013-01-01)
grid         = every Sunday from the first Sunday >= grid_start through the last Sunday
               <= the last BTC bar date
```

Expected 406 instants, `2018-12-30 … 2026-10-04`. The engine aborts if the grid differs
from this expectation.

## 4. State semantics (frozen; PIT-enforced)

**H-049-001.** At decision Sunday `S` use `t*` = the most recent dated stablecoin row on or
before `S − 2 days` (value dated `t` is available at 00:00 UTC of `t+1`, and the Saturday
23:59 cutoff leaves `t* ≤ S − 2`). LONG iff `r30(t*) > median(r30 over the previous 365
daily values ending at t*−1)`; else FLAT. Unavailable inputs → FLAT (fail-closed).

**H-049-002.** At `S` use the Wednesday reference `W = S − 4 days` and `W − 4 weeks`. For
each series take the most recent non-null observation on or before the reference weekday
with bounded reach-back of 7 calendar days; `NL = WALCL/1000 − RRPONTSYD − WTREGEN/1000`
(USD billions). LONG iff `NL(W) − NL(W−4w) > 0`; else FLAT. Missing input → FLAT.

Both rules are re-implemented from the frozen spec text and must reproduce RFC-049B's
realised counts exactly (`H-049-001`: 14 development / 9 validation / 23 total;
`H-049-002`: 26 / 22 / 48). A count mismatch aborts the run: it is an implementation defect,
not a result.

## 5. Execution, PnL accounting and costs

- One position at a time, long/cash, spot, 1x; fixed experimental stake **200 USDT** per
  round trip; no compounding in the per-trip statistics (an equity curve is used only for
  drawdown).
- Entry: first daily bar open strictly after the decision instant of the transition Sunday
  (Monday 00:00 UTC). Exit: first daily bar open strictly after the FLAT decision instant.
  No intrabar fills, no maker assumption.
- `gross_ret = exit_open/entry_open − 1`; `cost_bps` is re-derived from COST_MODEL_V3 at
  200 USDT (`BINANCE_SPOT_STANDARD_TAKER`, normal liquidity, market/market, 25-min
  horizon); `net_ret = gross_ret − cost_bps/10000`; `net_usd = 200 · net_ret`.
- Stress: every cost component ×1.5 for the stressed `net_ret`; a 1.25x variant is also
  reported. `ZERO_COST` is never used in any decision.
- The plan records the expected derived values (23.353553391 bps at 200 USDT;
  35.030330086 bps at 1.5×) and asserts equality to ±1e-6 bps at run time.

## 6. Partitions

- development: entry Sunday ≤ 2023-12-31; validation: 2024-01-01 … 2026-12-31 — the
  partition of a round trip is the partition of its entry Sunday (identical to RFC-049B's
  counting, so the counts above are comparable). Straddling trips are reported explicitly.
- sealed_oos: strictly after `2026-10-11T00:00:00Z`; **closed** — the engine reads no
  observation whose availability time is after `2026-10-10T11:26:20Z` and aborts if the
  sealed window is touched.

## 7. Metrics (per candidate, per asset, per partition)

round trips; gross and net sum (bps of notional and USDT); net per-trip expectancy;
profit factor; max drawdown of the compounded trip-equity curve; single-trade share of
positive net; the same four numbers under 1.25x and 1.5x stress; sign of net in each of
three equal consecutive sub-windows; LCB (section 8); bootstrap p; incremental tests
(section 9). All definitions: net = after COST_MODEL_V3.

## 8. Statistical procedure (frozen now, before results)

- **Stationary block bootstrap**, 10,000 resamples, expected block length 7 days, seed
  `490049`, one-sided 95% lower confidence bound of net per-trip expectancy (5th
  percentile of the bootstrap mean).
- The block length is expressed **in days and mapped to the trip grid** via the measured
  mean spacing between entry Sundays: `L_obs = max(1, round(7 / spacing_days))`. For these
  multi-week rules the mapping yields `L_obs = 1`, so the procedure is, honestly, the
  stationary bootstrap with block length 1 (equivalently iid resampling of trip returns);
  this is recorded rather than silently replaced. A sensitivity with block lengths 2 and 3
  trips is reported in the robustness battery.
- Bootstrap p (one-sided): fraction of bootstrap means ≤ 0. **BH and Holm** corrections are
  applied across the two admitted hypotheses for each partition; the p-values and corrected
  values are reported, and neither is used to move any acceptance threshold.
- **Gate decision use:** the LCB against 0 is the operative frozen criterion
  (`lcb_95_net_expectancy_positive`). p-values are descriptive at this stage.

## 9. Incremental tests (semantics frozen)

- **buy-and-hold**: one entry at the first execution bar of the partition (bar after its
  first decision) and one exit at the last execution bar of the partition (bar after its
  last decision), paying one round-trip cost. Net compounded return of that single
  window.
- **200-day trend baseline**: at each Sunday `S`, using daily closes strictly available at
  the decision instant (bar dated ≤ `S − 1 day`), LONG iff last close > SMA(200) of those
  closes; transitions executed exactly like the candidate's (next bar open, same cost per
  round trip). Same grid, same costs.
- **incrementals**: strategy net (compounded over its own trips, per partition) minus each
  baseline's net, in bps. Positive is required by the frozen thresholds,
  `incremental_over_buy_and_hold_positive` and
  `incremental_over_200d_trend_baseline_positive`.
- **between candidates**: each candidate's state versus the other's, per partition
  (descriptive).

## 10. Replication

ETHUSDT is run as the declared replication asset for both candidates (state inputs are the
same; only the price leg changes) and reported in full, labelled replication diagnostics.

## 11. Gate evaluation mapping (what is computable now)

| frozen threshold | computable now? |
| --- | --- |
| net_expectancy_positive, net_profit_factor_min ≥ 1.1 | development, validation |
| lcb_95_net_expectancy_positive | development, validation |
| cost_stress_1_5x_net_positive | development, validation |
| positive_in_every_partition | development and validation computable; sealed_oos deferred |
| max_drawdown_le 0.25, single_trade_share ≤ 0.4 | development, validation |
| incremental_over_buy_and_hold / _200d_trend | development, validation |
| net_pnl_oos_positive, minimum_oos_round_trips | **sealed_oos — deferred** |

Per-candidate stage verdict vocabulary (predeclared):

- `CANDIDATE_REJECTED` — any frozen criterion *computable on exposed partitions* fails; the
  candidate can no longer satisfy the acceptance list and is closed at this stage
  (admission policy §6: "a candidate that fails any stage is closed at that stage");
- `PENDING_SEALED_OOS` — all computable criteria pass; the final verdict waits for the
  sealed gate;
- **no PASS is emittable now.** If the sealed window reaches 24 months with fewer than 20
  trips the outcome is `INSUFFICIENT_OOS_SAMPLE`, never PASS and never REJECT on power.

## 12. Robustness battery (predeclared)

1. 1.5x cost stress positive on each computable partition (hard).
2. Sign stability: net positive in **all three** equal sub-windows of both partitions =
   FULL; 2 of 3 in both = PARTIAL (flag, not a hard fail); otherwise `SIGN_UNSTABLE`
   (hard robustness failure, `CANDIDATE_REJECTED`).
3. LCB block-length sensitivity (1/2/3 trip blocks): a sign flip of the LCB is recorded as
   `LCB_FRAGILE` (flag).
4. Sub-period boundaries and any straddling trips are listed explicitly.

## 13. Filter ablation (diagnostic; adopted by nothing)

- New diagnostic hypothesis record `E-049-ABL-001` (created separately; H-049-001 and
  H-049-002 are not modified). The base is the **declared 200-day trend state machine of
  section 9** (the frozen specs' own comparator), because the ACTIVE audit shows no
  admitted ACTIVE strategy exists to filter; using the trend machine keeps the experiment
  executable, and the audit records why an ACTIVE-strategy adoption cannot be evaluated
  today.
- Arms: base; base ∧ stablecoin-LONG; base ∧ macro-LONG; base ∧ both. Identical data,
  costs, partitions, execution. Metrics: net expectancy, PF, max drawdown, trades kept/lost,
  sub-window stability, per-regime split (by filter state).
- Adoption rule: nothing is adopted by this diagnostic, on any result. A future adoption
  would need a new hypothesis, a new budget, and reproducible improvement **outside the
  data used to select it** (forward), per the operator's instruction.

## 14. ACTIVE pipeline audit (FASE 5)

Real state of the paper pipeline: admission ledger states, per-cycle strategy evaluation,
and the distinction signal-generated / proposed / authorized / executed; the arithmetic of
what "3 operations/day, 7 days/week" would require against the cost floor; and the explicit
separation of any low-frequency line (the operator's `R6 P2 QUALITY` label is not found in
the repository; the audit maps it to the low-frequency liquidity line and keeps it separate
from the high-frequency objective).

## 15. Independent verification (builder != verifier)

A second implementation (`scripts/rfc049c_verify.py`) recomputes states, trades, costs and
metrics from the frozen inputs without importing the builder, reproduces the bootstrap by
the documented procedure, and runs negative controls (tampered spec hash, injected
look-ahead, altered trade, truncated price, shifted availability). Failure detection is
mandatory; `FALSE_SUCCESS = 0`. The unit-test suite adds contract tests over the artifacts.

## 16. Stop rules and prohibitions (active from this moment)

Frozen thresholds, rules, partitions, cost model and the 20-trip minimum are unchanged.
No candidate is refilled or re-tuned; no search over parameters; no extension of windows;
all trials (including negatives and this ablation) are recorded. Results that fail are
written up as carefully as passes would be. The sealed OOS is never inspected.
