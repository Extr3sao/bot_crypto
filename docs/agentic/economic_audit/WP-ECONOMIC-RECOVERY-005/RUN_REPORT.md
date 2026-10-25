# RUN_REPORT — WP-ECONOMIC-RECOVERY-005

Todas las cifras de este informe provienen de las transcripciones de `evidence/`. Nada
se ha ejecutado sobre datos de mercado: el árbol no contiene ninguno.

## 1. Entorno

| Campo | Valor |
| --- | --- |
| HEAD | `a6290714f8685dc3b91fdbc7ed4a66c305dba848` |
| Rama | `repro/economic-recovery-002` |
| Intérprete | `.venv/Scripts/python.exe` (3.11.15) |
| Cambios de este WP | `scripts/wp005_preflight.py`, `tests/unit/research/test_wp005_preflight.py`, `docs/agentic/economic_audit/WP-ECONOMIC-RECOVERY-005/` — sin commitear |

## 2. Preflight

```
$ ./.venv/Scripts/python.exe scripts/wp005_preflight.py --repo . --out $OUTSIDE/WP005_OUT
BLOCKED | HEAD=a6290714f8685dc3b91fdbc7ed4a66c305dba848 | datasets=0 | results=0 | blockers=2
EXIT=2
```

Bloqueos: `NO_DATASETS_IN_CANONICAL_INPUT_PATH`, `NO_MULTI_FAMILY_RESULTS`.
La salida se escribe **fuera** del repositorio (`--out` dentro del árbol se rechaza con
exit 2 y sin escribir nada), y las copias de `evidence/` son copias, no el original.

Entradas verificadas en el árbol:

| Ruta | Estado | SHA-256 (16) | Nota |
| --- | --- | --- | --- |
| `config/strategy_admission.json` | PRESENTE | `5e2ccc5792b8e691` | 24 estrategias, 0 admitidas, `strategy-admission-ledger-v1` |
| `data/recovery/COST_BARRIER_EXPLORER.json` | PRESENTE | `fdc6892f12280f4f` | JSON válido |
| `data/recovery/ACTIVE_ECONOMIC_AUDIT.json` | PRESENTE | `8a101e8875bdf61d` | JSON válido |
| `scripts/multi_family_backtest.py` | PRESENTE | `17904a18db507ba5` | entrypoint observado |
| seis módulos de familia | PRESENTES | ver observación | 6/6 |

## 3. Controles (sintéticos, etiquetados, fuera del repositorio)

| control | fichero | resultado |
| --- | --- | --- |
| C0 dataset vacío | `evidence/control_empty_dataset.txt` | artefacto de 62 791 bytes, 6 familias × 4 escenarios, 0 operaciones, exit 0 |
| C0b detección del artefacto | `evidence/control_zero_trade_detection.txt` | `ZERO_TRADE_FAMILIES` = las seis; `empty: False` (una comprobación ingenua lo aceptaría) |
| C2 coste dentro de `gross` | `evidence/control_synthetic_cost_and_split.txt` | `gross` BASE − `gross` ZERO_COST = 0,40 USD (`ema_crossover`), 0,35 USD (`momentum`) |
| C3 split por nombre de fichero | `evidence/control_synthetic_cost_and_split.txt` | renombrar el dataset: `totals` idéntico, `DEV/VAL/OOS` = 0 |
| C1 excepción oculta | `evidence/control_family_exception_masking.txt` | 6 → 0 operaciones, sin traceback, sin clave `error`, exit 0 |

Los tres scripts de control están junto a sus transcripciones para que cualquiera pueda
repetirlos. Ninguno escribe en el repositorio: repuntan `DATA`/`OUTDIR` a un directorio
temporal antes de invocar `main()`.

Nota de honestidad: la primera versión del control C1 abortó por un **error de índice en
el propio script de control** (`KeyError: 'trades'`), no en el entrypoint. Se corrigió y
se repitió; la transcripción archivada es la del control corregido.

Las transcripciones `.txt` se guardan normalizadas a LF: el host las emitió con CRLF y
normalizarlas es lo que hace que el mismo `evidence/` sea idéntico en cualquier checkout.
El contenido de los comandos no cambia; solo su representación.

Nota de propiedad: `data/st6/ST6_RUNS.jsonl` aparece sin rastrear en el `git status` de la
observación y **no pertenece a este WP**; no se ha tocado.

## 4. Suites

```
$ ./.venv/Scripts/python.exe -m pytest tests/unit/research/test_wp005_preflight.py -q
20 passed in 1.87s
EXIT=0

$ ./.venv/Scripts/python.exe -m pytest tests/unit/research -q
69 failed, 1795 passed, 30 skipped, 14 errors in 325.63s
EXIT=1
```

Los 69 nodeids en fallo son **el mismo conjunto** que registró WP-004 para
`tests/unit/research` (comparado con `diff`, no supuesto); los otros 2 fallos del informe
de WP-004 estaban en `tests/unit/risk`, fuera de esta selección. Ningún fallo menciona
`wp005`. Transcripción: `evidence/lane_suite_after.txt`.

Los 20 tests nuevos cubren, entre otras cosas: un agregado con cero operaciones es
bloqueo; un único agregado de ejecución completa satisface cobertura (y seis ficheros por
familia también); una familia ausente bloquea; un dataset con timestamps duplicados,
descendentes o OHLCV incoherente bloquea; `--out` dentro del repo se rechaza sin escribir;
ningún árbol produce `PASS`; la observación es byte-estable y en LF.

## 5. Lo que este run **no** hizo

- No ejecutó ningún backtest sobre datos reales (no hay).
- No modificó `config/strategy_admission.json`, `data/recovery/*` ni ningún gate.
- No habilitó ni cambió permisos de PAPER.
- No commiteó nada.
