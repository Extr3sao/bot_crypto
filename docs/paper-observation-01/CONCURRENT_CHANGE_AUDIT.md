# CONCURRENT_CHANGE_AUDIT — PAPER-OBSERVATION-CAMPAIGN-01

```text
AUDIT_DATE: 2026-09-06
BASE_IMPLEMENTATION: 1dfeea8b2c5e3272af9f7dc501ca5f43873eda82 (DEMO_PAPER_01 CERTIFIED, 27/27)
CERTIFICATION_RECORD_COMMIT: a282fcc
CONCURRENT_FILES: 2
CONCURRENT_LINES: 438 (+349 src, +89 validator script)
PATCH_FINGERPRINT (sha256):
  demo module diff:  08a7ce3cab49a3f3d6c03c27f0f241c4635f5daa4c2b6ed3fd6cd305a074629f
  validator script:  91a00dfd904894b5eb81b520a9dd671b146cf757729b9e0e3eba1e57e4e56de7
CAPTURED_AT: docs/paper-observation-01/evidence/concurrent_wip_demo_module.patch
             docs/paper-observation-01/evidence/concurrent_wip_validator.py
USER ORIGINAL WORKTREE: untouched (implementation done in .worktrees/poc01-setup on feat/poc01-setup)
```

Runtime reachability of the concurrent code at capture time: **never executed
by certification**. Reachable only via
`python -m trading_bot.demo.paper_multi_agent --campaign ...` (dispatch inside
`main()`) and via the untracked validator script. It wrapped the certified
functions (no monkeypatching, no threshold changes), so certified MA/Risk/
Paper behavior was **not** redefined by it — but its persistence shell was
non-durable and identity-unsafe.

## Per-change classification

| File | Change | Purpose (inferred) | Runtime reachability | POC01 requirement | Decision | Evidence / disposition |
|---|---|---|---|---|---|---|
| `src/trading_bot/demo/paper_multi_agent.py` | `--campaign` / `--resume` CLI flags + `run_campaign_observation()` dispatch in `main()` | One-command campaign entry | Reachable via module CLI only | §32 campaign CLI | **REJECT** (location) | Certified module must stay untouched (§0); CLI re-implemented in `trading_bot.paper_observation.runtime.main` with start/resume/status/stop/report/dashboard |
| same file | `DurableCampaignState` dataclass | Durable campaign state | Wrapped demo runs | §5 durable state | **ADAPT** | Field set carried into `poc01-state-v1` (schema_version, campaign identity, processed decision/order/fill ids, open positions, closed trades, PnL, daily metrics, errors, heartbeat); added schema versioning, atomic write, strict identity validation — all absent in WIP |
| same file | `_campaign_id_from_name()` | Campaign identity | Same | §4 campaign_id | **ADAPT** | Renamed to `poc01-…-001` form; made **restart-stable** (WIP embedded creation date → `--resume` could never find yesterday's campaign); hierarchy campaign_id ⊃ run_id ⊃ trace_id ⊃ artifacts enforced |
| same file | `_load/_save_durable_campaign_state()` | Persistence | Same | §5/§6 | **ADAPT** | Rebuilt as `CampaignStateStore`: atomic `tmp + os.replace` write (WIP used plain `write_text`), strict schema check, explicit `CorruptedStateError`; WIP silently **overwrote `campaign_id` on mismatch** — now a hard identity error |
| same file | `_write_daily_campaign_reports()` / `_write_campaign_report()` | Daily + campaign reports | Same | §14/§15 | **ADAPT** | Rebuilt with computed per-day aggregates, funnel, reasons, attribution, performance; WIP wrote **static markdown bullet labels with no values** and hardcoded `status: POC01_INFRA_READY` |
| same file | `_maybe_persist_campaign_state()` | State sync | Same | §5/§6/§30 | **REJECT** | Hardcoded `real_broker_calls=0/private_exchange_calls=0` regardless of runtime, `last_processed_market_timestamp=0`, no reconciliation hook, no fill/order dedup on write |
| same file | `run_campaign_observation()` | Campaign runner | Same | §6/§7/§33 | **REJECT** (replaced) | Delegated to `run_fixture_demo`/`run_real_market_demo` and re-tagged the resulting state: no resume rehydration of RiskManager/PaperBroker, no DecisionPackage dedup, no safe stop, campaign metrics == one demo run. Replaced by `CampaignRuntime` |
| `scripts/validate_paper_observation_campaign_01.py` | Whole file (89 lines) | Independent validator | Never executed | §37 | **REPLACE** | Checked only file existence + `status == READY`; no boundary verification. New validator: **25 checks** covering §37's required list, and no longer treats a fixture run as campaign performance (fixture tag → `EXCLUDED_FROM_CAMPAIGN_METRICS` path) |
| — | Verified-only adapter, RiskManager authority, PaperBroker-only, run/trace authority usage via certified functions | — | — | §2 freeze | **ALREADY_IMPLEMENTED** | WIP invoked the certified functions; the new runtime re-invokes them directly (`DecisionEngine`, verifier-v3, certified `DecisionToCandidateAdapter`, `RiskManager`, `PaperBroker`, `check_positions`) — no behavior change |

## Rollup

```text
ADOPTED: 0
ADAPTED: 5   (state schema, campaign identity, persistence, daily reports, campaign report)
REJECTED: 3  (CLI-in-certified-module location, _maybe_persist_campaign_state, run_campaign_observation)
REPLACED: 1  (independent validator)
ALREADY_IMPLEMENTED: 1 (certified boundary reuse)
UNRELATED: 0
```

## Guardrail verification

- `src/trading_bot/demo/paper_multi_agent.py` in the implementation worktree is
  byte-identical to the certified commit (`git diff 1dfeea8 -- <file>` is empty).
- No WIP code was copy-pasted into the new module; every adapted concept was
  re-implemented with durable/atomic/identity-safe semantics.
- No certified threshold, strategy, ranking, debate, decision, verifier, or
  risk limit was modified anywhere in `feat/poc01-setup`.
