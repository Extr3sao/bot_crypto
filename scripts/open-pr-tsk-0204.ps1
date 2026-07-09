#!/usr/bin/env pwsh
# open-pr-tsk-0204.ps1
# Opens the GitHub PR for branch feat/tsk-0204-fase2-f3b-structlog.
# Idempotent: re-running after a PR is already open will exit cleanly.
# Cross-links: TSK-200..204 indicators + TSK-104 F3b residuo + TSK-105 PineStructlog.
# ADRs cited: ADR-0017 (branch-protection auth-gated), ADR-0018 (F3 mirror contract).
#
# Compatible with both Windows PowerShell 5.1 (`powershell.exe`) and
# PowerShell 7+ (`pwsh`):
#   - Uses literal here-strings `@'...'@` for the PR body (no interpolation,
#     avoids PS5.1 parser issues with `"@` terminator detection).
#   - Uses `-f` format-string for the line-50 message (avoids PS5.1 parser
#     confusion with `$branch:` scope-qualified variable interpretation
#     inside an interpolated double-quoted string).

$ErrorActionPreference = 'Stop'

# --- pre-flight ---
Write-Host "=== pre-flight ===" -ForegroundColor Cyan

$ghAuth = gh auth status 2>&1
if ($LASTEXITCODE -ne 0) {
    Write-Host "gh CLI not authenticated. Run: gh auth login" -ForegroundColor Red
    exit 1
}

$remoteUrl = git remote get-url origin
if ($remoteUrl -notmatch 'github\.com[:/](Extr3sao)/bot_crypto') {
    Write-Host "remote 'origin' is not github.com/Extr3sao/bot_crypto. aborting. got: $remoteUrl" -ForegroundColor Red
    exit 1
}
Write-Host "remote OK: $remoteUrl"

$branch = 'feat/tsk-0204-fase2-f3b-structlog'
$currentBranch = git branch --show-current
if ($currentBranch -ne $branch) {
    Write-Host "not on $branch. current: $currentBranch. run: git switch $branch" -ForegroundColor Red
    exit 1
}
Write-Host "branch OK: $currentBranch"

$localSha = git rev-parse HEAD
$remoteSha = git ls-remote origin $branch 2>&1 | ForEach-Object { ($_ -split "`t")[0] }
if (-not $remoteSha) {
    Write-Host "remote branch $branch missing. push first: git push --force-with-lease origin $branch" -ForegroundColor Red
    exit 1
}
if ($localSha -ne $remoteSha) {
    Write-Host "local HEAD ($localSha) does not match remote ($remoteSha). sync first." -ForegroundColor Red
    exit 1
}
Write-Host "branch in sync: $localSha"

# --- idempotency ---
Write-Host "=== idempotency check ===" -ForegroundColor Cyan
$existingPr = @(gh pr list --head $branch --base main --state all --json number,title 2>&1 | ConvertFrom-Json)
if ($existingPr.Count -gt 0) {
    # PS5.1-safe: format string with -f avoids the `$branch:` scope-qualified
    # variable interpretation that PS5.1 mistakes inside interpolated strings.
    Write-Host ("PR already exists for {0}: #{1} -- {2}" -f $branch, $existingPr[0].number, $existingPr[0].title) -ForegroundColor Yellow
    Write-Host "no-op. run 'gh pr view --web' to inspect." -ForegroundColor Yellow
    exit 0
}

# --- label pre-creation (idempotent via --force) ---
Write-Host "=== label pre-create ===" -ForegroundColor Cyan
$labels = @(
    @{ name = 'feat';       color = '0e8a16'; description = 'New feature implementation' },
    @{ name = 'indicators'; color = '1d76db'; description = 'Fase 2 indicators work' },
    @{ name = 'backtesting';color = '5319e7'; description = 'TSK-104 backtest engine scope' },
    @{ name = 'paper';      color = 'b60205'; description = 'TSK-105 paper trading scope' },
    @{ name = 'ledger';     color = 'fbca04'; description = 'Decisions/ADR/retrieval-log sync' }
)
foreach ($l in $labels) {
    gh label create $l.name --color $l.color --description $l.description --force 2>&1 | Out-Null
    if ($LASTEXITCODE -ne 0 -and $LASTEXITCODE -ne 2) {
        Write-Host ("label create failed for {0}; continuing" -f $l.name) -ForegroundColor Yellow
    }
}

# --- open PR ---
Write-Host "=== opening PR ===" -ForegroundColor Cyan

# PS5.1-safe: literal here-string @'...'@ (no interpolation). The body is
# pure markdown with no live $variable references; the only $ that may
# appear is literal text inside code blocks describing commands the user
# will run later (e.g. ``git cherry-pick $fix-branch-commit-...`` quoted as
# example prose, NOT something PowerShell should expand). Using @
# avoids the PS5.1 parser misidentifying premature `"@` terminators
# inside the multi-line markdown body.
$prBody = @'
## Resumen

Cierra **Fase 2 Indicators** (TSK-200..204) + **TSK-104 F3b residuo** (cross-fold aggregated reports) + **TSK-105 PineStructlog** (5 structlog events nuevos) + **ledger sync** (ADR-0018 + retrieval-log entries + sprint-003 log updates + TSK-200..204 backlog flips).

## Tipo

