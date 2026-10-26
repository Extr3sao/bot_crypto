# Ejecución sin ventanas en Windows

> Contrato operativo de `WP-OPS-BACKGROUND-001`. Aplica a todo proceso que este
> repositorio arranca **sin una persona delante**: tareas programadas,
> supervisores, capturas y verificadores.

## 1. El problema, medido

Una ventana de consola no aparece porque un script "haga ruido": aparece porque
Windows tiene que **crear una consola** para un ejecutable de subsistema consola
cuyo padre no tiene ninguna. La cadena de padres de este host, leída con
`scripts/ops_window_origin.py`, lo dice sin interpretación:

```text
explorer.exe   GUI
└── Freebuff.exe   GUI        (Electron: no tiene consola)
    └── bun.exe    CONSOLE    ← aquí Windows crea la consola: la ventana
        └── bash.exe  CONSOLE
            └── python.exe ...
```

`bun.exe` es de subsistema consola y su padre (`Freebuff.exe`) es GUI. Esa pareja
es la definición de "se va a asignar una consola nueva". Dentro de esa consola
viven los comandos que lanza Codebuff, y por eso la ventana que se ve es de
**Bash/CMD**, no de nuestros scripts.

La segunda fuente es nuestra: una tarea programada con `InteractiveToken` que
ejecuta `python.exe` es un proceso de consola en la sesión interactiva, así que
posee una ventana mientras dura la campaña. Y cualquier `Popen` sin flags
hereda el mismo problema cuando el padre no tiene consola.

## 2. El contrato

Una sola implementación: [`src/trading_bot/ops/windowless.py`](../../src/trading_bot/ops/windowless.py).

| Necesidad | Llamada | Qué garantiza |
| --- | --- | --- |
| Hijo de vida corta, salida capturada | `windowless.run(argv, timeout=..., text=True)` | `CREATE_NO_WINDOW` + `STARTUPINFO(SW_HIDE)`, stdout/stderr, PID, exit code, duración, registro JSONL |
| Hijo supervisado | `windowless.spawn(argv, stdout=log, event_log=...)` | lo anterior sin bloquear; el `Popen` devuelto es la prueba de propiedad |
| Fin de un árbol | `windowless.terminate_tree(process)` | `taskkill /PID <pid> /T /F` solo sobre el PID que sigue siendo nuestro; `killpg` en POSIX |
| Tarea programada | `pythonw.exe scripts/windowless.py --log ... -- comando` | la tarea no tiene consola; el hijo se crea oculto; el exit code del hijo es el de la tarea |
| Muere el lanzador | `--keep-together` | job object con `KILL_ON_JOB_CLOSE`: el hijo no queda huérfano |

`TAP_WINDOWLESS=0` desactiva los flags para depurar un hijo que necesite consola.
Es la única forma de apagarlo, y es explícita.

### Lo que se conserva

stdout, stderr, exit code, PID, `cwd`, entorno, duración, timeout y errores de
arranque. Todo va a dos sitios:

* el log del hijo (append-only, ambos streams);
* un JSONL de ejecución con dos registros por lanzamiento:

```json
{"event":"spawn","pid":37524,"command":["python.exe","-m","pytest",...],"windowless":true}
{"event":"exit","pid":37524,"exit_code":0,"duration_seconds":17.5,"timed_out":false}
```

Un fallo al escribir el log no tumba el trabajo: se cuenta en `write_failures` y
se avisa una vez por stderr.

### Timeout, cancelación y limpieza

* `run(timeout=...)` y el `--timeout` del lanzador terminan **el hijo y sus
  descendientes** antes de devolver `124`/`TimeoutExpired`.
* `Ctrl-C`/`SIGTERM` en el lanzador termina el mismo árbol y devuelve `130`.
* `--keep-together` asigna el hijo a un job object: si el lanzador muere, Windows
  cierra el job y con él el árbol. No se busca ni se mata nada por nombre.
* Un proceso que no arrancamos no es objetivo: el alcance es el handle de
  `Popen`, no un patrón de línea de comandos.

## 3. Qué usa el contrato

