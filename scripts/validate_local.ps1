<#
.SYNOPSIS
  Validate TSK-099 (typed config with Pydantic v2) end-to-end.

.DESCRIPTION
  Runs in order:
    0) Preflight: python >=3.11 y uv disponibles.
    1) uv sync (omitible con -SkipSync para re-runs rapidos).
    2) ruff check (lint).
    3) ruff format --check (format gate).
    4) mypy strict (types).
    5) pytest + cobertura >= 90% (DoD coverage).
    6) python -m trading_bot.config --validate (smoke CLI).
    7) python -m trading_bot.config --dump-json (artefacto resuelto).

  Aborta en el primer fallo con un mensaje en rojo y el codigo de salida
  del step que fallo. Pensado para invocarse en UN solo comando:

    powershell -ExecutionPolicy Bypass -File scripts\validate_local.ps1

.PARAMETER SkipSync
  Omite el step 1 ('uv sync'). Util para re-runs tras instalar deps.

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File scripts\validate_local.ps1

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File scripts\validate_local.ps1 -SkipSync

.NOTES
  Patron heredado de scripts/git_init_and_push.ps1, endurecido para
  propagar errores nativos al exit code:
    - Preflight captura la ruta absoluta de uv con Get-Command uv y la
      guarda en $script:uvPath, evitando que el PATH-lookup dependa
      de `uv sync` (paso 1) que desinstala uv del .venv porque no
      esta en [dependency-groups].
    - Preflight siempre corre aunque -SkipSync: condiciona $script:uvPath
      necesario por Invoke-Uv.
    - Dentro del scope block por step, $ErrorActionPreference = "Stop"
      para que CommandNotFoundException (uv no encontrado) o
      ValidationError (mypy/Pydantic) sean TERMINANTES.
    - El catch distingue CommandNotFoundException (exit 127, tipico de
      uv no encontrado tras uv-sync auto-uninstall) del resto.
    - $LASTEXITCODE del body se preserva y decide halt; stderr ruidoso
      de uv/ruff sigue imprimiendose sin abortar.
  Esto evita el bug clasico de "NativeCommandError aunque el comando
  termino OK" Y el bug inverso "el script imprime OK aun cuando hubo
  CommandNotFoundException" que vimos en Windows al re-correr el script.
#>

[CmdletBinding()]
param(
  [switch]$SkipSync
)

$ErrorActionPreference = "Stop"

# Resolvemos la raiz del proyecto desde la localizacion del script
# para que pueda ejecutarse desde cualquier cwd (PowerShell conserva
# $PSScriptRoot correctamente).
$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Set-Location $ProjectRoot
$VenvScripts = Join-Path $ProjectRoot ".venv\Scripts"
$PythonCmd = if (Test-Path (Join-Path $VenvScripts "python.exe")) {
  Join-Path $VenvScripts "python.exe"
} else {
  "python"
}
$SystemPythonCmd = "python"

function Invoke-Uv {
  param(
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$Args
  )

  if (-not $script:uvLaunchMode) {
    throw 'Invoke-Uv llamado antes del preflight ($script:uvLaunchMode no resuelto).'
  }
  if ($script:uvLaunchMode -eq "python-module") {
    & $script:uvPythonCmd -m uv @Args
    return
  }

  # Invoca el binario `uv` usando la ruta ABSOLUTA capturada en preflight.
  # No usamos `& uv @Args` con PATH-lookup porque el step 1 hace `uv sync`,
  # que sincroniza `.venv/` con `[dependency-groups]` del pyproject.toml.
  # Como `uv` no esta listado alli (intencional: PEP 735 / dev tools
  # solo, no se meta a si mismo), uv sync lo DESINSTALA del
  # `.venv\Scripts\uv.exe` -- y si era la unica copia en PATH (tipico
  # cuando `pip install uv` se hizo dentro del venv activo), Lookup en
  # PATH pierde la entrada y los pasos 2-7 fallan con
  # 'CommandNotFoundException (uv)'. La ruta absoluta vive fuera del
  # venv y uv sync no la toca.
  if (-not $script:uvPath) {
    throw 'Invoke-Uv en modo binary pero $script:uvPath no esta resuelto.'
  }
  & $script:uvPath @Args
}

# -------------------------------------------------------------------
# Helpers
# -------------------------------------------------------------------
function Write-Step([string]$name) {
  Write-Host ""
  Write-Host ("=== " + $name + " ===") -ForegroundColor Cyan
}

