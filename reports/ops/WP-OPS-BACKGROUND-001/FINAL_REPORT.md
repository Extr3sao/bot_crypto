# WP-OPS-BACKGROUND-001 — ejecución sin ventanas

Rama `agent/ai-bots/RFC-TAP-AI-BOTS-003` · 2026-10-18 · modo OFFLINE (sin claves,
sin órdenes, sin capital). No se ha tocado `RiskManager`, `PaperBroker` ni
`config/`.

## 1. Veredicto

| afirmación | estado | evidencia |
| --- | --- | --- |
| Nuestros lanzadores no abren ventana | **PASS estructural**; visual `NOT_OBSERVABLE` en este host | `WINDOWLESS_LIVE_PROBE.json`, `tests/unit/ops` |
| La ventana de Bash/CMD viene de Codebuff | **CONFIRMADO** por cadena de padres y subsistema PE | `WINDOWLESS_AUDIT_GREEN.json#origin` |
| Tests, captura y timeout funcionan sin ventana | **PASS** | `evidence/pytest.*`, `evidence/capture.*`, `evidence/timeout.*` |
| Auditoría del repositorio | **CLEAN**: 0 HIGH (antes 7) | `WINDOWLESS_AUDIT_RED.json` → `WINDOWLESS_AUDIT_GREEN.json` |
| TAP-061 actualizado en el Excel maestro | **BLOQUEADO**: el libro no existe en este host | §7 |

## 2. Qué abría realmente las ventanas

Cadena leída con `scripts/ops_window_origin.py` (subsistema del PE de cada
ancestro, no una suposición):

```text
2692  UNKNOWN   (raíz de sesión)
2684  GUI       explorer.exe
1260  GUI       Freebuff.exe            ← Electron: no tiene consola
26968 CONSOLE   bun.exe                 ← Windows crea aquí la consola = la ventana
4332  CONSOLE   bash.exe
26520 CONSOLE   bash.exe
3336  CONSOLE   python.exe (venv)
...
```

`console_is_created_at = "Freebuff.exe (GUI) -> bun.exe (CONSOLE)"`. La ventana
es de **Bash**, y la abre el runner de comandos de Codebuff, no un `.bat` ni un
`Popen` nuestro.

La segunda fuente, esta sí nuestra, era la tarea programada: `python.exe` bajo
`InteractiveToken` posee una consola durante toda la campaña. Y cualquier
`Popen`/`shell=True` sin flags repite el patrón cuando el padre no tiene consola.

## 3. Cambios

| fichero | cambio | por qué |
| --- | --- | --- |
| `src/trading_bot/ops/windowless.py` (nuevo) | `CREATE_NO_WINDOW` + `STARTUPINFO(SW_HIDE)`, `run`/`spawn`, `terminate_tree`, job object, JSONL | una sola implementación; nada que recordar por script |
| `scripts/windowless.py` (nuevo) | lanzador `pythonw` con log, event log, timeout, cancelación, `--keep-together` | lo que debe arrancar el Task Scheduler |
| `src/trading_bot/autonomous/supervisor.py` | `Popen` → `windowless.spawn`; `stop()` → `terminate_tree`; cierra el log | el padre del laboratorio PAPER |
| `scripts/cap004_supervisor.py` | tarea = `pythonw.exe scripts/windowless.py`; `_run` → `windowless.run` | la tarea recurrente no debe poseer consola |
| `scripts/wp9_runtime_rehearsal.py` | `Popen` → `windowless.spawn` | el runtime real, medido, sin ventana |
| `scripts/recovery_run_report.py` | `shell=True` → argv + `windowless.run` | elimina el hop por `cmd.exe` |
| `scripts/alpha002_capture.cmd` | `pythonw` + lanzador + `--keep-together` | captura programada |
| `scripts/ops_background_audit.py` (nuevo) | inventario estático con severidades | el defecto no puede volver sin que un test lo vea |
| `scripts/ops_window_origin.py` (nuevo) | cadena de padres + subsistema PE | atribuir la ventana a quien la abre |
| `scripts/ops_windowless_probe.py` (nuevo) | evidencia viva desde un padre sin consola | medir adjunción de consola |
| `tests/unit/ops/test_windowless.py` (nuevo) | 13 tests RED → GREEN | contrato, no una impresión |
| `tests/unit/research/test_campaign_supervisor.py` | contrato actualizado a `pythonw` + lanzador | el test anterior codificaba el defecto |

## 4. RED → GREEN

