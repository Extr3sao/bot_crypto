# WP-051-02F — run report `20261022T140037Z-de5d3329`

- **state**: `CAPTURED_VERIFIED`
- **run directory**: `docs/agentic/exp004a/wp051_02f/evidence/20261022T140037Z-de5d3329`
- **independent verification**: `PASS`
- **head**: `f20dff9b71fd10a5f110ab6cae88e817c6f5d428` on `agent/ai-bots/RFC-TAP-AI-BOTS-003`
- **started**: 2026-10-22T14:00:37.581Z — **finished**: 2026-10-22T14:03:31.539Z
- **capture decision**: 2026-10-22T14:02:46.640Z

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
| `1h:BTC` | 5654 | 2026-10-22T13:00:00.000Z | 2026-10-22T14:00:43.904Z | 14 | 14 |
| `1h:ETH` | 5654 | 2026-10-22T13:00:00.000Z | 2026-10-22T14:00:43.904Z | 14 | 14 |
| `1h:SOL` | 5654 | 2026-10-22T13:00:00.000Z | 2026-10-22T14:00:43.904Z | 14 | 14 |

## The capture

| slice | exit | meaning | dataset | bytes |
| --- | --- | --- | --- | --- |
| `1h:BTC` | 0 | OK | data/exp004a/EXP-004A-1H-BTC.jsonl | 4403 |
| `1h:ETH` | 0 | OK | data/exp004a/EXP-004A-1H-ETH.jsonl | 4348 |
| `1h:SOL` | 0 | OK | data/exp004a/EXP-004A-1H-SOL.jsonl | 4296 |

## The temporal guard

| slice | verdict | rows | violations |
| --- | --- | --- | --- |
| `1h:BTC` | PASS | 14 | 0 |
| `1h:ETH` | PASS | 14 | 0 |
| `1h:SOL` | PASS | 14 | 0 |

## The gates this package did not move

- `C_004`: PASS
- `C_013`: TIME_PROOF_WEAK
- `C_015`: PASS (provenance of the declaration chain); unchanged by this runner
- `C_016`: UNREACHABLE_UNDER_DECLARED_COST_MODEL
- `PAPER_VALIDATION`: NOT_PASS
- `CERTIFICATION`: BLOCKED
- `PROMOTION`: NO_PROMOTION

## The notes

- the independent verifier passed the claim: the published bytes are the store's own bytes and every row is temporally admissible

This report is not a certification, a paper validation or a promotion. `economic_executions` in the JSON twin is 0 and stays 0.
