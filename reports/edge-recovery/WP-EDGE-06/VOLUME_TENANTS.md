# WP-EDGE-06 — the volume's other tenants, measured again

*Read at `2026-10-14T08:01:03Z` on `DESKTOP-4CHO695` by `scripts/edge06_volume_tenants.py`. **This tool deletes nothing**: it sizes what lives outside the repository and stops there.*

## 1. The volume, and the part of it this work package may touch

| | |
| --- | --- |
| Volume | `C:/` |
| Free | **1.578 GiB** (1694085120 bytes) |
| Repository | `C:\Users\GVLLFR0035\Downloads\bot freebuff` |
| Deleted anything | False |
| Every tenant fully walked | False |

read-only bounded directory walks; a tenant whose walk hit the 75s budget carries measured: false and its bytes are a floor, not a size.

## 2. Who else is on the volume, and what they did since the last reading

compared with the previous run of this tool at 2026-10-14T07:56:10Z.

| Tenant | Size | Files | Kind | Previous | Delta | Measured |
| --- | --- | --- | --- | --- | --- | --- |
| `AppData/Local` | 74,686.0 MiB (78,313,968,689 B) | 595,003 | host user data | 65,042.2 MiB | +9,643.8 MiB | **no — a floor** |
| `Windows` | 41,628.0 MiB (43,650,096,952 B) | 227,346 | operating system | 41,628.0 MiB | +0.0 MiB | yes |
| `Program Files` | 20,093.2 MiB (21,069,265,518 B) | 59,233 | installed software | 20,093.2 MiB | +0.0 MiB | yes |
| `AppData/Roaming` | 11,737.8 MiB (12,307,932,069 B) | 115,930 | host user data | 11,737.8 MiB | +0.0 MiB | yes |
| `Program Files (x86)` | 9,932.8 MiB (10,415,245,502 B) | 9,658 | installed software | 9,932.8 MiB | +0.0 MiB | yes |
| `Downloads` | 7,908.6 MiB (8,292,716,277 B) | 158,024 | user data | 7,908.5 MiB | +0.1 MiB | yes |
| `ProgramData` | 1,974.0 MiB (2,069,842,981 B) | 9,524 | installed software | 1,973.7 MiB | +0.3 MiB | yes |
| `.cache` | 1,480.0 MiB (1,551,928,351 B) | 29,237 | tool cache (outside the repository) | 1,480.0 MiB | +0.0 MiB | yes |
| `Documents` | 1,302.1 MiB (1,365,397,200 B) | 646 | user data | 1,302.1 MiB | +0.0 MiB | yes |
| `.docker` | 75.3 MiB (78,980,836 B) | 23 | tool cache (outside the repository) | 75.3 MiB | +0.0 MiB | yes |
| `.npm` | 52.3 MiB (54,891,436 B) | 120 | tool cache (outside the repository) | 52.3 MiB | +0.0 MiB | yes |

Those tenants hold **166.9 GiB** (a floor: at least one walk was cut short). The repository is not one of them.

### The home user's `AppData` one level down

| Tenant | Size | Files | Kind | Previous | Delta | Measured |
| --- | --- | --- | --- | --- | --- | --- |
| `AppData/Local/Temp` | 29,962.0 MiB | 242,040 | temporary files | — | no previous reading | yes |
| `AppData/Local/Microsoft` | 13,931.9 MiB | 62,786 | browser and profile caches | — | no previous reading | yes |
| `AppData/Local/Programs` | 7,193.1 MiB | 102,966 | per-user installed software | — | no previous reading | yes |
| `AppData/Roaming/Msty` | 6,503.1 MiB | 100 | local model files | — | no previous reading | yes |
| `AppData/Local/wsl` | 6,310.0 MiB | 2 | WSL distributions (data, not cache) | — | no previous reading | yes |
| `AppData/Local/ms-playwright` | 3,353.6 MiB | 2,528 | browser builds | — | no previous reading | yes |
| `AppData/Local/hermes` | 2,832.5 MiB | 113,264 | user data | — | no previous reading | yes |
| `AppData/Roaming/Code` | 1,693.3 MiB | 5,421 | editor state and extensions | — | no previous reading | yes |
| `AppData/Local/npm-cache` | 1,185.9 MiB | 7,175 | package cache | — | no previous reading | yes |
| `AppData/Roaming/npm` | 1,069.5 MiB | 68,623 | global packages | — | no previous reading | yes |

### The temporary directory, by the age of its newest write

| Newest write | Size | Files |
| --- | --- | --- |
| under 6h | 0.43 GiB | 5,301 |
| 6h to 24h | 0.93 GiB | 3,570 |
| 1d to 7d | 23.03 GiB | 182,066 |
| over 7d | 4.87 GiB | 51,103 |
| **total** | **29.27 GiB** | **242,040** |

The walk covered every file.

## 3. What this reading authorises, and what it does not

- It sizes the volume's other occupants so that the repository's floor can be read against them. Every byte in this file belongs to somebody else.
- It deletes nothing, and the plan for what could be deleted stays where WP-EDGE-05R put it: with the volume's owner, who is the only actor whose scope covers these paths.
- It cannot be read as a cleanup: `deleted_anything` is `false` in the JSON as well as in this sentence.

## 4. Provenance

| Figure | Value | as_of_utc | Source |
| --- | --- | --- | --- |
| `volume_free_bytes` | 1694085120 | 2026-10-14T08:01:03Z | operating system, `disk_usage` of the repository volume |
| `tenants_total_bytes` | 179170265811 | 2026-10-14T08:01:03Z | this tool's own bounded walks |
| `comparison_basis` | previous_run_of_this_tool | 2026-10-14T07:56:10Z | EDGE06-TENANTS-20261014T075610Z |

*`run_id`: `EDGE06-TENANTS-20261014T080103Z`. Payload digest of the tenants section: `f408ce30a748ab3f…`.*
