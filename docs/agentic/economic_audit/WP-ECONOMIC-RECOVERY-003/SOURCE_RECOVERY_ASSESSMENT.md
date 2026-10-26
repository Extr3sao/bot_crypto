# WP-ECONOMIC-RECOVERY-003 — Evaluación de recuperabilidad de la fuente

> Responde a las tareas 2 y 3 del WP: de dónde salieron los seis
> `MULTI_FAMILY_RESULTS_*.json`, y si cada entrada se puede reconstruir con datos,
> parámetros, versión y hashes verificables.
>
> Toda afirmación lleva el comando que la produce. Los comandos se ejecutaron en
> `repro/economic-recovery-002` @ `2bd6e346` el 2026-10-25.

---

## 1. De dónde salieron: lo que el repositorio conserva

### 1.1 El productor existe y está versionado

`scripts/multi_family_backtest.py` (319 líneas) escribe un único fichero:

```python
with open(os.path.join(OUTDIR, f"MULTI_FAMILY_RESULTS{fam_sfx}{tf_sfx}.json"), "w", ...)
```

con `OUTDIR = scripts/../reports/strategy-baseline` y `DATA = OUTDIR/data`. Llegó a
git en el commit que publicó los resultados agregados:

```
$ git show --stat --oneline 3271a975
 docs/STRATEGY_ADMISSION_MATRIX.json | 615 ++++++++++++++++++++++++++++++++++++
 docs/STRATEGY_ADMISSION_MATRIX.md   |  47 +++
 docs/STRATEGY_RUNTIME_INVENTORY.md  |  73 ++---
 scripts/build_admission_matrix.py   | 118 ++++++++
 scripts/multi_family_backtest.py    | 246 ++++++++++++
```

Es decir: el mismo commit que publica la **matriz** (el artefacto derivado) publica
también el productor. Los seis ficheros que el productor escribe **no están en ese
commit**, ni en ningún otro.

### 1.2 Los seis ficheros y su rastro en git

```
$ git log --oneline --all -- 'reports/strategy-baseline/MULTI_FAMILY_RESULTS_*.json'
(ninguna salida)
$ git log --oneline --all -- 'reports/strategy-baseline'
(ninguna salida)
$ git check-ignore -v reports/strategy-baseline/MULTI_FAMILY_RESULTS_momentum.json
.gitignore:55:reports/*   reports/strategy-baseline/MULTI_FAMILY_RESULTS_momentum.json
$ ls -d reports/strategy-baseline
ls: cannot access 'reports/strategy-baseline': No such file or directory
```

Los seis nombres se derivan del bucle de `scripts/build_admission_matrix.py`:

| fichero esperado | familia |
| --- | --- |
| `MULTI_FAMILY_RESULTS_momentum.json` | momentum |
| `MULTI_FAMILY_RESULTS_breakout.json` | breakout |
| `MULTI_FAMILY_RESULTS_trend.json` | trend |
| `MULTI_FAMILY_RESULTS_mean_reversion.json` | mean_reversion |
| `MULTI_FAMILY_RESULTS_volatility.json` | volatility |
| `MULTI_FAMILY_RESULTS_ema_crossover.json` | ema_crossover |

**0/6 presentes en el árbol, 0/6 presentes en el historial completo.** `.gitignore:55`
los excluye por diseño (`reports/*`, con `!reports/.gitkeep`).

### 1.3 Qué sobrevivió de ellos

| superviviente | qué conserva | qué no |
| --- | --- | --- |
| [`docs/STRATEGY_ADMISSION_MATRIX.json`](../../../../docs/STRATEGY_ADMISSION_MATRIX.json) (`3271a975`) | totals base y 2X, splits DEV/OOS, checks y veredicto de las 6 familias | ni un digest, ni el commit, ni la fecha de la corrida (la cadena `sha256` **no aparece** en el documento) |
| [`docs/EMA_CROSSOVER_PERFORMANCE_BASELINE.json`](../../../../docs/EMA_CROSSOVER_PERFORMANCE_BASELINE.json) (`21f78880`) | el baseline de `ema_crossover`, versionado: `per_window_asset`, `totals`, `splits` | tampoco digests ni commit |
| `docs/STRATEGY_ADMISSION_MATRIX.md`, `docs/MULTI_STRATEGY_FINAL_REPORT.md` | narrativa y tabla de veredictos | los números crudos |

Consecuencia: de las seis filas de la matriz, **una** (ema_crossover) tiene su entrada
versionada; las otras cinco sólo existen como agregado dentro de la matriz.

---

## 2. Qué hace falta para reconstruir, y qué hay de cada cosa

El productor es determinista dada su entrada, pero su entrada no está:

