# WP-TDM-015-OPS — puesta en marcha operativa

**Veredicto: `PARTIAL`.**

El sistema de señales y el runtime PAPER quedan operativos con datos reales, con
reinicio sin pérdida de evidencia y con la admisión económica intacta como
trabajo separado. La inferencia IA **no** se certifica: no existe credencial en
este host, y no se sustituyó por un mock. `PAPER_ORDER` sigue bloqueado por
admisión (0 de 24 estrategias) y no se relajó nada para forzar operaciones.

| | |
| --- | --- |
| Run id | `tdm15-ops-01` |
| Base publicada | `c30a826b` (`feat/tdm-015-live-paper`) |
| Commit de código | `c9623fd31d37` |
| Worktree | `ff-wt-tdm15ops`, rama `feat/tdm-015-ops` |
| Ventanas ejecutadas | 3 (mismo run id: 2363 s · 192 s · 898 s) |
| Estado final | `STOPPED`, stop verdict `CLEAN`, 5/5 hijos con exit 0 |
| Órdenes LIVE | **0** |
| Órdenes PAPER | 0 (admisión: 0 candidatas) |
| Inferencias IA reales | **0 — `AI_BLOCKED`** |
| Verificador independiente | **27/27 checks** ([VERIFY.json](VERIFY.json)) |
| Regresiones de tests | **0** ([TEST_RESULTS.json](TEST_RESULTS.json)) |

## 1. Qué se ejecutó

`scripts/start_paper_lab.py` con BTC/ETH/SOL, 5m, proveedor `ccxt`, cadencia
`bar-close`, cinco hijos supervisados (paper, collector, retention, strategy_lab,
analyst). Tres ventanas bajo el mismo run id, cerradas con `--restart` y `--stop`:

| ventana | duración | ciclos PAPER | cierre | evidencia |
| --- | ---: | ---: | --- | --- |
| `20261026T115147Z` | 2363 s | 8 | `STOPPED` / `CLEAN` | [manifiesto de ventana](../../../reports/paper-lab/tdm15-ops-01/windows/20261026T115147Z/WINDOW_MANIFEST.json) |
| `20261026T115503Z` | 192 s | 0 | `STOPPED` / `CLEAN` | misma carpeta `windows/` |
| viva (última) | 898 s | 3 | `STOPPED` / `CLEAN` | [OPS_EXECUTION.json](OPS_EXECUTION.json) |

Resultado de la última ventana (9 evaluaciones activo-ciclo): 33 señales
(21 `CANDIDATE`, 2 `SHADOW`, 10 `REJECTED`), 8 `NO_TRADE`, 0 órdenes, 0 trades
PAPER, 9 trazas persistidas. Los precios son reales: `environment = ccxt:binance`.

## 2. Defectos D-06…D-10

| id | estado | arreglo | prueba |
| --- | --- | --- | --- |
| D-06 | **FIXED** | cerrar `PAPER_RUN.json` **fusiona** sobre el descriptor de lanzamiento en vez de reemplazarlo: un run cerrado conserva `provider`, `environment`, `assets`, `timeframe`, `mode`, preflight del universo y recuentos de registro (`launch_descriptor_preserved: true`) | `test_run_descriptor_provenance.py` (4 casos) |
| D-07 | **FIXED** | `pending_signals` trata una fila `NOT_CONFIGURED` como *cubierta* mientras no haya proveedor, reintenta `FAILED` sólo tras un enfriamiento y ordena primero las señales sin fila. Cobertura real: **33/33 señales con fila** (antes 6/21) | `test_signal_analysis.py` (+3) |
| D-08 | **FIXED** | `SystemState.STOPPED`: una parada limpia ya no se reporta como `DEGRADED`; una parada escalada sigue siendo `FAILED`. Observado en vivo: `final state : STOPPED`, `stop verdict: CLEAN` | `test_supervisor.py` (+2) |
| D-09 | **FIXED** | `--restart` archiva la ventana cerrada en `windows/<window_id>/` (informes, snapshot, heartbeat del sistema, diario PAPER, descriptor, run report y daily) con `sha256` por fichero, índice `windows/INDEX.json` y espera a que el supervisor anterior salga antes de archivar | `test_lab_operations.py` (+4) |
| D-10 | **FIXED** | los gaps se clasifican (`RECOVERED` / `PARTIAL` / `RECOVERABLE` / `UNRECOVERABLE`) con segundos perdidos por clase y motivos, derivados en `RunManifest.as_dict` para no tocar el entry point de captura certificado | `test_forward_contract_storage.py` (+2) |

Sobre D-10 hubo un intento descartado: clasificar dentro de `collector.py` rompía
`test_the_capture_code_still_matches_the_certified_commit` (el guardián del
dataset certificado). La solución correcta era la de lectura, y así
`collector.py` queda **byte-idéntico** a `f406a45` — el guardián pasa sin
relajarse.

## 3. Lo que el run demostró

- **Señales reales**: 33 filas con `bar_close == decision` (sin look-ahead),
  0 filas `LIVE`, y `PAPER` sólo con orden cuando la admisión lo permite.
