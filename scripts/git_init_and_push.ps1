<#
.SYNOPSIS
  Inicializa el repo local y realiza el push inicial a GitHub.

.DESCRIPTION
  Script PowerShell idempotente y seguro para el proyecto
  crypto-scalping-agentic-bot. Hace:
   - Pre-flight de git, .env y credenciales locales.
   - Identidad local (no global) con fallback seguro.
   - git init + rama 'main' (renombra si viniera en 'master').
   - Filtro de seguridad sobre archivos staged (nombres peligrosos,
     extensiones sensibles, regex de tokens conocidos).
   - DOS pausas humanas: una tras 'git add' (revision de stage) y
     otra antes de 'git push' (recordatorio de proteccion de rama).
   - Fetch + rebase sobre origin/main si el remoto ya tenia
     commits (p.ej. README creado desde la UI de GitHub).
   - git push -u origin main.

  El script NO modifica secretos ni credenciales locales existentes.
  Ante cualquier senial de riesgo, ABORTA sin commitear.

.PARAMETER RemoteUrl
  URL HTTPS del repo de destino. Por defecto la firmada en ADR-0009.

.PARAMETER InitialCommitMessage
  Mensaje del commit inicial.

.PARAMETER LocalUserName
  Nombre local (solo este repo) usado si no hay identidad global.

.PARAMETER LocalUserEmail
  Email local usado si no hay identidad global.

.EXAMPLE
  pwsh -File scripts\git_init_and_push.ps1

.EXAMPLE
  pwsh -File scripts\git_init_and_push.ps1 -RemoteUrl https://github.com/Extr3sao/bot_crypto.git

.NOTES
  Invocacion (elige segun tu version de PowerShell):
   - PowerShell 7+  (pwsh, multiplataforma): 'pwsh -File scripts\git_init_and_push.ps1'
   - Windows PowerShell 5.1 (por defecto en Windows):
       'powershell -ExecutionPolicy Bypass -File scripts\git_init_and_push.ps1'
   - El script autobypasea ExecutionPolicy con -Scope Process; el flag
     '-ExecutionPolicy Bypass' es una red defensiva para politicas restringidas.

  Compatibilidad: probado conceptualmente con Windows PowerShell 5.1 y
  PowerShell 7+. Set-StrictMode usa '-Version Latest' para caer a v2 en
  PS 5.1 y v3 en PS 7+ sin parametrizar la version manualmente.

  Ver decisiones relacionadas:
   - ADR-0001 Licencia propietaria / uso interno privado.
   - ADR-0009 Hosting y repositorio remoto.
   - process_status: home office user; no usar credenciales globales.
#>
[CmdletBinding()]
param(
  [string]$RemoteUrl = "https://github.com/Extr3sao/bot_crypto.git",
  [string]$InitialCommitMessage = "chore: initial Phase 0 scaffolding for crypto-scalping-agentic-bot",
  [string]$LocalUserName = "Crypto Bot Admin",
  [string]$LocalUserEmail = "admin@bot-crypto.local"
)

$ErrorActionPreference = "Stop"

# Autobypass de ExecutionPolicy SOLO para este proceso (no afecta al sistema).
try {
  Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass -Force -ErrorAction SilentlyContinue | Out-Null
} catch { }

Set-StrictMode -Version Latest

# ---------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------
function Write-Section {
  param([string]$Message)
  Write-Host ""
  Write-Host "=== $Message ===" -ForegroundColor Cyan
}

function Require-Command {
  param([string]$CommandName)
  $null = Get-Command $CommandName -ErrorAction SilentlyContinue
  if (-not $?) {
    Write-Host "ERROR: '$CommandName' no esta en PATH. Instala Git for Windows: https://git-scm.com/download/win" -ForegroundColor Red
    exit 1
  }
}

function Ask-Continue {
  param([string]$Prompt)
  $answer = Read-Host "$Prompt [y/N]"
  if ($answer -notmatch '^[Yy]$') {
    Write-Host "Abortado por el usuario." -ForegroundColor Yellow
    exit 2
  }
}

function Repo-Path {
  param([string]$Relative)
  return (Join-Path (Get-Location).Path $Relative)
}

