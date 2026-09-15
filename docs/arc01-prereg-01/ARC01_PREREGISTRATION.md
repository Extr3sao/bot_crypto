# ARC-01 PREREGISTRATION (FROZEN)

**Hypothesis id:** `ARC-01-FUNDING-CROWDING-UNWIND-01`
**Checkpoint:** `ARC01-PREREG-001` · **Version:** 1 · **Frozen:** 2026-09-15
**Final state:** `PENDING_INDEPENDENT_PREREG_VERIFICATION`
**Builder:** DeepSeek (`BUILDER_CROSSCHECK` only — this document is **not** self-certified as independently verified)

Machine-readable authority: `ARC01_SPEC_V1.json` (spec), `ARC01_PIT_CONTRACT.json`, `ARC01_CONTROL_PLAN.json`,
`ARC01_STATISTICAL_GATES.json`, `ARC01_ROBUSTNESS_PLAN.json`, `ARC01_MANIFEST_V1.json`.
Rationale and evidence: `ARC01_SELECTION_RATIONALE.md`, `ARC01_MECHANISM_EVIDENCE.md`,
`ARC01_FAILED_MEMORY_COLLISION_REVIEW.md`.

**Observation ledger at freeze:** `ARC01_BACKTESTS = 0`, `ARC01_EXECUTIONS = 0`,
`ARC01_PERFORMANCE_OBSERVED = false`, `FALSE_SUCCESS = 0`. No return, PnL, Sharpe, Sortino, profit factor,
expectancy, win rate, trade outcome, per-asset performance or parameter sweep was inspected; no metric that
could influence an economic parameter choice was read.

---

## 1. Mechanism

> **EXTREME FUNDING + CROWDED POSITIONING + CAUSAL CONTEXT → CONTRARIAN UNWIND**

- Extreme **positive** funding (longs paying) **+** position-stock expansion → **SHORT**.
- Extreme **negative** funding (shorts paying) **+** position-stock expansion → **LONG**.
- `NO_SIGNAL` is explicit, first-class, counted, and never re-interpreted as a trade.

ARC-01 is **not** a trend, momentum, breakout or mean-reversion-on-price strategy: its direction is a
function of the funding sign and its only conditioning variable is the OI position stock
(`PRICE_CONTEXT = NONE`, §7). The claim is falsifiable and carries four frozen controls (§17).

## 2. Assets / market

`BTCUSDT`, `ETHUSDT`, `SOLUSDT` on Binance **USD-M USDT-margined perpetual** swaps. All three are traded;
no asset may be removed using outcome information. The price rejection leg sketched in the ARU candidate
design is deliberately **out** (justified in the selection rationale, reviewed in the collision review).

## 3. Common causal window

Intersection of the certified funding, OI and price authorities:

| | UTC |
| --- | --- |
| window start (bar open, inclusive) | `2021-12-01T00:00:00Z` |
| window end (bar open, inclusive) | `2026-09-10T23:00:00Z` |

Semantics: a **closed** interval on 1h bar **open times**; a bar spans `[open_time, open_time + 1h)`.
Funding alone covers `2020-09-13T16:00:00.004Z → 2026-09-14T16:00:00Z`, OI covers
`2021-12-01T00:00:00Z → 2026-09-10T23:55:00Z` (5m buckets), price covers `2021-12-01T00:00:00Z → 2026-09-10T23:00:00Z`.
The latest start and earliest end win. **No observation outside this window may be read**, and decisions
whose exit anchor would fall beyond it are not emitted (§10).

## 4. Decision cadence

**One decision per certified funding settlement instant, per asset.**

| Element | Frozen definition |
| --- | --- |
| `decision_time` | `funding_time_ms` of each certified funding row (`funding_time_ms == availability_time_ms == settlement_time_ms`) |
| eligible funding | all rows with `funding_time_ms <= decision_time` |
| eligible OI window | all OI observations with `timestamp_ms <= decision_time` (5m snapshots) |
| eligible price window | only **completed** 1h bars: `bar_open_time + 3600000 <= decision_time` |

