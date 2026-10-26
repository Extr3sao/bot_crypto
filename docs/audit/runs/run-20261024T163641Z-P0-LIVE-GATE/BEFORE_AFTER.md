# P0 — BEFORE / AFTER

Same probe, same settings, same entrypoints. The only difference is the commit.

| | BEFORE | AFTER |
|---|---|---|
| Revision | `96e211bd` | `efd97e76` |
| Gate importer in `src/` | none (`LiveTradingGate` never constructed) | `app.py` (`_evaluate_live_gate`) |
| Gate constructed on a live entry | 0 times | 1–2 times per entry |
| Rejected configuration, `place-order` | **1 broker call, exit 0** | **0 calls, exit 2** |
| Rejected configuration, `run --auto-trade` | **1 broker call, exit 0** | **0 calls, exit 2** |
| Reduction with a rejected gate | 1 call, exit 0 | 1 call, exit 0 |

## The ten checks, before and after

Every row uses a live configuration in which exactly one check rejects.

| Check | Before: calls / gate validations / exit | After: calls / gate validations / exit | Gate named in stderr |
|---|---|---|---|
| GATE-001 | 1 / 0 / 0 | **0 / 1 / 2** | yes |
| GATE-002 | 1 / 0 / 0 | **0 / 1 / 2** | yes |
| GATE-003 | 1 / 0 / 0 | **0 / 1 / 2** | yes |
| GATE-004 | 1 / 0 / 0 | **0 / 1 / 2** | yes |
| GATE-005 | 1 / 0 / 0 | **0 / 1 / 2** | yes |
| GATE-006 | 1 / 0 / 0 | **0 / 1 / 2** | yes |
| GATE-007 | 1 / 0 / 0 | **0 / 1 / 2** | yes |
| GATE-008 | 1 / 0 / 0 | **0 / 1 / 2** | yes |
| GATE-009 | 1 / 0 / 0 | **0 / 1 / 2** | yes |
| GATE-010 | 1 / 0 / 0 | **0 / 1 / 2** | yes |

Raw files: `before/place-order-futures-GATE-00N.json`,
`after/place-order-futures-GATE-00N.json`.

## Entrypoints

| Entrypoint | Before | After |
|---|---|---|
| `run-futures` (GATE-003 rejected) | 1 call, exit 0 | 0 calls, exit 2 |
| `run-spot` (GATE-003 rejected) | 1 call, exit 0 | 0 calls, exit 2 |
| `place-order-spot` buy (GATE-003 rejected) | 1 call, exit 0 | 0 calls, exit 2 |
| `place-order-futures` (legal config) | 1 call, exit 0 | 1 call, exit 0 |

## Reduction is not the regression

With GATE-004 rejected (no credentials), all four reduction paths still send:

| Path | Before | After |
|---|---|---|
| `close-position` | 1 call | 1 call |
| `set-tpsl` | 1 call | 1 call |
| `place-order --trade-side CLOSE --reduce-only` | 1 call | 1 call |
| `place-order --market-kind spot --side sell` | 1 call | 1 call |

`gate_validations = 0` on all four after-runs: the exemption is structural, not
an accident of a configuration that happened to pass.

## Fail closed

| Case | Calls | Exit |
|---|---|---|
| `load_settings` raises, `place-order-futures` | 0 | 2 |
| `load_settings` raises, `run-futures` | 0 | 2 |
| `LiveTradingGate.validate` raises, `place-order-spot` | 0 | 2 |
| `LiveTradingGate.validate` raises, `run-spot` | 0 | 2 |

## FALSE_SUCCESS

For every after-run with a rejected gate, stdout carries no `LIVE_ORDER_OK`,
`FUTURES_ORDER_OK` or `"success": true`. `after/SUMMARY.json` records
`false_success: false` on each of the ten rows.
