# RUN_REPORT — EXECUTION-REALISM-AND-COST-AUTHORITY-01

```
WORKTREE: .worktrees/execution-realism-01
BRANCH:   audit/execution-realism-01
BASE:     0941082fc875a66287d2b09159112963141bcf27 (H6-REPAIR-CLOSE-01, NOT_EXECUTED)
STATUS:   PASS_WITH_EVIDENCE_GAPS (execution realism foundation proven; STRESSED/SEVERE UNKNOWN until spread P99 + real slippage measured)
```

## Key verdicts (10 questions §45)

| # | Question | Answer | Authority |
|---|---|---|---|
| 1 | How does PaperBroker fill today? | **Signal/last price ± 1bp slippage per leg** — `LONG entry signal*(1.0001) / SHORT signal/1.0001 / LONG exit /1.0001 / SHORT *1.0001`; immediate deterministic full qty; `PaperPosition(entry_price=fill + commission stored)`; close at `SL/TP` with `both_hit stop_first` (conservative) | `paper/broker.py` SRC-PAPER-001 |
| 2 | Spread? | **Not included** — `bid/ask/mid` unused; `spread=0` assumed. Snapshot 2026-09-12 low-vol: **BTC 0.013 / ETH 0.039 / SOL 0.98 bps RT** (5× each stable). Historical `UNAVAILABLE`. | `05` SRC-SPREAD-001 |
| 3 | Slippage? | Paper **synthetic 1bp/leg (2 RT)** via `entry_slippage_price/exit_slippage_price` (always adverse). **Real `NOT_MEASURED`** (LIVE 0, R2 intent ledger is paper-only 3 intents). | `06` SRC-EXEC-001 |
| 4 | Fees correct? | **Yes** — `5+5=10 fee RT` matches Binance **VIP0 taker+taker** official `2/5 (5+5 RT 10)`; with slippage paper is `12 RT`. `planned_net_rr()` does `fees+slip` correctly. Config `spot` is legacy — fee market pinned as `usdm` in authority. | `04` SRC-FEE-001 |
| 5 | Funding? | **Not included** in paper (honest `EXCLUDED_WITH_LIMITATION`). BTC deep **7670 rows 2019-09-10→2026-09-09 8h 100%** admitted (fp `8b0e79`, sha `81936d1b`); ETH/SOL deep missing. H6 1h holding: `0 or 1` funding event (~12.5% of bars straddle `00/08/16 UTC`, `~0.36-0.50 bps/8h` live sample). | `08` SRC-FUND-* |
| 6 | Latency? | **Not modeled** — decision→fill `0 ms` simulated (synchronous in-process); `NETWORK_LATENCY NOT_MEASURED`; `FeedDeadManGuard` exists unused; adverse-move contract `50ms-5s` exists with coverage `None`. | `07` |
| 7 | Partial fills? | **Not modeled** — always 100%; `L2` unavailable. | `03` |
| 8 | Optimistic assumptions | `ZERO_SPREAD / MIDPRICE_FILL / ZERO_LATENCY / NO_PARTIAL_FILL / ZERO_FUNDING / NO_MARKET_IMPACT` | `10` gap analysis |
| 9 | Realistic cost range supported | **IDEALIZED 10.00 → BASE 10.01/10.04/10.98 (fee+spread at snapshot) → paper 12.01/12.04/12.98 (+2 slip) → STRESSED/SEVERE UNKNOWN** (needs spread `P90/P99` + real slippage). Funding adds `0 or ~0.4 bps` iff `1h bar` straddles settlement. | `09` |
| 10 | H6 10 bps obviously optimistic/conservative? | **APPROXIMATELY_REALISTIC to OPTIMISTIC** — fee exact for VIP0 taker; slightly optimistic for SOL even at low-vol spread; optimistic vs any `P90/P99` or real slippage. Not conservative; not judgeable for stressed regimes until data gap closed. | `09/04` |
| 11 | What data missing? | **ADOPT_P0**: funding deep ETH/SOL parity. **ADOPT_P1**: `bookTicker bid/ask` archiver (spread `P99`). **EXPERIMENT**: aggTrades sampled `250ms-5s` adverse (full 100 GB rejected without `COST_REVIEW`), `premiumIndex`. **DEFER**: L2 depth. | `11` |
| 12 | Minimum upgrade before PAPER profitability cert | **(a)** funding parity + **(b)** `bookTicker` spread archiver until `P99` + **(c)** decision→fill timing (VenuePort) before any `PAPER` profitability claim may clear `12_EXECUTION_REALISM_GATE NET>0`. Until then: `COST_SENSITIVE` or `INSUFFICIENT`. | `11/12/15` |