| Fichero | Antes | Ahora |
| --- | --- | --- |
| `src/trading_bot/autonomous/supervisor.py` | `subprocess.Popen` sin flags | `windowless.spawn` + `terminate_tree` + `execution.jsonl` |
| `scripts/cap004_supervisor.py` | tarea = `python.exe`; `subprocess.run` | tarea = `pythonw.exe scripts/windowless.py`; `windowless.run` |
| `scripts/wp9_runtime_rehearsal.py` | `subprocess.Popen` sin flags | `windowless.spawn` |
| `scripts/recovery_run_report.py` | `shell=True` (hop por `cmd.exe`) | argv + `windowless.run` |
| `scripts/alpha002_capture.cmd` | `python.exe` directo | `pythonw.exe scripts/windowless.py --keep-together` |

## 4. Verificación

```bash
.venv/Scripts/python.exe -m pytest tests/unit/ops -q                        # 13 passed
.venv/Scripts/python.exe scripts/ops_background_audit.py --json ... --md ... # 0 HIGH
.venv/Scripts/python.exe scripts/ops_windowless_probe.py --out ...          # structural PASS
```

El probe arranca dos hijos desde un padre **sin consola** (`pythonw.exe`):

| caso | procesos en su consola | ventana visible |
| --- | ---: | --- |
| `plain` (sin flags) | 9 | no observable |
| `guarded` (nuestro lanzador) | 2 | no observable |

Nueve significa que el hijo se unió a una consola ya existente; dos, que recibió
una consola privada y oculta (`python` + `conhost`). Es la diferencia que
`CREATE_NO_WINDOW` produce.

`GetConsoleWindow` devuelve `0` en ambos casos **en este host** porque la consola
está alojada por Windows Terminal (ConPTY), que no tiene `HWND`. Por eso el
informe declara `visual_verdict = NOT_OBSERVABLE`: no se afirma "no se vio
ninguna ventana", se afirma el mecanismo y se mide la diferencia de adjunción.

## 5. Lo que sigue abierto

* **303 llamadas `subprocess.run` acotadas** no pasan aún por el helper
  (`RUN_WITHOUT_WINDOWLESS`, severidad MEDIUM). Son de vida corta y muchas son
  scripts de evidencia que una persona lanza desde una terminal; cuando su padre
  no tiene consola, pueden parpadear. Están inventariadas, no ocultas.
* **20 lanzadores `.cmd`/`.bat` históricos** dentro de `reports/` siguen
  invocando `python.exe` (MEDIUM). Se dejan como artefactos de evidencia; la
  ruta de automatización es el lanzador sin ventana.
* **1 probe de investigación** (`src/trading_bot/research/edge04r/session.py`)
  registra una tarea con acción `cmd.exe` para leer su definición. Cambiarlo
  alteraría el probe; queda marcado MEDIUM y fuera de la ruta de automatización.

## 6. Bloqueo externo: Codebuff / Freebuff Desktop

La ventana de Bash/CMD que aparece durante una ejecución automática **no la abre
este repositorio**. El `bun.exe` de Codebuff es el primer proceso de consola de la
cadena, y su padre es GUI. El binario instalado
(`…/@codebufffreebuff-desktop/resources/orchestrator/orchestrator.js`) sí pasa
`windowsHide: true` en varias rutas —el servidor MCP, `reg`/`cygpath`,
`spawnDirectTerminalCommand` y las tareas de fondo— pero **no** en
`Bun.spawn([resolved, ...args], { cwd, env, stdin, stdout: "pipe", stderr: "pipe", detached })`,
que es la ruta por la que corre el shell de la herramienta.

`Bun.spawn` acepta `windowsHide`; sin él, Windows crea la consola. No existe en
esta build (0.0.173) un ajuste de usuario que lo active, y no es correcto que el
repositorio parchee un binario firmado que se actualiza solo.

**Mitigación disponible hoy**: iniciar `Freebuff.exe` desde una consola ya
existente (por ejemplo, una ventana de terminal abierta a mano). Los hijos de
consola heredan esa consola y dejan de crear una nueva. Mientras eso no se haga,
la ventana es de Codebuff, no de nuestros scripts.

**Corrección de fondo** (para el equipo de Codebuff): añadir `windowsHide: true`
a ese `Bun.spawn` —o crear el proceso con `CREATE_NO_WINDOW`— y cubrirlo con un
test que arranque un comando desde un padre GUI.
