# WP-EDGE-07 — storage reclaim: our own scratch, beside the repository

*Read at `2026-10-14T08:50:23Z` on `DESKTOP-4CHO695`. Mode: **applied**.*

## 1. The volume, before and after

| | |
| --- | --- |
| Free before | 2.630 GiB |
| Free after | **3.684 GiB** |
| Reclaimed by this run | **1042.61 MiB** |
| Critical floor (the tick refuses below it) | 2147483648 bytes |
| Healthy floor (the heavy publication waits below it) | 5368709120 bytes |
| Clears the critical floor | True |
| Clears the healthy floor | False |

the reclaim clears the 2 GiB the tick refuses below, so ingestion may resume; it is 1347.4 MiB short of the 5 GiB the heavy publication waits below

## 2. What was removed, and the rule each one passed

| Path | Rule | Size | Files | Removed | Created by |
| --- | --- | --- | --- | --- | --- |
| `C:\Users\GVLLFR~1\AppData\Local\Temp\pytest-of-GVLLFR0035\pytest-1337` | `pytest_sessions` | 113.83 MiB | 1811 | True | pytest (the base temp directory is the framework's own) |
| `C:\Users\GVLLFR~1\AppData\Local\Temp\pytest-of-GVLLFR0035\pytest-1338` | `pytest_sessions` | 113.80 MiB | 1809 | True | pytest (the base temp directory is the framework's own) |
| `C:\Users\GVLLFR~1\AppData\Local\Temp\pytest-of-GVLLFR0035\pytest-1345` | `pytest_sessions` | 113.24 MiB | 1805 | True | pytest (the base temp directory is the framework's own) |
| `C:\Users\GVLLFR~1\AppData\Local\Temp\pytest-of-GVLLFR0035\pytest-1344` | `pytest_sessions` | 113.23 MiB | 1805 | True | pytest (the base temp directory is the framework's own) |
| `C:\Users\GVLLFR~1\AppData\Local\Temp\pytest-of-GVLLFR0035\pytest-1488` | `pytest_sessions` | 113.23 MiB | 1805 | True | pytest (the base temp directory is the framework's own) |
| `C:\Users\GVLLFR~1\AppData\Local\Temp\pytest-of-GVLLFR0035\pytest-1358` | `pytest_sessions` | 113.20 MiB | 1803 | True | pytest (the base temp directory is the framework's own) |
| `C:\Users\GVLLFR~1\AppData\Local\Temp\pytest-of-GVLLFR0035\pytest-1343` | `pytest_sessions` | 78.27 MiB | 1636 | True | pytest (the base temp directory is the framework's own) |
| `C:\Users\GVLLFR~1\AppData\Local\Temp\pytest-of-GVLLFR0035\pytest-1329` | `pytest_sessions` | 56.84 MiB | 915 | True | pytest (the base temp directory is the framework's own) |
| `C:\Users\GVLLFR~1\AppData\Local\Temp\pytest-of-GVLLFR0035\pytest-1327` | `pytest_sessions` | 56.78 MiB | 678 | True | pytest (the base temp directory is the framework's own) |
| `C:\Users\GVLLFR~1\AppData\Local\Temp\pytest-of-GVLLFR0035\pytest-1328` | `pytest_sessions` | 56.78 MiB | 778 | True | pytest (the base temp directory is the framework's own) |
| `C:\Users\GVLLFR~1\AppData\Local\Temp\pytest-of-GVLLFR0035\pytest-1336` | `pytest_sessions` | 56.73 MiB | 609 | True | pytest (the base temp directory is the framework's own) |
| `C:\Users\GVLLFR~1\AppData\Local\Temp\pytest-of-GVLLFR0035\pytest-1330` | `pytest_sessions` | 56.69 MiB | 772 | True | pytest (the base temp directory is the framework's own) |

## 3. Kept, and why

| Path | Rule | Size | Kept because |
| --- | --- | --- | --- |
| `C:\Users\GVLLFR0035\Downloads\bot-freebuff-rfc035s3-lab` | `registered_worktrees` | 15.37 MiB | untracked paths: work that exists nowhere else |
| `C:\Users\GVLLFR~1\AppData\Local\Temp\pytest-of-GVLLFR0035\pytest-1764` | `pytest_sessions` | 3.54 MiB | the newest session, or written inside the declared freshness window |
| `C:\Users\GVLLFR~1\AppData\Local\Temp\pytest-of-GVLLFR0035\pytest-1763` | `pytest_sessions` | 3.54 MiB | the newest session, or written inside the declared freshness window |
| `C:\Users\GVLLFR~1\AppData\Local\Temp\pytest-of-GVLLFR0035\pytest-1765` | `pytest_sessions` | 3.54 MiB | the newest session, or written inside the declared freshness window |

## 4. Not ours: the neighbours this tool measured and left alone

| Path | Size | Newest write |
| --- | --- | --- |
| `C:\Users\GVLLFR~1\AppData\Local\Temp\pytest-of-GVLLFR0035` | 1053.24 MiB | 2026-10-14T08:44:40Z |
| `C:\Users\GVLLFR~1\AppData\Local\Temp\vscode-stable-user-x64` | 240.18 MiB | 2026-10-13T20:04:26Z |
| `C:\Users\GVLLFR~1\AppData\Local\Temp\TeamViewer` | 80.47 MiB | 2026-09-30T05:06:17Z |
| `C:\Users\GVLLFR~1\AppData\Local\Temp\Diagnostics` | 64.00 MiB | 2026-10-01T04:35:01Z |
| `C:\Users\GVLLFR~1\AppData\Local\Temp\tmpyhksnp1q` | 27.59 MiB | 2026-10-14T08:13:34Z |
| `C:\Users\GVLLFR~1\AppData\Local\Temp\tmpte65o4n5` | 27.55 MiB | 2026-10-14T08:12:44Z |
| `C:\Users\GVLLFR~1\AppData\Local\Temp\dylan-smoke-r1` | 17.41 MiB | 2026-10-13T23:03:02Z |
| `C:\Users\GVLLFR~1\AppData\Local\Temp\tmpqg6hk9gp` | 17.29 MiB | 2026-10-03T19:27:43Z |
| `C:\Users\GVLLFR~1\AppData\Local\Temp\tmpbk8m943y` | 17.29 MiB | 2026-10-03T19:23:06Z |
| `C:\Users\GVLLFR~1\AppData\Local\Temp\tmp2hmnpwe0` | 17.29 MiB | 2026-10-03T19:26:32Z |
| `C:\Users\GVLLFR~1\AppData\Local\Temp\arp005_run1` | 16.57 MiB | 2026-10-02T09:01:40Z |
| `C:\Users\GVLLFR~1\AppData\Local\Temp\SsmsSetup` | 14.26 MiB | 2026-10-07T08:22:53Z |

## 5. What this authorises, and what it does not

- It removes only paths whose provenance is this repository's own tooling, re-derived at
  the instant of removal, and it removes worktrees with `git worktree remove`.
- It does not touch another application's cache, another workstream's evidence, the
  repository's tracked files, or the market data under `data/`: none of those is a
  candidate here, whatever their size.
