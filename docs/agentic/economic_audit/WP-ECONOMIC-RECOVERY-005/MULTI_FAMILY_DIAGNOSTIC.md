# MULTI_FAMILY_DIAGNOSTIC — WP-005

**Estado:** `BLOCKED`. **No** es un veredicto `ECONOMICALLY_UNVIABLE` sobre el HEAD
post-WP-004, y no puede leerse como tal: en `a6290714` no hay ni un dataset sobre el
que ejecutar.

| Campo | Valor observado |
| --- | --- |
| HEAD | `a6290714f8685dc3b91fdbc7ed4a66c305dba848` |
| Rama | `repro/economic-recovery-002` |
| Datasets en `reports/strategy-baseline/data/` | **0** (el directorio no existe) |
| Artefactos `MULTI_FAMILY_RESULTS*.json` | **0** en todo el árbol |
| Módulos de familia | 6/6 presentes |
| Ledger de admisión | 24 estrategias, `admitted_for_paper = 0`, `_schema_version = strategy-admission-ledger-v1` |
| Preflight | `BLOCKED`, 2 bloqueos, exit **2** |

Fuente: [WP005_PREFLIGHT_OBSERVATION.json](evidence/WP005_PREFLIGHT_OBSERVATION.json).

## 1. Clases de evidencia

Cada afirmación de este documento lleva su clase. La distinción no es retórica: una
lectura de código no es una reproducción, y WP-003 demostró en este mismo lane lo que
cuesta tratar una como la otra.

- **REPRODUCIDO** — ejecutado aquí, transcripción en `evidence/`.
- **LEÍDO** — leído en el código de `a6290714`; no se ha provocado el efecto.
- **AUSENTE** — el artefacto no existe en el árbol.
- **NO_EVALUADO** — no hay material para evaluarlo.

## 2. Defectos

### D1 — El entrypoint escribe un artefacto de éxito cuando no hay ningún dataset (REPRODUCIDO)

`scripts/multi_family_backtest.py` construye `files` con `glob` y, si el resultado es
vacío, recorre igualmente las seis familias y escribe
`reports/strategy-baseline/MULTI_FAMILY_RESULTS.json`. Con el directorio de datos vacío:

```
ARTIFACT_WRITTEN: reports/strategy-baseline/MULTI_FAMILY_RESULTS.json
BYTES: 62791
FAMILIES: ['breakout', 'ema_crossover', 'mean_reversion', 'momentum', 'trend', 'volatility']
TRADES_BY_FAMILY: {todas: 0}
DATASETS_IN_INPUT_DIR: 0
EXIT=0
```

Seis familias, cuatro escenarios, 24 combinaciones, **cero operaciones**, salida `0`. Es
un fichero de resultados con la misma forma que uno real y sin nada dentro:
la existencia de resultados no demuestra ejecución. Transcripción:
[control_empty_dataset.txt](evidence/control_empty_dataset.txt).

### D2 — Una excepción de indicadores es indistinguible de «sin señal» (REPRODUCIDO)

`except Exception: alphas = []` convierte cualquier fallo de `_compute_indicators` o de
`generate` en ausencia de señal, sin categoría ni traceback. Sustituyendo una familia
por una que lanza dentro de `_compute_indicators`, con los mismos datos:

| familia | operaciones | net | traceback | clave `error` |
| --- | --- | --- | --- | --- |
| `momentum` sana | 6 | −14,85 | — | — |
| `momentum` que lanza | **0** | **0,00** | **NO** | **NO** |

Las demás familias no se ven afectadas y el proceso termina con éxito. El resultado de
una rotura es byte-equivalente en forma al de una estrategia sin señales: no se puede
distinguir «no hay edge» de «el indicador está roto». Transcripción:
[control_family_exception_masking.txt](evidence/control_family_exception_masking.txt).

### D3 — El campo llamado `gross` ya contiene slippage (REPRODUCIDO)

La entrada y la salida se ejecutan con slippage (`fill = cl * (1 ± slip)`) y `gross` se
calcula sobre esos precios; `fees` recoge solo comisiones. Con los mismos datos y la
misma familia, `BASE` frente a `ZERO_COST`:

| familia | gross BASE | gross ZERO_COST | diferencia |
| --- | --- | --- | --- |
| `ema_crossover` | −7,34 | −6,94 | **0,40 = slippage** |
| `momentum` | −11,86 | −11,51 | **0,35 = slippage** |

