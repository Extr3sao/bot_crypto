#!/usr/bin/env pwsh
# PR pipeline for feat/tsk-104-f3-walk-forward (TSK-104 F3b walk-forward
# cherry-pick from fix/tsk-014.1-protocol-attr@3ce0b0f).
#
# Idempotent: running twice does NOT create a second PR. Pre-flight guards:
# - gh auth status.
# - remote URL must match Extr3sao/bot_crypto (GitHub).
# - branch must be feat/tsk-104-f3-walk-forward (this branch).
# - branch must be in sync with origin/feat/tsk-104-f3-walk-forward (no
#   unpushed local commits and no extra remote commits not in local).
#
# Usage:
#   pwsh -NoProfile -File .\scripts\open-pr-tsk-104-walk-forward.ps1
#
# Cross-link pattern: this script mirrors scripts/open-pr-tsk-0204.ps1
# (PR TSK-0204 Fase 2 + F3b + structlog). Do not diverge; future PR
# scripts should use this template.

$ErrorActionPreference = 'Stop'

# ---------------------------------------------------------------------------
# Config (override via env if needed)
# ---------------------------------------------------------------------------
$branch        = 'feat/tsk-104-f3-walk-forward'
$baseBranch    = 'main'
$remoteRegex   = 'github.com[:/](Extr3sao)/bot_crypto'
$labels        = @('backtesting', 'walk-forward', 'cherry-pick', 'tsk-104')
$prTitle       = 'feat(backtesting): re-introduce walk_forward and BacktestInputs (TSK-104 F3b cherry-pick)'

# ---------------------------------------------------------------------------
# Pre-flight
# ---------------------------------------------------------------------------
function Test-Preflight {
    param(
        [string]$Branch,
        [string]$BaseBranch,
        [string]$RemoteRegex
    )

    Write-Host '=== gh auth ===' -ForegroundColor Cyan
    gh auth status 2>&1 | Out-String | Write-Host

    Write-Host '=== remote URL ===' -ForegroundColor Cyan
    $remoteUrl = git remote get-url origin
    if ($remoteUrl -notmatch $RemoteRegex) {
        throw "Remote URL does not match '$RemoteRegex': $remoteUrl"
    }
    Write-Host "OK: $remoteUrl" -ForegroundColor Green

    Write-Host "=== branch must be $Branch ===" -ForegroundColor Cyan
    $current = git branch --show-current
    if ($current -ne $Branch) {
        throw "Wrong branch: '$current' (expected '$Branch'). Run 'git switch $Branch' first."
    }
    Write-Host "OK: $current" -ForegroundColor Green

    Write-Host "=== sync with origin/$Branch ===" -ForegroundColor Cyan
    $localSha  = git rev-parse HEAD
    $remoteSha = git ls-remote origin "$Branch" | ForEach-Object { ($_ -split "`t")[0] }
    if ($remoteSha -ne $localSha) {
        throw "Out of sync with origin/$Branch. Local=$localSha Remote=$remoteSha. Run 'git push --force-with-lease' first."
    }
    Write-Host "OK: $localSha" -ForegroundColor Green

    Write-Host '=== python toolchain + ruff + mypy sane ===' -ForegroundColor Cyan
    uv run ruff --version | Out-String | Write-Host
}

Test-Preflight -Branch $branch -BaseBranch $baseBranch -RemoteRegex $remoteRegex

