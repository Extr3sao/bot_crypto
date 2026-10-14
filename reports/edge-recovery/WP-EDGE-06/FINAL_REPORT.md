# WP-EDGE-06 — FINAL REPORT

*Read at `2026-10-14T08:18:17Z` from `89b5e2210c8b` on branch `agent/edge-recovery/WP-EDGE-00-baseline`. One reading, three reports: the technical one, the run record and this one are renderings of the same frozen dictionary.*

## 1. In one line

**`CLOSED_WITH_OPEN_ITEMS`** — every acceptance row that could be measured passes (7/7 independent checks, 8 sabotages, 0 undetected), and the ingestion is **blocked by the volume, not by this work package**: 1.237 GiB free is `BELOW_CRITICAL`, below the 2 GiB the lane refuses under.

## 2. Track A — operational closure

| Item | What was done | Evidence |
| --- | --- | --- |
| Branch, remote, commits | Verified, then published: the local branch `agent/edge-recovery/WP-EDGE-00-baseline` was pushed without force, fast-forwarding a remote that held no copy of it | `GITHUB_STATE.json` |
| External storage audited | A read-only, repeatable walk of the volume's other tenants; two runs five minutes apart show `AppData/Local` moving 74686.0 MiB | `VOLUME_TENANTS.md` |
| Disk margin recovered | 45591379 bytes of this repository's own tool caches, each re-checked at the instant of deletion; the rest is the volume owner's decision | `STORAGE_RECLAIM.md` |
| Reconciliation in the cadence | A scheduled tick that consumed its slot now re-reads the lane and carries the receipt inside its own record; a failed re-read never changes the tick's verdict | `test_edge06_cadence.py` |
| WP-9B host-disk dependency | Four tests now declare the volume they read; 15/15 pass at 1.2 GiB free, the condition under which three of them failed | `test_wp9_disk_budget.py` |
| Stale artefacts | Three of the four repaired by regenerating the derived view (no frozen evidence edited); the fourth diagnosed as a conflict between two published expectations, and left failing on purpose | `VERIFICATION.md`, §4 below |
| Strategies and risk frozen | No path under `config/risk.yaml`, `src/trading_bot/risk`, `src/trading_bot/strategies` or the campaign's candidates has moved since the freeze; `PARAMS_HASH` unchanged | verification check `freeze` |

## 3. Track B — economic research

### 3.1 The audit answers the cost question with the frozen data

the gross expectation is negative in every window measured, before a single fee is charged: DEV:BASE -151.71 USDT over 290 trades (-10.46 bps/trade); OOS:BASE -19.91 USDT over 63 trades (-6.32 bps/trade); VAL:BASE -70.15 USDT over 344 trades (-4.08 bps/trade). Costs are the larger part of the net loss, but they are not the cause: a book that needed only a fee cut would show a positive gross against a negative net. Lowering fees cannot move a negative expectancy across zero — only a different setup, a different entry, or a longer hold can.

### 3.2 The families, and what each one earned

| Family | Answers | Verdict | The gate said |
| --- | --- | --- | --- |
| `edge06_fade_extension` |  | **REJECT_NO_GROSS_EDGE** | `REJECT` |
| `edge06_trend_fixed` |  | **ADMIT** | `ADMIT` |
| `edge06_xs_momentum` |  | **INSUFFICIENT_EVIDENCE** | `INSUFFICIENT_EVIDENCE` |

The three results in one paragraph: the fade back to the mean is **rejected** — its gross is negative before costs, like the intraday book's; the relative-strength book is **insufficient evidence** — its out-of-sample net is positive but one trade carries 63.7 % of it, over the frozen 50 % limit; and the frozen trend *entry* with a fixed 3×ATR target instead of a trail **clears the gate**, with 113 out-of-sample trades instead of 52, the largest trade only 22.2 % of the net instead of 79.87 %, and a positive net after removing that trade. That last reading is the useful one: it says the concentration that stopped the frozen 4h book was the **exit**, not the entry.

**Nothing here is validated.** The out-of-sample window had already been read by the frozen ruleset and by WP-EDGE-02's robustness analysis, so clearing the gate there is 'not yet rejected' and never confirmation; the report says so beside every verdict, and no strategy is promoted, sized or traded.

## 4. What this work package does NOT declare

- Not `CERTIFIED`, not `READY_FOR_PAPER`, not `PRODUCTION_READY`, and no profitability.
- **No forward day is shortened or added**: the 60-day gate is untouched.
- The lane is **not ingesting right now**: the volume is under its critical floor and the last three scheduled slots were refused before any market request, with 47 observing runs recorded in total.
- The four remaining suite failures are not hidden: one is the cost-barrier certification conflict described below, and three belong to other workstreams.
- The cost-barrier certification record was **not** re-issued. It pins a digest of `data/recovery/ACTIVE_ECONOMIC_AUDIT.json` from before that view was regenerated on 2026-10-12, while the clean-checkout rehearsal requires exactly that regeneration. Two published expectations contradict each other; repairing either one silently would be choosing which of them to believe. It is reported for its owner.
- No credential was read, stored or printed; no order was sent (`order_sent: false`); no risk limit, sizing rule or promotion gate was modified.

## 5. The next actions, in order of what unblocks the most

1. **Clear temporary files older than 24 hours in `%LOCALAPPDATA%\Temp`** — 27.9 GiB on this reading, more than five times the healthy floor. It is the only thing standing between this lane and continuous ingestion, and it is the volume owner's call, not a repository cleanup.
2. **Decide the fate of the cost-barrier certification record** — re-issue it against the current audit, or exempt the audit from byte-identity and certify its inputs. Its owner is the only actor who can say which.
3. **Give the fixed-target trend entry a genuinely unread window** before it is treated as anything: a new pre-registered run on a corpus that has not been read, per `HYPOTHESES.md` §5.

---

### The reading this report was rendered from

| Figure | Value |
| --- | --- |
| `as_of_utc` | `2026-10-14T08:18:17Z` |
| `head` | `89b5e2210c8b5d8f6bfd7d11c13eefb8b693b6f1` |
| `branch` | `agent/edge-recovery/WP-EDGE-00-baseline` |
| `worktree_dirty_entries` | `136` |
| `worktree_dirty_entries_of_this_work_package` | `1` |
| `volume.free_bytes` | `1328234496` |
| `volume.free_gib` | `1.237` |
| `volume.total_gib` | `237.5` |
| `volume.critical_floor_gib` | `2.0` |
| `volume.healthy_floor_gib` | `5.0` |
| `volume.verdict` | `BELOW_CRITICAL` |
| `storage.reclaimed_bytes` | `45591379` |
| `storage.reclaimed_mib` | `43.48` |
| `storage.verdict_before` | `ABOVE_CRITICAL_BELOW_HEALTHY` |
| `storage.verdict_after` | `ABOVE_CRITICAL_BELOW_HEALTHY` |
| `storage.repository_bytes` | `5750585960` |
| `storage.repository_share_of_volume_pct` | `2.25` |
| `storage.safe_reclaimable_mib` | `43.48` |
| `storage.tenants_total_gib` | `166.87` |
| `storage.tenants_all_measured` | `False` |
| `storage.appdata_local_mib` | `74686.0` |
| `storage.appdata_local_measured` | `False` |
| `storage.temp_total_gib` | `29.27` |
| `storage.temp_older_than_a_day_gib` | `27.9` |
