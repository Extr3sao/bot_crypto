# RUN REPORT — POST RFC-049 / ACTIVE RECOVERY

- generated `2026-10-10T20:07:02Z` · head `aed26c71efb9` · branch `main`
- mode: OFFLINE — no keys, no orders, no capital, no live path; only read-only audits and tests
- closure commit (WP-1): `108c44d` — Close RFC-049 Discovery 2 and retire the sealed OOS opening unused (24 files, this lane only)

## Commands

| step | command | exit | result |
| --- | --- | ---: | --- |
| campaign state view (WP-2) | `.venv/Scripts/python.exe scripts/campaign_state_view.py` | 0 | **PASS** |
| state view determinism | `.venv/Scripts/python.exe scripts/campaign_state_view.py --check` | 0 | **PASS** |
| ACTIVE economic audit (WP-3) | `.venv/Scripts/python.exe scripts/active_economic_audit.py` | 0 | **PASS** |
| audit determinism | `.venv/Scripts/python.exe scripts/active_economic_audit.py --check` | 0 | **PASS** |
| independent verification | `.venv/Scripts/python.exe scripts/recovery_verify.py` | 0 | **PASS** |
| new contract tests | `.venv/Scripts/python.exe -m pytest tests/unit/research/test_active_recovery_wp.py -q` | 0 | **PASS** |
| research suite (regression) | `.venv/Scripts/python.exe -m pytest tests/unit/research -q` | 0 | **PASS** |

## Artefacts

| path | exists | sha256 |
| --- | --- | --- |
| `data/recovery/CAMPAIGN_STATE_VIEW.json` | True | `538032fb95379a4d` |
| `data/recovery/CAMPAIGN_STATE_VIEW_REPORT.md` | True | `c76c712a775ec5d1` |
| `data/recovery/ACTIVE_ECONOMIC_AUDIT.json` | True | `31fc6d4f57248bed` |
| `data/recovery/ACTIVE_ECONOMIC_AUDIT.md` | True | `24652f8ccd5ca5bf` |
| `data/recovery/ACTIVE_RECOVERY_ROADMAP.md` | True | `48d92b379b3be5e6` |
| `data/recovery/RFC049_POST_CLOSURE_REPORT.md` | True | `ab2e138c32acbcff` |
| `data/recovery/INDEPENDENT_VERIFICATION.json` | True | `8440436ab8b7d221` |
| `data/recovery/FINAL_REPORT.md` | True | `d0219388dbca59c1` |
| `scripts/campaign_state_view.py` | True | `e94966b30b402140` |
| `scripts/active_economic_audit.py` | True | `a1d55ea37777a404` |
| `scripts/recovery_verify.py` | True | `c6d1dd67b3c6a9cc` |
| `tests/unit/research/test_active_recovery_wp.py` | True | `50d4403bd1658e99` |

## Notes

- a command not executed in this invocation is reported as NOT_EXECUTED, never as passing
- the research suite is a regression run over tests/unit/research; its count is in the output tail
- the report is written once before the commands run and rewritten with their real exit codes, so the verification step can see a complete deliverable set


## WP-8 — recovery determinism, state authority and clean checkout

The WP-1..WP-5 section above records the run that produced the lane's reports. WP-8 came
after, and it changed *how this lane reads its inputs*, not what it concludes. The full
report is [wp8/RUN_REPORT.md](wp8/RUN_REPORT.md); the short version:

| step | result |
| --- | --- |
| input bundle (`recovery_input_evidence.py --verify`) | VERIFIED, 0 failures |
| campaign state view / ACTIVE economic audit (+ `--check`) | PASS — and reproducible in a clean checkout |
| economic invariance of the repair | `IDENTICAL`: 0 changed findings, `admitted_for_paper` 0 → 0 |
| lane contract tests / determinism regressions / CI parity | 28 / 15 / 8 passed |
| global suite | 3390 passed, 3 deselected (the slow rehearsal tests) |
| clean-checkout rehearsal (`clean_checkout_rehearsal.py --scope full`) | **PASS** on `e07ce6c`, 4/4 artefacts state-identical, no input modified |
| sabotage proofs | 2/2 `SABOTAGE_DETECTED` (`wp8/evidence/SABOTAGE_*.json`) |
| independent verification | **PASS** 17/17 checks, 13/13 controls, `false_success 0` |

Three things a reader of the old report should know:

1. `data/recovery/CAMPAIGN_STATE_VIEW.json` and `data/recovery/ACTIVE_ECONOMIC_AUDIT.json`
   were **regenerated** in WP-8: they now resolve every input from the commit (or from a
   digest-pinned evidence copy) instead of from whatever the machine happened to hold. Their
   economic content did not move (see `wp8/evidence/ECONOMIC_INVARIANCE.json`), and the
   `INDEPENDENT_VERIFICATION.json` in this directory is the verifier's record of the repair.
2. The hash table above describes the artefacts as they stood when WP-1..WP-5 closed; the
   current files carry the identity of the repaired state, and their digests are in
   [wp8/RUN_REPORT.json](wp8/RUN_REPORT.json).
3. The WP-7 cost-barrier record that fingerprints the audit was re-issued as a consequence
   (`data/recovery/wp7/COST_BARRIER_CERTIFICATION.json`, `CERTIFIED` on `e07ce6c`, with the
   supersession block naming the record it replaced).

Governance is unchanged: `LIVE_TRADING = DISABLED`, `PAPER_PROMOTION = NOT_AUTHORIZED`,
sealed OOS `CANCELLED_NOT_OPENED`, `FALSE_SUCCESS = 0`, no strategy admitted (0 before and
after), no threshold, cost model or admission rule touched.
