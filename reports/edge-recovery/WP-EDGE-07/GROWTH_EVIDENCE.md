# WP-EDGE-07 — who is growing the volume, and what is the share of each writer

*Read at `2026-10-14T08:28:12Z` on `DESKTOP-4CHO695`. **Read-only**: `deleted_anything: False`.*

## 1. The volume, and the distance to each floor

| | |
| --- | --- |
| Free | **1.256 GiB** (1348886528 bytes) |
| Verdict | `BELOW_CRITICAL` |
| Critical floor (the lane refuses below it) | 2147483648 bytes |
| Healthy floor (the heavy publication waits below it) | 5368709120 bytes |
| Shortfall to resume ingestion | **0.744 GiB** |
| Shortfall to reach healthy | 3.744 GiB |

the lane refuses a tick below the critical floor and the heavy publication waits below the healthy floor; the numbers above are the distance to each, measured now.

## 2. What grew, by directory, inside the declared window

files whose modification time falls inside the last 180 minutes, walked with a 120s budget per root; a truncated walk says so and its bytes are a floor.

### `C:\Users\GVLLFR0035\AppData\Local`

*Window: 180 min. Scanned 682,386 files in 77.94 s. Fully walked: True.*

Total written inside the window: **4,459.6 MiB**.

| Directory | Written | Files | Newest write | Largest file in the window |
| --- | --- | --- | --- | --- |
| `Microsoft/Edge/User Data` | 3,340.1 MiB | 57 | 2026-10-14T08:28:13Z | `Microsoft\Edge\User Data\Default\ExtensionActivityEdge` (3,270.78 MiB) |
| `Microsoft/OneDrive/ListSync` | 240.4 MiB | 5 | 2026-10-14T08:19:46Z | `Microsoft\OneDrive\ListSync\Business_820946de-d416-4e75-ae0a-68cb0b3e5526\settings\Microsoft.ListSync.db` (236.77 MiB) |
| `Google/Chrome/User Data` | 123.1 MiB | 94 | 2026-10-14T08:28:15Z | `Google\Chrome\User Data\Default\Cache\Cache_Data\data_3` (44.01 MiB) |
| `Microsoft/Windows/WebCache` | 81.0 MiB | 4 | 2026-10-14T07:36:56Z | `Microsoft\Windows\WebCache\WebCacheV01.dat` (79.50 MiB) |
| `Temp/recovery-rehearsal-6_k8h2nd/checkout` | 79.5 MiB | 2,266 | 2026-10-14T06:04:14Z | `Temp\recovery-rehearsal-6_k8h2nd\checkout\reports\edge-recovery\WP-EDGE-01\EQUITY_CURVE.csv` (16.07 MiB) |
| `CiscoSpark/3776557700352324632/spark_persistent_store.db` | 57.5 MiB | 1 | 2026-10-14T08:28:02Z | `CiscoSpark\3776557700352324632\spark_persistent_store.db` (57.47 MiB) |
| `Temp/pytest-of-GVLLFR0035/pytest-1718` | 54.5 MiB | 2,044 | 2026-10-14T06:03:03Z | `Temp\pytest-of-GVLLFR0035\pytest-1718\test_str_001_linear_growth0\campaign_health.ndjson` (18.41 MiB) |
| `CiscoSpark/Logs/current_log.txt` | 20.2 MiB | 1 | 2026-10-14T08:28:12Z | `CiscoSpark\Logs\current_log.txt` (20.23 MiB) |
| `Temp/tmpyhksnp1q/ws3` | 16.5 MiB | 11 | 2026-10-14T08:13:35Z | `Temp\tmpyhksnp1q\ws3\learner.sqlite3` (5.77 MiB) |
| `Temp/tmpte65o4n5/ws3` | 16.4 MiB | 9 | 2026-10-14T08:12:45Z | `Temp\tmpte65o4n5\ws3\learner.sqlite3` (5.77 MiB) |
| `CiscoSpark/Logs/media` | 15.5 MiB | 1 | 2026-10-14T08:28:04Z | `CiscoSpark\Logs\media\current_log.txt` (15.53 MiB) |
| `Temp/tmpte65o4n5/ws1` | 11.1 MiB | 4 | 2026-10-14T08:12:44Z | `Temp\tmpte65o4n5\ws1\learner.sqlite3` (5.77 MiB) |
| `Temp/tmpleof2hhw/ws1` | 11.1 MiB | 4 | 2026-10-14T08:11:20Z | `Temp\tmpleof2hhw\ws1\learner.sqlite3` (5.77 MiB) |
| `Temp/tmpyhksnp1q/ws1` | 11.1 MiB | 4 | 2026-10-14T08:13:34Z | `Temp\tmpyhksnp1q\ws1\learner.sqlite3` (5.77 MiB) |
| `Temp/tmphwrztle0/ws1` | 11.1 MiB | 4 | 2026-10-14T08:11:36Z | `Temp\tmphwrztle0\ws1\learner.sqlite3` (5.77 MiB) |
| `Temp/tmpclw5gfbx/ws1` | 11.1 MiB | 4 | 2026-10-14T08:12:26Z | `Temp\tmpclw5gfbx\ws1\learner.sqlite3` (5.77 MiB) |
| `CiscoSpark/Logs/accessories` | 10.2 MiB | 1 | 2026-10-14T08:28:08Z | `CiscoSpark\Logs\accessories\current_log.txt` (10.23 MiB) |
| `Packages/MicrosoftWindows.Client.CBS_cw5n1h2txyewy/LocalState` | 6.0 MiB | 8 | 2026-10-14T08:23:45Z | `Packages\MicrosoftWindows.Client.CBS_cw5n1h2txyewy\LocalState\EBWebView\Default\DIPS-wal` (3.93 MiB) |
| `Temp/rfc008-rollback-fymjza1p/db.sqlite3` | 5.8 MiB | 1 | 2026-10-14T08:12:45Z | `Temp\rfc008-rollback-fymjza1p\db.sqlite3` (5.77 MiB) |
| `Temp/rfc008-verify-49er748t/database.sqlite` | 5.8 MiB | 1 | 2026-10-14T08:12:44Z | `Temp\rfc008-verify-49er748t\database.sqlite` (5.77 MiB) |
| `Temp/rfc008-verify-5msitxal/database.sqlite` | 5.8 MiB | 1 | 2026-10-14T08:13:34Z | `Temp\rfc008-verify-5msitxal\database.sqlite` (5.77 MiB) |
| `Temp/rfc008-verify-_jr67d8r/database.sqlite` | 5.8 MiB | 1 | 2026-10-14T08:12:44Z | `Temp\rfc008-verify-_jr67d8r\database.sqlite` (5.77 MiB) |
| `Temp/rfc008-verify-is_44udy/database.sqlite` | 5.8 MiB | 1 | 2026-10-14T08:12:26Z | `Temp\rfc008-verify-is_44udy\database.sqlite` (5.77 MiB) |
| `Temp/rfc008-verify-iumk6yrg/database.sqlite` | 5.8 MiB | 1 | 2026-10-14T08:13:35Z | `Temp\rfc008-verify-iumk6yrg\database.sqlite` (5.77 MiB) |
| `Temp/rfc008-verify-ly5cze64/database.sqlite` | 5.8 MiB | 1 | 2026-10-14T08:11:36Z | `Temp\rfc008-verify-ly5cze64\database.sqlite` (5.77 MiB) |