| requisito | estado | evidencia |
| --- | --- | --- |
| corpus de barras `reports/strategy-baseline/data/*.json` | **ausente**, `data/raw/` vacío (0 ficheros) | `ls data/raw \| wc -l` → 0; `git check-ignore` sobre `reports/*` |
| digest del corpus | **no registrado en ningún sitio** | no hay manifiesto ni campo `sha256` en ninguno de los dos JSON supervivientes |
| parámetros del modelo | **parcialmente en el código**: `WINDOW = 100`, `START_EVAL = 60`, escenarios `BASE/2X_COST/STRESSED_SLIPPAGE/ZERO_COST` | `scripts/multi_family_backtest.py:51-52`, `:264-266` |
| configuración de la corrida | **sólo como variables de entorno no registradas**: `DATASET_TF` (por defecto `5m`), `FAM`, `DUMP_TRADES` | `main()` lee `os.environ`; nada las escribe en la salida |
| versión del productor | **ambigua**: el fichero cambió después del commit que publicó los resultados (`9578ef69` lint, `026ea574` formatter, `0289bcb7`, `5b4051ee`, `31dd2614`) | `git log --oneline --all -- scripts/multi_family_backtest.py` |
| entorno (Python, numpy…) | **no registrado** | `pyproject.toml` fija el rango del proyecto, no el de la corrida |
| lista de símbolos y ventanas | **derivada de los nombres de fichero** (`<SYMBOL>_<WINDOW>.json`), no registrada | `sym, window = base.split("_", 1)` |

---

## 3. Veredicto por entrada

| entrada | ¿reconstruible **exactamente**? | fundamento | qué haría falta |
| --- | --- | --- | --- |
| `MULTI_FAMILY_RESULTS_momentum.json` | **NO** | sin corpus, sin digest, sin revisión del productor ni entorno registrados; no hay copia en el historial (`git log --all` vacío) | corpus congelado + digests + revisión exacta + entorno, o el propio fichero |
| `…_breakout.json` | **NO** | idem | idem |
| `…_trend.json` | **NO** | idem | idem |
| `…_mean_reversion.json` | **NO** | idem | idem |
| `…_volatility.json` | **NO** | idem | idem |
| `…_ema_crossover.json` | **NO** como fichero; **SÍ** su contenido como baseline versionado | `docs/EMA_CROSSOVER_PERFORMANCE_BASELINE.json` está en git (`21f78880`) y contiene totals/splits equivalentes | nada: la fila `ema_crossover` de la matriz se puede recomputar desde un fichero versionado |

Las cinco filas restantes de la matriz **no** se pueden re-derivar. Eso no las invalida:
la matriz está versionada y firmada por su propio commit, y es el ancla que WP-002
declaró autoritativa. Lo que no se puede hacer es *regenerarlas* y llamarlo
reconstrucción.

### Lo que sí sería una reconstrucción, y por qué no está en este WP

Re-capturar klines y re-ejecutar `multi_family_backtest.py` produce **números nuevos**.
Llamarlos reconstrucción sería el error que este WP evita: un backtest re-ejecutado sobre
datos re-descargados no es el mismo experimento, aunque el código sea el mismo. Para
sustituir la matriz haría falta un WP de re-ejecución con pre-registro nuevo, y ambos
resultados tendrían que convivir (el publicado y el nuevo), no reemplazarse.

---

## 4. Las 19 dependencias ausentes: clasificación y fundamento

Inventario de origen: [`DECLARED_DEPENDENCIES.json`](../WP-ECONOMIC-RECOVERY-002/DECLARED_DEPENDENCIES.json)
(WP-002). La clasificación se recalcula en cada corrida de
`scripts/wp_eco003_audit.py`; los productores se validan contra la línea exacta que
escribe el fichero, no contra una heurística de nombre.

