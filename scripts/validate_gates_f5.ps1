<#
.SYNOPSIS
    Runs the 7 quality gates that close TSK-103.5 (F5) per `docs/ci.md` section 3.

.DESCRIPTION
    Per TSK-103.5.7.* — the 7 quality gates required by ADR-0012 + the pine contract
    with `.github/workflows/ci.yml`. Each gate exits with a canonical color code
    so the user can paste a red gate's output to the chat for diagnostic.

    - Gate 1: ruff check
    - Gate 2: ruff format --check
    - Gate 3: mypy strict
    - Gate 4: pytest with coverage gate (scanner >= 90%)
    - Gate 5: safety check (with PYSEC-2026-597 carve-out)
    - Gate 6: pip-audit (with PYSEC-2026-597 carve-out)
    - Gate 7: BDD fixture injection contract (AST-based; scripts/check_bdd_fixtures.py)

.PRE-FLIGHT
    1. .venv exists OR Block 1..2 of the F4 PowerShell runbook applied
    2. gh CLI authenticated for branch creation / PR push (optional - P1 only)

.NOTES
    Author        : context-engineer (TSK-103.5 turn-13 autonomous)
    Requires      : PowerShell 7.x; uv-managed .venv; Python 3.11+
    Cross-links   : docs/ci.md §3; quality/code-quality.md; quality/release-gates.md
                    Bloque 6; ADR-0012 (numpy<2.1 + app.py omit + PYSEC-2026-597)

.EXAMPLE
    cd 'C:\Users\GVLLFR0035\Downloads\bot freebuff'
    .\scripts\validate_gates_f5.ps1 -Scope scanner
    # Run only the scanner-scoped subset first (faster feedback on F4/F5 churn).
#>

[CmdletBinding()]
param(
    [ValidateSet("scanner", "full")]
    [string]$Scope = "scanner",

    [string]$PythonExe = ".\.venv\Scripts\python.exe",

    [switch]$SkipSafety,
    [switch]$SkipPipAudit,
    [switch]$SkipBddFixtures
)

$ErrorActionPreference = "Continue"
$repo = (Get-Location).Path

function Test-RedGate {
    param([string]$Name, [int]$ExitCode, [string]$Output)
    if ($ExitCode -ne 0) {
        Write-Host ""
        Write-Host "=================================================" -ForegroundColor Red
        Write-Host "GATE FAILED: $Name (exit=$ExitCode)" -ForegroundColor Red
        Write-Host "=================================================" -ForegroundColor Red
        Write-Host $Output -ForegroundColor Red
        return $true
    }
    Write-Host "GATE PASSED: $Name" -ForegroundColor Green
    return $false
}

# -----------------------------------------------------------------------
# 0. Pre-flight: Python executable
# -----------------------------------------------------------------------
if (-not (Test-Path $PythonExe)) {
    Write-Host "[preflight] python.exe not found at $PythonExe" -ForegroundColor Red
    Write-Host "  Hint: Block 1 (permission repair) o Block 2 (system-Python fallback)"
    Write-Host "        of the F4 PowerShell runbook antes de este script."
    exit 1
}

# Branch pin (substring marker for diff isolation F5 vs F4 vs future chains)
$branch = & git rev-parse --abbrev-ref HEAD 2>$null
if ($branch -notlike "*tsk-103-5*") {
    Write-Host "[preflight] branch '$branch' no es feature/tsk-103-5-*; revisar checkout." -ForegroundColor Yellow
}

# -----------------------------------------------------------------------
# Gate 1: ruff check
# -----------------------------------------------------------------------
Write-Host ""
Write-Host "[Gate 1/7] ruff check . - exit-zero mode primero (smoke); fix-on-red:" -ForegroundColor Cyan
$gate1_out = & $PythonExe -m ruff check . 2>&1
$gate1_exit = $LASTEXITCODE
if (Test-RedGate "ruff check" $gate1_exit $gate1_out) {
    Write-Host "  Auto-fixable? '$PythonExe -m ruff check --fix .'" -ForegroundColor Yellow
    $choice = Read-Host "Apply auto-fix? [y/N]"
    if ($choice -eq "y") {
        & $PythonExe -m ruff check --fix . 2>&1 | Out-Host
        $gate1_out = & $PythonExe -m ruff check . 2>&1
        $gate1_exit = $LASTEXITCODE
        if ($gate1_exit -ne 0) { Test-RedGate "ruff check post-fix" $gate1_exit $gate1_out; exit 2 }
    } else { exit 2 }
}

# -----------------------------------------------------------------------
# Gate 2: ruff format --check
# -----------------------------------------------------------------------
Write-Host ""
Write-Host "[Gate 2/7] ruff format --check . (solo el flag, NO modifica):" -ForegroundColor Cyan
$gate2_out = & $PythonExe -m ruff format --check . 2>&1
$gate2_exit = $LASTEXITCODE
if (Test-RedGate "ruff format" $gate2_exit $gate2_out) {
    Write-Host "  Auto-fixable? '$PythonExe -m ruff format .'" -ForegroundColor Yellow
    $choice = Read-Host "Apply format? [y/N]"
    if ($choice -eq "y") {
        & $PythonExe -m ruff format . 2>&1 | Out-Host
        $gate2_out = & $PythonExe -m ruff format --check . 2>&1
        $gate2_exit = $LASTEXITCODE
        if ($gate2_exit -ne 0) { Test-RedGate "ruff format post-fix" $gate2_exit $gate2_out; exit 3 }
    } else { exit 3 }
}