# ---------------------------------------------------------------
# Pre-flight
# ---------------------------------------------------------------
Write-Section "Pre-flight checks"
Require-Command "git"

$gitVersionLine = git --version
Write-Host $gitVersionLine

if (Test-Path (Repo-Path ".env")) {
  Write-Host "ERROR: archivo .env presente en la raiz. .gitignore deberia excluirlo." -ForegroundColor Red
  exit 1
}

# ---------------------------------------------------------------
# Init (idempotente)  -- DEBE ir ANTES de leer/escribir config local,
# porque 'git config --local' necesita '.git/' presente.
# ---------------------------------------------------------------
Write-Section "Repository initialization"
if (Test-Path (Repo-Path ".git")) {
  Write-Host ".git/ ya existe - se omite 'git init'." -ForegroundColor Yellow
} else {
  # -b main crea la rama inicial con nombre 'main' (git >= 2.28).
  git init -b main | Out-Null
  if ($LASTEXITCODE -ne 0) {
    Write-Host "ERROR: 'git init -b main' fallo. Revisa permisos/disco y vuelve a correr." -ForegroundColor Red
    exit 1
  }
  Write-Host "git init done."
}

# Asegurar rama 'main' (cubre .git preexistente en 'master' o detached HEAD).
# Envoltorio try/catch defensivo: 'git symbolic-ref --short HEAD' puede salir != 0
# en detached HEAD y, con $ErrorActionPreference=Stop, eso lanzaria un
# NativeCommandError que abortaria el script antes de poder decidir la rama actual.
$currentBranch = $null
try {
  $currentBranch = git symbolic-ref --short HEAD 2>$null
} catch {
  # Detached HEAD o .git ausente: deja $currentBranch en $null y seguimos.
}
if ($currentBranch -and ($currentBranch -ne "main")) {
  git branch -m main | Out-Null
  if ($LASTEXITCODE -ne 0) {
    Write-Host "ERROR: no se pudo renombrar la rama actual a 'main'. Saliendo." -ForegroundColor Red
    exit 1
  }
  Write-Host "Renombrada a 'main'."
} else {
  Write-Host "Rama activa: 'main'."
}

# ---------------------------------------------------------------
# Identidad (local, no global)  -- solo DESPUES de tener .git/
# ---------------------------------------------------------------
Write-Section "Git identity (local-only)"
$localName = git config --local user.name 2>$null
$localEmail = git config --local user.email 2>$null
if (-not $localName) {
  git config --local user.name $LocalUserName
  Write-Host "user.name (local) -> $LocalUserName"
}
if (-not $localEmail) {
  git config --local user.email $LocalUserEmail
  Write-Host "user.email (local) -> $LocalUserEmail"
}
Write-Host "user.name:  $(git config --local user.name)"
Write-Host "user.email: $(git config --local user.email)"

# ---------------------------------------------------------------
# Stage + filtro de seguridad
# ---------------------------------------------------------------
Write-Section "git add . + safety filter"
git add .
if ($LASTEXITCODE -ne 0) {
  Write-Host "ERROR: 'git add .' fallo. Revisa permisos y paths bloqueados." -ForegroundColor Red
  exit 1
}

Write-Host ""
Write-Host "Archivos staged (git status --short):" -ForegroundColor Cyan
git status --short

# Lista de nombres bloqueados (coincidencia exacta)
$dangerousNames = @(
  ".env", ".env.local", ".env.production", ".env.development",
  "credentials.json", "client_secret.json", "auth.json"
)
# Extensiones bloqueadas (case-insensitive)
$dangerousExtensions = @(".pem", ".key", ".p12", ".pfx", ".db", ".db-journal")
# Extensiones donde SI escaneamos contenido con regex
$scannableExtensions = @(".py", ".yaml", ".yml", ".json", ".md", ".toml", ".txt", ".ini", ".cfg", ".env", ".sh", ".ps1", ".tf")
# Patrones de tokens conocidos
$dangerousPatterns = @(
  'ghp_[A-Za-z0-9]{36}',
  'gho_[A-Za-z0-9]{36}',
  'AKIA[0-9A-Z]{16}',
  '(?i)(api[_-]?key|secret|password)\s*[:=]\s*["'']?(?!changeme|paste)[A-Za-z0-9]{10,}["'']?'
)

