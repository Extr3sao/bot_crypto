# FINAL_REPORT — WP-ECONOMIC-RECOVERY-005

| Campo | Estado |
| --- | --- |
| PHASE | WP-ECONOMIC-RECOVERY-005 |
| HEAD observado | `a6290714f8685dc3b91fdbc7ed4a66c305dba848` (rama `repro/economic-recovery-002`) |
| COMMITS | Ninguno — los artefactos de este WP quedan **sin commitear** |
| IMPLEMENTED | `scripts/wp005_preflight.py` (preflight de solo lectura, fail-closed) y su test |
| TESTS | 20/20 nuevos en verde; suite de `tests/unit/research`: 69 fallos + 14 errores **preexistentes, mismo conjunto de nodeids**, 0 introducidos |
| RUNTIME_VALIDATION | `NOT_EXECUTED` — no existe ningún dataset en el árbol |
| PAPER_VALIDATION | `NOT_AUTHORIZED` |
| FALSE_SUCCESS | 0 producidos por este WP; la clase de artefacto que sí produce falsos positivos está reproducida y ahora se bloquea |
| DEFECTS | D1–D4 **reproducidos**; D5–D6 leídos; D7 ausente; D8 no evaluado — ver diagnóstico |
| BLOCKERS | `NO_DATASETS_IN_CANONICAL_INPUT_PATH`, `NO_MULTI_FAMILY_RESULTS` |
| EVIDENCE | `evidence/` — observación del preflight, una transcripción por control |
| ARCHITECTURE_STATUS | Sin modificaciones |
| RFC_STATUS | Sin modificaciones |

## 1. Por qué este WP no puede ser un sí ni un no económico

La pregunta de WP-005 es si las seis familias tienen ventaja neta demostrada. En este
HEAD esa pregunta **no es contestable**: `reports/strategy-baseline/data/` no existe y no
hay ningún `MULTI_FAMILY_RESULTS*.json` en el árbol. No hay medición que interpretar.

El preflight lo dice en su propia salida y con su propio código de salida:

```
BLOCKED | HEAD=a6290714f8685dc3b91fdbc7ed4a66c305dba848 | datasets=0 | results=0 | blockers=2
EXIT=2
```

Categorías de las seis familias: **`INCONCLUSIVE`** en las seis, ninguna
`VALIDATION_CANDIDATE`, ninguna rechazada. `PAPER = NOT_AUTHORIZED` sin cambios, y
`admitted_for_paper = 0/24` en el ledger sin tocar.

## 2. Lo que sí se ha establecido

Cuatro defectos del entrypoint histórico estaban descritos en el diagnóstico anterior
como sospechas sobre otra revisión remota. En vez de trasladarlos como están, se han
**reproducido sobre este HEAD**, con datos sintéticos y sin escribir en el repositorio:

| # | Hecho observado | Clase |
| --- | --- | --- |
| D1 | Con el directorio de datos vacío el entrypoint **escribe un `MULTI_FAMILY_RESULTS.json` de 62 791 bytes** con seis familias × cuatro escenarios, todas a cero operaciones, y **sale con 0** | REPRODUCIDO |
| D2 | Una familia que lanza dentro de `_compute_indicators` pasa de 6 operaciones a **0, sin traceback y sin ninguna clave de error**, indistinguible de «no hay señal» | REPRODUCIDO |
| D3 | El campo `gross` incluye slippage: `gross` BASE − `gross` ZERO_COST = 0,40 USD (`ema_crossover`) y 0,35 USD (`momentum`) | REPRODUCIDO |
| D4 | Renombrar el mismo dataset fuera de `W1..W7` deja `totals` idéntico y **vacía DEV/VAL/OOS** sin aviso | REPRODUCIDO |

Por eso el preflight de este WP no confía en la existencia del fichero: un artefacto con
las seis familias a cero operaciones se registra como bloqueo (`ZERO_TRADE_RESULT`), no
como resultado. El control lo demuestra sobre el artefacto real que produjo el
entrypoint: `zero_trade_families` devuelve las seis, mientras que una comprobación
ingenua de contenido (`bool(payload)`) lo habría aceptado — el fichero de ceros **no**
está vacío, pesa 62 KB.

También se ha corregido un supuesto del preflight anterior: exigía seis ficheros
`MULTI_FAMILY_RESULTS_*.json`, pero una ejecución completa del entrypoint escribe **un
solo** agregado con las seis familias. Un preflight que exigiera seis ficheros habría
marcado como bloqueada una matriz completa y correcta. Ahora se aceptan ambas formas y
se exige cobertura real de las seis familias, no un recuento de ficheros.

## 3. Lo que sigue sin establecerse

- **D5 (fill a cierre de la barra de señal)** y **D6 (equity solo realizada)**: leídos en
  código, no reproducidos. D5 puede ser la semántica correcta del runtime de paper; no se
  declara defecto hasta contrastarlo con el adaptador. D6 sí implica que `max_dd_pct` y
  `sharpe_proxy` son cotas inferiores del riesgo.
- **D8 (proveniencia, cobertura, PIT, huecos, duplicados)**: no evaluable sin datos.
- **Atribución de los 69 fallos + 14 errores de `tests/unit/research`**: el conjunto de
  nodeids es **idéntico** al registrado por WP-004 en el mismo árbol (comparado, no
  supuesto). No se ha introducido ninguno y ninguno se ha reclasificado como irrelevante.

## 4. Pregunta de cierre

**¿Existe ventaja neta suficientemente demostrada para continuar validación?**

**No evaluada — no hay datos.** Distinto de «no demostrada»: aquí no hay ni una
operación que contar. El único snapshot económico histórico conocido (11/10/2026, 0/24
combinaciones net-positivas) describe otro árbol y otras condiciones, y no puede
extenderse a este HEAD ni en un sentido ni en el otro.

## 5. Qué tiene que pasar antes de repetir WP-005

1. Reparar D1–D4 en el entrypoint y cubrirlos con test (un artefacto solo se escribe si
   hubo datos; los fallos por familia se cuentan y se nombran; PnL desglosado bruto /
   slippage / comisiones / neto; split declarado, no inferido del nombre del fichero).
2. Incorporar datasets con proveniencia demostrable a la ruta canónica, con fingerprints.
3. Verificar PIT y paridad temporal contra el adaptador de paper (D5), y publicar equity
   MTM (D6).
4. Una familia con resultado real, contabilidad independiente, y solo entonces la matriz
   completa con sensibilidades y OOS.
5. Verificador independiente. Solo entonces hay clasificación económica que emitir.

Los gates, el ledger y `admitted_for_paper` no se tocan en ningún paso.

## 6. Estado de entrega

Los artefactos de este WP están en el árbol de trabajo y **sin commitear**: no se ha
hecho `git add` ni commit, y el HEAD sigue siendo el tip de WP-004. La observación del
preflight se tomó con estos ficheros aún sin rastrear, y así consta en el `git status`
que ella misma publica.
