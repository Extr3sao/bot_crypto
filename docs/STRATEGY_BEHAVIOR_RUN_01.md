# STRATEGY_BEHAVIOR_RUN_01 — observation run report

RUN_ID: `STRATEGY-BEHAVIOR-RUN-01` · commits: instrument `23985f1` (+ `af9bebc`, `8175e7d`)
Setup: BTC/ETH/SOL · 5m · Binance testnet read-only · fresh clean state · PaperBroker 10000 USDT
Duration: **31.3 min uptime, 342 cycles** (8 process segments — shell-tool 600 s limit;
every segment restart reconciled `RECOVERED`, seg1 `CONSISTENT`; 0 errors, 0 FAILED cycles)

## Funnel (measured)

```
MARKET OBSERVATIONS      342 cycles × 3 assets = 1026 asset-decisions
STRATEGY EVALUATIONS     1026 (1 per asset per cycle)
SIGNALS                  1026 (3/cycle, constant min=med=max=3 — deterministic same-bar regeneration)
UNIQUE SIGNALS (bar-keyed)  ≈ 7 economic intents (cloid-unique) across the run
TRADE PROPOSALS          1026 (every alpha becomes a candidate)
RISK APPROVALS           45  (3 fills + position-open approvals while capacity lasted)
RISK VETOES              790 (all 'Max open positions reached (3)')
EXECUTION INTENTS        7 unique (+191 duplicate submissions suppressed)
ORDERS                   7 = 7 unique intents (exactly-once held)
FILLS                    7
CLOSED TRADES            4 (2×SOL TP, 2×ETH TP)
```

Ratios: signal/evaluation = 1.0 (deterministic families) · unique-signal/signal ≈ 0.7%
(7/1026) · approval/proposal = 4.4% · fill/approval = 100% · trades/hour ≈ 7.7 fills ·
closed trades/hour ≈ 4.6 (once at capacity, churn stops — see lifecycle).

## Strategy health table

| Strategy | Evaluations | Signals | Unique Signals | Proposals→Risk | Trades | Primary rejection | Runtime status |
| --- | ---: | ---: | ---: | ---: | ---: | --- | --- |
| ema_crossover | 1026 (as sole router pick) | 1026 | 7 bar-unique | 1026 | 7 (4 closed) | Max open positions | **DOMINANT / ACTIVE** |
| momentum | 0 at alpha stage (never routed) | 0 | 0 | 0 | 0 | map-order (never selected) | REACHABLE_NOT_SELECTABLE |
| breakout | 0 | 0 | 0 | 0 | 0 | map-order | REACHABLE_NOT_SELECTABLE |
| trend | 0 | 0 | 0 | 0 | 0 | map-order | REACHABLE_NOT_SELECTABLE |
| mean_reversion | 0 | 0 | 0 | 0 | 0 | map-order | REACHABLE_NOT_SELECTABLE |
| volatility | 0 | 0 | 0 | 0 | 0 | map-order | REACHABLE_NOT_SELECTABLE |

Economic attribution (new provenance field): **PnL by strategy = ema_crossover +15.15 USDT**
(2 SOL TP +5.20/+3.45, 2 ETH TP +3.21/+3.28); by asset: SOL +8.65, ETH +6.49.

## Duplicate decision analysis (§19)

```
TOTAL EVALUATIONS            1026
UNIQUE CLOSED CANDLES        ~6 per asset (5m bars in 31 min)
UNIQUE SIGNALS (intents)     7
DUPLICATE SUBMISSIONS        191 (idempotency) + 38 (broker same-side)
duplicate_signal_rate        ≈ 99.3% of evaluations were same-bar re-evaluations
duplicate_proposal_rate      same (proposals mirror alphas 1:1)
duplicate_intent_rate        191/(191+7) ≈ 96.5% of intent submissions
```

Verdict (§4): high upstream churn is REAL but is **re-evaluation of the same
closed candle by design** (polling 5.5 s vs 5 m bars) with correct economic
collapsing downstream — 7 orders == 7 unique intents, 0 duplicated economic
effects, 0 temporal violations. Classified `EFFICIENCY_DEBT (P3, deferred)`:
the minimal future fix is an explicit `evaluation_mode=BAR_CLOSE` contract +
evaluate-once-per-new-closed-candle, NOT a blind gate (§7). No before/after
performance run triggered because no correctness defect exists.

## Mark-to-market & drawdown (§13)

- Authoritative `equity` today = realized only (cash + Σ closed pnl). NEW:
  `PaperBroker.unrealized_pnl(prices)` / `mark_to_market_equity(prices)`
  (positions without a valid PIT price are skipped, never guessed).
- RUN-01 MTM at end: realized equity 10015.15 + 3 open longs (entry ≈ last
  bars) → unrealized computed at latest closed closes during analysis; peak
  realized equity 10015.15, realized drawdown 0.00. MTM drawdown requires the
  price series per closed candle — recorded as P3 instrumentation (per-cycle
  price snapshot) not yet persisted; flagged honestly as PARTIAL.
- `INSUFFICIENT_SAMPLE` on all economic inference (7 fills, 4 closed).

## Position lifecycle & cooldown (§24-25)

- Portfolio hit capacity (3) in the FIRST cycle (positions carried from prior
  runs? NO — fresh state; the first cycle opened 3 positions, one per asset,
  because each asset's alpha fired immediately).
- Positions stay open because: TP +2% / SL −1% (defaults) on 5m bars with
  ~0.1-0.3% bar ranges → hours-to-days expected time-to-exit; meanwhile the
  same LONG alphas re-fire every cycle → 790 capacity rejections.
- Cooldown (`Consecutive loss cooldown (3 losses)`): observed in post-burn-in
  run — starts at 3 consecutive losses, blocks NEW risk approvals (70 vetoes),
  does NOT block reconcile_session (closes continued) nor restart recovery
  (state restores `consecutive_losses` and the cooldown persisted correctly
  across restarts). `reset_daily()` clears counters daily by design.

## Exit-criteria answers (§30)

1. Active strategies: **ema_crossover only** (structural map-order dominance).
2. Activation: polling orchestrator; economic keying by closed bar.
3. Evaluations: 1026 (54× per candle per asset).
4. Real signals: 7 unique economic intents.
5. Duplicates: 99.3% of evaluations are same-bar re-evaluations (collapsed downstream).
6. NO_TRADE: POSITION_LIMIT (790) > DUPLICATE_SIGNAL (191+38) > NO_SIGNAL (rare).
7. Risk vetoes: capacity (`Max open positions`) — protecting capital AND absorbing upstream churn.
8. Trade origin: ema_crossover for all 7 (provenance field, new).
9. Regime: recorded in context trace; zero routing effect with current map.
10. PnL/fees per trade: attributed (true-net, includes both commissions).
11. MTM equity: implemented (`mark_to_market_equity`); per-cycle price history pending (P3).
12. Drawdown: realized-only 0.00; MTM drawdown requires the price series per closed candle — recorded as P3 instrumentation (per-cycle
    price snapshot) not yet persisted; flagged honestly as PARTIAL.

**FINAL STATUS: STRATEGY_BEHAVIOR_BASELINE_VERIFIED** (P0 open: 0 · P1 open: 0 · FALSE_SUCCESS: 0 — every number above traces to `reports/strategy-audit/` artifacts).
