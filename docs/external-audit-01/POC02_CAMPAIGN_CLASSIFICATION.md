# POC02 CAMPAIGN CLASSIFICATION — POC-02-paper-clean-01

Checkpoint: **MA-DIRECTION-ARBITRATION-AND-POC02-REPAIR-01** (A1 / TRACK H)

| Field | Value |
| --- | --- |
| CAMPAIGN_ID | `POC-02-paper-clean-01` |
| CLASSIFICATION | **DIAGNOSTIC_BLOCKED_CAMPAIGN** |
| REASON | `STRUCTURAL_AGENT_DIRECTION_CONFLICT` (proven in DIR-AUDIT-01, B1/B2; reproduced naturally in `test_poc02_natural_conflict_reproduction`) |

## Honesty rules (binding)

1. **No frequency or profitability evidence may be claimed from this
   campaign.** 0 completed valid days, 0 paper trades, 0 shadow captures;
   the coverage contract (≥ 0.80) was never evaluated against a completed
   day and MUST NOT be retroactively scored.
2. The campaign is **preserved as execution evidence**: 11 runtime cycles,
   33 observation windows, 18 attributed candidates, all frozen with SHA-256
   artifact hashes in `POC02_PRE_REPAIR_BASELINE.*` and
   `docs/external-audit-01/poc02-pre-repair/`.
3. The campaign is closed **observationally** — no data was rewritten, no
   artifacts deleted, the daily runner's identity and state files remain
   untouched. No replacement claims POC02's history.
4. Successor: `POC-02-R2-direction-arbitration-01` (fresh identity, fresh
   accounting, frozen corrected composition — see `POC02_R2_MANIFEST.md`).