Por tanto `gross` **no** es PnL bruto: no existe en el artefacto un PnL antes de costes,
ni slippage separado, ni funding. Cualquier comparación «bruto vs neto» mezcla
comisiones con slippage. Transcripción:
[control_synthetic_cost_and_split.txt](evidence/control_synthetic_cost_and_split.txt).

### D4 — El split DEV/VAL/OOS se deduce del nombre del fichero (REPRODUCIDO)

`dev`, `val` y `oos` se separan por prefijo del nombre del dataset (`W1..W4`, `W5..W6`,
`W7`); un dataset fuera de esa convención sigue entrando en `totals` pero en ningún
split, sin aviso. Renombrando el mismo dataset de `BTCUSDT_W1.json` a
`BTCUSDT_AUGSEP.json`:

- `totals` idéntico en las seis familias (p. ej. `ema_crossover` 6 → 6);
- `DEV_W1_W4 = VAL_W5_W6 = OOS_W7 = 0`.

Es decir: un conjunto con datos fuera de la convención produce un artefacto que declara
cero operaciones en validación y en out-of-sample sin haberlas perdido, y nada lo
señala. Misma transcripción que D3.

### D5 — El fill se ejecuta al cierre de la barra que genera la señal (LEÍDO)

La ventana point-in-time es `pit = bars[max(0, i-99) : i+1]`, es decir incluye la barra
`i`, y acto seguido se usa `fill = cl * (1 ± slip)` con el cierre de esa misma barra
`i`. No hay latencia ni barra siguiente. La señal y su ejecución comparten precio.

Esto **no se clasifica como defecto demostrado**: puede ser exactamente la semántica del
runtime de paper. Pero mientras no se contraste con el adaptador real, la paridad
temporal del backtest no está establecida, y una diferencia de una barra es del orden
del edge que se pretende medir. Requiere comparación explícita, no lectura.

### D6 — La curva de equity solo registra PnL realizado (LEÍDO)

`equity_curve.append(eq)` guarda `eq`, que solo cambia al cerrar una posición. No hay
MTM intratrade, así que `max_dd_pct` y `sharpe_proxy` se calculan sobre una equity que
ignora el recorrido adverso dentro de la posición. Son cotas inferiores del riesgo, no
medidas de riesgo. Para admisión se necesita equity MTM, y `avg_mfe_pct`/`avg_mae_pct`
(que sí existen) no la sustituyen.

### D7 — No hay datos (AUSENTE)

`reports/strategy-baseline/data/` no existe y no hay ningún `MULTI_FAMILY_RESULTS*.json`
rastreado ni sin rastrear. La conclusión honesta es que **la matriz de seis familias no
se ha ejecutado nunca en este HEAD**, no que haya salido mal.

### D8 — Proveniencia, cobertura y PIT del dato (NO_EVALUADO)

Sin datasets no se puede comprobar fuente, huecos, duplicados, granularidad, cobertura,
PIT ni fingerprints. El preflight valida forma OHLCV (ascendente, finita, coherente) y
declara explícitamente que eso no establece ninguna de esas propiedades.

## 3. Lo que este diagnóstico no concluye

- No concluye que las seis familias sean económicamente inviables. No hay medición.
- No concluye que el pipeline económico esté roto. D1–D4 son defectos del **entrypoint**
  y están reproducidos; ninguno requiere datos reales para arreglarse y ninguno autoriza
  ni impide nada por sí mismo.
- No atribuye ninguno de los fallos preexistentes de la suite a este pipeline: sin
  nodeids por familia no hay atribución.

## 4. Secuencia exigida antes de cualquier clasificación económica

1. Reparar y cubrir con test D1–D4 en el entrypoint: un artefacto solo se escribe si hubo
   al menos un dataset y cada familia informa cuántos fallos tuvo; el PnL se publica
   desglosado (bruto, slippage, comisiones, neto); el split se declara, no se adivina por
   nombre; una excepción se cuenta y se nombra.
2. Incorporar datasets con proveniencia demostrable a la ruta canónica, con fingerprints.
3. Verificar PIT y paridad temporal contra el adaptador de paper (D5) y equity MTM (D6).
4. Ejecutar una sola familia con resultado real, contrastar con una contabilidad
   independiente, y solo entonces ampliar a la matriz completa.
5. Sensibilidades y OOS con el split declarado, no inferido.
6. Verificador independiente, y solo entonces clasificar.

Los gates y `admitted_for_paper` no se tocan en ningún paso: `PAPER` sigue
`NOT_AUTHORIZED`.
