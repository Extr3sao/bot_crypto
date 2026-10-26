# G-7 — Real market data report

**Provider:** `binance-public-rest`  
**Base URL:** `https://api.binance.com`  
**Endpoints used:** `/api/v3/klines`, `/api/v3/ticker/24hr`, `/api/v3/ticker/bookTicker`  
**Authentication:** none (`authenticated: false` in every journal row)  
**Order endpoints:** none — the adapter's allowlist contains only the three
public routes above plus `/api/v3/time`, and the client has no order surface.

## 1. Committed capture

| Field | Value |
|---|---|
| File | `docs/audit/fixtures/g7_market_capture.json` |
| Raw SHA-256 | `cad0cd5ce98a27ab17f558928b8024ff357906e443b849382311ee2835df7f53` |
| Canonical capture SHA-256 | `136ed36e45a6a8714786c9976df1b438b72192c06ebe9c010eabd1d99c37e5d7` |
| Schema | `g7-public-capture/v1` |
| Captured at | `2026-10-25T17:09:51.602Z` |
| Timeframe | `5m` |
| Symbols | `BTC/USDT`, `ETH/USDT`, `SOL/USDT` |
| Bars per symbol | 500 |
| First bar open | `2026-10-23T23:25:00Z` |
| Last bar open | `2026-10-25T17:00:00Z` |
| Last bar close | `2026-10-25T17:05:00Z` |

Every symbol carries the 24h quote volume and the book-ticker spread observed
at the same capture. These are real provider values, not reconstructed
turnover:

| Symbol | 24h quote volume (USDT) | Spread (bps) |
|---|---:|---:|
| BTC/USDT | 473,815,475.47 | 0.00124 |
| ETH/USDT | 279,643,626.01 | 0.04246 |
| SOL/USDT | 90,366,908.64 | 0.98150 |

## 2. What was validated

`validate_closed_bars` is applied to the exact rows served at each decision.
It performs no repair:

| Check | Rule | Result on capture |
|---|---|---|
| Closed bar | `bar_open + 5m <= decision_time` | OK |
| Freshness | `decision_time - last_close <= 1.5 × 5m` | replay 0 ms; forward 27.2 s |
| Grid | consecutive timestamps differ by exactly 300,000 ms | OK |
| Order | timestamps strictly ascending | OK |
| Uniqueness | no duplicated timestamp | OK |
| OHLC | finite, `high >= max(open, close)`, `low <= min(open, close)`, `volume >= 0` | OK |
| Integrity | `data_hash` of the exact ordered rows | recorded per snapshot |

The provider journal for the forward session has **9 requests**
(`data_access_forward.jsonl`): one klines, one 24h ticker and one book ticker
for each of the three symbols.

## 3. Replay versus forward

| Property | Historical replay | Forward |
|---|---|---|
| Data source | committed capture | live public provider, captured at `2026-10-25T17:19:46.823Z` |
| `data_mode` | `HISTORICAL_REPLAY` | `FORWARD` |
| Decision instants | `16:55`, `17:00`, `17:05` UTC | `17:19:46.823` UTC |
| Receipt relative to decision | capture is later than the decision (retrospective evidence) | `received_at == decision_time` |
| Bars visible | only bars closed at the decision | only bars closed at the decision |
| Result | 3 × `NO_TRADE` per session | `NO_TRADE` |
| Orders | 0 | 0 |

The replay is **not** presented as a forward session. The forward decision is
taken after the provider answers; it is not back-dated to the last bar close.
The cycle consumes the captured forward rows rather than issuing a second
request after the decision, so no post-decision data can leak into it.

## 4. Dangerous inputs

| Scenario | Mutation | Validation | Outcome |
|---|---|---|---|
| `stale` | decide 10 minutes after the last close | `STALE` (600,000 ms > 450,000 ms budget) | `BLOCKED_DATA`, 0 orders |
| `duplicate` | append the last bar again | `DUPLICATE` (+ `OUT_OF_ORDER`, `GAP`) | `BLOCKED_DATA`, 0 orders |
| `gap` | remove a middle bar | `GAP` | `BLOCKED_DATA`, 0 orders |
| `future` | decide 2.5 minutes before the bar closes | `FUTURE` | `BLOCKED_DATA`, 0 orders |
| `out_of_order` | swap the last two bars | `OUT_OF_ORDER` | `BLOCKED_DATA`, 0 orders |
| `bad_ohlcv` | make `high < low` | `BAD_OHLCV` | `BLOCKED_DATA`, 0 orders |
| provider outage | every fetch raises | `scanner_errors=3`, `total_snapshots=0` | 0 orders |

No scenario falls back to synthetic bars, interpolation, forward-fill or a
cached older window.

## 5. Reproduce

```bash
# deterministic replay from the committed capture
uv run python scripts/audit/g7_real_paper.py \
  --out docs/audit/runs/run-20261025T173625Z-G-7-replay \
  --capture docs/audit/fixtures/g7_market_capture.json \
  --timeframe 5m --assets BTC,ETH,SOL --no-forward

# forward observation (network required)
uv run python scripts/audit/g7_real_paper.py \
  --out /tmp/g7-forward \
  --capture docs/audit/fixtures/g7_market_capture.json \
  --timeframe 5m --assets BTC,ETH,SOL
```

A provider failure is recorded as `BLOCKED_PROVIDER` in the forward section;
it is never converted into a PASS or a synthetic bar.
