# TSK-013.4 ruff backfill - PR opening pipeline (PowerShell)
#
# Pre-requisites:
#   - gh CLI authenticated: `gh auth status` should return "Logged in to github.com"
#   - Working directory = repo root
#   - Branch feature/tsk-013.4-ruff-cleanup already pushed (ba4f4e9)
#
# Usage:
#   .\scripts\open-pr-tsk-013.4.ps1
#
# Idempotent: re-running will NOT re-create the PR if it already exists.

$ErrorActionPreference = "Stop"

# 1. Pre-flight: gh auth + remote + branch
Write-Host "[1/5] Pre-flight checks..." -ForegroundColor Cyan
gh auth status 2>&1
if ($LASTEXITCODE -ne 0) {
    Write-Error "gh CLI not authenticated. Run: gh auth login"
    exit 1
}

# Validate remote URL is the expected github.com/Extr3sao/bot_crypto
$remoteUrl = git remote get-url origin
if (-not $remoteUrl) {
    Write-Error "No origin remote configured"
    exit 1
}
if ($remoteUrl -notmatch "github\.com[:/](Extr3sao)/bot_crypto") {
    Write-Error "Origin remote is '$remoteUrl' but expected github.com/Extr3sao/bot_crypto. Aborting to avoid wrong-repo PR."
    exit 1
}
Write-Host "Remote OK: $remoteUrl" -ForegroundColor Green

$currentBranch = git branch --show-current
if ($currentBranch -ne "feature/tsk-013.4-ruff-cleanup") {
    Write-Error "Must be on feature/tsk-013.4-ruff-cleanup (currently on $currentBranch)"
    exit 1
}

# 2. Verify branch is in sync with origin
Write-Host "[2/5] Verifying branch sync..." -ForegroundColor Cyan
$remoteRef = git ls-remote origin feature/tsk-013.4-ruff-cleanup
if ($LASTEXITCODE -ne 0 -or -not $remoteRef) {
    Write-Error "Remote branch origin/feature/tsk-013.4-ruff-cleanup does not exist. Push first: git push --force-with-lease origin feature/tsk-013.4-ruff-cleanup"
    exit 1
}
$localSha = git rev-parse HEAD
$remoteSha = ($remoteRef -split "`t")[0]
if ($localSha -ne $remoteSha) {
    Write-Warning "Local HEAD ($localSha) != origin ($remoteSha). Push before opening PR."
    exit 1
}
Write-Host "Branch in sync at $localSha" -ForegroundColor Green

# 3. Check if PR already exists
Write-Host "[3/5] Checking for existing PR..." -ForegroundColor Cyan
# Force array with @() because ConvertFrom-Json returns PSCustomObject (not array) for single-element JSON
$existingPr = @((gh pr list --head feature/tsk-013.4-ruff-cleanup --base main --state all --json number,url,state 2>&1 | ConvertFrom-Json))
if ($existingPr.Count -gt 0) {
    $pr = $existingPr[0]
    Write-Host "PR already exists: $($pr.url) (state: $($pr.state))" -ForegroundColor Yellow
    exit 0
}

# 3b. Ensure required labels exist (idempotent)
Write-Host "[3b/5] Ensuring required labels exist..." -ForegroundColor Cyan
foreach ($label in @("chore", "lint", "hygiene")) {
    # Use --force: idempotent create-or-update since gh 2.0 (avoids exit code handling for "already exists")
    gh label create $label --force --color "cfd8dc" --description "Auto-created by open-pr-tsk-013.4.ps1" 2>&1 | Out-Null
    if ($LASTEXITCODE -ne 0) {
        Write-Warning "Could not ensure label '$label' exists (exit $LASTEXITCODE). PR may lack this label."
    }
}

# 4. Open PR with conventional body
Write-Host "[4/5] Opening PR..." -ForegroundColor Cyan

$prBody = @"
## Resumen

TSK-013.4 cierra el backfill de hygiene pendiente sobre `main`: 29 archivos con format drift + 84 errores de ruff check (F401 unused imports, I001 import sort, N803 naming convention, W291 trailing whitespace) que bloqueaban universalmente cualquier PR subsiguiente de TSK-013.x, TSK-104+, TSK-200+, etc. porque el CI gate `ruff format --check` + `ruff check` fallaba en first push.

## Tipo de cambio

- [x] **Hygiene / lint** (sin logica de negocio)

