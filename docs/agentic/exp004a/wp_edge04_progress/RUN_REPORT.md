# RUN_REPORT — EXP004A progress (matriz, camino paper, congelación)

Árbol: `C:\Users\GVLLFR0035\Downloads\exp004a-recovery-02k` · rama `recovery/exp004a-02k-9983b050`
Modo: **PAPER/OFFLINE ONLY**. Datos públicos de mercado, proveedor falso, cero órdenes, cero
credenciales, ningún límite de riesgo tocado.

## 1. Ejecución, en orden

| # | Comando | Salida | Qué estableció |
|---|---|---|---|
| 1 | `pytest tests/unit/research/test_prospective_freeze.py -q` | **0** (10 passed) | el mecanismo de congelación y sus rechazos |
| 2 | `wp_edge04_freeze.py freeze --root reports/alpha-expansion-v1/data` | **0** | 23 shards, 174.094 barras, `e813921a…`, ninguna vela abierta |
| 3 | recomputar pins 1h de EDGE-03 (`load_1h`, 3 activos) | **0**, `ALL_MATCH True` | congelar no movió lo que el experimento fija |
| 4 | `wp_edge04_freeze.py mirror --dest ~/exp004a-corpus-mirror/…` | **0** | 23/23 shards verificados fuera del árbol |
| 5 | `wp_edge04_freeze.py drill --dest …` | **0** | 24 archivos borrados, `verify` en rojo, restaurado, lector de acuerdo |
| 6 | `wp_edge04_deps.py --out raw/DEPENDENCY_MATRIX.json` | **0** | 470 entrypoints: 29 bloqueados, 441 alcanzables |
| 7 | `pytest tests/unit/paper tests/unit/autonomous -q` | **0** (395 passed) | el runtime paper, de extremo a extremo y offline |
| 8 | `autonomous_paper.py --provider fake --cycles 2 --assets BTC` | **0** | ejecución real: 2 ciclos, `orders_created=0`, `runtime_failures=0` |
| 9 | `wp_edge04_verify.py --raw … --reports …` | **0** (11/11) | consistencia de todo lo anterior, con otro programa |
| 10 | `ruff check` sobre los cuatro scripts nuevos | **0** | sin hallazgos |

## 2. Matriz de dependencias

`scripts/wp_edge04_deps.py` calcula el cierre de imports de cada entrypoint **resolviendo
imports relativos** (sin eso, `edge03.run` parecía no tener dependencias) y separa tres
veredictos: `BLOQUEADO` (lee un directorio ausente sin guarda), `DEGRADA` (corre y marca la
entrada como no disponible) y `ALCANZABLE`.

```
entrypoints 470 · need_15m 29 · blocked 29 · reachable 441
bloqueados incluyen: edge03_run.py, edge04_observer.py (lane programada), edge01_run.py,
                     edge05/06/07/08/12 (…)  ·  alcanzables: autonomous_paper.py, wp_edge04_freeze.py
```

Tres correcciones hicieron falta para que la cifra fuese honesta, y están documentadas en el
propio script porque cada una era un falso positivo que habría inflado el bloqueo:

1. un `def load_15m(` no es una lectura — es un proveedor;
2. `if not root.is_dir(): continue` convierte el directorio en fuente opcional;
3. `CORPUS_15M` nombra una ruta, no la abre.

## 3. Camino paper validado

- **Integración**: 395 tests de `tests/unit/paper` + `tests/unit/autonomous`, exit 0.
- **Runtime**: `--provider fake --cycles 2` deja `RUN_REPORT.json` con `mode=paper`,
  `environment=fake:binance`, `totals.orders_created=0`, `totals.runtime_failures=0`,
  `totals.traces_persisted=2` y el commit del árbol. Copia en `raw/paper/`.

No se ejecutó ninguna variante con proveedor real: no hace falta para demostrar reachability y
habría añadido red y estado sin cambiar el veredicto.

## 4. Congelación y restauración

Ver §4 del informe final. Recibos crudos en `raw/freeze.json`, `raw/mirror.json`,
`raw/drill.json`, `raw/pins_1h_after_freeze.txt`.

## 5. Lo que no se ejecutó, y por qué

- **Tick de EXP004A / habilitar Forward**: el pin sigue sin poder satisfacerse; habilitar sería
  una luz verde sobre una lane que muere en la primera línea.
- **Re-congelar el corpus 15m**: prohibido por el WP anterior y por la RFC.
- **Copia fuera del host**: requiere un medio externo; el espejo actual es del mismo volumen.

## 6. Tests y lint

```
tests/unit/research/test_prospective_freeze.py ............ 10 passed
tests/unit/paper + tests/unit/autonomous ................... 395 passed
ruff check (4 scripts) ..................................... All checks passed
```