Chosen because funding is the only input whose information *arrives* on a schedule, so settlement instants
are exactly the instants at which the signal's primary input changes. A 1h or 5m calendar grid would emit
funding-blind duplicate decisions. Provider-native intervals are honoured (SOL 2022-11 2h/4h rows) — an 8h
calendar is never assumed. **No hidden runtime default exists**; the cadence is the settlement set itself.

## 5. Funding extreme (frozen transform)

| Element | Frozen value |
| --- | --- |
| transform | robust z-score `z = (rate_at_decision - median) / (1.4826 * MAD)` |
| lookback | trailing **60 days**, closed interval `[T − 60d, T]` on `funding_time_ms`, current settlement included |
| minimum observations | **90** (else `NO_SIGNAL / INSUFFICIENT_FUNDING_HISTORY`) |
| location estimator | **median** of the window |
| scale estimator | **MAD** = `median(\|x − median\|)` |
| MAD multiplier | **1.4826** (normal-consistency constant) |
| `MAD == 0` | fall back to **sample stdev (ddof = 1)** on the same window; if that is also 0 → `NO_SIGNAL / SCALE_NONPOSITIVE` |
| positive threshold | **z ≥ +2.0** (inclusive) |
| negative threshold | **z ≤ −2.0** (inclusive) |

No percentile variant and no absolute-funding-level variant is used. Justification (mechanism + estimator
statistics + event budget, never returns) in `ARC01_SELECTION_RATIONALE.md` §3.

## 6. OI crowding confirmation (frozen rule)

| Element | Frozen value |
| --- | --- |
| OI source authority | `data/processed/oi_full_history_v2` (`RUNTIME_AUTHORITATIVE`, reuse), reader `oi_dataset_v2.oi_state_at_ms` (PIT-causal, timestamp-scoped) |
| OI transformation | relative change over 24h, same time of day (5m slot for slot) |
| `oi_now` | `sum_open_interest` at the last observation with `timestamp_ms <= T` (staleness ≤ **600 s**, else `NO_SIGNAL`) |
| `oi_reference` | `sum_open_interest` at the last observation with `timestamp_ms <= T − 24h` (staleness ≤ **600 s**; must be `> 0`) |
| lookback | fixed 24h (`86400000` ms) |
| minimum observations | 2 (one eligible PIT observation per endpoint) |
| expansion definition | `oi_change_24h = oi_now/oi_ref − 1`; **EXPANSION ⇔ `oi_change_24h > 0` (strict)** |
| crowding definition | EXPANSION **at a decision whose funding is extreme in the direction implying a crowded side** |
| neutral behavior | `== 0` → NOT confirming → `NO_SIGNAL / OI_NOT_EXPANDING` |
| contraction behavior | `< 0` → NOT confirming → `NO_SIGNAL / OI_NOT_EXPANDING` (de-crowding is a different hypothesis) |
| magnitude gate | **NONE** (no invented percentage floor); magnitude sensitivity lives only in the robustness plan |
| field used | `sum_open_interest` (base-asset units); the notional field is not used |
| ledger role | the OI day-validity ledger is **forensic only** and never gates a decision |

## 7. Price context

