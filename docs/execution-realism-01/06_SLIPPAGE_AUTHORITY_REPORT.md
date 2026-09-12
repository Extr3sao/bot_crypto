# 06 — SLIPPAGE AUTHORITY REPORT — EXECUTION-REALISM-AND-COST-AUTHORITY-01

Machine: `06_SLIPPAGE_AUTHORITY_REPORT.json`

## 15 — What the repo preserves (decision vs fill)

| Field | PaperBroker (today) | Real market | Authoritative ledger |
|---|---|---|---|
| `decision_price` | `signal.price` (strategy tick price) | not recorded (no real fills) | `paper_cycle.intent_cloid` + `R2_INTENT_LEDGER 3` (paper only) |
| `intended_price` | same as `signal.price` | — | `Signal.price` |
| `submitted_price` | N/A (paper has no limit) | — | none (no order type) |
| `fill_price` | `signal.price * (1+1bp)` long / `/ (1+1bp)` short entry; exit ` / (1+1bp)` long / `* (1+1bp)` short | not measured | `PaperPosition.entry_price` + `ClosedTrade.entry/exit_price` |
| `fill_timestamp` | second-level `time.time()` at entry/exit | no real fill timestamps | `opened_at / closed_at` floats |
| `slippage_reported` | deterministic `1 bp` per leg (2 bps RT) via `ExecutionCostModel` | **NOT_MEASURED** | `ClosedTrade.pnl - gross` deterministic |

R2 ledger: 3 paper `INTENT_EXECUTED` entries (`2026-09-10 BTC buy/sell, ETH sell`) with `intent_key = date|asset|side|strategy` (paper, not exchange fill).

## Paper vs real

| Type | Value | Separation |
|---|---|---|
| `PAPER_SYNTHETIC_SLIPPAGE` | **1 bp/leg, 2 bps RT** (worsens fill: `entry_slippage_price / exit_slippage_price`) | deterministic, symmetric LONG/SHORT, included in `compute_costs(): entry_slip+exit_slip` inside `total_cost` and `net_pnl = gross - total_cost` |
| `REAL_MARKET_SLIPPAGE` | **`NOT_MEASURED`** | no real exchange fills exist (`LIVE_CALLS=0, real_broker_calls=0`); no `submitted_price→fill_price` delta recorded against a live venue |

Never mixed. `R2 shadow 11 captures` are **not** fills — they are `Risk REJECT` shadows (never reached `PaperBroker`).

## Slippage arithmetic (fee vs slippage separation)

`ExecutionCostModel.compute_costs(notional, entry_price, exit_price, qty, side)`:
- `actual_entry = entry_slippage_price(entry, side)` (worse)
- `actual_exit = exit_slippage_price(exit, side)` (worse)
- `gross = (actual_exit - actual_entry)*qty` (LONG)
- `entry_fee = notional*0.0005 (5bp)`, `exit_fee` same
- `entry_slippage = (actual_entry - entry)*qty` etc., floored at `0.0` (always cost)
- `total_cost = entry_fee+exit_fee+entry_slip+exit_slip`; `net = gross - total_cost`; `total_bps = total/notional*10000`

`PaperBroker` mirrors: entry `_commission_bps=5` stored, exit same, `net = gross - entry_comm - exit_comm`. Exit path also applies slippage via `actual_exit`.

`planned_net_rr()` (`paper/startup_recovery.py` cost-aware admission Phase 11) uses same split: `total = entry_fee+exit_fee+entry_slip+exit_slip` on normalized `1000 USDT` notional.

## Missing for a real slippage distribution

- No `L2 depth` or `aggTrades` turn history attached to fills (trade-flow admission `TRADE_FLOW_DATASET_MANIFEST.json` is **data-admission only**, not linked to fills).
- No `L1 quote` at decision instant (see `05` gap).
- Decision→fill latency is `0` in paper (next paper tick is same process tick).

Therefore: real slippage percentiles `P50/P90/P99` are `UNKNOWN` for any statement like "slippage is 3 bps". Allowed: *"paper synthetic slippage is 1 bp/leg (2 RT); historical real slippage is NOT_MEASURED; observational spread sample provides no slippage estimate beyond the half-spread floor"*.

## Recommendation

Collecting **bookTicker + decision timestamp + fill timestamp** would yield measured slippage (decision price at mid vs fill price). Until then, PaperBroker `1bp` is a placeholder — `BASE/IDEALIZED` must state `slippage=1bp synthetic` and `STRESSED/SEVERE = UNKNOWN` (see `09`).
