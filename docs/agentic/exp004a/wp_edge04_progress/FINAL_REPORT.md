# EXP004A sigue bloqueado; el progreso operativo ya no depende de él

**Dictamen: `EXP004A = BLOCKED_WITH_EVIDENCE` (sin cambios) + `OPERATIONAL_PROGRESS = UNBLOCKED`.**

Lo segundo es lo nuevo y está medido, no argumentado: **existe una lane paper autónoma que no
toca los tres shards perdidos y ha corrido de verdad** — dos ciclos, proveedor falso, cero
órdenes, cero fallos — mientras el corpus que falta sigue faltando y su tarea sigue aparcada.

| # | Objetivo | Resultado |
|---|---|---|
| 1 | Matriz de dependencias y reachability | **hecho** — 470 entrypoints; **29 bloqueados**, 441 alcanzables |
| 2 | EXP004A bloqueado, sin sustituir ni relajar | **cumplido** — pins 3/3 intactos, Forward `Enabled=false`, `data/raw/alpha003` no existe |
| 3 | Camino paper legítimo sin los shards | **existe y está validado** — 395 tests + ejecución real de 2 ciclos |
| 4 | Congelación mínima: manifiesto, velas cerradas, copia redundante, restauración real | **implementada y ejercitada** — `corpus_digest e813921a…`, espejo verificado, 24 archivos borrados y restaurados |
| 5 | Tests, integración, runtime, verificación independiente | **10/10 freeze · 395/395 paper+autonomous · 11/11 verificador** |
| 6 | Entregables | este informe, `RUN_REPORT.md/.json`, `EVIDENCE.json`, `VERIFIER.json` |

---

## 1. La matriz: quién necesita los shards y quién no

`scripts/wp_edge04_deps.py` no busca la cadena «15m»: construye el cierre de imports de cada
entrypoint (incluidos los **relativos**, que es donde se escondía `edge03.run`), y solo llama
*bloqueado* a lo que necesita un directorio ausente sin ninguna guarda.

| Grupo | Cuántos | Qué son |
|---|---|---|
| **BLOQUEADOS** | **29** | toda la familia EDGE-01/03/04/05/06/07/08/12 que lee el corpus congelado; incluye `edge03_run.py` y **`edge04_observer.py`, la lane programada** |
| **DEGRADAN** | 17 | corren, pero una entrada se declara `available: false` — `st6_forward_regime.py` es el caso claro |
| **ALCANZABLES sin el directorio** | **441** | el runtime paper, los verificadores, los productores de corpus |

Los lectores del directorio ausente son seis módulos, y sólo uno lo abre de verdad por barra:
`edge01.data` (proveedor), `edge01.campaign`, `edge03.forward_plan`, `edge03.run`,
`edge03.shadow`, `edge03.autonomous`. Los de `edge08` lo mencionan para declararse disjuntos y
**comprueban `is_dir()` antes de leer** — la matriz los cuenta aparte precisamente para no
inflar la cifra de bloqueados.

**Límite que se declara**: la matriz es estática. Un entrypoint que delegue por subprocess, o
que importe dentro de una función que nunca se llama, puede colarse como alcanzable. Por eso
las afirmaciones operativas de este informe **no salen de la matriz**, sino de las dos
ejecuciones de la §3 y de la §4.

## 2. EXP004A: nada se ha movido

- Los tres pins de 15m siguen sin poder satisfacerse: `data/raw/alpha003/price/` **no existe**.
- Los tres pins de 1h **siguen dando exactamente lo mismo** después de escribir el manifiesto
  de congelación en su directorio: `f4d16c36…`, `365046d4…`, `847d8eb4…` — recomputados por el
  verificador desde los bytes, no leídos de un informe.
- `TradingAgentic-EDGE04-Forward`: `Enabled=false`, acción intacta.
- No se ha tocado ningún umbral, ninguna lista de costes, ningún verificador del experimento.

## 3. El camino paper que sí existe, y su prueba

`scripts/autonomous_paper.py` declara en su propio `--help` que «no hay ruta de código que
pueda llegar a LIVE». No importa el corpus congelado: el cierre de imports no toca
`alpha003`. Se validó en dos capas:

| Capa | Comando | Resultado |
|---|---|---|
| Integración offline | `pytest tests/unit/paper tests/unit/autonomous` | **395 passed**, exit 0 |
| Runtime real | `autonomous_paper.py --provider fake --cycles 2 --assets BTC` | **exit 0** — `mode=paper`, `environment=fake:binance`, 2 ciclos, **`orders_created=0`**, `runtime_failures=0`, 2 trazas, 2 latidos, `RUN_REPORT` y `PAPER_DAILY_REPORT` escritos |

`run_id WP-EDGE04-PAPER-20261024T115217Z`, commit `c02edc0a` en el propio informe del run: la
ejecución queda atada al árbol que la produjo. **No hubo operación real, ni credenciales, ni
órdenes** — el proveedor es falso y no hay red.

