# WP-EDGE-12B — rollback

**Generated:** 2026-10-16T06:30:43Z · **Task:** `TradingAgentic-EDGE04-Forward`

Written before it is needed, and pinned to the registration that exists now rather than
to a definition somebody would have to reconstruct from a report.

|  |  |
| --- | --- |
| captured before any change | True |
| live registration sha256 | `7ac9e7ce2459580dcddb5b2120bfdeee…` |
| live registration bytes | 1861 |
| live trigger kinds | MSFT_TaskTimeTrigger |
| definition this rolls back | `C:\Users\GVLLFR0035\Downloads\bot freebuff\reports\edge-recovery\WP-EDGE-12\evidence\PROPOSED_DEFINITION.xml` |

### 1. export the current registration before applying anything

```bash
schtasks /query /tn "TradingAgentic-EDGE04-Forward" /xml > rollback-before.xml
```

### 2. restore it if the applied definition misbehaves

```bash
schtasks /create /tn "TradingAgentic-EDGE04-Forward" /xml rollback-before.xml /f
```

### 3. prove the restore, rather than assuming it

```bash
schtasks /query /tn "TradingAgentic-EDGE04-Forward" /xml
```

Verify: the trigger kinds and the logon type match live_registration_trigger_kinds

### 4. if the task itself is wrong, remove it and let the lane re-register

```bash
schtasks /delete /tn "TradingAgentic-EDGE04-Forward" /f
```

Precondition: the observer is stopped first, or the lane keeps ticking under no registration

## What a rollback cannot undo

the phase of the cadence: re-registering moves StartBoundary, and the instants before and after are not comparable in one window; a reading taken across the change must declare where it happened
