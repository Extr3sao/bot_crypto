# WP-9C — runtime rehearsal (24 h window: prepared and driven, not completed)

> `WINDOW_INCOMPLETE` · 0.0621 h of 24 h (0.26%) · generated `2026-10-11T20:52:51Z`

Entrypoint: `scripts/autonomous_paper.py` — the same one the lab launcher starts as its `paper` child. Provider `ccxt` (read-only public market data).

## 1. The declaration, first

* window complete: **False**
* stability declared: **False** — a window shorter than the target cannot pass a stability test, and the checks the short window could not reach are reported as NOT_EXERCISED rather than PASS
* paper authorisation: NOT_AUTHORIZED — this is a read-only market-data rehearsal, not the contractual paper test

## 2. Legs

| leg | what it exercises | exit | seconds | traces added | RSS max | CPU s |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| 1-interval-cadence | free-running loop: the cadence that loses part of its cycles to the freshness gate | 0 | 51.953 | 6 | 148.844 MB | 1.391 |
| 2-bar-close-cadence | phase-aligned to sealed bars: the cadence that keeps the same budget | 0 | 69.157 | 2 | 148.627 MB | 1.422 |
| 3-controlled-stop | stopped through the runtime's own STOP file (§51), which must exit zero | 0 | 49.375 | 4 | 149.299 MB | 1.563 |
| 4-resume-after-stop | the same run id, run root and state path, after the controlled stop | 0 | 53.031 | 6 | 148.832 MB | 1.578 |

## 3. Freshness per cadence

Budget: 1.5 bars of 5m = 450 s (the runtime's own constant, imported, not restated).

| leg | evaluations | age min/max ms | outside the budget | share | router reasons |
| --- | ---: | --- | ---: | ---: | --- |
| 1-interval-cadence | 6 | 490134 / 537736 | 6 | 1.0 | stale_context |
| 2-bar-close-cadence | 2 | 305006 / 305006 | 0 | 0.0 | — |
| 3-controlled-stop | 4 | 311555 / 335463 | 0 | 0.0 | — |
| 4-resume-after-stop | 6 | 360914 / 409551 | 0 | 0.0 | — |

## 4. Checks

| check | result | detail |
| --- | --- | --- |
| decisions are persisted and the trace chain is intact | `PASS` | 18 persisted records, links intact; the runtime's own summary agrees |
| no look-ahead: every decision consumed only sealed bars | `PASS` | every one of 18 traces has window_end_ts <= decision_time_ms (window_end is the newest bar's open, so the sealed bar closes before the decision) |
| the freshness gate is enforced: a late context cannot reach a proposal | `PASS` | max age 537.7 s against a 450 s budget (1.5 bars of 5m); 6 of 18 evaluations were late, 6 of them were rejected by the router for exactly that reason, and 0 produced a proposal |
| the strategy router ran and never selected a candidate that emitted no alpha | `PASS` | 108 candidate evaluations, statuses ['NOT_APPLICABLE', 'REJECTED'], 6 distinct strategies |
| the risk engine reviewed every proposal (deterministic, binding on orders) | `NOT_EXERCISED` | no evaluation carried a proposal, so the binding path was never entered: 18 rows are NO_TRADE with risk ['NOT_APPLICABLE']; the runtime reviews risk only when there is something to review (§3 of the runtime document) |
| the independent verifier graded the decisions it was asked to grade | `NOT_EXERCISED` | verifier verdicts ['NOT_RUN']: a NO_TRADE row with no proposal is not sent to the verifier, so this branch is NOT_EXERCISED in a window whose router rejects everything |
| the agents were reachable from the live path | `NOT_EXERCISED` | 0 agent message(s) recorded; with no proposal the registry is never consulted, so the live window cannot prove the agents are reachable and says so |
| checkpoint and resume: a later run continues the same chain | `PASS` | paper_state.json exists=True; leg 2-bar-close-cadence continued from record 6 and added 2; leg 3-controlled-stop continued from record 8 and added 4; leg 4-resume-after-stop continued from record 12 and added 6 |
| every evaluation is accounted for and no order was created | `PASS` | 18 evaluations across 4 leg(s), 0 runtime failure(s), 0 order(s), 0 production action(s) |
| replay reconstructs each decision without reading the market again | `PASS` | 1-interval-cadence: 6/6 ok, failed=0, market_data_accessed=False; 2-bar-close-cadence: 8/8 ok, failed=0, market_data_accessed=False; 3-controlled-stop: 12/12 ok, failed=0, market_data_accessed=False; 4-resume-after-stop: 18/18 ok, failed=0, market_data_accessed=False |
| no hidden critical error, and the cycle latency is measured | `PASS` | 0 error(s) in the leg reports; 9 cycle(s) with latency min 2487 ms / max 5743 ms |
| the executed window's flow coverage matches its own records | `PASS` | stages reached: scan and bar history fetched 18/18, regime and context built 18/18, router consulted 18/18, proposal built 0/18, agents consulted 0/0, risk engine evaluated 0/0, independent verifier ran 0/0, decision persisted to the trace chain 18/18, order created (TRADE_PAPER) 0/18, broker reconciliation / outcome resolved 0/0; not exercised in this window: agents consulted, independent verifier ran, proposal built, risk engine evaluated (the router admitted no candidate that emitted alpha; which stages a real window reaches depends on the market, so the rest is reported, not asserted) |
| the window reached the 24 h the operator asked for | `NOT_EXERCISED` | 0.0621 h executed of 24.0 h (0.259% of the target): the rehearsal is prepared and driven, the window is not complete, so no stability verdict is issued |

`13` checks, `0` failed, `4` not exercised by the executed window.

## 5. Governance

* orders created: **0**
* `LIVE_TRADING = DISABLED`, `TRADES_AUTHORIZED = 0`, `FALSE_SUCCESS = 0`
* not claimed: 24 h of continuous operation; profitability; the contractual paper test; any branch of the flow the executed window never entered