## Ticket

- **TSK-013.4** (backfill de los 14 ruff format + 47 ruff errors reportados por el sweep TSK-013.3 round-1 code-reviewer; ground-truth re-run confirmo 29 format + 84 check errors en 27 archivos unicos).

## Riesgo

**L** (Bajo). El commit es cherry-pick safe: zero logica de negocio tocada, solo estilo (whitespace, line wrapping, import sort) + auto-fix de F401/I001 + 5 correcciones manuales cosmeticas (dash, regex prefix, variable rename anti-shadow en tests).

## Quality gates

- [x] `uv run ruff format --check .` -> rc=0 (74 files formatted, 0 issues)
- [x] `uv run ruff check .` -> "All checks passed!" (1 non-critical warning sobre `# noqa` format en `src/trading_bot/scanner/filters.py:249` que ya existia pre-backfill)
- [x] `uv run mypy src/trading_bot` -> clean (per retrieval-log [2026-07-09 10:30])
- [x] `uv run pytest tests/unit/indicators -q` -> 42/42 passed (per validation step de retrieval-log [2026-07-09 10:30])
- [x] Cherry-pick safety verificada: 32 files changed, 323 insertions, 389 deletions, 100% style/imports/correcciones cosmeticas
- [x] Sin secrets, sin logica de negocio, sin cambios en contratos publicos

## Cross-links

- **TSK-013.3** (sweep feature-complete, descubrio el patron): parent ticket que origino el deferred scope.
- **ADR-0012** (gate-recovery precedent): analogamente al coverage gate que fallo en main antes de ser ADR-firmado, el ruff gate tiene el mismo tratamiento.
- **ADR-0016** (baseline health umbrella): 10 issues pre-existentes en main @ 2774021; TSK-013.4 resuelve los 2 de hygiene (lint) que estaban en el umbrella.
- **TSK-013.5..013.9** (5 tickets atomicos sobre los 8 issues restantes del umbrella ADR-0016): independientes de TSK-013.4; pueden mergear en paralelo tras este backfill.
- **TSK-200..204** (Fase 2 indicators): desbloqueados para PR limpio una vez TSK-013.4 mergee.
- **Retrieval-log**: `[2026-07-09 10:30]` (validation + rebase + push entry, esta conversacion).

## Plan de ejecucion (per backlog TSK-013.4 / TSK-111)

3 commits atomicos segun el plan de ejecucion del backlog:

1. `chore(lint): ruff format . auto-fix (29 files)` — formato
2. `chore(lint): ruff check --fix . (F401 + I001)` — imports no usados y sort
3. `chore(lint): N803 manual fixes + cosmetic dash/regex/shadow` — 5 fixes manuales

(El commit actual los consolida en uno solo `chore(lint): TSK-013.4 ruff backfill on main` para minimizar churn; el reviewer puede pedir split si lo desea.)

## Sign-off table

- [ ] **context-engineer** — verificado cherry-pick safety + cross-link retrieval-log
- [ ] **strategy-team** — sin impacto en strategy code
- [ ] **security-team** — sin secrets, sin cambios de permisos

## Procedimiento de merge

1. Esperar CODEOWNERS review (paths sensibles: `config/`, `risk/`, `execution/`, `secrets/`, `workflows/` no son tocados; el backfill se concentra en `src/trading_bot/{market_data,scanner,storage,execution,app}.py` + `tests/{unit,bdd}/`)
2. Confirmar 6 quality gates verdes per `docs/ci.md seccion 3`
3. Squash-merge con conventional message + `--delete-branch`
4. Tras merge, el branch `feature/tsk-013.4-ruff-cleanup` se borra automaticamente per branch-protection rules
"@

gh pr create `
    --base main `
    --head feature/tsk-013.4-ruff-cleanup `
    --title "chore(lint): TSK-013.4 ruff backfill on main (29 format + 84 check errors)" `
    --body $prBody `
    --label "chore" `
    --label "lint" `
    --label "hygiene" `
    --reviewer "Extr3sao/maintainers"

# 5. Summary
Write-Host "[5/5] Done!" -ForegroundColor Green
$prUrl = gh pr view --json url -q ".url"
Write-Host "PR opened: $prUrl" -ForegroundColor Green
Write-Host "Next: wait for CODEOWNERS review, then squash-merge per branch-protection rules." -ForegroundColor Cyan