- [x] Nueva feature (Fase 2 indicators + PineStructlog event taxonomy + cross-fold aggregate reports)

## Tickets

- **TSK-200** Motor de indicadores (interface `Indicator` Protocol + `IndicatorRegistry` + `IndicatorCache` + tipos frozen)
- **TSK-201** EMA, RSI, MACD, ATR, BollingerBands
- **TSK-202** VWAP, volume_relative, spread, volatilidad, momentum
- **TSK-203** Order book imbalance (feature-flagged)
- **TSK-204** 16 property tests hypothesis con **`@settings(max_examples=1000, deadline=None)`** (F3 mirror contract)
- **TSK-104 F3b residuo** `WalkForwardAggregateReport` con `MetricAggregate` (mean/std/min/max) + `consistency_score` + JSON-serializable payload via recursive `_dataclass_to_dict` (shape-drift proof)
- **TSK-105 PineStructlog** 5 eventos nuevos: `paper.session.started` (bind-once), `paper.scanner.completed`, `paper.broker.reconciled` (solo broker), `paper.report.alerts` (warning, solo si alerts y paper_report=True), `paper.report.written` (info, solo si paper_report=True)

## Riesgo

**M** (medium-multi): 3 paquetes modificados (indicators + backtesting + paper), 18 archivos modificados, 3 commits. Pre-conditions: indicadores deben pasar ruff/mypy/pytest antes de fusionar a main.

## Quality Gates

Per `docs/ci.md sec 3`:

- [x] ruff format --check en `src/trading_bot/indicators` + `backtesting` + `paper`: **clean** (verificado localmente; pre-existing main drift fuera de scope)
- [x] ruff check en los 3 paquetes: **clean** (post-fix via ruff --fix)
- [ ] mypy strict: 16 errores pre-existentes en main @ `41c4704` (no introducidos por este PR; ver pre-existing notes abajo)
- [ ] pytest 3 errores pre-existentes (idem)

### Notas sobre mypy/pytest pre-existentes

Los errores de `mypy` (16) y `pytest` (3 collection errors) son **pre-existentes en `main @ 41c4704`** — verificados via `git checkout main @ 41c4704 && uv run mypy src/trading_bot && uv run pytest --collect-only tests/unit/{indicators,backtesting,paper}`. Este PR no los introduce; son tickets separados (TSK-013.5..013.9 baseline remediation per ADR-0016 umbrella) o residuo de Fase 2 indicator import-resolver que requieren cherry-pick del fix branch `fix/tsk-014.1-protocol-attr` (F3b `BacktestInputs` pre-req).

## Cross-links

- **ADR-0017** (branch-protection auth-gated) — Block P2-Dual per F5 precedent
- **ADR-0018** (TSK-200..204 cierre + F3 mirror contract pineado) — la taxonomía `@settings(max_examples=1000, deadline=None)` es decision arquitectonica transversal
- **`tasks/decisions.md`** ADR-0018 firmada al final de sprint-003
- **`tasks/sprint-003.md`** log entries actualizadas: `[2026-07-08]` governance close-out + `[2026-07-09]` TSK-200..204 cierre
- **`context/retrieval-log.md`** entries `[2026-07-09 09:30]` + `[10:00]` pinean el F3 mirror + estado real
- **`docs/paper-trading-methodology.md`** sincronizada con la nueva taxonomía PineStructlog

## Plan de merge

1. Squash-merge de los 3 commits a `main` con conventional message:
   ```
   feat(Fase 2): TSK-200..204 + TSK-104 F3b residuo + TSK-105 PineStructlog (closes 7+1+1 tickets)
   ```
2. Tag `v0.6.0-rc.1` post-merge per Fase 2 milestone convention
3. CODEOWNERS aplica `strategy-team + security-team` dual-review per Block P2-Dual (ADR-0017 + F5 precedent)
4. Post-merge: cherry-pick de futuros fixes del `fix/tsk-014.1-protocol-attr` branch via `git pull --ff-only`

## Sign-off esperado

| Agente | Required | Status |
| --- | --- | --- |
| context-engineer | yes | pending review |
| quant-researcher | no (no toca estrategia) | n/a |
| strategy-engineer | yes (indicators layer) | pending review |
| execution-engineer | yes (paper harness extension) | pending review |
| risk-manager | no (PineStructlog events no son risk-relevant) | n/a |
| backtest-engineer | yes (F3b cross-fold reports) | pending review |
| observability-engineer | yes (5 nuevos structlog events) | pending review |
| security-reviewer | yes (no new secrets) | pending review |

## Procedimiento

```powershell
# una vez mergeada esta PR:
git switch main
git pull --ff-only
# cherry-pick F3b BacktestInputs from fix/tsk-014.1-protocol-attr:
#   git cherry-pick <fix-branch-commit-with-types.py-BacktestInputs>
#   esto habilitara un PR de seguimiento re-introduciendo walk_forward.py + __init__ removido.
```
'@

gh pr create --base main --head $branch --title "TSK-200..204 + TSK-104 F3b + TSK-105 PineStructlog close" --body $prBody 2>&1

if ($LASTEXITCODE -eq 0) {
    Write-Host "PR opened successfully. inspect with: gh pr view --web" -ForegroundColor Green
} else {
    Write-Host ("PR creation failed (exit {0})" -f $LASTEXITCODE) -ForegroundColor Red
    exit 1
}
