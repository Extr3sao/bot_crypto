# WP-051-02D preflight

**Run**: `wp051-02d/EXP-004A/2026-10-21`  
**HEAD**: `421590ced3ed435c95c92c09aed6b7bbe1898185`  
**Declaration**: `config/preregistrations/EXP-004A.datasets.phase2.json` (`EXP-004A.datasets.phase2/v1`)  
**Status**: `PASS`

| Control | Status | Detail |
| --- | --- | --- |
| `DECLARATION_SCHEMA` | `PASS` | 4 entries, schema 3.0 |
| `ORIGINAL_DECLARATION_UNCHANGED` | `PASS` | sha256 8946f871a97b7575... unchanged |
| `SUPERSEDES_LINK` | `PASS` | successor cites blob 43c9deea29a8... |
| `GENERATOR_COMMIT_FULL_SHA` | `PASS` | fc036d967923f09a6092cb0e5de7409afd07ebd7 |
| `GENERATOR_BYTES_MATCH_COMMIT` | `PASS` | scripts/exp004a_capture.py at fc036d96 is blob 052832c2252a... / sha256 af1ab7cc23980dad... |
| `GENERATOR_WORKTREE_CLEAN` | `PASS` | generator path is clean |
| `TEMPORAL_ORDER` | `PASS` | effective 2026-10-21T16:00:00.000Z precedes the window 2026-10-22T00:00:00.000Z |
| `DECLARATION_COMMITTED_BEFORE_WINDOW` | `PASS` | commit a179ed0d74bf... at 2026-10-21T15:21:23+00:00 precedes the window |
| `ENTRIES_UNCHANGED_EXCEPT_COMMIT` | `PASS` | every field except generator_code_commit equals phase 1 |
| `CAPTURE_WINDOW_UNCHANGED` | `PASS` | 2026-10-22T00:00:00Z to 2027-01-20T00:00:00Z |
| `DATASETS_ABSENT_BEFORE_WINDOW` | `PASS` | no declared dataset exists yet |
| `ST6_TAPE_STILL_REFUSED` | `PASS` | st6:tape refused: EXP-004A-ST6-TAPE declares timeframe '4h slot, 3 rounds of 15s', which is not a bar series; a slice rule for it is not defined by the declaration. Refusing rather than inventing one (this is the st6:tape case). |
| `OVERWRITE_REFUSED` | `PASS` | write_slice refuses an existing target |
| `WRITE_PERMISSION` | `PASS` | data\exp004a writable |
| `NO_LIVE_ORDER_PATH` | `PASS` | no network client, credential or venue client in the extractor |

> PASS here means these controls held on this checkout at this instant. It is not an authorisation, a 90-day validation or a promotion.
