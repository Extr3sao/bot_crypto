# 08 — FUNDING AUTHORITY REPORT — EXECUTION-REALISM-AND-COST-AUTHORITY-01

Machine: `08_FUNDING_AUTHORITY_REPORT.json` · Status: **ADMIT_WITH_LIMITATIONS** (honest)

## Availability

| Symbol | Historical coverage | Source | Fingerprint | PIT safe? |
|---|---|---|---|---|
| BTCUSDT | **2019-09-10T08:00Z → 2026-09-09T16:00Z** · 7,670 rows · cadence 8h 100% (7669 intervals) | `binanceusdm /fapi/v1/fundingRate` paginated `startTime 1000/page` | `8b0e796c808158cc...` | **Yes** (`fundingTime <= decision_time` contract; canonical `FUNDING-UNITS-CANONICAL-V1`) |
| ETHUSDT | 90 rows `INSUFFICIENT_DATA` (most-recent fetch, not full paginated) | same, single page 2024 | none | not admitted deep |
| SOLUSDT | same 90 rows | same | none | not admitted deep |

File: `docs/external-audit-01/carry-funding-deep-01/BTCUSDT_FUNDING_DEEP.jsonl` (sha `81936d1b`), `D1_DATA_FINGERPRINT.json` pinned `2026-09-09T21:39:33Z`. ETH/SOL deep not yet admitted — hence H6 `FUNDING_EXCLUDED_WITH_LIMITATION` is correct.

## Provider / semantics

- Provider `binanceusdm` public `fapi/v1/fundingRate` (no creds).
- Fields: `{symbol, fundingTime(epoch ms), fundingRate(decimal), markPrice?, nextFundingTime?, time}`.
- Semantics: `fundingTime` is the instant the rate applies (PIT boundary); schedule **00:00, 08:00, 16:00 UTC** every 8h.
- Sign: positive = **longs pay shorts** (shorts receive).
- PIT invariant: decision at `t` may only use rows with `fundingTime <= t`.

## 21 — Funding materiality (deterministic, synthetic only)

Contract: `src/trading_bot/execution_realism/funding.py`

```python
funding_cost_usdt(position_notional, direction, funding_rate, held_across_funding_event)
funding_cost_bps(funding_rate, held_across) -> rate*10000
funding_events_in_holding(entry_ms, exit_ms, interval=8h) -> count
```

| Input | Behavior |
|---|---|
| `held_across_funding_event=false` | `0.0` (no charge) |
| `long + rate 0.0001 (1bp), held` | `+1.0 USDT` per 10k notional (cost) |
| `short + rate 0.0001, held` | `-1.0 USDT` per 10k (income) |
| 1h holding (H6: `entry bar open → close`, exactly 1h) | **typically 0 funding events** unless the 1h bar straddles `00/08/16:00 UTC`. Helper `funding_events_in_holding(entry_ms, exit_ms)` counts `0 or 1`; for a full 1h, max 1 event iff the window contains `00/08/16:00` |

Examples: entry `07:00`→exit `08:00` = **1 event** (08:00 settlement); `00:30→01:30` = **0**; `08:00→09:00` (entry at boundary exclusive) = **0**.

## H6 implication

H6 `EXCLUDED_WITH_LIMITATION + funding_materiality_gate_before_promotion=true` is **the right preregistration**: cannot assume `0` forever; for a 1h next-bar hold, funding materiality is **conditional** — zero unless the bar straddles settlement, at which point `≈ last fundingRate` (observation 2026-09-12: `~0.36 BTC / 0.50 ETH / 0.41 SOL bps` per 8h). A future promotion must audit this — see 12.

## Status

`ADMIT_WITH_LIMITATIONS` (BTC deep admitted; ETH/SOL require `EXECUTION-DATA-ADMISSION-01` for deep funding backfill with paginated validation).
