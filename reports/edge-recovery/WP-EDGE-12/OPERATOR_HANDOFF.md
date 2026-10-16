# WP-EDGE-12B — operator handoff

**Generated:** 2026-10-16T06:20:12Z · **Selected mechanism:** `LOGON_TRIGGER`

> True and this file is the instruction set for somebody who can.

Definition: `C:\Users\GVLLFR0035\Downloads\bot freebuff\reports\edge-recovery\WP-EDGE-12\evidence\PROPOSED_DEFINITION.xml`

### Step 1 — read the preflight

```bash
python scripts/edge12_runner.py --preflight-only
```

Expect: PREFLIGHT_PASS with zero blocking failures

### Step 2 — capture the current registration

```bash
schtasks /query /tn "TradingAgentic-EDGE04-Forward" /xml > rollback-before.xml
```

Expect: a rollback-before.xml whose sha256 equals the one recorded in ROLLBACK.md

### Step 3 — apply the definition (an operator decision)

```bash
schtasks /create /tn "TradingAgentic-EDGE04-Forward" /xml "C:/Users/GVLLFR0035/Downloads/bot freebuff/reports/edge-recovery/WP-EDGE-12/evidence/PROPOSED_DEFINITION.xml" /f
```

Expect: the scheduler reports the task with both trigger kinds

### Step 4 — verify what the scheduler kept

```bash
schtasks /query /tn "TradingAgentic-EDGE04-Forward" /xml
```

Expect: MSFT_TaskLogonTrigger beside MSFT_TaskTimeTrigger, and the lane's own action unchanged

### Step 5 — for the mechanisms this process cannot use, an administrator is the actor

```bash
wevtutil sl Microsoft-Windows-TaskScheduler/Operational /e:true
```

Expect: the operational log enabled, which is what makes a future silent trigger attributable

Requires: **administrator rights**.

## What changes for the measurement

the cadence phase: StartBoundary is carried over to the second, so the instants do not move, but the logon trigger adds starts that are not on the quarter-hour grid

## What does not change

the action, its working directory, the principal's run level, the multiple-instances policy, the storage guard and every threshold this campaign measures against

Undoing it: `ROLLBACK.md`. Research only: no orders, no capital, no promotion.