# Patron heredado de scripts/git_init_and_push.ps1, endurecido para
# propagar errores nativos al exit code:
#   - Preflight captura la ruta absoluta de uv con Get-Command uv y la
#     guarda en $script:uvPath, evitando que el PATH-lookup dependa
#     de `uv sync` (paso 1) que desinstala uv del .venv porque no
#     esta en [dependency-groups].
#   - Preflight siempre corre aunque -SkipSync: condiciona $script:uvPath
#     necesario por Invoke-Uv.
#   - Dentro del scope block por step, $ErrorActionPreference = "Stop"
#     para que CommandNotFoundException (uv no encontrado) o
#     ValidationError (mypy/Pydantic) sean TERMINANTES.
#   - El catch distingue CommandNotFoundException (exit 127, tipico de
#     uv no encontrado tras uv-sync auto-uninstall) del resto.
#   - $LASTEXITCODE del body se preserva y decide halt; stderr ruidoso
#     de uv/ruff sigue imprimiendose sin abortar.
function Run-Step([string]$name, [scriptblock]$body) {
  Write-Step $name
  $script:exitCode = 0
  try {
    & {
      $ErrorActionPreference = "Stop"
      $global:LASTEXITCODE = 0
      & $body
      $script:exitCode = $LASTEXITCODE
    }
  } catch [System.Management.Automation.CommandNotFoundException] {
    Write-Host ("FAIL [" + $name + "] (cmd no encontrado): " + $_.Exception.Message) `
      -ForegroundColor Red
    $script:exitCode = 127
  } catch {
    Write-Host ("ERROR abortado [" + $name + "]: " + $_.Exception.Message) `
      -ForegroundColor Red
    $script:exitCode = 1
  }
  if ($script:exitCode -ne 0) {
    Write-Host ("FAIL: " + $name + " (exit code " + $script:exitCode + ")") `
      -ForegroundColor Red
    Write-Host "Copia el output completo y pegalo al asistente para diagnosticar." `
      -ForegroundColor Yellow
    exit $script:exitCode
  }
  Write-Host ("OK: " + $name) -ForegroundColor Green
}

# -------------------------------------------------------------------
# 0) Preflight
# -------------------------------------------------------------------
Write-Step "Preflight: python >=3.11 y uv"
$pythonVersion = & $PythonCmd --version 2>&1
Write-Host ("python: " + $pythonVersion)

if ($pythonVersion -notmatch "Python 3\.1[1-9]") {
  Write-Host "FAIL: se requiere Python 3.11+ en PATH." -ForegroundColor Red
  exit 2
}

# Resolvemos la forma de invocar uv UNA SOLA VEZ aqui. Preferimos
# `python -m uv` porque funciona aunque `uv.exe` no este en PATH.
$uvCommand = Get-Command uv -ErrorAction SilentlyContinue
$uvModuleVersion = & {
  $ErrorActionPreference = "Continue"
  & $PythonCmd -m uv --version 2>&1
}
$uvModuleExitCode = $LASTEXITCODE
$uvSystemModuleVersion = & {
  $ErrorActionPreference = "Continue"
  & $SystemPythonCmd -m uv --version 2>&1
}
$uvSystemModuleExitCode = $LASTEXITCODE
if ($uvModuleExitCode -eq 0 -and ($uvModuleVersion | Out-String) -match "uv ") {
  $script:uvLaunchMode = "python-module"
  $script:uvPythonCmd = $PythonCmd
  $script:uvPath = $null
  $uvVersion = ($uvModuleVersion | Out-String).Trim()
  Write-Host ("uv:     " + $uvVersion + " (via " + $PythonCmd + " -m uv)")
} elseif ($uvSystemModuleExitCode -eq 0 -and ($uvSystemModuleVersion | Out-String) -match "uv ") {
  $script:uvLaunchMode = "python-module"
  $script:uvPythonCmd = $SystemPythonCmd
  $script:uvPath = $null
  $uvVersion = ($uvSystemModuleVersion | Out-String).Trim()
  Write-Host ("uv:     " + $uvVersion + " (via python -m uv)")
} elseif ($uvCommand) {
  $script:uvLaunchMode = "binary"
  $script:uvPythonCmd = $null
  $script:uvPath = $uvCommand.Source
  $uvVersion = & $script:uvPath --version 2>&1
  Write-Host ("uv:     " + $uvVersion + " (at " + $script:uvPath + ")")
} else {
  Write-Host "FAIL: uv no disponible ni como 'python -m uv' ni como binario en PATH. Instalar: pip install uv  (o)  winget install astral-sh.uv" `
    -ForegroundColor Red
  exit 2
}

if ($uvVersion -notmatch "uv ") {
  Write-Host ("FAIL: el resolvedor de uv devolvio '" + $uvVersion + "'; no parece uv.") `
    -ForegroundColor Red
  exit 2
}
Write-Host ("OK: preflight") -ForegroundColor Green

# -------------------------------------------------------------------
# 1) uv sync
# -------------------------------------------------------------------
if (-not $SkipSync) {
  Run-Step "1. uv sync" { Invoke-Uv sync }
} else {
  Write-Host ""
  Write-Host "=== 1. uv sync === SKIP (-SkipSync)" -ForegroundColor DarkGray
}

# -------------------------------------------------------------------
# 2-7) Validacion
# -------------------------------------------------------------------
Run-Step "2. ruff check (lint)" {
  Invoke-Uv run ruff check src/trading_bot/config tests/unit/config
}

Run-Step "3. ruff format --check (format gate)" {
  Invoke-Uv run ruff format --check src/trading_bot/config tests/unit/config
}

Run-Step "4. mypy (strict types)" {
  Invoke-Uv run mypy src/trading_bot/config tests/unit/config
}

Run-Step "5. pytest + cobertura >= 90% (DoD)" {
  Invoke-Uv run pytest tests/unit/config -v `
    --cov=src/trading_bot/config `
    --cov-report=term-missing `
    --cov-fail-under=90
}

Run-Step "6. python -m trading_bot.config --validate (smoke CLI)" {
  Invoke-Uv run python -m trading_bot.config --validate
}

Run-Step "7. python -m trading_bot.config --dump-json (artefacto)" {
  Invoke-Uv run python -m trading_bot.config --dump-json
}

Write-Host ""
Write-Host "=== TSK-099 validado end-to-end ===" -ForegroundColor Green
Write-Host "Cierra TSK-099 con: 'feat: TSK-099 typed config with Pydantic v2' en develop." `
  -ForegroundColor Green
