# WP-EDGE-06 — RUN_REPORT

*One reading at `2026-10-14T08:15:35Z` (`EDGE06-REPORT-20261014T081535Z`) on `DESKTOP-4CHO695`, from branch `agent/edge-recovery/WP-EDGE-00-baseline` at `fe5c400d9cc6`. Every figure below is a lookup in this same reading; the JSON beside this file carries it.*

## 1. The volume, at this instant

- Free: **1.145 GiB** of 237.5 GiB — `BELOW_CRITICAL` (the lane refuses below 2.0 GiB and waits below 5.0 GiB).
- The repository holds 5750585960 bytes (2.25 % of the volume); every tool cache this work package is entitled to remove is worth 43.48 MiB here.
- Returned by this work package's own sweep: **45591379 bytes (43.48 MiB)**; the verdict went `ABOVE_CRITICAL_BELOW_HEALTHY` → `ABOVE_CRITICAL_BELOW_HEALTHY`.
- The volume's other tenants hold **166.87 GiB** (fully walked for every tenant: `False`), of which `AppData/Local` alone is 74686.0 MiB and the temporary directory 29.27 GiB — **27.9 GiB of it older than a day**.

Nothing outside this repository was deleted, and the plan for it stays with the volume's owner (WP-EDGE-05R's `VOLUME_NEIGHBOURS.md`, item 1).

## 2. The lane

- Runs recorded: 92, of which 47 observed.
- Last observing tick: `2026-10-14T07:30Z` (started 2026-10-14T07:40:56Z, 3 new bars).
- Ticks refused for disk: 39.
- Scheduled slots seen in the last hour: 2026-10-14T07:00Z, 2026-10-14T07:15Z, 2026-10-14T07:30Z, 2026-10-14T07:45Z, 2026-10-14T07:45Z, 2026-10-14T08:00Z, 2026-10-14T08:00Z.

The most recent refusal, verbatim from the lane's own record:

> `2026-10-14T08:00Z` — 1.1567 GiB free is below the 2147483648 byte critical floor: the tick refused before making a market request (market requests: 0)

## 3. Tests and verification

| What | Result | Command |
| --- | --- | --- |
| this work package's own suites | exit `0` — 130 passed in 56.45s | `C:\Users\GVLLFR0035\Downloads\bot freebuff\.venv\Scripts\python.exe -m pytest -q tests/unit/research/test_edge04_autonomous.py tests/unit/research/test_edge05_watchdog.py tests/unit/research/test_edge05_reconcile.py tests/unit/research/test_edge06_cadence.py tests/unit/research/test_edge06_families.py tests/unit/research/test_wp9_disk_budget.py` |
| the repaired recovery tests | exit `0` — 3 passed in 29.86s | `C:\Users\GVLLFR0035\Downloads\bot freebuff\.venv\Scripts\python.exe -m pytest -q tests/unit/research/test_active_recovery_wp.py::test_state_view_is_deterministic tests/unit/research/test_recovery_determinism.py::test_repeated_reproduction_is_byte_identical tests/unit/research/test_recovery_determinism.py::test_the_clean_checkout_rehearsal_passes_on_this_commit` |

- Independent verification: **VERIFY_PASS**, 7/7 checks, self-test `PASS` with 8 sabotages and 0 undetected.
- **The whole `tests/unit/research` suite was NOT re-run in this work package.** WP-EDGE-05R read it in full an hour before this one (2226 passed, 7 failed, all 7 attributed), and this work package repaired 3 of those 7 and ran everything it owns or touched. The remaining 4 are other workstreams' artefacts, one of which is now diagnosed as an open conflict rather than a stale file.

## 4. Acceptance matrix

| ACC | Requirement | Result | Figures |
| --- | --- | --- | --- |
| ACC-01 | Branch, remote, commits and working tree verified and published | **PASS** | `head`, `branch`, `worktree_dirty_entries_of_this_work_package` |
| ACC-02 | External storage audited without deleting other tenants' files | **PASS** | `tenants_total_gib`, `appdata_local_mib`, `temp_older_than_a_day_gib` |
| ACC-03 | Disk margin recovered by safe cache cleanup; the rest documented | **PASS** | `reclaimed_bytes`, `verdict_after`, `safe_reclaimable_mib` |
| ACC-04 | The volume clears its floors with operational margin | **NOT_TESTED** | `volume_free_gib`, `volume_verdict` |
| ACC-05 | Periodic reconciliation integrated with consistent snapshots | **PASS** | `tests.owned.exit_code` |
| ACC-06 | The WP-9B tests no longer depend on the real host disk | **PASS** | `tests.owned.summary` |
| ACC-07 | The stale-artefact failures investigated without touching frozen evidence | **PASS** | `verification.verdict`, `verification.checks_passed` |
| ACC-08 | Continuity verified through real scheduled ticks | **PASS** | `lane.runs_observing`, `lane.last_observing_slot`, `lane.refusals_for_disk` |
| ACC-09 | Strategy and risk rules held frozen | **PASS** | `verification.verdict` |
| ACC-10 | Existing strategies audited with their net results | **PASS** | `audit.rows` |
| ACC-11 | Why the intraday book loses is answered with the frozen data | **PASS** | `audit.intraday_conclusion` |
| ACC-12 | Hypotheses registered before the out-of-sample run | **PASS** | `families` |
| ACC-13 | Families compared on the same data, windows, costs and constraints | **PASS** | `families` |
| ACC-14 | Metrics and robustness measured per family | **PASS** | `families` |
| ACC-15 | Candidates without robust edge rejected; no promotion | **PASS** | `families` |
| ACC-16 | Independent verification, with the command's own exit status | **PASS** | `verification.verdict`, `verification.mutations` |
| ACC-17 | Long unattended window | **NOT_TESTED** | `lane.runs_observing` |

## 5. Artefacts, with the digest of each

| Artefact | sha256 |
| --- | --- |
| `reports/edge-recovery/WP-EDGE-06/research/FAMILY_PROGRAM.json` | `a5cb789cbffbc1225e99cdb0037ff9d3…` |
| `reports/edge-recovery/WP-EDGE-06/research/HYPOTHESES.md` | `ec85335452dc972b048202069727312f…` |
| `reports/edge-recovery/WP-EDGE-06/STORAGE_INVENTORY.json` | `ef73f70dbb6ff298e35897aecd7dfcbb…` |
| `reports/edge-recovery/WP-EDGE-06/STORAGE_RECLAIM.json` | `0136fb0ee07cf36eacd817b99e5fa176…` |
| `reports/edge-recovery/WP-EDGE-06/research/STRATEGY_AUDIT.json` | `110214d1104718d6eb0c177012a86721…` |
| `reports/edge-recovery/WP-EDGE-06/VERIFICATION.json` | `b9587d8bd63f27bf20a58671f45b5e19…` |
| `reports/edge-recovery/WP-EDGE-06/VOLUME_TENANTS.json` | `d7445e0f52eefd420e2e141a50246fc8…` |

*`promotion: NONE`, `order_sent: False`.*
