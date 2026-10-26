# WP-051-02K — final report

**Package:** WP-051-02K · **Experiment:** EXP-004A phase 3 (EDGE04) · **Date:** 2026-10-23 ·
**Verdict: `BLOCKED`** — `capacity=INSUFFICIENT`, `continuity=PASS`, `evidence=INTACT`,
`contract=UNCHANGED`, `tests=PASS (32/32)`, `verification=PASS`.

> The gap did not close, and this report does not pretend it did. What changed is that the gap is now
> a number with an owner, a recovery procedure and no administrator in the path: **14.16 GiB in five
> named paths**, of which this package freed **58.7 MiB** that were its own.

## 1. Capacity

| Moment | Free | Deficit vs the p90 budget |
| --- | --- | --- |
| 02J, 11:32Z | 3.2519 GiB | 11.317 GiB |
| 02K `--before`, 13:39Z | **1.4558 GiB** | **13.108 GiB** |
| 02K `--after`, 13:46Z | **1.4985 GiB** | **13.066 GiB** |
| Independent verifier | 1.49 GiB | 13.066 GiB |

Two instruments (`shutil.disk_usage`, `GetDiskFreeSpaceExW`) agree byte for byte in all three
readings. The volume lost **1.8 GiB between 11:32Z and 13:39Z**, which is the fact that matters: the
eight-day margin 02J published is being spent in real time.

## 2. Budget

Recomputed from the observer's own readings: **11 complete days, p90 drawdown 12.467 GiB, floor
2 GiB, own footprint 0.0967 GiB over 90 days → required 14.564 GiB**. The criterion was not touched
(p90 + floor + own growth; the maximum is reported, never used). Difference from 02J: −1 MiB, from
recomputing the campaign's own growth.

`DEF-02K-01` (new, open): 02J's `capacity()` anded the verdict with `not refused_total`, i.e. with
167 immutable historical refusals, so it could never return `SUFFICIENT`. 02K separates the two
facts — budget decides capacity, refusals are reported as history — and leaves the defect recorded
rather than quietly redefining the rule.

## 3. Where the disk went

`VOLUME_INVENTORY.json`: 9,155 rows in 139 s, no truncation, junctions skipped. The first-level
partition explains **230.38 of 236.09 GiB (97.58 %)**; the remaining **5.70 GiB** are trees this
process cannot read (`System Volume Information`, `Recovery`, locked system files).

| Consumer | Size | Owner |
| --- | --- | --- |
| `C:\Users` | 131.80 GiB | user |
| `C:\Windows` | 33.93 GiB | system |
| `C:\pagefile.sys` | 26.59 GiB | Windows |
| `C:\Program Files` | 20.39 GiB | system |
| `C:\Program Files (x86)` | 9.20 GiB | system |
| `C:\ESD` | 4.58 GiB | Windows Setup |

The single most important measurement: the **campaign's whole store is 14 MB and grows 1.15 MB/day
(0.0967 GiB across the window)**. It is 0.04 % of the volume. The 4–15 GiB/day churn is the host —
`python.exe`, `bun.exe`, `SearchIndexer.exe`, `chrome.exe` — exactly as 02J's per-process counters
showed, with no watched tree growing. **Nothing to delete inside the campaign; the space is outside
it.**

## 4. What this package freed

**209 directories, 61,520,363 B (58.7 MiB)**, all untracked byte-compiled caches in this worktree and
in the campaign repository. `--clean` asks `git ls-files` before deleting and records what it
refused to touch. That is 0.5 % of the gap, and it is claimed as 0.5 %, not as a fix.

## 5. What it asks for instead

`AUTHORISATION_REQUEST.json` — **5 paths, 14.16 GiB**, against a 14.066 GiB target (gap + 1 GiB of
slack). Cheapest recovery first; no administrator, no user document, no system change:

| Path | Size | Recovery |
| --- | --- | --- |
| `%LOCALAPPDATA%\ms-playwright` | 3.27 GiB | `python -m playwright install chromium` |
| `%LOCALAPPDATA%\hermes` | 2.00 GiB | re-run the tool |
| `%USERPROFILE%\.cache` | 1.30 GiB | refills itself |
| `%LOCALAPPDATA%\Temp` | 6.59 GiB | none: scratch has no origin |
| `Downloads\bot_crypto_004g` | 0.99 GiB | `git bundle` + `git archive` before deleting |

Measurements that are deliberately **not** asked for: `pagefile.sys` (system change + reboot), WSL
(exporting 6 GiB does not fit in the 1.5 GiB that needs freeing), `C:\ESD` (breaks a pending
upgrade, needs admin), `Msty` (app state, not a proven cache), Edge/OneDrive profiles, and the
document folders `Downloads`, `OneDrive`, `Documents`, `Desktop` — a 28.69 GiB folder of documents is
not a capacity decision.

## 6. Continuity

`STORE_INTEGRITY.json` **19/19 PASS**: append-only files keep their prefix (append allowed, rewrite
caught), all 11 write-once shards keep sha256 **and** `mtime_ns`, and the rewritten files keep their
contract (floor 2 GiB, warning 5 GiB, declared budget). **0 rows re-fetched, 0 re-timestamped**,
contract `git diff` empty, window 90 d / 6,480 rows / floor 0.9 unchanged.

Non-essential writes: the guard is already refusing ticks below its 2 GiB floor — **167 refusals in
history, 29 today, the last at 13:40:55Z with 1,547,677,696 B free**. That is the measured proof that
the campaign is in protected mode now, not a projection about tomorrow.

## 7. Evidence

| Artefact | Content |
| --- | --- |
| `CAPACITY_RECOVERY_REPORT.md` | the full report |
| `CAPACITY_RECOVERY.json` | verdict, inventory summary, options, coverage plan |
| `SNAPSHOT_BEFORE.json` / `SNAPSHOT_AFTER.json` | volume, budget, refusals, store fingerprint |
| `VOLUME_INVENTORY.json` | 9,155 measured rows |
| `CLEANUP_EVIDENCE.json` | 209 directories, 61,520,363 B |
| `STORE_INTEGRITY.json` | 19/19 PASS |
| `AUTHORISATION_REQUEST.json` | 5 items, exact paths, risks, recovery |
| `TEST_EVIDENCE.json` | 32 passed, exit 0, suite sha256 |
| `INDEPENDENT_VERIFICATION_02K.json` | separate program, 0 FAIL |
| `FINAL_REPORT.json` | this verdict, machine-readable |

## 8. Still open

`DEF-02I-07` (interactive logon unproven, needs admin) · `DEF-02I-08` (the `tests/unit/research`
directory still breaks on a pre-existing import) · `ALERT_REMOTE` (no remote channel) ·
`DEF-02K-01` (02J's verdict could never say SUFFICIENT).

## 9. What would turn this into `PASS`

Free the five named paths, re-run `--after`, `--report`, `--final` and the verifier. Until capacity
reports `PASS` with an independent measurement, the campaign keeps refusing ticks and losing whole
days — **72 rows per lost day**, and one day is already lost.