**`PRICE_CONTEXT = NONE`.** No price feature conditions the signal. Price is read **only** as the execution
anchor (`openTime`, `open`). Rationale: the payer is the crowded perpetual holder and the forcing variables
are carry cost and leverage — not price geometry; and every registered failure in `FAILED_RESEARCH_MEMORY`
(#1, #3, #4, #10, #12) is OHLCV-derived, so a price-rejection leg would re-test a refuted family under a new
name. No filter was added to make the hypothesis look more selective.

## 8. Signal rules

```
SHORT_RULE : z_funding >= +2.0 AND oi_change_24h > 0
LONG_RULE  : z_funding <= -2.0 AND oi_change_24h > 0
NO_SIGNAL  : everything else (explicit, first-class, counted)
```

Deterministic `NO_SIGNAL` precedence (first satisfied reason is recorded):

1. `OUTSIDE_COMMON_WINDOW`
2. `INSUFFICIENT_FUNDING_HISTORY` (< 90 obs in the trailing 60d window)
3. `SCALE_NONPOSITIVE` (MAD = 0 and stdev = 0)
4. `FUNDING_NOT_EXTREME` (`|z| < 2.0`, or the decision settlement absent)
5. `OI_MISSING_OR_STALE` (> 600 s, or after T)
6. `OI_REFERENCE_MISSING_OR_STALE`
7. `OI_REFERENCE_INVALID` (`oi_ref <= 0`)
8. `OI_NOT_EXPANDING` (neutral or contraction)
9. `POSITION_ALREADY_OPEN` (same asset)
10. `INSUFFICIENT_FORWARD_PRICE_DATA` (exit anchor beyond the window end)

Missing, stale, conflicting or degraded data always fails **closed** (`NO_SIGNAL`); nothing is
interpolated, forward-filled, carried forward or synthesized. There is **no discretionary interpretation**.
A signal is emitted only when **no** reason applies.

## 9. Entry

- Anchor: **the first 1h bar whose `openTime` is strictly greater than `decision_time`**; entry price is that
  bar's **open**.
- `entry_time > decision_time >=` every `data_time` used → strictly causal.
- Same-bar entry and same-bar look-ahead are forbidden; the entry bar never informs the decision.
- Deterministic single fill at the bar open; no intrabar model. The entry bar must itself lie inside the
  common window.

## 10. Hold / exit

- **`PRIMARY_HOLDING_PERIOD = exactly 72 hours` (72 bars, 3 days).** ONE primary horizon only.
- Exit anchor: **the 1h bar open at `entry_bar_open_time + 72h`**; exit price is that bar's **open**.
- **Unconditional** exit: no stop, no take-profit, no early exit, no signal invalidation exit.
- Selection basis: the unwind of a levered crowd is a multi-settlement process — 72h spans **9 consecutive
  settlements**, the horizon on which the crowded side has been charged the extreme carry repeatedly, while
  the hold remains event-driven. Chosen from the funding/OI mechanism, **not** from returns.
- Forward-data guard: if the exit anchor would exceed the window end, the candidate is **not emitted**
  (`NO_SIGNAL / INSUFFICIENT_FORWARD_PRICE_DATA`). Positions are never truncated or dropped ex post.
- Alternate horizons (24h/48h/120h) exist **only** in the robustness neighbourhood and can never become the
  primary result.

## 11. Stop / cooldown / overlap

| Policy | Frozen value |
| --- | --- |
| `STOP` | **NONE** |
| `COOLDOWN` | **NONE** |
| `OVERLAPPING_SIGNAL_POLICY` | **SKIP** — a new signal for an asset already holding a position is discarded, never queued or pyramided |
| `SAME_ASSET_REENTRY_POLICY` | re-entry only at a decision instant at/after the previous `exit_time` |
| `MULTI_ASSET_SIMULTANEOUS_POLICY` | assets independent; ≤ 1 concurrent position per asset, ≤ 3 overall; no cross-asset netting |
| position sizing | unit notional per trade; equal-weighted pooling; no compounding, no volatility targeting, no leverage overlay |

These are explicit; nothing is left to a runtime default.

## 12. Funding cashflow accounting

Funding is used as **information** *and* as an **execution cashflow**, and the two uses are separated by
construction — their windows are disjoint, so nothing is double counted:

| Use | Window |
| --- | --- |
| signal information | `funding_time <= decision_time` (trailing 60d, current settlement included) |
| execution cashflow | `entry_time < funding_time <= exit_time` |

A 72h hold **necessarily crosses ≥ 9 settlements**, so cashflow **must** be applied causally and
deterministically: for every certified settlement in `(entry_time, exit_time]`,
`cashflow_return = −direction_sign × funding_rate`. Consequence: a SHORT entered on extreme positive funding
**receives** funding; a LONG **pays** it. The cashflow is therefore systematically favourable to the
hypothesis, which is exactly why `G3_NET_EXPECTANCY_EX_FUNDING > 0` is a **critical gate** — an edge that
exists only with the carry is a carry strategy (the family already refuted as `FAILED_RESEARCH_MEMORY` #8)
and must fail. Cashflow is charged on the entry notional (frozen simplification; deviation O(1e-4), since
settlement sizes are ~1e-4 of notional and nine of them are applied). The cashflow uses the **same certified
funding authority** as the information leg; no reconstructed or third-party series is permitted.

Return definitions: `gross = direction_sign × (exit/entry − 1)`;
`net = gross + funding_cashflow − cost`; `net_ex_funding = gross − cost`. Both net variants are always reported.

## 13. Cost model (frozen before discovery)

`PRIMARY_ROUND_TRIP_COST_BPS = 10` — the **total** round-trip friction as a single canonical number (not
decomposed into per-side fees/slippage). Frozen evaluation scenarios: **0, 10, 20, 40 bps** — these are
*frozen evaluation scenarios, not optimization choices*; the primary gates use 10 bps, and 20/40 bps also
serve as a critical cost-sensitivity gate. Funding cashflow is never netted into the cost number.

## 14. PIT contract

Authority: `ARC01_PIT_CONTRACT.json` (status `PASS`). Frozen invariants:

- `funding_time <= decision_time`; `funding_availability_time <= decision_time`
  (`availability == settlement == funding_time`; `next_funding_time` is never read as an observation).
- `oi_time <= decision_time` (V2 causal, timestamp-scoped).
- `price_time <= decision_time`; only completed bars; no forward-filled close leakage.
- Only **completed windows** inform a decision. The decision hour's own close is never used.
- **Future mutation invariance:** mutating any observation strictly after T cannot change eligibility,
  feature state or signal input at T (non-vacuous baseline verified).
- **Past-eligible mutation detection:** mutating an eligible observation inside the window must change the
  feature state at T, so no stale cache or retroactive revision can freeze a decision.
- **Archive completeness is non-retroactive:** the OI day-validity ledger is forensic only; a later archive
  arrival can never validate or invalidate a historical decision.
- Conflicting duplicates fail closed; stale or missing authority fails to `NO_SIGNAL` per the frozen rules.

## 15. Sample rules

min funding observations **90** · min OI observations **2** (one per endpoint) · min trades per asset **40** ·
min total trades **120**. Insufficient sample ⇒ `INSUFFICIENT_SAMPLE` (terminal FAIL-class): no window
extension, no threshold relaxation, no asset reselection to chase N. All minimums were fixed before any result.

## 16. Statistical discovery gates

Eleven **critical** gates; **no single metric is sufficient** — PASS requires all of them:

| Gate | Requirement |
| --- | --- |
| G1 sample | total ≥ 120 and every asset ≥ 40 |
| G2 net expectancy | `> 0` at 10 bps (funding cashflow included) |
| G3 net expectancy **ex funding cashflow** | `> 0` at 10 bps |
| G4 profit factor | net `≥ 1.15` |
| G5 Sharpe | annualized net Sharpe `≥ 0.50` |
| G6 Sharpe uncertainty | bootstrap 95% CI lower bound of the mean net return `> 0` (10,000 i.i.d. resamples, seed 20260915) |
| G7 permutation | sign-flip permutation p `≤ 0.05` (10,000 draws, seed 20260915) |
| G8 temporal stability | both halves `> 0` **and** ≥ 3 of 4 quartiles `> 0` |
| G9 asset stability | ≥ 2 of 3 assets `> 0` |
| G10 concentration | max asset share ≤ 60%, max month share ≤ 40%, max single-trade share ≤ 25% |
| G11 cost sensitivity | `> 0` at 20 bps **and** `≥ 0` at 40 bps |

Win rate, mean holding period, trade counts per month and a drawdown diagnostic are **reported but never
gating**. Any unmet critical gate ⇒ `ARC01 = DISCOVERY_FAIL` (terminal).

## 17. Controls (falsification, frozen)

| Control | Definition | Required outcome |
| --- | --- | --- |
| `DIRECTION_CONTROL` | reverse the contrarian direction (trade **with** the crowd) | must **not** pass all critical gates |
| `TIMING_CONTROL` | decision shifted ±8h, breaking funding↔OI/price alignment (each variant still PIT-legal) | neither variant may pass |
| `OI_CONTROL` | funding-only, crowding confirmation removed | must **not** pass — otherwise OI is not load-bearing ⇒ `DISCOVERY_FAIL` |
| `NULL_CONTROL` | identical instants, direction from deterministic `SHA256(20260915:asset:decision_time)` parity | must **not** pass |

Controls are evaluations of the same frozen machinery, **not alternate strategies**, and **cannot be
promoted**; a control outcome may never adjust ARC-01's thresholds, lookbacks, holding period, assets or cadence.

## 18. Robustness plan (frozen, NOT executed now)

Runs **only if** the primary discovery passes all critical gates: R1 time splits (halves/thirds/quartiles +
3-fold walk-forward) · R2 asset splits and leave-one-asset-out · R3 regime splits (funding-regime terciles,
volatility terciles, calendar years; cells with N < 40 are `INSUFFICIENT_SAMPLE`) · R4 cost sensitivity
(0/10/20/40 bps on an identical trade set) · R5 parameter neighbourhood (funding lookback {30d, 60d, 90d},
threshold {1.5, 2.0, 2.5}, OI window {12h, 24h, 48h}, holding {24h, 48h, 72h, 120h}; ≥ 60% of cells must keep
a positive net-expectancy sign) · R6 concentration and leave-one-out · R7 signal-count/reason-code stability.

**Hard constraint:** the primary parameters are immutable; no neighbourhood cell may become the result, and a
majority sign reversal is reported as `PARAMETER_FRAGILITY`.

## 19. Orthogonality plan

ARC-01 will be compared with **H5** (order-flow imbalance), **H6** (OI-confirmed continuation) and
**ARC-02** (BTC→alt lead-lag) under a **later authorized experiment**, using signal-time overlap
(Jaccard ≤ 0.5) and daily net-PnL correlation (`|ρ| ≤ 0.5`), both computed before reading ARC-01's economics.
If H6 comparator evidence is not persisted, the comparison is recorded as
`NOT_EVALUABLE_FROM_PERSISTED_EVIDENCE` and H6 is **not** regenerated. ARC-01 parameters must **not** be
altered in response to an orthogonality or performance result; a failing orthogonality gate is a FAIL-class
outcome for ARC-01, not a redesign prompt. (The registered MEDIUM collision with H6 is the OI axis only; the
two hypotheses predict *opposite* signs from the same expansion state — see the collision review §3.)

## 20. Kill rule (permanent)

**ONE PREREGISTRATION → ONE PRIMARY DISCOVERY.** If primary discovery fails any critical gate:
`ARC01 = DISCOVERY_FAIL` (terminal). **No** threshold retuning, lookback retuning, holding-period retuning,
dropping of losing assets, or second attempt under the same hypothesis id. Any future variant requires a
**NEW_HYPOTHESIS_ID** and a **NEW_PREREGISTRATION**. Spec/manifest hash drift, dataset fingerprint drift or any
execution before this preregistration is verified ⇒ the experiment is **invalid**.

---

## Required artifacts (this checkpoint)

`ARC01_SPEC_V1.json` · `ARC01_MANIFEST_V1.json` · `ARC01_PREREGISTRATION.md` · `ARC01_MECHANISM_EVIDENCE.md` ·
`ARC01_SELECTION_RATIONALE.md` · `ARC01_PIT_CONTRACT.json` · `ARC01_CONTROL_PLAN.json` ·
`ARC01_STATISTICAL_GATES.json` · `ARC01_ROBUSTNESS_PLAN.json` · `ARC01_FAILED_MEMORY_COLLISION_REVIEW.md` ·
`ARC01_PREREG_VERIFICATION_PACKAGE.json` · `RUN_REPORT.json` · `RUN_REPORT.md`
(+ `scripts/verify_arc01_prereg.py`, `src/trading_bot/research/arc01/prereg_reference.py`,
`tests/unit/research/test_arc01_preregistration.py`)

## Next step

`ARC01_INDEPENDENT_PREREG_VERIFICATION` — an **independent** verifier (not DeepSeek) must reproduce the
bindings, the PIT contract, the control plan, the gates and the immutability check before any economic
execution of ARC-01 may be authorized.