```text
RED   pytest tests/unit/ops/test_windowless.py
      ModuleNotFoundError: No module named 'trading_bot.ops'          exit 1
RED   ops_background_audit.py
      HIGH_FINDINGS: HIGH 7 / MEDIUM 333                              exit 1
        SCHEDULED_TASK_CMD_ACTION  scripts/cap004_supervisor.py:1
        SHELL_TRUE                 scripts/recovery_run_report.py:63
        POPEN_WITHOUT_WINDOWLESS   scripts/wp9_runtime_rehearsal.py:290
        POPEN_WITHOUT_WINDOWLESS   src/trading_bot/autonomous/supervisor.py:291
        (+ 2 falsos positivos del propio auditor y del helper, corregidos)

GREEN pytest tests/unit/ops                                       13 passed  exit 0
GREEN pytest tests/unit/autonomous                                284 passed  exit 0
GREEN pytest tests/unit/research/test_campaign_supervisor.py       39 passed  exit 0
GREEN pytest test_st6_scheduler + test_edge12_runner
             + test_edge04r_continuity                             90 passed  exit 0
GREEN pytest test_edge04_autonomous                                87 passed  exit 0
GREEN ops_background_audit.py                     CLEAN 0 HIGH / 324 MEDIUM  exit 0
GREEN ruff check (nuevos y tocados)                        All checks passed  exit 0
GREEN mypy (7 ficheros nuevos/tocados)              Success: no issues found  exit 0
```

`scripts/wp9_runtime_rehearsal.py` conserva **10 errores de mypy que ya existen
en HEAD** (verificado ejecutando la versión de `git show HEAD`); este WP no añade
ninguno. No se han silenciado.

## 5. Verificación en Windows

Probe desde un padre sin consola (`pythonw.exe`), `WINDOWLESS_LIVE_PROBE.json`:

| caso | procesos en su consola | `GetConsoleWindow` | ventana nueva |
| --- | ---: | --- | --- |
| `plain` (sin flags) | **9** | `null` | ninguna enumerada |
| `guarded` (lanzador) | **2** | `null` | ninguna enumerada |

9 = el hijo se unió a una consola existente; 2 = consola privada y oculta
(`python` + `conhost`). `visual_verdict = NOT_OBSERVABLE` porque la consola de
este host la aloja Windows Terminal (ConPTY), que no expone `HWND`: no se afirma
"no se vio una ventana" sin poder verla. `structural_verdict = PASS`.

Ejecuciones reales a través del lanzador:

| prueba | comando | resultado |
| --- | --- | --- |
| tests | `pythonw windowless.py -- pytest tests/unit/ops -q` | 12 passed, exit 0, log + JSONL |
| captura | `pythonw windowless.py -- ai_bots_003c_capture.py --bars 200` | exit 0, 4 artefactos, `CAPTURE.json` |
| timeout | `pythonw windowless.py --timeout 2 --keep-together -- python -c sleep(60)` | exit **124**, `timed_out=true`, `job_object=true` |
| comando inexistente | `-- does-not-exist.exe` | exit **127**, error en el log |

## 6. Lo que NO está cerrado

* **303 `subprocess.run` acotadas** siguen sin el helper (MEDIUM
  `RUN_WITHOUT_WINDOWLESS`). Inventariadas, no migradas.
* **20 `.cmd`/`.bat` históricos** en `reports/` invocan `python.exe` (MEDIUM).
  Son artefactos de evidencia; la ruta de automatización es el lanzador.
* **1 probe de investigación** (`edge04r/session.py`) usa `cmd.exe` como acción
  de una tarea que solo lee su definición. Cambiarlo alteraría el probe.
* La ventana visual no es observable en este host; la prueba es estructural y de
  adjunción de consola, y así se declara.

## 7. Excel maestro y TAP-061 — bloqueado

No existe ningún libro maestro en este host: se buscó por nombre y por contenido
en el repositorio, `Downloads`, `Desktop`, `Documents`, OneDrive y la unidad
`G:`. El único rastro es `Downloads/~$Tareas_Programadas.xlsx` (fichero de
bloqueo de Excel) **sin** su `.xlsx`, es decir, el libro se borró o se movió
mientras estaba abierto.

No se inventa una hoja ni se crea un libro nuevo en su lugar. Se entrega la fila
lista para pegar en `TAP-061_ROW.json` / `TAP-061_ROW.md`, con los mismos campos
que el resto del registro.

## 8. Reanudación

```bash
cd "$(git rev-parse --show-toplevel)"
.venv/Scripts/python.exe -m pytest tests/unit/ops -q                     # 13 passed
.venv/Scripts/python.exe scripts/ops_background_audit.py \
  --json reports/ops/WP-OPS-BACKGROUND-001/WINDOWLESS_AUDIT_GREEN.json   # CLEAN
.venv/Scripts/python.exe scripts/ops_windowless_probe.py \
  --out reports/ops/WP-OPS-BACKGROUND-001/WINDOWLESS_LIVE_PROBE.json    # PASS estructural
```

Para registrar la tarea programada con la acción sin ventana:

```bash
.venv/Scripts/python.exe scripts/cap004_supervisor.py install
```
