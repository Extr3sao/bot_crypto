# WP-OPS-BACKGROUND-001 — Consolas Windows invisibles, logs y ciclo de vida

**Estado:** PENDIENTE DE DIAGNÓSTICO/IMPLEMENTACIÓN. Incidencia reportada por usuario el 18/10/2026. No está corregido en runtime.

## Objetivo y alcance

Durante ejecuciones automáticas de Codex/Codebuff/Trading Agentic Portable **no deben aparecer ventanas independientes de** `bash.exe`, `git-bash.exe`, `mintty.exe`, `cmd.exe`, `powershell.exe`, `pwsh.exe` ni `WindowsTerminal.exe`. Es legítimo usar shells como procesos hijos **sin UI visible**, cuando son necesarios para scripts, tests y procesos background.

**No silenciar evidencias:** stdout/stderr, código de salida, cwd, comando normalizado sin secretos, PID de hijo, parent PID, start/stop y timeout deben quedar trazables en ficheros de logs por run, con rotación y sin credenciales. Errores no son PASS.

## WP y aceptación

1. **RED diagnóstico:** inventariar entrypoints que invoquen `subprocess.Popen`, `subprocess.run`, `os.system`, `start`, `Start-Process`, `wt.exe`, `mintty.exe`, `git-bash.exe`, terminal externo en tasks IDE, agent wrappers y launchers. Capturar árbol PID→PPID y quién crea las ventanas. No matar procesos ajenos.
2. **Win32:** preferir `shell=False`, ejecutable `bash.exe` directo solo cuando necesario, `subprocess.CREATE_NO_WINDOW` + `subprocess.STARTUPINFO` con `STARTF_USESHOWWINDOW`/SW_HIDE, redirección real de stdout/stderr a log o PIPE drenada y `stdin=DEVNULL`. Si el proceso usa `mintty.exe`/terminal externo, sustituir launcher, no ocultar la evidencia; evaluar tasks integradas del IDE/Codebuff separadamente.
3. **Lifecycles:** cancellation/timeout terminan **solo los hijos lanzados por el run** y esperan su finalización; evitan procesos zombis, ciclos de polling intensivos y segunda instancia inadvertida; logs archivados y checksum.
4. **Pruebas Windows nativas:** arrancar/invocar REA, scripts de captura, ruff, mypy, pytest, git desde la misma ruta que abre ventanas; 0 ventanas emergentes durante 10 ejecuciones y reinicio/cancelación. Confirmar cobertura de PowerShell, Git Bash, Task Scheduler, IDE launcher; si la ventana viene del host Codex no controlable desde repo, dejar `BLOCKED_EXTERNAL_LAUNCHER` y recomendar ajuste host preciso, no false success.
5. **No alterar riesgo/estrategias/live:** cambios opt-in en capa de invocación; tests en branch/worktree aislado y builder!=verifier.

## Patrón Python (ejemplo, no afirmación de implantación)

```python
import subprocess
from pathlib import Path
from contextlib import ExitStack

def run_hidden(executable: str, args: list[str], log_file: Path, cwd: Path) -> int:
    startup = subprocess.STARTUPINFO()
    startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    startup.wShowWindow = 0  # SW_HIDE
    log_file.parent.mkdir(parents=True, exist_ok=True)
    with log_file.open("ab", buffering=0) as stream:
        result = subprocess.run(
            [executable, *args], cwd=str(cwd), check=False,
            shell=False, stdin=subprocess.DEVNULL,
            stdout=stream, stderr=subprocess.STDOUT,
            creationflags=subprocess.CREATE_NO_WINDOW,
            startupinfo=startup
        )
        return result.returncode
```

Este ejemplo **solo funciona en Windows** y debe encapsularse tras `sys.platform == "win32"`; POSIX requiere flags diferentes. Cerrar el proceso *porque aparece una ventana* no es solución válida. Ni `DETACHED_PROCESS` ni `start /min` garantizan trazabilidad; no ocultar logs ni exits.

**Evidencia de cierre:** `RUN_REPORT.md/json`, `WINDOW_PIDS.jsonl`, `HIDDEN_LAUNCHER_TEST.json`, logs por PID, independiente/verifier, tests RED→GREEN y pruebas sobre commit remoto. Cerrar `TAP-061` solo con 0 ventanas realmente observadas en Windows.

**Relación con el roadmap:** `TAP-061`, `BL-14`; no equivale a que el problema ya esté resuelto.
