# WP-051-02F — run report `20261022T134802Z-821a8f05`

- **state**: `BLOCKED`
- **run directory**: `docs/agentic/exp004a/wp051_02f/evidence/20261022T134802Z-821a8f05`
- **independent verification**: `FAIL`
- **head**: `f20dff9b71fd10a5f110ab6cae88e817c6f5d428` on `agent/ai-bots/RFC-TAP-AI-BOTS-003`
- **started**: 2026-10-22T13:48:02.652Z — **finished**: 2026-10-22T13:50:24.813Z
- **capture decision**: none

## The frozen inputs

| artefact | worktree sha256 | git blob sha |
| --- | --- | --- |
| `config/preregistrations/EXP-004A.datasets.phase2.json` | `eb27cedc2626844daba9c82915c9258687e20072b774ca564142993ed6e7c01e` | `9421cc52a8a3366b3a1fa6998d547b0a002ed89b` |
| `scripts/exp004a_capture.py` | `af1ab7cc23980dadac83ba53d2a5f8c1c5f33f6b5dd4841dd58620b9bb421cb8` | `052832c2252a719c63d0859628ada648c799c6ce` |

The two columns are different magnitudes: the first hashes the bytes in this checkout, the second is the Git object id at HEAD. A CRLF checkout of an LF blob makes them differ without any drift in the committed content.

## The window

- declared: `2026-10-22T00:00:00.000Z` → `2027-01-20T00:00:00.000Z`
- state at the end of the run: `OPEN`

## The store

| series | rows | last bar opens | last ingest | bars in window | closed in window |
| --- | --- | --- | --- | --- | --- |
| `1h:BTC` | 5653 | 2026-10-22T12:00:00.000Z | 2026-10-22T13:25:58.067Z | 13 | 13 |
| `1h:ETH` | 5653 | 2026-10-22T12:00:00.000Z | 2026-10-22T13:25:58.067Z | 13 | 13 |
| `1h:SOL` | 5653 | 2026-10-22T12:00:00.000Z | 2026-10-22T13:25:58.067Z | 13 | 13 |

## The capture

| slice | exit | meaning | dataset | bytes |
| --- | --- | --- | --- | --- |

## The temporal guard

| slice | verdict | rows | violations |
| --- | --- | --- | --- |

## The gates this package did not move

- `C_004`: PASS
- `C_013`: TIME_PROOF_WEAK
- `C_015`: PASS (provenance of the declaration chain); unchanged by this runner
- `C_016`: UNREACHABLE_UNDER_DECLARED_COST_MODEL
- `PAPER_VALIDATION`: NOT_PASS
- `CERTIFICATION`: BLOCKED
- `PROMOTION`: NO_PROMOTION

## The notes

- the provenance controls did not pass: []; the freeze or the contract does not bind, and nothing is captured
- the independent verifier refused the claim (exit 2); its checks are in INDEPENDENT_VERIFICATION.json

This report is not a certification, a paper validation or a promotion. `economic_executions` in the JSON twin is 0 and stays 0.