- **Cobertura del analista**: 33 señales, 33 filas de análisis, una por señal y
  sin repetir la misma fila `NOT_CONFIGURED` en cada pasada (D-07 medido, no
  afirmado).
- **Reinicio**: dos reinicios, tres ventanas, 100 % de digests re-verificados,
  diario de ciclos anterior íntegro (8 líneas en su ventana) y ninguno duplicado.
- **Reconciliación**: expediente `PAPER_RUN.json` cerrado con procedencia
  (`provider=ccxt`, `environment=ccxt:binance`).
- **Dashboard**: 5 endpoints 200 en `http://127.0.0.1:8793` (HTML y JSON
  guardados con su `sha256` en [dashboard/](dashboard/)). Muestra las 33 señales,
  los procesos y el manifiesto de captura.
- **Monitorización**: el heartbeat publica estado por hijo, reinicios, memoria,
  disco libre, nivel, tasa observada y horas restantes; la captura registró
  78 segmentos, 94,97 MB y 110 gaps con clasificación.

## 4. Lo que NO está resuelto

- **ACC-09 / IA real: `AI_BLOCKED`.** No hay `SIGNAL_ANALYST_API_KEY` en el host.
  El sidecar registró 33 filas `NOT_CONFIGURED` con
  `PROVIDER_NOT_CONFIGURED` y ningún `claim`. No se inventó una clave ni se
  simuló una respuesta. Queda preparado el almacén seguro
  (`scripts/paper_lab_service.py`, DPAPI por usuario/máquina, fuera del repo)
  para que, en cuanto exista clave, la misma señal se analice de verdad: las
  filas `NOT_CONFIGURED` pasan a rancias y se reintentan solas (D-07).
- **`PAPER_ORDER` bloqueado**: 0 candidatas en el ledger; 0 trades. La admisión
  económica es trabajo aparte y no se tocó.
- **72 h no intentadas**: no se declara 24/7 ni `PAPER_RUNTIME_VALIDATED`.
  Lo ejecutado son 58 min en tres ventanas, no una validación continua.
- **Captura incompleta**: 110 gaps, 22 recuperados, 88 irrecuperables
  (`WS_DISCONNECT`, `COLLECTOR_RESTART`, `AGG_TRADE_ID_JUMP`), continuidad
  `INCOMPLETE_DATA`. Es la realidad de una red doméstica, registrada y
  clasificada, no oculta.
- **El manifiesto de una captura reanudada describe su sesión**: tras un
  `--restart` el manifiesto cubre 895 s (la última sesión), no las tres. Los
  datos están completos por segmentos; la duración del manifiesto no suma las
  ventanas. Queda anotado como limitación conocida, no arreglado aquí.

## 5. Tests

| ejecución | resultado |
| --- | --- |
| Suite completa (head) | 3427 passed · 87 failed · 14 errors · 31 skipped (876 s) |
| Baseline `c30a826b`, mismos 24 ficheros que fallan | 86 failed · 420 passed · 13 skipped · 14 errors |
| Head, mismos 24 ficheros | 86 failed · 420 passed · 13 skipped · 14 errors |
| Comparación nodo a nodo | 100 nodos comunes · **0 regresiones** · 0 arreglados por accidente |
| Casos nuevos | 19, todos verdes |

El único nodo extra de la suite completa
(`test_runtime_artifacts_are_untouched_by_serving`) falló porque **la propia
captura del lab estaba escribiendo durante el test**; aislado y con el lab
parado: `1 passed`. Los 86 fallos restantes son preexistentes (evidencias
congeladas de research/economic) y fallan igual en el commit padre.

## 6. Operación permanente (preparada, no prometida)

- `scripts/install_paper_lab_task.ps1` registra una tarea de Windows con
  `RestartCount 999` que ejecuta `scripts/paper_lab_service.cmd`.
- `scripts/paper_lab_service.py` carga la clave del analista desde DPAPI
  (usuario+máquina) al entorno del proceso y relanza el lab con `--restart`, que
  ya archiva la ventana anterior: reiniciar el host continúa la misma evidencia
  en lugar de crear un run nuevo.
- Recomendado: `python scripts/paper_lab_service.py --store-secret` (entrada
  oculta) cuando exista clave; `--secret-status` responde sin mostrar el valor.

## 7. Evidencia

| fichero | contenido |
| --- | --- |
| [OPS_EXECUTION.json](OPS_EXECUTION.json) | ejecución, señales, análisis, captura, ventanas, defectos, aceptación |
| [VERIFY.json](VERIFY.json) | 27 comprobaciones recomputadas desde los artefactos |
| [TEST_RESULTS.json](TEST_RESULTS.json) | suite, baseline, comparación nodo a nodo |
| [dashboard/](dashboard/) | respuestas HTTP reales del dashboard con sus digests |
| [FINAL_REPORT.json](FINAL_REPORT.json) | el mismo veredicto, legible por máquina |

Cada número de este informe se lee de un artefacto del run; ninguno se escribió a
mano. `VERIFY.json` no lee `OPS_EXECUTION.json`: re-deriva todo de los
manifiestos, el descriptor y los ledgers, de modo que una discrepancia señala a
los artefactos, no al informe.
