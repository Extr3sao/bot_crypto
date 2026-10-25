# RUN_REPORT — WP-ECONOMIC-RECOVERY-006

## 1. Secuencia ejecutada

| # | comando | exit | artefacto |
| --- | --- | --- | --- |
| 1 | `python scripts/wp005_preflight.py --repo . --out <fuera>` | 2 | preflight `BLOCKED` (línea base) |
| 2 | `python -m pytest tests -q --junitxml=before.xml` | 1 | 71 fallos + 14 errores, 3 314 passed |
| 3 | `python scripts/w006_fetch_klines.py --out data/economic/w006 --days 120` | 0 | 3 datasets + `MANIFEST.json` (72 peticiones) |
| 4 | `python scripts/w006_validate_data.py` | 0 | `DATA_QUALITY.json` — PASS |
| 5 | `python scripts/multi_family_backtest.py --dump-trades --out reports/economic/w006` | 0 | resultados + `TRADES.csv` |
| 6 | `python scripts/w006_verify.py` | 0 | `INDEPENDENT_VERIFICATION.json` — 10/10 PASS |
| 7 | `python -m pytest tests/unit/research/test_w006_engine.py -q` | 0 | 17 passed |
| 8 | `python scripts/w006_classify_failures.py --xml before.xml --baseline ...` | 0 | `FAILURE_CLASSIFICATION.json` |
| 9 | `python -m pytest tests -q --junitxml=after.xml` | 1 | mismos 71 + 14; +20 tests nuevos en verde |

## 2. Datos

| activo | barras | inicio | fin | huecos | bytes | digest |
| --- | --- | --- | --- | --- | --- | --- |
| BTCUSDT | 34 560 | 2026-06-27T17:40Z | 2026-10-25T17:35Z | 0 | 3 381 712 | en `MANIFEST.json` |
| ETHUSDT | 34 560 | 2026-06-27T17:40Z | 2026-10-25T17:35Z | 0 | 3 408 333 | en `MANIFEST.json` |
| SOLUSDT | 34 560 | 2026-06-27T17:40Z | 2026-10-25T17:35Z | 0 | 3 195 688 | en `MANIFEST.json` |

Cada petición registra `url`, `params`, `http_status`, `response_sha256`, `response_bytes`,
`rows` y `requested_at_utc`. Reintentos con backoff en 418/429/5xx; un fallo persistente
aborta en vez de escribir un dataset parcial.

## 3. Cambios en el motor

`scripts/multi_family_backtest.py` reescrito conservando el contrato productivo: se siguen
usando las clases de familia reales y su `_compute_indicators` sobre ventana PIT de 100
barras. Las señales se calculan **una vez** por (familia, activo) porque no dependen de los
costes; cada escenario de costes es una repetición pura de las mismas decisiones (4m33s
para 6 familias × 3 activos × 4 escenarios × 34 560 barras).

Nuevos flags: `--manifest`, `--out`, `--families`, `--symbols`, `--scenarios`,
`--dump-trades`, `--fees-bps`, `--slippage-bps`, `--half-spread-bps`.

## 4. Comportamiento de fallo (comprobado, no declarado)

| situación | comportamiento |
| --- | --- |
| manifiesto ausente | `MULTI_FAMILY_RUN.json` con `status: NO_DATA`; sin resultados; exit 2 |
| digest de dataset distinto del manifiesto | `NO_DATA` con `digest mismatch`; sin resultados; exit 2 |
| dataset con spacing irregular o menos de 160 barras | `NO_DATA`; exit 2 |
| excepción de familia | fallo registrado con traceback; `INCOMPLETE`; sin resultados; exit 3 |
| cobertura parcial entre activos | `coverage_mismatch` publicado en el run record |

## 5. Tests

- `tests/unit/research/test_w006_engine.py`: 18 tests (D1 ×3, D2 ×3, D5 ×2, D3 ×4, D4 ×3, D6 ×2, adaptador legacy ×1).
- Suite completa antes/después: 71 fallos + 14 errores en ambas; pasa de 3 334 a 3 351
  `passed` (+17 = lo que esa corrida recogió del fichero nuevo; el test 18 se añadió
después y pasa en ejecución dirigida).
- Conjunto de nodeids en fallo: **idéntico** (comprobado por el clasificador con
  `--baseline`, campo `comparison.introduced` vacío).

## 6. Clasificación de fallos

Ver [FAILURE_CLASSIFICATION.md](FAILURE_CLASSIFICATION.md). 85 problemas:
41 artefactos no versionados, 18 digests obsoletos, 8 huecos de inventario en dobles de
test, 18 aserciones sin atribuir (publicadas con su línea).

## 7. Verificación independiente

`scripts/w006_verify.py`: 10 checks, 23 444 operaciones, 0 fallos. Detalle en
`evidence/independent_verification_run.txt` e `INDEPENDENT_VERIFICATION.json`.

## 8. Limitaciones

- Un venue y 120 días: los resultados económicos valen para esta muestra.
- Los datos se descargan de un endpoint vivo: una re-ejecución en otra fecha produce otro
  periodo. El manifiesto fija el periodo y los hashes de esta ejecución, y el motor
  rechaza cualquier dataset que no coincida con su manifiesto.
- `data/economic/w006/datasets/*.json` suma ~10 MB en el repositorio: es el coste de tener
  la evidencia económica reproducible sin volver a pedirla.
