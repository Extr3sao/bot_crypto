# G-7 — PAPER execution report

**Runtime:** `PaperOrchestrator → PaperSessionRunner → PaperCycleEngine`  
**Broker:** `DurablePaperBroker` over `PaperStateStore`  
**Recovery:** `StartupReconcilerV4`  
**Admission:** `config/strategy_admission.json` (0 admitted)  
**Execution class:** `PAPER_ONLY_REAL_PUBLIC_DATA`

## 1. Circuit exercised

```text
Binance public REST capture
  → ReplayMarketDataSource (HISTORICAL_REPLAY) / forward capture (FORWARD)
  → UniverseScanner (CandleFilter)
  → CryptoAssetAgentRegistry (PIT context)
  → StrategyRouter.select_eligible_strategies
      → 0 selected
  → PaperCycleEngine rejection: NO_TRADE:no_strategy_passed_gates
  → RiskManager: not reached
  → HotStopGate.order_boundary: not reached
  → DurablePaperBroker.execute_signal: not called
  → PaperStateStore: durable empty book
  → StartupReconcilerV4: RECOVERED / CONSISTENT
```

The engine did **not** bypass the router to force a family invocation. The
strategies were not “evaluated for a signal” because none is allowed to reach
signal generation: `strategy_invocations=0` in every session. This is the
correct fail-closed behaviour.

## 2. Replay decisions

| Session | Decision (UTC) | Contexts | Router NO_TRADE | Signals | Risk accepted | Orders | `execute_signal` | Reconciliation |
|---|---|---:|---:|---:|---:|---:|---:|---|
| replay-1 | 2026-10-25T16:55:00 | 3 | 3 | 0 | 0 | 0 | 0 | CONSISTENT |
| replay-2 | 2026-10-25T17:00:00 | 3 | 3 | 0 | 0 | 0 | 0 | RECOVERED |
| replay-3 | 2026-10-25T17:05:00 | 3 | 3 | 0 | 0 | 0 | 0 | RECOVERED |
| replay-restart | 2026-10-25T17:05:00 | 3 | 3 | 0 | 0 | 0 | 0 | RECOVERED |

Every rejection is explicit:

```json
{"symbol": "BTC/USDT", "stage": "router",
 "reason": "NO_TRADE:no_strategy_passed_gates"}
```

and repeats for ETH/USDT and SOL/USDT.

## 3. Forward decision

| Field | Value |
|---|---|
| Received at | 2026-10-25T17:19:46.823Z |
| Decision at | 2026-10-25T17:19:46.823Z |
| Snapshots | 3 × `FORWARD` / `OK` |
| Contexts | 3 |
| Router NO_TRADE | 3 |
| Signals / orders | 0 / 0 |
| `execute_signal` / `close_position` | 0 / 0 |
| Reconciliation | CONSISTENT |

Total across the replay, restart and forward: **5 decisions, 15 contexts,
15 router `NO_TRADE`, 0 signals, 0 orders, 0 broker calls.**

## 4. Durable state

After the replay and restart:

| Field | Value |
|---|---:|
| State file | `replay/paper_state.json` (488 bytes) |
| Open positions | 0 |
| Closed trades | 0 |
| Sent intents | 0 |
| Orders | `[]` |
| Equity | 10,000.00 |
| Restart reconciliation | `RECOVERED` |
| `duplicate_intents` | 0 |

The restart opened a new broker/engine/reconciler over the same file. It
recovered the empty book, placed no order and left the state unchanged. A
durable book with zero economic effect is the honest result of zero eligible
strategies.

## 5. Why there is no PAPER_TRADE

The decision outcome is `NO_TRADE`, not `BLOCKED` and not `FAILED`, because the
runtime itself worked: data was valid, context was built, the router ran, and
the rejection was explicit. The blocker is upstream of the runtime: the ledger
admits no strategy.

A trade would have required one of these illegitimate actions, none of which
was taken:

- editing `config/strategy_admission.json` to set `admitted_for_paper=true`;
- passing the G-5 `CONTROLLED_TEST_FIXTURE` ledger as if it were production;
- adding a synthetic signal or bypassing the router;
- lowering `RouterGates.require_confirmed`.

## 6. Broker path evidence (controlled, not G-7 eligibility)

The canonical broker path is already proven by G-5's
`tests/integration/test_g5_paper_end_to_end.py`: with a fixture ledger
explicitly labelled `CONTROLLED_TEST_FIXTURE`, the same `PaperCycleEngine`
opens one position, persists it, restarts, reconciles and closes it. G-7
intentionally does **not** reuse that fixture for its real-data campaign,
because that would turn reachability evidence into a false eligibility claim.

## 7. Safety

| Claim | Evidence |
|---|---|
| No live client | no exchange SDK object in the path; payload `exchange_clients_constructed=false` |
| No credentials | public endpoints only; `authenticated=false` in the journal |
| No real order | `order_sent=false`; broker is `DurablePaperBroker` |
| No duplicate order | `duplicate_orders=0`; `duplicate_intents=0` |
| No bypass | router verdicts are explicit; `strategy_invocations=0` |
| LIVE gate unchanged | `src/trading_bot/execution/live_gate.py` SHA-256 `edabd6d3…` |
| Hot stop unchanged | `src/trading_bot/autonomous/hot_stop.py` SHA-256 `76cfca23…` |
