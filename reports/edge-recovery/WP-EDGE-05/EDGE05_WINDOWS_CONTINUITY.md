# WP-EDGE-05 — Windows continuity: what the host actually permits

*Task `TradingAgentic-EDGE04-Forward`, read from the platform's own registration. Read-only.*

## The registered settings

| setting | value |
| --- | --- |
| `DisallowStartIfOnBatteries` | `false` |
| `StopIfGoingOnBatteries` | `false` |
| `ExecutionTimeLimit` | `PT1H` |
| `MultipleInstancesPolicy` | `IgnoreNew` |
| `RestartOnFailure` | `{'Count': '3', 'Interval': 'PT5M'}` |
| `StartWhenAvailable` | `true` |
| `IdleSettings` | `{'StopOnIdleEnd': 'true', 'RestartOnIdle': 'false'}` |
| `Enabled_defaulted` | `true (element absent: schema default)` |
| `RunLevel_defaulted` | `LeastPrivilege (element absent: schema default)` |
| `AllowHardTerminate_defaulted` | `true (element absent: schema default)` |
| `WakeToRun_defaulted` | `false (element absent: schema default)` |
| `RunOnlyIfNetworkAvailable_defaulted` | `false (element absent: schema default)` |
| `Hidden_defaulted` | `false (element absent: schema default)` |
| `AllowStartOnDemand_defaulted` | `true (element absent: schema default)` |
| `Priority_defaulted` | `7 (element absent: schema default)` |
| `logon_type` | `InteractiveToken` |
| `run_level` | `LeastPrivilege (element absent: schema default)` |
| `user_id` | `S-1-12-1-2907394642-1261797007-1573842048-3608101379` |
| `start_boundary` | `2026-10-13T13:25:53` |
| `trigger_repetition_interval` | `PT15M` |
| `trigger_duration` | `P3650D` |
| `action_command` | `C:\Users\GVLLFR0035\Downloads\bot freebuff\.venv\Scripts\python.exe` |
| `action_arguments` | `"C:/Users/GVLLFR0035/Downloads/bot freebuff/scripts/edge04_observer.py" --scheduled --due` |

## What that permits, measured or declared

* **logged on user session** — the task runs: the tick has been observed firing unattended on a schedule, without any agent or terminal open
* **screen locked but session alive** — EXPECTED to run — a locked screen does not end the session — and NOT EXERCISED: locking this host's screen would interrupt the person using it, so the work package records the expectation and does not measure it
* **logged off** — does NOT run: LogonType=InteractiveToken means the task needs the user's session, and no stored credential exists for it. This is the single largest caveat on the sixty-day requirement
* **machine rebooted** — NOT EXERCISED: a reboot would end this session and every other process on the host, which is an operator's decision and not a work package's
* **machine asleep** — the trigger is missed and StartWhenAvailable fires it on wake; that path is declared by the registration and NOT EXERCISED here
* **machine off across several slots** — the next tick ingests every bar that closed after the store's high-water mark, so the gap is latency and not data — EXERCISED by this work package as a real scheduler outage, see OUTAGE_REHEARSAL_*.json

## The safe unattended modes, and what each needs

* **a host that stays logged in, with the screen locked**
  * needs: nothing beyond what is registered
  * limitation: a logoff, a reboot without an auto-logon, or a session that is closed ends the observation until somebody logs back in
  * authorisation: the owner's decision; this work package leaves it registered as it is
* **run whether the user is logged on or not**
  * needs: the account's password stored for the task, or a dedicated low-privilege service account, and the policy to allow it
  * limitation: a credential would have to be stored on this host; the WP was not authorised to hold one and did not
  * authorisation: REQUIRED — operator. The commands are in `commands_for_the_owner`
* **a Linux host with systemd --user**
  * needs: the same command under a timer, with Persistent=true
  * limitation: still a user session; the durable form is a system service
  * authorisation: not available on this host and NOT EXERCISED

## Not applied, and why

storing an account credential on this host is exactly what the security rules of this project forbid an automated agent to do; the change is spelled out for a person to make, and until it is made the sixty-day accumulation depends on the session staying alive

```
schtasks /change /tn "TradingAgentic-EDGE04-Forward" /ru "<DOMAIN\user>" /rp "<password>"
schtasks /change /tn "TradingAgentic-EDGE05-Watchdog" /ru "<DOMAIN\user>" /rp "<password>"
# or, from PowerShell, which also needs the password interactively:
$c = Get-Credential; Set-ScheduledTask -TaskName 'TradingAgentic-EDGE04-Forward' -User $c.UserName -Password $c.GetNetworkCredential().Password
```