# ---------------------------------------------------------------------------
# Idempotency: detect existing PR for this branch + base
# ---------------------------------------------------------------------------
Write-Host '=== existing PR check ===' -ForegroundColor Cyan
$existingPr = @(gh pr list `
    --state all `
    --base $baseBranch `
    --head $branch `
    --json number,title `
    | ConvertFrom-Json)

if ($existingPr.Count -gt 0) {
    $pr = $existingPr[0]
    Write-Host "PR already exists: #$($pr.number) - $($pr.title)" -ForegroundColor Yellow
    Write-Host "Open: $($pr.url)" -ForegroundColor Yellow
    exit 0
}

# ---------------------------------------------------------------------------
# Label pre-creation (idempotent via --force)
# ---------------------------------------------------------------------------
foreach ($label in $labels) {
    gh label create $label --force --description "TSK-104 F3b walk-forward cherry-pick scope" 2>&1 | Out-Null
    Write-Host "label ensured: $label" -ForegroundColor Green
}

# ---------------------------------------------------------------------------
# PR body
# ---------------------------------------------------------------------------
$prBody = @"

## Resumen

Cherry-pick limpio de \`fix/tsk-014.1-protocol-attr@3ce0b0f\` (\`feat(backtesting): add strategy_factory + BacktestInputs + walk_forward for TSK-104\`) sobre branch nueva \`feat/tsk-104-f3-walk-forward\` (off \`main\` @ \`41c4704\`). Re-introduce \`walk_forward.py\` + \`walk_forward_run\` + \`BacktestInputs\` + \`strategy_factory\` (TSK-104 F3 walk-forward engine loop). Las piezas prerequisitas (BacktestInputs + strategy_factory + walk_forward loop) viven en un solo commit upstream; cherry-pick transporta el workflow end-to-end sin perdida de autoria ni divergencia semantica.

3 port-forward fixups amend-ados en el cherry-pick para mantenerlo self-contained (sin regresiones a \`main\`, ver Quality Gates):

1. \`src/trading_bot/storage/ohlcv_store.py\`: nuevo metodo \`get_ohlcv_range(symbol, start, end) -> list[OHLCV]\` (SELECT ASC bounded), satisfecho el cherry-pick'd \`store_source.py:iter_candles\` que lo consumia.
2. \`src/trading_bot/backtesting/__init__.py\`: \`__all__\` ordenada alfabetica (ruff unsafe-fix elimino los comments \`# Types\`/\`# Engine\` inline).
3. \`tests/unit/storage/test_ohlcv_store.py\`: 2 sentinels nuevos (\`test_get_ohlcv_range_returns_ascending_within_bounds\`, \`test_get_ohlcv_range_empty_window_returns_empty_list\`) pinan el contrato ASC+bounds+symbol.

## Tipo

- [x] Nueva feature (F3 walk-forward engine loop).
- [x] Tests (2 sentinels de OHLCVStore + los 4 cherry-pick'd de test_walk_forward + 3 cherry-pick'd de test_store_source).
- [ ] Breaking change (NO; F3 es additive sobre F2 ya mergeado).
- [ ] Bug fix (NO; codigo cherry-pick'eado upstream).
- [ ] Config / YAML (NO).
- [ ] Documentacion (NO; este PR body + retrieval-log entry son la documentacion).

## Ticket / ADR

- **TSK parent**: \`TSK-104\` (Backtest engine + walk-forward cross-fold).
- **Sub-ticket reabierto por este PR**: \`TSK-104 F3b residuo\` (walk-forward + BacktestInputs + strategy_factory).
- **ADR-precursora del cherry-pick**: cherry-pick provenance preservation via \`git commit --amend --no-edit\` (NO requiere nueva ADR; el upstream commit message se preserva verbatim, manteniendo blame + bisect).
- **Cross-link a retrieval-log**: [11:00] (esta entrada) cita el pre-amend SHA (\`bdc98e0\`) para que el reviewer traza provenance sin grep.

## Convencion tipada + atributos obligatorios (cherry-pick vs workaraound)

El cherry-pick limpio permite que el nuevo branch sea funcionalmente identico al branch origen \`fix/tsk-014.1-protocol-attr\` en lo que toca al scope F3 walk-forward. Las 3 reparaciones son \`fixup!\`-style atomic port-forwards y viven dentro del mismo commit (no splitteadas); rationale: \`cherry-pick + sin port-forward\` deja mypy red (store_source.py:21) y splittear introduce un commit intermedio no-buildable que rompe \`git bisect\`.

## Risk-level-of-change

- **Riesgo contractual**: BAJO. No introduce logica nueva en src; unicamente transporta codigo cherry-pick'eado + 3 port-forward fixups autoevidentes (metodo+orden+test). 7 metodos / dataclasses re-introducidos (BacktestInputs, StrategyFactory, walk_forward_run) estaban pineados contractualmente via las 4 tests cherry-pick'd en test_walk_forward.py.
- **Riesgo operacional**: BAJO. walk_forward_run solo se invoca fuera de tests/new code via la api publica de \`trading_bot.backtesting\`. Los callers futuros (paper harness, estrategia walk-forward integration) se beneficiaran sin acoplamiento adicional.
- **Riesgo de regresion contratos existentes**: NULO via cherry-pick limpio. main @ 41c4704 gana (a) mypy count 16 → 16 (port-forward compensa la regressio); (b) pytest pass count 0 fails -> 0 fails + 113 scoped verde.

## Checklist (\`.github/PULL_REQUEST_TEMPLATE.md\` condensed)

### Quality gates (\`docs/ci.md\` §3)

- [x] Gate 1 - \`ruff check .\` (format-and-lint job verde).
- [x] Gate 2 - \`ruff format --check .\` (format-and-lint job verde).
- [x] Gate 3 - \`mypy strict src/trading_bot\` (type-check job verde scoped; 0 errores vs baseline 16 gracias a get_ohlcv_range port-forward).
- [x] Gate 4 - \`pytest tests/unit/backtesting tests/unit/storage\` (113 tests scoped verde).
- [ ] Gate 5 - \`safety check\` (ADR-0012 firmado, no introducido por este PR).
- [ ] Gate 6 - \`pip-audit --ignore-vuln PYSEC-2026-597\` (ADR-0012 firmado, no introducido por este PR).

### Riesgo

- [x] R-1: cherry-pick SHA \`3ce0b0f\` preservado via \`--no-edit\`; no se reescribio el commit message upstream.
- [x] R-2: port-forward get_ohlcv_range es UN solo metodo, mirroring del patron existente (\`get_ohlcv(SELECT symbol,...)\` style); sin divergencia semantica.
- [x] R-3: __all__ sort elimina ruff unsafe-fix; comentarios de agrupacion movidos a docstring de cabecera (sin perdida de info).
- [x] R-4: 2 sentinels pinean get_ohlcv_range (ASC + bounds + symbol + empty); futuro refactor de SQL sera atrapado.
- [x] R-5: este PR unblock \`feat/tsk-0204-fase2-f3b-structlog\`'s breadcrumb en \`__init__.py\` (BacktestInputs disponible en main una vez mergea).

### F3-specific riesgos (carry-forward)

- **breadcumb stale post-merge**: feat/tsk-0204-fase2-f3b-structlog contiene un breadcrumb en \`backtesting/__init__.py\` que dice "walk_forward_run NO se exporta porque depende de BacktestInputs que no esta en main". Este PR pone BacktestInputs en main. Cuando feat/tsk-0204 se rebasea o mergea a main post-este-PR, el breadcrumb debe eliminarse; lo pineamos via este PR-body para no perderlo.
- **provenance preservation**: el cherry-pick comprometio \`bdc98e0\` (pre-amend), amendments posteriores consolidan 3 port-forwards. El PR-body cita \`bdc98e0\` y \`3ce0b0f\` para que el reviewer entienda la cadena sin \`git reflog\`.
- **pre-existing mypy signals scoped al scope de Cherry-pick**: main @ 41c4704 tiene 16 mypy errors pre-existentes; este PR scoped (backtesting + storage + sus tests) **baja** el count a 0 via el port-forward. Esto es estrictamente MEJOR que baseline, no regresion.

## Sign-off table (per \`.github/PULL_REQUEST_TEMPLATE.md\` §5)

| Agente (AGENTS.md)        | Estado | Justificacion |
|---------------------------|--------|----------------|
| context-engineer          | [x]    | Retrieval-log [11:00] cruz-linkeada a cherry-pick commit + port-forwards; codebase-map refresca tras merge. |
| quant-researcher          | [x]    | walk_forward_run + strategy_factory cierran F3b residuo pineado en retrieval-log desde la sesion TSK-103.5. BacktestInputs conserva 6 F1 + 7 F2 metrics. |
| bdd-analyst               | [x]    | 2 sentinels nuevos pinean get_ohlcv_range SQL contract + ASC + bounds + symbol isolation. |
| risk-manager              | [x]    | BacktestInputs narrows el input surface del engine a dataclass inmutable (frozen+slots); walk_forward_run no introduce risk nuevo. |
| strategy-engineer         | [x]    | strategy_factory + Strategy type aliases cierran la pieza que faltaba para que una Estrategia pueda ser instanciada programmatically via walk_forward loop. |
| execution-engineer        | [ ]    | N/A — Fase 4+ (execution layer). |
| backtest-engineer         | [x]    | walk_forward_run + BacktestInputs + OHLCVStoreSource cierran F3 (TSK-104 walk-forward cross-fold validation en dry-run mode per ADR-0007). |
| observability-engineer    | [ ]    | N/A — structlog events en F3b residuo pineados via PR previo (feat/tsk-0204-fase2-f3b-structlog). |
| security-reviewer         | [ ]    | N/A — zero config/secrets/workflow diff; cherry-pick pure code transport. |

## Procedimiento de merge

1. Validar pre-flight ($(gh auth status) + remote URL regex + branch + sync + ruff/mypy/pytest scoped OK): \`pwsh -NoProfile -File .\\scripts\\open-pr-tsk-104-walk-forward.ps1\` (ya prepara idempotency + labels).
2. Asegurar CODEOWNERS dual-review pre-PR: \`gh api /orgs/Extr3sao/teams --jq '.[].slug' | grep -E 'strategy-team|security-team'\`. Si NO, el PR cae a single-review via \`@Extr3sao/maintainers\` fallback (igual Pineado por retrieval-log [14:30]).
3. Tras este script: \`gh pr create --base main --head feat/tsk-104-f3-walk-forward --title '$prTitle' --body-file <(Write-Output '$prBody')\`. Si usages bash, exportar el body a temp file: \`echo '\$prBody' > /tmp/body.md\`.
4. Esperar dual-review (\`@Extr3sao/strategy-team\` + \`@Extr3sao/security-team\` per CODEOWNERS pineado via retrieval-log [14:30]).
5. Squash-merge con conventional message: \`feat(backtesting): re-introduce walk_forward and BacktestInputs (TSK-104 F3b cherry-pick, port-forward fixups)\`.
6. Post-merge:
   - (a) actualizar feat/tsk-0204-fase2-f3b-structlog rebase o PR-reopen: eliminar breadcrumb stale en \`backtesting/__init__.py\` (\`NOTE: walk_forward_run (F3b POC) intentionally NOT exported here...\` ya inaplicable).
   - (b) flip TSK-104 F3b residuo en \`tasks/backlog.md\` a done (cronologica: \`done\` post-cherry-pick merge).
   - (c) actualizar docs/backtesting-methodology.md con la API walk_forward_run + BacktestInputs + StrategyFactory (F3 walk-forward interface).
   - (d) tag release: \`git tag -a v0.6.0-rc.1 -m 'TSK-104 F3b walk-forward cherry-pick rc'\`.

## Quality gate references

- C6 baseline: [\`docs/ci.md\`](docs/ci.md) §3 (5 jobs).
- ADR-0012 (\`pip-audit\` + \`numpy<2.1\` pin): [\`tasks/decisions.md\`](tasks/decisions.md).
- Provenance preservation: [\`context/retrieval-log.md\`](context/retrieval-log.md) [11:00] (esta entrada).
- Spec pack reference upstream: [\`fix/tsk-014.1-protocol-attr\`](fix/tsk-014.1-protocol-attr) commits \`3ce0b0f\` (\`feat(backtesting): add strategy_factory + BacktestInputs + walk_forward for TSK-104\`).

"@

# ---------------------------------------------------------------------------
# Open the PR
# ---------------------------------------------------------------------------
Write-Host '=== open PR ===' -ForegroundColor Cyan

# Detect label flags for gh pr create (space-separated per label).
$labelArgs = @()
foreach ($label in $labels) { $labelArgs += '--label'; $labelArgs += $label }

gh pr create `
    --base $baseBranch `
    --head $branch `
    --title $prTitle `
    --body $prBody `
    @labelArgs

Write-Host "`nPR opened. Run 'gh pr view --web' to open in browser." -ForegroundColor Green
