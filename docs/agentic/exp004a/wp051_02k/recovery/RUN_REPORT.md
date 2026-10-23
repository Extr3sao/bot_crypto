# WP-051-02K — auditoría de recuperación

**Generado:** 2026-10-23T19:15:17Z · **Fuente:** `9983b050c8e2` · **Dictamen:** `BLOCKED_WITH_EVIDENCE`

| Comprobación | Estado | Detalle |
| --- | --- | --- |
| SOURCE_COMMIT_CHECKED_OUT | **PASS** | HEAD=9983b050c8e2, source=9983b050c8e2 |
| CONTRACT_DECLARES_ITS_GENERATOR | **PASS** | contract present=True; declared objects present=4/4 |
| CONTRACT_SUPERSEDES_HASH_MATCHES | **PASS** | declared=eb27cedc2626844d, file=match |
| PHASE3_SHARD_MANIFESTS_VERIFY | **PASS** | 24 manifests, 24 pass; rows: rehearsal=864 production=0 |
| PUBLISHED_PREFIX_VERIFIES | **PASS** | 29 of 29 published files match their own snapshot hash |
| PUBLISHED_PREFIX_VERSUS_THE_RECORD | **PASS** | 3 of 11 recorded days survive; 2 match the recorded hash; differing=['2026-10-15.json']; missing=8 days |
| RECORD_BYTES_STILL_MATCH_THEIR_COMMIT | **PASS** | 12 of 12 files identical to 9983b050 |
| GUARD_TASK_POINTS_AT_A_LIVE_SCRIPT | **FAIL** | registered=True; action=C:\Users\GVLLFR0035\Downloads\bot-freebuff-exp004a-02h\scripts\edge04_watchdog.py; exists=False |
| GUARD_IS_OPERABLE | **PASS** | `--help` exit=0 |
| RUNNER_IS_EXECUTABLE | **PASS** | `--check` exit=0 (read-only mode) |
| TESTS_PASS | **PASS** | exit=0 :: ...........................................................              [100%]
59 passed in 0.93s |
| SPACE_WITHIN_THE_FROZEN_BUDGET | **FAIL** | INSUFFICIENT: free=13.3997 GiB, required=14.564 GiB, margin=-1.1643 GiB, instruments agree=True |
| FORWARD_STORE_STILL_EXISTS | **FAIL** | data/forward/edge04 and data/forward/edge03 are absent: the campaign cannot resume from this tree |

## Inventario

| Componente | Clase | Evidencia |
| --- | --- | --- |
| `contract_phase3` | FOUND_VALID | byte-identical to blob 82aec64affaf |
| `contract_phase2` | FOUND_VALID | byte-identical to blob 9421cc52a8a3 |
| `contract_root` | FOUND_VALID | byte-identical to blob d3bf7f003f22 |
| `capture_runner_02f` | FOUND_VALID | byte-identical to blob f5aac1604e37 |
| `capture_runner_02g` | FOUND_VALID | byte-identical to blob 2fec148451ed |
| `capture_verifier_02g` | FOUND_VALID | byte-identical to blob 20503fb2a17d |
| `observer` | FOUND_VALID | byte-identical to blob cab2e11fab91 |
| `observer_watchdog` | FOUND_VALID | byte-identical to blob 4f3460329f1d |
| `closure` | FOUND_VALID | byte-identical to blob 9a89939ee884 |
| `engine` | FOUND_VALID | byte-identical to blob 75d73669df03 |
| `store_module` | FOUND_VALID | byte-identical to blob af7162fbfcd5 |
| `shard_store_phase3` | FOUND_VALID | directory with 50 files, tracked at 9983b050 |
| `published_prefix` | FOUND_VALID | directory with 31 files, tracked at 9983b050 |
| `store_forward_edge04` | ABSENT | not in this checkout and not tracked by the commit |
| `store_forward_edge03` | ABSENT | not in this checkout and not tracked by the commit |

## Prefijo publicado frente al registro 02K

- días registrados por 02K: 11
- días que sobreviven: 3
- coinciden con el hash registrado: 2
- difieren: ['2026-10-15.json']
- perdidos: 8 días

## Espacio

Libre: **13.3997 GiB**; presupuesto congelado 14.564 GiB; margen -1.1643 GiB; instrumentos coinciden.

## Guard

Tarea `\TradingAgentic-EDGE04-Watchdog` registrada: True; script referenciado: `C:\Users\GVLLFR0035\Downloads\bot-freebuff-exp004a-02h\scripts\edge04_watchdog.py`; existe: False.
