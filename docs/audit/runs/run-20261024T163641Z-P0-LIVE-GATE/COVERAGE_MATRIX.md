# P0 — coverage matrix

`ENTRYPOINT → GATE → BROKER SINK`

Revision under test: `efd97e76` (implementation commit `6c90b21d`).
Instrumentation: `scripts/audit/p0_live_gate_probe.py` in a subprocess; every
exchange client is a recorder. No socket is opened.

## 1. Risk-opening paths

| ID | Entrypoint | Gate consulted at entry | Gate consulted at the sink | Broker sink | Before (`96e211bd`) | After (`efd97e76`) | Evidence |
|---|---|---|---|---|---|---|---|
| P1 | `run --mode live --auto-trade --market-kind futures` | yes (`_cmd_run`, before the scanner) | yes (`_maybe_execute_live_futures_trade` → boundary) | `BitunixFuturesClient.place_order` | 1 call, exit 0 | **0 calls**, exit 2 | `after/run-futures-GATE-003.json` |
| P2 | `run --mode live --auto-trade --market-kind spot` | yes | yes (`_maybe_execute_live_trade`) | `MultiExchangeConnector.create_order` | 1 call, exit 0 | **0 calls**, exit 2 | `after/run-spot-GATE-003.json` |
| P3 | `place-order --market-kind futures --trade-side OPEN` | yes (before the client exists) | yes | `BitunixFuturesClient.place_order` | 1 call, exit 0 | **0 calls**, exit 2 | `before/place-order-futures-GATE-00N.json`, `after/place-order-futures-GATE-00N.json` |
| P4 | `place-order --market-kind spot --side buy` | yes | yes | `BitunixSpotClient.place_spot_order` | 1 call, exit 0 | **0 calls**, exit 2 | `after/place-order-spot-GATE-003.json` |

Before, the gate was constructed **zero** times on every row. After,
`gate_validations >= 1` on every row.

## 2. Reduction and protection (exempt by design)

| ID | Entrypoint | Gate | Sink | Before | After | Evidence |
|---|---|---|---|---|---|---|
| P5 | `run --auto-trade` stale-futures flatten | not consulted | `flash_close_position` | 1 call | **1 call**, exit 0 | G-3 suite (`test_reduction_and_protection_still_reach_the_broker`) |
| P6 | `place-order --trade-side CLOSE --reduce-only` | not consulted | `place_order` | 1 call | **1 call**, exit 0 | `after/place-order-futures-close-GATE-004.json` |
| P7 | `place-order --market-kind spot --side sell` | not consulted | `place_spot_order` | 1 call | **1 call**, exit 0 | `after/place-order-spot-sell-GATE-004.json` |
| P8 | `close-position` | not consulted | `flash_close_position` | 1 call | **1 call**, exit 0 | `after/close-position-GATE-004.json` |
| P9 | `set-tpsl` | not consulted | `place_position_tpsl` | 1 call | **1 call**, exit 0 | `after/set-tpsl-GATE-004.json` |

The gate is rejected (GATE-004, no credentials) in every P6–P9 run, so the
1 call proves the exemption, not a permissive environment.

## 3. Paths that cannot open exposure

| ID | Path | Why it is not gated | Status |
|---|---|---|---|
| P10 | `run --demo` → `paper/paper_cycle.py` | paper broker; G-4 scope | unchanged, still uncovered |
| P11 | `run --mode live` without `--auto-trade` | no dispatch site | scanner only |
| P12 | `BitunixFuturesClient.cancel_order` / spot `cancel_order` | no entrypoint reaches it (G-3) | unreachable |

## 4. The ten checks, one row each

`after/place-order-futures-GATE-00N.json`, legal live configuration except the
one field that check validates.

| Check | Broken through | Broker calls | Exit | Gate id in stderr |
|---|---|---|---|---|
| GATE-001 | `mode=live`, `live_trading_enabled=false` | 0 | 2 | yes |
| GATE-002 | `kill_switch_enabled=false` | 0 | 2 | yes |
| GATE-003 | `max_risk_per_trade_pct=0` | 0 | 2 | yes |
| GATE-004 | empty API key/secret | 0 | 2 | yes |
| GATE-005 | `sandbox=true` with `mode=live` | 0 | 2 | yes |
| GATE-006 | SQLite parent directory missing | 0 | 2 | yes |
| GATE-007 | `runtime.exchange_id=""` | 0 | 2 | yes |
| GATE-008 | `risk.live_trading_enabled=true` | 0 | 2 | yes |
| GATE-009 | forced failure of `_check_logging` | 0 | 2 | yes |
| GATE-010 | forced failure of `_check_risk_limits` | 0 | 2 | yes |

GATE-009/010 cannot fail through configuration; the probe forces a failure on
the real class. GATE-006/008 are severity `high` in the gate and would pass
`GateReport.all_passed`; P0's rule (`failed_gates == 0`) refuses them, and the
verifier V-9 re-derives that from the export.

## 5. Fail-closed cases

| Case | Entrypoint | Calls | Exit | Evidence |
|---|---|---|---|---|
| `load_settings` raises | `place-order-futures` | 0 | 2 | `after/settings-error-place-order-futures.json` |
| `load_settings` raises | `run-futures` | 0 | 2 | `after/settings-error-run-futures.json` |
| `validate` raises | `place-order-spot` | 0 | 2 | `after/gate-crash-place-order-spot.json` |
| `validate` raises | `run-spot` | 0 | 2 | `after/gate-crash-run-spot.json` |
| report has 9 checks | in-process | n/a | refused | verifier V-9 |
| marker + rejected gate | `place-order-futures` | 0 | 2 | verifier V-8, stderr names the stop |
