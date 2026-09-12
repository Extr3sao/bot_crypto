# 09 — EXECUTION COST MODEL — EXECUTION-REALISM-AND-COST-AUTHORITY-01

Machine: `09_EXECUTION_COST_MODEL.json` · Contracts: `src/trading_bot/execution_realism/{cost_authority,funding,realism_estimate}.py`

## 22 — Taxonomy (TOTAL_COST never hides assumptions)

```
TOTAL_COST  =  EXCHANGE_FEES          (maker/taker on notional, per leg)
           +  SPREAD_COST             (half-spread per leg, full RT = spread_bps)
           +  SLIPPAGE                (beyond mid/ask/bid, adverse fill)
           +  MARKET_IMPACT           (size vs depth; 0 for small paper notionals)
           +  FUNDING                 (8h settlement if held across; see 08)
           +  OTHER (e.g. invalidation delay, weekend gap — not modeled)
```

Each slice is a `CostComponent(bps | None, confidence, source, limitations)`; `UNKNOWN → None` and stays explicit.

## 23 — Scenarios (generic, NOT H6-fitted)

| Kind | Semantics | When valid |
|---|---|---|
| `IDEALIZED` | fees only | always (fee is known) |
| `BASE` | `fees + median observed spread/slippage` | when `median` has evidence |
| `STRESSED` | `fees + P90 friction` | needs `P90` (spread or slippage) evidence |
| `SEVERE` | `fees + P99 / conservative bound` | needs `P99` / bound |
| `UNKNOWN` | insufficient evidence — do NOT fabricate | current for `P90/P99` |

Exact `bps` must come from evidence; otherwise `UNKNOWN`.

## 24 — ExecutionCostAuthority (diagnostic, NOT wired into production)

```python
ExecutionCostAuthority(
  authority_id, provider="binance", market="usdm", asset,
  profile=ExchangeExecutionProfile(maker_bps, taker_bps, vip, bnb),
  valid_from, valid_to, scenarios=(IDEALIZED/BASE/...), source_refs, confidence, limitations
)
```

`ExchangeExecutionProfile` carries the exchange-specific fee tier (portable, §37). Generic mechanics live in the authority; no Binance hardcoding in the generic path. Future: `Bybit/OKX` profiles alongside.

Canonical profiles (fee authority §4): `BINANCE_USDM_VIP0` (`2/5 bps RT 10 taker, 4 maker`) and `BINANCE_USDM_VIP0_BNB` (`1.8/4.5 RT 9`).

## 25 — ExecutionRealismEstimate (per-trade diagnostic)

```python
ExecutionRealismEstimate.build(
  asset, direction, order_type, notional, holding_period,
  fee_cost_bps, spread_cost_bps, slippage_bps, impact_bps, funding_bps,
  other_bps?, source_refs, limitations
) -> ExecutionRealismEstimate(
  ...total_cost_bps (None if any missing), confidence, missing_components, net_edge_bps(gross)
)
```

Unknown components remain explicit: `missing_components = ["spread","slippage"]` ⇒ `total_cost_bps = None`, `net_edge_bps = None`. Confidence degrades with each unknown; no fake total is emitted.

### Current populated authority (evidence-backed, 2026-09-12 low-vol snapshot)

| Asset | IDEALIZED (fee only, HIGH) | BASE (fee+spread at snapshot, MEDIUM) | STRESSED / SEVERE |
|---|---|---|---|
| BTCUSDT | 10.0 bps | **10.01 bps** (`10 fee + 0.013 spread`) | **UNKNOWN** (no P90/P99 spread, no real slippage) |
| ETHUSDT | 10.0 | **10.04 bps** | UNKNOWN |
| SOLUSDT | 10.0 | **10.98 bps** | UNKNOWN |

Add paper synthetic: `+2 bps slippage RT` (`1+1`) yields paper today `12.01/12.04/12.98 bps` (still optimistic — spread is low-vol point sample only; funding `0 or ~0.4 bps` depending on whether `1h bar` straddles settlement, see `08`; impact `0` for `20-500 USDT` paper notionals but `NOT_EMPIRICALLY_ESTIMATED` beyond).

STRESSED/SEVERE remain `UNKNOWN` until `bookTicker` and `aggTrades` depth are archived (11).

## Comparison that matters (§12 — DO NOT CHANGE H6 10 BPS)

| H6 discovery | Realistic at sample (fee+spread) | + paper slippage | Classification |
|---|---|---|---|
| **10 bps TOTAL RT** | 10.01–10.98 bps | 12.01–12.98 bps | **APPROXIMATELY_REALISTIC to OPTIMISTIC** — fee is exact for VIP0 taker; H6 10 bps is *slightly optimistic* once spread added (SOL), and *optimistic* once real slippage/latency/impact replace the `2bps synthetic` with measured `P90/P99`. Not yet _conservative_; not yet judgeable for stressed regimes. |

This does **not** rewrite `H6_SPEC_V2`. It is the `PROMOTION MATERIALITY GATE` input: a future H6 that is `NET>0 @10bps` but `NET≤0 @spread+real-slippage` must `DO_NOT_PROMOTE`.

## Funding note (so total is honest)

H6 1h holding: funding applies only if the 1h bar `entry..exit` contains an 8h settlement (`00/08/16 UTC`). For a 1h bar this is ~`1/8` of days (≈`12.5%` of bars straddle settlement). When it does, cost magnitude `≈ funding_rate` (`~0.36-0.50 bps` per 8h live sample, but historically varies — BTC deep distribution TBD in 11). Diagnostic must apply `funding_events_in_holding(entry_ms, exit_ms) * rate * direction_sign`.

## Confidence

- HIGH: fee `10/9 bps` (official).
- MEDIUM: fee+spread at `2026-09-12` low-vol snapshot (point sample, not distribution).
- LOW/UNKNOWN: everything `P90/P99`, real slippage, impact, latency adverse move.