$stagedNames = git diff --name-only --cached
$violations = @()

foreach ($name in $stagedNames) {
  $baseName = Split-Path $name -Leaf
  $ext = [System.IO.Path]::GetExtension($name)

  foreach ($bad in $dangerousNames) {
    if ($name -eq $bad -or $baseName -eq $bad) {
      $violations += "$name (nombre bloqueado: $bad)"
    }
  }
  if ($ext -and ($dangerousExtensions -contains $ext.ToLower())) {
    $violations += "$name (extension bloqueada: $ext)"
  }
  if ($ext -and ($scannableExtensions -contains $ext.ToLower())) {
    $fullPath = Repo-Path $name
    if (Test-Path $fullPath) {
      $content = Get-Content -Path $fullPath -Raw -ErrorAction SilentlyContinue
      foreach ($pattern in $dangerousPatterns) {
        if ($content -and ($content -match $pattern)) {
          $violations += "$name (regex: $pattern)"
          break
        }
      }
    }
  }
}

if ($violations.Count -gt 0) {
  Write-Host ""
  Write-Host "ERROR: violaciones en el stage:" -ForegroundColor Red
  foreach ($v in $violations) { Write-Host "  - $v" -ForegroundColor Red }
  Write-Host ""
  Write-Host "Para sacar archivos del stage usa: git reset HEAD <archivo>" -ForegroundColor Yellow
  exit 1
}
Write-Host "Safety filter OK."

# ---------------------------------------------------------------
# Pausa 1: revision del stage
# ---------------------------------------------------------------
Write-Section "PAUSA 1 - revisar stage"
Ask-Continue "Continuar con el commit inicial?"

# ---------------------------------------------------------------
# Commit
# ---------------------------------------------------------------
Write-Section "git commit"
# 'git commit' escribe '[main abc123] message' a stderr en exito. Mismo patron
# que fetch/pull/push: scope local con Continue para absorber el ruido.
$commitExitCode = 0
& {
  $ErrorActionPreference = "Continue"
  git commit -m "$InitialCommitMessage" 2>&1
  $commitExitCode = $LASTEXITCODE
}
if ($commitExitCode -ne 0) {
  Write-Host "ERROR: git commit devolvio codigo no-cero ($commitExitCode). Abortando." -ForegroundColor Red
  exit 1
}

# ---------------------------------------------------------------
# Remoto: alta o ajuste
# ---------------------------------------------------------------
Write-Section "Remote setup"

# 'git remote get-url origin' falla con NativeCommandError cuando 'origin' no
# existe (exit != 0 + $ErrorActionPreference=Stop hace abortar el script).
# Usamos 'git remote -v' (siempre sale 0, incluso sin remotos) y parseamos
# la salida para detectar el URL de 'origin'.
$existingRemote = $null
foreach ($line in (git remote -v 2>$null)) {
  if ($line -match '^origin\s+(.+?)\s+\(fetch\)') {
    $existingRemote = $Matches[1]
    break
  }
}

if ($existingRemote) {
  if ($existingRemote -ne $RemoteUrl) {
    Write-Host "Remote 'origin' actual: $existingRemote" -ForegroundColor Yellow
    Write-Host "Objetivo:                 $RemoteUrl"
    Ask-Continue "Sobreescribir?"
    git remote set-url origin $RemoteUrl
    if ($LASTEXITCODE -ne 0) {
      Write-Host "ERROR: 'git remote set-url origin' fallo." -ForegroundColor Red
      exit 1
    }
  } else {
    Write-Host "Remote 'origin' ya coincide: $existingRemote"
  }
} else {
  git remote add origin $RemoteUrl
  if ($LASTEXITCODE -ne 0) {
    Write-Host "ERROR: 'git remote add origin' fallo." -ForegroundColor Red
    exit 1
  }
  Write-Host "Remote 'origin' anadido: $RemoteUrl"
}

# Verificar alcance del remoto
git ls-remote origin | Out-Null
if ($LASTEXITCODE -ne 0) {
  Write-Host "ERROR: no se puede alcanzar '$RemoteUrl'. Verifica URL y credenciales HTTPS." -ForegroundColor Red
  exit 1
}
Write-Host "Remoto alcanzable."

