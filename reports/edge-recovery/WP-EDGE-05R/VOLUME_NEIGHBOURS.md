# WP-EDGE-05R — the volume's other tenants, and the plan that is not this work package's to run

*Read on `DESKTOP-4CHO695` between `2026-10-14T05:46Z` and `2026-10-14T05:49Z`, with read-only directory
walks. **Nothing in this document was deleted, and nothing in it will be**: the mission authorises
cache cleanup inside the repository and stops there, so what follows is a plan for the volume's owner.*

## 1. Why this document exists

The lane's next tick is refused whenever the volume holding the repository is below its declared
critical floor of 2 GiB. On `2026-10-14` that is what happened, and the repository's own tool caches
are far too small to change it:

| Read at | Free on the volume | The repository's share | Safe to reclaim inside it |
| --- | --- | --- | --- |
| `2026-10-13T21:52:59Z` (STORAGE_INVENTORY.json) | 2.081 GiB | 5.419 GiB in 28,906 files | 43.32 MiB |
| `2026-10-13T22:22:02Z` (STORAGE_RECLAIM.json) | 1.808 → 1.854 GiB after 43.23 MiB reclaimed | — | — |
| `2026-10-14T05:39:11Z` (same tool, stdout) | **0.826 GiB** | 5.354 GiB in 26,985 files | 43.32 MiB |
| `2026-10-14T05:44:41Z` (STORAGE_RECLAIM.json) | **5.456 GiB** | 5.331 GiB in 26,178 files | 43.32 MiB |
| `2026-10-14T05:44:52Z` (STORAGE_RECLAIM.json, applied) | 5.502 GiB | — | 43.35 MiB reclaimed; 19.81 MiB regenerated since |

Between `05:39:11Z` and `05:44:41Z` the volume gained **about 4.63 GiB** while the repository lost only
the ~43 MiB its own sweep returned. That recovery happened **outside this repository** and is
recorded here as such rather than credited to this work package. Two readings of the same volume,
five minutes apart, one of them before a refusal and one after a resumption: the lesson is that the
repository's floor is set by who else lives on the volume.

## 2. Who else lives on the volume

Walked read-only with a per-directory time budget; sizes are the walk's own sum of file lengths.
The repository is **5.33 GiB — 2.25% of the volume.**

| Path | Size | Kind |
| --- | --- | --- |
| `C:\Users\GVLLFR0035\AppData\Local` | **85,457.7 MiB** | host user data |
| `C:\Windows` | 33,775.4 MiB | operating system |
| `C:\Program Files` | 20,050.6 MiB | installed software |
| `C:\Users\GVLLFR0035\AppData\Roaming` | 11,738.3 MiB | host user data |
| `C:\Program Files (x86)` | 9,978.4 MiB | installed software |
| `C:\Users\GVLLFR0035\Downloads` | 7,906.7 MiB | user data |
| `C:\ProgramData` | 1,976.0 MiB | installed software |
| `C:\Users\GVLLFR0035\.cache` | 1,486.5 MiB | tool cache (outside the repository) |
| `C:\Users\GVLLFR0035\Documents` | 1,302.1 MiB | user data |
| `C:\Users\GVLLFR0035\.docker` | 75.3 MiB | tool cache |
| `C:\Users\GVLLFR0035\.npm` | 52.3 MiB | tool cache |

The three largest tenants inside `AppData\Local` and `AppData\Roaming`, where the volume's growth
lives:

| Path | Size | What it is |
| --- | --- | --- |
| `AppData\Local\Temp` | **29,747.9 MiB** | temporary files, by definition regenerable |
| `AppData\Local\Microsoft` | 14,714.8 MiB | browser/profile/Teams caches |
| `AppData\Local\Programs` | 7,193.1 MiB | per-user installed software |
| `AppData\Local\wsl` | 6,310.0 MiB | WSL distributions (data, not cache) |
| `AppData\Roaming\Msty` | 6,503.1 MiB | local model files (data, re-downloadable) |
| `AppData\Local\ms-playwright` | 3,353.6 MiB | browser builds for tests (regenerable) |
| `AppData\Local\hermes` | 2,832.5 MiB | user data |
| `AppData\Local\npm-cache` | 1,185.9 MiB | package cache (regenerable) |
| `AppData\Roaming\Code` | 1,693.3 MiB | editor state/extensions |
| `AppData\Roaming\npm` | 1,069.5 MiB | global packages |
| `Downloads\bot freebuff` | 5,482.4 MiB | **this repository** |

`AppData\Local\Temp` alone, by the age of its newest write:

| Newest write | Size | Files |
| --- | --- | --- |
| under 6 h | 0.0 GiB | 13 |
| 6–24 h | 1.17 GiB | 5,503 |
| 1–7 days | 23.05 GiB | 181,850 |
| over 7 days | 4.84 GiB | 49,252 |
| **total** | **29.05 GiB** | 236,618 |

## 3. The plan — for the owner, not for this work package

Ordered by how little can go wrong. None of it has been run.

1. **Clear temporary files older than 24 hours in `%LOCALAPPDATA%\Temp`** (≈27.9 GiB). Prefer the
   platform's own tool (`Settings → System → Storage → Temporary files`, or `cleanmgr`) over a blind
   delete: some files are held open by running processes and the platform skips those, where a raw
   `Remove-Item` reports errors and can disturb a live application. This single action returns ~28 GiB
   — more than five times the 5 GiB healthy floor the lane waits below.
2. **Regenerable tool caches outside the repository** (`ms-playwright` 3.35 GiB, `npm-cache` 1.19 GiB,
   `.cache` 1.49 GiB, `AppData\Roaming\npm` 1.07 GiB): safe to remove, each rebuilt on next use. They
   are the tools' own stores, so deleting them is the owner's call, not a repository cleanup.
3. **Duplicate downloads** (`Downloads\github analisis_e13bd` 973 MiB,
   `Downloads\daily_stock_analysis-main` 970 MiB, the `bot-freebuff-*` labs): the owner knows what
   these are; a repository agent does not.
4. **Do not touch, under any reading of this plan:** `data/`, `evidence/`, other workstreams'
   `reports/`, `src/`, `config/`, or anything under `.git`. They are this project's record, and the
   disk guard's refusal is a *correct* behaviour, not a reason to delete evidence.

## 4. What this work package did and did not do about it

- Did: inventoried the repository by kind and owner (`STORAGE_INVENTORY.json`/`.md`), reclaimed only
  tool caches that each passed three checks at the instant of deletion (cache by name, untracked by
  git, named in `.gitignore`), and recorded each sweep in `STORAGE_RECLAIM_HISTORY.jsonl`.
- Did not: delete any evidence, market data, other workstream cost or user data; did not touch
  anything outside the repository, including the 29.05 GiB of temporary files in item 1.
- The reason is not tidiness. The mission's rule is that a destructive action outside the authorised
  scope stops and becomes a plan; this document is that plan.