| # | ruta | clase | fundamento |
| - | ---- | ----- | ---------- |
| 1 | `reports/strategy-baseline/COST_BARRIER.json` | **RECOVERABLE_EXACT** | copia byte-idéntica en `data/recovery/wp7/evidence/COST_BARRIER.json` (`2437f446…`), que es exactamente el pin del explorer; `--materialize` la restaura sin transformar |
| 2 | `data/raw/alpha003/price/BTCUSDT_5m.json` | **RECOVERABLE_BY_RERUN** | klines de exchange: se pueden volver a descargar, pero no byte a byte; una re-descarga es un dataset nuevo |
| 3 | `data/raw/alpha003/price/BTCUSDT_15m.json` | **RECOVERABLE_BY_RERUN** | idem |
| 4 | `data/st6/ST6_HEALTH_STATUS.json` | **HOST_ONLY** | residuo de runtime de esta máquina; no pertenece a la cadena económica |
| 5 | `reports/rfc035/search_round_3/BASELINE.json` | **RECOVERABLE_BY_RERUN** | escrito por `scripts/rfc035s3_closure.py:1780` (committed) |
| 6 | `reports/rfc035/search_round_3/RULE_CONTRACT_AUDIT.json` | **RECOVERABLE_BY_RERUN** | `scripts/rfc035s3_closure.py:1784` |
| 7 | `reports/rfc035/search_round_3/CANDIDATE_DEEP_DIVE.json` | **RECOVERABLE_BY_RERUN** | `scripts/rfc035s3_closure.py:1787` |
| 8 | `reports/rfc035/search_round_3/ECONOMIC_EVIDENCE.json` | **RECOVERABLE_BY_RERUN** | `scripts/rfc035s3_closure.py:1791` |
| 9 | `reports/rfc035/search_round_3/REJECTION_LOG.json` | **RECOVERABLE_BY_RERUN** | `scripts/rfc035s3_closure.py:1797` |
| 10 | `reports/rfc035/search_round_3/FINAL_REPORT.json` | **RECOVERABLE_BY_RERUN** | `scripts/rfc035s3_closure.py:1806` |
| 11 | `reports/rfc035/search_round_3/INDEPENDENT_VERIFICATION.json` | **RECOVERABLE_BY_RERUN** | `scripts/rfc035s3_verify.py:675` |
| 12 | `reports/profitability_gate035/ECONOMIC_FEASIBILITY.md` | **RECOVERABLE_BY_RERUN** | `scripts/pgate035_closure.py:1544` |
| 13 | `reports/profitability_gate035/ALTERNATIVE_PATHS.md` | **RECOVERABLE_BY_RERUN** | `scripts/pgate035_closure.py:1546` |
| 14 | `reports/profitability_gate035/SEARCH_POSTMORTEM.md` | **RECOVERABLE_BY_RERUN** | `scripts/pgate035_closure.py:1543` |
| 15 | `reports/profitability_gate035/FINAL_REPORT.md` | **RECOVERABLE_BY_RERUN** | `scripts/pgate035_closure.py:1550` |
| 16 | `reports/profitability_gate035/INDEPENDENT_VERIFICATION.json` | **RECOVERABLE_BY_RERUN** | `scripts/pgate035_verify.py:690` |
| 17 | `reports/profitability_gate035/INDEPENDENT_VERIFICATION.md` | **RECOVERABLE_BY_RERUN** | `scripts/pgate035_verify.py:738` |
| 18 | `reports/rfc046/IMPACT_ASSESSMENT.md` | **RECOVERABLE_BY_RERUN** | `scripts/rfc046_audit.py:732` escribe `IMPACT` = `(OUT / "IMPACT_ASSESSMENT.md")` |
| 19 | `docs/research/work_packages/WP-HTF-PIT-001_htf_availability_unit_fix.md` | **NEVER_COMMITTED_DELIVERABLE** | ningún script lo escribe; sólo se lo **cita** (`scripts/rfc046_audit.py:625`, `:764`). No hay nada que re-ejecutar |

Resumen: **16 recuperables por re-ejecución, 1 recuperable de forma exacta, 1 sólo de
host, 1 irrecuperable**. Ninguna es bloqueante para la recertificación del cost-barrier.

> **Corrección a WP-002, medida.** WP-002 contó **dos** "entregables que nunca se
> commitearon". Hoy sólo uno lo es: `reports/rfc046/IMPACT_ASSESSMENT.md` **sí** tiene
> productor versionado (`scripts/rfc046_audit.py:732`, constante `IMPACT`). La
> clasificación anterior venía de mirar quién *nombra* el fichero, no quién lo
> *escribe*; con el nombre solo, `FINAL_REPORT.json` "pertenece" a cuatro árboles de
> informe distintos. La tabla `PRODUCER_WRITES` del script de auditoría fija la ruta
> exacta y re-valida la línea en cada corrida.

### Las dos dependencias que WP-002 llamó "entregables no commiteados"

| ruta | veredicto WP-003 | por qué cambia |
| --- | --- | --- |
| `reports/rfc046/IMPACT_ASSESSMENT.md` | recuperable por re-ejecución | tiene productor; `reports/*` está gitignoreado, que es la única razón de su ausencia |
| `docs/research/work_packages/WP-HTF-PIT-001_htf_availability_unit_fix.md` | **nunca commiteado, irrecuperable** | ningún script lo escribe; es un documento de revisión que se perdió. Su ausencia no bloquea nada: sólo lo cita un informe ya publicado |

---

## 5. Lo que este WP **no** hace

- No descarga datos ni re-ejecuta ningún backtest: sería un experimento nuevo, no una
  reconstrucción, y el WP lo prohíbe explícitamente.
- No rellena huecos con valores plausibles. Donde falta un digest se escribe `—`.
- No toca `reports/`, `data/`, `config/` ni `src/`.
