# Runtime authority map

Who owns each decision this work package reasons about, and the line that says so. Each row was resolved by searching the named file for the named symbol: an unresolved row is a gap, not a convention.

| stage | component | resolved at | owns | does not own |
| --- | --- | --- | --- | --- |
| signal_calculation | `def machine_for` | `src/trading_bot/research/economic_recovery/pit15.py`:575 | the rule: one object per family, fed closed bars only, one construction site | prices, sizes or admission — a machine emits a decision and nothing else |
| closed_bar_availability | `def period_ms` | `src/trading_bot/research/economic_recovery/pit15.py`:88 | the bar's own spacing and therefore the instant its close becomes available | the venue's clock: the series defines the period, not an assumption of one hour |
| ohlc_simulator | `def check_positions_ohlc` | `src/trading_bot/paper/broker.py`:398 | whether a resting stop or target was touched, and the order of an ambiguous bar | an intrabar path: the policy (stop_first) is enforced and the residual gap optimism is declared |
| paper_broker_fills | `def execute_signal` | `src/trading_bot/paper/broker.py`:221 | fills, commissions, position ids and the cash/realised/unrealised identities | which bar is executable: the driver owns the clock and passes the price |
| portfolio_and_risk | `def check_signal` | `src/trading_bot/risk/manager.py`:147 | approval, refusal, sizing, exposure clamps, loss limits and the kill switch | the cost model and the research restatement, which never place orders |
| admission | `def is_paper_admitted` | `src/trading_bot/autonomous/admission_ledger.py`:168 | whether a strategy may trade paper at all, from the committed ledger | the research lane's own tag: an experimental lane bypasses it by design and says so |
| scheduler | `def main` | `scripts/edge16_capture.py`:65 | nothing yet: no scheduled job runs this package's collector, and none was created | the collector's execution; the ST6 Windows task belongs to another line and runs every 15 min |
| prospective_collector | `--capture` | `scripts/edge15_oos_preregistration.py`:13 | appending newly closed public bars to the frozen holdout slice, idempotently | the schedule: it is a manual command while the disk guard reports INSUFFICIENT_FREE_SPACE |

## What is deliberately unowned

A scheduled collector: no job in this repository runs the prospective capture, and this package created none. The GitHub workflows declare no `schedule:` trigger at all; the only scheduled task that exists on this machine belongs to the ST6 forward-regime line.