Esto **no desbloquea EXP004A**: su forward sigue cerrado porque su pin exige unos bytes que ya
no existen. Lo que desbloquea es el *progreso operativo*: hay una lane que se puede ejecutar y
medir mientras el corpus no llegue.

## 4. Congelación: manifiesto, velas cerradas, espejo y restauración real

`src/trading_bot/research/prospective/freeze.py` (+ CLI `scripts/wp_edge04_freeze.py`). Reutiliza
la vocabulario de manifiesto que el árbol ya publica (`_FETCH_MANIFEST.json`: `source`,
`interval`, `normalization`, totales, `corpus_digest`) y el primitivo de hash de
`edge01.data.os_sha256`. Añade lo que faltaba, que es justo lo que costó el corpus:

| Regla | Qué impide |
|---|---|
| `UNCLOSED_BAR` | congelar un shard cuya última barra aún no ha cerrado — el fallo exacto de EXP004A |
| `BAD_GRID` | timestamps no crecientes o fuera de rejilla |
| `EMPTY_SHARD` / `MISSING_SHARD` | shards vacíos o ausentes de la lista esperada |
| `corpus_digest` sobre `nombre+sha256+bytes` | renombrar, truncar o añadir un shard sin que el digest se mueva |
| `verify()` que devuelve diferencias, no un booleano | «ha cambiado algo» sin decir qué, que no es evidencia |

Aplicado al corpus 1h restaurado (el único completo que queda):

```
23 shards · 174.094 barras · 19.380.640 bytes · corpus_digest e813921a0c91d682…
última barra cerrada: 1772323200000 (2026-03-01T00:00Z)  → ninguna abierta
```

**Espejo independiente del árbol**: `C:\Users\GVLLFR0035\exp004a-corpus-mirror\alpha-expansion-v1-data`,
23/23 shards idénticos, verificado por hash contra el manifiesto.

**Prueba de restauración real** (`drill`): copia a un root desechable, **borra los 24 archivos**
(shards + manifiesto), `verify` acusa `MISSING` en los 23, se restaura desde el espejo y vuelve
el mismo `corpus_digest`. Además un lector real (`edge01.data.load_1h`) lee la copia restaurada
y devuelve el mismo `sha256` que antes del borrado — `f4d16c36…`, que es el pin de 1h de
EDGE-03. La restauración no es una hipótesis: se ejecutó y se comparó.

*Limitación honesta*: el espejo está en el mismo volumen físico. Protege del borrado, de un
árbol corrupto y de un `clean` accidental; **no** protege de la pérdida del disco. La copia
fuera del host sigue siendo la acción pendiente que este WP no puede ejecutar.

## 5. Qué se ejecutó de verdad

| Ejecución | Resultado |
|---|---|
| `pytest tests/unit/research/test_prospective_freeze.py` | **10 passed** |
| `pytest tests/unit/paper tests/unit/autonomous` | **395 passed** |
| `wp_edge04_freeze.py freeze / verify / mirror / drill` | 4/4 exit 0 |
| `wp_edge04_deps.py` | 470 entrypoints clasificados |
| `autonomous_paper.py --provider fake --cycles 2` | exit 0, `orders_created=0` |
| `wp_edge04_verify.py` (builder ≠ verifier) | **11/11**, `EVIDENCE_CONSISTENT_WITH_BLOCKED` |

Ningún PASS de este informe viene de un test que se haya suavizado: los 395 tests son los del
árbol, y el verificador recomputa hashes y pins por su cuenta.

## 6. Qué sigue bloqueado

1. **EXP004A completo**: corpus 15m irrepetible (informe previo `wp_edge04_15m/`), Forward
   aparcada, `edge03_verify` sin poder completarse.
2. **29 entrypoints** que leen ese directorio, incluida la lane programada.
3. **Copia fuera del host**: el espejo actual muere con el disco.

## 7. Cambio mínimo para una campaña nueva e independiente

Ninguno de estos pasos toca EXP004A, y ninguno necesita un RFC nuevo:

1. **Congelar primero, con la regla de vela cerrada.** `wp_edge04_freeze.py freeze` sobre el
   corpus nuevo; si imprime `UNCLOSED_BAR`, el corpus no está listo y no se congela.
2. **Corpus propio y pin propio.** Los shards 15m se vuelven a pedir al venue *hacia delante*
   (`since` = instante de arranque), con `run_id` nuevo y hashes nuevos. Los valores esperados
   de EXP004A no se reutilizan: serían otros bytes y otro experimento.
3. **Espejo fuera del árbol al crearlo**, no después, y `drill` como parte del arranque.
4. **Un solo criterio de admisión nuevo**: la campaña no empieza hasta que `verify` salga 0 y
   `drill` devuelva `restored=true` con el lector de acuerdo.

## 8. Artefactos

`RUN_REPORT.md`, `RUN_REPORT.json`, `EVIDENCE.json`, `VERIFIER.json` y `raw/` (matriz, recibos de
congelación/espejo/drill, informe del run paper, salidas de tests y del verificador) en
`docs/agentic/exp004a/wp_edge04_progress/`.
