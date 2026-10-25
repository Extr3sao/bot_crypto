# WP-9B — Disk budget audit

> `DISK_BUDGET_MEASURED` · generated `2026-10-11T20:53:13Z` ·
> mode: OFFLINE READ-ONLY — no process started, no segment read, no file written outside data/recovery/wp9/

## 1. The two windows

| | window 1 `paper-lab-continuous-02` | window 2 `paper-lab-continuous-03` |
| --- | --- | --- |
| sealed manifest | yes | **no** |
| wall | 4.16 h | 5.89 h |
| start → end (UTC) | 2026-09-29T22:59:18.288000Z → 2026-09-30T03:08:51.773000Z | 2026-09-30T17:53:01.788000Z → 2026-09-30T23:46:14.091000Z |
| bytes written | 799,632,725 | measured from names |
| rate | **192.25 MB/h** | **159.77 MB/h** |
| how it ended | `disk budget` (`CONTROLLED_STOP`) | `None` — no stop recorded |
| children at the end | collector stopped, paper kept cycling | {'paper': 'RUNNING', 'collector': 'RUNNING', 'retention': 'RUNNING', 'strategy_lab': 'RUNNING'}, {'paper': 0, 'collector': 0, 'retention': 0, 'strategy_lab': 0} restarts |
| free disk at the end | 11.02 GB (reported) | 31.502 GB |

Uncompressed the sealed window wrote 14.23 GB and stored 0.800 GB (17.79x ratio).

## 2. Why 24 h was impossible in window 1

- **WP9-DISK-01** (CONFIGURATION_DEFECT) — window 1 was launched with a 800 MB collector valve while its own measured rate was 192.25 MB/h, so the valve fills in 4.2 h: 24 h was arithmetically impossible from the first byte, and no code defect was involved
- **WP9-DISK-02** (UNRECORDED_TERMINATION) — window 2 stopped after 5.89 h with every child RUNNING, {'paper': 0, 'collector': 0, 'retention': 0, 'strategy_lab': 0} restarts, disk at 31.502 GB free and the valve only 1.74 GB used: nothing in the record says why, and no manifest was sealed, so the window's data cannot be used as evidence
- **WP9-DISK-03** (SHARED_HOST_PRESSURE) — free space on this host moved by far more than the lane wrote, and 94 % of the volume is already in use by other writers, so a budget that counts only this lane's bytes budgets for a machine that does not exist

## 3. Requirement per horizon

Planning rate: **192.25 MB/h** (the higher of the two windows: a budget derived from the cheaper window under-provisions the next one by construction). Reserve 2.00 GB.

| horizon | required | +50 % stress | free after (mean) | fits | free after (stress) | fits |
| --- | --- | --- | --- | --- | --- | --- |
| 24 h | 4.62 GB | 6.93 GB | 11.08 GB | yes | 8.77 GB | yes |
| 48 h | 9.24 GB | 13.85 GB | 6.46 GB | yes | 1.84 GB | yes |
| 72 h | 13.85 GB | 20.78 GB | 1.84 GB | yes | -5.09 GB | **no** |

Recommended valve per horizon (`--collector-max-bytes`): 24 h → 6,927,089,253 B, 48 h → 13,854,178,507 B, 72 h → 20,781,267,761 B

## 4. Where the bytes go

| component | bytes | share |
| --- | ---: | ---: |
| forward_segments | 1,740,177,336 | 99.0945% |
| lab_run_dirs | 14,218,320 | 0.8097% |
| forward_aggregated | 846,767 | 0.0482% |
| forward_lineage | 515,395 | 0.0293% |
| forward_manifest | 310,866 | 0.0177% |
| forward_reports | 8,268 | 0.0005% |
| forward_state | 974 | 0.0001% |

Non-segment overhead: 1,682,270 B (0.0960% of the lane), i.e. 0.167 MB/h measured over 10.05 h of capture.

## 5. What this authorises

* a **disk budget preflight** in the launcher, because the defect of window 1 was knowable before it started and is arithmetic rather than physics;
* a reserve that covers the *host*, not just the lane, because the volume is 93.1% full and moved -5.15 GB while the lane wrote 1.74 GB;
* **not** a bigger valve on its own: raising the budget without a preflight only moves the failure to the host.

## 6. Checks

| check | result |
| --- | --- |
| the sealed window's published rate reproduces from its own bytes/time | `PASS` |
| the filesystem agrees with the sealed manifest's byte counter | `PASS` |
| the unsealed window is measured from segment names, not from mtimes | `PASS` |
| no SQLite/embedded database carries market data (gzip JSONL only) | `PASS` |
| retention deleted no authoritative raw data | `PASS` |
| every horizon is planned at the stress rate as well as the mean | `PASS` |

