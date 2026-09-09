# POC01 Continuity Certification — SHADOW-AND-LEGACY-VALIDATION-01

> Track A. Evidence gathered read-only. The campaign runtime was **not started,
> stopped, or restarted** by this checkpoint. Structural continuity is proven
> from durable state + code semantics; availability is certified separately.

## 1. Continuity lineage (structural proof)

| Field | Value | Source |
| --- | --- | --- |
| CAMPAIGN_ID_BEFORE | `POC-01-paper-observation-01` | `CAMPAIGN_STATE.json` (mtime 2026-09-08T19:12:49+02:00) |
| CAMPAIGN_ID_AFTER | `POC-01-paper-observation-01` | same durable file (no runtime run since; hash `6f4d41b6…`) |
| campaign_id equality | **SAME** — no new campaign created | resume path `_campaign_id_from_name()` is deterministic (`POC-01-` prefix); `_load_durable_campaign_state()` reloads existing state and never resets identity |
| RUN_LINEAGE | `demo-paper-01-fixture` preserved | `current_run` field intact |
| Decision IDs unique | 1 decision, 0 duplicates | validator check `candidate_ids_unique` |
| Trade/PnL history | 0 trades, 0.0 PnL — nothing overwritten | state + daily report |
| Daily report reset | NO — `2026-09-08/DAILY_REPORT.json` intact | file mtime unchanged |
| Accounting reset | NO — `pnl` dict + counters intact | state file |

### STOP/RESUME timestamps

| Field | Value |
| --- | --- |
| LAST_HEARTBEAT (≈STOP anchor) | `2026-09-08T17:12:49Z` (`runtime_state=RESUMED`) |
| RESUME_TIMESTAMP | **n/a — runtime is currently DOWN** (not resumed again since; no downtime re-encountered by this checkpoint) |
| DOWNTIME_SECONDS (observation gap) | ≥ 45,756 s (12.7 h from last heartbeat to checkpoint observation `2026-09-09T05:57:05Z`) |

### Downtime classification

- **MATERIAL_OBSERVATION_GAP** — the runtime is not alive; no scans/trades can
  occur during the gap. **But**: COMPLETED_VALID_DAYS is unaffected because
  D1 (the only completed day) was already finalized before the gap, and its
  validity under the existing frequency contract (`trades_day >= 3` →
  `day_ge_3=0`) does not depend on anything after it.
- **NOT DAY_INVALIDATING** for D1 (already closed and independent of the gap).
- Current partial day D2 (`2026-09-08`) remains PARTIAL_DAY and was never
  eligible for COMPLETED_VALID_DAYS regardless.

## 2. A1 — D1 FINALIZATION (canonical)

| Field | Value |
| --- | --- |
| D1_FINALIZED | **true** |
| BURN_IN_DATE | 2026-09-06 |
| BURN_IN_COUNTED | **false** |
| D1_DATE | 2026-09-07 |
| D1_VALID | **true** (day completed under observation contract; validity is about observation integrity, NOT alpha) |
| COMPLETED_VALID_DAYS (canonical) | **0** — D1 has `trades_day=0 < 3` |
| market_scans | 1 |
| trade_proposals | 0 |
| debates | 0 |
| selected | 0 |
| no_trade | 1 |
| verifier_verified | 1 (`VERIFIED`, `decision-package-verifier-v3`) |
| verifier_rejected | 0 |
| risk_accepts | 0 |
| risk_rejects | 0 |
| risk_rejections_by_reason | n/a (no rejects) |
| paper_opens | 0 |
| paper_closes | 0 |
| wins / losses | 0 / 0 |
| realized_pnl | 0.0 |
| unrealized_pnl | 0 |
| trades_day | 0 |
| trades_ge_3 | 0 |
| provider_failures | 0 (`errors=[]`) |
| data_gaps | none recorded |
| stale_events | 0 |
| future_events | 0 |
| FALSE_SUCCESS | 0 |

> ⚠️ One NO_TRADE day is **not alpha**. D1 proves pipeline integrity only.

Note: D1's decision cycle executed on fixture market data
(`provider=fake`, `run_id=demo-paper-01-fixture`). The campaign remains an
infrastructure/shell certification (status `POC01_INFRA_READY`), not a
real-market observation yet. This is recorded as-is; no claim upgrade is made.

## 3. A2 — D2 CURRENT STATE

| Field | Value |
| --- | --- |
| CURRENT_PARTIAL_DAY | 2026-09-08 (UTC) |
| Status | **PARTIAL_DAY** — never included in COMPLETED_VALID_DAYS or PERCENT_DAYS_GE_3 |
| Scans so far | 1 · selected 0 · no_trade 1 · trades 0 |

## 4. A3 — API / FRONTEND

| Check | Result | Classification |
| --- | --- | --- |
| `http://127.0.0.1:8766/api/campaign` | **000** (connection refused) | `API_SERVICE_DOWN` |
| Frontend `:8767` | **000** (connection refused) | `UI_SERVICE_DOWN` |
| Campaign runtime | DOWN (heartbeat 12.7 h stale; no listener on 876x) | **CAMPAIGN_DOWN** (process not alive at checkpoint time) |

- Per checkpoint rule: **no restart was performed** for UI recovery; also
  nothing in this repository binds ports 8766/8767 (verified by source scan) —
  the API/UI belong to the external campaign tooling, so recovery is an
  operational action outside this checkpoint's authority.
- `API_SERVICE_DOWN` ≠ `CAMPAIGN_DOWN` are recorded as distinct facts; here
  **both** are down. The durable campaign state remains intact and resumable
  under the existing resume contract (`resume=True` reloads the same
  `campaign_id` — proven structurally, not executed).

## 5. Safety counters at certification time

| Counter | Value |
| --- | --- |
| live_calls | 0 |
| real_broker_calls | 0 |
| private_exchange_calls | 0 |
| false_success | 0 |
| POC01_RUNTIME_CHANGED | 0 |
| POC01_PNL_CHANGED | 0 |
| POC01_TRADE_COUNT_CHANGED | 0 |

State-file integrity: sha256 of every campaign artifact recorded at checkpoint
start (`/tmp/poc01_hashes_before.txt`) and re-verified at checkpoint end —
byte-identical, proving this checkpoint consumed no future data and mutated
no campaign state.
