# WP-EDGE-12B — how the observer could be started without a session

**Generated:** 2026-10-16T06:20:12Z · **Selected:** `LOGON_TRIGGER`

> prefer the mechanism that removes the dependence and stores no credential; fall back to the additive mechanism that bounds the loss instead of the one that would require a credential or a privilege this package does not have

**Outcome:** the host refused the S4U registration of this very definition, so the mechanism that removes the dependence is not available to this process; the logon trigger is the strongest available one and is already exercised

## 1. The mechanisms RFC-EDGE-012 names

| mechanism | verdict | what the host said |
| --- | --- | --- |
| `S4U_TASK` | `NEEDS_ELEVATION` | Error: Acceso denegado. |
| `AUTHORISED_SERVICE_ACCOUNT` | `NO_ACCOUNT_DESIGNATED` | no account in this inventory is designated for the lane, and granting a right to an existing account is a change to this host's policy, which this package does not make |
| `WINDOWS_SERVICE` | `NOT_ATTEMPTED_NEEDS_ELEVATION` | creating a service needs administrator rights; a refused attempt can leave a half-created service behind, and this package does not change the host |
| `INDEPENDENT_HOST_RUNNER` | `NO_AUTHORISED_INFRASTRUCTURE_FOUND` | no SSH configuration, no known remote host and no self-hosted runner declaration was found in this checkout; a runner on another host stays a documented option for an operator who has one, not a mechanism this package ca |
| `LOGON_TRIGGER` | `VIABLE` | the LogonTrigger is additive: it does not remove the session absence, it bounds the recovery from it, and it is registered in the same scheduler the lane already uses |

### 1.1 The S4U attempt, in full

The probe registers **this definition** — both triggers, the witness action, the lane's
own principal — with `LogonType=S4U`, reads it back, runs it on demand and deletes it.
The question an operator asks is not whether S4U exists; it is whether *this* definition
can be registered that way from an unelevated process.

|  |  |
| --- | --- |
| registration accepted | False |
| waited for input | False |
| password stored | False |
| read-back logon type |  |
| read-back trigger kinds | — |
| ran on demand | False |
| task left behind | False |
| host answer | Error: Acceso denegado. |

The same attempt with a bare `cmd.exe` task:

* verdict `NEEDS_ELEVATION`, registration accepted False, waited for input False
* host answer: Escriba la contrase¤a de ejecutar como para DIRECTORI\GVLLFR0035:

### 1.2 The mechanisms that need an operator

| mechanism | why not attempted here | what it would buy |
| --- | --- | --- |
| `WINDOWS_SERVICE` | creating a service needs administrator rights; a refused attempt can leave a half-created service behind, and this package does not change the host (token elevated: False) | the session dependence, and with it the need for any account to be signed in; it is the same effect as an S4U task at a larger price |
| `AUTHORISED_SERVICE_ACCOUNT` | no account in this inventory is designated for the lane, and granting a right to an existing account is a change to this host's policy, which this package does not make (9 account(s) listed, 0 designated) | a principal whose rights are granted on purpose, instead of borrowed ones |
| `INDEPENDENT_HOST_RUNNER` | no SSH configuration, no known remote host and no self-hosted runner declaration was found in this checkout; a runner on another host stays a documented option for an operator who has one, not a mechanism this package can exercise | a host that is not this one, which removes both the session and the volume from the equation |

Automatic logon is not in the table because it is not attempted at all: it would require
storing the account password on the machine (0 is `AutoAdminLogon` on this host), and this package holds no credential and will not acquire one.

## 2. The levers already in the registration

Two settings are additive and were never priced by the previous pass. Both are visible
in the lane's own run log, which is what makes them measurable rather than arguable.

| lever | value | measured effect in this window |
| --- | --- | --- |
| `StartWhenAvailable` | True | 4 off-phase scheduled launch(es) of 248 |
| `RestartOnFailure` | count=3, interval=PT5M | 0 follow-up(s) at the policy's own interval |
| `MultipleInstances` | IgnoreNew | the second trigger changes nothing |

> a run recorded as SCHEDULED is invoked with the scheduler's own arguments, which is also what an on-demand `schtasks /run` does; the Task Scheduler operational log that would separate them is disabled on this host, so an off-phase launch is reported as off-phase and not attributed to a mechanism

> it converts a start missed while the host was unavailable into a catch-up run when the host returns; it does not help a start that could not run because no session existed, which is the loss this campaign is actually about

## 3. Preflight: what an operator can check before applying anything

`PREFLIGHT_PASS` — 13 check(s), 0 blocking failure(s).

| check | verdict | detail |
| --- | --- | --- |
| `definition_carries_a_time_trigger` | PASS | trigger elements: ['TimeTrigger', 'LogonTrigger'] |
| `definition_adds_a_logon_trigger` | PASS | trigger elements: ['TimeTrigger', 'LogonTrigger'] |
| `definition_carries_the_witness_action_first` | PASS | 2 action(s), first is the witness: yes |
| `definition_declares_its_logon_type` | PASS | logon types declared: ['InteractiveToken'] |
| `definition_keeps_multiple_instances_ignored` | PASS | MultipleInstancesPolicy='IgnoreNew' |
| `the_action_binary_exists_on_this_host` | PASS | command=C:\Users\GVLLFR0035\Downloads\bot freebuff\.venv\Scripts\python.exe |
| `the_working_directory_exists_on_this_host` | PASS | working_directory=C:\Users\GVLLFR0035\Downloads\bot freebuff |
| `the_interpreter_is_the_interpreter_that_certified_this_package` | PASS | the same interpreter WP-EDGE-12A measured the entry points under |
| `the_witness_path_is_writable` | PASS | witness=C:\Users\GVLLFR0035\Downloads\bot freebuff\reports\edge-recovery\WP-EDGE-12\evidence\forward-witness.txt |
| `the_volume_is_above_the_guard_critical_floor` | PASS | 7.5355 GiB free against a critical floor of 2.0 GiB |
| `the_definition_keeps_the_live_cadence_phase` | PASS | live boundary 2026-10-13T13:25:53 vs definition 2026-10-13T13:25:53 |
| `the_target_task_name_is_the_lane_own` | PASS | task_name=TradingAgentic-EDGE04-Forward |
| `no_probe_task_was_left_behind_by_this_pass` | PASS | the scheduler was asked, not the probe's own delete call |

> every item is a read of this host; applying the definition stays an operator action, and the rollback is written before it is needed

## 4. What was not applied, and why

The live task is left exactly as WP-EDGE-04 registered it. Re-registering a running
lane's task moves the phase a continuity reading measures, which makes it a deployment
decision for an operator rather than a side effect of a certification. The probes used
throwaway names and the count of tasks they left behind is measured:
**0 left behind**.

Research only: hypothetical marks, no orders, no capital, no promotion.
