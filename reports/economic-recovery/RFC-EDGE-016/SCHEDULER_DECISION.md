# WP-EDGE-016 — scheduler decision

**DO_NOT_CREATE_A_SCHEDULER**

- the disk guard reports INSUFFICIENT_FREE_SPACE for the declared collection window
- creating a Windows scheduled task needs administrator privileges, which are not authorized
- a GitHub cron cannot run this collector: the working copy and the data are local
- the brief prefers reuse over invention, and the one existing task belongs to another line

## What is delivered instead

- `manual_collector`: scripts/edge15_oos_preregistration.py --capture (idempotent, appends only new bars)
- `runbook`: PROSPECTIVE_COVERAGE.md
- `status_while_blocked`: PROSPECTIVE_CAPTURE_NOT_AUTOMATED

## What unblocks it

- free space for the declared horizon (the guard's own arithmetic, not a lowered threshold)
- an explicit decision to schedule a local task, which this package does not take
