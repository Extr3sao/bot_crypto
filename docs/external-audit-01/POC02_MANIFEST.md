# POC02 Preregistration Manifest — PAPER-02

> **Status: PREREGISTERED — NOT LAUNCHED.** Per checkpoint rules, POC02
> must not start until explicitly allowed by campaign timing/governance
> (TRACK E). This manifest freezes the experiment BEFORE any POC02 result
> exists. No threshold here was chosen after observing outcomes.

| Field | Value |
| --- | --- |
| campaign_id | `POC-02-paper-clean-01` |
| start_utc | **TBD — set at launch authorization** |
| end_utc | **TBD — start + 21 counted days** |
| duration | 21 counted UTC days (min), plus burn-in |
| burn_in_days | 1 (excluded from KPIs) |
| assets | BTC, ETH, SOL |
| strategies_eligible | Momentum, Trend, Breakout, MeanReversion, Volatility (unchanged POC01 set) |
| cadence | unchanged from POC01 runtime (deterministic cycle) |
| shadow_enabled | **true** (`RiskGateRouter` + `ShadowCaptureHook` wired into Risk-REJECT arm) |
| live | **DISABLED** (`live_trading_enabled: false`) |

## E1 — Provider authority (explicit, never just "Binance")

| Role | Value | Why |
| --- | --- | --- |
| MARKET_DATA_PROVIDER | `binanceusdm` (public REST OHLCV + funding) | PIT-fetchable, no credentials |
| EXECUTION_MODE | `PAPER` | no venue connectivity |
| EXECUTION_VENUE_MODEL | `PaperBroker` (repo `trading_bot.paper`) | deterministic fills, protocol costs |

The UI must label these three fields separately. A "Binance" label without
the `PAPER` + `PaperBroker` qualifiers is a misrepresentation and is
treated as FALSE_SUCCESS.

## E2 — Coverage contract (declared BEFORE launch)

| Item | Contract |
| --- | --- |
| expected cycles/day | runtime cadence × 1440 min (recorded per day) |
| minimum acceptable coverage | **≥ 0.80 observed/expected minutes** per counted day |
| runtime outage handling | auto-detect via heartbeat; on restart, existing resume contract; gaps recorded per UTC day, midnight-clipped |
| provider outage handling | provider failures counted; ≥ 3 consecutive failures marks the affected window `DATA_GAP` |
| day invalidation semantics | **unchanged from the canonical validity contract** (`docs/paper-trading-methodology.md`); coverage is evidence, not a new threshold |
| valid-day definition | FINALIZED ∧ COUNTED ∧ VALID (trade-count independent — DEF-POC01-OBS-006 semantics) |
| frequency KPI | `DAYS_GE_3` / `COMPLETED_VALID_DAYS` (zero-trade valid days count in denominator) |

## E3 — Shadow enabled

- Every VERIFIED candidate reaching Risk is routed through
  `RiskGateRouter` (ACCEPT → PAPER as today; REJECT → immutable
  `ShadowCandidateCapture`, later PIT resolution to `ShadowTrade`).
- PAPER decisions are **unchanged**; shadow is observational only.
- Isolation targets: `SHADOW_PAPERBROKER_CALLS = 0`,
  `SHADOW_RISK_MUTATIONS = 0`, `SHADOW_ACCOUNTING_CONTAMINATION = 0`.

## Immutable references at freeze time

| Artifact | Hash / Value |
| --- | --- |
| risk policy | `config/risk.py::Risk` (current defaults; hash recorded at launch config export) |
| cost model | `ExecutionCostModel(commission_bps=5.0, slippage_bps=1.0)` — POC01 values unchanged |
| confirmation lock | `CONF-EDGE-002-001` untouched (window 2026-09-08→2026-09-22) |
| discovery intake | Discovery Batch 01 results are RESEARCH ONLY; no candidate promoted |

## Launch gate (to be executed at authorization, not before)

1. Fill `start_utc` / `end_utc`.
2. Export the exact runtime config; record `risk_policy_sha256` and
   `cost_model_sha256` in the campaign state.
3. Verify shadow hook mounts and writes to a separate ledger path.
4. Verify `LIVE_CALLS = 0` plumbing before the first scan.
