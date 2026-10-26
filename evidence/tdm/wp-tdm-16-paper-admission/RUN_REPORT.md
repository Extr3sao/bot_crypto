# WP-TDM-016 — RUN_REPORT

> Secuencia ejecutada, con los comandos reales y su exit code. Ninguna salida se filtra.

## Comandos

| # | Comando | Exit | Qué produjo |
| ---: | --- | ---: | --- |
| 1 | `python scripts/tdm16_admission_audit.py` | 0 | ADMISSION_AUDIT.json/.md (14/14 checks, 24 estrategias) |
| 2 | `python scripts/tdm16_paper_evidence.py` | 0 | PAPER_CYCLE_EVIDENCE.json (3 tests, 10/10 checks) |
| 3 | `python scripts/tdm16_decision.py` | 0 | ECONOMIC_DECISION.json (veredicto y umbral derivados) |
| 4 | `python scripts/tdm16_tests.py` | 0 | TEST_RESULTS.json (547 tests, 0 fallos) |
| 5 | `python scripts/tdm16_verify.py` | 0 | VERIFY.json (checks independientes + mutaciones) |
| 6 | `python scripts/tdm16_report.py` | 0 | RUN_REPORT.md/.json, FINAL_REPORT.md/.json |

## Suites

| Suite | Target | Tests | Fallos | Errores | Exit | Duración |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| `wp016_paper_cycle` | `tests/integration/test_wp016_paper_order_cycle.py` | 3 | 0 | 0 | 0 | 2.85s |
| `paper` | `tests/unit/paper` | 57 | 0 | 0 | 0 | 2.41s |
| `risk` | `tests/unit/risk` | 119 | 0 | 0 | 0 | 11.2s |
| `autonomous` | `tests/unit/autonomous` | 341 | 0 | 0 | 0 | 27.22s |
| `integration` | `tests/integration` | 27 | 0 | 0 | 0 | 4.66s |

Total: **547** tests, **0** fallos, **0** errores.

## Artefactos

- `audit`: `evidence/tdm/wp-tdm-16-paper-admission/ADMISSION_AUDIT.json`
- `cycle`: `evidence/tdm/wp-tdm-16-paper-admission/PAPER_CYCLE_EVIDENCE.json`
- `decision`: `evidence/tdm/wp-tdm-16-paper-admission/ECONOMIC_DECISION.json`
- `next`: `evidence/tdm/wp-tdm-16-paper-admission/NEXT_EXPERIMENT.json`
- `tests`: `evidence/tdm/wp-tdm-16-paper-admission/TEST_RESULTS.json`

## Por qué no hay run de PAPER con datos reales

El ledger de admisión admite 0 de 24 estrategias y la capa `PAPER_ORDER` está `BLOCKED`. Colocar una orden PAPER de todos modos sería forzar una operación a través del control que existe precisamente para impedirlo, así que no se coloca ninguna: el run con datos reales queda para el experimento siguiente, y no se declara rentabilidad de lo que no se ha ejecutado.

