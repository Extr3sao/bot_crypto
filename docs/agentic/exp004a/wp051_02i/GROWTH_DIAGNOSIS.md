# EDGE-04 growth and projected capacity

Measured at `2026-10-23T10:55:31Z` on `C:\Users\GVLLFR0035\Downloads\bot freebuff\data\forward\edge04`: **237.5264 GiB** total, **4.412 GiB** free (98.14 % used), state `WARNING`.

## 1. The record, before the arithmetic

The observer's own log holds **929** free-space readings from `2026-10-13T11:23:38Z` to `2026-10-23T10:40:56Z`. In that record the volume went under the 2 GiB floor **25** time(s), spent **40.55 hour(s)** there, and reached **0.0 GiB** free at its worst.

The guard refused **162** tick(s) (`DISK_BUDGET_EXCEEDED`, 40.5 hour(s) of slots) — every one of them a slot whose bars were never fetched, because the lag policy forbids fetching them later.

| Under the floor | Hours | Lowest free |
| --- | --- | --- |
| `2026-10-13T20:25:56Z` → `2026-10-13T20:55:56Z` | 0.75 | 1.809 GiB |
| `2026-10-13T21:25:56Z` → `2026-10-13T21:40:56Z` | 0.5 | 1.773 GiB |
| `2026-10-13T22:10:57Z` → `2026-10-14T05:25:56Z` | 7.5 | 0.83 GiB |
| `2026-10-14T07:55:09Z` → `2026-10-14T08:40:57Z` | 1.01 | 1.157 GiB |
| `2026-10-14T12:55:56Z` → `2026-10-14T13:40:56Z` | 1.0 | 1.384 GiB |
| `2026-10-17T16:55:57Z` → `2026-10-17T17:10:57Z` | 0.5 | 1.614 GiB |
| `2026-10-17T18:10:57Z` → `2026-10-17T19:55:56Z` | 2.0 | 0.155 GiB |
| `2026-10-17T22:40:56Z` → `2026-10-17T22:40:56Z` | 0.25 | 0.76 GiB |
| `2026-10-17T23:10:56Z` → `2026-10-17T23:10:56Z` | 0.25 | 1.776 GiB |
| `2026-10-18T00:10:55Z` → `2026-10-18T00:10:55Z` | 0.25 | 1.998 GiB |
| `2026-10-18T02:40:56Z` → `2026-10-18T02:40:56Z` | 0.25 | 1.999 GiB |
| `2026-10-18T07:40:56Z` → `2026-10-18T07:55:56Z` | 0.5 | 1.932 GiB |
| `2026-10-18T09:10:57Z` → `2026-10-18T12:25:56Z` | 3.5 | 0.0 GiB |
| `2026-10-18T19:10:57Z` → `2026-10-19T02:40:55Z` | 7.75 | 0.0 GiB |
| `2026-10-20T11:40:58Z` → `2026-10-20T11:40:58Z` | 0.25 | 1.935 GiB |
| `2026-10-20T14:26:17Z` → `2026-10-20T14:43:24Z` | 0.54 | 0.911 GiB |
| `2026-10-21T16:10:56Z` → `2026-10-21T17:10:56Z` | 1.25 | 0.263 GiB |
| `2026-10-21T17:55:56Z` → `2026-10-21T17:55:56Z` | 0.25 | 1.32 GiB |
| `2026-10-21T18:25:56Z` → `2026-10-21T19:55:57Z` | 1.75 | 0.035 GiB |
| `2026-10-22T14:55:56Z` → `2026-10-22T14:55:56Z` | 0.25 | 1.691 GiB |
| `2026-10-22T16:55:56Z` → `2026-10-22T18:10:56Z` | 1.5 | 1.442 GiB |
| `2026-10-22T19:55:56Z` → `2026-10-22T22:10:56Z` | 2.5 | 0.278 GiB |
| `2026-10-23T00:10:56Z` → `2026-10-23T05:25:57Z` | 5.5 | 0.0 GiB |
| `2026-10-23T05:55:56Z` → `2026-10-23T05:55:56Z` | 0.25 | 0.48 GiB |
| `2026-10-23T06:40:57Z` → `2026-10-23T06:55:57Z` | 0.5 | 0.659 GiB |

## 2. Where the bytes are

| Consumer | Owner | Class | Size |
| --- | --- | --- | --- |
| `data/forward/edge04` | this campaign | PROTECTED_EVIDENCE | 13.67 MiB |
| `data/forward/edge03` | this campaign | PROTECTED_EVIDENCE | 6.39 MiB |
| `data/exp004a` | this campaign | PROTECTED_EVIDENCE | 0.32 MiB |
| `.git` | the repository | PROTECTED_REPOSITORY | 150.58 MiB |
| `%TEMP%/edge14r` | another agent (running processes) | FOREIGN_IN_USE | 0.0 MiB |
| `.tmp/audit/baseline-wt` | another agent | FOREIGN | 160.22 MiB |
| `%HOME%/Downloads` | the user and other packages | FOREIGN | 18972.76 MiB |
| `%TEMP%` | every process on this host | SHARED_TEMP | 7029.45 MiB |

## 3. The two series, kept apart

- The campaign's own tree: **13.67 MiB**.
- Shard format: **314.5 bytes per row** over 15 shard(s) found in 3 searched root(s).
- The campaign's own measured growth: **1161639 bytes/day** over 9.938 day(s) of its own samples.
- The host's oscillation: largest fall from a peak inside one UTC day **14.583 GiB** on 2026-10-19; median daily net change **-1.6607 GiB** over 11 day(s) (`MEASURED`), with 7 day(s) spending and 4 day(s) recovering.

The two are not the same series and must not be added into one number: the campaign writes roughly a megabyte a day, and the volume loses gigabytes a day to processes this package cannot name.

## 4. The projection

- Own need for 90 days: **104547510 bytes** (format 2037960, measured tree 104547510).
- Floor that must never be spent: **2147483648 bytes**.
- Headroom the volume must already hold: **15658606592 bytes**, the largest observed daily fall.
- Required free space: **16.681 GiB**; available now: **4.412 GiB** → headroom **-13173273782 bytes**.
- At the worst observed drawdown, the floor is **3.97 hour(s)** away.

**Verdict: `INSUFFICIENT`.**
- free space 4.412 GiB is under the 16.681 GiB the floor plus one day's observed drawdown needs

Hypotheses this verdict rests on:

- the window is 90 consecutive UTC days
- every day holds 72 rows (3 assets x 24 hours)
- the host's own drawdown repeats at the largest rate already observed
- the critical floor stays at 2 GiB and is never spent
- the bytes this package cannot name are not claimed as available
- recovery of free space is not planned: it has happened, and it is not a plan

## 5. What this package reclaimed

- Eligible inside its own worktree: **0 bytes** in 0 file(s).
- Removed across 2 recorded run(s): **4** director(ies), **216353 bytes**; the volume itself moved -65536 bytes while the last run lasted, which is not the same quantity.
- Foreign and shared bytes (temp, other agents' checkouts, browser caches, Downloads) are listed and left untouched: this package cannot name their owner or their retention.
