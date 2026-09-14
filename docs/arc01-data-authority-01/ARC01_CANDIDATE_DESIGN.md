# ARC-01 Candidate Design — Limited (non-economic) Scope

**Checkpoint:** `ARC-01-FUNDING-AUTHORITY-01`  
**Status:** `UNFROZEN_PENDING_PREREG_DESIGN` (no thresholds optimized, no backtest, no economics observed)  
**Data authority prerequisite:** `PASS` (funding `5f4845f50…`, canonical `34f736b1…`, OI `16779b7d2eff`, price `e1c2462a6aa9`)

This document formalizes the **non-economic mechanism** only, after data authority is understood. It defines
inputs, causal features, decision timeframe candidates based on data cadence, mechanism, invalidation conceptually,
and required controls — but leaves threshold/lookback/holding-period **UNFROZEN** until a separate preregistration.

---

## 1. Inputs (adopted data contracts only)

- **Funding** — `data/processed/arc01_funding/{BTC,ETH,SOL}_funding.jsonl` (authorized above; 8h settlements; PIT at settlement).
- **Crowding / OI context** — `data/processed/oi_full_history_v2/{BTC,ETH,SOL}/` hourly eligibility-scoped OI changes (5m cadence aggregated to hourly robust_z) — reuse `REUSABLE`.
- **Price / OHLCV** — `data/processed/price_1h_v2/{BTC,ETH,SOL}_1h.jsonl` — reuse `REUSABLE`.

No other market data is assumed admitted. No reconstruction from third parties.

---

## 2. Causal features (definition — no threshold choice)

- **Funding crowding pressure** — per-symbol funding-rate level and its trailing deviation conditioned on availability:  
  `funding_rate_at(T)` is the last settlement with `funding_time_ms <= decision_time_ms`.  
  Features will be *functions* of the causal history (e.g. z-score vs trailing median/MAD), not of an optimized percentile.
- **Positioning / OI state** — causal OI change and its robust normalization (H6's `robust_z` family — already PIT-true at `decision_time_ms`), used as the **positioning context** that funding alone failed to predict without (FAILED_RESEARCH_MEMORY.md #8).
- **Price-rejection context** — 1h/5m price exhaustion (failed continuation) as the third leg of the hypothesis. Defined qualitatively now; the prereg will freeze which bar aggregation and which rejection shape (not tuned here).

All features respect `availability_time_ms == funding_time_ms` and `oi_time <= decision_time`.

---

## 3. Decision timeframe candidates (driven by data cadence, not returns)

Available cadences (from inventory):

- Funding settlements: every **8h** (00:00, 08:00, 16:00 UTC, with ±50 ms jitter; SOL 2022-11 was 2h/4h per `funding_interval_hours` — PIT-safe but noted).
- OI: every **5m**, aggregated to **1h** eligibility buckets by the V2 causal reader.
- Price: every **1h** (5m not separately admitted for this candidate's horizon).

**Candidate decision buckets** (no holding period chosen here):

- Funding-driven bucket: **8h** (natural funding settlement cadence).
- OI/price reading bucket: **1h** (H6 heritage; price-rejection operates at 1h).
- Prereg will freeze which bucket is the tradable decision and which bar the fill lands on (strictly `bar_time > decision_time`).

No lookback window (e.g. 30-day OI robust_z window) is frozen here; the data's native cadences nominate candidates, not observed profitability.

---

## 4. Mechanism (conceptual — funding / crowding unwind)

> Extreme derivatives crowding + funding pressure + a price-rejection tells that **crowded leveraged holders may unwind**, producing an **unwind / mean-reversion** episode opposite the crowded direction.

- Who pays (per ARU `who_pays`): crowded perpetual traders (long-funding payers or stressed shorts).
- The conditioning variable that prior funding-only tests lacked (memory #8: funding basis alone failed, `PF 1.062`, inconsistent) is **OI / participation + price exhaustion**.

This remains a qualitative mechanism claim — not a tuned signal.

---

## 5. Invalidation logic (conceptual — not an observed gate yet)

- In the future frozen prereg, the null will be `net expectancy <= 0, PF <= 1, or single-asset concentration` (mirroring ARU 09 kill) or an equivalent fixed kill independent of observed returns.
- No season/exchange/asset sweep is planned.

---

## 6. Required controls (to freeze at prereg)

- Execution cost: **10 bps round-trip** (ARU frozen cost for ARC-01); no funding carry synthesis needed beyond the observed settlement rate.
- Single decision per funding settlement; one asset at a time or portfolio-level exclusivity will be frozen (not tuned).
- Exactly-once semantics inherited from H6 governance (already frozen).

---

## 7. What is NOT frozen here

| Parameter class | Value | Reason |
|---|---|---|
| Funding extreme threshold / percentile | `UNFROZEN_PENDING_PREREG_DESIGN` | Cannot be justified without observing outcomes; snooping risk. |
| OI / positioning level threshold | `UNFROZEN_PENDING_PREREG_DESIGN` | Same |
| Price-rejection shape (e.g. failed-breakout bar) | `UNFROZEN_PENDING_PREREG_DESIGN` | Same |
| Holding horizon (`next-bar` vs `8h` vs `12 bars`) | `UNFROZEN_PENDING_PREREG_DESIGN` | Same |
| Asset selection (BTC/ETH/SOL subset) | `UNFROZEN_PENDING_PREREG_DESIGN` | Same |
| Lookback windows (funding trail, OI robust_z) | `UNFROZEN_PENDING_PREREG_DESIGN` | Same but bounded by data cadence above |
| Direction rule conditioning order | `UNFROZEN_PENDING_PREREG_DESIGN` | Mechanism is conjunctive — pruning order not data-mined here |

Freezing any of these by looking at future returns before preregistration is **prohibited**.

---

## 8. Verification posture

- `ARC01_BACKTESTS = 0` — no backtest run.
- `ARC01_EXECUTIONS = 0` — no live/paper execution.
- `ARC01_PERFORMANCE_OBSERVED = false` — no PnL/Sharpe/win-rate inspected.

The next step before any economics is a standalone `ARC-01-PREREG` that freezes the undecided items above with fixed values (no grid) — outside this data-authority workstream.

---

## 9. Related records

- Data authority: `docs/arc01-data-authority-01/ARC01_DATA_INVENTORY.json`, `ARC01_FUNDING_MANIFEST.json`, `ARC01_COMMON_CAUSAL_WINDOW.json`
- PIT: `docs/arc01-data-authority-01/ARC01_PIT_AUTHORITY.json`
- Universe / queue: `docs/alpha-research-universe-01/{05,09,…}.json` (frozen at `e7f470d`)