By extension:

| Extension | Written | Files |
| --- | --- | --- |
| `(none)` | 3,435.6 MiB | 168 |
| `.db` | 294.7 MiB | 9 |
| `.sqlite3` | 143.6 MiB | 166 |
| `.sqlite` | 133.6 MiB | 255 |
| `.dat` | 79.9 MiB | 42 |
| `.sqlite3-wal` | 52.5 MiB | 81 |
| `.txt` | 49.7 MiB | 16 |
| `.zip` | 48.1 MiB | 29 |
| `.json` | 36.4 MiB | 1,895 |
| `.csv` | 35.4 MiB | 229 |
| `.ndjson` | 30.9 MiB | 4 |
| `.log` | 30.5 MiB | 85 |

## 3. Processes running from the profile

*Source: ps -W (psutil unavailable); 44 process(es)*

| PID | Name | Image |
| --- | --- | --- |
| — | — | `4196824       0       0       2520  ?              0   Oct  1 C:\Users\GVLLFR0035\AppData\Local\Discord\app-1.0.9259\Discord.exe` |
| — | — | `4206824       0       0      12520  ?              0   Oct  1 C:\Users\GVLLFR0035\AppData\Local\Discord\app-1.0.9259\Discord.exe` |
| — | — | `4208800       0       0      14496  ?              0   Oct  1 C:\Users\GVLLFR0035\AppData\Local\Discord\app-1.0.9259\Discord.exe` |
| — | — | `4210784       0       0      16480  ?              0   Oct  1 C:\Users\GVLLFR0035\AppData\Local\Discord\app-1.0.9259\Discord.exe` |
| — | — | `4213796       0       0      19492  ?              0   Oct  1 C:\Users\GVLLFR0035\AppData\Local\Discord\app-1.0.9259\Discord.exe` |
| — | — | `4214552       0       0      20248  ?              0   Oct  1 C:\Users\GVLLFR0035\AppData\Local\CiscoSparkLauncher\CiscoCollabHost.exe` |
| — | — | `4206100       0       0      11796  ?              0   Oct  1 C:\Users\GVLLFR0035\AppData\Local\CiscoSparkLauncher\CiscoCollabHost.exe` |
| — | — | `4212680       0       0      18376  ?              0   Oct  1 C:\Users\GVLLFR0035\AppData\Local\WebEx\WebexHost.exe` |
| — | — | `4214544       0       0      20240  ?              0   Oct  1 C:\Users\GVLLFR0035\AppData\Local\CiscoSparkLauncher\46.9.0.35800_14bda21a-66af-457b-a13d-5e72cbcf916c\dependencies\wmlhost.exe` |
| — | — | `4201192       0       0       6888  ?              0   Oct  1 C:\Users\GVLLFR0035\AppData\Local\CiscoSparkLauncher\CiscoCollabHost.exe` |
| — | — | `275       1     269      28492  ?           4096   Oct  3 /c/Users/GVLLFR0035/Downloads/bot freebuff/.venv/Scripts/python` |
| — | — | `4211440       0       0      17136  ?              0   Oct  3 C:\Users\GVLLFR0035\AppData\Roaming\uv\python\cpython-3.11.15-windows-x86_64-none\python.exe` |
| — | — | `4225628       0       0      31324  ?              0   Oct  6 C:\Users\GVLLFR0035\AppData\Local\WebEx\WebEx64\Meetings\atmgr.exe` |
| — | — | `4216076       0       0      21772  ?              0   Oct  9 C:\Users\GVLLFR0035\AppData\Local\Programs\Python\Python312\python.exe` |
| — | — | `4218444       0       0      24140  ?              0   Oct  9 C:\Users\GVLLFR0035\AppData\Local\Programs\Python\Python312\python.exe` |
| — | — | `4220432       0       0      26128  ?              0   Oct  9 C:\Users\GVLLFR0035\AppData\Local\Programs\Python\Python312\python.exe` |
| — | — | `27828       1   27826       5588  ?           4096   Oct  9 /c/Users/GVLLFR0035/AppData/Local/hermes/hermes-agent/venv/Scripts/python` |
| — | — | `4216392       0       0      22088  ?              0   Oct  9 C:\Users\GVLLFR0035\AppData\Roaming\uv\python\cpython-3.11.15-windows-x86_64-none\python.exe` |
| — | — | `37490       1   37488       2092  ?           4096   Oct 11 /c/Users/GVLLFR0035/AppData/Local/hermes/bin/uv` |
| — | — | `4214180       0       0      19876  ?              0   Oct 11 C:\Users\GVLLFR0035\Downloads\bot freebuff\.venv\Scripts\python.exe` |
| — | — | `4209360       0       0      15056  ?              0   Oct 11 C:\Users\GVLLFR0035\AppData\Roaming\uv\python\cpython-3.11.15-windows-x86_64-none\python.exe` |
| — | — | `4224016       0       0      29712  ?              0   Oct 11 C:\Users\GVLLFR0035\Downloads\bot freebuff\.venv\Scripts\python.exe` |
| — | — | `4228484       0       0      34180  ?              0   Oct 11 C:\Users\GVLLFR0035\AppData\Roaming\uv\python\cpython-3.11.15-windows-x86_64-none\python.exe` |
| — | — | `4225960       0       0      31656  ?              0   Oct 12 C:\Users\GVLLFR0035\AppData\Local\Programs\Python\Python312\python.exe` |
| — | — | `4228148       0       0      33844  ?              0   Oct 12 C:\Users\GVLLFR0035\AppData\Local\Programs\@codebufffreebuff-desktop\Freebuff.exe` |

## 4. What this reading authorises

- It names the writers. It does not stop them and it does not delete their files: every path in this file belongs to another application or to the user.
- What this work package may clean is its own: the repository's tool caches, and only those whose removal is provable at the instant of removal.
- The distance to the floor is **0.744 GiB**; if no repository-owned action can close it, that is the volume owner's decision, taken with this table in hand.