## Authority contracts produced

- `ExecutionCostAuthority` (§24) + `ExchangeExecutionProfile` portable (fee tier) + `CostComponent/CostScenario (IDEALIZED/BASE/STRESSED/SEVERE)` per `09`.
- `ExecutionRealismEstimate.build()` (§25) — unknown propagation: `total=None, missing=[spread,slippage]` when evidence missing, `net_edge=None`.
- `funding_cost_usdt/bps + funding_events_in_holding(entry_ms, exit_ms)` (§21, synthetic only).
- `FalseProfitabilityDetector` (§32, offline: `ROBUST/COST_SENSITIVE/NEGATIVE/INSUFFICIENT/GROSS_NEGATIVE`; synthetic + authorized histories only).
- `AdverseMoveHorizons (50ms..5s)` (§19, coverage explicit; no sub-second from 1h bars).

## Existing paper diagnostic (§28, diagnostic-only)

- R2: 3 `INTENT_EXECUTED` (2026-09-10 BTC buy/sell ETH sell) with `intent_cloid`; `0 closed_trades` in snapshot (insufficient for re-accounting → `INSUFFICIENT_EXECUTION_EVIDENCE`, correct). No `ClosedTrade` overwritten.
- Shadows 11 `PROFITABLE_REJECT mean 0.39R` are **not** trades (`Risk REJECT`, never reached broker).
- Historical `H1 gross -0.003 R PF 0.995 → H3 gross -0.367 PF 0.492 → gross-negative ⇒ NEGATIVE_AFTER_COSTS (WORSE)` — never rescued as viable (§33).

## Non-interference proof (§39)

Pre-work `sha256` for no-touch zone re-verified after work (STATE_BEFORE == STATE_AFTER):

| Artifact | SHA256[:16] |
|---|---|
| `H6_SPEC_V2.json` | `221cfa1d6eb3dae3` |
| `H6_MANIFEST_V2.json` | `5f9aba446686a32b` |
| `OI_MANIFEST_V2.json` | `24160d1c8eb42dc6` |
| `PRICE_V2_MANIFEST.json` | `c7726cc1b64fed99` |
| `CONFIRMATION_LEDGER_V2.jsonl` | `188290908fe4765c` |
| `SHADOW_CAPTURES` (worktree) | `2c9dc5cb0add0a81` |
| `config/{exchange,risk,runtime}.yaml` | unchanged |

Risk thresholds, sizing, leverage, live config, confirmation, shadow history untouched; no `H6/H5/confirmation/live` executed.

## Defects (14) & roadmap (15)

See `14_EXECUTION_REALISM_DEFECTS.json` (8 defects: `ER-SPREAD-001 MEDIUM`, `ER-SLIPPAGE-001 MEDIUM`, `ER-PAPER-001 MEDIUM`, `ER-FUNDING-001 MEDIUM`, `ER-LATENCY-001 MEDIUM`, `ER-FEE-001 LOW`, `ER-IMPACT-001 LOW`, `ER-RECONCILE-001 INFO`) and `15_IMPLEMENTATION_ROADMAP.md` priority-ranked `ADOPT_P0 (funding parity) > ADOPT_P1 (bookTicker) > ask/bid fills > Venue-timed fills > aggTrades sampled`.

```
FALSE_SUCCESS=0  H6_EXECUTIONS=0  H6_BACKTESTS=0  PERFORMANCE_OBSERVED=false  LIVE/RISK_CHANGED=0
```

## Next (§49)

- If funding+spread gaps stay open: `NEXT = EXECUTION-DATA-ADMISSION-01` (minimum necessary `bookTicker + funding deep`).
- Once sufficient: `NEXT = EXECUTION-REALISM-PAPER-INTEGRATION-RFC-01` (design/prepare integration only — do not yet change PaperBroker, §27).
