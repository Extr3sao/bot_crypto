# 03 — PAPERBROKER REALISM AUDIT — EXECUTION-REALISM-AND-COST-AUTHORITY-01

Machine: `03_PAPERBROKER_REALISM_AUDIT.json` · Base `0941082` · Source: `SRC-PAPER-001`

## How PaperBroker fills today (traced)

| Question | Answer | Evidence |
|---|---|---|
| Fill price source for **LONG entry** | `signal.price * (1 + slippage_bps/10000)` — **last/signal price worsened by slippage** | `broker.py:execute_signal slippage_mult; fill_price = signal.price * slippage_mult` |
| SHORT entry | `signal.price / (1 + slippage_bps/10000)` — signal price worsened | same, `else fill_price = signal.price / slippage_mult` |
| LONG exit | `exit_price / (1 + slippage_bps/10000)` | `_close_position actual_exit = exit_price / slippage_mult` for buy |
| SHORT exit | `exit_price * (1 + slippage_bps/10000)` | same for sell |
| Uses bid / ask / mid / last? | Uses **last/signal price only** (no bid/ask/mid). Spread **not modeled**. | grep: `bidPrice/bidQty/askPrice` only in observability probe `strategy_runtime_authority_map.md` §survey, not in `paper/broker.py` |
| Bar open/close vs tick? | Tick-signal price + slippage; exits via `check_positions(price)` (close) or `check_positions_ohlc(high,low)` (TP/SL by high/low) | `broker.py:check_positions` vs `check_positions_ohlc` |
| Immediate deterministic fill? | **Yes** — no queue, no delay, no partial fills | `execute_signal` returns `PaperPosition` immediately; fills_opened++ |
| Slippage default | `1 bp` per leg (2 bps RT) | `PaperBroker(slippage_bps=1.0)`; `ExecutionCostModel` same default |
| Fee default | `5 bps` per leg (10 bps RT) | `PaperBroker(commission_bps=5.0)` |
| Total default RT | **12 bps** (10 fee + 2 slippage) — *slightly more conservative than H6 10 bps discovery* | 5+5+1+1 |
| PnL accounting | `gross = f(slippage prices) * qty`; `net = gross - entry_commission - exit_commission`; `equity += net`; `ClosedTrade.pnl == net` | `_close_position` |
| Position sizing | `notional = signal.metadata.notional_usdt or 1% equity`; `qty = notional / fill_price` | `execute_signal` |
| Opposite side? | Closes opposite existing `symbol` via `_close_position("signal")` | `execute_signal` |
| Same side duplicate? | Skipped (`paper.skip_duplicate`) | same |
| Funding? | **Not included** | grep: `funding` absent in `paper/broker.py` |
| Latency? | **Not modeled** (zero) | no sleep/timestamp delta |
| Partial fills? | **Not modeled** | always full qty |
| Rejects? | Only duplicate-skip; no liquidity/venue rejects | same |

## Entry realism by side

- **LONG buy @ signal=100.00, default 1bp:** fill `100.01` (signal *1.0001). `notional 1000` → qty `99.99`; commission `0.50` stored. Unrealistic: would be `ask` or `ask+sippage` → `mid + half-spread + slippage`. Ignores current `0.013 bps BTC / 0.039 ETH / 0.98 SOL` spread (2026-09-12 snapshot, low-vol).
- **SHORT sell @ signal=100.00:** fill `99.99` (signal /1.0001). Same issue — should reference `bid`.

## Exit realism

- `check_positions(prices:{close})` only hits TP/SL if `close` equals the level — **under-triggers** in gap bars (next section corrects via OHLC).
- `check_positions_ohlc(high,low)` correctly uses `low <= SL / high >= TP` for LONG and converse for SHORT with `stop_first` (conservative). Fill is at `SL` or `TP` level (not beyond), with exit slippage applied (correct: worse fill).

## Unrealistic assumptions (for gap analysis)

- `ZERO_SPREAD_ASSUMPTION` — spread is zero (mid≈bid≈ask).
- `ZERO_LATENCY_ASSUMPTION` — decision→fill is instant.
- `ZERO_PARTIAL_FILL` — always 100% immediately.
- `ZERO_FUNDING_ASSUMPTION` — funding never charged (H6 `EXCLUDED_WITH_LIMITATION`; paper same).
- `MIDPRICE_FILL_ASSUMPTION` — signal=mid assumed executable, not bid/ask.
- `NO_MARKET_IMPACT_MODEL` — `impact = 0` regardless of notional (paper `min 20 max 500 USDT` small but not proven zero).
- Fees: not a defect — model exists, but PAPER defaults `5+5=10 bps RT` vs Binance VIP0 `2+2=4 bps maker-maker / 5+5=10 bps taker-taker`. At taker-taker, fee matches H6 10 bps; slippage adds 2 bps beyond price.

## Verdict

`PaperBroker` is **deterministic, conservative on SL (stop_first), true-net PnL, and idempotent** — but **optimistic on spread, latency, partial fills, and impact**. Spread live is `~0.013-0.98 bps` round-trip (instant snapshot, low-vol); realistic RT cost today is therefore `~10-11 bps fee+spread` plus slippage/impact/latency. Full hermetic `1299 passed` includes this behavior.
