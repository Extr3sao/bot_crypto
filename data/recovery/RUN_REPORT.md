# RUN REPORT — POST RFC-049 / ACTIVE RECOVERY

- generated `2026-10-10T19:46:11Z` · head `108c44d08f7a` · branch ``
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
| `data/recovery/CAMPAIGN_STATE_VIEW.json` | True | `8e1f888f8e4e8251` |
| `data/recovery/CAMPAIGN_STATE_VIEW_REPORT.md` | True | `d9dc4e2fb834a08c` |
| `data/recovery/ACTIVE_ECONOMIC_AUDIT.json` | True | `710f106821f1cf5a` |
| `data/recovery/ACTIVE_ECONOMIC_AUDIT.md` | True | `78d3909ba4443749` |
| `data/recovery/ACTIVE_RECOVERY_ROADMAP.md` | True | `48d92b379b3be5e6` |
| `data/recovery/RFC049_POST_CLOSURE_REPORT.md` | True | `ab2e138c32acbcff` |
| `data/recovery/INDEPENDENT_VERIFICATION.json` | True | `2f96d4a5d9284416` |
| `data/recovery/FINAL_REPORT.md` | True | `d0219388dbca59c1` |
| `scripts/campaign_state_view.py` | True | `6d46c16e14274821` |
| `scripts/active_economic_audit.py` | True | `12b84b059e917ee7` |
| `scripts/recovery_verify.py` | True | `c6d1dd67b3c6a9cc` |
| `tests/unit/research/test_active_recovery_wp.py` | True | `e927269536eec4c4` |

## Notes

- a command not executed in this invocation is reported as NOT_EXECUTED, never as passing
- the research suite is a regression run over tests/unit/research; its count is in the output tail
- the report is written once before the commands run and rewritten with their real exit codes, so the verification step can see a complete deliverable set