# ---------------------------------------------------------------
# Pausa 2: confirmacion + recordatorio proteccion main
# ---------------------------------------------------------------
Write-Section "PAUSA 2 - pre-push"
$owner = ($RemoteUrl -split '/')[-2]
$repo = (($RemoteUrl -split '/')[-1]) -replace '\.git$',''
$branchProtectionUrl = "https://github.com/$owner/$repo/settings/branches"
Write-Host ""
Write-Host "[REMINDER ADR-0009] Protege la rama 'main' tras este push:" -ForegroundColor Yellow
Write-Host "  $branchProtectionUrl" -ForegroundColor Yellow
Write-Host "  Marca al menos: 'Require a pull request before merging' y"
Write-Host "                  'Do not allow force pushes'." -ForegroundColor Yellow
Write-Host ""
Ask-Continue "Proceder con 'git push -u origin main'?"
# ---------------------------------------------------------------
# Fetch + rebase si el remoto ya tenia commits
# ---------------------------------------------------------------
Write-Section "Fetch + rebase si hay divergencia"
# 'git fetch' emite progreso a stderr ("From <url>", "* branch"); con
# $ErrorActionPreference = "Stop" eso se convierte en NativeCommandError
# aunque exit code sea 0. Scope local con Continue para absorber el ruido.
$fetchExitCode = 0
& {
  $ErrorActionPreference = "Continue"
  git fetch origin 2>&1 | Out-Null
  $fetchExitCode = $LASTEXITCODE
}
# 'git rev-parse --verify <ref>' sale != 0 si la ref no existe; con
# $ErrorActionPreference=Stop eso seria NativeCommandError. Envoltorio try/catch.
$remoteMain = $null
try {
  $remoteMain = git rev-parse --verify origin/main 2>$null
} catch { }
$localMain  = $null
try {
  $localMain  = git rev-parse --verify main 2>$null
} catch { }
if ($remoteMain -and $localMain -and ($remoteMain -ne $localMain)) {
  Write-Host "El remoto tiene commits previos (p.ej. README desde la UI). Rebase sobre origin/main..." -ForegroundColor Yellow
  # Mismo patron para 'git pull --rebase' (progreso y conflictos van a stderr).
  $rebaseExitCode = 0
  & {
    $ErrorActionPreference = "Continue"
    git pull --rebase origin main 2>&1
    $rebaseExitCode = $LASTEXITCODE
  }
  if ($rebaseExitCode -ne 0) {
    Write-Host "ERROR: conflictos durante rebase. Resolver manualmente:" -ForegroundColor Red
    Write-Host "  git status" -ForegroundColor Yellow
    Write-Host "  ... editar archivos ..."
    Write-Host "  git add <archivos>"
    Write-Host "  git rebase --continue" -ForegroundColor Yellow
    Write-Host "  ... y luego re-correr este script." -ForegroundColor Yellow
    exit 1
  }
}

# ---------------------------------------------------------------
# Push
# ---------------------------------------------------------------
Write-Section "git push -u origin main"
# 'git push' emite mensajes informativos a stderr (e.g. "To <URL>",
# "branch 'main' set up..."). Con $ErrorActionPreference = "Stop" eso se
# convierte en NativeCommandError aunque exit code sea 0. Scope local con
# Continue para absorber el ruido y capturamos $LASTEXITCODE.
$pushExitCode = 0
& {
  $ErrorActionPreference = "Continue"
  git push -u origin main 2>&1
  $pushExitCode = $LASTEXITCODE
}
if ($pushExitCode -ne 0) {
  Write-Host "ERROR: git push fallo (exit $pushExitCode). Revisa branch protection o credenciales." -ForegroundColor Red
  exit 1
}

Write-Section "Listo"
Write-Host "Push inicial completo. Verifica en: $RemoteUrl" -ForegroundColor Green
Write-Host ""
Write-Host "Proximos pasos:" -ForegroundColor Cyan
Write-Host "  1. Activar proteccion de rama 'main' en GitHub UI (URL arriba)."
Write-Host "  2. Crear rama 'develop' como integradora:  git checkout -b develop"
Write-Host "  3. Instalar uv (ADR-0002) y arrancar TSK-099: configuracion tipada Pydantic."
