# WP-EDGE-04R — session independence: what this host allows

Each mechanism below was **attempted**, not assumed: the probe's own output is in
`evidence/SESSION_INDEPENDENCE.json`. Verdicts are `VIABLE` (exercised here), `NEEDS_ELEVATION`,
`NEEDS_CREDENTIALS`, `NOT_APPLICABLE`.

| mechanism | verdict | what it needs |
| --- | --- | --- |
| `AUTOMATIC_LOGON` | `NEEDS_CREDENTIALS` | automatic logon re-creates the session after a reboot and requires the account password to be stored on the machine; this work package holds no credential and will not acquire one |
| `S4U_TASK` | `NEEDS_ELEVATION` | S4U runs whether or not a session exists and stores no credential; it needs the 'log on as a batch job' right, which this process cannot grant itself |
| `SESSION_LOGON_TRIGGER` | `VIABLE` | the LogonTrigger is additive: it does not remove the session absence, it bounds the recovery from it, and it is registered in the same scheduler the lane already uses |
| `TASK_SCHEDULER_OPERATIONAL_LOG` | `NEEDS_ELEVATION` | with this log disabled, a trigger that fired and could not start a process leaves no host-side record at all: that is why one of the 221 instants in this window ends as SILENT_UNATTRIBUTABLE instead of as a cause |
| `WAKE_TO_RUN` | `NOT_APPLICABLE` | the task is already registered with WakeToRun=false, and the host recorded no sleep or standby in the window, so there is nothing for this setting to recover |
| `WINDOWS_SERVICE` | `NEEDS_ELEVATION` | creating a service needs administrator rights; not attempted, and not needed if an S4U task is available, because both remove the session dependence equally |
| `WITNESS_ACTION` | `VIABLE` |  |

Viable without new privileges: SESSION_LOGON_TRIGGER, WITNESS_ACTION.
Blocked: AUTOMATIC_LOGON, S4U_TASK, TASK_SCHEDULER_OPERATIONAL_LOG, WINDOWS_SERVICE.

## What each one buys, priced from the audit

* **Trigger loss in the measured window:** 24 triggers lost to an absent session, 1 unattributable.
* **Worst measured recovery after a sign-in:** 321.41 s.
* **Logon trigger:** it bounds the recovery from a sign-in to the trigger delay; the absence itself is untouched, so it recovers minutes, not the hours the absence consumed
* **S4U:** the session dependence disappears: the 24 triggers lost to NO_SESSION would be scheduleable. It is blocked on the batch-logon right, so it needs an operator with administrator rights.
* **Witness action:** the 1 trigger(s) that end as SILENT_UNATTRIBUTABLE would become attributable, without needing the Task Scheduler's operational log

## The definition this package would apply, and what the rehearsal found

`evidence/PROPOSED_FORWARD_TASK.xml` — 4784 bytes, sha256 `3ae22b847ee65f92aaa1e34024913964df07aef4f7238565da91cd1682ddd91e`. It is rendered from the lane's own registration, so applying it changes which instants can start and nothing about what the lane does when it starts:

* carried over: task_name=TradingAgentic-EDGE04-Forward, user_id=GVLLFR0035, logon_type=InteractiveToken, logon_type_as_the_scheduler_reported_it=Interactive, interval_minutes=15, command=C:\Users\GVLLFR0035\Downloads\bot freebuff\.venv\Scripts\python.exe, arguments="C:/Users/GVLLFR0035/Downloads/bot freebuff/scripts/edge04_observer.py" --scheduled --due, working_directory=C:\Users\GVLLFR0035\Downloads\bot freebuff, wake_to_run=False
* added: LogonTrigger, enabled, delay PT60S, additive to the existing TimeTrigger; a witness Exec ahead of the lane's action

| rehearsal (`TradingAgentic-EDGE04R-Probe-Proposal`) | measured |
| --- | --- |
| verdict | `VIABLE` |
| trigger kinds the scheduler reported back | MSFT_TaskLogonTrigger, MSFT_TaskTimeTrigger |
| actions, in the order they run | 2 |
| witness line written before the long action | True |
| task deleted after the rehearsal | True |
| lines the rehearsal moved from the committed definition | 2 |

The rehearsal registers a copy of the committed definition whose only difference is the action payload: running the lane's own action there would let a rehearsal write an out-of-phase tick into the ledger this audit measures, so it carries `cmd.exe /c exit 0` instead. Everything else — both triggers, the principal, the settings, the order of the actions, the witness path — is the committed bytes.

## What was not applied, and why

the live task is left exactly as WP-EDGE-04 registered it: re-registering a running lane's task changes the phase the audit measures and is a deployment decision for the operator, not a side effect of an audit

The command that would apply it, once an operator decides to: `schtasks /create /tn "TradingAgentic-EDGE04-Forward" /xml "reports/edge-recovery/WP-EDGE-04R/evidence/PROPOSED_FORWARD_TASK.xml" /f` — it re-registers the live task (in place, `/f`), so it stays an operator decision: `schtasks /create /tn "TradingAgentic-EDGE04-Forward" /xml <definition with both triggers> /f`

## The honest bound

No mechanism available to this work package removes the cost of the host being unavailable or of nobody being signed in. The measured window lost 24 triggers to an absent session; the only two mechanisms that would have scheduled through it are an S4U task (needs the batch-logon right) and automatic logon (needs a stored password). Everything else recovers minutes around the edges.

Research only: public market data, no credentials, no orders, no capital, no promotion.