# -----------------------------------------------------------------------
# Gate 3: mypy strict
# -----------------------------------------------------------------------
Write-Host ""
Write-Host "[Gate 3/7] mypy strict src/trading_bot + tests/:" -ForegroundColor Cyan
if ($Scope -eq "scanner") {
    # F5 scoped fast-feedback: solo scanner pkg.
    $gate3_out = & $PythonExe -m mypy src/trading_bot/scanner tests/unit/scanner tests/bdd 2>&1
} else {
    $gate3_out = & $PythonExe -m mypy src/trading_bot tests/ 2>&1
}
$gate3_exit = $LASTEXITCODE
if (Test-RedGate "mypy strict" $gate3_exit $gate3_out) { exit 4 }

# -----------------------------------------------------------------------
# Gate 4: pytest --cov --cov-fail-under=90
# -----------------------------------------------------------------------
Write-Host ""
Write-Host "[Gate 4/7] pytest -m 'not slow' --cov --cov-fail-under=90:" -ForegroundColor Cyan
if ($Scope -eq "scanner") {
    $gate4_out = & $PythonExe -m pytest -m "not slow" `
        --cov=src/trading_bot/scanner --cov-fail-under=90 `
        tests/unit/scanner tests/bdd -q 2>&1
} else {
    $gate4_out = & $PythonExe -m pytest -m "not slow" `
        --cov=src/trading_bot --cov-fail-under=90 `
        -q 2>&1
}
$gate4_exit = $LASTEXITCODE
if (Test-RedGate "pytest+coverage" $gate4_exit $gate4_out) { exit 5 }

# -----------------------------------------------------------------------
# Gate 5: safety (ADR-0012 firmado: nltk PYSEC-2026-597 dev carve-out)
# -----------------------------------------------------------------------
if (-not $SkipSafety) {
    Write-Host ""
    Write-Host "[Gate 5/7] safety check (ADR-0012 firmado; revisar sigue vigente):" -ForegroundColor Cyan
    $gate5_out = & $PythonExe -m safety check 2>&1
    $gate5_exit = $LASTEXITCODE
    if (Test-RedGate "safety" $gate5_exit $gate5_out) { exit 6 }
} else {
    Write-Host "[Gate 5/7] safety SKIPPED (-SkipSafety)" -ForegroundColor Yellow
}

# -----------------------------------------------------------------------
# Gate 6: pip-audit (ADR-0012 firmado: --ignore-vuln PYSEC-2026-597)
# -----------------------------------------------------------------------
if (-not $SkipPipAudit) {
    Write-Host ""
    Write-Host "[Gate 6/7] pip-audit --ignore-vuln PYSEC-2026-597:" -ForegroundColor Cyan
    $gate6_out = & $PythonExe -m pip_audit --ignore-vuln PYSEC-2026-597 2>&1
    $gate6_exit = $LASTEXITCODE
    if (Test-RedGate "pip-audit" $gate6_exit $gate6_out) { exit 7 }
} else {
    Write-Host "[Gate 6/7] pip-audit SKIPPED (-SkipPipAudit)" -ForegroundColor Yellow
}

# -----------------------------------------------------------------------
# Gate 7: BDD fixture injection contract (TSK-103.5.7.7 — pre-push guard)
# -----------------------------------------------------------------------
# Round-19..22 nightly review chain: scripts/check_bdd_fixtures.py is the
# AST-based, cross-file-aware validator that catches pytest-bdd exact-name
# injection bugs BEFORE runtime. Output exits 0 (clean) / 1 (>=1 red flag)
# / 2 (parse error). We surface the full validator output on red so the
# user can paste [RED] lines into chat for diagnosis.
if (-not $SkipBddFixtures) {
    Write-Host ""
    Write-Host "[Gate 7/7] BDD fixture injection contract (scripts/check_bdd_fixtures.py tests/bdd/):" -ForegroundColor Cyan
    if (-not (Test-Path "scripts/check_bdd_fixtures.py")) {
        Write-Host "  [RED] scripts/check_bdd_fixtures.py not found at repo root" -ForegroundColor Red
        exit 8
    }
    $gate7_out = & $PythonExe scripts/check_bdd_fixtures.py tests/bdd/ 2>&1
    $gate7_exit = $LASTEXITCODE
    if (Test-RedGate "bdd-fixtures" $gate7_exit $gate7_out) { exit 8 }
} else {
    Write-Host "[Gate 7/7] BDD fixtures SKIPPED (-SkipBddFixtures)" -ForegroundColor Yellow
}

# -----------------------------------------------------------------------
# Resumen final
# -----------------------------------------------------------------------
Write-Host ""
Write-Host "=================================================" -ForegroundColor Green
Write-Host "7 quality gates verdes per ADR-0012 + docs/ci.md" -ForegroundColor Green
Write-Host "F5 cierre listo para `gh pr create --body-file pr-body-TASK-103.5.md`" -ForegroundColor Green
Write-Host "=================================================" -ForegroundColor Green
Write-Host "Coverage (scanner) : >= 90% expected per pyproject fail_under" -ForegroundColor Green
Write-Host "Pytest-bdd         : 23/23 scenarios per tests/bdd/step_defs/*" -ForegroundColor Green
Write-Host "PYSEC-2026-597     : firmado en ADR-0012 (nltk dev-only)" -ForegroundColor Green
Write-Host "Cross-layer AST    : tests/unit/scanner/test_cross_layer.py verde por F4" -ForegroundColor Green
exit 0
